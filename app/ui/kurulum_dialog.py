"""Eksik bilesen penceresi.

Kasiyerden hicbir kurulum bilgisi beklenmez: pencere neyin eksik oldugunu ve
eksigin neye mal oldugunu duz Turkce yazar, tek dugmeyle kurar. Indirme ve
kurulum arka planda yurur, arayuz donmaz.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.config import Ayarlar
from app.kurulum.denetim import Gereksinim, eksikler


class KurulumIscisi(QThread):
    """Kurulumu arka planda yurutur.

    Indirme ve kurulum dakikalarca surebilir; UI thread'inde calistirilirsa
    pencere donar ve Windows "yanit vermiyor" der.
    """

    ilerleme = Signal(str, int)  # mesaj, yuzde (-1 = belirsiz)
    bitti = Signal(bool, str)  # basarili mi, hata mesaji

    def __init__(self, anahtarlar: list[str], parent=None):
        super().__init__(parent)
        self.anahtarlar = list(anahtarlar)

    def run(self) -> None:
        from app.kurulum.tesseract import KurulumHatasi, kur

        try:
            kur(self.anahtarlar, lambda mesaj, yuzde: self.ilerleme.emit(mesaj, yuzde))
        except KurulumHatasi as exc:
            self.bitti.emit(False, str(exc))
        except Exception as exc:  # beklenmeyen hata uygulamayi dusurmesin
            self.bitti.emit(False, f"Beklenmeyen hata: {exc}")
        else:
            self.bitti.emit(True, "")


class KurulumDiyalogu(QDialog):
    """Eksikleri listeler ve tek dugmeyle kurar."""

    def __init__(self, ayarlar: Ayarlar, gereksinimler: list[Gereksinim], parent=None):
        super().__init__(parent)
        self.ayarlar = ayarlar
        self.gereksinimler = list(gereksinimler)
        self.isci: KurulumIscisi | None = None

        self.setWindowTitle("Eksik bileşenler")
        self.setMinimumWidth(520)
        self._arayuzu_kur()

    # --- arayuz ---

    def _arayuzu_kur(self) -> None:
        duzen = QVBoxLayout(self)

        baslik = QLabel(
            "Docvera'nın kimliği otomatik okuyabilmesi için aşağıdakiler eksik. "
            "<b>Kur</b> düğmesine basmanız yeterli; indirme ve kurulumu uygulama "
            "kendisi yapar."
        )
        baslik.setWordWrap(True)
        duzen.addWidget(baslik)

        for gereksinim in self.gereksinimler:
            satir = QLabel(f"<b>{gereksinim.ad}</b><br>{gereksinim.neden}")
            satir.setWordWrap(True)
            satir.setStyleSheet(
                "color: #444; font-size: 11px; border-left: 3px solid #c0392b;"
                " padding-left: 8px; margin-top: 6px;"
            )
            duzen.addWidget(satir)

        self.durum = QLabel()
        self.durum.setWordWrap(True)
        self.durum.setStyleSheet("color: #666; font-size: 11px; margin-top: 8px;")
        duzen.addWidget(self.durum)

        self.cubuk = QProgressBar()
        self.cubuk.setVisible(False)
        duzen.addWidget(self.cubuk)

        self.sorma_kutusu = QCheckBox("Bu uyarıyı bir daha gösterme")
        duzen.addWidget(self.sorma_kutusu)

        dugmeler = QHBoxLayout()
        dugmeler.addStretch(1)
        self.sonra_dugmesi = QPushButton("Sonra")
        self.sonra_dugmesi.clicked.connect(self.reject)
        self.kur_dugmesi = QPushButton("Kur")
        self.kur_dugmesi.setDefault(True)
        self.kur_dugmesi.clicked.connect(self._kur)
        dugmeler.addWidget(self.sonra_dugmesi)
        dugmeler.addWidget(self.kur_dugmesi)
        duzen.addLayout(dugmeler)

        self.durum.setText(
            "Bileşenler internetten indirilir; kurulum sırasında Windows bir kez "
            "izin isteyebilir."
        )

    # --- kurulum ---

    def _kur(self) -> None:
        self.kur_dugmesi.setEnabled(False)
        self.sonra_dugmesi.setEnabled(False)
        self.sorma_kutusu.setEnabled(False)
        self.cubuk.setVisible(True)
        self.cubuk.setRange(0, 0)  # belirsiz
        self.durum.setStyleSheet("color: #666; font-size: 11px; margin-top: 8px;")
        self.durum.setText("Başlatılıyor...")

        self.isci = KurulumIscisi([g.anahtar for g in self.gereksinimler], self)
        self.isci.ilerleme.connect(self._ilerleme)
        self.isci.bitti.connect(self._bitti)
        self.isci.start()

    def _ilerleme(self, mesaj: str, yuzde: int) -> None:
        self.durum.setText(mesaj)
        if yuzde < 0:
            self.cubuk.setRange(0, 0)
        else:
            self.cubuk.setRange(0, 100)
            self.cubuk.setValue(yuzde)

    def _bitti(self, basarili: bool, hata: str) -> None:
        self.cubuk.setVisible(False)
        self.sorma_kutusu.setEnabled(True)
        self.sonra_dugmesi.setEnabled(True)

        if not basarili:
            self.durum.setStyleSheet("color: #c0392b; font-size: 11px; margin-top: 8px;")
            self.durum.setText(hata)
            self.kur_dugmesi.setEnabled(True)
            self.kur_dugmesi.setText("Yeniden dene")
            return

        kalan = eksikler(self.ayarlar.tesseract_yolu)
        if kalan:
            self.durum.setStyleSheet("color: #b8860b; font-size: 11px; margin-top: 8px;")
            self.durum.setText(
                "Kurulum bitti ama şunlar hâlâ eksik: "
                + ", ".join(g.ad for g in kalan)
            )
            self.kur_dugmesi.setEnabled(True)
            self.kur_dugmesi.setText("Yeniden dene")
            return

        self.durum.setStyleSheet("color: #1f6f43; font-size: 11px; margin-top: 8px;")
        self.durum.setText("Kuruldu. Otomatik kimlik okuma artık çalışıyor.")
        self.kur_dugmesi.setText("Kapat")
        self.kur_dugmesi.setEnabled(True)
        try:
            self.kur_dugmesi.clicked.disconnect(self._kur)
        except (RuntimeError, TypeError):
            pass
        self.kur_dugmesi.clicked.connect(self.accept)
        self.sonra_dugmesi.setVisible(False)

    # --- kapanis ---

    def _sormayi_kaydet(self) -> None:
        """'Bir daha gosterme' isaretliyse ayarlara yazar."""
        if not self.sorma_kutusu.isChecked() or self.ayarlar.kurulum_sorma:
            return
        self.ayarlar.kurulum_sorma = True
        try:
            self.ayarlar.kaydet()
        except OSError:  # ayar yazilamamasi kurulumu bosa cikarmamali
            pass

    def _calisiyor_mu(self) -> bool:
        return self.isci is not None and self.isci.isRunning()

    def accept(self) -> None:
        self._sormayi_kaydet()
        super().accept()

    def reject(self) -> None:
        if self._calisiyor_mu():
            return  # kurulum surerken pencere kapanmaz
        self._sormayi_kaydet()
        super().reject()

    def closeEvent(self, olay) -> None:
        if self._calisiyor_mu():
            olay.ignore()
            return
        self._sormayi_kaydet()
        super().closeEvent(olay)


def eksikleri_sor(ayarlar: Ayarlar, parent=None) -> bool:
    """Eksik varsa pencereyi acar. Eksik yoksa hicbir sey yapmaz.

    Dondurdugu deger: pencere gosterildi mi.
    """
    kalan = eksikler(ayarlar.tesseract_yolu)
    if not kalan:
        return False
    diyalog = KurulumDiyalogu(ayarlar, kalan, parent)
    diyalog.setWindowModality(Qt.WindowModality.ApplicationModal)
    diyalog.exec()
    return True
