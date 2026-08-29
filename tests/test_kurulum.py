"""Eksik bilesen tespiti ve otomatik kurulum.

Testler agi hic kullanmaz: indirme her yerde taklit edilir. Amac, kurulumun
DOGRU seyi dogru sirayla ve guvenli adresten istedigini dogrulamak.
"""

from __future__ import annotations

import pytest

from app.kurulum import tesseract
from app.kurulum.denetim import TESSERACT, TURKCE_DIL, denetle, eksikler
from app.ocr import engine


def _tesseract_yok(ayar_yolu: str = "") -> str:
    raise engine.OcrYok("Tesseract OCR bulunamadı.")


class TestGereksinimDenetimi:
    def test_tesseract_yoksa_ikisi_de_eksik(self, monkeypatch):
        monkeypatch.setattr(engine, "tesseract_bul", _tesseract_yok)
        monkeypatch.setattr(engine, "diller", lambda ayar_yolu="": ["tur"])

        eksik = {g.anahtar for g in eksikler()}
        assert eksik == {TESSERACT, TURKCE_DIL}

    def test_motor_yokken_dil_listesi_sorulmaz(self, monkeypatch):
        """Tesseract yokken --list-langs cagrisi bos yere calistirilmamali."""
        monkeypatch.setattr(engine, "tesseract_bul", _tesseract_yok)

        def patlar(ayar_yolu: str = ""):
            raise AssertionError("motor yokken diller() cagrilmamali")

        monkeypatch.setattr(engine, "diller", patlar)
        assert len(denetle()) == 2

    def test_tesseract_var_turkce_yok(self, monkeypatch):
        monkeypatch.setattr(engine, "tesseract_bul", lambda ayar_yolu="": "C:/t.exe")
        monkeypatch.setattr(engine, "diller", lambda ayar_yolu="": ["eng", "osd"])

        eksik = [g.anahtar for g in eksikler()]
        assert eksik == [TURKCE_DIL]

    def test_hepsi_kuruluysa_eksik_yok(self, monkeypatch):
        monkeypatch.setattr(engine, "tesseract_bul", lambda ayar_yolu="": "C:/t.exe")
        monkeypatch.setattr(engine, "diller", lambda ayar_yolu="": ["eng", "tur"])

        assert eksikler() == []
        assert all(g.tamam for g in denetle())

    def test_her_gereksinim_kullaniciya_gerekce_verir(self, monkeypatch):
        """Kasiyer 'neden kuruyorum' sorusunun yanitini penceresinde gormeli."""
        monkeypatch.setattr(engine, "tesseract_bul", _tesseract_yok)
        monkeypatch.setattr(engine, "diller", lambda ayar_yolu="": [])

        for gereksinim in denetle():
            assert gereksinim.neden.strip()
            assert gereksinim.ad.strip()


class TestAdresGuvenligi:
    """Indirilen dosya calistirilacagi icin adres denetimi guvenlik meselesi."""

    def test_https_disi_reddedilir(self):
        with pytest.raises(tesseract.KurulumHatasi):
            tesseract._dogrula_adres("http://digi.bib.uni-mannheim.de/x.exe")

    def test_taninmayan_sunucu_reddedilir(self):
        with pytest.raises(tesseract.KurulumHatasi):
            tesseract._dogrula_adres("https://ornek-saldirgan.test/tesseract.exe")

    def test_dosya_semasi_reddedilir(self):
        with pytest.raises(tesseract.KurulumHatasi):
            tesseract._dogrula_adres("file:///C:/kotu.exe")

    def test_gomulu_adresler_beyaz_listeden_gecer(self):
        tesseract._dogrula_adres(tesseract.YEDEK_KURULUM_ADRESI)
        tesseract._dogrula_adres(tesseract.DIL_ADRESI.format(dil="tur"))


class TestDilPaketiKurulumu:
    def test_eksik_diller_indirilir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)
        istenen: list[str] = []

        def sahte_indir(adres, hedef, bildir, etiket):
            istenen.append(adres)
            hedef.write_bytes(b"veri")

        monkeypatch.setattr(tesseract, "_indir", sahte_indir)
        tesseract.dil_paketi_kur(["tur", "eng"], lambda m, y: None)

        assert [a.rsplit("/", 1)[-1] for a in istenen] == [
            "tur.traineddata",
            "eng.traineddata",
        ]
        assert (tmp_path / "tur.traineddata").is_file()

    def test_var_olan_dil_yeniden_indirilmez(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)
        (tmp_path / "tur.traineddata").write_bytes(b"zaten var")

        def patlar(*args, **kwargs):
            raise AssertionError("var olan dil yeniden indirilmemeli")

        monkeypatch.setattr(tesseract, "_indir", patlar)
        tesseract.dil_paketi_kur(["tur"], lambda m, y: None)

    def test_turkce_istenince_ingilizce_de_gelir(self, monkeypatch, tmp_path):
        """MRZ 'eng' ile okunur; --tessdata-dir verilince o klasorde de olmali."""
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)
        indirilen: list[str] = []
        monkeypatch.setattr(tesseract, "tesseract_kur", lambda bildir: "C:/t.exe")
        monkeypatch.setattr(
            tesseract,
            "dil_paketi_kur",
            lambda diller, bildir: indirilen.extend(diller),
        )

        tesseract.kur([TURKCE_DIL], lambda m, y: None)
        assert indirilen == [TURKCE_DIL, "eng"]

    def test_motor_dilden_once_kurulur(self, monkeypatch):
        sira: list[str] = []
        monkeypatch.setattr(
            tesseract, "tesseract_kur", lambda bildir: sira.append("motor")
        )
        monkeypatch.setattr(
            tesseract, "dil_paketi_kur", lambda diller, bildir: sira.append("dil")
        )

        tesseract.kur([TURKCE_DIL, TESSERACT], lambda m, y: None)
        assert sira == ["motor", "dil"]


class TestTessdataYonlendirmesi:
    def test_indirilen_dil_icin_klasor_gosterilir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)
        (tmp_path / "tur.traineddata").write_bytes(b"veri")

        assert engine._tessdata_argumani("tur") == ["--tessdata-dir", str(tmp_path)]

    def test_indirilmemis_dilde_arguman_eklenmez(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)

        assert engine._tessdata_argumani("tur") == []

    def test_indirilen_diller_listeye_katilir(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.config.dil_klasoru", lambda: tmp_path)
        (tmp_path / "tur.traineddata").write_bytes(b"veri")

        assert engine._indirilen_diller() == {"tur"}
