"""Paketlenmis surumu GitHub Releases'e yayimlar.

Uygulamanin guncelleme sistemi tam olarak bu betigin urettigi bicimi bekler:

    v<surum>  etiketi
    Docvera-<surum>-win64.zip  eki (kokunde tek bir Docvera\\ klasoru)
    yayin notlarinda "SHA-256: <ozet>" satiri

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
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
DIST = KOK / "dist" / "Docvera"
EXE = DIST / "Docvera.exe"

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


def notlar(s: str, sha: str) -> str:
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

    return (
        f"Docvera {s}\n\n"
        "## Değişiklikler\n\n"
        f"{gecmis or '- (kayıt yok)'}\n\n"
        "## Kurulum\n\n"
        "Uygulama içinden **Yardım > Güncellemeleri denetle** ile kurulur. "
        "İlk kurulum için zip'i indirip klasörü açmanız yeterlidir.\n\n"
        f"SHA-256: `{sha}`\n"
    )


def gh_var_mi() -> bool:
    return shutil.which("gh") is not None


def yayimla(zip_yolu: Path, s: str, metin: str, taslak: bool) -> None:
    etiket = f"v{s}"
    komut = [
        "gh", "release", "create", etiket, str(zip_yolu),
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
    metin = notlar(s, sha)

    print(f"    Surum : {s}")
    print(f"    Boyut : {zip_yolu.stat().st_size / 1048576:.1f} MB")
    print(f"    SHA256: {sha}")

    if secenek.sadece_zip:
        return 0

    if not gh_var_mi():
        print(
            "\n[!] GitHub CLI (gh) bulunamadi. Elle yayimlamak icin:\n"
            f"    1. https://github.com/tbsagdic/docvera/releases/new\n"
            f"    2. Etiket: v{s}\n"
            f"    3. Dosya : {zip_yolu}\n"
            "    4. Notlara asagidaki metni yapistirin (SHA-256 satiri sart):\n\n"
            f"{metin}"
        )
        return 1

    yayimla(zip_yolu, s, metin, secenek.taslak)
    print("[+] Bitti. Kullanicilar bir gun icinde guncellemeyi gorur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
