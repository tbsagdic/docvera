"""Ana pencere: musteri formu, tarayici secimi, sayfa seridi ve kayit."""

from __future__ import annotations

import datetime as _dt
import getpass
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import (
    QBitmap,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QRegion,
    QShortcut,
    QTransform,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import Ayarlar, gecici_klasor
from app.db import BEKLIYOR, MANUEL, TAMAM, Veritabani
from app.scanner.base import Kaynak, TaramaAyarlari
from app.storage.paths import goreli_parcalar, kayit_klasoru, pdf_dosya_adi
from app.storage.writer import meta_yaz, pdf_uret, sayfalari_yaz
from app.ui.preview_dialog import ONAYLA_VE_DEVAM, OnizlemeDiyalogu
from app.ui.workers import (
    AktarimIscisi,
    CihazListeIscisi,
    KimlikOkumaIscisi,
    TaramaIscisi,
    YetenekIscisi,
)
from app.validation import (
    ad_normalize,
    dogum_tarihi_ayristir,
    tc_hata_mesaji,
    tc_normalize,
)
from app.varliklar import YATAY_LOGO, varlik_yolu

KUCUK_RESIM = QSize(72, 100)
SAYFA_GRID = QSize(90, 134)  # bir kucuk resim hucresi
SAYFA_ARALIK = 4
# Serit tek seferde 5x2 = 10 sayfa gosterir; fazlasi sonraki serit sayfasina
SAYFA_SUTUN = 5
SAYFA_SATIR = 2
SERIT_SAYFA_BOYU = SAYFA_SUTUN * SAYFA_SATIR
# Logo yuksekligi; genislik cizimin kendi oranindan hesaplanir
LOGO_YUKSEKLIGI = 68
# Logo once bu kat kadar buyuk cizilir, sonra kucultulur: kenarlar keskin kalir
LOGO_OLCUM_KATI = 3


def logo_pixmapi(yukseklik: int) -> QPixmap:
    """Yatay logoyu cevresindeki bos paydan arindirip verilen yukseklige getirir.

    Dosyanin viewBox'i cizimin cevresinde genis pay birakir. Pay sabit degildir:
    yazi tipi rasterleme boyutuna gore olculdugunden wordmark'in genisligi de
    boyutla degisir, sabit bir kirpma dikdortgeni logonun sagini kesiyor. Bu
    yuzden logo once bol payli ve yuksek cozunurlukte cizilir, gercek siniri
    piksellerden olculur, kirpilir ve istenen yukseklige kucultulur.
    """
    cizici = QSvgRenderer(str(varlik_yolu(YATAY_LOGO)))
    tuval = cizici.viewBoxF()
    olcek = LOGO_OLCUM_KATI * yukseklik / tuval.height()

    goruntu = QImage(
        round(tuval.width() * olcek),
        round(tuval.height() * olcek),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    goruntu.fill(Qt.GlobalColor.transparent)
    boyayici = QPainter(goruntu)
    boyayici.setRenderHint(QPainter.RenderHint.Antialiasing)
    cizici.render(boyayici)
    boyayici.end()

    sinir = QRegion(QBitmap.fromImage(goruntu.createAlphaMask())).boundingRect()
    return QPixmap.fromImage(goruntu.copy(sinir)).scaledToHeight(
        yukseklik, Qt.TransformationMode.SmoothTransformation
    )


class TaslakSayfa:
    """Onaylanmis ama henuz arsive yazilmamis sayfa."""

    def __init__(self, gecici_yol: str):
        self.gecici_yol = Path(gecici_yol)
        self.donme = 0


class AnaPencere(QMainWindow):
    def __init__(self, ayarlar: Ayarlar, vt: Veritabani, kuyruk=None):
        super().__init__()
        self.ayarlar = ayarlar
        self.vt = vt
        self.kuyruk = kuyruk  # app.drive.queue.YuklemeKuyrugu veya None
        self.taslaklar: list[TaslakSayfa] = []
        self._serit_sayfasi = 0  # seritte gosterilen 10'luk kume
        self.cihazlar: list = []
        self.tarama_iscisi: TaramaIscisi | None = None
        self.liste_iscisi: CihazListeIscisi | None = None
        self.yetenek_iscisi: YetenekIscisi | None = None
        self.kimlik_iscisi: KimlikOkumaIscisi | None = None
        self.aktarim_iscisi = None
        self._ocr_sirasi: list[str] = []  # sirayla okunacak sayfa yollari
        self._ocr_calisiyor = False
        self.oturum_klasoru = gecici_klasor() / f"oturum_{_dt.datetime.now():%Y%m%d_%H%M%S}"
        self.oturum_klasoru.mkdir(parents=True, exist_ok=True)

        self.setWindowTitle("Docvera - Müşteri Evrak Tarama")
        self.resize(1000, 720)
        self.setAcceptDrops(True)  # PDF/goruntu surukleyip birakmak icin
        self._arayuzu_kur()
        self._menuyu_kur()
        self._kisayollari_kur()

        self.cihazlari_yenile()
        self._esitleme_onbellek_kok = ""
        self._esitleme_onbellek = None
        self._durum_zamanlayici = QTimer(self)
        self._durum_zamanlayici.timeout.connect(self._drive_durumunu_yenile)
        self._durum_zamanlayici.start(3000)
        self._drive_durumunu_yenile()
        self._guncellemeyi_kur()

    # --- Arayuz kurulumu --------------------------------------------------

    def _arayuzu_kur(self) -> None:
        merkez = QWidget()
        self.setCentralWidget(merkez)
        ana_duzen = QHBoxLayout(merkez)

        sol = QVBoxLayout()
        sol.addWidget(self._logo_seridi())
        sol.addWidget(self._musteri_kutusu())
        sol.addWidget(self._tarayici_kutusu())
        sol.addWidget(self._tara_dugmesi())
        sol.addStretch(1)
        sol.addWidget(self._kaydet_dugmesi())

        sag = QVBoxLayout()
        sag.addWidget(self._sayfa_kutusu())
        sag.addStretch(1)

        ana_duzen.addLayout(sol, 0)
        ana_duzen.addLayout(sag, 0)
        ana_duzen.addStretch(1)

        self.durum_etiketi = QLabel()
        self.statusBar().addPermanentWidget(self.durum_etiketi)

    def _logo_seridi(self) -> QLabel:
        """Sol panelin ustundeki marka seridi."""
        oran = self.devicePixelRatioF()
        pixmap = logo_pixmapi(round(LOGO_YUKSEKLIGI * oran))
        pixmap.setDevicePixelRatio(oran)

        etiket = QLabel()
        etiket.setPixmap(pixmap)
        etiket.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return etiket

    def _musteri_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Müşteri Bilgileri")
        duzen = QFormLayout(kutu)

        self.ad_alani = QLineEdit()
        self.soyad_alani = QLineEdit()
        self.tc_alani = QLineEdit()
        # Bilerek setMaxLength kullanilmiyor: alan uzunlugu once kirpar, rakam
        # disi karakterler ancak sonra ayiklanirdi. "100 000 001-46" yapistiran
        # kasiyer 11 karakterlik "100 000 001" -> 9 haneli TC ile kalirdi.
        # Kirpma _tc_degisti icinde, rakamlar ayiklandiktan SONRA yapiliyor.
        self.tc_alani.setPlaceholderText("11 haneli TC Kimlik No")
        self.dogum_alani = QLineEdit()
        self.dogum_alani.setPlaceholderText("GG.AA.YYYY (isteğe bağlı)")

        for alan in (self.ad_alani, self.soyad_alani, self.tc_alani, self.dogum_alani):
            alan.setMinimumWidth(260)

        self.tc_alani.textChanged.connect(self._tc_degisti)
        self.ad_alani.textChanged.connect(self._formu_denetle)
        self.soyad_alani.textChanged.connect(self._formu_denetle)
        # Kasiyer alana dokundugunda 'onay bekliyor' vurgusu kalkar
        self.ad_alani.editingFinished.connect(lambda: self._ad_onayini_isaretle(False))
        self.soyad_alani.editingFinished.connect(lambda: self._ad_onayini_isaretle(False))

        self.tc_uyari = QLabel()
        self.tc_uyari.setWordWrap(True)
        self.tc_uyari.setStyleSheet("color: #c0392b;")

        self.gecmis_etiketi = QLabel()
        self.gecmis_etiketi.setWordWrap(True)
        self.gecmis_etiketi.setStyleSheet("color: #1f6f43;")

        duzen.addRow("Ad", self.ad_alani)
        duzen.addRow("Soyad", self.soyad_alani)
        duzen.addRow("TC Kimlik No", self.tc_alani)
        duzen.addRow("Doğum Tarihi", self.dogum_alani)
        duzen.addRow("", self.tc_uyari)
        duzen.addRow("", self.gecmis_etiketi)
        return kutu

    def _tarayici_kutusu(self) -> QGroupBox:
        kutu = QGroupBox("Tarayıcı")
        duzen = QFormLayout(kutu)

        self.cihaz_kutusu = QComboBox()
        self.cihaz_kutusu.currentIndexChanged.connect(self._cihaz_secildi)

        self.yenile_dugmesi = QPushButton("Yenile")
        self.yenile_dugmesi.clicked.connect(self.cihazlari_yenile)

        cihaz_satiri = QHBoxLayout()
        cihaz_satiri.addWidget(self.cihaz_kutusu, 1)
        cihaz_satiri.addWidget(self.yenile_dugmesi)
        cihaz_sarici = QWidget()
        cihaz_sarici.setLayout(cihaz_satiri)

        self.kaynak_kutusu = QComboBox()
        self.kaynak_kutusu.addItem("Cam (tek sayfa)", Kaynak.CAM)
        self.kaynak_kutusu.addItem("Besleyici (çok sayfa)", Kaynak.BESLEYICI)

        self.dpi_kutusu = QComboBox()
        for dpi in (150, 200, 300, 400, 600):
            self.dpi_kutusu.addItem(f"{dpi} DPI", dpi)
        self.dpi_kutusu.setCurrentText(f"{self.ayarlar.varsayilan_dpi} DPI")

        self.renkli_kutusu = QCheckBox("Renkli tara")
        self.renkli_kutusu.setChecked(self.ayarlar.renkli_tara)

        duzen.addRow("Cihaz", cihaz_sarici)
        duzen.addRow("Kaynak", self.kaynak_kutusu)
        duzen.addRow("Çözünürlük", self.dpi_kutusu)
        duzen.addRow("", self.renkli_kutusu)
        return kutu

    def _tara_dugmesi(self) -> QWidget:
        sarici = QWidget()
        duzen = QVBoxLayout(sarici)
        duzen.setContentsMargins(0, 0, 0, 0)

        self.tara_dugmesi = QPushButton("TARA  (F5)")
        self.tara_dugmesi.setMinimumHeight(56)
        self.tara_dugmesi.setStyleSheet(
            "font-size: 17px; font-weight: bold; background: #1f6f43; color: white;"
        )
        self.tara_dugmesi.clicked.connect(self.tara)

        # Tarayici her zaman kullanilabilir olmuyor: evrak WhatsApp'tan gelmis
        # ya da baska bir bilgisayarda taranmis olabilir.
        self.aktar_dugmesi = QPushButton("Dosyadan Ekle  (Ctrl+O)")
        self.aktar_dugmesi.setMinimumHeight(38)
        self.aktar_dugmesi.setToolTip(
            "PDF veya görüntü dosyası seçin. Dosyaları pencereye sürükleyip "
            "bırakabilirsiniz."
        )
        self.aktar_dugmesi.clicked.connect(self.dosyadan_ekle)

        self.ilerleme = QProgressBar()
        self.ilerleme.setRange(0, 0)  # belirsiz sure
        self.ilerleme.setVisible(False)

        duzen.addWidget(self.tara_dugmesi)
        duzen.addWidget(self.aktar_dugmesi)
        duzen.addWidget(self.ilerleme)
        return sarici

    def _kaydet_dugmesi(self) -> QWidget:
        sarici = QWidget()
        duzen = QVBoxLayout(sarici)
        duzen.setContentsMargins(0, 0, 0, 0)

        self.kaydet_dugmesi = QPushButton("KAYDET  (Ctrl+S)")
        self.kaydet_dugmesi.setMinimumHeight(48)
        self.kaydet_dugmesi.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.kaydet_dugmesi.clicked.connect(self.kaydet)
        self.kaydet_dugmesi.setEnabled(False)

        self.hedef_etiketi = QLabel()
        self.hedef_etiketi.setWordWrap(True)
        self.hedef_etiketi.setStyleSheet("color: #666; font-size: 11px;")

        duzen.addWidget(self.hedef_etiketi)
        duzen.addWidget(self.kaydet_dugmesi)
        return sarici

    def _serit_olcusu(self) -> QSize:
        """Tam SAYFA_SUTUN x SAYFA_SATIR hucre alan serit boyutu."""
        hucre_en = SAYFA_GRID.width() + 2 * SAYFA_ARALIK
        hucre_boy = SAYFA_GRID.height() + 2 * SAYFA_ARALIK
        cerceve = 2 * self.sayfa_listesi.frameWidth()
        return QSize(
            SAYFA_SUTUN * hucre_en + cerceve,
            SAYFA_SATIR * hucre_boy + cerceve,
        )

    def _sayfa_kutusu(self) -> QGroupBox:
        self.sayfa_grubu = QGroupBox("Taranan Sayfalar")
        kutu = self.sayfa_grubu
        duzen = QVBoxLayout(kutu)

        self.sayfa_listesi = QListWidget()
        self.sayfa_listesi.setViewMode(QListWidget.ViewMode.IconMode)
        self.sayfa_listesi.setIconSize(KUCUK_RESIM)
        self.sayfa_listesi.setGridSize(SAYFA_GRID)
        self.sayfa_listesi.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.sayfa_listesi.setMovement(QListWidget.Movement.Static)
        self.sayfa_listesi.setSpacing(SAYFA_ARALIK)
        # Serit tam bir kumeyi gosterir; kaydirma yok, kume degistirilir
        self.sayfa_listesi.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.sayfa_listesi.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.sayfa_listesi.setFixedSize(self._serit_olcusu())

        self.onceki_dugmesi = QPushButton("‹")
        self.onceki_dugmesi.setFixedWidth(28)
        self.onceki_dugmesi.clicked.connect(lambda: self._serit_sayfasini_kaydir(-1))
        self.sonraki_dugmesi = QPushButton("›")
        self.sonraki_dugmesi.setFixedWidth(28)
        self.sonraki_dugmesi.clicked.connect(lambda: self._serit_sayfasini_kaydir(1))
        self.serit_etiketi = QLabel()

        self.sil_dugmesi = QPushButton("Seçili sayfayı sil")
        self.sil_dugmesi.clicked.connect(self.secili_sayfayi_sil)
        self.sol_dugmesi = QPushButton("↺ Sola döndür")
        self.sol_dugmesi.clicked.connect(lambda: self.secili_sayfayi_dondur(-90))
        self.sag_dugmesi = QPushButton("↻ Sağa döndür")
        self.sag_dugmesi.clicked.connect(lambda: self.secili_sayfayi_dondur(90))

        arac = QHBoxLayout()
        arac.addWidget(self.sol_dugmesi)
        arac.addWidget(self.sag_dugmesi)
        arac.addWidget(self.sil_dugmesi)
        arac.addStretch(1)
        arac.addWidget(self.onceki_dugmesi)
        arac.addWidget(self.serit_etiketi)
        arac.addWidget(self.sonraki_dugmesi)

        duzen.addWidget(self.sayfa_listesi, 1)
        duzen.addLayout(arac)
        return kutu

    def _menuyu_kur(self) -> None:
        dosya = self.menuBar().addMenu("&Dosya")
        dosya.addAction("Dosyadan ekle (PDF/görüntü)...\tCtrl+O", self.dosyadan_ekle)
        dosya.addAction("Geçmiş kayıtlar...\tCtrl+F", self.gecmisi_ac)
        dosya.addAction("Arşiv klasörünü aç", self.arsivi_ac)
        dosya.addSeparator()
        dosya.addAction("Çıkış", self.close)

        araclar = self.menuBar().addMenu("&Araçlar")
        araclar.addAction("Ayarlar...", self.ayarlari_ac)
        araclar.addAction("Tarayıcı listesini yenile", self.cihazlari_yenile)
        self.yeniden_dene_eylemi = araclar.addAction(
            "Yüklenemeyen dosyaları yeniden dene", self.yuklemeleri_yeniden_dene
        )

        yardim = self.menuBar().addMenu("&Yardım")
        yardim.addAction("Güncellemeleri denetle...", self.guncellemeleri_denetle)
        yardim.addSeparator()
        yardim.addAction("Hakkında", self.hakkinda)

    def _kisayollari_kur(self) -> None:
        QShortcut(QKeySequence("F5"), self, self.tara)
        QShortcut(QKeySequence("Ctrl+S"), self, self.kaydet)
        QShortcut(QKeySequence("Ctrl+F"), self, self.gecmisi_ac)
        QShortcut(QKeySequence("Ctrl+O"), self, self.dosyadan_ekle)
        QShortcut(QKeySequence("Delete"), self.sayfa_listesi, self.secili_sayfayi_sil)

    # --- Menu eylemleri ---------------------------------------------------

    def gecmisi_ac(self) -> None:
        from app.ui.history_view import GecmisDiyalogu

        GecmisDiyalogu(self.vt, self).exec()

    def arsivi_ac(self) -> None:
        import os

        kok = Path(self.ayarlar.kok_klasor)
        if not kok.is_dir():
            QMessageBox.warning(
                self, "Arşiv klasörü",
                f"Arşiv klasörü bulunamadı:\n{kok}\n\nAyarlardan konumu düzeltin.",
            )
            return
        os.startfile(kok)  # noqa: S606 - Windows Gezgini

    def ayarlari_ac(self) -> None:
        from app.ui.settings_dialog import AyarlarDiyalogu

        diyalog = AyarlarDiyalogu(self.ayarlar, self.vt, self)
        if diyalog.exec():
            self.dpi_kutusu.setCurrentText(f"{self.ayarlar.varsayilan_dpi} DPI")
            self.renkli_kutusu.setChecked(self.ayarlar.renkli_tara)
            self._formu_denetle()
            self._drive_durumunu_yenile()

    def yuklemeleri_yeniden_dene(self) -> None:
        adet = self.vt.kuyruk_sifirla(sadece_manuel=True)
        if self.kuyruk is not None:
            self.kuyruk.tetikle()
        self.statusBar().showMessage(
            f"{adet} dosya yeniden denemeye alındı." if adet
            else "Yeniden denenecek dosya yok.",
            5000,
        )
        self._drive_durumunu_yenile()

    # --- Guncelleme -------------------------------------------------------

    def _guncellemeyi_kur(self) -> None:
        """Guncelleme denetleyicisini kurar ve acilis islerini yapar."""
        from app.ui.guncelleme_dialog import GuncellemeDenetleyici

        self.guncelleme = GuncellemeDenetleyici(
            self.ayarlar, self, engel=self._guncelleme_engeli
        )
        self.guncelleme.bilgi.connect(self._guncelleme_bilgisi)
        self._onceki_kurulumu_bildir()
        self.guncelleme.acilista_denetle()

    def guncellemeleri_denetle(self) -> None:
        """Yardim menusundeki elle denetim."""
        self.guncelleme.denetle(sessiz=False)

    def _guncelleme_bilgisi(self, mesaj: str, sure: int) -> None:
        if mesaj:
            self.statusBar().showMessage(mesaj, sure)
        else:
            self.statusBar().clearMessage()

    def _guncelleme_engeli(self) -> str:
        """Kurulum su an sakincaliysa gerekcesini dondurur.

        Kurulum uygulamayi kapatir; kaydedilmemis taranmis sayfa varsa bu
        sayfalar silinir. Kullaniciyi bu secimle karsilastirmak yerine
        guncellemeyi erteletmek daha guvenli.
        """
        if self.taslaklar:
            return (
                f"{len(self.taslaklar)} taranmış sayfa henüz kaydedilmedi. "
                "Güncelleme uygulamayı kapatacağı için önce kaydı tamamlayın, "
                "sonra tekrar deneyin."
            )
        return ""

    def _onceki_kurulumu_bildir(self) -> None:
        """Bir onceki oturumda baslatilan kurulumun sonucunu gosterir."""
        from app.guncelleme import (
            eski_dosyalari_temizle,
            sonucu_al,
            yarim_kalan_kurulum,
        )

        durum, mesaj = sonucu_al()
        if durum == "tamam":
            self.statusBar().showMessage(mesaj, 10000)
            eski_dosyalari_temizle()  # indirilen paket artik gereksiz
            return
        if durum == "hata":
            QMessageBox.warning(
                self,
                "Güncelleme tamamlanamadı",
                f"{mesaj}\n\nÖnceki sürüm çalışmaya devam ediyor. "
                "Yardım menüsünden yeniden deneyebilirsiniz.",
            )
            return

        # Sonuc dosyasi yok ama kurulum betigi kalmissa betik hic calismamis
        if yarim_kalan_kurulum():
            QMessageBox.warning(
                self,
                "Güncelleme tamamlanamadı",
                "Başlatılan güncelleme tamamlanmadı; uygulama önceki sürümde "
                "kaldı. Güvenlik yazılımı kurulum betiğini engellemiş olabilir."
                "\n\nYardım menüsünden yeniden deneyebilirsiniz.",
            )

    def hakkinda(self) -> None:
        from app.config import UYGULAMA_SURUMU
        from app.guncelleme import DEPO

        QMessageBox.about(
            self,
            "Docvera hakkında",
            f"<b>Docvera</b> {UYGULAMA_SURUMU}<br><br>"
            "Müşteri evrağı tarama ve arşivleme uygulaması.<br><br>"
            f"Kaynak kod ve sürümler:<br>"
            f"<a href='https://github.com/{DEPO}'>github.com/{DEPO}</a>",
        )

    # --- Cihaz yonetimi ---------------------------------------------------

    def cihazlari_yenile(self) -> None:
        """Tarayici listesini arka planda tazeler."""
        self.yenile_dugmesi.setEnabled(False)
        self.cihaz_kutusu.clear()
        self.cihaz_kutusu.addItem("Aranıyor...", None)

        self.liste_iscisi = CihazListeIscisi(self)
        self.liste_iscisi.tamamlandi.connect(self._cihazlar_geldi)
        self.liste_iscisi.hata.connect(self._cihaz_listesi_hatasi)
        self.liste_iscisi.finished.connect(
            lambda: self.yenile_dugmesi.setEnabled(True)
        )
        self.liste_iscisi.start()

    def _cihazlar_geldi(self, cihazlar: list) -> None:
        self.cihazlar = cihazlar
        self.cihaz_kutusu.clear()
        if not cihazlar:
            self.cihaz_kutusu.addItem("Tarayıcı bulunamadı", None)
            self.statusBar().showMessage(
                "Tarayıcı bulunamadı. Cihazı açıp 'Yenile' düğmesine basın.", 8000
            )
        else:
            for cihaz in cihazlar:
                self.cihaz_kutusu.addItem(cihaz.ad, cihaz.cihaz_id)
            # Son kullanilan cihazi hatirla
            if self.ayarlar.son_cihaz_id:
                indeks = self.cihaz_kutusu.findData(self.ayarlar.son_cihaz_id)
                if indeks >= 0:
                    self.cihaz_kutusu.setCurrentIndex(indeks)
        self._formu_denetle()

    def _cihaz_listesi_hatasi(self, mesaj: str) -> None:
        self.cihaz_kutusu.clear()
        self.cihaz_kutusu.addItem("Tarayıcı bulunamadı", None)
        self.statusBar().showMessage(mesaj, 8000)

    def _cihaz_secildi(self) -> None:
        cihaz_id = self.cihaz_kutusu.currentData()
        if not cihaz_id:
            return
        self.ayarlar.son_cihaz_id = cihaz_id
        # Besleyici destegi ancak cihaza baglanildiginda ogrenilebilir
        self.yetenek_iscisi = YetenekIscisi(cihaz_id, self)
        self.yetenek_iscisi.tamamlandi.connect(self._yetenekler_geldi)
        self.yetenek_iscisi.start()
        self._formu_denetle()

    def _yetenekler_geldi(self, cihaz) -> None:
        indeks = self.kaynak_kutusu.findData(Kaynak.BESLEYICI)
        if indeks < 0:
            return
        model = self.kaynak_kutusu.model()
        oge = model.item(indeks)
        oge.setEnabled(cihaz.besleyici_var)
        if not cihaz.besleyici_var:
            oge.setText("Besleyici (bu cihazda yok)")
            if self.kaynak_kutusu.currentIndex() == indeks:
                self.kaynak_kutusu.setCurrentIndex(
                    self.kaynak_kutusu.findData(Kaynak.CAM)
                )
        else:
            oge.setText("Besleyici (çok sayfa)")

    # --- Form dogrulama ---------------------------------------------------

    def _tc_degisti(self, metin: str) -> None:
        # Kasiyer bosluklu/tireli TC yapistirmis olabilir: once rakamlari
        # ayikla, sonra 11 haneye kirp.
        temiz = tc_normalize(metin)[:11]
        if temiz != metin:
            self.tc_alani.setText(temiz)  # tekrar _tc_degisti tetiklenir
            return

        hata = tc_hata_mesaji(temiz) if temiz else None
        self.tc_uyari.setText("" if not temiz else (hata or ""))
        self.tc_alani.setStyleSheet(
            "border: 1px solid #c0392b;" if (temiz and hata) else ""
        )

        self.gecmis_etiketi.setText("")
        if temiz and not hata:
            self._gecmisi_goster(temiz)
        self._formu_denetle()

    def _gecmisi_goster(self, tc: str) -> None:
        """Musteri daha once geldiyse kasiyeri bilgilendirir ve alanlari doldurur."""
        musteri = self.vt.musteri_bul(tc)
        if musteri is None:
            return
        if not self.ad_alani.text().strip():
            self.ad_alani.setText(musteri["ad"])
        if not self.soyad_alani.text().strip():
            self.soyad_alani.setText(musteri["soyad"])
        if musteri["dogum_tarihi"] and not self.dogum_alani.text().strip():
            try:
                gun = _dt.date.fromisoformat(musteri["dogum_tarihi"])
                self.dogum_alani.setText(f"{gun.day:02d}.{gun.month:02d}.{gun.year}")
            except ValueError:
                pass

        gecmis = self.vt.musteri_gecmisi(tc, sinir=3)
        if gecmis:
            tarihler = ", ".join(
                _dt.date.fromisoformat(k["tarih"]).strftime("%d.%m.%Y") for k in gecmis
            )
            self.gecmis_etiketi.setText(
                f"Bu müşteri daha önce geldi: {tarihler}"
                + (f" (+{len(gecmis)} kayıt)" if len(gecmis) > 2 else "")
            )

    def _formu_denetle(self) -> None:
        gecerli = self._form_gecerli_mi()
        # TARA yalnizca tarayici secilmis olmasini ister. Musteri bilgisi
        # sarti KAYDET'tedir: kimlik tarandiginda TC, ad soyad ve dogum
        # tarihi MRZ'den zaten dolduruluyor - once form doldurmayi zorunlu
        # tutmak kasiyere ayni bilgiyi iki kez girdirirdi.
        aktarim_suruyor = (
            self.aktarim_iscisi is not None and self.aktarim_iscisi.isRunning()
        )
        self.tara_dugmesi.setEnabled(
            bool(self.cihaz_kutusu.currentData()) and not aktarim_suruyor
        )
        self.kaydet_dugmesi.setEnabled(gecerli and bool(self.taslaklar))
        self._hedefi_goster()

    def _form_gecerli_mi(self) -> bool:
        if not self.ad_alani.text().strip() or not self.soyad_alani.text().strip():
            return False
        tc = tc_normalize(self.tc_alani.text())
        if tc_hata_mesaji(tc) is not None:
            return False
        try:
            dogum_tarihi_ayristir(self.dogum_alani.text())
        except ValueError:
            return False
        return True

    def _hedefi_goster(self) -> None:
        """Kayit hedefini ya da KAYDET'in neden kapali oldugunu gosterir.

        Tarama artik form doldurulmadan yapilabildigi icin, kimlik okunamadigi
        durumda kasiyer neyin eksik oldugunu buradan gorur.
        """
        if self._form_gecerli_mi():
            self.hedef_etiketi.setStyleSheet("color: #666; font-size: 11px;")
            self.hedef_etiketi.setText(f"Kayıt yeri:\n{self._hedef_klasor()}")
            return

        if not self.taslaklar:
            self.hedef_etiketi.setText("")
            return

        eksikler = []
        if not self.ad_alani.text().strip():
            eksikler.append("ad")
        if not self.soyad_alani.text().strip():
            eksikler.append("soyad")
        if tc_hata_mesaji(tc_normalize(self.tc_alani.text())) is not None:
            eksikler.append("geçerli TC")
        self.hedef_etiketi.setStyleSheet("color: #b8860b; font-size: 11px;")
        self.hedef_etiketi.setText(
            f"Kaydetmek için {', '.join(eksikler)} girin."
            if eksikler
            else "Doğum tarihi biçimi hatalı."
        )

    def _hedef_klasor(self) -> Path:
        return kayit_klasoru(
            self.ayarlar.kok_klasor,
            ad_normalize(self.ad_alani.text()),
            ad_normalize(self.soyad_alani.text()),
            tc_normalize(self.tc_alani.text()),
            _dt.date.today(),
            sube=self.ayarlar.sube,
        )

    # --- Tarama -----------------------------------------------------------

    def _tarama_ayarlari(self) -> TaramaAyarlari:
        return TaramaAyarlari(
            dpi=int(self.dpi_kutusu.currentData()),
            renkli=self.renkli_kutusu.isChecked(),
            kaynak=self.kaynak_kutusu.currentData(),
        )

    def tara(self) -> None:
        if self.tarama_iscisi is not None and self.tarama_iscisi.isRunning():
            return
        cihaz_id = self.cihaz_kutusu.currentData()
        if not cihaz_id:
            QMessageBox.warning(
                self, "Tarayıcı yok", "Önce bir tarayıcı seçin. Cihaz listesini "
                "yenilemek için 'Yenile' düğmesini kullanın."
            )
            return
        self._tarama_kilidi(True)
        self.statusBar().showMessage("Taranıyor...")

        self.tarama_iscisi = TaramaIscisi(
            cihaz_id, self._tarama_ayarlari(), self.oturum_klasoru, self
        )
        self.tarama_iscisi.tamamlandi.connect(self._tarama_bitti)
        self.tarama_iscisi.hata.connect(self._tarama_hatasi)
        self.tarama_iscisi.start()

    def _tarama_kilidi(self, calisiyor: bool) -> None:
        self.tara_dugmesi.setEnabled(not calisiyor)
        self.yenile_dugmesi.setEnabled(not calisiyor)
        self.ilerleme.setVisible(calisiyor)

    def _tarama_bitti(self, yollar: list) -> None:
        self._tarama_kilidi(False)
        self.statusBar().clearMessage()
        for yol in yollar:
            devam = self._onaya_sun(yol)
            if devam:
                self.tara()
                return

    def _tarama_hatasi(self, mesaj: str, iptal_mi: bool) -> None:
        self._tarama_kilidi(False)
        self.statusBar().clearMessage()
        if iptal_mi:
            self.statusBar().showMessage("Tarama iptal edildi.", 4000)
            return
        QMessageBox.critical(self, "Tarama hatası", mesaj)

    def _onaya_sun(self, gecici_yol: str) -> bool:
        """Sayfayi onizlemede gosterir. 'Onayla ve Tekrar Tara' secilirse True doner."""
        diyalog = OnizlemeDiyalogu(gecici_yol, len(self.taslaklar) + 1, self)
        diyalog.exec()

        if diyalog.karar == 0:
            # Reddedilen sayfa arsive hic girmez, gecici dosyasi da silinir
            Path(gecici_yol).unlink(missing_ok=True)
            return False

        taslak = TaslakSayfa(gecici_yol)
        taslak.donme = diyalog.donme
        self.taslaklar.append(taslak)
        self._sayfa_listesini_yenile(len(self.taslaklar) - 1)
        self._formu_denetle()
        self._kimligi_oku(gecici_yol)
        return diyalog.karar == ONAYLA_VE_DEVAM

    # --- Dosyadan ice aktarma --------------------------------------------

    def dosyadan_ekle(self, dosyalar: list[str] | None = None) -> None:
        """PDF veya goruntu dosyalarindan sayfa ekler.

        Taramadan gelen sayfalarla tamamen ayni sekilde islenir: onizleme,
        kimlik okuma, dondurme, kayit.
        """
        from app.storage.aktarim import AZAMI_SAYFA, dosya_filtresi

        if self.aktarim_iscisi is not None and self.aktarim_iscisi.isRunning():
            return

        if not dosyalar:
            dosyalar, _ = QFileDialog.getOpenFileNames(
                self, "Eklenecek belgeleri seçin", "", dosya_filtresi()
            )
        if not dosyalar:
            return

        if not self._sayfa_sayisini_onayla(dosyalar, AZAMI_SAYFA):
            return

        self._aktarim_kilidi(True)
        self.statusBar().showMessage(f"{len(dosyalar)} dosya aktarılıyor...")

        self.aktarim_iscisi = AktarimIscisi(
            dosyalar, self.oturum_klasoru, int(self.dpi_kutusu.currentData()), self
        )
        self.aktarim_iscisi.tamamlandi.connect(self._aktarim_bitti)
        self.aktarim_iscisi.start()

    def _sayfa_sayisini_onayla(self, dosyalar: list[str], azami: int) -> bool:
        """Kalin bir PDF yanlislikla secildiyse kullaniciya sorar."""
        from app.storage.aktarim import AktarimHatasi, sayfa_sayisi

        toplam = 0
        for dosya in dosyalar:
            try:
                toplam += sayfa_sayisi(dosya)
            except AktarimHatasi:
                toplam += 1  # okunamayan dosyanin hatasi aktarim sirasinda cikar

        if toplam <= 5:
            return True

        kirpma = (
            f"\n\nDosya başına en fazla {azami} sayfa alınır."
            if toplam > azami
            else ""
        )
        cevap = QMessageBox.question(
            self,
            "Çok sayfalı belge",
            f"Seçilen dosyalarda toplam {toplam} sayfa var.\n"
            f"Hepsi müşteri klasörüne eklenecek.{kirpma}\n\nDevam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return cevap == QMessageBox.StandardButton.Yes

    def _aktarim_kilidi(self, calisiyor: bool) -> None:
        self.aktar_dugmesi.setEnabled(not calisiyor)
        self.tara_dugmesi.setEnabled(
            not calisiyor and bool(self.cihaz_kutusu.currentData())
        )
        self.ilerleme.setVisible(calisiyor)

    def _aktarim_bitti(self, yollar: list, hatalar: list) -> None:
        self._aktarim_kilidi(False)
        self.statusBar().clearMessage()

        if hatalar:
            QMessageBox.warning(
                self, "Bazı dosyalar eklenemedi", "• " + "\n• ".join(hatalar)
            )
        if not yollar:
            return

        # Tek sayfa taramadaki gibi onaya sunulur; cok sayfada onizleme
        # yerine dogrudan seride eklenir, kasiyer serit uzerinden ayiklar.
        if len(yollar) == 1:
            self._onaya_sun(yollar[0])
            return

        for yol in yollar:
            self.taslaklar.append(TaslakSayfa(yol))
        self._sayfa_listesini_yenile(len(self.taslaklar) - 1)
        self._formu_denetle()
        self._kimligi_oku(*yollar)
        self.statusBar().showMessage(
            f"{len(yollar)} sayfa eklendi. İstemediğinizi şeritten silebilirsiniz.",
            8000,
        )

    # --- Surukle birak ----------------------------------------------------

    def dragEnterEvent(self, olay) -> None:  # noqa: N802 (Qt adlandirmasi)
        """Desteklenen dosyalar pencereye surukleniyorsa birakmaya izin ver."""
        from app.storage.aktarim import desteklenir_mi

        if not olay.mimeData().hasUrls():
            return
        if any(desteklenir_mi(u.toLocalFile()) for u in olay.mimeData().urls()):
            olay.acceptProposedAction()

    def dropEvent(self, olay) -> None:  # noqa: N802 (Qt adlandirmasi)
        from app.storage.aktarim import desteklenir_mi

        dosyalar = [
            u.toLocalFile()
            for u in olay.mimeData().urls()
            if u.isLocalFile() and desteklenir_mi(u.toLocalFile())
        ]
        if dosyalar:
            olay.acceptProposedAction()
            self.dosyadan_ekle(dosyalar)

    # --- Otomatik kimlik okuma -------------------------------------------

    def _kimligi_oku(self, *goruntu_yollari: str) -> None:
        """Verilen sayfalari kimlik okuma sirasina alir.

        Sayfalar TEK TEK ve sirayla islenir. Birden fazla sayfa ayni anda
        okunmaya kalkarsa is parcaciklari birbirinin uzerine yazar ve sonuclar
        karisir; ayrica kimlik hangi sayfadaysa oradan okunmasi yeterlidir.
        """
        if not self.ayarlar.otomatik_kimlik_oku:
            return
        self._ocr_sirasi.extend(goruntu_yollari)
        self._sonraki_kimlik_okumasi()

    def _okuma_gerekli_mi(self) -> bool:
        """Form zaten eksiksizse OCR'a gerek yok."""
        return not (self._form_gecerli_mi() and self.dogum_alani.text().strip())

    def _sonraki_kimlik_okumasi(self) -> None:
        """Siradaki sayfayi okumaya baslar; sira bostaysa veya mesgulse cikar.

        Mesgulluk denetimi icin QThread.isRunning() KULLANILAMAZ: 'tamamlandi'
        sinyali run() icinden, thread daha bitmeden gonderilir. Sonucu isleyen
        yuvadan siradakini baslatmaya calisirken isRunning() hala True doner ve
        sira kalici olarak tikanir - kimlik ikinci sayfadaysa hic okunmaz.
        Bunun yerine kendi bayragimizi tutup zincirlemeyi finished sinyaline
        bagliyoruz; finished, run() dondukten SONRA gelir.
        """
        if self._ocr_calisiyor:
            return
        if not self._okuma_gerekli_mi():
            self._ocr_sirasi.clear()
            return
        if not self._ocr_sirasi:
            return

        yol = self._ocr_sirasi.pop(0)
        self._ocr_calisiyor = True
        self.kimlik_iscisi = KimlikOkumaIscisi(yol, self.ayarlar.tesseract_yolu, self)
        self.kimlik_iscisi.tamamlandi.connect(self._kimlik_okundu)
        self.kimlik_iscisi.finished.connect(self._kimlik_okumasi_bitti)
        self.kimlik_iscisi.start()
        kalan = f" ({len(self._ocr_sirasi)} sayfa sırada)" if self._ocr_sirasi else ""
        self.statusBar().showMessage(f"Kimlik bilgileri okunuyor...{kalan}", 6000)

    def _kimlik_okumasi_bitti(self) -> None:
        """Is parcacigi gercekten bittikten sonra siradaki sayfaya gecer."""
        self._ocr_calisiyor = False
        self._sonraki_kimlik_okumasi()

    def _kimlik_okundu(self, sonuc) -> None:
        """OCR sonucunu forma yansitir.

        Kasiyerin elle yazdigi bir deger ASLA sessizce degistirilmez; farklilik
        varsa uyari gosterilir. Yalnizca bos alanlar doldurulur.
        """
        if not sonuc.kullanilabilir or sonuc.kimlik is None:
            if sonuc.mesaj:
                self.statusBar().showMessage(sonuc.mesaj, 8000)
            # Kimlik baska bir sayfada olabilir; siradaki sayfaya gecisi
            # _kimlik_okumasi_bitti yapar (bkz. _sonraki_kimlik_okumasi)
            return

        kimlik = sonuc.kimlik
        dolan: list[str] = []
        catisan: list[str] = []

        def alani_doldur(alan, deger: str, etiket: str) -> None:
            if not deger:
                return
            mevcut = alan.text().strip()
            if not mevcut:
                alan.setText(deger)
                dolan.append(etiket)
            elif mevcut.upper() != deger.upper():
                catisan.append(f"{etiket}: siz '{mevcut}', kimlikte '{deger}'")

        alani_doldur(self.tc_alani, kimlik.tc, "TC")
        alani_doldur(self.ad_alani, kimlik.ad, "Ad")
        alani_doldur(self.soyad_alani, kimlik.soyad, "Soyad")
        if kimlik.dogum_tarihi:
            alani_doldur(
                self.dogum_alani,
                kimlik.dogum_tarihi.strftime("%d.%m.%Y"),
                "Doğum tarihi",
            )

        self._formu_denetle()

        self._ocr_sirasi.clear()  # kimlik bulundu, kalan sayfalara gerek yok

        if catisan:
            QMessageBox.warning(
                self,
                "Kimlik bilgileri uyuşmuyor",
                "Kimlikten okunan bilgiler girdiğinizden farklı:\n\n• "
                + "\n• ".join(catisan)
                + "\n\nDoğru olanı kontrol edip elle düzeltin.",
            )
            return

        if not dolan:
            return

        renk = "#1f6f43" if sonuc.guven == "kesin" else "#b8860b"
        etiket = "doğrulandı" if sonuc.guven == "kesin" else "kontrol edin"
        self.gecmis_etiketi.setStyleSheet(f"color: {renk};")

        # TC ve dogum tarihi kontrol haneleriyle dogrulanir; ad soyad
        # dogrulanamaz (MRZ'de ad satirini koruyan hane yoktur), bu yuzden
        # ad alanlari her zaman gorsel olarak isaretlenir.
        not_metni = f"Kimlikten okundu ({etiket}): {', '.join(dolan)}."
        if not kimlik.ad or not kimlik.soyad:
            not_metni += "  Ad/soyad okunamadı, elle yazın."
        elif sonuc.ad_onay_gerekli:
            not_metni += "  Ad/soyad doğrulanamaz - kimlikle karşılaştırın."
            self._ad_onayini_isaretle(True)
        self.gecmis_etiketi.setText(not_metni)
        self.statusBar().showMessage(sonuc.mesaj, 8000)

    def _ad_onayini_isaretle(self, gerekli: bool) -> None:
        """Ad/soyad alanlarini onay bekliyor olarak vurgular."""
        stil = "background: #fff8dc; border: 1px solid #b8860b;" if gerekli else ""
        self.ad_alani.setStyleSheet(stil)
        self.soyad_alani.setStyleSheet(stil)

    # --- Sayfa seridi -----------------------------------------------------

    def _serit_sayfa_sayisi(self) -> int:
        """Seritte gezilebilecek kume sayisi (bos listede de en az 1)."""
        return max(1, -(-len(self.taslaklar) // SERIT_SAYFA_BOYU))

    def _serit_sayfasini_kaydir(self, yon: int) -> None:
        hedef = self._serit_sayfasi + yon
        if 0 <= hedef < self._serit_sayfa_sayisi():
            self._serit_sayfasi = hedef
            self._sayfa_listesini_yenile()

    def _sayfa_listesini_yenile(self, odak: int | None = None) -> None:
        """Seridi tazeler; odak verilirse o sayfanin kumesine gecip secer."""
        toplam = len(self.taslaklar)
        if odak is not None and 0 <= odak < toplam:
            self._serit_sayfasi = odak // SERIT_SAYFA_BOYU
        self._serit_sayfasi = min(self._serit_sayfasi, self._serit_sayfa_sayisi() - 1)

        self.sayfa_grubu.setTitle(
            f"Taranan Sayfalar ({toplam})" if toplam else "Taranan Sayfalar"
        )

        bas = self._serit_sayfasi * SERIT_SAYFA_BOYU
        self.sayfa_listesi.clear()
        for indeks in range(bas, min(bas + SERIT_SAYFA_BOYU, toplam)):
            taslak = self.taslaklar[indeks]
            pixmap = QPixmap(str(taslak.gecici_yol))
            if taslak.donme:
                pixmap = pixmap.transformed(QTransform().rotate(taslak.donme))
            simge = QIcon(
                pixmap.scaled(
                    KUCUK_RESIM,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            oge = QListWidgetItem(simge, f"Sayfa {indeks + 1}")
            oge.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            # Seritte sadece bir kume durdugundan satir numarasi taslak
            # indeksine esit degil; gercek indeks ogenin uzerinde tasinir.
            oge.setData(Qt.ItemDataRole.UserRole, indeks)
            self.sayfa_listesi.addItem(oge)

        if odak is not None and bas <= odak < bas + SERIT_SAYFA_BOYU:
            self.sayfa_listesi.setCurrentRow(odak - bas)

        self._serit_gezinmesini_yenile()

    def _serit_gezinmesini_yenile(self) -> None:
        sayfa_sayisi = self._serit_sayfa_sayisi()
        cok_sayfali = sayfa_sayisi > 1
        self.serit_etiketi.setText(
            f"{self._serit_sayfasi + 1} / {sayfa_sayisi}" if cok_sayfali else ""
        )
        for dugme, etkin in (
            (self.onceki_dugmesi, self._serit_sayfasi > 0),
            (self.sonraki_dugmesi, self._serit_sayfasi < sayfa_sayisi - 1),
        ):
            dugme.setVisible(cok_sayfali)
            dugme.setEnabled(etkin)

    def _secili_indeks(self) -> int | None:
        oge = self.sayfa_listesi.currentItem()
        if oge is None:
            return None
        indeks = oge.data(Qt.ItemDataRole.UserRole)
        return indeks if indeks is not None and 0 <= indeks < len(self.taslaklar) else None

    def secili_sayfayi_sil(self) -> None:
        indeks = self._secili_indeks()
        if indeks is None:
            return
        taslak = self.taslaklar.pop(indeks)
        taslak.gecici_yol.unlink(missing_ok=True)
        # Silinenin yerindeki sayfa secili kalir, liste sonundaysa bir onceki
        self._sayfa_listesini_yenile(min(indeks, len(self.taslaklar) - 1))
        self._formu_denetle()

    def secili_sayfayi_dondur(self, aci: int) -> None:
        indeks = self._secili_indeks()
        if indeks is None:
            return
        self.taslaklar[indeks].donme = (self.taslaklar[indeks].donme + aci) % 360
        self._sayfa_listesini_yenile(indeks)

    # --- Kayit ------------------------------------------------------------

    def kaydet(self) -> None:
        if not self.taslaklar or not self._form_gecerli_mi():
            return

        ad = ad_normalize(self.ad_alani.text())
        soyad = ad_normalize(self.soyad_alani.text())
        tc = tc_normalize(self.tc_alani.text())
        try:
            dogum = dogum_tarihi_ayristir(self.dogum_alani.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Doğum tarihi", str(exc))
            return

        bugun = _dt.date.today()
        klasor = self._hedef_klasor()
        parcalar = goreli_parcalar(ad, soyad, tc, bugun, sube=self.ayarlar.sube)
        pdf_adi = pdf_dosya_adi(ad, soyad, bugun) if self.ayarlar.pdf_olustur else None

        try:
            yazilan = sayfalari_yaz(
                [t.gecici_yol for t in self.taslaklar],
                klasor,
                jpeg_kalite=self.ayarlar.jpeg_kalite,
                donmeler=[t.donme for t in self.taslaklar],
                dpi=int(self.dpi_kutusu.currentData()),
            )
            pdf_yolu = pdf_uret(klasor, pdf_adi) if pdf_adi else None

            musteri_id = self.vt.musteri_kaydet(
                tc, ad, soyad, dogum.isoformat() if dogum else None
            )
            kayit_id = self.vt.kayit_ac(
                musteri_id, bugun, str(klasor), "/".join(parcalar),
                self.ayarlar.sube_kodu, pdf_adi,
            )
            for sayfa in yazilan:
                self.vt.sayfa_ekle(
                    kayit_id, sayfa.sira, sayfa.dosya_adi, sayfa.bayt, sayfa.sha256
                )
                if self.ayarlar.drive_etkin:
                    self.vt.kuyruga_ekle(
                        kayit_id, str(sayfa.yol), parcalar, sayfa.dosya_adi
                    )
            if pdf_yolu and self.ayarlar.drive_etkin:
                self.vt.kuyruga_ekle(kayit_id, str(pdf_yolu), parcalar, pdf_adi)

            meta_yaz(
                klasor, ad, soyad, tc, dogum, bugun, yazilan, pdf_adi,
                self.ayarlar.sube_kodu, self.cihaz_kutusu.currentText(),
                getpass.getuser(),
            )
            self.vt.denetim_yaz(
                "kayit_olusturuldu", kayit_id, f"{ad} {soyad} - {len(yazilan)} sayfa"
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Kayıt hatası",
                f"Dosyalar yazılamadı:\n{exc}\n\nArşiv klasörüne erişimi ve disk "
                "alanını kontrol edin.",
            )
            return

        for taslak in self.taslaklar:
            taslak.gecici_yol.unlink(missing_ok=True)
        self.taslaklar.clear()
        self._sayfa_listesini_yenile()

        # Yukleme dongusunun bir sonraki turunu beklemeden hemen basla
        if self.kuyruk is not None and self.ayarlar.drive_etkin:
            self.kuyruk.tetikle()

        self.statusBar().showMessage(
            f"Kaydedildi: {klasor.name} ({len(yazilan)} sayfa)", 6000
        )
        self._formu_temizle()
        self.ayarlar.kaydet()

    def _formu_temizle(self) -> None:
        for alan in (self.ad_alani, self.soyad_alani, self.tc_alani, self.dogum_alani):
            alan.clear()
        self.tc_uyari.clear()
        self.gecmis_etiketi.clear()
        self._ad_onayini_isaretle(False)
        self.ad_alani.setFocus()
        self._formu_denetle()

    # --- Drive durumu -----------------------------------------------------

    def _esitlenen_klasor(self):
        """Arsiv Drive'in esitledigi bir klasorde mi?

        Durum satiri saniyede bir yenileniyor; tarama sonucu kok klasor
        degismedikce onbellekten okunur.
        """
        kok = self.ayarlar.kok_klasor
        if kok != self._esitleme_onbellek_kok:
            from app.drive.yerel_esitleme import esitlenen_klasor

            self._esitleme_onbellek_kok = kok
            self._esitleme_onbellek = esitlenen_klasor(kok)
        return self._esitleme_onbellek

    def _drive_durumunu_yenile(self) -> None:
        if not self.ayarlar.drive_etkin:
            # Yukleme kapali gorunse de arsiv Drive klasorundeyse dosyalar
            # Drive masaustu uygulamasiyla yukleniyor demektir
            if self._esitlenen_klasor():
                self.durum_etiketi.setText("Drive: klasör eşitlemesi açık")
                self.durum_etiketi.setStyleSheet("color: #1f6f43;")
            else:
                self.durum_etiketi.setText("Google Drive: kapalı")
                self.durum_etiketi.setStyleSheet("color: #888;")
            return

        ozet = self.vt.kuyruk_ozeti()
        bekleyen = ozet.get(BEKLIYOR, 0)
        manuel = ozet.get(MANUEL, 0)
        if manuel:
            self.durum_etiketi.setText(f"Drive: {manuel} dosya yüklenemedi")
            self.durum_etiketi.setStyleSheet("color: #c0392b; font-weight: bold;")
        elif bekleyen:
            self.durum_etiketi.setText(f"Drive: {bekleyen} dosya yükleniyor")
            self.durum_etiketi.setStyleSheet("color: #b8860b;")
        else:
            self.durum_etiketi.setText(f"Drive: tümü yüklendi ({ozet.get(TAMAM, 0)})")
            self.durum_etiketi.setStyleSheet("color: #1f6f43;")

    # --- Kapanis ----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt adlandirmasi)
        if self.taslaklar:
            cevap = QMessageBox.question(
                self,
                "Kaydedilmemiş sayfalar",
                f"{len(self.taslaklar)} taranmış sayfa henüz kaydedilmedi.\n"
                "Çıkarsanız bu sayfalar silinecek. Devam edilsin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if cevap != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        self.ayarlar.kaydet()
        shutil.rmtree(self.oturum_klasoru, ignore_errors=True)
        event.accept()
