"""Guncelleme penceresi ve arka plan denetleyicisi.

Kullanicidan hicbir teknik islem beklenmez: yeni surum bulununca notlariyla
gosterilir, "Şimdi kur" dendiginde indirme, dogrulama, kurulum ve yeniden
baslatma uygulamanin isidir.

Ag islemleri ve paket acma arka planda yurur; UI thread'i asla bloke edilmez.
"""

from __future__ import annotations

import logging
import webbrowser
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from app import guncelleme
from app.config import UYGULAMA_SURUMU, Ayarlar
from app.guncelleme import GuncellemeHatasi, GuncellemeIptal, Yayin

log = logging.getLogger(__name__)

# Otomatik denetim bu araliktan sik yapilmaz; her acilista GitHub'a gitmek
# hem gereksiz hem de anonim sorgu siniri icin savurgandir.
DENETIM_ARALIGI = timedelta(hours=24)


class DenetimIscisi(QThread):
    """GitHub sorgusunu arka planda yapar."""

    sonuc = Signal(object)  # Yayin ya da None (guncel)
    hata = Signal(str)

    def run(self) -> None:
        try:
            yayin = guncelleme.guncelleme_var_mi()
        except GuncellemeHatasi as exc:
            self.hata.emit(str(exc))
        except Exception as exc:  # beklenmeyen hata uygulamayi dusurmesin
            log.exception("Guncelleme denetimi basarisiz")
            self.hata.emit(f"Beklenmeyen hata: {exc}")
        else:
            self.sonuc.emit(yayin)


class IndirmeIscisi(QThread):
    """Paketi indirir ve dogrular."""

    ilerleme = Signal(int, int)  # inen, toplam (bayt)
    bitti = Signal(str)  # zip yolu
    hata = Signal(str)
    iptal_edildi = Signal()

    def __init__(self, yayin: Yayin, parent=None):
        super().__init__(parent)
        self.yayin = yayin
        self._iptal = False

    def iptal_et(self) -> None:
        self._iptal = True

    def run(self) -> None:
        try:
            yol = guncelleme.indir(
                self.yayin,
                ilerleme=lambda inen, toplam: self.ilerleme.emit(inen, toplam),
                iptal=lambda: self._iptal,
            )
        except GuncellemeIptal:
            self.iptal_edildi.emit()
        except GuncellemeHatasi as exc:
            self.hata.emit(str(exc))
        except Exception as exc:
            log.exception("Indirme basarisiz")
            self.hata.emit(f"Beklenmeyen hata: {exc}")
        else:
            self.bitti.emit(str(yol))


class KurulumIscisi(QThread):
    """Paketi acar ve yer degistirme betigini baslatir.

    Yuzlerce megabaytlik paketin acilmasi saniyeler surer; UI thread'inde
    yapilirsa pencere donar.
    """

    bitti = Signal()
    hata = Signal(str)

    def __init__(self, zip_yolu: str, yayin: Yayin, parent=None):
        super().__init__(parent)
        self.zip_yolu = zip_yolu
        self.yayin = yayin

    def run(self) -> None:
        try:
            guncelleme.kur(self.zip_yolu, self.yayin)
        except GuncellemeHatasi as exc:
            self.hata.emit(str(exc))
        except Exception as exc:
            log.exception("Kurulum baslatilamadi")
            self.hata.emit(f"Beklenmeyen hata: {exc}")
        else:
            self.bitti.emit()


