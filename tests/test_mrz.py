"""MRZ cozumleyici testleri.

Testlerde gercek kisiye ait kimlik verisi KULLANILMAZ; MRZ'ler kontrol
haneleri hesaplanarak sentetik olarak uretilir.
"""

import datetime as dt

import pytest

from app.ocr.mrz import (
    DUSUK,
    KESIN,
    YUKSEK,
    ad_satiri_makul_mu,
    coz,
    dolgu_duzelt,
    karakter_degeri,
    kontrol_hanesi,
    satirlari_temizle,
)

TC = "10000000146"  # TC algoritmasindan gecen sahte numara
BELGE_NO = "A12345678"
DOGUM = "850305"  # 05.03.1985
GECERLILIK = "300101"  # 01.01.2030


def mrz_uret(
    tc: str = TC,
    belge_no: str = BELGE_NO,
    dogum: str = DOGUM,
    gecerlilik: str = GECERLILIK,
    soyad: str = "OZDEMIR",
    ad: str = "ALI",
) -> str:
    """Kontrol haneleri dogru hesaplanmis sentetik bir TD1 MRZ uretir."""
    l1 = f"I<TUR{belge_no}{kontrol_hanesi(belge_no)}{tc}".ljust(30, "<")
    govde = (
        f"{dogum}{kontrol_hanesi(dogum)}M{gecerlilik}{kontrol_hanesi(gecerlilik)}TUR"
    ).ljust(29, "<")
    bilesik = l1[5:30] + govde[0:7] + govde[8:15] + govde[18:29]
    l2 = govde + str(kontrol_hanesi(bilesik))
    l3 = f"{soyad}<<{ad}".ljust(30, "<")
    return f"{l1}\n{l2}\n{l3}"


class TestKontrolHanesi:
    def test_icao_ornegi(self):
        # ICAO 9303 dokumanindaki referans ornek
        assert kontrol_hanesi("D23145890734") == 9

    def test_dolgu_sifir_sayilir(self):
        assert kontrol_hanesi("<<<<<<") == 0

    def test_harf_degerleri(self):
        assert karakter_degeri("A") == 10
        assert karakter_degeri("Z") == 35
        assert karakter_degeri("<") == 0
        assert karakter_degeri("7") == 7


class TestTemizOkuma:
    def test_tum_alanlar_cozulur(self):
        k = coz(mrz_uret())
        assert k.tc == TC
        assert k.ad == "ALI"
        assert k.soyad == "OZDEMIR"
        assert k.dogum_tarihi == dt.date(1985, 3, 5)
        assert k.gecerlilik_tarihi == dt.date(2030, 1, 1)
        assert k.belge_no == BELGE_NO
        assert k.uyruk == "TUR"
        assert k.cinsiyet == "M"

    def test_temiz_mrz_kesin_guven_verir(self):
        assert coz(mrz_uret()).guven == KESIN

    def test_cok_adli_kisi(self):
        k = coz(mrz_uret(soyad="KARA", ad="ALI<VELI"))
        assert k.soyad == "KARA"
        assert k.ad == "ALI VELI"

    def test_ondokuzuncu_yuzyil_dogumu_gelecege_kaymaz(self):
        k = coz(mrz_uret(dogum="500101"))
        assert k.dogum_tarihi == dt.date(1950, 1, 1)
        assert k.dogum_tarihi < dt.date.today()


class TestOcrHatalari:
    def test_sayisal_alanlarda_harf_karisikligi_duzeltilir(self):
        """OCR 0'i O/Q, 1'i I sanabilir."""
        bozuk = mrz_uret().replace("850305", "85O3O5", 1)
        k = coz(bozuk)
        assert k.dogum_tarihi == dt.date(1985, 3, 5)
        assert k.kontroller["dogum_tarihi"]

    def test_dolgu_karakteri_K_olarak_okunursa_duzeltilir(self):
        """Tesseract OCR-B'deki '<' isaretini en cok 'K' sanir."""
        satirlar = mrz_uret().split("\n")
        satirlar[2] = satirlar[2].replace("<<<<<<", "KKKKKK")
        k = coz("\n".join(satirlar))
        assert k.soyad == "OZDEMIR" and k.ad == "ALI"

    def test_tek_K_isimde_korunur(self):
        """'KAYA' soyadindaki tek K dolgu sanilmamali."""
        assert dolgu_duzelt("KAYA<<ALI") == "KAYA<<ALI"

    def test_ardisik_KK_dolguya_cevrilir(self):
        assert dolgu_duzelt("OZDEMIRKKALI") == "OZDEMIR<<ALI"


class TestGuvenDuzeyleri:
    def test_bilesik_hane_okunamazsa_yuksek_guven(self):
        """Son karakter OCR'in en cok kacirdigi yer; TC algoritmasi devreye girer."""
        satirlar = mrz_uret().split("\n")
        satirlar[1] = satirlar[1][:29] + "<"  # bilesik hane kayip
        k = coz("\n".join(satirlar))
        assert k.guven == YUKSEK
        assert k.guvenilir_mi
        assert k.tc == TC
        assert k.dogum_tarihi == dt.date(1985, 3, 5)

    def test_bozuk_tc_guvenilmez(self):
        """TC'nin bir hanesi yanlis okunursa kendi algoritmasi yakalar."""
        bozuk = mrz_uret().replace(TC, "10000000147", 1)
        k = coz(bozuk)
        assert k.guven == DUSUK
        assert not k.guvenilir_mi

    def test_alakasiz_metin_guvenilmez(self):
        metin = "\n".join(["BU BIR FORM SATIRIDIR VE MRZ DEGILDIR"] * 3)
        sonuc = coz(metin)
        assert sonuc is None or not sonuc.guvenilir_mi

    def test_bos_metin_none_doner(self):
        assert coz("") is None


