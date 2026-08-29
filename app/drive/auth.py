"""Google Drive kimlik dogrulama.

Kapsam bilerek 'drive.file' secildi: uygulama YALNIZCA kendi olusturdugu
dosya ve klasorlere erisir, kullanicinin Drive'indaki diger hicbir seye
dokunamaz. Bu kapsam Google tarafinda hassas sayilmadigi icin uygulama
dogrulama (verification) surecinden gecmek zorunda kalmaz.

Bunun bir sonucu var: MEVCUT bir Drive klasorune yazilamaz. Bu yuzden kok
klasor ilk kurulumda uygulama tarafindan olusturulur.

Yenileme jetonu Windows DPAPI ile sifrelenir (win32crypt) - duz metin
token.json diskte durmaz. DPAPI cozumu yalnizca ayni Windows kullanicisi
ayni makinede yapabilir.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

log = logging.getLogger(__name__)

KAPSAMLAR = ["https://www.googleapis.com/auth/drive.file"]

JETON_DOSYASI = "token.bin"
ISTEMCI_DOSYASI = "credentials.json"


class KimlikHatasi(Exception):
    """Kullaniciya gosterilebilir Drive kimlik dogrulama hatasi."""


def _sifrele(veri: bytes) -> bytes:
    """DPAPI ile sifreler; pywin32 yoksa duz metne duser."""
    try:
        import win32crypt

        return win32crypt.CryptProtectData(veri, "Docvera", None, None, None, 0)
    except Exception as exc:
        log.warning("DPAPI sifreleme kullanilamadi, jeton duz metin saklanacak: %s", exc)
        return veri


def _coz(veri: bytes) -> bytes:
    try:
        import win32crypt

        return win32crypt.CryptUnprotectData(veri, None, None, None, 0)[1]
    except Exception:
        # Duz metin olarak yazilmis eski jeton olabilir
        return veri


def jeton_yolu(veri_klasoru: Path) -> Path:
    return Path(veri_klasoru) / JETON_DOSYASI


def _paket_klasoru() -> Path:
    """Uygulamayla birlikte gelen dosyalarin klasoru.

    PyInstaller ile paketlendiginde gecici acilim klasoru (_MEIPASS),
    kaynaktan calisirken proje kokudur.
    """
    taban = getattr(sys, "_MEIPASS", None)
    if taban:
        return Path(taban)
    return Path(__file__).resolve().parents[2]


def gomulu_istemci_yolu() -> Path:
    """Uygulamayla birlikte dagitilan OAuth istemci dosyasi."""
    return _paket_klasoru() / ISTEMCI_DOSYASI


def istemci_yolu(veri_klasoru: Path) -> Path:
    """Kullanilacak OAuth istemci dosyasinin yolu.

    Once kullaniciya ozel dosyaya bakilir (kendi Google projesini kullanmak
    isteyen icin), yoksa uygulamayla GOMULU dosyaya duser.

    Gomulu dosya sayesinde son kullanici hicbir kurulum yapmaz: 'Google
    Drive'a baglan' der, Google ekraninda onaylar, biter. Google Cloud
    Console adimlari GELISTIRICI tarafinda BIR KEZ yapilir.

    Masaustu uygulamalarinda istemci gizli anahtari zaten gizli tutulamaz;
    Google bunu boyle tasarlamistir ('installed app' akisi). Guvenlik,
    kullanicinin tarayicida verdigi onaya dayanir - anahtarin gizliligine
    degil.
    """
    kullanici_dosyasi = Path(veri_klasoru) / ISTEMCI_DOSYASI
    if kullanici_dosyasi.is_file():
        return kullanici_dosyasi
    return gomulu_istemci_yolu()


def istemci_hazir_mi(veri_klasoru: Path) -> bool:
    """OAuth istemci dosyasi (kullaniciya ozel ya da gomulu) mevcut mu?"""
    return istemci_yolu(veri_klasoru).is_file()


def jeton_kaydet(veri_klasoru: Path, kimlik: Credentials) -> None:
    yol = jeton_yolu(veri_klasoru)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(_sifrele(kimlik.to_json().encode("utf-8")))


def jeton_yukle(veri_klasoru: Path) -> Credentials | None:
    yol = jeton_yolu(veri_klasoru)
    if not yol.is_file():
        return None
    try:
        ham = json.loads(_coz(yol.read_bytes()).decode("utf-8"))
        return Credentials.from_authorized_user_info(ham, KAPSAMLAR)
    except Exception as exc:
        log.warning("Kayitli Drive jetonu okunamadi: %s", exc)
        return None


def kimlik_al(veri_klasoru: Path, etkilesimli: bool = True) -> Credentials:
    """Gecerli bir Drive kimligi dondurur.

    Kayitli jeton varsa kullanir, suresi dolmussa yeniler. Jeton yoksa ve
    etkilesimli=True ise tarayicida yetkilendirme akisini baslatir.
    """
    veri_klasoru = Path(veri_klasoru)
    kimlik = jeton_yukle(veri_klasoru)

    if kimlik and kimlik.valid:
        return kimlik

    if kimlik and kimlik.expired and kimlik.refresh_token:
        try:
            kimlik.refresh(Request())
            jeton_kaydet(veri_klasoru, kimlik)
            return kimlik
        except Exception as exc:
            log.warning("Drive jetonu yenilenemedi, yeniden yetkilendirme gerekli: %s", exc)

    if not etkilesimli:
        raise KimlikHatasi(
            "Google Drive yetkilendirmesi gerekli. Ayarlar penceresinden "
            "'Google Drive'a bağlan' düğmesini kullanın."
        )

    istemci = istemci_yolu(veri_klasoru)
    if not istemci.is_file():
        raise KimlikHatasi(
            "Google bağlantı dosyası bulunamadı.\n\n"
            "Bu dosya normalde uygulamayla birlikte gelir. Eksikse uygulamayı "
            "yeniden kurun.\n\nKendi Google projenizi kullanacaksanız "
            "credentials.json dosyasını şuraya koyun:\n"
            f"{Path(veri_klasoru) / ISTEMCI_DOSYASI}"
        )

    try:
        akis = InstalledAppFlow.from_client_secrets_file(str(istemci), KAPSAMLAR)
        kimlik = akis.run_local_server(
            port=0,
            authorization_prompt_message="Tarayıcıda açılan sayfadan Google hesabınızı seçin...",
            success_message="Yetkilendirme tamamlandı. Bu sekmeyi kapatabilirsiniz.",
            open_browser=True,
        )
    except Exception as exc:
        raise KimlikHatasi(f"Google Drive yetkilendirmesi tamamlanamadı: {exc}") from exc

    jeton_kaydet(veri_klasoru, kimlik)
    return kimlik


def jetonu_sil(veri_klasoru: Path) -> None:
    """Baglantiyi keser (hesap degistirmek icin)."""
    jeton_yolu(Path(veri_klasoru)).unlink(missing_ok=True)
