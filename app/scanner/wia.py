"""WIA (Windows Image Acquisition) tabanli tarayici arka ucu.

Windows'un yerlesik tarama API'sini kullanir - ek surucu veya SDK gerektirmez.
Tum COM cagrilari cagiran thread'de CoInitialize edilmis olmalidir; bu modul
her genel giris noktasinda bunu kendisi halleder.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

import pythoncom
import win32com.client

from app.scanner.base import Kaynak, SayfaGeriCagirim, TaramaAyarlari, TarayiciCihaz
from app.scanner.errors import (
    WIA_ERROR_PAPER_EMPTY,
    TaramaHatasi,
    com_hatasini_cevir,
    hresult_cikar,
)

log = logging.getLogger(__name__)

# --- WIA sabitleri (wiadef.h) ---------------------------------------------
DEVICE_TYPE_SCANNER = 1

# Cihaz duzeyi ozellikler
DIP_DEV_ID = 2
DIP_VEND_DESC = 3
DIP_PORT_NAME = 5
DIP_DEV_NAME = 7
DIP_DEV_DESC = 9

DPS_DOCUMENT_HANDLING_CAPABILITIES = 3086
DPS_DOCUMENT_HANDLING_SELECT = 3088
DPS_PAGES = 3096

# Oge duzeyi ozellikler
IPA_DATATYPE = 4103
IPA_DEPTH = 4104
IPS_XRES = 6147
IPS_YRES = 6148
IPS_XPOS = 6149
IPS_YPOS = 6150
IPS_XEXTENT = 6151
IPS_YEXTENT = 6152

# DOCUMENT_HANDLING_SELECT degerleri
SELECT_FEEDER = 0x001
SELECT_FLATBED = 0x002

# DOCUMENT_HANDLING_CAPABILITIES bayraklari
CAP_FEEDER = 0x001
CAP_FLATBED = 0x002
CAP_DUPLEX = 0x004

# Veri tipleri
DATATYPE_GRAYSCALE = 2
DATATYPE_COLOR = 3

FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"
FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"

# Besleyiciden alinabilecek makul ust sinir - sonsuz donguye karsi emniyet
BESLEYICI_UST_SINIR = 100


_thread_durumu = threading.local()


def _com_hazirla() -> None:
    """Bulundugu thread'de COM'u bir kez baslatir.

    Bilerek CoUninitialize cagirmiyoruz: WIA nesneleri (DeviceInfo, Item,
    ImageFile) cagiran koda donduruluyor ve Python bunlari daha sonra
    topluyor. COM erken kapatilirsa bu nesneler serbest birakilirken
    "Win32 exception occurred releasing IUnknown" uyarilari olusur.
    COM, thread sonlandiginda isletim sistemi tarafindan zaten kapatilir.
    """
    if getattr(_thread_durumu, "com_hazir", False):
        return
    pythoncom.CoInitialize()
    _thread_durumu.com_hazir = True


def _ozellik_sozlugu(koleksiyon) -> dict[int, object]:
    """WIA Properties koleksiyonunu {PropertyID: deger} sozlugune cevirir."""
    sonuc: dict[int, object] = {}
    for ozellik in koleksiyon:
        try:
            sonuc[int(ozellik.PropertyID)] = ozellik.Value
        except Exception:  # bazi ozellikler yazilir-okunmaz olabilir
            continue
    return sonuc


def _ozellik_ayarla(koleksiyon, ozellik_id: int, deger) -> bool:
    """Bir WIA ozelligini ayarlar.

    Cihaz o ozelligi desteklemiyorsa veya deger reddedilirse False doner -
    tarama yine de varsayilan ayarlarla surdurulebilir, bu yuzden hata
    firlatmiyoruz.
    """
    for ozellik in koleksiyon:
        try:
            if int(ozellik.PropertyID) != ozellik_id:
                continue
            ozellik.Value = deger
            return True
        except Exception as exc:
            log.warning("WIA ozelligi ayarlanamadi (%s = %r): %s", ozellik_id, deger, exc)
            return False
    return False


def _ilk_oge(cihaz):
    """Cihazin ilk tarama ogesini dondurur.

    Farkli WIA suruculeri Items koleksiyonunu farkli sekilde sunuyor;
    her iki erisim bicimini de deniyoruz.
    """
    try:
        return cihaz.Items.Item(1)
    except Exception:
        pass
    try:
        return cihaz.Items(1)
    except Exception:
        pass
    for oge in cihaz.Items:
        return oge
    raise TaramaHatasi("Tarayicida taranabilir bir oge bulunamadi.")


class WiaTarayici:
    """WIA arka ucu - app.scanner.base.TarayiciArkaUcu arayuzunu uygular."""

    def cihazlari_listele(self) -> list[TarayiciCihaz]:
        """Bagli tarayicilari dondurur.

        Cihaz listesi anlik degisebilir (ag tarayicisi uykuya gecebilir),
        bu yuzden UI bunu her 'Yenile' isteginde tekrar cagirmalidir.
        """
        _com_hazirla()
        try:
            yonetici = win32com.client.Dispatch("WIA.DeviceManager")
        except Exception as exc:
            raise com_hatasini_cevir(exc) from exc

        cihazlar: list[TarayiciCihaz] = []
        for bilgi in yonetici.DeviceInfos:
            try:
                if int(bilgi.Type) != DEVICE_TYPE_SCANNER:
                    continue
                ozellikler = _ozellik_sozlugu(bilgi.Properties)
                cihazlar.append(
                    TarayiciCihaz(
                        cihaz_id=str(bilgi.DeviceID),
                        ad=str(ozellikler.get(DIP_DEV_NAME) or bilgi.DeviceID),
                        uretici=str(ozellikler.get(DIP_VEND_DESC) or ""),
                    )
                )
            except Exception as exc:
                log.warning("Cihaz bilgisi okunamadi: %s", exc)
        return cihazlar

    def cihaz_yetenekleri(self, cihaz_id: str) -> TarayiciCihaz:
        """Cihaza baglanip besleyici/duplex destegini ogrenir.

        Baglanti gerektirdigi icin listeleme sirasinda degil, cihaz secildikten
        sonra cagrilir - aksi halde her acilista tum cihazlar uyandirilir.
        """
        _com_hazirla()
        bilgi = self._cihaz_bilgisi_bul(cihaz_id)
        try:
            cihaz = bilgi.Connect()
        except Exception as exc:
            raise com_hatasini_cevir(exc) from exc

        ozellikler = _ozellik_sozlugu(cihaz.Properties)
        yetenek = ozellikler.get(DPS_DOCUMENT_HANDLING_CAPABILITIES, 0)
        yetenek = int(yetenek) if isinstance(yetenek, int) else 0
        ad = _ozellik_sozlugu(bilgi.Properties).get(DIP_DEV_NAME) or cihaz_id
        return TarayiciCihaz(
            cihaz_id=cihaz_id,
            ad=str(ad),
            besleyici_var=bool(yetenek & CAP_FEEDER),
            duplex_var=bool(yetenek & CAP_DUPLEX),
        )

    def tara(
        self,
        cihaz_id: str,
        ayarlar: TaramaAyarlari,
        hedef_klasor: Path,
        geri_cagirim: SayfaGeriCagirim | None = None,
    ) -> list[Path]:
        """Tarar ve olusan gecici goruntu dosyalarinin yollarini dondurur.

        Cam kaynaginda tek sayfa alinir. Besleyici kaynaginda kagit bitene
        (WIA_ERROR_PAPER_EMPTY) veya azami_sayfa sinirina ulasilana kadar
        devam edilir.
        """
        hedef_klasor = Path(hedef_klasor)
        hedef_klasor.mkdir(parents=True, exist_ok=True)

        _com_hazirla()
        bilgi = self._cihaz_bilgisi_bul(cihaz_id)
        try:
            cihaz = bilgi.Connect()
        except Exception as exc:
            raise com_hatasini_cevir(exc) from exc

        besleyici = ayarlar.kaynak == Kaynak.BESLEYICI
        if besleyici:
            _ozellik_ayarla(cihaz.Properties, DPS_DOCUMENT_HANDLING_SELECT, SELECT_FEEDER)
            _ozellik_ayarla(cihaz.Properties, DPS_PAGES, 1)
        else:
            _ozellik_ayarla(cihaz.Properties, DPS_DOCUMENT_HANDLING_SELECT, SELECT_FLATBED)

        oge = _ilk_oge(cihaz)
        self._oge_ayarla(oge, ayarlar)

        sinir = ayarlar.azami_sayfa or (BESLEYICI_UST_SINIR if besleyici else 1)
        yollar: list[Path] = []

        for sira in range(1, sinir + 1):
            try:
                goruntu = oge.Transfer(FORMAT_JPEG)
            except Exception as exc:
                kod = hresult_cikar(exc)
                # Besleyicide kagit bitmesi hata degil, dogal bitis kosulu
                if besleyici and kod == WIA_ERROR_PAPER_EMPTY and yollar:
                    break
                raise com_hatasini_cevir(exc) from exc

            yol = self._goruntuyu_kaydet(goruntu, hedef_klasor, sira)
            yollar.append(yol)
            if geri_cagirim is not None:
                geri_cagirim(sira, yol)

            if not besleyici:
                break

        if not yollar:
            raise TaramaHatasi("Tarayicidan hic sayfa alinamadi.")
        return yollar

    # --- ic yardimcilar ---------------------------------------------------

    def _cihaz_bilgisi_bul(self, cihaz_id: str):
        """DeviceID'ye gore WIA DeviceInfo nesnesini bulur."""
        try:
            yonetici = win32com.client.Dispatch("WIA.DeviceManager")
        except Exception as exc:
            raise com_hatasini_cevir(exc) from exc

        for bilgi in yonetici.DeviceInfos:
            try:
                if str(bilgi.DeviceID) == cihaz_id:
                    return bilgi
            except Exception:
                continue
        raise TaramaHatasi(
            "Secili tarayici artik bagli degil. Yenile dugmesiyle listeyi "
            "guncelleyip tekrar deneyin."
        )

    def _oge_ayarla(self, oge, ayarlar: TaramaAyarlari) -> None:
        """Cozunurluk ve renk ayarlarini uygular.

        Cozunurluk degisince tarama alani (XEXTENT/YEXTENT) piksel cinsinden
        gecersiz kalir; bu yuzden once DPI, sonra alan olceklenir.
        """
        ozellikler = oge.Properties
        onceki = _ozellik_sozlugu(ozellikler)
        onceki_dpi = onceki.get(IPS_XRES)

        _ozellik_ayarla(ozellikler, IPS_XRES, ayarlar.dpi)
        _ozellik_ayarla(ozellikler, IPS_YRES, ayarlar.dpi)
        _ozellik_ayarla(
            ozellikler,
            IPA_DATATYPE,
            DATATYPE_COLOR if ayarlar.renkli else DATATYPE_GRAYSCALE,
        )

        # DPI degistiyse tarama alanini yeni cozunurluge gore olcekle
        if isinstance(onceki_dpi, int) and onceki_dpi > 0 and onceki_dpi != ayarlar.dpi:
            oran = ayarlar.dpi / onceki_dpi
            for alan_id in (IPS_XEXTENT, IPS_YEXTENT):
                eski = onceki.get(alan_id)
                if isinstance(eski, int) and eski > 0:
                    _ozellik_ayarla(ozellikler, alan_id, int(eski * oran))
            _ozellik_ayarla(ozellikler, IPS_XPOS, 0)
            _ozellik_ayarla(ozellikler, IPS_YPOS, 0)

    def _goruntuyu_kaydet(self, goruntu, hedef_klasor: Path, sira: int) -> Path:
        """WIA ImageFile'i diske yazar.

        Bazi suruculer istenen JPEG bicimini yok sayip BMP dondurur; bu yuzden
        surucunun verdigi uzantiyla kaydedilir, JPEG'e donusum cagirana birakilir.
        """
        try:
            uzanti = str(goruntu.FileExtension or "jpg").lstrip(".").lower()
        except Exception:
            uzanti = "jpg"

        with tempfile.NamedTemporaryFile(
            prefix=f"tarama_{sira:02d}_",
            suffix=f".{uzanti}",
            dir=hedef_klasor,
            delete=False,
        ) as gecici:
            yol = Path(gecici.name)
        # WIA hedef dosyanin var olmamasini ister
        yol.unlink(missing_ok=True)

        try:
            goruntu.SaveFile(str(yol))
        except Exception as exc:
            raise com_hatasini_cevir(exc) from exc
        return yol
