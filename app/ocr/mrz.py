"""TD1 (kimlik karti) MRZ cozumleyicisi ve dogrulayicisi.

Yeni TC kimlik kartinin arkasindaki 3 x 30 karakterlik makine okunabilir alan
(MRZ) ICAO 9303 TD1 standardindadir:

    I<TURA123456784<10000000146<<<
    8503057M3001019TUR<<<<<<<<<<<2
    OZDEMIR<<ALI<<<<<<<<<<<<<<<<<<

(Ornek sentetiktir: kontrol haneleri hesaplanarak uretilmistir, gercek bir
kimlige ait degildir.)

Bu alan OCR icin ideal: yalnizca A-Z, 0-9 ve '<' karakterlerini icerir VE
icinde kontrol haneleri vardir. Kontrol haneleri sayesinde okumanin dogru
olup olmadigi TAHMIN edilmez, HESAPLANIR.

Uygulamanin "hatasiz" olma sozu buraya dayanir: kontrol haneleri tutmuyorsa
alanlar bos birakilir ve kasiyerden elle girmesi istenir. Yanlis veriyle
dolu bir form asla uretilmez.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from app.validation import tc_gecerli_mi

# TD1: 3 satir, her biri 30 karakter
SATIR_UZUNLUGU = 30
SATIR_SAYISI = 3

DOLGU = "<"
GECERLI_KARAKTERLER = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<")

# ICAO 9303 kontrol hanesi agirliklari
_AGIRLIKLAR = (7, 3, 1)

# OCR'in sayisal alanlarda harfle karistirdigi karakterler
_SAYIYA = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                         "S": "5", "B": "8", "Z": "2", "G": "6", "T": "7"})
# OCR'in harf alanlarinda rakamla karistirdigi karakterler
_HARFE = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})


class MrzHatasi(Exception):
    """MRZ okunamadi veya dogrulanamadi."""


def karakter_degeri(karakter: str) -> int:
    """ICAO 9303'e gore karakterin sayisal degeri: '<'=0, 0-9=kendisi, A-Z=10-35."""
    if karakter == DOLGU:
        return 0
    if karakter.isdigit():
        return int(karakter)
    if "A" <= karakter <= "Z":
        return ord(karakter) - 55  # A -> 10
    raise MrzHatasi(f"MRZ'de gecersiz karakter: {karakter!r}")


def kontrol_hanesi(veri: str) -> int:
    """Verilen dizgenin ICAO 9303 kontrol hanesini hesaplar."""
    return (
        sum(
            karakter_degeri(karakter) * _AGIRLIKLAR[indeks % 3]
            for indeks, karakter in enumerate(veri)
        )
        % 10
    )


def _kontrol_uyuyor(veri: str, beklenen: str) -> bool:
    if not beklenen.isdigit():
        return False
    return kontrol_hanesi(veri) == int(beklenen)


def _tarih_coz(yymmdd: str, gelecek_olabilir: bool) -> _dt.date | None:
    """YYMMDD'yi tarihe cevirir.

    Iki haneli yil belirsizdir. Dogum tarihi gelecekte olamaz; gecerlilik
    tarihi ise gecmiste olabilir (suresi dolmus kimlik) ama genelde ileridedir.
    """
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, ay, gun = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not (1 <= ay <= 12 and 1 <= gun <= 31):
        return None

    bugun = _dt.date.today()
    yuzyil = bugun.year - bugun.year % 100
    try:
        tarih = _dt.date(yuzyil + yy, ay, gun)
    except ValueError:
        return None

    if gelecek_olabilir:
        # Gecerlilik tarihi: cok gerideyse bir sonraki yuzyila ait olmali
        if (bugun - tarih).days > 365 * 10:
            tarih = tarih.replace(year=tarih.year + 100)
    elif tarih > bugun:
        # Dogum tarihi gelecekte olamaz
        tarih = tarih.replace(year=tarih.year - 100)
    return tarih


# Guven duzeyleri
KESIN = "kesin"  # tum MRZ kontrol haneleri + TC algoritmasi tutuyor
YUKSEK = "yuksek"  # TC kendi algoritmasindan geciyor, dogum hanesi tutuyor
ORTA = "orta"  # MRZ yok; TC belge metninden okundu, algoritmadan gecti
DUSUK = "dusuk"  # dogrulanamadi - forma yazilmaz


