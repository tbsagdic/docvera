"""Paketlenmis surumu GitHub Releases'e yayimlar.

Her yayin IKI dosya icerir:

    Docvera-<surum>-kurulum.exe  ilk kurulum icin sihirbaz (Inno Setup)
    Docvera-<surum>-win64.zip    uygulamanin kendi guncellemesi icin paket

Guncelleme sistemi zip'i bekler (sessizce acilip yerine tasinabilsin diye);
son kullanici ise kurulum sihirbazini indirir. Yayin bicimi:

    v<surum>  etiketi
    yayin notlarinda ilk "SHA-256: <ozet>" satiri ZIP'e aittir

Kullanim:
    .venv\\Scripts\\python.exe tools\\yayinla.py            yayimlar
    .venv\\Scripts\\python.exe tools\\yayinla.py --taslak    taslak yayin
    .venv\\Scripts\\python.exe tools\\yayinla.py --sadece-zip  yalnizca paketler

Onkosullar: `paketle.bat` calistirilmis olmali (dist\\Docvera hazir) ve
GitHub CLI (`gh auth login`) kurulmus olmali. gh yoksa betik zip'i ve ozeti
uretip elle yayimlama adimlarini yazar.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
DIST = KOK / "dist" / "Docvera"
EXE = DIST / "Docvera.exe"
ISS = KOK / "tools" / "docvera.iss"
PAKET_DENETLE_BAYRAGI = "--paket-denetle"

# Inno Setup derleyicisinin olagan konumlari (winget kullanici klasorune kurar)
ISCC_ADAYLARI = (
    r"{LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    r"{ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    r"{ProgramFiles}\Inno Setup 6\ISCC.exe",
)

sys.path.insert(0, str(KOK))


def surum() -> str:
    from app.surum import SURUM

    return SURUM


def ozet(yol: Path) -> str:
    """Dosyanin SHA-256 ozeti. Guncelleme bunu indirdikten sonra dogrular."""
    toplayici = hashlib.sha256()
    with yol.open("rb") as dosya:
        for parca in iter(lambda: dosya.read(1024 * 1024), b""):
            toplayici.update(parca)
    return toplayici.hexdigest()


def paketi_denetle() -> None:
    """Yayimlanacak paketin var ve guncel oldugunu dogrular."""
    if not EXE.is_file():
        raise SystemExit(
            f"{EXE} bulunamadi. Once paketle.bat calistirin."
        )
    kaynak = KOK / "app" / "surum.py"
    if kaynak.stat().st_mtime > EXE.stat().st_mtime:
        raise SystemExit(
            "dist\\Docvera surum.py'den eski gorunuyor: paket bu commit'ten "
            "once uretilmis. paketle.bat'i yeniden calistirin."
        )

    try:
        sonuc = subprocess.run(
            [str(EXE), PAKET_DENETLE_BAYRAGI], cwd=DIST, timeout=60
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(
            "Paket acilis denetimi 60 saniyede tamamlanmadi. Yayin durduruldu."
        ) from exc
    if sonuc.returncode != 0:
        raise SystemExit(
            "Paket Qt/UI acilis denetimini gecemedi "
            f"(cikis kodu {sonuc.returncode}). Yayin durduruldu."
        )


def zip_uret(s: str) -> Path:
    """dist\\Docvera klasorunu kokunde Docvera\\ olacak sekilde zipler."""
    hedef = KOK / "dist" / f"Docvera-{s}-win64.zip"
    hedef.unlink(missing_ok=True)
    print(f"[+] Paketleniyor: {hedef.name}")
    with zipfile.ZipFile(hedef, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as arsiv:
        for dosya in sorted(DIST.rglob("*")):
            if dosya.is_file():
                arsiv.write(dosya, Path("Docvera") / dosya.relative_to(DIST))
    return hedef


def iscc_bul() -> str:
    """Inno Setup derleyicisinin yolu; bulunamazsa bos dizge."""
    bulunan = shutil.which("ISCC")
    if bulunan:
        return bulunan
    for kalip in ISCC_ADAYLARI:
        taban = os.environ.get(kalip[1:kalip.index("}")], "")
        if not taban:
            continue
        aday = Path(kalip.format(**os.environ))
        if aday.is_file():
            return str(aday)
    return ""


def kurulum_uret(s: str) -> Path | None:
    """Kurulum sihirbazini derler. Inno Setup yoksa None doner (zip yine cikar)."""
    iscc = iscc_bul()
    if not iscc:
        print(
            "[!] Inno Setup bulunamadi, kurulum sihirbazi uretilmedi.\n"
            "    Kurmak icin: winget install --id JRSoftware.InnoSetup"
        )
        return None

    print("[+] Kurulum sihirbazi derleniyor...")
    sonuc = subprocess.run(
        [iscc, f"/DSURUM={s}", str(ISS)], cwd=KOK, capture_output=True, text=True
    )
    if sonuc.returncode != 0:
        raise SystemExit(
            "Kurulum sihirbazi derlenemedi:\n"
            + (sonuc.stdout or sonuc.stderr or "")[-800:]
        )

    hedef = KOK / "dist" / f"Docvera-{s}-kurulum.exe"
    if not hedef.is_file():
        raise SystemExit(f"{hedef} uretilmedi.")
    return hedef


def notlar(s: str, sha: str, kurulum_sha: str = "") -> str:
    """Yayin notu: son commit basliklari + dogrulama ozeti."""
    try:
        gecmis = subprocess.run(
            ["git", "log", "-15", "--pretty=- %s"],
            cwd=KOK,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        gecmis = ""

    kurulum_satiri = (
        f"\nKurulum dosyası SHA-256: `{kurulum_sha}`\n" if kurulum_sha else ""
    )
    return (
        f"Docvera {s}\n\n"
        "## Kurulum\n\n"
        f"**İlk kurulum:** `Docvera-{s}-kurulum.exe` dosyasını indirip çalıştırın. "
        "Yönetici şifresi istemez; Başlat menüsüne ve isterseniz masaüstüne "
        "kısayol ekler.\n\n"
        "**Zaten kuruluysa:** uygulama kendini günceller — **Yardım > "
        "Güncellemeleri denetle** (ya da günde bir kendiliğinden). "
        f"`Docvera-{s}-win64.zip` uygulamanın kendi güncellemesi için olan "
        "taşınabilir pakettir; elle indirmeniz gerekmez.\n\n"
        "## Değişiklikler\n\n"
        f"{gecmis or '- (kayıt yok)'}\n\n"
        "## Doğrulama\n\n"
        f"SHA-256: `{sha}`  (zip; güncelleme bunu indirdikten sonra denetler)\n"
        f"{kurulum_satiri}"
    )


def gh_var_mi() -> bool:
    return shutil.which("gh") is not None


def yayimla(dosyalar: list[Path], s: str, metin: str, taslak: bool) -> None:
    etiket = f"v{s}"
    komut = [
        "gh", "release", "create", etiket, *[str(d) for d in dosyalar],
        "--title", f"Docvera {s}",
        "--notes", metin,
    ]
    if taslak:
        komut.append("--draft")

    print(f"[+] Yayimlaniyor: {etiket}")
    sonuc = subprocess.run(komut, cwd=KOK)
    if sonuc.returncode != 0:
        raise SystemExit(
            "gh release create basarisiz. Etiket zaten var olabilir; "
            f"'gh release delete {etiket}' ile silip tekrar deneyin."
        )


def main() -> int:
    ayristirici = argparse.ArgumentParser(description="Docvera surumu yayimlar")
    ayristirici.add_argument("--taslak", action="store_true", help="taslak yayin")
    ayristirici.add_argument(
        "--sadece-zip", action="store_true", help="yalnizca zip uret, yayimlama"
    )
    secenek = ayristirici.parse_args()

    paketi_denetle()
    s = surum()
    zip_yolu = zip_uret(s)
    sha = ozet(zip_yolu)
    kurulum = kurulum_uret(s)
    kurulum_sha = ozet(kurulum) if kurulum else ""
    metin = notlar(s, sha, kurulum_sha)

    print(f"    Surum   : {s}")
    print(f"    Zip     : {zip_yolu.stat().st_size / 1048576:.1f} MB  {sha[:16]}...")
    if kurulum:
        print(
            f"    Kurulum : {kurulum.stat().st_size / 1048576:.1f} MB  "
            f"{kurulum_sha[:16]}..."
        )

    if secenek.sadece_zip:
        return 0

    if not gh_var_mi():
        print(
            "\n[!] GitHub CLI (gh) bulunamadi. Elle yayimlamak icin:\n"
            f"    1. https://github.com/tbsagdic/docvera/releases/new\n"
            f"    2. Etiket: v{s}\n"
            f"    3. Dosyalar: {kurulum or '(kurulum uretilmedi)'} + {zip_yolu}\n"
            "    4. Notlara asagidaki metni yapistirin (SHA-256 satiri sart):\n\n"
            f"{metin}"
        )
        return 1

    dosyalar = [d for d in (kurulum, zip_yolu) if d is not None]
    yayimla(dosyalar, s, metin, secenek.taslak)
    print("[+] Bitti. Kullanicilar bir gun icinde guncellemeyi gorur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
