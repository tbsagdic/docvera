"""Arsive yazma testleri: JPG normalizasyonu, PDF birlestirme, meta.json."""

import datetime as dt
import json
import re

import pytest
from PIL import Image

from app.storage.writer import META_DOSYASI, meta_yaz, pdf_uret, sayfa_yaz, sayfalari_yaz

TARIH = dt.date(2026, 1, 2)


@pytest.fixture
def bmp_sayfa(tmp_path):
    """Tarayici surucusunun JPEG yerine BMP dondurdugu durumu taklit eder."""

    def uret(ad="tarama.bmp", boyut=(600, 800)):
        yol = tmp_path / ad
        Image.new("RGB", boyut, "white").save(yol, format="BMP")
        return yol

    return uret


class TestSayfaYazma:
    def test_bmp_girdi_jpeg_olarak_kaydedilir(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "musteri"
        sonuc = sayfa_yaz(bmp_sayfa(), hedef, sira=1)

        assert sonuc.yol.name == "01.jpg"
        with Image.open(sonuc.yol) as goruntu:
            assert goruntu.format == "JPEG"

    def test_dpi_bilgisi_gomulur(self, tmp_path, bmp_sayfa):
        sonuc = sayfa_yaz(bmp_sayfa(), tmp_path / "m", sira=1, dpi=300)
        with Image.open(sonuc.yol) as goruntu:
            assert goruntu.info.get("dpi") == (300, 300)

    def test_doksan_derece_donme_boyutu_cevirir(self, tmp_path, bmp_sayfa):
        sonuc = sayfa_yaz(bmp_sayfa(boyut=(600, 800)), tmp_path / "m", sira=1, donme=90)
        with Image.open(sonuc.yol) as goruntu:
            assert goruntu.size == (800, 600), "90 derece donmede kenarlar degismeli"

    def test_yuz_seksen_derece_boyutu_korur(self, tmp_path, bmp_sayfa):
        sonuc = sayfa_yaz(bmp_sayfa(boyut=(600, 800)), tmp_path / "m", sira=1, donme=180)
        with Image.open(sonuc.yol) as goruntu:
            assert goruntu.size == (600, 800)

    def test_sha256_hesaplanir(self, tmp_path, bmp_sayfa):
        sonuc = sayfa_yaz(bmp_sayfa(), tmp_path / "m", sira=1)
        assert len(sonuc.sha256) == 64
        assert sonuc.bayt > 0

    def test_hedef_klasor_yoksa_olusturulur(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "a" / "b" / "c"
        sayfa_yaz(bmp_sayfa(), hedef, sira=1)
        assert hedef.is_dir()


class TestCokluSayfa:
    def test_sayfalar_sirayla_numaralanir(self, tmp_path, bmp_sayfa):
        kaynaklar = [bmp_sayfa(f"s{i}.bmp") for i in range(3)]
        sonuc = sayfalari_yaz(kaynaklar, tmp_path / "m")
        assert [s.dosya_adi for s in sonuc] == ["01.jpg", "02.jpg", "03.jpg"]

    def test_ikinci_ziyaret_mevcut_sayfalarin_ustune_yazmaz(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "m"
        sayfalari_yaz([bmp_sayfa("a.bmp"), bmp_sayfa("b.bmp")], hedef)
        ikinci = sayfalari_yaz([bmp_sayfa("c.bmp")], hedef)

        assert [s.dosya_adi for s in ikinci] == ["03.jpg"]
        assert sorted(p.name for p in hedef.glob("*.jpg")) == ["01.jpg", "02.jpg", "03.jpg"]

    def test_her_sayfaya_ayri_donme_uygulanir(self, tmp_path, bmp_sayfa):
        kaynaklar = [bmp_sayfa("a.bmp", (600, 800)), bmp_sayfa("b.bmp", (600, 800))]
        sonuc = sayfalari_yaz(kaynaklar, tmp_path / "m", donmeler=[0, 90])

        with Image.open(sonuc[0].yol) as birinci, Image.open(sonuc[1].yol) as ikinci:
            assert birinci.size == (600, 800)
            assert ikinci.size == (800, 600)


class TestPdfBirlestirme:
    def _sayfa_sayisi(self, pdf_yolu):
        return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_yolu.read_bytes()))

    def test_tum_sayfalar_tek_pdfte_birlesir(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "m"
        sayfalari_yaz([bmp_sayfa(f"s{i}.bmp") for i in range(3)], hedef)

        pdf = pdf_uret(hedef, "TEST.pdf")

        assert pdf is not None and pdf.is_file()
        assert self._sayfa_sayisi(pdf) == 3

    def test_jpeg_yeniden_sikistirilmaz(self, tmp_path, bmp_sayfa):
        """img2pdf JPEG akisini oldugu gibi gomer - kalite kaybi olmamali."""
        hedef = tmp_path / "m"
        sayfalari_yaz([bmp_sayfa("a.bmp")], hedef)
        pdf = pdf_uret(hedef, "TEST.pdf")
        assert pdf.read_bytes().count(b"DCTDecode") == 1

    def test_sayfa_yoksa_pdf_uretilmez(self, tmp_path):
        assert pdf_uret(tmp_path, "TEST.pdf") is None

    def test_sayfa_eklenince_pdf_guncellenir(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "m"
        sayfalari_yaz([bmp_sayfa("a.bmp")], hedef)
        pdf_uret(hedef, "TEST.pdf")

        sayfalari_yaz([bmp_sayfa("b.bmp")], hedef)
        pdf = pdf_uret(hedef, "TEST.pdf")

        assert self._sayfa_sayisi(pdf) == 2

    def test_yarim_pdf_birakilmaz(self, tmp_path, bmp_sayfa):
        hedef = tmp_path / "m"
        sayfalari_yaz([bmp_sayfa("a.bmp")], hedef)
        pdf_uret(hedef, "TEST.pdf")
        assert not list(hedef.glob("*.tmp")), "Gecici dosya temizlenmemis"


class TestMetaJson:
    def _meta_yaz(self, klasor, sayfalar):
        return meta_yaz(
            klasor, "ALİ", "ÖZDEMİR", "10000000146", dt.date(1985, 3, 5), TARIH,
            sayfalar, "ALİ ÖZDEMİR_02.01.2026.pdf", "MRK", "HP MFP 4103", "kasiyer",
        )

    def test_musteri_bilgileri_yazilir(self, tmp_path, bmp_sayfa):
        sayfalar = sayfalari_yaz([bmp_sayfa("a.bmp")], tmp_path)
        yol = self._meta_yaz(tmp_path, sayfalar)

        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert veri["ad"] == "ALİ" and veri["soyad"] == "ÖZDEMİR"
        assert veri["tc"] == "10000000146"
        assert veri["dogum_tarihi"] == "1985-03-05"
        assert veri["sube_kodu"] == "MRK"
        assert veri["sayfa_sayisi"] == 1

    def test_ikinci_ziyaret_sayfalari_birlestirir(self, tmp_path, bmp_sayfa):
        ilk = sayfalari_yaz([bmp_sayfa("a.bmp"), bmp_sayfa("b.bmp")], tmp_path)
        self._meta_yaz(tmp_path, ilk)

        ikinci = sayfalari_yaz([bmp_sayfa("c.bmp")], tmp_path)
        yol = self._meta_yaz(tmp_path, ikinci)

        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert veri["sayfa_sayisi"] == 3, "Onceki sayfa bilgisi kaybolmus"
        assert [s["dosya"] for s in veri["sayfalar"]] == ["01.jpg", "02.jpg", "03.jpg"]

    def test_bozuk_meta_dosyasi_kaydi_engellemez(self, tmp_path, bmp_sayfa):
        (tmp_path / META_DOSYASI).write_text("{bozuk json", encoding="utf-8")
        sayfalar = sayfalari_yaz([bmp_sayfa("a.bmp")], tmp_path)

        yol = self._meta_yaz(tmp_path, sayfalar)

        veri = json.loads(yol.read_text(encoding="utf-8"))
        assert veri["sayfa_sayisi"] == 1

    def test_olusturma_zamani_korunur(self, tmp_path, bmp_sayfa):
        sayfalar = sayfalari_yaz([bmp_sayfa("a.bmp")], tmp_path)
        ilk = json.loads(self._meta_yaz(tmp_path, sayfalar).read_text(encoding="utf-8"))

        sayfalar2 = sayfalari_yaz([bmp_sayfa("b.bmp")], tmp_path)
        ikinci = json.loads(self._meta_yaz(tmp_path, sayfalar2).read_text(encoding="utf-8"))

        assert ikinci["olusturma"] == ilk["olusturma"]
