"""Ayarlar penceresi: arsiv konumu, sube, tarama varsayilanlari, Google Drive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config import Ayarlar, veri_klasoru
from app.db import Veritabani


class DriveBaglantiIscisi(QThread):
    """Drive yetkilendirmesini arka planda yurutur.

    Tarayicida acilan onay akisi dakikalarca surebilir; UI thread'inde
    calistirilirsa uygulama tamamen kilitlenir.
    """

    tamamlandi = Signal(str, str)  # e-posta, kok klasor id
    hata = Signal(str)

    def __init__(self, kok_adi: str, mevcut_kok_id: str, parent=None):
        super().__init__(parent)
        self.kok_adi = kok_adi
        self.mevcut_kok_id = mevcut_kok_id

    def run(self) -> None:
        try:
            from app.drive.auth import kimlik_al
            from app.drive.client import DriveIstemcisi

            kimlik = kimlik_al(veri_klasoru(), etkilesimli=True)
            istemci = DriveIstemcisi(kimlik)
            eposta = istemci.baglanti_testi()

            # drive.file kapsami mevcut klasore yazamaz; kok klasoru
            # uygulamanin kendisi olusturmali
            kok_id = self.mevcut_kok_id or istemci.kok_klasor_olustur(self.kok_adi)
        except Exception as exc:
            self.hata.emit(str(exc))
        else:
            self.tamamlandi.emit(eposta, kok_id)


class AyarlarDiyalogu(QDialog):
    def __init__(self, ayarlar: Ayarlar, vt: Veritabani, parent=None):
        super().__init__(parent)
        self.ayarlar = ayarlar
        self.vt = vt
        self.baglanti_iscisi: DriveBaglantiIscisi | None = None

        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(560)

        duzen = QVBoxLayout(self)
        duzen.addWidget(self._arsiv_kutusu())
        duzen.addWidget(self._tarama_kutusu())
        duzen.addWidget(self._ocr_kutusu())
        duzen.addWidget(self._drive_kutusu())

        dugmeler = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        dugmeler.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        dugmeler.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        dugmeler.accepted.connect(self._kaydet)
        dugmeler.rejected.connect(self.reject)
        duzen.addWidget(dugmeler)

    # --- Bolumler ---------------------------------------------------------

    def _arsiv_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Arşiv")
        duzen = QFormLayout(kutu)

        self.kok_alani = QLineEdit(self.ayarlar.kok_klasor)
        gozat = QPushButton("Gözat...")
        gozat.clicked.connect(self._klasor_sec)
        kok_satiri = QHBoxLayout()
        kok_satiri.addWidget(self.kok_alani, 1)
        kok_satiri.addWidget(gozat)

        self.sube_kodu_alani = QLineEdit(self.ayarlar.sube_kodu)
        self.sube_kodu_alani.setPlaceholderText("örn. MRK (boş bırakılabilir)")
        self.sube_adi_alani = QLineEdit(self.ayarlar.sube_adi)
        self.sube_adi_alani.setPlaceholderText("örn. MERKEZ - klasör ağacında görünür")

        ipucu = QLabel(
            "Şube adı doluysa klasör yapısı ŞUBE\\2026\\01.2026\\02.01.26\\... olur. "
            "Boş bırakılırsa şube seviyesi oluşmaz."
        )
        ipucu.setWordWrap(True)
        ipucu.setStyleSheet("color: #666; font-size: 11px;")

        duzen.addRow("Kök klasör", kok_satiri)
        duzen.addRow("Şube kodu", self.sube_kodu_alani)
        duzen.addRow("Şube adı", self.sube_adi_alani)
        duzen.addRow("", ipucu)
        return kutu

    def _tarama_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Tarama Varsayılanları")
        duzen = QFormLayout(kutu)

        self.dpi_kutusu = QComboBox()
        for dpi in (150, 200, 300, 400, 600):
            self.dpi_kutusu.addItem(f"{dpi} DPI", dpi)
        indeks = self.dpi_kutusu.findData(self.ayarlar.varsayilan_dpi)
        self.dpi_kutusu.setCurrentIndex(max(indeks, 0))

        self.renkli_kutusu = QCheckBox("Renkli tara")
        self.renkli_kutusu.setChecked(self.ayarlar.renkli_tara)

        self.kalite_kutusu = QSpinBox()
        self.kalite_kutusu.setRange(40, 100)
        self.kalite_kutusu.setValue(self.ayarlar.jpeg_kalite)
        self.kalite_kutusu.setSuffix("  (yüksek = daha büyük dosya)")

        self.pdf_kutusu = QCheckBox("Sayfaları tek PDF'te birleştir")
        self.pdf_kutusu.setChecked(self.ayarlar.pdf_olustur)

        duzen.addRow("Çözünürlük", self.dpi_kutusu)
        duzen.addRow("JPEG kalitesi", self.kalite_kutusu)
        duzen.addRow("", self.renkli_kutusu)
        duzen.addRow("", self.pdf_kutusu)
        return kutu

    def _ocr_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Otomatik Kimlik Okuma")
        duzen = QVBoxLayout(kutu)

        self.ocr_kutusu = QCheckBox(
            "Taranan kimlikten TC, ad soyad ve doğum tarihini otomatik oku"
        )
        self.ocr_kutusu.setChecked(self.ayarlar.otomatik_kimlik_oku)

        self.ocr_durumu = QLabel()
        self.ocr_durumu.setWordWrap(True)

        self.ocr_kur_dugmesi = QPushButton("Eksikleri kur")
        self.ocr_kur_dugmesi.setToolTip(
            "Tesseract OCR ve Türkçe dil paketini uygulama kendisi indirip kurar."
        )
        self.ocr_kur_dugmesi.clicked.connect(self._eksikleri_kur)

        self._ocr_durumunu_yaz()

        aciklama = QLabel(
            "Kimliğin <b>arka yüzündeki</b> makine okunabilir alan (MRZ) okunur. "
            "MRZ'de kontrol haneleri bulunduğu için okumanın doğruluğu hesaplanarak "
            "denetlenir. <b>TC ve doğum tarihi</b> yalnızca bu denetimden geçerse "
            "forma yazılır; geçmezse alanlar boş bırakılır. <b>Ad soyad</b> MRZ'de "
            "kontrol hanesiyle korunmadığı için her zaman kontrol edilmek üzere "
            "sarı işaretlenir. Okuma tamamen bu bilgisayarda yapılır, hiçbir "
            "görüntü internete gönderilmez."
        )
        aciklama.setWordWrap(True)
        aciklama.setStyleSheet("color: #666; font-size: 11px;")

        dugme_satiri = QHBoxLayout()
        dugme_satiri.addWidget(self.ocr_kur_dugmesi)
        dugme_satiri.addStretch(1)

        duzen.addWidget(self.ocr_kutusu)
        duzen.addWidget(self.ocr_durumu)
        duzen.addLayout(dugme_satiri)
        duzen.addWidget(aciklama)
        return kutu

    def _ocr_durumunu_yaz(self) -> None:
        from app.ocr import engine

        try:
            yol = engine.tesseract_bul(self.ayarlar.tesseract_yolu)
        except engine.OcrYok:
            self.ocr_durumu.setText(
                "Tesseract OCR kurulu değil - otomatik okuma çalışmaz."
            )
            self.ocr_durumu.setStyleSheet("color: #c0392b;")
            self.ocr_kur_dugmesi.setEnabled(True)
            return

        mevcut = engine.diller(self.ayarlar.tesseract_yolu)
        if "tur" in mevcut:
            self.ocr_durumu.setText(f"Hazır: {yol} (Türkçe dil paketi kurulu)")
            self.ocr_durumu.setStyleSheet("color: #1f6f43;")
            self.ocr_kur_dugmesi.setEnabled(False)
        else:
            self.ocr_durumu.setText(
                f"Hazır: {yol} - ancak Türkçe dil paketi yok, "
                "isimlerdeki Ş/Ğ/İ harfleri geri kazanılamaz."
            )
            self.ocr_durumu.setStyleSheet("color: #b8860b;")
            self.ocr_kur_dugmesi.setEnabled(True)

    def _eksikleri_kur(self) -> None:
        """Eksik bilesenleri kuran pencereyi acar."""
        from app.kurulum.denetim import eksikler
        from app.ui.kurulum_dialog import KurulumDiyalogu

        kalan = eksikler(self.ayarlar.tesseract_yolu)
        if not kalan:
            QMessageBox.information(
                self, "Eksik yok", "Gerekli bileşenlerin tümü kurulu."
            )
            self._ocr_durumunu_yaz()
            return

        KurulumDiyalogu(self.ayarlar, kalan, self).exec()
        self._ocr_durumunu_yaz()

    def _drive_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Google Drive")
        duzen = QVBoxLayout(kutu)

        self.drive_kutusu = QCheckBox("Google Drive'a otomatik yükle")
        self.drive_kutusu.setChecked(self.ayarlar.drive_etkin)

        self.drive_durumu = QLabel()
        self.drive_durumu.setWordWrap(True)
        self._drive_durumunu_yaz()

        self.baglan_dugmesi = QPushButton("Google Drive'a bağlan")
        self.baglan_dugmesi.clicked.connect(self._drive_baglan)

        kes_dugmesi = QPushButton("Bağlantıyı kes")
        kes_dugmesi.clicked.connect(self._drive_kes)

        satir = QHBoxLayout()
        satir.addWidget(self.baglan_dugmesi)
        satir.addWidget(kes_dugmesi)
        satir.addStretch(1)

        kurulum = QLabel()
        kurulum.setWordWrap(True)
        kurulum.setStyleSheet("color: #666; font-size: 11px;")

        from app.drive.auth import istemci_hazir_mi

        if istemci_hazir_mi(veri_klasoru()):
            kurulum.setText(
                "<b>Google Drive'a bağlan</b> düğmesine basın, açılan Google "
                "sayfasından hesabınızı seçip izin verin. Başka bir işlem yok. "
                f"Uygulama Drive'ınızda <b>{self.ayarlar.drive_kok_adi}</b> adlı "
                "klasörü oluşturur ve arşivi oraya yükler; Drive'ınızdaki başka "
                "hiçbir dosyaya erişemez."
            )
        else:
            kurulum.setText(
                "<b>Google bağlantı dosyası eksik.</b> Bu dosya normalde "
                "uygulamayla birlikte gelir; eksikse uygulamayı yeniden kurun. "
                "Kendi Google projenizi kullanacaksanız "
                f"<code>credentials.json</code> dosyasını <code>{veri_klasoru()}</code> "
                "klasörüne koyun."
            )
            kurulum.setStyleSheet("color: #c0392b; font-size: 11px;")

        duzen.addWidget(self.drive_kutusu)
        duzen.addWidget(self.drive_durumu)
        duzen.addLayout(satir)
        duzen.addWidget(kurulum)
        return kutu

    # --- Eylemler ---------------------------------------------------------

    def _klasor_sec(self) -> None:
        secilen = QFileDialog.getExistingDirectory(
            self, "Arşiv kök klasörünü seçin", self.kok_alani.text()
        )
        if secilen:
            self.kok_alani.setText(str(Path(secilen)))

    def _drive_durumunu_yaz(self) -> None:
        if self.ayarlar.drive_kok_klasor_id:
            self.drive_durumu.setText(
                f"Bağlı. Drive kök klasörü: {self.ayarlar.drive_kok_adi}"
            )
            self.drive_durumu.setStyleSheet("color: #1f6f43;")
        else:
            self.drive_durumu.setText("Henüz bağlanılmadı.")
            self.drive_durumu.setStyleSheet("color: #888;")

    def _drive_baglan(self) -> None:
        self.baglan_dugmesi.setEnabled(False)
        self.drive_durumu.setText("Tarayıcıda açılan sayfadan hesabınızı seçin...")
        self.drive_durumu.setStyleSheet("color: #b8860b;")

        self.baglanti_iscisi = DriveBaglantiIscisi(
            self.ayarlar.drive_kok_adi, self.ayarlar.drive_kok_klasor_id, self
        )
        self.baglanti_iscisi.tamamlandi.connect(self._baglanti_kuruldu)
        self.baglanti_iscisi.hata.connect(self._baglanti_hatasi)
        self.baglanti_iscisi.finished.connect(
            lambda: self.baglan_dugmesi.setEnabled(True)
        )
        self.baglanti_iscisi.start()

    def _baglanti_kuruldu(self, eposta: str, kok_id: str) -> None:
        onceki = self.ayarlar.drive_kok_klasor_id
        self.ayarlar.drive_kok_klasor_id = kok_id
        self.drive_kutusu.setChecked(True)
        if onceki and onceki != kok_id:
            # Kok degistiyse eski klasor kimlikleri gecersizdir
            self.vt.klasor_onbellegi_temizle()
        self.drive_durumu.setText(f"Bağlandı: {eposta}")
        self.drive_durumu.setStyleSheet("color: #1f6f43;")

    def _baglanti_hatasi(self, mesaj: str) -> None:
        self._drive_durumunu_yaz()
        QMessageBox.critical(self, "Google Drive", mesaj)

    def _drive_kes(self) -> None:
        from app.drive.auth import jetonu_sil

        jetonu_sil(veri_klasoru())
        self.ayarlar.drive_kok_klasor_id = ""
        self.drive_kutusu.setChecked(False)
        self.vt.klasor_onbellegi_temizle()
        self._drive_durumunu_yaz()

    def _kaydet(self) -> None:
        self.ayarlar.kok_klasor = self.kok_alani.text().strip()
        self.ayarlar.sube_kodu = self.sube_kodu_alani.text().strip()
        self.ayarlar.sube_adi = self.sube_adi_alani.text().strip()
        self.ayarlar.varsayilan_dpi = int(self.dpi_kutusu.currentData())
        self.ayarlar.renkli_tara = self.renkli_kutusu.isChecked()
        self.ayarlar.jpeg_kalite = self.kalite_kutusu.value()
        self.ayarlar.pdf_olustur = self.pdf_kutusu.isChecked()
        self.ayarlar.otomatik_kimlik_oku = self.ocr_kutusu.isChecked()
        self.ayarlar.drive_etkin = self.drive_kutusu.isChecked()

        sorunlar = self.ayarlar.dogrula()
        if sorunlar:
            QMessageBox.warning(
                self, "Ayarlar eksik", "• " + "\n• ".join(sorunlar)
            )
            return

        self.ayarlar.kaydet()
        self.accept()
