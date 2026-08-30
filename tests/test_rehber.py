"""Arsiv kokundeki musteri rehberi (musteriler.json) testleri.

Rehberin isi ayni musteriyi tek girdi altinda toplamak: ayni kisi ikinci kez
geldiginde yeni musteri acilmamali, gelisi kayitlar listesine eklenmelidir.
"""

import datetime as dt
import json

from app.storage import rehber

TC = "10000000146"
TC2 = "20000000148"


def _yaz(kok, tc=TC, ad="ALİ", soyad="ÖZDEMİR", gun=dt.date(2026, 1, 2), **ek):
    varsayilan = {
        "dogum_tarihi": None,
        "goreli_yol": f"2026/01.2026/{gun:%d.%m.%y}/{ad} {soyad} 0146",
        "sube_kodu": "",
        "pdf_adi": None,
        "sayfa_sayisi": 1,
    }
    varsayilan.update(ek)
    return rehber.musteri_yaz(kok, tc, ad, soyad, tarih=gun, **varsayilan)


class TestOkuYaz:
    def test_dosya_yoksa_bos_rehber(self, tmp_path):
        assert rehber.rehber_oku(tmp_path)["musteriler"] == {}

    def test_bozuk_dosya_uygulamayi_durdurmaz(self, tmp_path):
        rehber.rehber_yolu(tmp_path).write_text("{bozuk", encoding="utf-8")
        assert rehber.rehber_oku(tmp_path)["musteriler"] == {}

    def test_beklenmeyen_bicim_bos_doner(self, tmp_path):
        rehber.rehber_yolu(tmp_path).write_text("[1, 2]", encoding="utf-8")
        assert rehber.rehber_oku(tmp_path)["musteriler"] == {}

    def test_kok_klasor_yoksa_olusturulur(self, tmp_path):
        kok = tmp_path / "yeni" / "arsiv"
        _yaz(kok)
        assert rehber.rehber_yolu(kok).is_file()

    def test_dosya_arsiv_kokune_yazilir(self, tmp_path):
        yol = _yaz(tmp_path)
        assert yol == tmp_path / "musteriler.json"
        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert veri["surum"] == rehber.REHBER_SURUMU
        assert veri["musteriler"][TC]["ad"] == "ALİ"