@dataclass
class KimlikBilgisi:
    """MRZ'den cozulmus kimlik bilgileri."""

    tc: str = ""
    ad: str = ""
    soyad: str = ""
    dogum_tarihi: _dt.date | None = None
    gecerlilik_tarihi: _dt.date | None = None
    belge_no: str = ""
    uyruk: str = ""
    cinsiyet: str = ""

    # Hangi kontrollerin tuttugu
    kontroller: dict[str, bool] = field(default_factory=dict)
    ham_satirlar: list[str] = field(default_factory=list)

    @property
    def tum_kontroller_gecti(self) -> bool:
        """Butun kontroller tutuyorsa okuma matematiksel olarak dogrulanmistir."""
        return bool(self.kontroller) and all(self.kontroller.values())

    @property
    def basarisiz_kontroller(self) -> list[str]:
        return [ad for ad, gecti in self.kontroller.items() if not gecti]

    @property
    def guven(self) -> str:
        """Okumanin ne kadar guvenilir oldugunu dondurur.

        MRZ'nin bilesik kontrol hanesi satirin son karakteridir ve OCR'in en
        cok kacirdigi yerdir. Kacirildiginda TC'yi dogrulayacak MRZ hanesi
        kalmaz - ama TC Kimlik No'nun KENDI algoritmasi (son iki hane) bagimsiz
        bir dogrulama saglar. Bu yuzden iki asamali guven kullaniyoruz.
        """
        if not self.kontroller:
            return DUSUK
        tc_ok = self.kontroller.get("tc_algoritma", False)
        dogum_ok = self.kontroller.get("dogum_tarihi", False)
        belge_ok = self.kontroller.get("belge_no", False)
        bilesik_ok = self.kontroller.get("bilesik", False)

        if tc_ok and dogum_ok and belge_ok and bilesik_ok:
            return KESIN
        if tc_ok and dogum_ok and (belge_ok or bilesik_ok):
            return YUKSEK
        return DUSUK

    @property
    def guvenilir_mi(self) -> bool:
        """Forma otomatik yazilabilecek kadar guvenilir mi?"""
        return self.guven in (KESIN, YUKSEK)

    @property
    def tam_ad(self) -> str:
        return f"{self.ad} {self.soyad}".strip()


# OCR'in dolgu karakteri '<' yerine urettigi harfler. Tesseract'in standart
# ingilizce modeli OCR-B yazi tipindeki '<' isaretini en cok 'K' sanir; bu,
# MRZ okumasindaki bir numarali hata kaynagidir.
DOLGU_KARISIKLIGI = "KC"

# Bir satirin MRZ adayi sayilmasi icin gereken uzunluk araligi.
#
# Ust sinir comert tutulmalidir: OCR, MRZ satirinin basina ya da sonuna
# kimligin uzerindeki baska metni ekleyebiliyor. Gercek bir taramada su
# satirlar okundu (dogrusu 30 karakter):
#     'TTOR8802015F2905132TURK<<<<<<<<<<K<6'   36 karakter
#     '13052029BAYINDIR<<UMMU<<<<<<<<<<<<<'    35 karakter
# Dar bir sinir bunlari eler ve MRZ hic okunamaz. Yanlis adaylari uzunluk
# degil, kontrol haneleri ve ad satiri sekil denetimi eler.
_ASGARI_UZUNLUK = SATIR_UZUNLUGU - 4
_AZAMI_UZUNLUK = SATIR_UZUNLUGU + 14

# TD1'de ulke kodu 'TUR' sabit konumdadir: 1. satirda 2., 2. satirda 15.
# karakterden baslar. Bunu capa alarak satiri dogru hizaya oturtmak, kor
# kaydirma denemelerinden hem daha kesin hem cok daha hizlidir.
_ULKE_KODU = "TUR"
_ULKE_KONUMU = {0: 2, 1: 15}


