"""Veritabani arama testleri ve sema yukseltmesi.

Kasiyer aceleyle 'ozdemir' yazar, kayit 'ÖZDEMİR'dir. Arama bu iki yazimi
esitlemezse musteri "yok" gorunur ve ayni kisiye ikinci bir kayit acilir -
sistemin onlemeye calistigi seyin ta kendisi.
"""

import datetime as dt
import sqlite3

import pytest

from app.db import SEMA_SURUMU, Veritabani

TC = "10000000146"
TC2 = "20000000148"


@pytest.fixture
def vt(tmp_path):
    veritabani = Veritabani(tmp_path / "test.db")
    yield veritabani
    veritabani.kapat()


def _kayit(vt, tc, ad, soyad, gun=dt.date(2026, 1, 2)):
    musteri_id = vt.musteri_kaydet(tc, ad, soyad)
    vt.kayit_ac(musteri_id, gun, r"C:\arsiv", "2026/01.2026/02.01.26", "", None)


class TestArama:
    @pytest.mark.parametrize(
        "yazilan", ["ozdemir", "ÖZDEMİR", "özdem", "OZDEM", "ali", "ALİ"]
    )
    def test_turkce_harf_yazilmadan_bulunur(self, vt, yazilan):
        _kayit(vt, TC, "ALİ", "ÖZDEMİR")
        assert len(vt.ara(yazilan)) == 1

    @pytest.mark.parametrize("yazilan", ["yilmaz", "YILMAZ", "yılmaz", "yil"])
    def test_noktasiz_i_iki_yonlu(self, vt, yazilan):
        _kayit(vt, TC2, "AYŞE", "YILMAZ")
        assert len(vt.ara(yazilan)) == 1

    def test_tc_ile_bulunur(self, vt):
        _kayit(vt, TC, "ALİ", "ÖZDEMİR")
        assert len(vt.ara("0000014")) == 1

    def test_baskasi_gelmez(self, vt):
        _kayit(vt, TC, "ALİ", "ÖZDEMİR")
        _kayit(vt, TC2, "AYŞE", "YILMAZ")
        sonuc = vt.ara("ozdemir")
        assert [s["tc"] for s in sonuc] == [TC]

    def test_eslesmeyen_metin(self, vt):
        _kayit(vt, TC, "ALİ", "ÖZDEMİR")
        assert vt.ara("veli") == []

    def test_ad_degisirse_arama_sutunu_guncellenir(self, vt):
        vt.musteri_kaydet(TC, "ALI", "OZDEMIR")
        vt.musteri_kaydet(TC, "ALİ", "ŞAHİN")  # evlilik/duzeltme
        _kayit(vt, TC, "ALİ", "ŞAHİN")
        assert len(vt.ara("sahin")) == 1
        assert vt.ara("ozdemir") == []


class TestSemaYukseltme:
    """v1 veritabanindaki 'arama' sutunu katlanmamis bicimdeydi."""

    def _eski_veritabani(self, yol):
        vt = Veritabani(yol)
        vt.musteri_kaydet(TC, "ALİ", "ÖZDEMİR")
        musteri_id = vt.musteri_bul(TC)["id"]
        vt.kayit_ac(
            musteri_id, dt.date(2026, 1, 2), r"C:\arsiv", "2026/01.2026", "", None
        )
        # v1 bicimini taklit et: yalnizca Turkce kucuk harf, katlama yok
        with vt.baglanti:
            vt.baglanti.execute("UPDATE musteriler SET arama = 'ali özdemir'")
            vt.baglanti.execute("UPDATE sema_bilgi SET surum = 1")
        vt.kapat()

    def test_eski_kayitlar_yeniden_hesaplanir(self, tmp_path):
        yol = tmp_path / "eski.db"
        self._eski_veritabani(yol)

        vt = Veritabani(yol)  # acilista yukseltme calisir
        try:
            assert len(vt.ara("ozdemir")) == 1
            assert len(vt.ara("özdemir")) == 1
        finally:
            vt.kapat()

    def test_surum_guncellenir(self, tmp_path):
        yol = tmp_path / "eski.db"
        self._eski_veritabani(yol)

        vt = Veritabani(yol)
        try:
            surum = vt.baglanti.execute("SELECT surum FROM sema_bilgi").fetchone()
            assert int(surum["surum"]) == SEMA_SURUMU
        finally:
            vt.kapat()

    def test_yukseltme_veriyi_bozmaz(self, tmp_path):
        yol = tmp_path / "eski.db"
        self._eski_veritabani(yol)

        vt = Veritabani(yol)
        try:
            musteri = vt.musteri_bul(TC)
            assert (musteri["ad"], musteri["soyad"]) == ("ALİ", "ÖZDEMİR")
            assert len(vt.musteri_gecmisi(TC)) == 1
        finally:
            vt.kapat()

    def test_guncel_veritabani_dokunulmaz(self, tmp_path):
        yol = tmp_path / "yeni.db"
        vt = Veritabani(yol)
        vt.musteri_kaydet(TC, "ALİ", "ÖZDEMİR")
        vt.kapat()

        vt = Veritabani(yol)
        try:
            arama = vt.baglanti.execute(
                "SELECT arama FROM musteriler WHERE tc = ?", (TC,)
            ).fetchone()
            assert arama["arama"] == "ali ozdemir"
        finally:
            vt.kapat()

    def test_bos_veritabani_yukseltilebilir(self, tmp_path):
        yol = tmp_path / "bos.db"
        baglanti = sqlite3.connect(str(yol))
        baglanti.executescript(
            "CREATE TABLE sema_bilgi (surum INTEGER NOT NULL);"
            "INSERT INTO sema_bilgi (surum) VALUES (1);"
        )
        baglanti.commit()
        baglanti.close()

        vt = Veritabani(yol)  # musteriler tablosu bos: yukseltme sorunsuz gecmeli
        try:
            assert vt.ara("ozdemir") == []
        finally:
            vt.kapat()