class TestMusteriTekrari:
    """Ayni musteri kac kez gelirse gelsin rehberde tek girdi olur."""

    def test_ayni_musteri_ikinci_gunde_tek_girdi(self, tmp_path):
        _yaz(tmp_path, gun=dt.date(2026, 1, 2))
        _yaz(tmp_path, gun=dt.date(2026, 8, 30))

        musteriler = rehber.musteriler(tmp_path)
        assert len(musteriler) == 1
        assert len(musteriler[0]["kayitlar"]) == 2

    def test_ayni_gun_tekrar_gelis_yeni_satir_acmaz(self, tmp_path):
        _yaz(tmp_path, gun=dt.date(2026, 1, 2), sayfa_sayisi=1)
        _yaz(tmp_path, gun=dt.date(2026, 1, 2), sayfa_sayisi=4)

        kayitlar = rehber.musteri_getir(tmp_path, TC)["kayitlar"]
        assert len(kayitlar) == 1
        assert kayitlar[0]["sayfa_sayisi"] == 4

    def test_ilk_ve_son_kayit_hesaplanir(self, tmp_path):
        _yaz(tmp_path, gun=dt.date(2026, 8, 30))
        _yaz(tmp_path, gun=dt.date(2026, 1, 2))

        musteri = rehber.musteri_getir(tmp_path, TC)
        assert musteri["ilk_kayit"] == "2026-01-02"
        assert musteri["son_kayit"] == "2026-08-30"

    def test_farkli_subeler_ayni_gun_ayri_kayit(self, tmp_path):
        _yaz(tmp_path, sube_kodu="")
        _yaz(tmp_path, sube_kodu="MERKEZ")
        assert len(rehber.musteri_getir(tmp_path, TC)["kayitlar"]) == 2

    def test_baska_musteri_silinmez(self, tmp_path):
        _yaz(tmp_path, tc=TC)
        _yaz(tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ")
        assert set(rehber.rehber_oku(tmp_path)["musteriler"]) == {TC, TC2}

    def test_dogum_tarihi_bos_gelirse_eskisi_korunur(self, tmp_path):
        _yaz(tmp_path, dogum_tarihi=dt.date(1985, 3, 5))
        _yaz(tmp_path, dogum_tarihi=None)
        assert rehber.musteri_getir(tmp_path, TC)["dogum_tarihi"] == "1985-03-05"

    def test_ad_guncellenir(self, tmp_path):
        _yaz(tmp_path, ad="ALI")
        _yaz(tmp_path, ad="ALİ")
        assert rehber.musteri_getir(tmp_path, TC)["ad"] == "ALİ"


class TestArama:
    def test_turkce_kucuk_harf_duyarsiz(self, tmp_path):
        _yaz(tmp_path, ad="ALİ", soyad="ÖZDEMİR")
        assert rehber.ara(rehber.musteriler(tmp_path), "özdem")

    def test_tc_parcasiyla_bulunur(self, tmp_path):
        _yaz(tmp_path)
        assert rehber.ara(rehber.musteriler(tmp_path), "0146")

    def test_eslesmeyen_metin_bos_doner(self, tmp_path):
        _yaz(tmp_path)
        assert rehber.ara(rehber.musteriler(tmp_path), "veli") == []

    def test_bos_metin_hepsini_doner(self, tmp_path):
        _yaz(tmp_path, tc=TC)
        _yaz(tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ")
        assert len(rehber.ara(rehber.musteriler(tmp_path), "  ")) == 2

    def test_en_son_gelen_ustte(self, tmp_path):
        _yaz(tmp_path, tc=TC, gun=dt.date(2026, 1, 2))
        _yaz(tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ", gun=dt.date(2026, 8, 30))
        assert rehber.musteriler(tmp_path)[0]["tc"] == TC2


class TestYenidenUretme:
    """Rehber silinse bile meta.json dosyalarindan geri kazanilir."""

    def _meta_yaz(self, kok, goreli, **alanlar):
        klasor = kok / goreli
        klasor.mkdir(parents=True, exist_ok=True)
        veri = {
            "tc": TC,
            "ad": "ALİ",
            "soyad": "ÖZDEMİR",
            "tarih": "2026-01-02",
            "sube_kodu": "",
            "pdf": None,
            "sayfa_sayisi": 2,
        }
        veri.update(alanlar)
        (klasor / "meta.json").write_text(
            json.dumps(veri, ensure_ascii=False), encoding="utf-8"
        )

    def test_meta_dosyalarindan_uretilir(self, tmp_path):
        self._meta_yaz(tmp_path, "2026/01.2026/02.01.26/ALİ ÖZDEMİR 0146")
        self._meta_yaz(
            tmp_path,
            "2026/08.2026/30.08.26/ALİ ÖZDEMİR 0146",
            tarih="2026-08-30",
        )

        assert rehber.rehberi_yeniden_uret(tmp_path) == 1
        musteri = rehber.musteri_getir(tmp_path, TC)
        assert len(musteri["kayitlar"]) == 2
        assert musteri["kayitlar"][0]["klasor"].startswith("2026/01.2026")

    def test_bozuk_meta_atlanir(self, tmp_path):
        self._meta_yaz(tmp_path, "2026/01.2026/02.01.26/ALİ ÖZDEMİR 0146")
        bozuk = tmp_path / "2026/01.2026/02.01.26/BOZUK 0000"
        bozuk.mkdir(parents=True)
        (bozuk / "meta.json").write_text("{yarim", encoding="utf-8")

        assert rehber.rehberi_yeniden_uret(tmp_path) == 1

    def test_tc_siz_meta_atlanir(self, tmp_path):
        self._meta_yaz(tmp_path, "2026/01.2026/02.01.26/ISIMSIZ", tc="")
        assert rehber.rehberi_yeniden_uret(tmp_path) == 0

    def test_eski_rehberin_uzerine_yazar(self, tmp_path):
        _yaz(tmp_path, tc=TC2, ad="AYŞE", soyad="YILMAZ")
        self._meta_yaz(tmp_path, "2026/01.2026/02.01.26/ALİ ÖZDEMİR 0146")

        rehber.rehberi_yeniden_uret(tmp_path)
        assert set(rehber.rehber_oku(tmp_path)["musteriler"]) == {TC}
