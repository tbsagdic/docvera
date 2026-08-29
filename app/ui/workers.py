"""Arka plan is parcaciklari.

Tarama ve cihaz listeleme COM uzerinden yurudugu ve saniyeler surebildigi
icin asla UI thread'inde calistirilmaz - aksi halde uygulama donar ve
Windows "yanit vermiyor" uyarisi verir.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.scanner.base import TaramaAyarlari, TarayiciCihaz
from app.scanner.errors import TaramaHatasi
from app.scanner.wia import WiaTarayici


class CihazListeIscisi(QThread):
    """Bagli tarayicilari arka planda listeler.

    Ag tarayicilari yanit vermesi saniyeler surebildigi icin bu islem
    acilista UI'i bloklamamalidir.
    """

    tamamlandi = Signal(list)  # list[TarayiciCihaz]
    hata = Signal(str)

    def run(self) -> None:
        try:
            cihazlar = WiaTarayici().cihazlari_listele()
        except TaramaHatasi as exc:
            self.hata.emit(exc.mesaj)
        except Exception as exc:  # beklenmeyen COM hatasi UI'i dusurmesin
            self.hata.emit(f"Tarayici listesi alinamadi: {exc}")
        else:
            self.tamamlandi.emit(cihazlar)


class YetenekIscisi(QThread):
    """Secilen cihazin besleyici/duplex destegini arka planda ogrenir."""

    tamamlandi = Signal(object)  # TarayiciCihaz
    hata = Signal(str)

    def __init__(self, cihaz_id: str, parent=None):
        super().__init__(parent)
        self.cihaz_id = cihaz_id

    def run(self) -> None:
        try:
            cihaz = WiaTarayici().cihaz_yetenekleri(self.cihaz_id)
        except TaramaHatasi as exc:
            self.hata.emit(exc.mesaj)
        except Exception as exc:
            self.hata.emit(f"Cihaz ozellikleri okunamadi: {exc}")
        else:
            self.tamamlandi.emit(cihaz)


class TaramaIscisi(QThread):
    """Taramayi arka planda yurutur ve her sayfayi aninda bildirir."""

    sayfa_geldi = Signal(int, str)  # sira, gecici dosya yolu
    tamamlandi = Signal(list)  # list[str]
    hata = Signal(str, bool)  # mesaj, iptal_mi

    def __init__(
        self,
        cihaz_id: str,
        ayarlar: TaramaAyarlari,
        gecici_klasor: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.cihaz_id = cihaz_id
        self.ayarlar = ayarlar
        self.gecici_klasor = Path(gecici_klasor)

    def run(self) -> None:
        try:
            yollar = WiaTarayici().tara(
                self.cihaz_id,
                self.ayarlar,
                self.gecici_klasor,
                geri_cagirim=lambda sira, yol: self.sayfa_geldi.emit(sira, str(yol)),
            )
        except TaramaHatasi as exc:
            self.hata.emit(exc.mesaj, exc.iptal_mi)
        except Exception as exc:
            self.hata.emit(f"Tarama sirasinda beklenmeyen hata: {exc}", False)
        else:
            self.tamamlandi.emit([str(yol) for yol in yollar])


class KimlikOkumaIscisi(QThread):
    """Taranan sayfadan kimlik bilgilerini arka planda okur.

    OCR birkac saniye surebilir; UI thread'inde calistirilirsa kasiyer
    onizleme penceresinde bekler.
    """

    tamamlandi = Signal(object)  # app.ocr.kimlik.OkumaSonucu

    def __init__(self, goruntu_yolu: str, tesseract_yolu: str = "", parent=None):
        super().__init__(parent)
        self.goruntu_yolu = goruntu_yolu
        self.tesseract_yolu = tesseract_yolu

    def run(self) -> None:
        from app.ocr.kimlik import OkumaSonucu, kimlik_oku

        try:
            sonuc = kimlik_oku(self.goruntu_yolu, self.tesseract_yolu)
        except Exception as exc:  # OCR hatasi taramayi bosa cikarmamali
            sonuc = OkumaSonucu(mesaj=f"Kimlik okunamadı: {exc}")
        self.tamamlandi.emit(sonuc)


class AktarimIscisi(QThread):
    """Secilen PDF/goruntu dosyalarini arka planda sayfalara cevirir.

    Cok sayfali bir PDF'in 300 DPI'da goruntuye cevrilmesi saniyeler surer;
    UI thread'inde yapilirsa pencere donar.
    """

    tamamlandi = Signal(list, list)  # sayfa yollari, hata mesajlari

    def __init__(self, dosyalar: list[str], hedef_klasor: Path, dpi: int = 300, parent=None):
        super().__init__(parent)
        self.dosyalar = list(dosyalar)
        self.hedef_klasor = Path(hedef_klasor)
        self.dpi = dpi

    def run(self) -> None:
        from app.storage.aktarim import AktarimHatasi, dosyadan_sayfalar

        yollar: list[str] = []
        hatalar: list[str] = []
        for dosya in self.dosyalar:
            try:
                yollar.extend(
                    str(yol)
                    for yol in dosyadan_sayfalar(dosya, self.hedef_klasor, self.dpi)
                )
            except AktarimHatasi as exc:
                hatalar.append(f"{Path(dosya).name}: {exc}")
            except Exception as exc:
                hatalar.append(f"{Path(dosya).name}: beklenmeyen hata - {exc}")
        self.tamamlandi.emit(yollar, hatalar)
