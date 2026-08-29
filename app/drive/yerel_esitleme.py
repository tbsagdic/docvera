"""Drive masaustu uygulamasinin (Drive for desktop) esitledigi klasoru bulur.

API ile yukleme her kurulumda kullanicinin bir Google Cloud projesi
olusturmasini gerektiriyor; teknik olmayan biri icin surecin en cok takilinan
yeri burasi. Drive masaustu uygulamasi kuruluysa arsivi dogrudan esitlenen
klasore yazmak ayni sonucu hic kurulum olmadan verir: yuklemeyi Google'in
kendi uygulamasi yapar.

Iki yolun farki kullaniciya soylenmelidir: esitleme bir ayna, yedek degildir.
Yerelden silinen dosya Drive'dan da silinir. API yuklemesi tek yonlu oldugu
icin bulut kopyasi bagimsiz kalir.
"""

from __future__ import annotations

import os
import string
from pathlib import Path

INDIRME_ADRESI = "https://www.google.com/drive/download/"

VARSAYILAN_ARSIV_ADI = "DOCVERA ARSIV"

# Drive masaustu uygulamasi kok klasoru arayuz diline gore adlandirir
KLASOR_ADLARI = ("My Drive", "Drive'ım", "Drive'im", "Benim Drive'ım")


def surucu_kokleri() -> list[Path]:
    """Windows'ta bagli surucu harflerini dondurur.

    Drive masaustu uygulamasi varsayilan olarak sanal bir surucu baglar (G:);
    "akis" modunda esitlenen klasor ev dizininde degil orada durur.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes

        maske = ctypes.windll.kernel32.GetLogicalDrives()
    except (AttributeError, OSError):  # pragma: no cover - Windows disi
        return []
    return [
        Path(f"{harf}:/")
        for sira, harf in enumerate(string.ascii_uppercase)
        if maske >> sira & 1
    ]


def _klasor_mu(yol: Path) -> bool:
    """Cikarilmis surucu veya erisilemeyen ag yolu taramayi durdurmasin."""
    try:
        return yol.is_dir()
    except OSError:
        return False


def drive_klasorleri_bul(tabanlar: list[Path] | None = None) -> list[Path]:
    """Esitlenen Drive klasorlerini bulundugu sirayla dondurur.

    Ev dizini ("aynalama" modu) ve surucu harfleri ("akis" modu) taranir;
    eski istemcinin dogrudan `Google Drive` klasorune esitledigi kurulumlar
    da yakalanir.
    """
    if tabanlar is None:
        tabanlar = [Path.home(), Path.home() / "Google Drive", *surucu_kokleri()]

    bulunan: list[Path] = []
    for taban in tabanlar:
        icerdekiler = [taban / ad for ad in KLASOR_ADLARI if _klasor_mu(taban / ad)]
        for aday in icerdekiler:
            if aday not in bulunan:
                bulunan.append(aday)
        # Eski istemci "My Drive" ara klasoru olmadan esitliyordu
        if (
            not icerdekiler
            and taban.name == "Google Drive"
            and _klasor_mu(taban)
            and taban not in bulunan
        ):
            bulunan.append(taban)
    return bulunan


def esitlenen_klasor(
    yol: str | Path, klasorler: list[Path] | None = None
) -> Path | None:
    """`yol` esitlenen bir Drive klasorunun icindeyse o klasoru dondurur."""
    if not str(yol).strip():
        return None
    try:
        hedef = Path(yol).expanduser().resolve()
    except OSError:
        return None

    for klasor in drive_klasorleri_bul() if klasorler is None else klasorler:
        try:
            kok = klasor.resolve()
        except OSError:
            continue
        if hedef == kok or hedef.is_relative_to(kok):
            return klasor
    return None


def arsiv_hedefi(drive_klasoru: Path, ad: str = VARSAYILAN_ARSIV_ADI) -> Path:
    """Arsivin yazilacagi klasoru dondurur.

    Drive klasorunun kokune degil ayri bir alt klasore yazilir: kok klasorde
    kullanicinin kendi dosyalari durur, arsiv onlarin arasina karismamalidir.
    """
    return Path(drive_klasoru) / ad
