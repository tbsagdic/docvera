"""Drive masaustu uygulamasiyla esitleme yolu.

Kullanicilarin cogu Google Cloud kurulumunda takiliyor; arsivi Drive'in
esitledigi klasore yazmak ayni sonucu kurulum olmadan veriyor. Burada klasor
bulma ve ayarlar penceresinin bu yolu dogru kurmasi kapsaniyor.
"""

from pathlib import Path

from app.drive import yerel_esitleme


class TestKlasorBulma:
    """Drive masaustu uygulamasinin esitledigi klasoru bulma."""

    def test_ingilizce_ad_bulunur(self, tmp_path):
        (tmp_path / "My Drive").mkdir()
        assert yerel_esitleme.drive_klasorleri_bul([tmp_path]) == [
            tmp_path / "My Drive"
        ]

    def test_turkce_ad_bulunur(self, tmp_path):
        """Uygulama arayuz diline gore klasoru Turkce adlandiriyor."""
        (tmp_path / "Drive'ım").mkdir()
        assert yerel_esitleme.drive_klasorleri_bul([tmp_path]) == [
            tmp_path / "Drive'ım"
        ]

    def test_eski_istemcinin_klasoru_bulunur(self, tmp_path):
        """Eski istemci ara klasor olmadan 'Google Drive'a esitliyordu."""
        eski = tmp_path / "Google Drive"
        eski.mkdir()
        assert yerel_esitleme.drive_klasorleri_bul([eski]) == [eski]

    def test_ara_klasor_varsa_ust_klasor_donmez(self, tmp_path):
        """Yeni istemcide arsiv 'Google Drive' degil 'My Drive' altina gider."""
        ust = tmp_path / "Google Drive"
        (ust / "My Drive").mkdir(parents=True)
        assert yerel_esitleme.drive_klasorleri_bul([ust]) == [ust / "My Drive"]

    def test_birden_cok_taban_taranir(self, tmp_path):
        (tmp_path / "ev" / "My Drive").mkdir(parents=True)
        (tmp_path / "g" / "Drive'ım").mkdir(parents=True)
        bulunan = yerel_esitleme.drive_klasorleri_bul(
            [tmp_path / "ev", tmp_path / "g"]
        )
        assert bulunan == [
            tmp_path / "ev" / "My Drive",
            tmp_path / "g" / "Drive'ım",
        ]

    def test_kurulu_degilse_bos_doner(self, tmp_path):
        assert yerel_esitleme.drive_klasorleri_bul([tmp_path]) == []


class TestEsitlenenKlasor:
    """Arsivin esitlenen klasorde olup olmadigi."""

    def test_alt_klasor_esitlenen_sayilir(self, tmp_path):
        kok = tmp_path / "My Drive"
        kok.mkdir()
        arsiv = kok / "DOCVERA ARSIV" / "2026"
        assert yerel_esitleme.esitlenen_klasor(arsiv, [kok]) == kok

    def test_disaridaki_yol_sayilmaz(self, tmp_path):
        kok = tmp_path / "My Drive"
        kok.mkdir()
        assert yerel_esitleme.esitlenen_klasor(tmp_path / "baska", [kok]) is None

    def test_bos_yol_sayilmaz(self, tmp_path):
        assert yerel_esitleme.esitlenen_klasor("  ", [tmp_path]) is None

    def test_arsiv_hedefi_alt_klasore_gider(self, tmp_path):
        """Kullanicinin kendi dosyalarinin arasina yazilmamali."""
        hedef = yerel_esitleme.arsiv_hedefi(tmp_path)
        assert hedef.parent == tmp_path
        assert hedef.name == yerel_esitleme.VARSAYILAN_ARSIV_ADI


class TestAyarlarAkisi:
    """Ayarlar penceresi esitlemeyi kurar ve cift yuklemeyi engeller."""

    @staticmethod
    def _diyalog(tmp_path, monkeypatch, kok_klasor: str, drive_etkin: bool = False):
        from PySide6.QtWidgets import QApplication

        import app.drive.auth as auth
        import app.ui.settings_dialog as sd
        from app.config import Ayarlar
        from app.db import Veritabani
        from app.ui.settings_dialog import AyarlarDiyalogu

        QApplication.instance() or QApplication([])

        monkeypatch.setattr(auth, "gomulu_istemci_yolu", lambda: tmp_path / "yok.json")
        veri = tmp_path / "appdata"
        veri.mkdir(exist_ok=True)
        monkeypatch.setattr(sd, "veri_klasoru", lambda: veri)

        vt = Veritabani(tmp_path / "t.db")
        ayarlar = Ayarlar(kok_klasor=kok_klasor, drive_etkin=drive_etkin)
        return AyarlarDiyalogu(ayarlar, vt), vt

    @staticmethod
    def _drive_klasoru(tmp_path, monkeypatch) -> Path:
        """Sahte bir Drive klasoru kurar ve taramayi ona yonlendirir."""
        klasor = tmp_path / "G" / "My Drive"
        klasor.mkdir(parents=True)
        monkeypatch.setattr(
            yerel_esitleme, "drive_klasorleri_bul", lambda tabanlar=None: [klasor]
        )
        return klasor

    def test_esitlenen_klasorde_durum_yesil(self, tmp_path, monkeypatch):
        klasor = self._drive_klasoru(tmp_path, monkeypatch)
        diyalog, vt = self._diyalog(
            tmp_path, monkeypatch, str(klasor / "DOCVERA ARSIV")
        )
        try:
            assert "Drive klasörüne yazılıyor" in diyalog.esitleme_durumu.text()
        finally:
            vt.kapat()

    def test_iki_yol_birden_acikken_uyarilir(self, tmp_path, monkeypatch):
        """Ayni dosya hem esitlenir hem API ile yuklenirse iki kopya olusur."""
        klasor = self._drive_klasoru(tmp_path, monkeypatch)
        diyalog, vt = self._diyalog(
            tmp_path, monkeypatch, str(klasor / "DOCVERA ARSIV"), drive_etkin=True
        )
        try:
            assert "iki kez" in diyalog.esitleme_durumu.text()
        finally:
            vt.kapat()

    def test_disarida_kalan_arsiv_icin_uyari_yok(self, tmp_path, monkeypatch):
        self._drive_klasoru(tmp_path, monkeypatch)
        diyalog, vt = self._diyalog(tmp_path, monkeypatch, str(tmp_path / "arsiv"))
        try:
            assert "eşitlenen bir klasörde değil" in diyalog.esitleme_durumu.text()
        finally:
            vt.kapat()

    def test_kurma_kok_klasoru_tasir_ve_yuklemeyi_kapatir(self, tmp_path, monkeypatch):
        import app.ui.settings_dialog as sd

        klasor = self._drive_klasoru(tmp_path, monkeypatch)
        diyalog, vt = self._diyalog(
            tmp_path, monkeypatch, str(tmp_path / "arsiv"), drive_etkin=True
        )
        try:
            monkeypatch.setattr(
                sd.QMessageBox, "information", lambda *a, **k: None
            )
            diyalog._esitlemeyi_kur()

            assert Path(diyalog.kok_alani.text()) == klasor / "DOCVERA ARSIV"
            assert not diyalog.drive_kutusu.isChecked()
            assert "Drive klasörüne yazılıyor" in diyalog.esitleme_durumu.text()
        finally:
            vt.kapat()
