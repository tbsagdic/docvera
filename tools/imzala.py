"""Windows kod imzalama yardimcisi.

Windows 11'in "Akilli Uygulama Denetimi" (Smart App Control) ve kurumsal
"App Control for Business" (WDAC) ilkeleri IMZASIZ calistirilabilir dosyalari
calistirmaz. Boyle bir makinede kurulum sihirbazi kendini %TEMP% klasorune
acip calistirmaya kalktigi anda su hatayla durur:

    Gecici klasordeki dosya calistirilamadigindan kurulum iptal edildi.
    Hata 4551: Uygulama Denetimi ilkesi bu dosyayi engelledi.

Kalici tek cozum paketi bir kod imzalama sertifikasiyla imzalamaktir. Sertifika
alindiginda tek yapilacak DOCVERA_IMZA ortam degiskenini signtool komutuna
ayarlamak; $f yerine imzalanacak dosya konur:

    set DOCVERA_IMZA=signtool.exe sign /fd SHA256 ^
        /tr http://timestamp.digicert.com /td SHA256 /a $f

Ayni sablon hem PyInstaller ciktisi hem de Inno Setup icin kullanilir
(Inno de $f yer tutucusunu bilir).

Degisken tanimli degilse paketleme aynen surer, paket yalnizca imzasiz cikar.
Boylece sertifikasi olmayan gelistirici de paket uretebilir; imza yayin
oncesinde eklenen bir adimdir, gelistirmeyi engellemez.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

DEGISKEN = "DOCVERA_IMZA"
YER_TUTUCU = "$f"

# Imza gerektiren uzantilar. Uygulama Denetimi yalnizca .exe'yi degil, surece
# yuklenen DLL/PYD'leri de denetler; birini atlarsak uygulama acilirken duser.
UZANTILAR = (".exe", ".dll", ".pyd")

# Windows komut satiri ~32k karakterle sinirli; dosyalari oberk oberk veriyoruz.
OBEK = 50


def _bol(metin: str) -> list[str]:
    """Komut sablonunu parcalara ayirir.

    Windows yollarindaki ters bolu kacis karakteri sayilmamali, bu yuzden
    shlex'in kacis islemesi kapatilir.
    """
    ayirici = shlex.shlex(metin, posix=True)
    ayirici.whitespace_split = True
    ayirici.escape = ""
    return list(ayirici)


def sablon() -> str:
    """DOCVERA_IMZA degiskeninin degeri; tanimsizsa bos dizge."""
    return os.environ.get(DEGISKEN, "").strip()


def hazir_mi() -> bool:
    return bool(sablon())


def _calistir(parcalar: list[str], yollar: list[Path]) -> None:
    komut: list[str] = []
    for parca in parcalar:
        if parca == YER_TUTUCU:
            komut.extend(str(y) for y in yollar)
        else:
            komut.append(parca)

    sonuc = subprocess.run(komut, capture_output=True, text=True)
    if sonuc.returncode != 0:
        cikti = (sonuc.stdout or "") + (sonuc.stderr or "")
        raise SystemExit(
            f"Imzalama basarisiz (cikis kodu {sonuc.returncode}):\n"
            + cikti.strip()[-800:]
        )


def dosyalari_imzala(yollar: list[Path]) -> int:
    """Verilen dosyalari imzalar. Sablon tanimsizsa hicbir sey yapmaz."""
    metin = sablon()
    if not metin:
        return 0

    parcalar = _bol(metin)
    if YER_TUTUCU not in parcalar:
        raise SystemExit(
            f"{DEGISKEN} icinde '{YER_TUTUCU}' yer tutucusu yok; imzalanacak "
            "dosyanin komutta nereye gelecegi belirsiz."
        )

    for basla in range(0, len(yollar), OBEK):
        _calistir(parcalar, yollar[basla : basla + OBEK])
    return len(yollar)


def paketi_imzala(klasor: Path) -> int:
    r"""dist\Docvera altindaki tum calistirilabilir dosyalari imzalar."""
    if not hazir_mi():
        return 0
    hedefler = sorted(
        y for y in klasor.rglob("*") if y.is_file() and y.suffix.lower() in UZANTILAR
    )
    return dosyalari_imzala(hedefler)


def uyari() -> str:
    """Imza yokken yayin ciktisinda gosterilecek aciklama."""
    return (
        f"[!] Paket IMZASIZ: {DEGISKEN} tanimli degil.\n"
        "    Akilli Uygulama Denetimi acik Windows 11 makinelerinde kurulum\n"
        "    'Hata 4551: Uygulama Denetimi ilkesi bu dosyayi engelledi' verir.\n"
        "    Ayrinti: README > Dagitim > Windows'un imzasiz paketi engellemesi"
    )
