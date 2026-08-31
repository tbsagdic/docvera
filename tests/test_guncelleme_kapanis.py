"""Guncelleme sirasinda uygulamanin kapanmasi.

Kurulum betigi calisan .exe'nin klasorunu yer degistiriyor; bu ancak uygulama
kapandiktan sonra yapilabilir. Sahadaki hata tam buradaydi: betik baslar
baslamaz uygulama ONAY BEKLEYEN bir pencere gosteriyordu. Betigin sayaci o
sirada isliyor, kullanici Tamam'a basana kadar uygulama kapanmiyor ve
guncelleme "uygulama kapanmadi" diye yarim kaliyordu.

Iki tarafta da onlem alindi ve ikisi de burada tutuluyor:
  - Uygulama kurulum baslayinca hicbir sey sormadan kapanir.
  - Betik beklemekle yetinmez; once nazikce kapanmasini ister, sonra zorlar.
"""

from __future__ import annotations

import os
import zipfile

import pytest

from app import guncelleme
from app.guncelleme import Yayin


def _yayin() -> Yayin:
    return Yayin(
        surum="1.0.30",
        etiket="v1.0.30",
        notlar="",
        indirme_url="https://example.invalid/paket.zip",
        dosya_adi="Docvera-1.0.30-win64.zip",
        boyut=10,
        sayfa_url="https://example.invalid/yayin",
    )


@pytest.fixture
def betik_icerigi(tmp_path, monkeypatch) -> str:
    """kur() cagirir ve uretilen .bat dosyasinin icerigini dondurur."""
    kurulum = tmp_path / "program" / "Docvera"
    kurulum.mkdir(parents=True)
    (kurulum / "Docvera.exe").write_text("eski")
    veri = tmp_path / "veri"
    veri.mkdir()

    paket_zip = tmp_path / "paket.zip"
    with zipfile.ZipFile(paket_zip, "w") as arsiv:
        arsiv.writestr("Docvera/Docvera.exe", "yeni")

    monkeypatch.setattr(guncelleme, "kurulum_klasoru", lambda: kurulum)
    monkeypatch.setattr(guncelleme, "kurulabilir_mi", lambda: (True, ""))
    monkeypatch.setattr(guncelleme, "veri_klasoru", lambda: veri)
    monkeypatch.setattr(guncelleme.subprocess, "Popen", lambda k, **a: object())

    return guncelleme.kur(paket_zip, _yayin()).read_text(encoding="ascii")


class TestBetik:
    def test_uygulamayi_kendisi_kapatir(self, betik_icerigi):
        """Yalnizca beklemek yetmedi; betik kapanmayi kendisi istemeli."""
        assert f"taskkill /pid {os.getpid()}" in betik_icerigi

    def test_kapanmayan_uygulamayi_zorlar(self, betik_icerigi):
        assert f"taskkill /f /pid {os.getpid()}" in betik_icerigi

    def test_surec_agacini_oldurmez(self, betik_icerigi):
        """/T verilseydi betik kendini oldururdu: o da uygulamanin cocugu."""
        oldurenler = [
            s
            for s in betik_icerigi.splitlines()
            if "taskkill" in s and not s.strip().lower().startswith("rem")
        ]
        assert oldurenler
        for satir in oldurenler:
            assert " /t" not in satir.lower()

    def test_once_nazik_sonra_zorla_denenir(self, betik_icerigi):
        nazik = betik_icerigi.index("taskkill /pid")
        zorla = betik_icerigi.index("taskkill /f /pid")
        assert nazik < zorla

    def test_pes_etmeden_once_zorlama_denenmis_olur(self):
        assert 0 < guncelleme.NAZIK_KAPATMA_TIKI < guncelleme.ZORLA_KAPATMA_TIKI
        assert guncelleme.ZORLA_KAPATMA_TIKI < guncelleme.AZAMI_BEKLEME_TIKI


class TestDiyalog:
    @staticmethod
    def _diyalog(monkeypatch):
        from PySide6.QtWidgets import QApplication, QMessageBox

        import app.ui.guncelleme_dialog as gd
        from app.config import Ayarlar

        QApplication.instance() or QApplication([])

        def patlar(*a, **k):
            raise AssertionError("kurulum baslarken onay bekleyen pencere acilmamali")

        monkeypatch.setattr(QMessageBox, "information", staticmethod(patlar))
        return gd.GuncellemeDiyalogu(_yayin(), Ayarlar())

    def test_kurulum_baslayinca_pencere_sormaz(self, monkeypatch):
        """Onay bekleyen pencere betigin sayacini bosa harciyordu."""
        diyalog = self._diyalog(monkeypatch)
        try:
            diyalog._kurulum_basladi()  # patlar() tetiklenirse test duser
        finally:
            diyalog.deleteLater()

    def test_kapatilmali_isareti_verilir(self, monkeypatch):
        diyalog = self._diyalog(monkeypatch)
        kapandi: list[bool] = []
        diyalog.kapatilmali.connect(lambda: kapandi.append(True))
        try:
            diyalog._kurulum_basladi()
            assert kapandi == [True]
        finally:
            diyalog.deleteLater()

    def test_durum_metni_kullaniciya_yazilir(self, monkeypatch):
        """Pencere kalkti; kullanici ne oldugunu diyalogdan okuyabilmeli."""
        diyalog = self._diyalog(monkeypatch)
        try:
            diyalog._kurulum_basladi()
            assert "kapanacak" in diyalog.durum.text()
        finally:
            diyalog.deleteLater()