def satirlari_temizle(metin: str) -> list[str]:
    """OCR ciktisindan MRZ'ye benzeyen satirlari ayiklar.

    Sayfanin herhangi bir yerinde olabilir; sabit koordinat kullanmiyoruz
    cunku kimlik her taramada ayni yere denk gelmez. Eleme kasitli olarak
    genis tutulur - yanlis adaylari kontrol haneleri zaten eler.
    """
    adaylar: list[str] = []
    for satir in metin.splitlines():
        # MRZ'de bosluk yoktur; OCR araya bosluk koyabilir
        temiz = re.sub(r"\s+", "", satir.upper())
        temiz = "".join(k for k in temiz if k in GECERLI_KARAKTERLER)
        if _ASGARI_UZUNLUK <= len(temiz) <= _AZAMI_UZUNLUK:
            adaylar.append(temiz)
    return adaylar


def ad_satiri_makul_mu(satir: str) -> bool:
    """3. satirin gercekten MRZ ad satiri olup olmadigini sinar.

    TD1'de ad satirini koruyan HICBIR kontrol hanesi yoktur. Dolayisiyla
    dogru okunmus 1. ve 2. satirlar, sayfadaki alakasiz bir metin satiriyla
    eslesebilir ve forma cop bir isim yazilabilir. Bu sinama onu engeller:

      - Ad satirinda rakam bulunmaz
      - Isimler 30 karakteri doldurmaz; sonda dolgu olmak zorundadir
      - Soyad ile ad '<<' ile ayrilir
    """
    if not satir or any(karakter.isdigit() for karakter in satir):
        return False
    if len(satir) > SATIR_UZUNLUGU:
        return False
    hizali = satir.ljust(SATIR_UZUNLUGU, DOLGU)
    if not hizali.endswith(DOLGU):
        return False
    return DOLGU * 2 in hizali.rstrip(DOLGU) or len(satir) < SATIR_UZUNLUGU


def dolgu_duzelt(satir: str) -> str:
    """Dolgu olarak okunmus harf dizilerini '<' karakterine cevirir.

    Yalnizca IKI VE DAHA FAZLA ardisik karisiklik harfi donusturulur; tek
    basina duran K bir isimde gecen gercek harf olabilir ('KAYA'). Ardisik
    'KK' ise MRZ'de neredeyse her zaman '<<' dolgusudur.
    """
    return re.sub(
        rf"[{DOLGU_KARISIKLIGI}]{{2,}}",
        lambda esleme: DOLGU * len(esleme.group()),
        satir,
    )


# Satirin basinda kac karaktere kadar OCR copu aranacagi. Kimligin yanindaki
# desen/hologram MRZ satirinin basina birkac harf ekleyebiliyor:
#   'GCI<TURA19K671336<...'  <- dogrusu 'I<TURA19K671336<...'
# Bastaki cop tum alanlari kaydirdigi icin kontrol haneleri tutmaz.
AZAMI_BAS_KAYMASI = 4


def _satir_adaylari(satir: str, satir_sirasi: int = 0) -> list[str]:
    """Bir satir icin denenecek varyantlari dondurur (once ham hali).

    Uc tur bozulma denenir ve dogrusunu kontrol haneleri secer:
      - dolgu karakterinin harf okunmasi ('<' -> 'K')
      - satirin basina cop eklenmesi (kayma)
    """
    tabanlar = [satir]
    for uretici in (dolgu_duzelt, lambda s: re.sub(rf"[{DOLGU_KARISIKLIGI}]", DOLGU, s)):
        aday = uretici(satir)
        if aday not in tabanlar:
            tabanlar.append(aday)

    varyantlar: list[str] = []
    for taban in tabanlar:
        # 'TUR' capasi: satiri dogru hizaya oturtan en olasi adaylar once
        for aday in _ulke_koduyla_hizala(taban, satir_sirasi):
            if aday not in varyantlar:
                varyantlar.append(aday)
        # Capa bulunamazsa kisa kor kaydirmalar
        fazla = min(len(taban) - SATIR_UZUNLUGU, AZAMI_BAS_KAYMASI)
        for kayma in range(max(fazla, 0) + 1):
            aday = taban[kayma:]
            if aday not in varyantlar:
                varyantlar.append(aday)
    return varyantlar


