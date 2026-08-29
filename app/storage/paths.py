r"""Arsiv klasor ve dosya adi uretimi.

Mevcut elle olusturulmus arsivle birebir uyumlu duzen:

    <KOK>\<SUBE>6\01.2026\02.01.26\ALI OZDEMIR 8901\

SUBE seviyesi yalnizca ayarlarda sube tanimliysa eklenir.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from app.validation import ad_normalize, tc_son4

# Windows'ta dosya/klasor adinda kullanilamayan karakterler.
# Duzenli ifade yerine ceviri tablosu kullaniliyor: karakter sinifi icinde
# ters bolunun kacirilmasi kolayca yanlis yazilabiliyor ve sessizce eleyip
# gecmeyen bir desen olusuyor. chr(92) ile ters bolu tartismasiz belirtilir.
_YASAK_KARAKTERLER = '<>:"/|?*' + chr(92)
_CEVIRI_TABLOSU = {ord(karakter): " " for karakter in _YASAK_KARAKTERLER}
_CEVIRI_TABLOSU.update({kod: " " for kod in range(32)})  # kontrol karakterleri

_COKLU_BOSLUK = re.compile(r"\s+")

# Windows'ta rezerve edilmis aygit adlari (uzantili hali de gecersiz)
_REZERVE_ADLAR = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Tek bir klasor/dosya adi icin guvenli ust sinir (260 karakterlik yol
# limitine karsi pay birakir)
AD_UZUNLUK_SINIRI = 60


def ad_temizle(ad: str, uzunluk_siniri: int = AD_UZUNLUK_SINIRI) -> str:
    """Verilen metni Windows'ta gecerli bir klasor/dosya adina cevirir.

    Turkce karakterler korunur - NTFS ve Google Drive UTF-8 destekler.
    """
    temiz = ad.translate(_CEVIRI_TABLOSU)
    temiz = _COKLU_BOSLUK.sub(" ", temiz).strip()
    # Windows sondaki nokta ve boslugu sessizce kirpar; biz bilerek kirpiyoruz
    temiz = temiz.rstrip(". ")
    if temiz.split(".")[0].upper() in _REZERVE_ADLAR:
        temiz = f"_{temiz}"
    if len(temiz) > uzunluk_siniri:
        temiz = temiz[:uzunluk_siniri].rstrip(". ")
    return temiz or "ISIMSIZ"


def musteri_klasor_adi(ad: str, soyad: str, tc: str) -> str:
    """'ALI OZDEMIR 8901' bicimindeki musteri klasor adini uretir.

    Son 4 hane, ayni gun ayni isimli farkli musterileri ayirt etmek icin
    eklenir; ayni TC ayni gun tekrar gelirse ayni klasore denk gelir.
    """
    tam_ad = ad_normalize(f"{ad} {soyad}")
    return ad_temizle(f"{tam_ad} {tc_son4(tc)}".strip())


def tarih_parcalari(tarih: _dt.date) -> tuple[str, str, str]:
    """(yil, ay, gun) klasor adlarini arsiv bicimiyle dondurur.

    Ornek: 2 Ocak 2026 -> ('2026', '01.2026', '02.01.26')
    """
    return (
        f"{tarih.year:04d}",
        f"{tarih.month:02d}.{tarih.year:04d}",
        f"{tarih.day:02d}.{tarih.month:02d}.{tarih.year % 100:02d}",
    )


def goreli_parcalar(
    ad: str,
    soyad: str,
    tc: str,
    tarih: _dt.date,
    sube: str | None = None,
) -> list[str]:
    """Kok klasorden itibaren yol parcalarini dondurur.

    Ayni liste hem yerel diskte hem Google Drive'da klasor agacini kurmak
    icin kullanilir - iki taraf boylece asla ayrisamaz.
    """
    parcalar: list[str] = []
    if sube and sube.strip():
        parcalar.append(ad_temizle(sube))
    parcalar.extend(tarih_parcalari(tarih))
    parcalar.append(musteri_klasor_adi(ad, soyad, tc))
    return parcalar


def kayit_klasoru(
    kok: str | Path,
    ad: str,
    soyad: str,
    tc: str,
    tarih: _dt.date,
    sube: str | None = None,
) -> Path:
    """Musterinin tam yerel klasor yolunu dondurur (klasoru olusturmaz)."""
    yol = Path(kok)
    for parca in goreli_parcalar(ad, soyad, tc, tarih, sube):
        yol = yol / parca
    return yol


def pdf_dosya_adi(ad: str, soyad: str, tarih: _dt.date) -> str:
    """'ALI OZDEMIR_02.01.2026.pdf' bicimindeki birlesik PDF adini uretir."""
    tam_ad = ad_normalize(f"{ad} {soyad}")
    gun = f"{tarih.day:02d}.{tarih.month:02d}.{tarih.year:04d}"
    return f"{ad_temizle(f'{tam_ad}_{gun}')}.pdf"


_SAYFA_ADI = re.compile(r"^(\d{2,})\.jpg$", re.IGNORECASE)


def mevcut_sayfa_numaralari(klasor: str | Path) -> list[int]:
    """Klasordeki 01.jpg, 02.jpg ... dosyalarinin numaralarini dondurur."""
    yol = Path(klasor)
    if not yol.is_dir():
        return []
    numaralar = []
    for dosya in yol.iterdir():
        eslesme = _SAYFA_ADI.match(dosya.name)
        if eslesme:
            numaralar.append(int(eslesme.group(1)))
    return sorted(numaralar)


def sonraki_sayfa_numarasi(klasor: str | Path) -> int:
    """Ayni musteri ayni gun tekrar gelirse sayfa numarasi kaldigi yerden devam eder."""
    numaralar = mevcut_sayfa_numaralari(klasor)
    return (numaralar[-1] + 1) if numaralar else 1


def sayfa_dosya_adi(numara: int) -> str:
    """1 -> '01.jpg', 12 -> '12.jpg', 123 -> '123.jpg'"""
    return f"{numara:02d}.jpg"
