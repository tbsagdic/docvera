"""Dosyadan sayfa ice aktarma testleri (PDF ve goruntu)."""

import img2pdf
import pytest
from PIL import Image

from app.storage.aktarim import (
    AZAMI_SAYFA,
    AktarimHatasi,
    desteklenir_mi,
    dosya_filtresi,
    dosyadan_sayfalar,
    sayfa_sayisi,
)


@pytest.fixture
def goruntu(tmp_path):
    def uret(ad="belge.jpg", boyut=(800, 1100), bicim=None):
        yol = tmp_path / ad
        Image.new("RGB", boyut, "white").save(yol, format=bicim)
        return yol

    return uret


@pytest.fixture
def pdf(tmp_path, goruntu):
    def uret(sayfa=3, ad="belge.pdf"):
        kaynaklar = [str(goruntu(f"s{i}.jpg")) for i in range(sayfa)]
        yol = tmp_path / ad
        yol.write_bytes(img2pdf.convert(kaynaklar))
        return yol

    return uret


class TestDosyaTuru:
    @pytest.mark.parametrize("ad", ["a.pdf", "a.PDF", "a.jpg", "a.jpeg", "a.png",
                                    "a.tif", "a.tiff", "a.bmp", "a.webp"])
    def test_desteklenen_turler(self, ad):
        assert desteklenir_mi(ad)

    @pytest.mark.parametrize("ad", ["a.docx", "a.xlsx", "a.txt", "a.zip", "a"])
    def test_desteklenmeyen_turler(self, ad):
        assert not desteklenir_mi(ad)

    def test_filtre_metni_pdf_ve_goruntu_icerir(self):
        filtre = dosya_filtresi()
        assert "*.pdf" in filtre and "*.jpg" in filtre


class TestSayfaSayisi:
    def test_pdf_sayfa_sayisi(self, pdf):
        assert sayfa_sayisi(pdf(sayfa=4)) == 4

    def test_goruntu_tek_sayfa(self, goruntu):
        assert sayfa_sayisi(goruntu()) == 1

    def test_bozuk_pdf_hata_verir(self, tmp_path):
        bozuk = tmp_path / "bozuk.pdf"
        bozuk.write_bytes(b"bu bir pdf degil")
        with pytest.raises(AktarimHatasi, match="PDF"):
            sayfa_sayisi(bozuk)


class TestGoruntuAktarimi:
    def test_goruntu_tek_sayfa_uretir(self, goruntu, tmp_path):
        sayfalar = dosyadan_sayfalar(goruntu(), tmp_path / "cikti")
        assert len(sayfalar) == 1
        assert sayfalar[0].is_file()

    def test_hedef_klasor_olusturulur(self, goruntu, tmp_path):
        hedef = tmp_path / "a" / "b"
        dosyadan_sayfalar(goruntu(), hedef)
        assert hedef.is_dir()

    def test_png_de_kabul_edilir(self, goruntu, tmp_path):
        sayfalar = dosyadan_sayfalar(goruntu("a.png", bicim="PNG"), tmp_path / "c")
        assert len(sayfalar) == 1

    def test_kaynak_dosya_degistirilmez(self, goruntu, tmp_path):
        kaynak = goruntu()
        onceki = kaynak.read_bytes()
        dosyadan_sayfalar(kaynak, tmp_path / "cikti")
        assert kaynak.read_bytes() == onceki


class TestPdfAktarimi:
    def test_her_sayfa_ayri_goruntu_olur(self, pdf, tmp_path):
        sayfalar = dosyadan_sayfalar(pdf(sayfa=3), tmp_path / "cikti", dpi=100)
        assert len(sayfalar) == 3
        assert all(yol.is_file() for yol in sayfalar)

    def test_sayfa_sirasi_korunur(self, pdf, tmp_path):
        sayfalar = dosyadan_sayfalar(pdf(sayfa=4), tmp_path / "cikti", dpi=72)
        assert sayfalar == sorted(sayfalar, key=lambda y: y.name)

    def test_azami_sayfa_siniri_uygulanir(self, pdf, tmp_path):
        sayfalar = dosyadan_sayfalar(
            pdf(sayfa=6), tmp_path / "cikti", dpi=72, azami_sayfa=2
        )
        assert len(sayfalar) == 2

    def test_dpi_cozunurlugu_etkiler(self, pdf, tmp_path):
        dusuk = dosyadan_sayfalar(pdf(sayfa=1, ad="a.pdf"), tmp_path / "d", dpi=72)
        yuksek = dosyadan_sayfalar(pdf(sayfa=1, ad="b.pdf"), tmp_path / "y", dpi=200)
        with Image.open(dusuk[0]) as kucuk, Image.open(yuksek[0]) as buyuk:
            assert buyuk.width > kucuk.width


class TestHatalar:
    def test_olmayan_dosya(self, tmp_path):
        with pytest.raises(AktarimHatasi, match="bulunamadı"):
            dosyadan_sayfalar(tmp_path / "yok.pdf", tmp_path / "cikti")

    def test_desteklenmeyen_tur(self, tmp_path):
        belge = tmp_path / "a.docx"
        belge.write_bytes(b"icerik")
        with pytest.raises(AktarimHatasi, match="Desteklenmeyen"):
            dosyadan_sayfalar(belge, tmp_path / "cikti")

    def test_bozuk_goruntu(self, tmp_path):
        bozuk = tmp_path / "bozuk.jpg"
        bozuk.write_bytes(b"bu bir jpeg degil")
        with pytest.raises(AktarimHatasi, match="açılamadı"):
            dosyadan_sayfalar(bozuk, tmp_path / "cikti")

    def test_bozuk_pdf(self, tmp_path):
        bozuk = tmp_path / "bozuk.pdf"
        bozuk.write_bytes(b"%PDF-1.4 ama gerisi bozuk")
        with pytest.raises(AktarimHatasi):
            dosyadan_sayfalar(bozuk, tmp_path / "cikti")


def test_azami_sayfa_makul():
    """Yanlislikla secilen kalin bir PDF uygulamayi kilitlememelidir."""
    assert 10 <= AZAMI_SAYFA <= 200
