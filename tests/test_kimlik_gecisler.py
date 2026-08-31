"""MRZ'siz belge okumasi: cok gecisli OCR.

Gercek bir surucu belgesi taramasi tek gecisle okunamiyordu. Iki ayri kusur
vardi ve testler ikisini de tutuyor:

  1. OCR'a RENKLI goruntu veriliyordu. Ayni taramanin gri hali TC'yi dogru
     okurken renkli hali hic bulamadi.
  2. Tek psm deneniyordu. Ayni sayfada psm 6 numarayi, psm 11 ise ad satirini
     temiz cikarabiliyor; alanlarin gecisler arasinda toplanmasi gerekiyor.

Testler Tesseract'i hic calistirmaz; OCR ciktisi taklit edilir.
"""

from __future__ import annotations

import datetime as _dt

import pytest
from PIL import Image

from app.ocr import engine, kimlik

TC = "10000000146"

# psm 6: numarayi ve tarihi cikarir, ad satirini gurultuye bogar
PSM6_METNI = f"""7 1. ÖZDEMİR j Ae le | Fi
3. 05.03.1985 Nazilli
4d.{TC}
"""

# psm 11: numarayi kacirir ama ad ve soyad satirlari temizdir
PSM11_METNI = """1. ÖZDEMİR
2. Ali
"""

# Uzerinde TC olmayan bir sayfa
BOS_METIN = "SATIM BELGESI\nTutar 469.800,00 TL\n"


@pytest.fixture
def sayfa() -> Image.Image:
    """Tarama gibi RENKLI bir goruntu."""
    return Image.new("RGB", (400, 600), "white")


class TestVaryantlar:
    def test_hepsi_gri_tonlamadir(self, sayfa):
        """Asil kusur buydu: renkli goruntude TC hic bulunamiyordu."""
        modlar = {g.mode for _e, g, _p in kimlik._metin_varyantlari(sayfa)}
        assert modlar == {"L"}

    def test_dagilmis_metin_gecisi_var(self, sayfa):
        psmler = [p for _e, _g, p in kimlik._metin_varyantlari(sayfa)]
        assert 6 in psmler and 11 in psmler

    def test_cozunurluk_dusurulmez(self, sayfa):
        """4d alanindaki numara kucultulmus goruntude kayboluyor."""
        for etiket, goruntu, _psm in kimlik._metin_varyantlari(sayfa):
            if etiket.startswith("donmus"):
                continue  # dondurmede en/boy yer degistirir
            assert goruntu.size == sayfa.size


class TestGecisBirlesimi:
    @staticmethod
    def _oku(monkeypatch, sayfa, metinler: dict[int, str]) -> tuple:
        """psm'e gore metin dondurur; cagrilan psm'leri de kaydeder."""
        cagrilar: list[int] = []

        def sahte(goruntu, ayar_yolu="", psm=6):
            cagrilar.append(psm)
            return metinler.get(psm, "")

        monkeypatch.setattr(engine, "turkce_oku", sahte)
        return kimlik._metinden_oku(sayfa, "", 0), cagrilar

    def test_alanlar_gecisler_arasinda_toplanir(self, monkeypatch, sayfa):
        sonuc, _ = self._oku(monkeypatch, sayfa, {6: PSM6_METNI, 11: PSM11_METNI})

        assert sonuc is not None and sonuc.dogrulandi
        assert sonuc.kimlik.tc == TC
        assert sonuc.kimlik.ad == "Ali"
        assert sonuc.kimlik.soyad == "ÖZDEMİR"
        assert sonuc.kimlik.dogum_tarihi == _dt.date(1985, 3, 5)

    def test_ad_soyad_tamamlaninca_durulur(self, monkeypatch, sayfa):
        """Gereksiz OCR gecisi kasiyeri bekletir; ilk tam sonucta durulmali."""
        sonuc, cagrilar = self._oku(
            monkeypatch, sayfa, {6: PSM6_METNI, 11: PSM11_METNI}
        )

        assert sonuc is not None
        toplam = len(list(kimlik._metin_varyantlari(sayfa)))
        assert len(cagrilar) == 2 < toplam

    def test_tc_yoksa_tum_varyantlar_denenir(self, monkeypatch, sayfa):
        sonuc, cagrilar = self._oku(monkeypatch, sayfa, {6: BOS_METIN, 11: BOS_METIN})

        assert sonuc is None
        assert len(cagrilar) == len(list(kimlik._metin_varyantlari(sayfa)))

    def test_bos_cikti_gecisi_harcamaz(self, monkeypatch, sayfa):
        """Tesseract bos donerse sonraki varyant denenmeli."""
        sonuc, _ = self._oku(monkeypatch, sayfa, {6: "", 11: PSM6_METNI + PSM11_METNI})

        assert sonuc is not None and sonuc.kimlik.tc == TC

    def test_ocr_patlarsa_sonraki_varyanta_gecilir(self, monkeypatch, sayfa):
        cagri = {"sayi": 0}

        def sahte(goruntu, ayar_yolu="", psm=6):
            cagri["sayi"] += 1
            if cagri["sayi"] == 1:
                raise RuntimeError("tesseract coktu")
            return PSM6_METNI + PSM11_METNI

        monkeypatch.setattr(engine, "turkce_oku", sahte)
        sonuc = kimlik._metinden_oku(sayfa, "", 0)

        assert sonuc is not None and sonuc.kimlik.tc == TC

    def test_renkli_goruntu_ocr_a_gitmez(self, monkeypatch, sayfa):
        modlar: list[str] = []

        def sahte(goruntu, ayar_yolu="", psm=6):
            modlar.append(goruntu.mode)
            return BOS_METIN

        monkeypatch.setattr(engine, "turkce_oku", sahte)
        kimlik._metinden_oku(sayfa, "", 0)

        assert modlar and set(modlar) == {"L"}


class TestSonucRaporu:
    def test_orta_guvenle_raporlanir(self, monkeypatch, sayfa):
        """MRZ kontrol hanesi yok; sonuc kesin diye sunulmamali."""
        monkeypatch.setattr(
            engine, "turkce_oku", lambda g, a="", psm=6: PSM6_METNI + PSM11_METNI
        )
        sonuc = kimlik._metinden_oku(sayfa, "", 0)

        assert sonuc.guven == "orta"
        assert sonuc.ad_onay_gerekli is True
        assert "kontrol edin" in sonuc.mesaj

    def test_deneme_sayisi_gercek_gecisi_yansitir(self, monkeypatch, sayfa):
        monkeypatch.setattr(
            engine, "turkce_oku", lambda g, a="", psm=6: PSM6_METNI + PSM11_METNI
        )
        sonuc = kimlik._metinden_oku(sayfa, "", 7)  # MRZ dongusu 7 gecis yapmisti

        assert sonuc.deneme_sayisi == 8
