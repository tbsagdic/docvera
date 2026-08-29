"""Arsive yazma: JPG sayfalar, birlesik PDF ve meta.json.

Taranan gecici goruntuler burada normalize edilip (JPEG'e cevrilip, dondurulup,
DPI bilgisi gomulup) musteri klasorune yazilir.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import img2pdf
from PIL import Image, ImageOps

from app.config import UYGULAMA_SURUMU
from app.storage.paths import mevcut_sayfa_numaralari, sayfa_dosya_adi

META_DOSYASI = "meta.json"


@dataclass(frozen=True)
class YazilanSayfa:
    """Arsive yazilmis tek bir sayfa."""

    sira: int
    yol: Path
    bayt: int
    sha256: str

    @property
    def dosya_adi(self) -> str:
        return self.yol.name


def sha256_hesapla(yol: str | Path, blok: int = 1 << 20) -> str:
    """Dosyanin SHA-256 ozetini dondurur (Drive'da mukerrer yuklemeyi onler)."""
    ozet = hashlib.sha256()
    with open(yol, "rb") as dosya:
        for parca in iter(lambda: dosya.read(blok), b""):
            ozet.update(parca)
    return ozet.hexdigest()


def sayfa_yaz(
    kaynak: str | Path,
    hedef_klasor: str | Path,
    sira: int,
    jpeg_kalite: int = 85,
    donme: int = 0,
    dpi: int = 300,
) -> YazilanSayfa:
    """Gecici tarama dosyasini musteri klasorune NN.jpg olarak yazar.

    Surucu BMP dondurmus olabilecegi icin bicim burada JPEG'e sabitlenir.
    """
    kaynak = Path(kaynak)
    hedef_klasor = Path(hedef_klasor)
    hedef_klasor.mkdir(parents=True, exist_ok=True)
    hedef = hedef_klasor / sayfa_dosya_adi(sira)

    with Image.open(kaynak) as goruntu:
        # Fotograf makinesi/tarayici EXIF yonlendirmesini piksellere uygula
        goruntu = ImageOps.exif_transpose(goruntu)
        if donme % 360:
            # expand=True: 90/270 derecede goruntu kirpilmasin
            goruntu = goruntu.rotate(-donme % 360, expand=True)
        if goruntu.mode not in ("RGB", "L"):
            goruntu = goruntu.convert("RGB")
        goruntu.save(
            hedef,
            format="JPEG",
            quality=jpeg_kalite,
            optimize=True,
            dpi=(dpi, dpi),
        )

    return YazilanSayfa(
        sira=sira,
        yol=hedef,
        bayt=hedef.stat().st_size,
        sha256=sha256_hesapla(hedef),
    )


def sayfalari_yaz(
    kaynaklar: list[str | Path],
    hedef_klasor: str | Path,
    jpeg_kalite: int = 85,
    donmeler: list[int] | None = None,
    dpi: int = 300,
) -> list[YazilanSayfa]:
    """Birden fazla gecici dosyayi sirayla arsive yazar.

    Numaralandirma klasordeki mevcut sayfalardan devam eder; boylece ayni
    musteri ayni gun tekrar geldiginde eski sayfalar ustune yazilmaz.
    """
    hedef_klasor = Path(hedef_klasor)
    mevcut = mevcut_sayfa_numaralari(hedef_klasor)
    sonraki = (mevcut[-1] + 1) if mevcut else 1

    yazilanlar: list[YazilanSayfa] = []
    for indeks, kaynak in enumerate(kaynaklar):
        donme = donmeler[indeks] if donmeler and indeks < len(donmeler) else 0
        yazilanlar.append(
            sayfa_yaz(kaynak, hedef_klasor, sonraki + indeks, jpeg_kalite, donme, dpi)
        )
    return yazilanlar


def pdf_uret(klasor: str | Path, pdf_adi: str) -> Path | None:
    """Klasordeki tum NN.jpg sayfalarini tek PDF'te birlestirir.

    img2pdf JPEG verisini yeniden sikistirmadan gomer - kalite kaybi olmaz.
    Sayfa eklendiginde PDF bastan uretilir; sayfa yoksa None doner.
    """
    klasor = Path(klasor)
    numaralar = mevcut_sayfa_numaralari(klasor)
    if not numaralar:
        return None

    sayfalar = [str(klasor / sayfa_dosya_adi(numara)) for numara in numaralar]
    hedef = klasor / pdf_adi
    gecici = hedef.with_suffix(".pdf.tmp")

    # Once gecici dosyaya yaz, sonra yer degistir: yarim PDF asla olusmaz
    with open(gecici, "wb") as cikti:
        cikti.write(img2pdf.convert(sayfalar))
    gecici.replace(hedef)
    return hedef


def meta_yaz(
    klasor: str | Path,
    ad: str,
    soyad: str,
    tc: str,
    dogum_tarihi: _dt.date | None,
    tarih: _dt.date,
    sayfalar: list[YazilanSayfa],
    pdf_adi: str | None,
    sube_kodu: str,
    tarayici: str,
    olusturan: str,
) -> Path:
    """Musteri klasorune meta.json yazar.

    Var olan dosya okunur ve sayfa listesi birlestirilir; ayni musteri ayni
    gun tekrar geldiginde onceki tarama bilgisi kaybolmaz.
    """
    klasor = Path(klasor)
    hedef = klasor / META_DOSYASI

    veri: dict = {}
    if hedef.is_file():
        try:
            veri = json.loads(hedef.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            veri = {}
    if not isinstance(veri, dict):
        veri = {}

    onceki_sayfalar = veri.get("sayfalar") if isinstance(veri.get("sayfalar"), list) else []
    yeni_sayfalar = {
        sayfa.sira: {
            "sira": sayfa.sira,
            "dosya": sayfa.dosya_adi,
            "bayt": sayfa.bayt,
            "sha256": sayfa.sha256,
        }
        for sayfa in sayfalar
    }
    birlesik = {
        kayit.get("sira"): kayit
        for kayit in onceki_sayfalar
        if isinstance(kayit, dict) and kayit.get("sira") is not None
    }
    birlesik.update(yeni_sayfalar)

    veri.update(
        {
            "ad": ad,
            "soyad": soyad,
            "tc": tc,
            "dogum_tarihi": dogum_tarihi.isoformat() if dogum_tarihi else None,
            "tarih": tarih.isoformat(),
            "sube_kodu": sube_kodu,
            "pdf": pdf_adi,
            "sayfa_sayisi": len(birlesik),
            "sayfalar": [birlesik[k] for k in sorted(birlesik)],
            "tarayici": tarayici,
            "olusturan": olusturan,
            "uygulama_surumu": UYGULAMA_SURUMU,
            "son_guncelleme": _dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    veri.setdefault("olusturma", veri["son_guncelleme"])

    gecici = hedef.with_suffix(".json.tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(hedef)
    return hedef
