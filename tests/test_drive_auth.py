"""OAuth istemci dosyasi dogrulama ve kurulum testleri.

Gercek bir Google istemcisi kullanilmaz; dosya bicimini taklit eden sahte
iceriklerle calisilir.
"""

import json

import pytest

from app.drive import auth

MASAUSTU = {
    "installed": {
        "client_id": "1234567890-abcdefg.apps.googleusercontent.com",
        "client_secret": "GOCSPX-sahte",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


@pytest.fixture
def dosya(tmp_path):
    def yaz(icerik, ad="c.json"):
        yol = tmp_path / ad
        yol.write_text(
            icerik if isinstance(icerik, str) else json.dumps(icerik),
            encoding="utf-8",
        )
        return yol

    return yaz


class TestDogrulama:
    def test_masaustu_istemcisi_kabul_edilir(self, dosya):
        kimlik = auth.istemci_dosyasini_dogrula(dosya(MASAUSTU))
        assert kimlik == MASAUSTU["installed"]["client_id"]

    def test_web_istemcisi_reddedilir(self, dosya):
        """Google Cloud'da en sik yapilan hata: 'Web uygulamasi' secmek."""
        yol = dosya({"web": {"client_id": "x", "client_secret": "y"}})
        with pytest.raises(auth.KimlikHatasi) as hata:
            auth.istemci_dosyasini_dogrula(yol)
        assert "Masaüstü" in str(hata.value), "Hata mesaji cozumu soylemiyor"

    def test_bozuk_json_reddedilir(self, dosya):
        with pytest.raises(auth.KimlikHatasi, match="JSON"):
            auth.istemci_dosyasini_dogrula(dosya("{bozuk"))

    def test_alakasiz_json_reddedilir(self, dosya):
        with pytest.raises(auth.KimlikHatasi, match="OAuth"):
            auth.istemci_dosyasini_dogrula(dosya({"foo": "bar"}))

    def test_liste_iceren_dosya_reddedilir(self, dosya):
        with pytest.raises(auth.KimlikHatasi):
            auth.istemci_dosyasini_dogrula(dosya([1, 2, 3]))

    def test_eksik_alan_reddedilir(self, dosya):
        yol = dosya({"installed": {"client_id": "x"}})
        with pytest.raises(auth.KimlikHatasi, match="client_secret"):
            auth.istemci_dosyasini_dogrula(yol)

    def test_olmayan_dosya_reddedilir(self, tmp_path):
        with pytest.raises(auth.KimlikHatasi, match="okunamadı"):
            auth.istemci_dosyasini_dogrula(tmp_path / "yok.json")


class TestKurulum:
    def test_dosya_veri_klasorune_kopyalanir(self, dosya, tmp_path):
        veri = tmp_path / "appdata"
        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)
        assert (veri / auth.ISTEMCI_DOSYASI).is_file()
        assert auth.kullanici_istemcisi_var_mi(veri)

    def test_klasor_yoksa_olusturulur(self, dosya, tmp_path):
        veri = tmp_path / "a" / "b" / "c"
        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)
        assert veri.is_dir()

    def test_kurulunca_kullanici_dosyasi_oncelik_alir(self, dosya, tmp_path):
        veri = tmp_path / "appdata"
        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)
        assert auth.istemci_yolu(veri) == veri / auth.ISTEMCI_DOSYASI

    def test_gecersiz_dosya_kurulmaz(self, dosya, tmp_path):
        veri = tmp_path / "appdata"
        with pytest.raises(auth.KimlikHatasi):
            auth.istemci_dosyasini_kur(dosya({"web": {}}), veri)
        assert not auth.kullanici_istemcisi_var_mi(veri)

    def test_proje_degisince_eski_jeton_silinir(self, dosya, tmp_path):
        """Baska bir Google projesine ait jeton gecersizdir."""
        veri = tmp_path / "appdata"
        veri.mkdir()
        auth.jeton_yolu(veri).write_bytes(b"eski jeton")

        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)

        assert not auth.jeton_yolu(veri).is_file()


class TestKaldirma:
    def test_kaldirinca_gomuluye_donulur(self, dosya, tmp_path):
        veri = tmp_path / "appdata"
        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)
        auth.kullanici_istemcisini_sil(veri)

        assert not auth.kullanici_istemcisi_var_mi(veri)
        assert auth.istemci_yolu(veri) == auth.gomulu_istemci_yolu()

    def test_kaldirinca_jeton_da_silinir(self, dosya, tmp_path):
        veri = tmp_path / "appdata"
        auth.istemci_dosyasini_kur(dosya(MASAUSTU), veri)
        auth.jeton_yolu(veri).write_bytes(b"jeton")

        auth.kullanici_istemcisini_sil(veri)

        assert not auth.jeton_yolu(veri).is_file()

    def test_yokken_kaldirmak_hata_vermez(self, tmp_path):
        auth.kullanici_istemcisini_sil(tmp_path / "hic_olmayan")