class TestAdSatiriKorumasi:
    """3. satiri koruyan kontrol hanesi YOKTUR - sekil sinamasi sarttir."""

    def test_rakam_iceren_satir_ad_sayilmaz(self):
        assert not ad_satiri_makul_mu("OZDEMIR<<ALI12<<<<<<<<<<<<<<<<")

    def test_dolgusuz_dolu_satir_ad_sayilmaz(self):
        assert not ad_satiri_makul_mu("A" * 30)

    def test_gecerli_ad_satiri_kabul_edilir(self):
        assert ad_satiri_makul_mu("OZDEMIR<<ALI<<<<<<<<<<<<<<<<<<")

    def test_form_metni_ad_olarak_yazilmaz(self):
        """Dogru okunmus 1-2. satirlar alakasiz bir metinle eslesirse ad bos kalir."""
        satirlar = mrz_uret().split("\n")
        satirlar[2] = "GERCEKKISILERICINMUSTERINITANI"  # sayfadaki form basligi
        k = coz("\n".join(satirlar))
        assert k.tc == TC, "TC yine okunmali"
        assert k.dogum_tarihi == dt.date(1985, 3, 5), "Dogum tarihi yine okunmali"
        assert k.ad == "" and k.soyad == "", "Cop isim forma yazilmamali"

    def test_ad_satiri_hic_yoksa_diger_alanlar_okunur(self):
        """OCR ad satirini tamamen kacirsa bile TC ve dogum tarihi kurtarilir."""
        satirlar = mrz_uret().split("\n")[:2]
        k = coz("\n".join(satirlar))
        assert k is not None
        assert k.tc == TC
        assert k.dogum_tarihi == dt.date(1985, 3, 5)
        assert k.guvenilir_mi


class TestSatirAyiklama:
    def test_bosluklar_atilir(self):
        satirlar = satirlari_temizle("I<TUR A12345678 4 10000000146<<<<")
        assert satirlar and " " not in satirlar[0]

    def test_cok_uzun_satirlar_elenir(self):
        """Form cumleleri MRZ adayi olmamali."""
        uzun = "BU SATIR MRZ OLAMAYACAK KADAR UZUNDUR VE ELENMELIDIR"
        assert satirlari_temizle(uzun) == []

    def test_cok_kisa_satirlar_elenir(self):
        assert satirlari_temizle("KISA") == []


@pytest.mark.parametrize(
    "tc",
    ["10000000146", "11111111110", "12345678950"],
)
def test_farkli_tc_numaralari(tc):
    k = coz(mrz_uret(tc=tc))
    assert k.tc == tc
    assert k.guven == KESIN


class TestGercekTaramaBozulmalari:
    """Gercek bir A4 taramasinda gozlenen bozulmalar.

    OCR, MRZ satirlarinin basina ve sonuna kimlik uzerindeki baska metni
    ekliyor. Satirlar bu haliyle 30 karakterden uzun oluyor ve alanlar
    kayiyor. Veriler sentetiktir; gercek kisiye ait degildir.
    """

    def test_birinci_satirin_basindaki_cop_atilir(self):
        satirlar = mrz_uret().split("\n")
        satirlar[0] = "GC" + satirlar[0]  # kimlik deseninden sizan harfler
        k = coz("\n".join(satirlar))
        assert k.tc == TC
        assert k.kontroller["belge_no"], "Kayma duzeltilmemis"

    def test_ikinci_satirin_basindaki_cop_atilir(self):
        satirlar = mrz_uret().split("\n")
        satirlar[1] = "TTOR" + satirlar[1]
        k = coz("\n".join(satirlar))
        assert k.dogum_tarihi == dt.date(1985, 3, 5)
        assert k.kontroller["dogum_tarihi"]

    def test_ad_satirinin_basindaki_rakamlar_atilir(self):
        """Kimligin tarih alanindan sizan rakamlar ad satirinin basina yapisiyor."""
        satirlar = mrz_uret().split("\n")
        satirlar[2] = "13052029" + satirlar[2]
        k = coz("\n".join(satirlar))
        assert k.soyad == "OZDEMIR" and k.ad == "ALI"

    def test_uc_satir_da_bozukken_okunur(self):
        satirlar = mrz_uret().split("\n")
        satirlar[0] = "GC" + satirlar[0]
        satirlar[1] = "TTOR" + satirlar[1] + "K<6"
        satirlar[2] = "13052029" + satirlar[2]
        k = coz("\n".join(satirlar))
        assert k.tc == TC
        assert k.dogum_tarihi == dt.date(1985, 3, 5)
        assert k.soyad == "OZDEMIR"
        assert k.guvenilir_mi

    def test_uzun_satirlar_artik_elenmez(self):
        """Onceki dar uzunluk siniri gercek MRZ satirlarini eliyordu."""
        uzun = "TTOR" + mrz_uret().split("\n")[1] + "K<6"  # 37 karakter
        assert satirlari_temizle(uzun) == [uzun]

    def test_form_cumlesi_hala_elenir(self):
        """Sinir gevsedi ama sayfa metni yine aday olmamali."""
        cumle = "YUKARIDA BELIRTILEN BILGILERIN DOGRU OLDUGUNU BEYAN EDERIM"
        assert satirlari_temizle(cumle) == []
