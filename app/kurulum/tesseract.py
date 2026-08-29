"""Eksik bilesenleri kullanici ugrasmadan kurar.

Iki yol denenir:

1. **winget** (tercih edilen). Windows 10/11 ile birlikte gelir. Indirdigi
   dosyanin SHA-256 ozetini kendi deposundaki imzali paket ozetiyle
   dogrular; boylece bizim koda URL ya da ozet gommemiz gerekmez.
2. **Dogrudan indirme** (yedek). winget yoksa resmi UB-Mannheim dagitimindan
   HTTPS uzerinden indirilip sessiz kurulur. Adres beyaz listeyle sinirli,
   indirilen dosya calistirilmadan once boyut ve PE imzasi yonunden
   denetlenir.

Her iki yolda da Windows bir kez yonetici izni sorar - Tesseract Program
Files altina kurulur. Kullanicinin yapmasi gereken tek sey "Evet" demektir.

Dil paketleri Program Files'a DEGIL kullanici klasorune indirilir; boylece
yonetici yetkisi gerekmez ve Tesseract'a --tessdata-dir ile gosterilir.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Ilerleme bildirimi: (mesaj, yuzde). Yuzde -1 ise sure bilinmiyor demektir.
Ilerleme = Callable[[str, int], None]

WINGET_PAKET = "UB-Mannheim.TesseractOCR"

# winget bulunmayan makineler icin yedek. Surum yukseltildiginde bu adres
# guncellenmelidir; ulasilamazsa kullaniciya acik hata verilir.
YEDEK_KURULUM_ADRESI = (
    "https://digi.bib.uni-mannheim.de/tesseract/"
    "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
)

# tessdata deposu. "fast" daha hizli ama daha hatali, "best" ~15 MB;
# standart depo ikisinin arasinda ve kimlik okumada yeterli.
DIL_ADRESI = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main/{dil}.traineddata"
)

_GUVENILIR_SUNUCULAR = (
    "digi.bib.uni-mannheim.de",
    "raw.githubusercontent.com",
)

_KURULUM_ZAMAN_ASIMI = 900  # saniye; yavas diskte kurulum dakikalar surebilir
_INDIRME_ZAMAN_ASIMI = 60
_ASGARI_KURULUM_BOYUTU = 20 * 1024 * 1024  # gercek kurulum dosyasi ~60 MB


class KurulumHatasi(Exception):
    """Kullaniciya gosterilebilir kurulum hatasi."""


def _sessiz() -> int:
    """Alt surecin konsol penceresi acmasini engelleyen bayrak."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _dogrula_adres(adres: str) -> None:
    """Yalnizca HTTPS ve beyaz listedeki sunuculara izin verir."""
    parca = urllib.parse.urlparse(adres)
    if parca.scheme != "https":
        raise KurulumHatasi(f"Güvensiz adres reddedildi: {adres}")
    if parca.hostname not in _GUVENILIR_SUNUCULAR:
        raise KurulumHatasi(f"Tanınmayan sunucu reddedildi: {parca.hostname}")


def _indir(adres: str, hedef: Path, bildir: Ilerleme, etiket: str) -> None:
    """Dosyayi indirir. Yarim kalan indirme hedefin uzerine yazilmaz."""
    _dogrula_adres(adres)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_name(hedef.name + ".indiriliyor")

    istek = urllib.request.Request(adres, headers={"User-Agent": "Docvera"})
    try:
        with urllib.request.urlopen(istek, timeout=_INDIRME_ZAMAN_ASIMI) as yanit:
            toplam = int(yanit.headers.get("Content-Length") or 0)
            alinan = 0
            with gecici.open("wb") as dosya:
                while True:
                    parca = yanit.read(65536)
                    if not parca:
                        break
                    dosya.write(parca)
                    alinan += len(parca)
                    if toplam:
                        bildir(
                            f"{etiket} indiriliyor... "
                            f"{alinan // 1048576} / {toplam // 1048576} MB",
                            int(alinan * 100 / toplam),
                        )
                    else:
                        bildir(f"{etiket} indiriliyor...", -1)
    except (urllib.error.URLError, OSError) as exc:
        gecici.unlink(missing_ok=True)
        raise KurulumHatasi(
            f"{etiket} indirilemedi: {exc}\n\n"
            "İnternet bağlantısını denetleyin. Bağlantı güvenlik duvarından "
            "geçmiyorsa bileşeni elle kurmanız gerekebilir."
        ) from exc

    gecici.replace(hedef)


