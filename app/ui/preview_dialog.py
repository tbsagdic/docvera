"""Tarama onizleme ve onay penceresi.

Taranan sayfa once burada gosterilir. Kullanici onaylamadan hicbir sey
arsive yazilmaz - reddedilen sayfa gecici dosyasiyla birlikte silinir.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

# Kullanicinin verdigi karar
ONAYLA = 1
ONAYLA_VE_DEVAM = 2
REDDET = 0


class OnizlemeDiyalogu(QDialog):
    """Tek bir taranmis sayfayi gosterip onay ister."""

    def __init__(self, goruntu_yolu: str | Path, sayfa_no: int, parent=None):
        super().__init__(parent)
        self.goruntu_yolu = Path(goruntu_yolu)
        self.donme = 0
        self.karar = REDDET

        self.setWindowTitle(f"Tarama Onizleme - Sayfa {sayfa_no}")
        self.setMinimumSize(760, 820)

        self._pixmap = QPixmap(str(self.goruntu_yolu))

        self.goruntu_etiketi = QLabel()
        self.goruntu_etiketi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.goruntu_etiketi.setStyleSheet("background: #3a3a3a;")

        kaydirma = QScrollArea()
        kaydirma.setWidget(self.goruntu_etiketi)
        kaydirma.setWidgetResizable(True)

        self.bilgi_etiketi = QLabel()
        self.bilgi_etiketi.setStyleSheet("color: #666;")

        dondur_sol = QPushButton("↺  Sola dondur")
        dondur_sag = QPushButton("↻  Saga dondur")
        dondur_sol.clicked.connect(lambda: self._dondur(-90))
        dondur_sag.clicked.connect(lambda: self._dondur(90))

        arac_satiri = QHBoxLayout()
        arac_satiri.addWidget(dondur_sol)
        arac_satiri.addWidget(dondur_sag)
        arac_satiri.addStretch(1)
        arac_satiri.addWidget(self.bilgi_etiketi)

        dugmeler = QDialogButtonBox()
        onayla = dugmeler.addButton(
            "Onayla", QDialogButtonBox.ButtonRole.AcceptRole
        )
        devam = dugmeler.addButton(
            "Onayla ve Tekrar Tara", QDialogButtonBox.ButtonRole.ActionRole
        )
        reddet = dugmeler.addButton("Reddet", QDialogButtonBox.ButtonRole.RejectRole)

        onayla.setDefault(True)
        onayla.setStyleSheet("font-weight: bold; padding: 8px 20px;")
        devam.setStyleSheet("padding: 8px 20px;")
        reddet.setStyleSheet("padding: 8px 20px;")

        onayla.clicked.connect(lambda: self._karar_ver(ONAYLA))
        devam.clicked.connect(lambda: self._karar_ver(ONAYLA_VE_DEVAM))
        reddet.clicked.connect(lambda: self._karar_ver(REDDET))

        duzen = QVBoxLayout(self)
        duzen.addWidget(kaydirma, 1)
        duzen.addLayout(arac_satiri)
        duzen.addWidget(dugmeler)

        self._goruntuyu_yenile()

    def _karar_ver(self, karar: int) -> None:
        self.karar = karar
        self.accept() if karar else self.reject()

    def _dondur(self, aci: int) -> None:
        self.donme = (self.donme + aci) % 360
        self._goruntuyu_yenile()

    def _goruntuyu_yenile(self) -> None:
        if self._pixmap.isNull():
            self.goruntu_etiketi.setText("Goruntu okunamadi.")
            return

        pixmap = self._pixmap
        if self.donme:
            pixmap = pixmap.transformed(
                QTransform().rotate(self.donme),
                Qt.TransformationMode.SmoothTransformation,
            )

        # Onizleme icin olcekle - tam cozunurluk ekrana sigmaz
        olcekli = pixmap.scaled(
            700,
            700,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.goruntu_etiketi.setPixmap(olcekli)
        self.goruntu_etiketi.resize(olcekli.size())

        boyut_kb = self.goruntu_yolu.stat().st_size / 1024 if self.goruntu_yolu.exists() else 0
        self.bilgi_etiketi.setText(
            f"{pixmap.width()} x {pixmap.height()} piksel  |  {boyut_kb:,.0f} KB"
            + (f"  |  {self.donme}° dondurulmus" if self.donme else "")
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt adlandirmasi)
        """Enter onaylar, Esc reddeder - kasiyer fareye uzanmadan calisabilsin."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._karar_ver(ONAYLA)
            return
        super().keyPressEvent(event)
