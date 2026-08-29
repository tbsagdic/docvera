"""Klasor/dosya adi uretimi testleri - mevcut arsiv duzeniyle uyum kritik."""

import datetime as dt

import pytest

from app.storage.paths import (
    AD_UZUNLUK_SINIRI,
    ad_temizle,
    goreli_parcalar,
    kayit_klasoru,
    mevcut_sayfa_numaralari,
    musteri_klasor_adi,
    pdf_dosya_adi,
    sayfa_dosya_adi,
    sonraki_sayfa_numarasi,
    tarih_parcalari,
)

TARIH = dt.date(2026, 1, 2)
TC = "10000000146"


class TestTarihBicimi:
    """Musterinin elle olusturdugu arsiv duzeni: 2026\\01.2026\\02.01.26"""

    def test_arsiv_bicimiyle_ayni(self):
        assert tarih_parcalari(TARIH) == ("2026", "01.2026", "02.01.26")

    def test_tek_haneli_gun_ve_ay_sifirlanir(self):
        assert tarih_parcalari(dt.date(2026, 9, 7)) == ("2026", "09.2026", "07.09.26")

    def test_yuzyil_donumu(self):
        assert tarih_parcalari(dt.date(2100, 12, 31))[2] == "31.12.00"


class TestMusteriKlasoru:
    def test_ad_buyuk_harf_ve_son_dort_hane(self):
        assert musteri_klasor_adi("ali", "özdemir", TC) == "ALİ ÖZDEMİR 0146"

    def test_ayni_isim_farkli_tc_ayrisir(self):
        birinci = musteri_klasor_adi("ali", "özdemir", "10000000146")
        ikinci = musteri_klasor_adi("ali", "özdemir", "11111111110")
        assert birinci != ikinci

    def test_ayni_tc_ayni_klasore_gider(self):
        # Ayni musteri ayni gun tekrar gelirse ayni klasor kullanilmali
        assert musteri_klasor_adi("ali", "özdemir", TC) == musteri_klasor_adi(
            "ALİ", "ÖZDEMİR", TC
        )


class TestAdTemizleme:
    @pytest.mark.parametrize("karakter", list('<>:"/\\|?*'))
    def test_windows_yasak_karakterleri_atilir(self, karakter):
        assert karakter not in ad_temizle(f"AY{karakter}SE")

    def test_rezerve_adlar_kacirilir(self):
        assert ad_temizle("CON") == "_CON"
        assert ad_temizle("com1") == "_com1"

    def test_sondaki_nokta_ve_bosluk_kirpilir(self):
        assert ad_temizle("AYSE. ") == "AYSE"

    def test_uzun_ad_kirpilir(self):
        assert len(ad_temizle("A" * 200)) <= AD_UZUNLUK_SINIRI

    def test_bos_ad_yedek_deger_alir(self):
        assert ad_temizle("   ") == "ISIMSIZ"
        assert ad_temizle("///") == "ISIMSIZ"

    def test_turkce_karakterler_korunur(self):
        assert ad_temizle("ÇĞİÖŞÜ") == "ÇĞİÖŞÜ"


class TestYolUretimi:
    def test_subesiz_yapi_mevcut_arsivle_ayni(self):
        assert goreli_parcalar("ali", "özdemir", TC, TARIH) == [
            "2026", "01.2026", "02.01.26", "ALİ ÖZDEMİR 0146",
        ]

    def test_sube_en_uste_eklenir(self):
        parcalar = goreli_parcalar("ali", "özdemir", TC, TARIH, sube="MERKEZ")
        assert parcalar[0] == "MERKEZ"
        assert len(parcalar) == 5

    def test_bos_sube_seviye_eklemez(self):
        assert len(goreli_parcalar("ali", "özdemir", TC, TARIH, sube="  ")) == 4

    def test_tam_yol_kokten_baslar(self, tmp_path):
        yol = kayit_klasoru(tmp_path, "ali", "özdemir", TC, TARIH)
        assert yol == tmp_path / "2026" / "01.2026" / "02.01.26" / "ALİ ÖZDEMİR 0146"

    def test_pdf_adi_tam_tarih_icerir(self):
        assert pdf_dosya_adi("ali", "özdemir", TARIH) == "ALİ ÖZDEMİR_02.01.2026.pdf"


class TestSayfaNumaralandirma:
    def test_bos_klasor_birden_baslar(self, tmp_path):
        assert sonraki_sayfa_numarasi(tmp_path) == 1

    def test_olmayan_klasor_birden_baslar(self, tmp_path):
        assert sonraki_sayfa_numarasi(tmp_path / "yok") == 1

    def test_mevcut_sayfalardan_devam_eder(self, tmp_path):
        for ad in ("01.jpg", "02.jpg", "03.jpg"):
            (tmp_path / ad).write_bytes(b"x")
        assert mevcut_sayfa_numaralari(tmp_path) == [1, 2, 3]
        assert sonraki_sayfa_numarasi(tmp_path) == 4

    def test_ilgisiz_dosyalar_sayilmaz(self, tmp_path):
        (tmp_path / "01.jpg").write_bytes(b"x")
        (tmp_path / "meta.json").write_text("{}")
        (tmp_path / "ALİ ÖZDEMİR_02.01.2026.pdf").write_bytes(b"x")
        assert mevcut_sayfa_numaralari(tmp_path) == [1]

    def test_sayfa_adi_iki_haneli(self):
        assert sayfa_dosya_adi(1) == "01.jpg"
        assert sayfa_dosya_adi(12) == "12.jpg"
        assert sayfa_dosya_adi(123) == "123.jpg"
