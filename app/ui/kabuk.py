"""Dosya ve klasorleri isletim sisteminin varsayilan uygulamasiyla acar.

Kasiyer bir evraga tikladiginda JPG'i goruntuleyicide, PDF'i PDF okuyucuda
gormeli; uygulama kendi goruntuleyicisini yazmaz. Dosya bulunamazsa sessiz
kalinmaz - arsiv tasinmis ya da Drive dosyayi henuz indirmemis olabilir.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

log = logging.getLogger(__name__)


def ac(yol: str | Path, ebeveyn=None) -> bool:
    """Dosya ya da klasoru acar; acilamadiysa kullaniciya soyler."""
    yol = Path(yol)
    if not yol.exists():
        QMessageBox.warning(
            ebeveyn,
            "Bulunamadı",
            f"Şu konum diskte yok:\n{yol}\n\nTaşınmış, silinmiş ya da Google "
            "Drive tarafından henüz indirilmemiş olabilir.",
        )
        return False

    try:
        if sys.platform == "win32":
            os.startfile(yol)  # noqa: S606 - Windows kabugu
        else:
            subprocess.run(["xdg-open", str(yol)], check=False)
    except OSError as exc:
        log.warning("Acilamadi (%s): %s", yol, exc)
        QMessageBox.warning(ebeveyn, "Açılamadı", f"{yol}\n\n{exc}")
        return False
    return True
