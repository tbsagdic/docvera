"""WIA hata kodlarini kullanicinin anlayacagi Turkce mesajlara cevirir.

COM cagrilari hatayi cift katmanli firlatir: dis katman DISP_E_EXCEPTION
(0x80020009), asil WIA kodu ise excepinfo[5] icinde gelir. Bu modul asil
kodu cikarip anlamli bir mesaja donusturur.
"""

from __future__ import annotations

# wiadef.h - dogrulanmis degerler
WIA_ERROR_GENERAL_ERROR = 0x80210001
WIA_ERROR_PAPER_JAM = 0x80210002
WIA_ERROR_PAPER_EMPTY = 0x80210003
WIA_ERROR_PAPER_PROBLEM = 0x80210004
WIA_ERROR_OFFLINE = 0x80210005
WIA_ERROR_BUSY = 0x80210006
WIA_ERROR_WARMING_UP = 0x80210007
WIA_ERROR_USER_INTERVENTION = 0x80210008
WIA_ERROR_ITEM_DELETED = 0x80210009
WIA_ERROR_DEVICE_COMMUNICATION = 0x8021000A
WIA_ERROR_INVALID_COMMAND = 0x8021000B
WIA_ERROR_INCORRECT_HARDWARE_SETTING = 0x8021000C
WIA_ERROR_DEVICE_LOCKED = 0x8021000D
WIA_ERROR_EXCEPTION_IN_DRIVER = 0x8021000E
WIA_ERROR_INVALID_DRIVER_RESPONSE = 0x8021000F
WIA_S_NO_DEVICE_AVAILABLE = 0x80210015
WIA_ERROR_COVER_OPEN = 0x80210016
WIA_ERROR_LAMP_OFF = 0x80210017
WIA_ERROR_BUSY_TIMEOUT = 0x80210018
WIA_ERROR_DESTINATION = 0x80210019
WIA_ERROR_NETWORK_RESERVATION_FAILED = 0x8021001A
WIA_ERROR_USER_CANCELED = 0x80210064

MESAJLAR: dict[int, str] = {
    WIA_ERROR_GENERAL_ERROR: (
        "Tarayicida bilinmeyen bir hata olustu. Cihazi kapatip acmayi deneyin."
    ),
    WIA_ERROR_PAPER_JAM: "Tarayicida kagit sikismasi var. Kagidi cikarip tekrar deneyin.",
    WIA_ERROR_PAPER_EMPTY: "Besleyicide kagit yok. Evraki besleyiciye koyup tekrar deneyin.",
    WIA_ERROR_PAPER_PROBLEM: "Kagit duzgun beslenemedi. Evraki duzeltip tekrar deneyin.",
    WIA_ERROR_OFFLINE: (
        "Tarayici cevrimici degil. Cihazin acik oldugunu ve ag/USB baglantisini kontrol edin."
    ),
    WIA_ERROR_BUSY: "Tarayici su anda mesgul. Islem bitince tekrar deneyin.",
    WIA_ERROR_WARMING_UP: "Tarayici isiniyor. Birkac saniye sonra tekrar deneyin.",
    WIA_ERROR_USER_INTERVENTION: (
        "Tarayici mudahale bekliyor. Cihazin ekranindaki uyariyi kontrol edin."
    ),
    WIA_ERROR_ITEM_DELETED: "Tarama ogesi kayboldu. Cihazi yenileyip tekrar deneyin.",
    WIA_ERROR_DEVICE_COMMUNICATION: (
        "Tarayici ile iletisim kurulamadi. Kabloyu/ag baglantisini kontrol edin."
    ),
    WIA_ERROR_INVALID_COMMAND: "Tarayici bu komutu desteklemiyor.",
    WIA_ERROR_INCORRECT_HARDWARE_SETTING: "Tarayici ayari cihaz tarafindan kabul edilmedi.",
    WIA_ERROR_DEVICE_LOCKED: "Tarayici baska bir program tarafindan kullaniliyor.",
    WIA_ERROR_EXCEPTION_IN_DRIVER: (
        "Tarayici surucusunde hata olustu. Cihazi kapatip acin, gerekirse surucuyu yeniden kurun."
    ),
    WIA_ERROR_INVALID_DRIVER_RESPONSE: "Tarayici surucusu beklenmeyen bir yanit verdi.",
    WIA_S_NO_DEVICE_AVAILABLE: "Sistemde tarayici bulunamadi.",
    WIA_ERROR_COVER_OPEN: "Tarayicinin kapagi acik. Kapagi kapatip tekrar deneyin.",
    WIA_ERROR_LAMP_OFF: "Tarayici lambasi kapali. Cihazi kapatip acin.",
    WIA_ERROR_BUSY_TIMEOUT: "Tarayici zaman asimina ugradi. Tekrar deneyin.",
    WIA_ERROR_DESTINATION: "Taranan goruntu kaydedilemedi. Disk alanini kontrol edin.",
    WIA_ERROR_NETWORK_RESERVATION_FAILED: (
        "Ag tarayicisi baska bir kullanici tarafindan kullaniliyor."
    ),
    WIA_ERROR_USER_CANCELED: "Tarama iptal edildi.",
}

