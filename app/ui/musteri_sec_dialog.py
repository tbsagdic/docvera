"""Hızlı müşteri seçme penceresi.

Aynı müşteri birden çok kez gelir; her gelişinde adını, soyadını ve TC'sini
yeniden yazmak hem yavaştır hem de yazım farkından ikinci bir müşteri kaydı
doğurur. Bu pencere kayıtlı müşterileri arattırır, seçilen müşterinin
bilgileri forma yüklenip kilitlenir - böylece evrak her zaman mevcut
müşterinin altına düşer.

Liste iki kaynağın birleşimidir (bkz. app.musteri): yerel veritabanı ve
arşivdeki musteriler.json rehberi.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
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

from app.musteri import MusteriOzeti, musteri_ozetleri, ozet_ara

SUTUNLAR = ["Ad Soyad", "TC Kimlik No", "Doğum Tarihi", "Kayıt", "Son Geliş"]


def _tarih_metni(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return _dt.date.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


class MusteriSecDiyalogu(QDialog):
    """Kayitli musteriler arasindan secim yapar."""

    def __init__(self, ayarlar, vt, parent=None):
        super().__init__(parent)
        self.ayarlar = ayarlar
        self.vt = vt
        self.secilen: MusteriOzeti | None = None
        self._tumu: list[MusteriOzeti] = []
        self._gosterilen: list[MusteriOzeti] = []

        self.setWindowTitle("Kayıtlı Müşteriler")
        self.resize(820, 540)

        self.arama_alani = QLineEdit()
        self.arama_alani.setPlaceholderText("Ad soyad veya TC Kimlik No yazın...")
        self.arama_alani.setClearButtonEnabled(True)
        self.arama_alani.textChanged.connect(self._suz)
        # Kasiyer arayip Enter'a basar: en ustteki eslesme secilir
        self.arama_alani.returnPressed.connect(self._sec)

        self.tablo = QTableWidget(0, len(SUTUNLAR))
        self.tablo.setHorizontalHeaderLabels(SUTUNLAR)
        self.tablo.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tablo.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tablo.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.doubleClicked.connect(self._sec)
        self.tablo.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )

        self.sonuc_etiketi = QLabel()
        self.sonuc_etiketi.setStyleSheet("color: #666;")

        sec_dugmesi = QPushButton("Seç")
        sec_dugmesi.setDefault(True)
        sec_dugmesi.clicked.connect(self._sec)

        detay_dugmesi = QPushButton("Müşteri bilgisi gör")
        detay_dugmesi.clicked.connect(self._detayi_ac)

        yenile_dugmesi = QPushButton("Arşivden tara")
        yenile_dugmesi.setToolTip(
            "Arşiv klasörünü tarayıp müşteri rehberini (musteriler.json) "
            "yeniden oluşturur. Rehber silinmişse ya da arşiv başka bir "
            "bilgisayarda doldurulmuşsa kullanın."
        )
        yenile_dugmesi.clicked.connect(self._rehberi_yenile)

        kapat_dugmesi = QPushButton("Kapat")
        kapat_dugmesi.clicked.connect(self.reject)

        alt = QHBoxLayout()
        alt.addWidget(self.sonuc_etiketi, 1)
        alt.addWidget(yenile_dugmesi)
        alt.addWidget(detay_dugmesi)
        alt.addWidget(sec_dugmesi)
        alt.addWidget(kapat_dugmesi)

        duzen = QVBoxLayout(self)
        duzen.addWidget(self.arama_alani)
        duzen.addWidget(self.tablo, 1)
        duzen.addLayout(alt)

        self.yukle()
        self.arama_alani.setFocus()

    # --- Liste ------------------------------------------------------------

    def yukle(self) -> None:
        self._tumu = musteri_ozetleri(self.ayarlar.kok_klasor, self.vt)
        self._suz(self.arama_alani.text())

    def _suz(self, metin: str) -> None:
        self._gosterilen = ozet_ara(self._tumu, metin)
        self.tablo.setRowCount(len(self._gosterilen))

        for satir, musteri in enumerate(self._gosterilen):
            degerler = [
                musteri.tam_ad,
                musteri.tc,
                _tarih_metni(musteri.dogum_tarihi),
                str(musteri.kayit_sayisi),
                _tarih_metni(musteri.son_kayit),
            ]
            for sutun, deger in enumerate(degerler):
                oge = QTableWidgetItem(deger)
                if sutun >= 2:
                    oge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tablo.setItem(satir, sutun, oge)

        if self._gosterilen:
            self.tablo.selectRow(0)
        self.sonuc_etiketi.setText(
            f"{len(self._gosterilen)} müşteri"
            if len(self._gosterilen) == len(self._tumu)
            else f"{len(self._gosterilen)} / {len(self._tumu)} müşteri"
        )

    def _secili_musteri(self) -> MusteriOzeti | None:
        satir = self.tablo.currentRow()
        if 0 <= satir < len(self._gosterilen):
            return self._gosterilen[satir]
        return None

    # --- Eylemler ---------------------------------------------------------

    def _sec(self) -> None:
        musteri = self._secili_musteri()
        if musteri is None:
            return
        self.secilen = musteri
        self.accept()

    def _detayi_ac(self) -> None:
        musteri = self._secili_musteri()
        if musteri is None:
            return
        from app.ui.musteri_detay_dialog import MusteriDetayDiyalogu

        # Buradaki detay yalnizca gostermek icin: yeni belge eklemek zaten
        # bu pencerede "Sec" demekle olur
        MusteriDetayDiyalogu(self.ayarlar, self.vt, musteri.tc, self).exec()

    def _rehberi_yenile(self) -> None:
        """Arsivi tarayip musteriler.json'u bastan olusturur."""
        from app.storage import rehber

        adet: int | None = None
        hata = ""
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            adet = rehber.rehberi_yeniden_uret(self.ayarlar.kok_klasor)
        except OSError as exc:
            hata = str(exc)
        finally:
            QGuiApplication.restoreOverrideCursor()

        if adet is None:
            QMessageBox.warning(
                self,
                "Rehber güncellenemedi",
                f"Arşiv taranamadı:\n{hata}\n\nArşiv klasörüne erişimi kontrol edin.",
            )
            return

        self.yukle()
        self.sonuc_etiketi.setText(f"Rehber güncellendi: {adet} müşteri")