class GuncellemeDiyalogu(QDialog):
    """Yeni surumu tanitir, onay alindiginda indirip kurar."""

    # Kurulum betigi baslatildi: uygulamanin kapanmasi gerekiyor
    kapatilmali = Signal()

    def __init__(self, yayin: Yayin, ayarlar: Ayarlar, parent=None, engel=None):
        super().__init__(parent)
        self.yayin = yayin
        self.ayarlar = ayarlar
        # engel(): kurulum su an sakincaliysa gerekce dondurur (ornegin
        # kaydedilmemis taranmis sayfa varsa), yoksa bos dizge
        self._engel = engel
        self.indirme_iscisi: IndirmeIscisi | None = None
        self.kurulum_iscisi: KurulumIscisi | None = None
        self._zip_yolu = ""

        self.setWindowTitle("Güncelleme")
        self.setMinimumWidth(560)
        self._arayuzu_kur()

    # --- Arayuz -----------------------------------------------------------

    def _arayuzu_kur(self) -> None:
        duzen = QVBoxLayout(self)

        baslik = QLabel(
            f"<b>Docvera {self.yayin.surum}</b> yayımlandı. "
            f"Kullandığınız sürüm {UYGULAMA_SURUMU}."
        )
        baslik.setWordWrap(True)
        duzen.addWidget(baslik)

        if self.yayin.notlar:
            notlar = QTextBrowser()
            notlar.setMarkdown(self.yayin.notlar)
            notlar.setOpenExternalLinks(True)
            notlar.setMaximumHeight(220)
            duzen.addWidget(notlar)

        self.durum = QLabel(
            f"İndirilecek paket: {self.yayin.boyut_metni}. Kurulum sırasında "
            "uygulama kapanır ve yeni sürümle kendiliğinden açılır. "
            "Ayarlarınız, arşiviniz ve Drive bağlantınız korunur."
        )
        self.durum.setWordWrap(True)
        self.durum.setStyleSheet("color: #666; font-size: 11px; margin-top: 6px;")
        duzen.addWidget(self.durum)

        self.cubuk = QProgressBar()
        self.cubuk.setVisible(False)
        duzen.addWidget(self.cubuk)

        dugmeler = QHBoxLayout()
        self.atla_dugmesi = QPushButton("Bu sürümü atla")
        self.atla_dugmesi.setToolTip(
            "Bu sürüm bir daha hatırlatılmaz; sonraki sürümler yine bildirilir."
        )
        self.atla_dugmesi.clicked.connect(self._atla)
        dugmeler.addWidget(self.atla_dugmesi)
        dugmeler.addStretch(1)

        self.sonra_dugmesi = QPushButton("Daha sonra")
        self.sonra_dugmesi.clicked.connect(self.reject)
        self.kur_dugmesi = QPushButton("Şimdi kur")
        self.kur_dugmesi.setDefault(True)
        self.kur_dugmesi.clicked.connect(self._kur)
        dugmeler.addWidget(self.sonra_dugmesi)
        dugmeler.addWidget(self.kur_dugmesi)
        duzen.addLayout(dugmeler)

    def _durumu_yaz(self, metin: str, renk: str = "#666") -> None:
        self.durum.setText(metin)
        self.durum.setStyleSheet(f"color: {renk}; font-size: 11px; margin-top: 6px;")

    # --- Eylemler ---------------------------------------------------------

    def _atla(self) -> None:
        self.ayarlar.guncelleme_atlanan_surum = self.yayin.surum
        try:
            self.ayarlar.kaydet()
        except OSError:  # ayar yazilamamasi pencereyi kilitlememeli
            log.warning("Atlanan surum kaydedilemedi")
        self.reject()

    def _kur(self) -> None:
        uygun, gerekce = guncelleme.kurulabilir_mi()
        if not uygun:
            self._elle_kurulum(gerekce)
            return

        engel = self._engel() if self._engel is not None else ""
        if engel:
            QMessageBox.warning(self, "Güncelleme", engel)
            return

        self.kur_dugmesi.setEnabled(False)
        self.atla_dugmesi.setEnabled(False)
        self.sonra_dugmesi.setText("İptal")
        self.cubuk.setVisible(True)
        self.cubuk.setRange(0, 0)
        self._durumu_yaz("İndiriliyor...")

        self.indirme_iscisi = IndirmeIscisi(self.yayin, self)
        self.indirme_iscisi.ilerleme.connect(self._ilerleme)
        self.indirme_iscisi.bitti.connect(self._indirme_bitti)
        self.indirme_iscisi.hata.connect(self._hata)
        self.indirme_iscisi.iptal_edildi.connect(self._iptal_edildi)
        self.indirme_iscisi.start()

    def _elle_kurulum(self, gerekce: str) -> None:
        """Otomatik kurulum yapilamiyorsa kullaniciyi yayin sayfasina yonlendirir."""
        cevap = QMessageBox.question(
            self,
            "Otomatik kurulum yapılamıyor",
            f"{gerekce}\n\nYayın sayfası tarayıcıda açılsın mı?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if cevap == QMessageBox.StandardButton.Yes:
            webbrowser.open(self.yayin.sayfa_url)

    def _ilerleme(self, inen: int, toplam: int) -> None:
        if toplam <= 0:
            self.cubuk.setRange(0, 0)
            self._durumu_yaz(f"İndiriliyor... {inen / 1048576:.0f} MB")
            return
        self.cubuk.setRange(0, 100)
        self.cubuk.setValue(int(inen * 100 / toplam))
        self._durumu_yaz(
            f"İndiriliyor... {inen / 1048576:.0f} / {toplam / 1048576:.0f} MB"
        )

    def _indirme_bitti(self, zip_yolu: str) -> None:
        self._zip_yolu = zip_yolu
        self.sonra_dugmesi.setEnabled(False)  # bu noktadan sonra iptal edilemez
        self.cubuk.setRange(0, 0)
        self._durumu_yaz("Paket açılıyor, lütfen bekleyin...")

        self.kurulum_iscisi = KurulumIscisi(zip_yolu, self.yayin, self)
        self.kurulum_iscisi.bitti.connect(self._kurulum_basladi)
        self.kurulum_iscisi.hata.connect(self._hata)
        self.kurulum_iscisi.start()

    def _kurulum_basladi(self) -> None:
        self.cubuk.setVisible(False)
        self._durumu_yaz(
            "Kurulum başlatıldı. Uygulama şimdi kapanacak ve yeni sürümle "
            "kendiliğinden açılacak.",
            "#1f6f43",
        )
        QMessageBox.information(
            self,
            "Güncelleme",
            f"Docvera {self.yayin.surum} kuruluyor.\n\n"
            "Uygulama şimdi kapanacak; kurulum bitince yeni sürüm kendiliğinden "
            "açılacak. Bu sırada uygulamayı elle açmayın.",
        )
        self.accept()
        self.kapatilmali.emit()

    def _iptal_edildi(self) -> None:
        self.cubuk.setVisible(False)
        self.kur_dugmesi.setEnabled(True)
        self.atla_dugmesi.setEnabled(True)
        self.sonra_dugmesi.setText("Daha sonra")
        self._durumu_yaz("İndirme iptal edildi.", "#b8860b")

    def _hata(self, mesaj: str) -> None:
        self.cubuk.setVisible(False)
        self.kur_dugmesi.setEnabled(True)
        self.kur_dugmesi.setText("Yeniden dene")
        self.atla_dugmesi.setEnabled(True)
        self.sonra_dugmesi.setEnabled(True)
        self.sonra_dugmesi.setText("Kapat")
        self._durumu_yaz(mesaj, "#c0392b")

    # --- Kapanis ----------------------------------------------------------

    def _calisiyor_mu(self) -> bool:
        for isci in (self.indirme_iscisi, self.kurulum_iscisi):
            if isci is not None and isci.isRunning():
                return True
        return False

    def reject(self) -> None:
        if self.indirme_iscisi is not None and self.indirme_iscisi.isRunning():
            self.indirme_iscisi.iptal_et()
            self.sonra_dugmesi.setEnabled(False)
            self._durumu_yaz("İndirme durduruluyor...", "#b8860b")
            return
        if self.kurulum_iscisi is not None and self.kurulum_iscisi.isRunning():
            return  # paket acilirken kapanmak yarim kurulum birakir
        super().reject()

    def closeEvent(self, olay) -> None:  # noqa: N802 (Qt adlandirmasi)
        if self._calisiyor_mu():
            olay.ignore()
            self.reject()
            return
        super().closeEvent(olay)


class GuncellemeDenetleyici(QObject):
    """Denetim isteklerini yoneten kucuk yardimci.

    Ana pencere bunu bir kez olusturur: is parcaciginin sahibi olur (aksi
    halde thread bitmeden cop toplanip uygulamayi dusurebilir) ve ayni anda
    birden fazla sorgu yapilmasini engeller.
    """

    # Bilgi mesaji: durum cubugunda gosterilir (metin, saniye)
    bilgi = Signal(str, int)

    def __init__(self, ayarlar: Ayarlar, pencere, engel=None):
        super().__init__(pencere)
        self.ayarlar = ayarlar
        self.pencere = pencere
        self._engel = engel
        self._isci: DenetimIscisi | None = None
        self._sessiz = False

    # --- Denetim ---

    def calisiyor_mu(self) -> bool:
        return self._isci is not None and self._isci.isRunning()

    def denetle(self, sessiz: bool = False) -> None:
        """Yeni surum sorgular.

        sessiz=True (otomatik denetim) yalnizca yeni surum varsa konusur;
        guncel oldugunda ya da internet yokken kullaniciyi rahatsiz etmez.
        """
        if self.calisiyor_mu():
            if not sessiz:
                self.bilgi.emit("Güncelleme denetimi zaten sürüyor...", 4000)
            return

        self._sessiz = sessiz
        if not sessiz:
            self.bilgi.emit("Güncellemeler denetleniyor...", 0)

        self._isci = DenetimIscisi(self)
        self._isci.sonuc.connect(self._sonuc)
        self._isci.hata.connect(self._hata)
        self._isci.start()

    def acilista_denetle(self) -> None:
        """Otomatik denetim acikken ve gunluk aralik dolduysa sorgular."""
        if not self.ayarlar.guncelleme_otomatik_denetle:
            return
        if not self._aralik_doldu():
            return
        # Acilisi yavaslatmamak icin pencere gorundukten birkac saniye sonra
        QTimer.singleShot(5000, lambda: self.denetle(sessiz=True))

    def _aralik_doldu(self) -> bool:
        damga = (self.ayarlar.guncelleme_son_denetim or "").strip()
        if not damga:
            return True
        try:
            son = datetime.fromisoformat(damga)
        except ValueError:  # bozuk damga denetimi engellememeli
            return True
        return datetime.now() - son >= DENETIM_ARALIGI

    def _damgayi_yaz(self) -> None:
        self.ayarlar.guncelleme_son_denetim = datetime.now().isoformat(
            timespec="seconds"
        )
        try:
            self.ayarlar.kaydet()
        except OSError:
            log.warning("Guncelleme denetim damgasi kaydedilemedi")

    # --- Sonuc ---

    def _sonuc(self, yayin) -> None:
        self._damgayi_yaz()

        if yayin is None:
            if not self._sessiz:
                self.bilgi.emit(f"Docvera {UYGULAMA_SURUMU} güncel.", 6000)
            return

        if self._sessiz and yayin.surum == self.ayarlar.guncelleme_atlanan_surum:
            return  # kullanici bu surumu atlamayi secmisti

        self.bilgi.emit(f"Yeni sürüm bulundu: {yayin.surum}", 6000)
        self.goster(yayin)

    def _hata(self, mesaj: str) -> None:
        self._damgayi_yaz()
        if self._sessiz:
            log.info("Otomatik guncelleme denetimi basarisiz: %s", mesaj)
            return
        self.bilgi.emit("", 0)
        QMessageBox.warning(self.pencere, "Güncelleme denetimi", mesaj)

    def goster(self, yayin: Yayin) -> None:
        diyalog = GuncellemeDiyalogu(yayin, self.ayarlar, self.pencere, self._engel)
        diyalog.setWindowModality(Qt.WindowModality.ApplicationModal)
        diyalog.kapatilmali.connect(self._kapat)
        diyalog.exec()

    def _kapat(self) -> None:
        """Kurulum betigi calisirken uygulamayi kapatir."""
        QTimer.singleShot(0, self.pencere.close)
