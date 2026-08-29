"""Uygulamanin calismasi icin gereken dis bilesenleri tespit eder.

Son kullanicidan kurulum beklenmez: eksik bir bilesen varsa uygulama bunu
kendisi bulur ve tek dugmeyle kurar. Bu modul yalnizca TESPIT eder,
kurulumu app/kurulum/tesseract.py yurutur.
"""

from __future__ import annotations

from dataclasses import dataclass

TESSERACT = "tesseract"
TURKCE_DIL = "tur"


@dataclass(frozen=True)
class Gereksinim:
    """Tek bir dis bilesenin durumu."""

    anahtar: str
    ad: str
    neden: str  # eksikse ne calismaz - kullaniciya bu gosterilir
    tamam: bool
    kurulabilir: bool  # uygulama kendisi kurabiliyor mu
    ayrinti: str = ""  # bulunan yol ya da eksiklik notu


def denetle(tesseract_yolu: str = "") -> list[Gereksinim]:
    """Tum gereksinimleri sirayla denetler.

    Tesseract yoksa dil paketi de zorunlu olarak eksiktir; ikisi ayri satir
    olarak raporlanir cunku Tesseract kurulu olup Turkce paketi olmayan
    kurulumlar sahada cok yaygin.
    """
    from app.ocr import engine

    try:
        yol = engine.tesseract_bul(tesseract_yolu)
    except engine.OcrYok:
        yol = ""

    kurulu_diller = engine.diller(tesseract_yolu) if yol else []

    return [
        Gereksinim(
            anahtar=TESSERACT,
            ad="Tesseract OCR",
            neden=(
                "Kimlikten TC, ad soyad ve doğum tarihi otomatik okunamaz; "
                "kasiyer her alanı elle yazmak zorunda kalır."
            ),
            tamam=bool(yol),
            kurulabilir=True,
            ayrinti=yol or "Bulunamadı",
        ),
        Gereksinim(
            anahtar=TURKCE_DIL,
            ad="Türkçe dil paketi",
            neden=(
                "İsimlerdeki Ş, Ğ, İ, Ö, Ü, Ç harfleri geri kazanılamaz; "
                "ad soyad ASCII karşılığıyla yazılır."
            ),
            tamam=TURKCE_DIL in kurulu_diller,
            kurulabilir=True,
            ayrinti="Kurulu" if TURKCE_DIL in kurulu_diller else "Bulunamadı",
        ),
    ]


def eksikler(tesseract_yolu: str = "") -> list[Gereksinim]:
    """Yalnizca eksik olan ve uygulamanin kurabilecegi bilesenler."""
    return [g for g in denetle(tesseract_yolu) if not g.tamam and g.kurulabilir]


def hepsi_hazir(tesseract_yolu: str = "") -> bool:
    return not eksikler(tesseract_yolu)
