"""Surum numarasini git commit sayisina baglar.

Sema: 1.0.<commit sayisi>. Numara elle guncellenmez; her commit bir sonraki
yamayi uretir.

app/surum.py bu betik tarafindan uretilir ve depoya dahil edilir; boylece
paketlenen .exe, git kurulu olmayan bir makinede de kendi surumunu bilir.

Kullanim:
    python tools/surum_yaz.py            HEAD'deki commit sayisini yazar
    python tools/surum_yaz.py --sonraki  HEAD + 1 yazar (pre-commit kancasi)

`--sonraki` yalnizca yeni commit icindir; `git commit --amend` commit sayisini
artirmadigi icin kanca amend sirasinda numarayi bir fazla yazar.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ANA_SURUM = "1.0"

KOK = Path(__file__).resolve().parent.parent
HEDEF = KOK / "app" / "surum.py"

SABLON = '''"""Uretilen dosya - elle duzenlemeyin.

tools/surum_yaz.py tarafindan git commit sayisindan uretilir.
"""

COMMIT_SAYISI = {sayi}
SURUM = "{surum}"
'''


def commit_sayisi() -> int:
    """HEAD'e kadarki commit sayisi; depo yoksa ya da bossa 0."""
    try:
        cikti = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=KOK,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return int(cikti)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0


def yaz(sayi: int) -> str:
    """app/surum.py dosyasini uretir, yazilan surumu dondurur."""
    surum = f"{ANA_SURUM}.{sayi}"
    HEDEF.write_text(SABLON.format(sayi=sayi, surum=surum), encoding="utf-8")
    return surum


def main() -> int:
    sayi = commit_sayisi()
    if "--sonraki" in sys.argv:
        sayi += 1
    print(yaz(sayi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
