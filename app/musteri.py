"""Musteri ozeti ve gecmisi: yerel veritabani ile arsiv rehberinin birlesimi.

Iki kaynak da eksik olabilir:

* Veritabani (`app.db`) yalnizca **bu bilgisayarda** alinan kayitlari bilir.
* Rehber (`app.storage.rehber`) arsivin icinde durup Drive ile esitlendigi
  icin **tum subelerin** kayitlarini bilir, ama arsive erisilemiyorsa okunamaz.

Bu modul ikisini TC uzerinden birlestirir; boylece hizli musteri secme ve
musteri detay ekrani, kaydin hangi bilgisayarda alindigindan bagimsiz olarak
ayni listeyi gosterir. Qt'ye bagimli degildir, dogrudan test edilebilir.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path

from app.storage import rehber
from app.validation import tr_lower


@dataclass(frozen=True)
class MusteriOzeti:
    """Musteri secme listesinde gosterilen tek satir."""

    tc: str
    ad: str
    soyad: str
    dogum_tarihi: str | None = None
    kayit_sayisi: int = 0
    ilk_kayit: str | None = None
    son_kayit: str | None = None

    @property
    def tam_ad(self) -> str:
        return f"{self.ad} {self.soyad}".strip()


@dataclass(frozen=True)
class MusteriKaydi:
    """Musterinin bir gunluk gelisi (bir klasor)."""

    tarih: _dt.date
    klasor: Path
    sube: str = ""
    pdf: str | None = None
    sayfa_sayisi: int = 0
    ilk_mi: bool = False  # musterinin ilk kaydi: musteri formunun tarandigi gun


def _tarih_ayristir(deger) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(deger))
    except (TypeError, ValueError):
        return None


def musteri_ozetleri(kok: str | Path, vt=None) -> list[MusteriOzeti]:
    """Bilinen tum musterileri en son gelenden eskiye dogru dondurur."""
    birlesik: dict[str, dict] = {}

    for musteri in rehber.rehber_oku(kok)["musteriler"].values():
        tc = str(musteri.get("tc", ""))
        if not tc:
            continue
        birlesik[tc] = {
            "tc": tc,
            "ad": musteri.get("ad", ""),
            "soyad": musteri.get("soyad", ""),
            "dogum_tarihi": musteri.get("dogum_tarihi"),
            "kayit_sayisi": len(musteri.get("kayitlar", [])),
            "ilk_kayit": musteri.get("ilk_kayit"),
            "son_kayit": musteri.get("son_kayit"),
        }

    if vt is not None:
        for satir in vt.musteri_listesi():
            tc = str(satir["tc"])
            girdi = birlesik.setdefault(tc, {"tc": tc})
            # Ad/soyad ve dogum tarihinde yerel veritabani daha guncel olabilir
            girdi["ad"] = satir["ad"]
            girdi["soyad"] = satir["soyad"]
            girdi["dogum_tarihi"] = satir["dogum_tarihi"] or girdi.get("dogum_tarihi")
            # Kayit sayisi ve tarihlerde iki kaynagin genisi alinir: rehber
            # baska subeleri, veritabani bu bilgisayardaki en yeni kaydi bilir
            girdi["kayit_sayisi"] = max(
                int(girdi.get("kayit_sayisi") or 0), int(satir["kayit_sayisi"] or 0)
            )
            girdi["ilk_kayit"] = min(
                [t for t in (girdi.get("ilk_kayit"), satir["ilk_kayit"]) if t],
                default=None,
            )
            girdi["son_kayit"] = max(
                [t for t in (girdi.get("son_kayit"), satir["son_kayit"]) if t],
                default=None,
            )

    ozetler = [
        MusteriOzeti(
            tc=girdi["tc"],
            ad=girdi.get("ad", ""),
            soyad=girdi.get("soyad", ""),
            dogum_tarihi=girdi.get("dogum_tarihi"),
            kayit_sayisi=int(girdi.get("kayit_sayisi") or 0),
            ilk_kayit=girdi.get("ilk_kayit"),
            son_kayit=girdi.get("son_kayit"),
        )
        for girdi in birlesik.values()
    ]
    ozetler.sort(key=lambda m: (m.son_kayit or "", tr_lower(m.tam_ad)), reverse=True)
    return ozetler


def ozet_ara(ozetler: list[MusteriOzeti], metin: str) -> list[MusteriOzeti]:
    """TC veya ad/soyad parcasiyla suzer (Turkce buyuk/kucuk harfe duyarsiz)."""
    metin = (metin or "").strip()
    if not metin:
        return list(ozetler)
    aranan = tr_lower(metin)
    return [
        ozet
        for ozet in ozetler
        if aranan in tr_lower(ozet.tam_ad) or aranan in ozet.tc
    ]


def musteri_kayitlari(kok: str | Path, tc: str, vt=None) -> list[MusteriKaydi]:
    """Musterinin tum gelislerini eskiden yeniye dogru dondurur.

    Ilk kayit `ilk_mi` ile isaretlenir: musteri formu o gun taranmistir.
    """
    kok = Path(kok)
    birlesik: dict[tuple[str, str], dict] = {}

    musteri = rehber.rehber_oku(kok)["musteriler"].get(tc)
    for kayit in (musteri or {}).get("kayitlar", []):
        tarih = _tarih_ayristir(kayit.get("tarih"))
        if tarih is None:
            continue
        sube = str(kayit.get("sube") or "")
        birlesik[(tarih.isoformat(), sube)] = {
            "tarih": tarih,
            "klasor": kok / Path(str(kayit.get("klasor", ""))),
            "sube": sube,
            "pdf": kayit.get("pdf"),
            "sayfa_sayisi": int(kayit.get("sayfa_sayisi") or 0),
        }

    if vt is not None:
        for satir in vt.musteri_gecmisi(tc, sinir=1000):
            tarih = _tarih_ayristir(satir["tarih"])
            if tarih is None:
                continue
            sube = str(satir["sube_kodu"] or "")
            # Veritabanindaki mutlak yol bu bilgisayarda gecerlidir; rehberden
            # gelen goreli yola gore daha guvenilirdir
            birlesik[(tarih.isoformat(), sube)] = {
                "tarih": tarih,
                "klasor": Path(satir["klasor_yolu"]),
                "sube": sube,
                "pdf": satir["pdf_adi"],
                "sayfa_sayisi": int(satir["sayfa_sayisi"] or 0),
            }

    sirali = [birlesik[anahtar] for anahtar in sorted(birlesik)]
    return [
        MusteriKaydi(**girdi, ilk_mi=(indeks == 0))
        for indeks, girdi in enumerate(sirali)
    ]
