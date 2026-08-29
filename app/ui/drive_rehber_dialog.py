"""Kendi Google hesabıyla bağlanmak isteyenler için adım adım rehber.

Google Cloud Console adımları teknik olmayan biri için kolay kaybolunacak
kadar uzun. Bu pencere adımları sırayla gösterir, her adımın ilgili sayfasını
tek tuşla açar ve en sık yapılan hatayı (Web yerine Masaüstü istemcisi
seçmek) öne çıkarır.
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# Adim: (baslik, aciklama HTML, acilacak baglanti veya "", dugme metni)
ADIMLAR: list[tuple[str, str, str, str]] = [
    (
        "Google Cloud'da proje oluşturun",
        "Açılan sayfada üst çubuktaki proje seçiciye tıklayın → "
        "<b>Yeni Proje</b> → adını <b>Docvera</b> yazın → <b>Oluştur</b>.<br><br>"
        "Proje oluşturulduktan sonra yine üst çubuktan bu projeyi seçili hale "
        "getirin.",
        "https://console.cloud.google.com/projectcreate",
        "Proje oluşturma sayfasını aç",
    ),
    (
        "Google Drive API'yi etkinleştirin",
        "Açılan sayfada <b>Etkinleştir</b> düğmesine basın.<br><br>"
        "Sayfa 'API etkin' diyorsa zaten yapılmış demektir, sonraki adıma geçin.",
        "https://console.cloud.google.com/apis/library/drive.googleapis.com",
        "Drive API sayfasını aç",
    ),
    (
        "OAuth izin ekranını doldurun",
        "Kullanıcı türü olarak <b>Harici</b> seçin → <b>Oluştur</b>.<br>"
        "Uygulama adı: <b>Docvera</b>, kullanıcı destek e-postası ve geliştirici "
        "e-postası olarak kendi adresinizi yazın → <b>Kaydet ve devam et</b>.<br>"
        "Kapsam (scope) eklemenize gerek yok, geçin.<br><br>"
        "<span style='color:#b8860b'><b>Önemli:</b> En sonda <b>Uygulamayı yayınla</b> "
        "(Publish app) düğmesine basın. \"Test\" durumunda kalırsa yetkilendirme "
        "<b>7 günde bir düşer</b> ve her hafta yeniden bağlanmanız gerekir. "
        "Yayınlamak Google onayı gerektirmez, hemen etkin olur.</span>",
        "https://console.cloud.google.com/apis/credentials/consent",
        "İzin ekranı sayfasını aç",
    ),
    (
        "Masaüstü istemcisi oluşturun ve indirin",
        "<b>Kimlik bilgileri oluştur</b> → <b>OAuth istemci kimliği</b>.<br>"
        "Uygulama türü: <b>Masaüstü uygulaması</b> → Ad: <b>Docvera</b> → "
        "<b>Oluştur</b>.<br>"
        "Açılan pencerede <b>JSON'u indir</b> düğmesine basın.<br><br>"
        "<span style='color:#c0392b'><b>Dikkat:</b> Uygulama türü mutlaka "
        "<b>Masaüstü uygulaması</b> olmalı. \"Web uygulaması\" seçilirse dosya "
        "bu programda çalışmaz.</span>",
        "https://console.cloud.google.com/apis/credentials",
        "Kimlik bilgileri sayfasını aç",
    ),
    (
        "İndirdiğiniz dosyayı seçin",
        "Bu pencereyi kapatın ve <b>Kendi Google hesabımla bağlan</b> "
        "bölümündeki <b>Dosya seç</b> düğmesine basıp indirdiğiniz JSON "
        "dosyasını gösterin.<br><br>"
        "Dosyayı yeniden adlandırmanıza veya bir klasöre kopyalamanıza gerek "
        "yok; program gerekeni kendisi yapar ve dosyanın doğru türde olduğunu "
        "kontrol eder.",
        "",
        "",
    ),
]


class DriveRehberDiyalogu(QDialog):
    """Google Cloud kurulum adimlarini sirayla gosterir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kendi Google hesabımla bağlanma - Adım adım")
        self.resize(720, 640)

        duzen = QVBoxLayout(self)

        giris = QLabel(
            "Bu adımlar <b>bir kez</b> yapılır ve yaklaşık 5 dakika sürer. "
            "Sonrasında bu bilgisayarda bir daha gerekmez.<br><br>"
            "Her adımdaki düğme ilgili Google sayfasını tarayıcınızda açar."
        )
        giris.setWordWrap(True)
        giris.setStyleSheet("font-size: 12px; padding: 4px;")
        duzen.addWidget(giris)

        duzen.addWidget(self._adim_listesi(), 1)

        alt = QHBoxLayout()
        kopyala = QPushButton("Adımları panoya kopyala")
        kopyala.setToolTip("Başka birine göndermek veya yazdırmak için")
        kopyala.clicked.connect(self._panoya_kopyala)
        alt.addWidget(kopyala)
        alt.addStretch(1)

        dugmeler = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        dugmeler.button(QDialogButtonBox.StandardButton.Close).setText("Kapat")
        dugmeler.rejected.connect(self.reject)
        alt.addWidget(dugmeler)
        duzen.addLayout(alt)

    def _adim_listesi(self) -> QScrollArea:
        kapsayici = QWidget()
        ic_duzen = QVBoxLayout(kapsayici)
        ic_duzen.setSpacing(14)

        for sira, (baslik, aciklama, baglanti, dugme_metni) in enumerate(ADIMLAR, 1):
            ic_duzen.addWidget(self._adim_karti(sira, baslik, aciklama, baglanti, dugme_metni))

        ic_duzen.addStretch(1)

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setWidget(kapsayici)
        kaydirma.setFrameShape(QFrame.Shape.NoFrame)
        return kaydirma

    def _adim_karti(
        self, sira: int, baslik: str, aciklama: str, baglanti: str, dugme_metni: str
    ) -> QFrame:
        kart = QFrame()
        kart.setFrameShape(QFrame.Shape.StyledPanel)
        kart.setStyleSheet(
            "QFrame { background: palette(base); border: 1px solid palette(mid);"
            " border-radius: 6px; padding: 6px; }"
        )
        duzen = QVBoxLayout(kart)

        baslik_etiketi = QLabel(f"<b>{sira}. {baslik}</b>")
        baslik_etiketi.setStyleSheet("font-size: 13px; border: none;")
        duzen.addWidget(baslik_etiketi)

        metin = QLabel(aciklama)
        metin.setWordWrap(True)
        metin.setTextFormat(Qt.TextFormat.RichText)
        metin.setStyleSheet("font-size: 12px; border: none;")
        duzen.addWidget(metin)

        if baglanti:
            ac = QPushButton(dugme_metni)
            ac.clicked.connect(lambda _, u=baglanti: self._baglantiyi_ac(u))
            satir = QHBoxLayout()
            satir.addWidget(ac)
            satir.addStretch(1)
            duzen.addLayout(satir)

        return kart

    @staticmethod
    def _baglantiyi_ac(adres: str) -> None:
        """Baglantiyi varsayilan tarayicida acar."""
        from PySide6.QtCore import QUrl

        if not QDesktopServices.openUrl(QUrl(adres)):
            webbrowser.open(adres)  # Qt acamazsa yedek yol

    def _panoya_kopyala(self) -> None:
        import re

        satirlar = []
        for sira, (baslik, aciklama, baglanti, _) in enumerate(ADIMLAR, 1):
            duz = re.sub(r"<[^>]+>", "", aciklama).replace("&nbsp;", " ")
            duz = re.sub(r"\n\s*", " ", duz).strip()
            satirlar.append(f"{sira}. {baslik}\n   {duz}")
            if baglanti:
                satirlar.append(f"   Bağlantı: {baglanti}")
            satirlar.append("")
        QGuiApplication.clipboard().setText("\n".join(satirlar))
