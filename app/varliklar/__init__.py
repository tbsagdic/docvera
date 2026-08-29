"""Uygulamayla birlikte dagitilan gorsel varliklar.

Sabit marka dosyalari:
    docvera-logo-horizontal.svg  - arayuz ici yatay logo
    docvera-simge.svg            - uygulama simgesi (pencere / gorev cubugu)
    docvera-simge.ico            - Windows .exe simgesi (tools/ikon_uret.py uretir)
"""

from __future__ import annotations

import sys
from pathlib import Path

YATAY_LOGO = "docvera-logo-horizontal.svg"
SIMGE = "docvera-simge.svg"
SIMGE_ICO = "docvera-simge.ico"


def varlik_klasoru() -> Path:
    """Varlik dosyalarinin bulundugu klasor.

    PyInstaller ile paketlendiginde gecici acilim klasorune (_MEIPASS)
    "app/varliklar" olarak kopyalanir, kaynaktan calisirken bu modulun
    kendi klasorudur.
    """
    taban = getattr(sys, "_MEIPASS", None)
    if taban:
        return Path(taban) / "app" / "varliklar"
    return Path(__file__).resolve().parent


def varlik_yolu(ad: str) -> Path:
    """Verilen varlik dosyasinin tam yolu."""
    return varlik_klasoru() / ad
