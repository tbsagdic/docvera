"""Musteri ozeti/gecmisi testleri: veritabani ile arsiv rehberinin birlesimi.

Kritik davranis: bir musteri yalnizca rehberde ya da yalnizca veritabaninda
kayitli olsa bile listede tek satir olarak gorunur; iki kaynakta da varsa
kayitlari birlestirilir, ikiye katlanmaz.
"""

import datetime as dt

import pytest

from app.db import Veritabani
from app.musteri import musteri_kayitlari, musteri_ozetleri, ozet_ara
from app.storage import rehber

TC = "10000000146"
TC2 = "20000000148"
KLASOR = "2026/01.2026/02.01.26/ALİ ÖZDEMİR 0146"
KLASOR2 = "2026/08.2026/30.08.26/ALİ ÖZDEMİR 0146"


@pytest.fixture
def vt(tmp_path):
    veritabani = Veritabani(tmp_path / "test.db")
    yield veritabani
    veritabani.kapat()


def _vt_kaydi(vt, kok, tc=TC, ad="ALİ", soyad="ÖZDEMİR", gun=dt.date(2026, 1, 2),
              goreli=KLASOR, sayfa=2):
    musteri_id = vt.musteri_kaydet(tc, ad, soyad, "1985-03-05")
    kayit_id = vt.kayit_ac(musteri_id, gun, str(kok / goreli), goreli, "", None)
    for sira in range(1, sayfa + 1):
        vt.sayfa_ekle(kayit_id, sira, f"{sira:02d}.jpg", 100, "x")
    return kayit_id


def _rehber_kaydi(kok, tc=TC, ad="ALİ", soyad="ÖZDEMİR", gun=dt.date(2026, 1, 2),
                  goreli=KLASOR, sayfa=2):
    rehber.musteri_yaz(
        kok, tc, ad, soyad, None, gun, goreli, sube_kodu="", sayfa_sayisi=sayfa
    )


class TestOzetler:
    def test_yalniz_rehberdeki_musteri_gorunur(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        ozetler = musteri_ozetleri(tmp_path, vt)
        assert [o.tc for o in ozetler] == [TC]
        assert ozetler[0].tam_ad == "ALİ ÖZDEMİR"

    def test_yalniz_veritabanindaki_musteri_gorunur(self, tmp_path, vt):
        _vt_kaydi(vt, tmp_path)
        ozetler = musteri_ozetleri(tmp_path, vt)
        assert [o.tc for o in ozetler] == [TC]

    def test_iki_kaynaktaki_musteri_tek_satir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        _vt_kaydi(vt, tmp_path)
        assert len(musteri_ozetleri(tmp_path, vt)) == 1

    def test_kayit_sayisi_genis_olandan_alinir(self, tmp_path, vt):
        # Rehberde iki gelis var (biri baska bilgisayarda alinmis), yerelde bir
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 1, 2))
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 8, 30), goreli=KLASOR2)
        _vt_kaydi(vt, tmp_path, gun=dt.date(2026, 1, 2))

        ozet = musteri_ozetleri(tmp_path, vt)[0]
        assert ozet.kayit_sayisi == 2
        assert ozet.ilk_kayit == "2026-01-02"
        assert ozet.son_kayit == "2026-08-30"

    def test_dogum_tarihi_veritabanindan_tamamlanir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)  # rehberde dogum tarihi yok
        _vt_kaydi(vt, tmp_path)
        assert musteri_ozetleri(tmp_path, vt)[0].dogum_tarihi == "1985-03-05"

    def test_en_son_gelen_ustte(self, tmp_path, vt):
        _rehber_kaydi(tmp_path, tc=TC, gun=dt.date(2026, 1, 2))
        _rehber_kaydi(
            tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ", gun=dt.date(2026, 8, 30)
        )
        assert musteri_ozetleri(tmp_path, vt)[0].tc == TC2

    def test_veritabanisiz_calisir(self, tmp_path):
        _rehber_kaydi(tmp_path)
        assert len(musteri_ozetleri(tmp_path, None)) == 1


class TestArama:
    def test_turkce_harfe_duyarsiz(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        assert ozet_ara(musteri_ozetleri(tmp_path, vt), "özdem")

    def test_tc_parcasi(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        assert ozet_ara(musteri_ozetleri(tmp_path, vt), "0146")

    def test_bos_metin_hepsi(self, tmp_path, vt):
        _rehber_kaydi(tmp_path, tc=TC)
        _rehber_kaydi(tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ")
        assert len(ozet_ara(musteri_ozetleri(tmp_path, vt), "")) == 2


class TestKayitlar:
    def test_eskiden_yeniye_siralanir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 8, 30), goreli=KLASOR2)
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 1, 2))

        kayitlar = musteri_kayitlari(tmp_path, TC, vt)
        assert [k.tarih for k in kayitlar] == [
            dt.date(2026, 1, 2),
            dt.date(2026, 8, 30),
        ]

    def test_ilk_kayit_isaretlenir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 1, 2))
        _rehber_kaydi(tmp_path, gun=dt.date(2026, 8, 30), goreli=KLASOR2)

        kayitlar = musteri_kayitlari(tmp_path, TC, vt)
        assert [k.ilk_mi for k in kayitlar] == [True, False]

    def test_ayni_gun_iki_kaynaktan_tek_kayit(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        _vt_kaydi(vt, tmp_path)
        assert len(musteri_kayitlari(tmp_path, TC, vt)) == 1

    def test_rehberdeki_goreli_yol_koke_baglanir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        kayit = musteri_kayitlari(tmp_path, TC, None)[0]
        assert kayit.klasor == tmp_path / KLASOR

    def test_veritabanindaki_mutlak_yol_tercih_edilir(self, tmp_path, vt):
        _rehber_kaydi(tmp_path)
        _vt_kaydi(vt, tmp_path)
        kayit = musteri_kayitlari(tmp_path, TC, vt)[0]
        assert kayit.klasor == tmp_path / KLASOR
        assert kayit.sayfa_sayisi == 2

    def test_kaydi_olmayan_musteri_bos_liste(self, tmp_path, vt):
        assert musteri_kayitlari(tmp_path, TC, vt) == []
