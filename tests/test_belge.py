"""MRZ'siz belgelerden (surucu belgesi vb.) TC cikarimi testleri.

Gercek kisiye ait veri kullanilmaz; TC algoritmasindan gecen sahte numaralar
kullanilir.
"""

import datetime as dt

import pytest

from app.ocr.belge import (
    ad_soyad_sec,
    dogum_tarihi_adaylari,
    dogum_tarihi_sec,
    tc_adaylari,
    tc_sec,
)

TC = "10000000146"
TC2 = "11111111110"


def surucu_belgesi(tc: str = TC, ikinci_gecis: bool = True) -> str:
    """Surucu belgesi + doviz belgesi bulunan bir sayfanin OCR ciktisi."""
    satirlar = [
        "SURUCU BELGESİ / DRIVING LICENCE SATIM BELGESİ BİLGİLERİ",
        "1. ÖZDEMİR DSB2025000031802",
        "2. Ali 01/05/2025 19:04",
        "3. 05.03.1985 Nazilli",
        "4a. 10.07.2023",
        "4b. 10.07.2033",
        f"4d. {tc}",
        "5. 38825",
    ]
    if ikinci_gecis:
        satirlar.append(f"Passport no : {tc}")
    return "\n".join(satirlar)


class TestTcBulma:
    def test_surucu_belgesinden_tc_okunur(self):
        secilen = tc_sec(surucu_belgesi())
        assert secilen is not None
        assert secilen.tc == TC

    def test_4d_etiketi_taninir(self):
        adaylar = tc_adaylari(f"4d. {TC}")
        assert adaylar and adaylar[0].etiketli

    def test_tc_kimlik_no_etiketi_taninir(self):
        adaylar = tc_adaylari(f"TC Kimlik No: {TC}")
        assert adaylar and adaylar[0].etiketli

    def test_bosluklu_numara_okunur(self):
        """OCR rakamlarin arasina bosluk koyabilir."""
        bosluklu = f"4d. {TC[:3]} {TC[3:6]} {TC[6:9]} {TC[9:]}"
        secilen = tc_sec(bosluklu)
        assert secilen is not None and secilen.tc == TC

    def test_harf_karisikligi_duzeltilir(self):
        """OCR 0'i O, 1'i I okuyabilir."""
        bozuk = "4d. " + TC.replace("0", "O").replace("1", "I")
        secilen = tc_sec(bozuk)
        assert secilen is not None and secilen.tc == TC


class TestKanitGucu:
    """Rastgele 11 haneli bir sayinin TC algoritmasindan gecme olasiligi 1/100."""

    def test_etiketsiz_tek_gecis_kabul_edilmez(self):
        secilen = tc_sec(f"Sayfada gecen numara {TC} baska ipucu yok")
        assert secilen is None, "Tek kanitla otomatik doldurma yapilmamali"

    def test_iki_ayri_gecis_kabul_edilir(self):
        metin = f"Musteri no {TC} islem tutari 100 TL\nIkinci sayfa {TC} onay"
        secilen = tc_sec(metin)
        assert secilen is not None and secilen.tekrar >= 2

    def test_ayni_gecis_iki_kez_sayilmaz(self):
        """Uc farkli desen ayni numarayi bulur; bu tek gecistir."""
        adaylar = tc_adaylari(f"numara {TC} son")
        assert adaylar[0].tekrar == 1, "Ayni gecis tekrar sayilmis"

    def test_iki_farkli_aday_varsa_secim_yapilmaz(self):
        secilen = tc_sec(f"Musteri {TC} kefil {TC2}")
        assert secilen is None, "Belirsizlikte otomatik doldurma yapilmamali"

    def test_etiketli_aday_etiketsizi_yener(self):
        secilen = tc_sec(f"Rastgele {TC2} bilgi\n4d. {TC}")
        assert secilen is not None and secilen.tc == TC

    def test_gecersiz_numaralar_aday_olmaz(self):
        assert tc_adaylari("Tutar 46980000000 TL fatura 12345678901") == []


class TestDogumTarihi:
    def test_verilis_ve_gecerlilik_tarihleri_elenir(self):
        """Belgede baska tarihler de var; yalnizca makul yas verenler aday."""
        adaylar = dogum_tarihi_adaylari(surucu_belgesi())
        assert adaylar == [dt.date(1985, 3, 5)]

    def test_tek_aday_secilir(self):
        assert dogum_tarihi_sec(surucu_belgesi()) == dt.date(1985, 3, 5)

    def test_birden_fazla_makul_tarihte_secim_yapilmaz(self):
        metin = "Dogum 05.03.1985 ... esi 12.11.1990"
        assert dogum_tarihi_sec(metin) is None

    def test_gelecek_tarih_aday_olmaz(self):
        assert dogum_tarihi_adaylari("Gecerlilik 10.07.2033") == []

    def test_cok_yeni_tarih_aday_olmaz(self):
        yakin = dt.date.today().replace(year=dt.date.today().year - 2)
        assert dogum_tarihi_adaylari(yakin.strftime("%d.%m.%Y")) == []


class TestAdSoyad:
    def test_numarali_alanlardan_okunur(self):
        ad, soyad = ad_soyad_sec("1. ÖZDEMİR\n2. Ali\n")
        assert (ad, soyad) == ("Ali", "ÖZDEMİR")

    def test_birlesmis_sutun_kesilir(self):
        """Tesseract iki sutunu tek satirda birlestirir; rakamda durulmali."""
        ad, soyad = ad_soyad_sec("1. ÖZDEMİR DSB2025000031802\n2. Ali 01/05/2025 19:04\n")
        assert (ad, soyad) == ("Ali", "ÖZDEMİR")

    def test_iki_kelimeli_isim_korunur(self):
        ad, soyad = ad_soyad_sec("1. KARA ÖZTÜRK\n2. Ali Veli\n")
        assert (ad, soyad) == ("Ali Veli", "KARA ÖZTÜRK")

    def test_alan_yoksa_bos_doner(self):
        assert ad_soyad_sec("Burada numarali alan yok") == ("", "")


@pytest.mark.parametrize("etiket", ["4d.", "TC Kimlik No:", "TCKN", "Kimlik No"])
def test_farkli_etiketler_taninir(etiket):
    adaylar = tc_adaylari(f"{etiket} {TC}")
    assert adaylar and adaylar[0].etiketli, etiket