def _ulke_koduyla_hizala(satir: str, satir_sirasi: int):
    """'TUR' ulke kodunu sabit konumuna oturtacak kaydirmalari uretir."""
    konum = _ULKE_KONUMU.get(satir_sirasi)
    if konum is None:
        return
    for eslesme in re.finditer(_ULKE_KODU, satir):
        baslangic = eslesme.start() - konum
        if baslangic > 0:
            yield satir[baslangic:]
        elif baslangic == 0:
            yield satir


def ad_satirini_kirp(satir: str) -> str:
    """Ad satirinin basindaki OCR copunu atar.

    Gercek bir taramada '13052029BAYINDIR<<UMMU<<<' okundu; bastaki rakamlar
    kimligin uzerindeki tarih alanindan sizmis. Ad satirinda rakam bulunmaz,
    dolayisiyla bastaki rakamlar ve dolgular guvenle atilabilir.
    """
    return satir.lstrip("0123456789" + DOLGU)


def _satiri_hizala(satir: str) -> str:
    """Satiri tam 30 karaktere getirir (eksikse dolgu ekler, fazlaysi kirpar)."""
    if len(satir) < SATIR_UZUNLUGU:
        return satir.ljust(SATIR_UZUNLUGU, DOLGU)
    return satir[:SATIR_UZUNLUGU]


def _alani_duzelt(alan: str, sayisal: bool) -> str:
    """OCR'in karistirdigi karakterleri alanin turune gore duzeltir."""
    return alan.translate(_SAYIYA if sayisal else _HARFE)


def _ucluyu_coz(satirlar: list[str], duzelt: bool) -> KimlikBilgisi | None:
    """MRZ satirlarini cozumler. Cozulemezse None doner.

    Ad satiri (3. satir) istege baglidir. Dogrulanabilen tum veri - TC, dogum
    tarihi, belge no, gecerlilik - 1. ve 2. satirdadir; OCR ad satirini
    kacirdiginda bunlari da kaybetmek gereksiz olurdu.
    """
    if len(satirlar) < 2:
        return None
    ham3 = satirlar[2] if len(satirlar) > 2 else ""
    l1, l2 = (_satiri_hizala(s) for s in satirlar[:2])
    l3 = _satiri_hizala(ham3) if ham3 else DOLGU * SATIR_UZUNLUGU

    belge_no = l1[5:14]
    belge_kd = l1[14]
    opsiyonel1 = l1[15:30]
    dogum = l2[0:6]
    dogum_kd = l2[6]
    cinsiyet = l2[7]
    gecerlilik = l2[8:14]
    gecerlilik_kd = l2[14]
    uyruk = l2[15:18]
    opsiyonel2 = l2[18:29]
    bilesik_kd = l2[29]

    if duzelt:
        # Tarih alanlari tamamen sayisal; kontrol haneleri de oyle
        dogum = _alani_duzelt(dogum, sayisal=True)
        gecerlilik = _alani_duzelt(gecerlilik, sayisal=True)
        dogum_kd = _alani_duzelt(dogum_kd, sayisal=True)
        gecerlilik_kd = _alani_duzelt(gecerlilik_kd, sayisal=True)
        belge_kd = _alani_duzelt(belge_kd, sayisal=True)
        bilesik_kd = _alani_duzelt(bilesik_kd, sayisal=True)
        uyruk = _alani_duzelt(uyruk, sayisal=False)
        # TC yalnizca rakamdan olusur
        opsiyonel1 = "".join(
            _alani_duzelt(k, sayisal=True) if k != DOLGU else k for k in opsiyonel1
        )
        l2 = dogum + dogum_kd + cinsiyet + gecerlilik + gecerlilik_kd + uyruk + opsiyonel2 + bilesik_kd
        l1 = l1[:14] + belge_kd + opsiyonel1

    tc = opsiyonel1.replace(DOLGU, "").strip()
    bilesik_veri = l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]
    kontroller = {
        "belge_no": _kontrol_uyuyor(belge_no, belge_kd),
        "dogum_tarihi": _kontrol_uyuyor(dogum, dogum_kd),
        "gecerlilik": _kontrol_uyuyor(gecerlilik, gecerlilik_kd),
        "bilesik": _kontrol_uyuyor(bilesik_veri, bilesik_kd),
        # MRZ'den bagimsiz dogrulama: TC Kimlik No'nun kendi saglama algoritmasi.
        # Bilesik hane OCR'da kacirildiginda TC'yi dogrulayan tek kanit budur.
        "tc_algoritma": tc_gecerli_mi(tc),
    }

    # 3. satir: SOYAD<<AD<IKINCI-AD
    # Ad satiri hicbir kontrol hanesiyle korunmadigi icin once seklen
    # dogrulanir; supheliyse ad/soyad BOS birakilir. Dogrulanmis TC ve
    # dogum tarihi yine kullanilir, adi kasiyer yazar.
    ad = soyad = ""
    kontroller["ad_satiri"] = bool(ham3) and ad_satiri_makul_mu(ham3)
    if kontroller["ad_satiri"]:
        ad_alani = l3.rstrip(DOLGU)
        soyad_ham, _, ad_ham = ad_alani.partition(DOLGU * 2)
        soyad = soyad_ham.replace(DOLGU, " ").strip()
        ad = ad_ham.replace(DOLGU, " ").strip()

    return KimlikBilgisi(
        tc=tc,
        ad=ad,
        soyad=soyad,
        dogum_tarihi=_tarih_coz(dogum, gelecek_olabilir=False),
        gecerlilik_tarihi=_tarih_coz(gecerlilik, gelecek_olabilir=True),
        belge_no=belge_no.replace(DOLGU, "").strip(),
        uyruk=uyruk.replace(DOLGU, "").strip(),
        cinsiyet=cinsiyet if cinsiyet in ("M", "F") else "",
        kontroller=kontroller,
        ham_satirlar=[l1, l2, l3],
    )