class TestRehber:
    """Kendi hesabiyla baglanma rehberi."""

    def test_tum_adimlar_tanimli(self):
        from app.ui.drive_rehber_dialog import ADIMLAR

        assert len(ADIMLAR) >= 4
        for baslik, aciklama, _baglanti, _dugme in ADIMLAR:
            assert baslik and aciklama

    def test_baglantilar_google_cloud_adresi(self):
        from app.ui.drive_rehber_dialog import ADIMLAR

        adresler = [b for _a, _b, b, _d in ADIMLAR if b]
        assert adresler
        assert all(a.startswith("https://console.cloud.google.com/") for a in adresler)

    def test_kritik_uyarilar_rehberde_var(self):
        """Iki uyari atlanirsa kullanici saatlerce takilir."""
        from app.ui.drive_rehber_dialog import ADIMLAR

        tum_metin = " ".join(aciklama for _b, aciklama, _l, _d in ADIMLAR)
        assert "Masaüstü uygulaması" in tum_metin, "Istemci turu uyarisi yok"
        assert "yayınla" in tum_metin.lower(), "Uygulamayi yayinlama uyarisi yok"
        assert "7 gün" in tum_metin, "Test modunda jeton dusme uyarisi yok"


class TestAyarlarAkisi:
    """Gomulu istemci DAGITILMIYOR; her kurulum kendi projesini kurar."""

    @staticmethod
    def _diyalog(tmp_path, monkeypatch, gomulu_var: bool = False):
        from PySide6.QtWidgets import QApplication

        import app.ui.settings_dialog as sd
        from app.config import Ayarlar
        from app.db import Veritabani
        from app.ui.settings_dialog import AyarlarDiyalogu

        QApplication.instance() or QApplication([])

        gomulu = tmp_path / "gomulu.json"
        if gomulu_var:
            gomulu.write_text(json.dumps(MASAUSTU), encoding="utf-8")
        monkeypatch.setattr(auth, "gomulu_istemci_yolu", lambda: gomulu)

        veri = tmp_path / "appdata"
        veri.mkdir(exist_ok=True)
        monkeypatch.setattr(sd, "veri_klasoru", lambda: veri)

        vt = Veritabani(tmp_path / "t.db")
        diyalog = AyarlarDiyalogu(Ayarlar(kok_klasor=str(tmp_path)), vt)
        return diyalog, veri, vt

    def test_baglanti_yokken_baglan_dugmesi_kapali(self, tmp_path, monkeypatch):
        """Acik biraksaydik hata ancak basildiktan sonra ogrenilirdi."""
        diyalog, _veri, vt = self._diyalog(tmp_path, monkeypatch)
        try:
            assert not diyalog.baglan_dugmesi.isEnabled()
            assert diyalog.baglan_dugmesi.toolTip()
        finally:
            vt.kapat()

    def test_gomulu_yokken_o_secenek_gosterilmez(self, tmp_path, monkeypatch):
        diyalog, _veri, vt = self._diyalog(tmp_path, monkeypatch)
        try:
            assert diyalog.gomulu_secenek_etiketi.isHidden()
        finally:
            vt.kapat()

    def test_gomulu_varsa_secenek_gorunur(self, tmp_path, monkeypatch):
        diyalog, _veri, vt = self._diyalog(tmp_path, monkeypatch, gomulu_var=True)
        try:
            assert not diyalog.gomulu_secenek_etiketi.isHidden()
            assert diyalog.baglan_dugmesi.isEnabled()
        finally:
            vt.kapat()

    def test_dosya_yuklenince_baglan_acilir(self, tmp_path, monkeypatch):
        diyalog, veri, vt = self._diyalog(tmp_path, monkeypatch)
        try:
            kaynak = tmp_path / "indirilen.json"
            kaynak.write_text(json.dumps(MASAUSTU), encoding="utf-8")
            auth.istemci_dosyasini_kur(kaynak, veri)
            diyalog._istemci_durumunu_yaz()

            assert diyalog.baglan_dugmesi.isEnabled()
            assert diyalog.istemci_kaldir_dugmesi.isEnabled()
        finally:
            vt.kapat()

    def test_kaldirinca_baglan_tekrar_kapanir(self, tmp_path, monkeypatch):
        diyalog, veri, vt = self._diyalog(tmp_path, monkeypatch)
        try:
            kaynak = tmp_path / "indirilen.json"
            kaynak.write_text(json.dumps(MASAUSTU), encoding="utf-8")
            auth.istemci_dosyasini_kur(kaynak, veri)
            auth.kullanici_istemcisini_sil(veri)
            diyalog._istemci_durumunu_yaz()

            assert not diyalog.baglan_dugmesi.isEnabled()
        finally:
            vt.kapat()