def winget_var_mi() -> bool:
    return shutil.which("winget") is not None


def _winget_ile_kur(bildir: Ilerleme) -> bool:
    """winget ile kurar. Basarisizsa False doner (yedek yola gecilir)."""
    bildir("Tesseract OCR kuruluyor (Windows paket yöneticisi)...", -1)
    komut = [
        "winget", "install",
        "--id", WINGET_PAKET,
        "--exact",
        "--source", "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    try:
        sonuc = subprocess.run(
            komut,
            capture_output=True,
            text=True,
            timeout=_KURULUM_ZAMAN_ASIMI,
            creationflags=_sessiz(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("winget calistirilamadi: %s", exc)
        return False

    if sonuc.returncode == 0:
        return True
    log.warning(
        "winget basarisiz (kod %s): %s",
        sonuc.returncode,
        (sonuc.stdout or sonuc.stderr or "")[-400:],
    )
    return False


def _dogrudan_kur(bildir: Ilerleme) -> None:
    """Resmi dagitimdan indirip sessiz kurar (winget yoksa)."""
    with tempfile.TemporaryDirectory(prefix="docvera_kurulum_") as gecici:
        kurulum = Path(gecici) / "tesseract-kurulum.exe"
        _indir(YEDEK_KURULUM_ADRESI, kurulum, bildir, "Tesseract OCR")

        boyut = kurulum.stat().st_size
        if boyut < _ASGARI_KURULUM_BOYUTU:
            raise KurulumHatasi(
                "İndirilen kurulum dosyası beklenenden küçük "
                f"({boyut // 1048576} MB); güvenlik gereği çalıştırılmadı."
            )
        with kurulum.open("rb") as dosya:
            if dosya.read(2) != b"MZ":
                raise KurulumHatasi(
                    "İndirilen dosya bir Windows kurulum programı değil; "
                    "güvenlik gereği çalıştırılmadı."
                )

        bildir("Tesseract OCR kuruluyor... (Windows izin isteyebilir)", -1)
        try:
            # /S = NSIS sessiz kurulum
            sonuc = subprocess.run(
                [str(kurulum), "/S"],
                capture_output=True,
                timeout=_KURULUM_ZAMAN_ASIMI,
                creationflags=_sessiz(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise KurulumHatasi(f"Kurulum çalıştırılamadı: {exc}") from exc

        if sonuc.returncode != 0:
            raise KurulumHatasi(
                f"Kurulum tamamlanamadı (kod {sonuc.returncode}). "
                "Yönetici izni reddedilmiş olabilir."
            )


def tesseract_kur(bildir: Ilerleme) -> str:
    """Tesseract'i kurar; kurulan calistirilabilir dosyanin yolunu dondurur."""
    from app.ocr import engine

    if not (winget_var_mi() and _winget_ile_kur(bildir)):
        _dogrudan_kur(bildir)

    bildir("Kurulum doğrulanıyor...", -1)
    try:
        return engine.tesseract_bul()
    except engine.OcrYok as exc:
        raise KurulumHatasi(
            "Kurulum bitti ama Tesseract bulunamadı. Uygulamayı kapatıp "
            "yeniden açmayı deneyin; sorun sürerse Ayarlar'dan kurulum "
            "yolunu elle gösterebilirsiniz."
        ) from exc


def dil_paketi_kur(diller: list[str], bildir: Ilerleme) -> None:
    """Dil paketlerini kullanici klasorune indirir (yonetici gerekmez).

    MRZ 'eng' ile okundugu icin Turkce istenirken 'eng' de indirilir:
    --tessdata-dir verildiginde Tesseract yalnizca o klasore bakar.
    """
    from app.config import dil_klasoru

    klasor = dil_klasoru()
    for dil in diller:
        hedef = klasor / f"{dil}.traineddata"
        if hedef.is_file():
            continue
        _indir(DIL_ADRESI.format(dil=dil), hedef, bildir, f"{dil} dil paketi")


def kur(anahtarlar: list[str], bildir: Ilerleme) -> None:
    """Verilen gereksinimleri sirayla kurar.

    Once motor, sonra dil paketi kurulur; sira onemlidir cunku motor yoksa
    dil paketinin tek basina anlami yoktur.
    """
    from app.kurulum.denetim import TESSERACT, TURKCE_DIL

    if TESSERACT in anahtarlar:
        tesseract_kur(bildir)
    if TURKCE_DIL in anahtarlar:
        dil_paketi_kur([TURKCE_DIL, "eng"], bildir)
    bildir("Hazır.", 100)
