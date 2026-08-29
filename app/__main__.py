"""Uygulama giris noktasi.

Calistirma:
    python -m app
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import UYGULAMA_ADI, UYGULAMA_SURUMU, Ayarlar, veri_klasoru
from app.db import Veritabani
from app.varliklar import SIMGE, varlik_yolu

PAKET_DENETLE_BAYRAGI = "--paket-denetle"
PAKET_DENETIM_HATASI = 86


def _paketi_denetle() -> int:
    """Paketin kritik Qt ve ana pencere bilesenlerini yukleyebildigini denetler.

    Hata yakalanir; boylece penceresiz build denetimi PyInstaller'in hata
    diyalogunda takilmak yerine sifirdan farkli bir cikis kodu dondurur.
    """
    try:
        from PySide6.QtGui import QIcon  # noqa: F401
        from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: F401

        from app.ui.main_window import AnaPencere  # noqa: F401
    except Exception:
        return PAKET_DENETIM_HATASI
    return 0


def _gunlugu_kur() -> None:
    """Hata ayiklama icin donen dosya gunlugu kurar."""
    klasor = veri_klasoru()
    klasor.mkdir(parents=True, exist_ok=True)
    islemci = RotatingFileHandler(
        klasor / "tarama.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    islemci.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[islemci])


def _kuyrugu_baslat(ayarlar: Ayarlar, vt: Veritabani, log: logging.Logger):
    """Drive acikken arka plan yukleme kuyrugunu baslatir.

    Drive istemcisi tembel uretilir: yetkilendirme sorunu uygulamanin
    acilmasini engellemez, sadece yuklemeler kuyrukta bekler.
    """
    if not (ayarlar.drive_etkin and ayarlar.drive_kok_klasor_id):
        return None

    from app.drive.queue import YuklemeKuyrugu

    def istemci_uret():
        from app.drive.auth import kimlik_al
        from app.drive.client import DriveIstemcisi

        return DriveIstemcisi(kimlik_al(veri_klasoru(), etkilesimli=False), vt)

    kuyruk = YuklemeKuyrugu(
        vt,
        istemci_uret,
        ayarlar.drive_kok_klasor_id,
        azami_deneme=ayarlar.drive_azami_deneme,
    )
    kuyruk.basla()
    log.info("Drive yukleme kuyrugu baslatildi")
    return kuyruk


def main() -> int:
    if PAKET_DENETLE_BAYRAGI in sys.argv:
        return _paketi_denetle()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    _gunlugu_kur()
    log = logging.getLogger(__name__)
    log.info("%s %s baslatiliyor", UYGULAMA_ADI, UYGULAMA_SURUMU)

    uygulama = QApplication(sys.argv)
    uygulama.setApplicationName(UYGULAMA_ADI)
    uygulama.setApplicationVersion(UYGULAMA_SURUMU)
    # Tum pencere ve diyaloglar bu simgeyi devralir
    uygulama.setWindowIcon(QIcon(str(varlik_yolu(SIMGE))))

    ayarlar = Ayarlar.yukle()
    sorunlar = ayarlar.dogrula()

    try:
        vt = Veritabani(ayarlar.veritabani_yolu)
    except Exception as exc:
        log.exception("Veritabani acilamadi")
        QMessageBox.critical(
            None,
            "Veritabanı hatası",
            f"Veritabanı açılamadı:\n{exc}\n\nKonum: {ayarlar.veritabani_yolu}",
        )
        return 1

    kuyruk = _kuyrugu_baslat(ayarlar, vt, log)

    # Ana pencere ancak Qt hazir olduktan sonra iceri alinir
    from app.ui.main_window import AnaPencere

    pencere = AnaPencere(ayarlar, vt, kuyruk)
    pencere.show()

    if sorunlar:
        QMessageBox.warning(
            pencere, "Ayar uyarısı", "Ayarlarda düzeltilmesi gerekenler:\n\n• "
            + "\n• ".join(sorunlar),
        )

    # Eksik dis bilesen varsa kasiyer ugrasmadan kurulmasi teklif edilir
    if ayarlar.otomatik_kimlik_oku and not ayarlar.kurulum_sorma:
        from app.ui.kurulum_dialog import eksikleri_sor

        try:
            eksikleri_sor(ayarlar, pencere)
        except Exception:  # denetim hatasi uygulamanin acilmasini engellemesin
            log.exception("Eksik bilesen denetimi basarisiz")

    kod = uygulama.exec()

    if kuyruk is not None:
        kuyruk.durdur()
    vt.kapat()
    log.info("Uygulama kapandi (%s)", kod)
    return kod


if __name__ == "__main__":
    sys.exit(main())
