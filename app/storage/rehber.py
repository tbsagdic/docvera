r"""Arsiv kokundeki musteri rehberi (musteriler.json).

Neden ayri bir dosya: SQLite veritabani her bilgisayarda yereldir. Rehber
arsivin *icinde* durdugu icin Drive ile birlikte esitlenir; baska bir
bilgisayardaki Docvera da ayni musteri listesini gorur ve ayni musteriye
ikinci bir kayit acmaz.

Bicim:

    {
      "surum": 1,
      "guncelleme": "2026-08-30T14:32:00",
      "musteriler": {
        "10000000146": {
          "tc": "10000000146",
          "ad": "ALI", "soyad": "OZDEMIR",
          "dogum_tarihi": "1985-03-05",
          "ilk_kayit": "2026-01-02", "son_kayit": "2026-08-30",
          "kayitlar": [
            {"tarih": "2026-01-02",
             "klasor": "2026/01.2026/02.01.26/ALI OZDEMIR 0146",
             "sube": "", "pdf": "ALI OZDEMIR_02.01.2026.pdf", "sayfa_sayisi": 3}
          ]
        }
      }
    }

Musteriler TC'ye gore sozlukte tutulur: ayni musteri kac kez gelirse gelsin
tek girdi olur, gelisleri "kayitlar" listesine eklenir.

Rehber bir dizindir, kaynak degildir: asil veriyi her musteri klasorundeki
meta.json tasir. Dosya bozulur ya da kaybolursa `rehberi_yeniden_uret` ile
arsiv taranarak bastan olusturulabilir.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

from app.storage.writer import META_DOSYASI
from app.validation import tr_lower

log = logging.getLogger(__name__)

REHBER_DOSYASI = "musteriler.json"
REHBER_SURUMU = 1


def rehber_yolu(kok: str | Path) -> Path:
    return Path(kok) / REHBER_DOSYASI


def _simdi() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def bos_rehber() -> dict:
    return {"surum": REHBER_SURUMU, "guncelleme": _simdi(), "musteriler": {}}


def rehber_oku(kok: str | Path) -> dict:
    """Rehberi okur; dosya yoksa ya da bozuksa bos rehber doner.

    Bozuk bir dosya yuzunden kayit alinamamasi kabul edilemez: hata gunluge
    yazilir ve calismaya bos rehberle devam edilir.
    """
    yol = rehber_yolu(kok)
    if not yol.is_file():
        return bos_rehber()
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.error("Musteri rehberi okunamadi (%s): %s", yol, exc)
        return bos_rehber()

    if not isinstance(veri, dict) or not isinstance(veri.get("musteriler"), dict):
        log.error("Musteri rehberi beklenen bicimde degil: %s", yol)
        return bos_rehber()

    veri.setdefault("surum", REHBER_SURUMU)
    veri["musteriler"] = {
        str(tc): _musteriyi_duzelt(str(tc), girdi)
        for tc, girdi in veri["musteriler"].items()
        if isinstance(girdi, dict)
    }
    return veri


def rehber_yaz(kok: str | Path, veri: dict) -> Path:
    """Rehberi diske yazar (once gecici dosyaya, sonra yer degistirerek)."""
    yol = rehber_yolu(kok)
    yol.parent.mkdir(parents=True, exist_ok=True)
    veri["surum"] = REHBER_SURUMU
    veri["guncelleme"] = _simdi()

    gecici = yol.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(yol)
    return yol


def _musteriyi_duzelt(tc: str, girdi: dict) -> dict:
    """Eksik/elle duzenlenmis girdiyi beklenen alanlarla tamamlar."""
    kayitlar = [k for k in girdi.get("kayitlar", []) if isinstance(k, dict)]
    kayitlar.sort(key=lambda k: (str(k.get("tarih", "")), str(k.get("sube") or "")))
    tarihler = [str(k.get("tarih")) for k in kayitlar if k.get("tarih")]
    return {
        "tc": str(girdi.get("tc") or tc),
        "ad": girdi.get("ad", ""),
        "soyad": girdi.get("soyad", ""),
        "dogum_tarihi": girdi.get("dogum_tarihi"),
        "olusturma": girdi.get("olusturma", ""),
        "guncelleme": girdi.get("guncelleme", ""),
        "ilk_kayit": tarihler[0] if tarihler else girdi.get("ilk_kayit"),
        "son_kayit": tarihler[-1] if tarihler else girdi.get("son_kayit"),
        "kayitlar": kayitlar,
    }


def musteri_yaz(
    kok: str | Path,
    tc: str,
    ad: str,
    soyad: str,
    dogum_tarihi: _dt.date | str | None,
    tarih: _dt.date,
    goreli_yol: str,
    sube_kodu: str = "",
    pdf_adi: str | None = None,
    sayfa_sayisi: int = 0,
) -> Path:
    """Musteriyi ve o gunku kaydini rehbere isler.

    Dosya her seferinde yeniden okunup birlestirilerek yazilir; ayni arsivi
    kullanan ikinci bir bilgisayar araya girdiyse onun ekledigi musteriler
    silinmez. Ayni musteri ayni gun tekrar geldiginde yeni satir acilmaz,
    mevcut kaydin sayfa sayisi guncellenir.
    """
    if isinstance(dogum_tarihi, _dt.date):
        dogum_tarihi = dogum_tarihi.isoformat()

    veri = rehber_oku(kok)
    musteri = veri["musteriler"].get(tc) or {
        "tc": tc,
        "olusturma": _simdi(),
        "kayitlar": [],
    }
    musteri.update(
        {
            "tc": tc,
            "ad": ad,
            "soyad": soyad,
            # Kimligi okunamayan yeni bir kayit, daha once girilmis dogum
            # tarihini silmesin
            "dogum_tarihi": dogum_tarihi or musteri.get("dogum_tarihi"),
            "guncelleme": _simdi(),
        }
    )

    yeni = {
        "tarih": tarih.isoformat(),
        "klasor": goreli_yol,
        "sube": sube_kodu,
        "pdf": pdf_adi,
        "sayfa_sayisi": sayfa_sayisi,
    }
    kayitlar = {
        (str(k.get("tarih")), str(k.get("sube") or "")): k
        for k in musteri.get("kayitlar", [])
        if isinstance(k, dict)
    }
    kayitlar[(yeni["tarih"], yeni["sube"])] = yeni
    musteri["kayitlar"] = [kayitlar[anahtar] for anahtar in sorted(kayitlar)]

    veri["musteriler"][tc] = _musteriyi_duzelt(tc, musteri)
    return rehber_yaz(kok, veri)


def musteriler(kok: str | Path) -> list[dict]:
    """Rehberdeki musterileri en son gelenden eskiye dogru dondurur."""
    return sirala(rehber_oku(kok)["musteriler"].values())


def musteri_getir(kok: str | Path, tc: str) -> dict | None:
    return rehber_oku(kok)["musteriler"].get(tc)


def sirala(girdiler) -> list[dict]:
    """En son gelen musteri en ustte; tarihi olmayanlar ada gore sonda."""
    return sorted(
        girdiler,
        key=lambda m: (
            m.get("son_kayit") or "",
            tr_lower(f"{m.get('ad', '')} {m.get('soyad', '')}"),
        ),
        reverse=True,
    )


def ara(girdiler, metin: str) -> list[dict]:
    """TC veya ad/soyad parcasiyla suzer (Turkce buyuk/kucuk harfe duyarsiz)."""
    metin = (metin or "").strip()
    if not metin:
        return list(girdiler)
    aranan = tr_lower(metin)
    sonuc = []
    for musteri in girdiler:
        tam_ad = tr_lower(f"{musteri.get('ad', '')} {musteri.get('soyad', '')}")
        if aranan in tam_ad or aranan in str(musteri.get("tc", "")):
            sonuc.append(musteri)
    return sonuc


def rehberi_yeniden_uret(kok: str | Path) -> int:
    """Arsivdeki meta.json dosyalarini tarayip rehberi bastan olusturur.

    Rehber silinmis, bozulmus ya da uygulama arsiv doldurulduktan sonra
    kurulmus olabilir. Asil veri musteri klasorlerindeki meta.json'da
    durdugu icin dizin her zaman geri kazanilabilir. Islenen musteri
    sayisini dondurur.
    """
    kok = Path(kok)
    veri = bos_rehber()
    for meta_yolu in kok.rglob(META_DOSYASI):
        try:
            meta = json.loads(meta_yolu.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            log.warning("meta.json okunamadi (%s): %s", meta_yolu, exc)
            continue
        if not isinstance(meta, dict) or not meta.get("tc") or not meta.get("tarih"):
            continue

        tc = str(meta["tc"])
        musteri = veri["musteriler"].setdefault(
            tc, {"tc": tc, "olusturma": meta.get("olusturma", ""), "kayitlar": []}
        )
        musteri.update(
            {
                "ad": meta.get("ad", ""),
                "soyad": meta.get("soyad", ""),
                "dogum_tarihi": meta.get("dogum_tarihi") or musteri.get("dogum_tarihi"),
                "guncelleme": meta.get("son_guncelleme", ""),
            }
        )
        musteri["kayitlar"].append(
            {
                "tarih": str(meta["tarih"]),
                "klasor": meta_yolu.parent.relative_to(kok).as_posix(),
                "sube": meta.get("sube_kodu", ""),
                "pdf": meta.get("pdf"),
                "sayfa_sayisi": int(meta.get("sayfa_sayisi") or 0),
            }
        )

    veri["musteriler"] = {
        tc: _musteriyi_duzelt(tc, girdi) for tc, girdi in veri["musteriler"].items()
    }
    rehber_yaz(kok, veri)
    return len(veri["musteriler"])
