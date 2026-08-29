"""Girdi dogrulama ve Turkce metin normalizasyonu."""

from __future__ import annotations

import datetime as _dt
import re

# Python'un .lower()/.upper() metodlari Turkce'de yanlis sonuc verir:
# "ISTANBUL".lower() -> "istanbul" (dogrusu "ıstanbul"), "istanbul".upper() -> "ISTANBUL"
# (dogrusu "İSTANBUL"). Bu yuzden i/I ciftini once elle esliyoruz.
_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I"})
_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})

_COKLU_BOSLUK = re.compile(r"\s+")


def tr_upper(metin: str) -> str:
    """Turkce kurallarina uygun buyuk harfe cevirir."""
    return metin.translate(_UPPER_MAP).upper()


def tr_lower(metin: str) -> str:
    """Turkce kurallarina uygun kucuk harfe cevirir."""
    return metin.translate(_LOWER_MAP).lower()


def ad_normalize(metin: str) -> str:
    """Ad/soyadi arsivde kullanilan bicime getirir: tek bosluk, buyuk harf."""
    return _COKLU_BOSLUK.sub(" ", metin.strip()).translate(_UPPER_MAP).upper()


def tc_normalize(tc: str) -> str:
    """TC alanindan rakam disi her seyi atar."""
    return re.sub(r"\D", "", tc or "")


def tc_gecerli_mi(tc: str) -> bool:
    """TC Kimlik No'yu resmi algoritmayla dogrular.

    Kurallar:
      1. 11 hane, tamami rakam
      2. Ilk hane 0 olamaz
      3. (d1+d3+d5+d7+d9)*7 - (d2+d4+d6+d8) mod 10 == d10
      4. Ilk 10 hanenin toplami mod 10 == d11
    """
    tc = tc_normalize(tc)
    if len(tc) != 11 or tc[0] == "0":
        return False
    d = [int(k) for k in tc]
    tek_toplam = d[0] + d[2] + d[4] + d[6] + d[8]
    cift_toplam = d[1] + d[3] + d[5] + d[7]
    if (tek_toplam * 7 - cift_toplam) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def tc_hata_mesaji(tc: str) -> str | None:
    """Gecersizse kullaniciya gosterilecek Turkce mesaji, gecerliyse None doner."""
    ham = tc_normalize(tc)
    if not ham:
        return "TC Kimlik No bos birakilamaz."
    if len(ham) != 11:
        return f"TC Kimlik No 11 haneli olmali (girilen: {len(ham)} hane)."
    if ham[0] == "0":
        return "TC Kimlik No sifir ile baslayamaz."
    if not tc_gecerli_mi(ham):
        return "TC Kimlik No gecersiz - lutfen kontrol edin."
    return None


def tc_son4(tc: str) -> str:
    """Klasor adinda kullanilan son 4 hane."""
    return tc_normalize(tc)[-4:]


_TARIH_BICIMLERI = ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%Y-%m-%d")


def dogum_tarihi_ayristir(metin: str) -> _dt.date | None:
    """Opsiyonel dogum tarihi alanini ayristirir. Bos ise None doner.

    Ayristirilamayan ama bos olmayan girdi icin ValueError firlatir.
    """
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in _TARIH_BICIMLERI:
        try:
            tarih = _dt.datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
        bugun = _dt.date.today()
        if tarih > bugun:
            raise ValueError("Dogum tarihi gelecekte olamaz.")
        if tarih.year < 1900:
            raise ValueError("Dogum tarihi 1900'den eski olamaz.")
        return tarih
    raise ValueError("Dogum tarihi GG.AA.YYYY biciminde olmali (orn. 05.03.1985).")
