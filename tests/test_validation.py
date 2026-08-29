"""TC dogrulama ve Turkce metin normalizasyonu testleri."""

import datetime as dt

import pytest

from app.validation import (
    ad_normalize,
    dogum_tarihi_ayristir,
    tc_gecerli_mi,
    tc_hata_mesaji,
    tc_normalize,
    tc_son4,
    tr_lower,
    tr_upper,
)

# Algoritmaya uyan gecerli ornekler (gercek kisilere ait degil)
GECERLI_TC = ["10000000146", "11111111110", "12345678950"]


@pytest.mark.parametrize("tc", GECERLI_TC)
def test_gecerli_tc_kabul_edilir(tc):
    assert tc_gecerli_mi(tc)
    assert tc_hata_mesaji(tc) is None


@pytest.mark.parametrize(
    "tc, sebep",
    [
        ("", "bos"),
        ("123", "kisa"),
        ("123456789012", "uzun"),
        ("01234567890", "sifirla baslar"),
        ("12345678901", "saglama tutmaz"),
        ("abcdefghijk", "rakam degil"),
    ],
)
def test_gecersiz_tc_reddedilir(tc, sebep):
    assert not tc_gecerli_mi(tc), sebep
    assert tc_hata_mesaji(tc) is not None


def test_bicimli_tc_temizlenir():
    assert tc_normalize("100 000 001-46") == "10000000146"
    assert tc_gecerli_mi("100 000 001-46")


def test_son_dort_hane():
    assert tc_son4("10000000146") == "0146"


class TestTurkceHarfler:
    """Python'un .upper()/.lower() metodlari Turkce'de yanlis sonuc verir."""

    def test_i_harfi_buyutulur(self):
        assert tr_upper("istanbul") == "İSTANBUL"
        assert tr_upper("ismail ilhan") == "İSMAİL İLHAN"

    def test_noktasiz_i_buyutulur(self):
        assert tr_upper("ışık") == "IŞIK"

    def test_buyuk_i_kucultulur(self):
        assert tr_lower("ISPARTA") == "ısparta"
        assert tr_lower("İSTANBUL") == "istanbul"

    def test_ad_normalize_fazla_bosluk_atar(self):
        assert ad_normalize("  ali   özdemir  ") == "ALİ ÖZDEMİR"

    def test_arama_icin_kucuk_harf_eslesir(self):
        # Kasiyerin yazdigi 'özdem', kayitli 'ÖZDEMİR' ile eslesmeli
        assert tr_lower("ÖZDEMİR").startswith(tr_lower("Özdem"))


class TestDogumTarihi:
    def test_bos_deger_none_doner(self):
        assert dogum_tarihi_ayristir("") is None
        assert dogum_tarihi_ayristir("   ") is None

    @pytest.mark.parametrize(
        "metin", ["05.03.1985", "05/03/1985", "05-03-1985", "1985-03-05"]
    )
    def test_farkli_bicimler_kabul_edilir(self, metin):
        assert dogum_tarihi_ayristir(metin) == dt.date(1985, 3, 5)

    def test_gelecek_tarih_reddedilir(self):
        gelecek = dt.date.today() + dt.timedelta(days=1)
        with pytest.raises(ValueError, match="gelecekte"):
            dogum_tarihi_ayristir(gelecek.strftime("%d.%m.%Y"))

    def test_anlamsiz_metin_reddedilir(self):
        with pytest.raises(ValueError, match="GG.AA.YYYY"):
            dogum_tarihi_ayristir("dun")

    def test_cok_eski_tarih_reddedilir(self):
        with pytest.raises(ValueError, match="1900"):
            dogum_tarihi_ayristir("05.03.1850")
