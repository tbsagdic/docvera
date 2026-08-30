"""Geçmiş kayıtlarda arama penceresi.

Listede klasör yolu gösterilmez: kasiyerin işine yarayan şey yolun kendisi
değil, o müşterinin evraklarıdır. Her satırdaki "Müşteri bilgisi gör"
düğmesi müşteri detay ekranını açar (bkz. musteri_detay_dialog).
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.db import Veritabani
from app.ui.kabuk import ac as kabukta_ac

SUTUNLAR = ["Tarih", "Ad Soyad", "TC", "Sayfa", "Şube", "Müşteri"]

# Satirin tasidigi klasor yolu ve TC bu rollerde saklanir
KLASOR_ROLU = Qt.ItemDataRole.UserRole
TC_ROLU = Qt.ItemDataRole.UserRole + 1

DETAY_SUTUNU = 5


class GecmisDiyalogu(QDialog):
    """TC veya ad ile eski kayitlari arar; musteri detayini ve klasoru acar."""

    def __init__(self, ayarlar, vt: Veritabani, parent=None, belge_ekle=None):
        """belge_ekle: detay ekranindaki "yeni belge ekle" dugmesinin geri cagrisi."""
        super().__init__(parent)
        self.ayarlar = ayarlar
        self.vt = vt
        self._belge_ekle = belge_ekle
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
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.doubleClicked.connect(self.detayi_ac)
        self.tablo.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        detay_dugmesi = QPushButton("Müşteri bilgisi gör")
        detay_dugmesi.clicked.connect(self.detayi_ac)
        ac_dugmesi = QPushButton("Klasörü aç")
        ac_dugmesi.clicked.connect(self.klasoru_ac)
        kapat_dugmesi = QPushButton("Kapat")
        kapat_dugmesi.clicked.connect(self.accept)

        alt = QHBoxLayout()
        alt.addWidget(self.sonuc_etiketi, 1)
        alt.addWidget(detay_dugmesi)
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
            ]
            for sutun, deger in enumerate(degerler):
                oge = QTableWidgetItem(deger)
                if sutun == 3:
                    oge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tablo.setItem(satir, sutun, oge)

            # Klasor yolu ve TC gorunmez veri olarak ilk hucrede tasinir
            ilk = self.tablo.item(satir, 0)
            ilk.setData(KLASOR_ROLU, kayit["klasor_yolu"])
            ilk.setData(TC_ROLU, kayit["tc"])

            dugme = QPushButton("Müşteri bilgisi gör")
            dugme.setToolTip("Bu müşterinin tüm evraklarını tarih tarih gösterir")
            dugme.clicked.connect(
                lambda _=False, tc=kayit["tc"]: self._detayi_goster(tc)
            )
            self.tablo.setCellWidget(satir, DETAY_SUTUNU, dugme)

        self.tablo.resizeColumnsToContents()
        self.tablo.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.sonuc_etiketi.setText(f"{len(kayitlar)} kayıt")

    # --- Eylemler ---------------------------------------------------------

    def _secili_veri(self, rol: int) -> str | None:
        satir = self.tablo.currentRow()
        if satir < 0:
            return None
        oge = self.tablo.item(satir, 0)
        return oge.data(rol) if oge is not None else None

    def detayi_ac(self) -> None:
        """Secili satirin musterisini detay ekraninda acar."""
        tc = self._secili_veri(TC_ROLU)
        if tc:
            self._detayi_goster(tc)

    def _detayi_goster(self, tc: str) -> None:
        from app.ui.musteri_detay_dialog import MusteriDetayDiyalogu

        diyalog = MusteriDetayDiyalogu(
            self.ayarlar, self.vt, tc, self, belge_ekle=self._belge_ekle
        )
        if diyalog.exec() and self._belge_ekle is not None:
            # Detaydan "yeni belge ekle" secildi: ana pencereye don
            self.accept()

    def klasoru_ac(self) -> None:
        """Secili kaydin klasorunu Windows Gezgini'nde acar."""
        klasor = self._secili_veri(KLASOR_ROLU)
        if klasor:
            kabukta_ac(klasor, self)
