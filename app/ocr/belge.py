"""MRZ'siz belgelerden TC ve dogum tarihi cikarimi.

Kimlik KARTI'nin arkasinda MRZ vardir ve kontrol haneleriyle kesin dogrulama
saglar (bkz. app/ocr/mrz.py). Ancak musteriler baska belgeler de getiriyor:

  - Surucu belgesi: TC, '4d' alaninda yazar; MRZ yoktur
  - Eski nufus cuzdani
  - Doviz alim/satim belgesinin kendisi (uzerinde TC basili)

Bu modul bu belgelerde TC'yi bulur. Dogrulayici olarak MRZ kontrol haneleri
yerine TC Kimlik No'nun KENDI saglama algoritmasi kullanilir.

Guvenilirlik acikca daha dusuktur ve oyle raporlanir: rastgele 11 haneli bir
sayinin TC algoritmasindan gecme olasiligi 1/100'dur. Bu yuzden tek basina
yeterli sayilmaz; su ek kanitlar aranir:

  1. Baglam - numaranin yaninda '4d', 'TC', 'Kimlik No' gibi bir etiket
  2. Mutabakat - ayni numaranin sayfada birden fazla yerde gecmesi
  3. Teklik - algoritmadan gecen baska aday bulunmamasi

Hicbiri saglanmazsa alan bos birakilir.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from app.validation import tc_gecerli_mi, tc_normalize

# TC'nin yaninda gecmesi beklenen etiketler (buyuk harfe cevrilmis metinde
# aranir). '4D' surucu belgesindeki alan numarasidir.
_BAGLAM_ETIKETLERI = (
    "4D",
    "TC KIMLIK",
    "T.C. KIMLIK",
    "TCKN",
    "KIMLIK NO",
    "KIMLIK NUMARASI",
    "TC NO",
    "T.C. NO",
    "VATANDASLIK",
    "PASSPORT NO",
    "PASAPORT NO",
)

# Etiketin numaradan en fazla kac karakter once gecebilecegi
_BAGLAM_PENCERESI = 40

# Bir kisinin makul yas araligi - dogum tarihi adaylarini elemek icin
_ASGARI_YAS = 16
_AZAMI_YAS = 110

# OCR'in rakam yerine urettigi harfler
_RAKAMA = str.maketrans(
    {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1",
     "S": "5", "B": "8", "Z": "2", "G": "6", "T": "7", "A": "4"}
)

# Rakamlar arasina OCR'in serpistirdigi bosluk/nokta/tire
_AYIRICI = re.compile(r"[ .\-_/]")

# OCR'in rakam yerine urettigi noktalama isaretleri. '/' hem gercek bir
# ayirici hem de yanlis okunmus bir '7' olabilir; bu yuzden iki yorum da
# denenir (bkz. _rakam_dizileri).
_BELIRSIZ_RAKAM = str.maketrans({"/": "7", "?": "7", "|": "1", "!": "1",
                                 "l": "1", "I": "1"})

_TARIH = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")


# Ayni fiziksel gecisi tekrar saymamak icin konum toleransi. Uc ayri desen
# ayni numarayi birkac karakter kaymis konumlarda bulabiliyor.
_KONUM_TOLERANSI = 15


@dataclass
class TcAdayi:
    """Sayfada bulunmus, TC algoritmasindan gecen bir numara."""

    tc: str
    etiketli: bool = False  # yaninda '4d', 'TC Kimlik No' gibi bir etiket var mi
    baglamlar: list[str] = field(default_factory=list)
    konumlar: list[int] = field(default_factory=list)

    def konum_ekle(self, konum: int) -> None:
        """Yeni bir gecis konumu kaydeder; ayni gecisi tekrar saymaz."""
        if any(abs(konum - mevcut) <= _KONUM_TOLERANSI for mevcut in self.konumlar):
            return
        self.konumlar.append(konum)

    @property
    def tekrar(self) -> int:
        """Sayfadaki BIRBIRINDEN AYRI gecis sayisi."""
        return max(len(self.konumlar), 1)

    @property
    def skor(self) -> int:
        """Kanit gucu. Yuksek olan tercih edilir."""
        return (2 if self.etiketli else 0) + min(self.tekrar - 1, 2)

    @property
    def guclu_mu(self) -> bool:
        """Tek basina forma yazilacak kadar kanit var mi?

        Ya bir etiketin yaninda gecmeli, ya da sayfada birden fazla yerde
        ayni sekilde gecmeli. Ikisi de yoksa 1/100'luk yanlis pozitif riski
        tek basina tasinmaz.
        """
        return self.etiketli or self.tekrar >= 2


def _rakam_dizileri(metin: str):
    """Metinden 11 haneye ulasabilecek rakam dizilerini konumlariyla uretir.

    OCR uc ayri sekilde bozar ve ucu de denenir:

      - Rakamlarin arasina bosluk koyar: '321 700 080 12'
      - Rakami harf okur: '32I70008012'
      - Rakami noktalama okur: '321/0008012' - burada '/' hem ayirici hem de
        yanlis okunmus bir '7' olabilir. Iki yorum da uretilir; hangisinin
        dogru oldugunu TC algoritmasi secer.
    """
    # 1) Duz rakam dizileri
    for eslesme in re.finditer(r"\d{9,}", metin):
        yield eslesme.start(), eslesme.group()

    # 2) Ayiricilarla bolunmus diziler - ayiricilar ATILIR
    for eslesme in re.finditer(r"\d[\d .\-_/]{9,20}\d", metin):
        temiz = _AYIRICI.sub("", eslesme.group())
        if temiz.isdigit():
            yield eslesme.start(), temiz

    # 3) Belirsiz karakterler RAKAMA cevrilir ('/' -> 7, '|' -> 1 gibi)
    for eslesme in re.finditer(r"[\d/|!?lI]{11,22}", metin):
        ham = eslesme.group()
        if not any(karakter.isdigit() for karakter in ham):
            continue
        temiz = ham.translate(_BELIRSIZ_RAKAM)
        if temiz.isdigit():
            yield eslesme.start(), temiz

    # 4) Harf karisikligi olan diziler (OCR duzeltmesiyle)
    for eslesme in re.finditer(r"[\dOQDILSBZGTA|]{11,13}", metin):
        ham = eslesme.group()
        if not any(karakter.isdigit() for karakter in ham):
            continue
        temiz = ham.translate(_RAKAMA)
        if temiz.isdigit():
            yield eslesme.start(), temiz


def _etiketli_mi(metin: str, konum: int) -> tuple[bool, str]:
    """Numaradan hemen once TC etiketi gecip gecmedigine bakar."""
    baslangic = max(0, konum - _BAGLAM_PENCERESI)
    onceki = metin[baslangic:konum].upper()
    # Turkce harfleri sadelestir; OCR bunlari kacirabiliyor
    onceki = (
        onceki.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
        .replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
    )
    for etiket in _BAGLAM_ETIKETLERI:
        if etiket in onceki:
            return True, etiket
    return False, ""


def tc_adaylari(metin: str) -> list[TcAdayi]:
    """Metindeki gecerli TC adaylarini kanit gucune gore sirali dondurur."""
    bulunanlar: dict[str, TcAdayi] = {}

    for konum, dizi in _rakam_dizileri(metin):
        # 11 haneden uzun dizilerde kayan pencere ile ara
        for baslangic in range(0, len(dizi) - 10):
            aday = dizi[baslangic : baslangic + 11]
            if not tc_gecerli_mi(aday):
                continue

            etiketli, etiket = _etiketli_mi(metin, konum)
            kayit = bulunanlar.get(aday)
            if kayit is None:
                kayit = TcAdayi(tc=aday)
                bulunanlar[aday] = kayit
            kayit.konum_ekle(konum)
            if etiketli and etiket not in kayit.baglamlar:
                kayit.etiketli = True
                kayit.baglamlar.append(etiket)

    return sorted(bulunanlar.values(), key=lambda a: a.skor, reverse=True)


def tc_sec(metin: str) -> TcAdayi | None:
    """Sayfadaki TC'yi secer; emin olunamiyorsa None doner.

    Birden fazla aday ayni gucteyse hicbiri secilmez - yanlis musteriye kayit
    acmaktansa kasiyerin elle girmesi yeglenir.
    """
    adaylar = tc_adaylari(metin)
    if not adaylar:
        return None

    en_iyi = adaylar[0]
    if not en_iyi.guclu_mu:
        return None
    # Esit guclu ikinci bir aday varsa hangisi oldugu belirsizdir
    if len(adaylar) > 1 and adaylar[1].skor == en_iyi.skor:
        return None
    return en_iyi


def dogum_tarihi_adaylari(metin: str, bugun: _dt.date | None = None) -> list[_dt.date]:
    """Metindeki tarihlerden dogum tarihi olabilecekleri dondurur.

    Belgede baska tarihler de vardir (verilis, gecerlilik, islem tarihi).
    Yalnizca makul bir yas veren gecmis tarihler aday sayilir.
    """
    bugun = bugun or _dt.date.today()
    adaylar: list[_dt.date] = []
    for gun, ay, yil in _TARIH.findall(metin):
        try:
            tarih = _dt.date(int(yil), int(ay), int(gun))
        except ValueError:
            continue
        yas = (bugun - tarih).days / 365.25
        if _ASGARI_YAS <= yas <= _AZAMI_YAS and tarih not in adaylar:
            adaylar.append(tarih)
    return adaylar


def dogum_tarihi_sec(metin: str, bugun: _dt.date | None = None) -> _dt.date | None:
    """Dogum tarihini secer; birden fazla makul aday varsa None doner.

    Dogum tarihi formda zaten istege bagli oldugu icin, suphede kalmaktansa
    bos birakmak dogru davranistir.
    """
    adaylar = dogum_tarihi_adaylari(metin, bugun)
    return adaylar[0] if len(adaylar) == 1 else None


# Surucu belgesinde ad ve soyad numarali alanlarda yazar:
#   1. SUNDU      (soyad)
#   2. Gürsoy     (ad)
#
# Alan numarasindan once birkac karakterlik cop kabul edilir: kartin
# cercevesi ve hologramu OCR'da satir basina '7 1. SUNDU' ya da 'ç 2. Gürsoy'
# gibi tek karakterlik lekeler birakiyor. Satir basina baglayan eski desen
# bu yuzden gercek taramalarda hic tutmuyordu.
_ALAN_ONEKI = r"^.{0,4}?"
_ALAN_SONU = r"[.\)]\s*([A-ZÇĞİÖŞÜa-zçğıöşü].*)$"
_SOYAD_ALANI = re.compile(_ALAN_ONEKI + "1" + _ALAN_SONU, re.M)
_AD_ALANI = re.compile(_ALAN_ONEKI + "2" + _ALAN_SONU, re.M)

# Isim olabilecek tek kelime: yalnizca harf, kesme isareti ve tire
_ISIM_KELIMESI = re.compile(r"^[A-ZÇĞİÖŞÜa-zçğıöşü][A-ZÇĞİÖŞÜa-zçğıöşü'\-]*$")

# Bir isimde en fazla kac kelime kabul edilecegi
_AZAMI_ISIM_KELIMESI = 3

# Tek harflik 'kelime' isim degildir; OCR lekesidir
_ASGARI_ISIM_UZUNLUGU = 2


def _isim_ayikla(satir: str) -> str:
    """Satirin basindaki isim kelimelerini alir, ilk isim-disi kelimede durur.

    Tesseract iki sutunlu sayfalarda sutunlari TEK SATIRDA birlestiriyor:

        '1. SUNDU DSB2025000031802'      <- soyad + yandaki belge numarasi
        '2. Gürsoy 01/05/2025 19:04'     <- ad + yandaki islem tarihi

    Sutun bosluklari kayboldugu icin bosluga gore bolmek ise yaramaz. Rakam
    iceren ilk kelimede durmak bu birlesmeyi guvenilir sekilde keser; gercek
    iki kelimeli isimler ('ALİ VELİ') etkilenmez.

    Kart kenarindan gelen lekeler ise rakam icermez:

        '1. SUNDU j Ae le | Fi'          <- soyad + hologram lekeleri

    Bunlar icin iki kural daha var: tek harflik kelime isim sayilmaz ve
    kelimenin yazim bicimi ilk kelimeyle ayni olmalidir. Surucu belgesinde
    soyad BUYUK ('SUNDU'), ad Ilk-Harfi-Buyuk ('Gürsoy') yazilir; leke
    ikisine de uymaz.
    """
    kelimeler: list[str] = []
    for kelime in satir.split():
        if not _ISIM_KELIMESI.match(kelime):
            break
        if len(kelime) < _ASGARI_ISIM_UZUNLUGU:
            break
        if kelimeler and kelime.isupper() != kelimeler[0].isupper():
            break
        kelimeler.append(kelime)
        if len(kelimeler) >= _AZAMI_ISIM_KELIMESI:
            break
    return " ".join(kelimeler)


def ad_soyad_sec(metin: str) -> tuple[str, str]:
    """Surucu belgesindeki numarali alanlardan ad ve soyadi okur.

    Hicbir kontrol mekanizmasi yoktur; sonuc daima kasiyerin onayina sunulur.
    Bulunamayan alan bos doner.
    """
    soyad_eslesme = _SOYAD_ALANI.search(metin)
    ad_eslesme = _AD_ALANI.search(metin)
    soyad = _isim_ayikla(soyad_eslesme.group(1)) if soyad_eslesme else ""
    ad = _isim_ayikla(ad_eslesme.group(1)) if ad_eslesme else ""
    return ad, soyad
