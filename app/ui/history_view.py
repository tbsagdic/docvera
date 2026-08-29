"""Geçmiş kayıtlarda arama penceresi."""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.db import Veritabani

SUTUNLAR = ["Tarih", "Ad Soyad", "TC", "Sayfa", "Şube", "Klasör"]


class GecmisDiyalogu(QDialog):
    """TC veya ad ile eski kayitlari arar ve klasorunu acar."""

    def __init__(self, vt: Veritabani, parent=None):
        super().__init__(parent)
        self.vt = vt
        self.setWindowTitle("Geçmiş Kayıtlar")
        self.resize(940, 560)

        self.arama_alani = QLineEdit()
        self.arama_alani.setPlaceholderText("TC Kimlik No veya ad soyad yazın...")
        self.arama_alani.textChanged.connect(self.ara)
        self.arama_alani.setClearButtonEnabled(True)

        self.sonuc_etiketi = QLabel()
        self.sonuc_etiketi.setStyleSheet("color: #666;")

        self.tablo = QTableWidget(0, len(SUTUNLAR))
        self.tablo.setHorizontalHeaderLabels(SUTUNLAR)
        self.tablo.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tablo.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tablo.doubleClicked.connect(self.klasoru_ac)
        basliklar = self.tablo.horizontalHeader()
        basliklar.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        ac_dugmesi = QPushButton("Klasörü aç")
        ac_dugmesi.clicked.connect(self.klasoru_ac)
        kapat_dugmesi = QPushButton("Kapat")
        kapat_dugmesi.clicked.connect(self.accept)

        alt = QHBoxLayout()
        alt.addWidget(self.sonuc_etiketi, 1)
        alt.addWidget(ac_dugmesi)
        alt.addWidget(kapat_dugmesi)

        duzen = QVBoxLayout(self)
        duzen.addWidget(self.arama_alani)
        duzen.addWidget(self.tablo, 1)
        duzen.addLayout(alt)

        self.ara("")

    def ara(self, metin: str) -> None:
        kayitlar = self.vt.ara(metin) if metin.strip() else self.vt.son_kayitlar()
        self.tablo.setRowCount(len(kayitlar))

        for satir, kayit in enumerate(kayitlar):
            tarih = _dt.date.fromisoformat(kayit["tarih"]).strftime("%d.%m.%Y")
            degerler = [
                tarih,
                f"{kayit['ad']} {kayit['soyad']}",
                kayit["tc"],
                str(kayit["sayfa_sayisi"]),
                kayit["sube_kodu"] or "-",
                kayit["klasor_yolu"],
            ]
            for sutun, deger in enumerate(degerler):
                oge = QTableWidgetItem(deger)
                if sutun == 3:
                    oge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tablo.setItem(satir, sutun, oge)

        self.tablo.resizeColumnsToContents()
        self.tablo.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
        self.sonuc_etiketi.setText(f"{len(kayitlar)} kayıt")

    def klasoru_ac(self) -> None:
        """Secili kaydin klasorunu Windows Gezgini'nde acar."""
        satir = self.tablo.currentRow()
        if satir < 0:
            return
        oge = self.tablo.item(satir, 5)
        if oge is None:
            return

        klasor = Path(oge.text())
        if not klasor.is_dir():
            QMessageBox.warning(
                self,
                "Klasör bulunamadı",
                f"Klasör diskte yok:\n{klasor}\n\nTaşınmış veya silinmiş olabilir.",
            )
            return

        if sys.platform == "win32":
            os.startfile(klasor)  # noqa: S606 - Windows Gezgini
        else:
            subprocess.run(["xdg-open", str(klasor)], check=False)
