"""Tesseract OCR sarmalayicisi.

Tesseract bilerek secildi: tamamen CIHAZ UZERINDE calisir. Kimlik goruntusu
hicbir bulut servisine gonderilmez - KVKK acisindan bulut OCR'i kabul
edilemez olurdu.

pytesseract yerine dogrudan subprocess kullaniliyor: bir bagimlilik daha az
ve komut satiri parametreleri uzerinde tam denetim var.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

# MRZ yalnizca bu karakterleri icerir. Beyaz listeyle Tesseract'in Turkce
# harf veya noktalama uretmesi engellenir - dogruluk belirgin sekilde artar.
MRZ_KARAKTERLERI = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"

# Tesseract'in Windows'taki olagan kurulum konumlari
_OLASI_KONUMLAR = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Tesseract-OCR\tesseract.exe",
)

_ZAMAN_ASIMI = 60  # saniye; tek bir OCR gecisi icin fazlasiyla yeterli


class OcrYok(Exception):
    """Tesseract bulunamadi."""


def tesseract_bul(ayar_yolu: str = "") -> str:
    """Tesseract calistirilabilir dosyasini bulur.

    Sirasiyla: ayarlardaki yol -> PATH -> olagan kurulum konumlari.
    """
    if ayar_yolu and Path(ayar_yolu).is_file():
        return ayar_yolu

    yol = shutil.which("tesseract")
    if yol:
        return yol

    for aday in _OLASI_KONUMLAR:
        if Path(aday).is_file():
            return aday

    raise OcrYok(
        "Tesseract OCR bulunamadı. Otomatik kimlik okuma için kurulması gerekir.\n\n"
        "https://github.com/UB-Mannheim/tesseract/wiki adresinden kurun ve "
        "kurulum sırasında Türkçe dil paketini seçin."
    )


def kullanilabilir_mi(ayar_yolu: str = "") -> bool:
    try:
        tesseract_bul(ayar_yolu)
        return True
    except OcrYok:
        return False


def _indirilen_diller() -> set[str]:
    """Uygulamanin kullanici klasorune indirdigi dil paketleri."""
    from app.config import dil_klasoru

    try:
        return {yol.stem for yol in dil_klasoru().glob("*.traineddata")}
    except OSError:
        return set()


def _tessdata_argumani(dil: str) -> list[str]:
    """Dil paketi uygulama tarafindan indirildiyse Tesseract'i oraya yonlendirir.

    Kurulum sirasinda Program Files'a yazmak yonetici yetkisi isterdi; dil
    paketleri bu yuzden kullanici klasorunde durur ve her cagride acikca
    gosterilir.
    """
    from app.config import dil_klasoru

    klasor = dil_klasoru()
    if (klasor / f"{dil}.traineddata").is_file():
        return ["--tessdata-dir", str(klasor)]
    return []


def diller(ayar_yolu: str = "") -> list[str]:
    """Kurulu Tesseract dil paketlerini dondurur."""
    try:
        sonuc = subprocess.run(
            [tesseract_bul(ayar_yolu), "--list-langs"],
            capture_output=True,
            text=True,
            timeout=_ZAMAN_ASIMI,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OcrYok, subprocess.SubprocessError) as exc:
        log.warning("Tesseract dilleri listelenemedi: %s", exc)
        return []
    satirlar = sonuc.stdout.splitlines()[1:]  # ilk satir baslik
    kurulu = {s.strip() for s in satirlar if s.strip()}
    # Uygulamanin indirdigi paketler Tesseract'in kendi klasorunde gorunmez
    kurulu.update(_indirilen_diller())
    return sorted(kurulu)


def metin_oku(
    goruntu: Image.Image,
    dil: str = "eng",
    beyaz_liste: str = "",
    psm: int = 6,
    ayar_yolu: str = "",
) -> str:
    """Goruntuden metin okur.

    psm 6 = "tek tip metin blogu"; MRZ gibi duzenli satirlar icin en iyisi.
    """
    calistirilabilir = tesseract_bul(ayar_yolu)

    with tempfile.TemporaryDirectory(prefix="ocr_") as gecici:
        girdi = Path(gecici) / "girdi.png"
        cikti_taban = Path(gecici) / "cikti"
        goruntu.save(girdi, format="PNG")

        komut = [
            calistirilabilir,
            str(girdi),
            str(cikti_taban),
            "--psm", str(psm),
            "-l", dil,
        ]
        komut += _tessdata_argumani(dil)
        if beyaz_liste:
            komut += ["-c", f"tessedit_char_whitelist={beyaz_liste}"]
        # Sozluk duzeltmeleri MRZ'de zararlidir: gecerli bir kodu "duzeltip"
        # bozabilir
        komut += ["-c", "load_system_dawg=0", "-c", "load_freq_dawg=0"]

        try:
            subprocess.run(
                komut,
                capture_output=True,
                timeout=_ZAMAN_ASIMI,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            log.warning("Tesseract zaman asimina ugradi")
            return ""
        except subprocess.CalledProcessError as exc:
            log.warning("Tesseract hata verdi: %s", exc.stderr[:400] if exc.stderr else exc)
            return ""

        cikti = cikti_taban.with_suffix(".txt")
        if not cikti.is_file():
            return ""
        return cikti.read_text(encoding="utf-8", errors="replace")


def mrz_oku(goruntu: Image.Image, ayar_yolu: str = "") -> str:
    """MRZ icin ayarlanmis OCR gecisi."""
    return metin_oku(
        goruntu,
        dil="eng",
        beyaz_liste=MRZ_KARAKTERLERI,
        psm=6,
        ayar_yolu=ayar_yolu,
    )


def turkce_oku(goruntu: Image.Image, ayar_yolu: str = "") -> str:
    """Turkce alanlar icin OCR gecisi (Ş, Ğ, İ, Ö, Ü, Ç harflerini tanir)."""
    mevcut = diller(ayar_yolu)
    dil = "tur" if "tur" in mevcut else "eng"
    if dil == "eng":
        log.warning("Turkce dil paketi kurulu degil; Ingilizce ile okunuyor")
    return metin_oku(goruntu, dil=dil, psm=6, ayar_yolu=ayar_yolu)