def coz(metin: str) -> KimlikBilgisi | None:
    """OCR metninden MRZ'yi bulup cozumler.

    OCR hatalarina karsi birden fazla duzeltme varyanti denenir ve dogrusunu
    KONTROL HANELERI secer - tahmin yurutulmez. Dort kontrol hanesinin ayni
    anda yanlislikla tutma olasiligi 10.000'de birdir, dolayisiyla "hepsi
    gecti" sonucu pratikte kesinliktir.

    1. ve 2. satirlarda varyantlar bagimsiz denenir; 3. satir (ad soyad)
    hicbir kontrol hanesiyle korunmadigi icin yalnizca ihtiyatli dolgu
    duzeltmesinden gecirilir ve kasiyerin onayina birakilir.
    """
    adaylar = satirlari_temizle(metin)
    if len(adaylar) < 2:
        return None

    en_iyi: KimlikBilgisi | None = None
    for baslangic in range(len(adaylar) - 1):
        ham1, ham2 = adaylar[baslangic], adaylar[baslangic + 1]
        # Ad satiri varsa kullan; yoksa TC ve dogum tarihi yine okunur
        sonraki = adaylar[baslangic + 2] if baslangic + 2 < len(adaylar) else ""
        satir3 = ad_satirini_kirp(dolgu_duzelt(sonraki)) if sonraki else ""

        for satir1 in _satir_adaylari(ham1, 0):
            for satir2 in _satir_adaylari(ham2, 1):
                for duzelt in (False, True):
                    sonuc = _ucluyu_coz([satir1, satir2, satir3], duzelt)
                    if sonuc is None:
                        continue
                    if sonuc.tum_kontroller_gecti:
                        return sonuc
                    gecen = sum(sonuc.kontroller.values())
                    if en_iyi is None or gecen > sum(en_iyi.kontroller.values()):
                        en_iyi = sonuc
    return en_iyi


def coz_veya_hata(metin: str) -> KimlikBilgisi:
    """coz() gibidir ama MRZ bulunamazsa MrzHatasi firlatir."""
    sonuc = coz(metin)
    if sonuc is None:
        raise MrzHatasi(
            "Kimliğin arka yüzündeki makine okunabilir alan (MRZ) bulunamadı. "
            "Kimliği düz ve tam olarak tarayın."
        )
    return sonuc
