r"""docvera-simge.svg dosyasindan Windows .ico uretir.

Logo degistiginde calistirilir:

    .venv\Scripts\python.exe tools\ikon_uret.py

Uretilen dosya app/varliklar/docvera-simge.ico olarak depoya islenir; boylece
paketleme icin PySide6 disinda ek bir arac gerekmez.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.varliklar import SIMGE, SIMGE_ICO, varlik_yolu  # noqa: E402

# Windows kabugu bu boyutlari kullanir: kucuk simge listesinden 256'lik
# jumbo gorunume kadar her biri ayri ayri rasterlenir.
BOYUTLAR = (16, 24, 32, 48, 64, 128, 256)


def _rasterle(kaynak: Path, boyut: int) -> Image.Image:
    """SVG'yi verilen kenar uzunlugunda seffaf zeminli PNG'ye cevirir."""
    goruntu = QImage(boyut, boyut, QImage.Format.Format_ARGB32)
    goruntu.fill(Qt.GlobalColor.transparent)
    boyayici = QPainter(goruntu)
    boyayici.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(kaynak)).render(boyayici)
    boyayici.end()

    veri = goruntu.constBits().tobytes()
    return Image.frombytes("RGBA", (boyut, boyut), veri, "raw", "BGRA")


def main() -> int:
    QGuiApplication([])  # QImage/QPainter icin Qt cekirdegi gerekir
    kaynak = varlik_yolu(SIMGE)
    if not kaynak.exists():
        print(f"[!] Kaynak bulunamadi: {kaynak}")
        return 1

    kareler = [_rasterle(kaynak, boyut) for boyut in BOYUTLAR]
    hedef = varlik_yolu(SIMGE_ICO)
    kareler[-1].save(hedef, format="ICO", sizes=[(b, b) for b in BOYUTLAR])
    print(f"[+] {hedef} uretildi ({', '.join(str(b) for b in BOYUTLAR)} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