# Kullanicinin kendi iptali - hata olarak gosterilmemeli
IPTAL_KODLARI = frozenset({WIA_ERROR_USER_CANCELED})

# Yeniden denemenin anlamli oldugu gecici durumlar
GECICI_KODLAR = frozenset(
    {
        WIA_ERROR_BUSY,
        WIA_ERROR_WARMING_UP,
        WIA_ERROR_BUSY_TIMEOUT,
        WIA_ERROR_NETWORK_RESERVATION_FAILED,
    }
)

# Besleyici bittiginde donen kod - cok sayfali taramada dongu bitisi demektir
KAGIT_BITTI_KODLARI = frozenset({WIA_ERROR_PAPER_EMPTY})


class TaramaHatasi(Exception):
    """Tarayicidan gelen, kullaniciya gosterilebilir hata."""

    def __init__(self, mesaj: str, kod: int | None = None, ayrinti: str = ""):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.kod = kod
        self.ayrinti = ayrinti

    @property
    def iptal_mi(self) -> bool:
        return self.kod in IPTAL_KODLARI

    @property
    def gecici_mi(self) -> bool:
        return self.kod in GECICI_KODLAR

    @property
    def kagit_bitti_mi(self) -> bool:
        return self.kod in KAGIT_BITTI_KODLARI

    def __str__(self) -> str:
        if self.kod is None:
            return self.mesaj
        return f"{self.mesaj} (kod: 0x{self.kod:08X})"


def hresult_cikar(hata: BaseException) -> int | None:
    """pywintypes.com_error icinden asil WIA hata kodunu cikarir.

    com_error yapisi: (hresult, strerror, excepinfo, argerror)
    excepinfo yapisi: (wCode, source, description, helpfile, helpcontext, scode)
    Dis hresult genelde DISP_E_EXCEPTION (0x80020009) olur; asil kod scode'dadir.
    """
    args = getattr(hata, "args", None)
    if not args:
        return None

    kodlar: list[int] = []
    if isinstance(args[0], int):
        kodlar.append(args[0] & 0xFFFFFFFF)
    if len(args) > 2 and isinstance(args[2], (tuple, list)) and len(args[2]) >= 6:
        scode = args[2][5]
        if isinstance(scode, int):
            kodlar.insert(0, scode & 0xFFFFFFFF)  # ic kod once denenir

    for kod in kodlar:
        if kod in MESAJLAR:
            return kod
    return kodlar[0] if kodlar else None


def com_hatasini_cevir(hata: BaseException) -> TaramaHatasi:
    """Bir COM istisnasini kullaniciya gosterilebilir TaramaHatasi'na cevirir."""
    kod = hresult_cikar(hata)
    if kod in MESAJLAR:
        mesaj = MESAJLAR[kod]
    elif kod is not None:
        mesaj = f"Tarayici hatasi olustu (kod: 0x{kod:08X})."
    else:
        mesaj = "Tarayici ile iletisimde beklenmeyen bir hata olustu."
    return TaramaHatasi(mesaj, kod, ayrinti=str(hata))
