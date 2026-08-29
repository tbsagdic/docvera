"""Diskteki dosyalardan sayfa ice aktarma (elle yukleme).

Tarayici her zaman kullanilabilir olmuyor: musteri evraki WhatsApp'tan
gonderiyor, baska bir bilgisayarda taranmis oluyor ya da cihaz ariza yapiyor.
Bu modul, secilen PDF veya goruntu dosyasini taramadan gelmis gibi sayfalara
cevirir; sonrasindaki akis (onizleme, kimlik okuma, kayit) aynidir.

PDF sayfalari PyMuPDF ile goruntuye cevrilir - harici bir program (poppler
vb.) gerektirmez.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

PDF_UZANTILARI = frozenset({".pdf"})

# Pillow'un actigi, tarama evraki icin anlamli bicimler
GORUNTU_UZANTILARI = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp"}
)

DESTEKLENEN_UZANTILAR = PDF_UZANTILARI | GORUNTU_UZANTILARI

# Tek seferde ice aktarilabilecek azami sayfa - yanlislikla secilen kalin bir
# PDF uygulamayi kilitlemesin
AZAMI_SAYFA = 50

# PDF sayfalarinin hangi cozunurlukte goruntuye cevrilecegi. Taramalarla ayni
# olmasi icin 300 DPI; MRZ okumasi icin de bu alt sinir gerekiyor.
VARSAYILAN_DPI = 300


class AktarimHatasi(Exception):
    """Kullaniciya gosterilebilir ice aktarma hatasi."""


def dosya_filtresi() -> str:
    """Qt dosya secme penceresi icin filtre metni."""
    goruntuler = " ".join(f"*{u}" for u in sorted(GORUNTU_UZANTILARI))
    return (
        f"Belgeler (*.pdf {goruntuler});;"
        "PDF dosyalari (*.pdf);;"
        f"Görüntüler ({goruntuler});;"
        "Tüm dosyalar (*)"
    )


def desteklenir_mi(yol: str | Path) -> bool:
    return Path(yol).suffix.lower() in DESTEKLENEN_UZANTILAR


def sayfa_sayisi(yol: str | Path) -> int:
    """Dosyanin kac sayfa icerdigini dondurur (goruntuler icin 1).

    Kullaniciya "23 sayfa eklenecek, emin misiniz?" diye sorabilmek icin,
    sayfalari donusturmeden once cagrilir.
    """
    yol = Path(yol)
    if yol.suffix.lower() not in PDF_UZANTILARI:
        return 1
    try:
        with pymupdf.open(yol) as belge:
            return belge.page_count
    except Exception as exc:
        raise AktarimHatasi(f"PDF açılamadı: {exc}") from exc


def dosyadan_sayfalar(
    yol: str | Path,
    hedef_klasor: str | Path,
    dpi: int = VARSAYILAN_DPI,
    azami_sayfa: int = AZAMI_SAYFA,
) -> list[Path]:
    """Dosyayi sayfa goruntulerine cevirir ve gecici dosya yollarini dondurur.

    Donen dosyalar taramadan gelenlerle ayni sekilde islenir.
    """
    yol = Path(yol)
    hedef_klasor = Path(hedef_klasor)
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    if not yol.is_file():
        raise AktarimHatasi(f"Dosya bulunamadı: {yol}")
    if not desteklenir_mi(yol):
        raise AktarimHatasi(
            f"Desteklenmeyen dosya türü: {yol.suffix or 'uzantısız'}\n\n"
            "PDF veya görüntü dosyası (JPG, PNG, TIFF, BMP) seçin."
        )

    if yol.suffix.lower() in PDF_UZANTILARI:
        return _pdf_sayfalari(yol, hedef_klasor, dpi, azami_sayfa)
    return [_goruntu_sayfasi(yol, hedef_klasor)]


def _gecici_yol(hedef_klasor: Path, on_ek: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=on_ek, suffix=".png", dir=hedef_klasor, delete=False
    ) as gecici:
        return Path(gecici.name)


def _pdf_sayfalari(
    yol: Path, hedef_klasor: Path, dpi: int, azami_sayfa: int
) -> list[Path]:
    """PDF sayfalarini goruntuye cevirir."""
    try:
        belge = pymupdf.open(yol)
    except Exception as exc:
        raise AktarimHatasi(f"PDF açılamadı: {exc}") from exc

    with belge:
        if belge.needs_pass:
            raise AktarimHatasi(
                "PDF parola korumalı. Parolayı kaldırıp tekrar deneyin."
            )
        if belge.page_count == 0:
            raise AktarimHatasi("PDF boş - hiç sayfa içermiyor.")

        alinacak = min(belge.page_count, azami_sayfa)
        if belge.page_count > azami_sayfa:
            log.warning(
                "PDF %s sayfa iceriyor; ilk %s sayfa alindi", belge.page_count, azami_sayfa
            )

        yollar: list[Path] = []
        for sira in range(alinacak):
            try:
                sayfa = belge.load_page(sira)
                # PNG kayipsizdir; JPEG'e cevrim arsive yazilirken yapilir
                pixmap = sayfa.get_pixmap(dpi=dpi)
                hedef = _gecici_yol(hedef_klasor, f"aktarim_{sira + 1:02d}_")
                pixmap.save(hedef)
                yollar.append(hedef)
            except Exception as exc:
                # Tek bir bozuk sayfa tum ice aktarimi bosa cikarmasin
                log.warning("PDF sayfa %s cevrilemedi: %s", sira + 1, exc)

    if not yollar:
        raise AktarimHatasi("PDF sayfalarının hiçbiri görüntüye çevrilemedi.")
    return yollar


def _goruntu_sayfasi(yol: Path, hedef_klasor: Path) -> Path:
    """Goruntu dosyasini dogrulayip calisma klasorune kopyalar.

    Dogrudan kullanmak yerine yeniden yazmak iki ise yarar: dosyanin gercekten
    acilabildigi anlasilir ve telefondan gelen EXIF yonlendirmesi piksellere
    uygulanir (aksi halde onizlemede duz gorunup arsivde yan kaydedilirdi).
    """
    try:
        with Image.open(yol) as goruntu:
            goruntu = ImageOps.exif_transpose(goruntu)
            if goruntu.mode not in ("RGB", "L"):
                goruntu = goruntu.convert("RGB")
            hedef = _gecici_yol(hedef_klasor, "aktarim_")
            goruntu.save(hedef, format="PNG")
    except AktarimHatasi:
        raise
    except Exception as exc:
        raise AktarimHatasi(
            f"Görüntü açılamadı: {yol.name}\n{exc}\n\n"
            "Dosya bozuk olabilir veya desteklenmeyen bir biçimde olabilir."
        ) from exc
    return hedef
