"""Ayarlar penceresi: arsiv konumu, sube, tarama varsayilanlari, Google Drive."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
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

        sekmeler = QTabWidget()
        sekmeler.addTab(
            self._sekme(self._arsiv_kutusu(), self._tarama_kutusu()), "Genel"
        )
        sekmeler.addTab(self._sekme(self._ocr_kutusu()), "Kimlik Okuma")
        sekmeler.addTab(self._sekme(self._drive_kutusu()), "Google Drive")
        sekmeler.addTab(self._sekme(self._guncelleme_kutusu()), "Güncelleme")
        duzen.addWidget(sekmeler)

        dugmeler = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        dugmeler.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        dugmeler.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        dugmeler.accepted.connect(self._kaydet)
        dugmeler.rejected.connect(self.reject)
        duzen.addWidget(dugmeler)

    # --- Bolumler ---------------------------------------------------------

    @staticmethod
    def _sekme(*kutular: QGroupBox) -> QWidget:
        """Ayar gruplarini ekrana sigan ortak bir sekme sayfasina yerlestirir."""
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        for kutu in kutular:
            duzen.addWidget(kutu)
        duzen.addStretch(1)
        return sayfa

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

        duzen.addWidget(self.drive_kutusu)
        duzen.addWidget(self.drive_durumu)
        duzen.addLayout(satir)
        duzen.addSpacing(6)
        duzen.addWidget(self._baglanti_yontemi_kutusu())
        return kutu

    def _baglanti_yontemi_kutusu(self) -> QGroupBox:
        """Baglanti kurulumunu sunar.

        Uygulamayla gomulu bir OAuth istemcisi DAGITILMIYOR: her kurulum kendi
        Google projesini kullanir. Boylece kota, sorumluluk ve olasi bir
        askiya alinma her musteride ayri kalir - tek bir proje uzerinden
        gidilseydi biri kotayi doldurdugunda herkesin yuklemesi dururdu.

        Yine de gomulu bir dosya bulunursa (ozel dagitim) o da desteklenir;
        bu durumda ek secenek olarak gosterilir.
        """
        from app.drive.auth import gomulu_istemci_yolu

        kutu = QGroupBox("Bağlantı kurulumu")
        duzen = QVBoxLayout(kutu)

        gomulu_var = gomulu_istemci_yolu().is_file()

        # --- Uygulamayla gelen baglanti (varsa) --------------------------
        birinci = QLabel(
            "<b>Docvera ile bağlan</b><br>"
            "Yukarıdaki <b>Google Drive'a bağlan</b> düğmesine basın, açılan "
            "Google sayfasından hesabınızı seçip izin verin."
        )
        birinci.setWordWrap(True)
        birinci.setStyleSheet("font-size: 11px;")
        # Gomulu istemci dagitilmadiginda bu secenek hic gosterilmez
        birinci.setVisible(gomulu_var)
        self.gomulu_secenek_etiketi = birinci

        # --- Kendi Google projesi ----------------------------------------
        ikinci = QLabel(
            ("<b>Kendi Google hesabınızla bağlanın</b><br>" if not gomulu_var
             else "<b>Kendi Google hesabımla bağlan</b><br>")
            + "Google Drive'a yükleme için kendi Google projenizi oluşturup "
            "indirdiğiniz dosyayı seçmeniz gerekir. Yaklaşık 5 dakika sürer ve "
            "bu bilgisayarda bir kez yapılır.<br>"
            "<b>Nasıl yapılır?</b> düğmesi adım adım anlatır."
        )
        ikinci.setWordWrap(True)
        ikinci.setStyleSheet("font-size: 11px;")

        self.istemci_sec_dugmesi = QPushButton("Dosya seç...")
        self.istemci_sec_dugmesi.setToolTip(
            "Google Cloud'dan indirdiğiniz JSON dosyasını seçin. "
            "Yeniden adlandırmanıza veya kopyalamanıza gerek yok."
        )
        self.istemci_sec_dugmesi.clicked.connect(self._istemci_dosyasi_sec)

        rehber_dugmesi = QPushButton("Nasıl yapılır?")
        rehber_dugmesi.setToolTip("Adım adım anlatım ve Google sayfalarına kısayollar")
        rehber_dugmesi.clicked.connect(self._drive_rehberini_ac)

        self.istemci_kaldir_dugmesi = QPushButton("Kaldır")
        self.istemci_kaldir_dugmesi.setToolTip(
            "Kendi dosyanızı kaldırır, uygulamayla gelen bağlantıya döner"
        )
        self.istemci_kaldir_dugmesi.clicked.connect(self._istemci_dosyasini_kaldir)

        ikinci_satir = QHBoxLayout()
        ikinci_satir.addWidget(self.istemci_sec_dugmesi)
        ikinci_satir.addWidget(rehber_dugmesi)
        ikinci_satir.addWidget(self.istemci_kaldir_dugmesi)
        ikinci_satir.addStretch(1)

        self.istemci_durumu = QLabel()
        self.istemci_durumu.setWordWrap(True)
        self.istemci_durumu.setStyleSheet("font-size: 11px;")

        duzen.addWidget(birinci)
        duzen.addSpacing(8)
        duzen.addWidget(ikinci)
        duzen.addLayout(ikinci_satir)
        duzen.addWidget(self.istemci_durumu)

        self._istemci_durumunu_yaz()
        return kutu

    def _istemci_durumunu_yaz(self) -> None:
        """Hangi baglantinin kullanildigini gosterir ve dugmeleri ayarlar.

        Istemci dosyasi yokken 'Google Drive'a bağlan' dugmesi kapali tutulur:
        acik biraksaydik basildiginda ancak hata penceresiyle ogrenilirdi.
        """
        from app.drive.auth import (
            gomulu_istemci_yolu,
            istemci_hazir_mi,
            kullanici_istemcisi_var_mi,
        )

        kendi = kullanici_istemcisi_var_mi(veri_klasoru())
        hazir = istemci_hazir_mi(veri_klasoru())

        self.istemci_kaldir_dugmesi.setEnabled(kendi)
        self.baglan_dugmesi.setEnabled(hazir)
        self.baglan_dugmesi.setToolTip(
            "" if hazir
            else "Önce aşağıdan Google bağlantı dosyanızı seçin"
        )

        if kendi:
            self.istemci_durumu.setText("Kendi Google projeniz kurulu.")
            self.istemci_durumu.setStyleSheet("font-size: 11px; color: #1f6f43;")
        elif gomulu_istemci_yolu().is_file():
            self.istemci_durumu.setText(
                "Uygulamayla gelen bağlantı kullanılıyor."
            )
            self.istemci_durumu.setStyleSheet("font-size: 11px; color: #666;")
        else:
            self.istemci_durumu.setText(
                "Henüz bir Google bağlantısı kurulmadı. "
                "<b>Nasıl yapılır?</b> düğmesiyle başlayın."
            )
            self.istemci_durumu.setStyleSheet("font-size: 11px; color: #b8860b;")

    def _drive_rehberini_ac(self) -> None:
        from app.ui.drive_rehber_dialog import DriveRehberDiyalogu

        DriveRehberDiyalogu(self).exec()

    def _istemci_dosyasi_sec(self) -> None:
        """Kullanicinin indirdigi OAuth dosyasini alir, dogrular ve kurar."""
        from app.drive.auth import KimlikHatasi, istemci_dosyasini_kur

        indirilenler = str(Path.home() / "Downloads")
        secilen, _ = QFileDialog.getOpenFileName(
            self,
            "Google Cloud'dan indirdiğiniz JSON dosyasını seçin",
            indirilenler if Path(indirilenler).is_dir() else "",
            "Google OAuth dosyası (*.json);;Tüm dosyalar (*)",
        )
        if not secilen:
            return

        try:
            istemci_kimligi = istemci_dosyasini_kur(secilen, veri_klasoru())
        except KimlikHatasi as exc:
            QMessageBox.critical(self, "Dosya kullanılamadı", str(exc))
            return

        self.ayarlar.drive_kok_klasor_id = ""  # baska proje, baska klasor
        self.vt.klasor_onbellegi_temizle()
        self._istemci_durumunu_yaz()
        self._drive_durumunu_yaz()
        QMessageBox.information(
            self,
            "Dosya kabul edildi",
            "Kendi Google projeniz kuruldu.\n\n"
            f"İstemci: {istemci_kimligi[:28]}...\n\n"
            "Şimdi <b>Google Drive'a bağlan</b> düğmesine basıp hesabınızı "
            "seçin.",
        )

    def _istemci_dosyasini_kaldir(self) -> None:
        from app.drive.auth import kullanici_istemcisini_sil

        cevap = QMessageBox.question(
            self,
            "Kendi bağlantınızı kaldır",
            "Kendi Google projeniz kaldırılacak ve uygulamayla gelen bağlantıya "
            "dönülecek.\n\nDrive'daki mevcut dosyalarınız silinmez, ancak yeni "
            "yüklemeler için yeniden bağlanmanız gerekir.\n\nDevam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if cevap != QMessageBox.StandardButton.Yes:
            return

        kullanici_istemcisini_sil(veri_klasoru())
        self.ayarlar.drive_kok_klasor_id = ""
        self.vt.klasor_onbellegi_temizle()
        self._istemci_durumunu_yaz()
        self._drive_durumunu_yaz()

    def _guncelleme_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Güncelleme")
        duzen = QVBoxLayout(kutu)

        self.guncelleme_kutusu = QCheckBox(
            "Yeni sürümleri kendiliğinden denetle (günde bir kez)"
        )
        self.guncelleme_kutusu.setChecked(self.ayarlar.guncelleme_otomatik_denetle)

        self.guncelleme_durumu = QLabel()
        self.guncelleme_durumu.setWordWrap(True)
        self._guncelleme_durumunu_yaz()

        denetle_dugmesi = QPushButton("Şimdi denetle")
        denetle_dugmesi.setToolTip(
            "Ayarlar kaydedilir, pencere kapanır ve denetim hemen başlar."
        )
        denetle_dugmesi.clicked.connect(self._simdi_denetle)

        self.hatirlat_dugmesi = QPushButton("Atlanan sürümü yeniden hatırlat")
        self.hatirlat_dugmesi.clicked.connect(self._atlamayi_geri_al)
        self.hatirlat_dugmesi.setVisible(bool(self.ayarlar.guncelleme_atlanan_surum))

        satir = QHBoxLayout()
        satir.addWidget(denetle_dugmesi)
        satir.addWidget(self.hatirlat_dugmesi)
        satir.addStretch(1)

        aciklama = QLabel(
            "Yeni sürüm GitHub'daki resmî yayın sayfasından indirilir, indirilen "
            "paketin SHA-256 özeti doğrulanır ve kurulum onayınızdan sonra yapılır. "
            "Ayarlarınız, arşiviniz ve Drive bağlantınız güncellemeden etkilenmez."
        )
        aciklama.setWordWrap(True)
        aciklama.setStyleSheet("color: #666; font-size: 11px;")

        duzen.addWidget(self.guncelleme_kutusu)
        duzen.addWidget(self.guncelleme_durumu)
        duzen.addLayout(satir)
        duzen.addWidget(aciklama)
        return kutu

    def _guncelleme_durumunu_yaz(self) -> None:
        from app.config import UYGULAMA_SURUMU

        metin = f"Kullanılan sürüm: {UYGULAMA_SURUMU}"
        atlanan = self.ayarlar.guncelleme_atlanan_surum
        if atlanan:
            metin += f" - {atlanan} sürümü atlandı, hatırlatılmıyor."
        self.guncelleme_durumu.setText(metin)
        self.guncelleme_durumu.setStyleSheet("color: #666; font-size: 11px;")

    def _atlamayi_geri_al(self) -> None:
        self.ayarlar.guncelleme_atlanan_surum = ""
        self.hatirlat_dugmesi.setVisible(False)
        self._guncelleme_durumunu_yaz()

    def _simdi_denetle(self) -> None:
        """Ayarlari kaydedip denetimi ana pencereye devreder.

        Denetim ana pencerede yurutulur: kurulum uygulamayi kapatacagi icin
        acik bir ayar penceresinin arkada kalmasi kapanmayi engellerdi.
        """
        pencere = self.parent()
        self._kaydet()
        if self.result() != QDialog.DialogCode.Accepted:
            return  # ayarlarda sorun var, kaydedilemedi
        if hasattr(pencere, "guncellemeleri_denetle"):
            QTimer.singleShot(0, pencere.guncellemeleri_denetle)

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
        self.ayarlar.guncelleme_otomatik_denetle = self.guncelleme_kutusu.isChecked()

        sorunlar = self.ayarlar.dogrula()
        if sorunlar:
            QMessageBox.warning(
                self, "Ayarlar eksik", "• " + "\n• ".join(sorunlar)
            )
            return

        self.ayarlar.kaydet()
        self.accept()
