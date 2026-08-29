"""Ayar dosyasi okuma/yazma ve dogrulama testleri."""

import json

from app.config import Ayarlar


class TestOkuma:
    def test_dosya_yoksa_varsayilanlar_kullanilir(self, tmp_path):
        ayarlar = Ayarlar.yukle(tmp_path / "yok.json")
        assert ayarlar.varsayilan_dpi == 300
        assert not ayarlar.okuma_hatasi

    def test_gecerli_dosya_okunur(self, tmp_path):
        yol = tmp_path / "c.json"
        yol.write_text(
            json.dumps({"kok_klasor": "D:/Arsiv", "sube_adi": "MERKEZ", "jpeg_kalite": 92}),
            encoding="utf-8",
        )
        ayarlar = Ayarlar.yukle(yol)
        assert ayarlar.kok_klasor == "D:/Arsiv"
        assert ayarlar.sube == "MERKEZ"
        assert ayarlar.jpeg_kalite == 92

    def test_bozuk_dosya_sessizce_gecilmez(self, tmp_path):
        """Sessiz yutulursa 'ayari degistirdim ama etkisi yok' hatasi tespit edilemez."""
        yol = tmp_path / "c.json"
        yol.write_text("{bozuk json", encoding="utf-8")

        ayarlar = Ayarlar.yukle(yol)

        assert ayarlar.okuma_hatasi, "Bozuk dosya icin uyari uretilmedi"
        assert ayarlar.dogrula(), "Bozuk dosya dogrulama sorunu olarak gorunmuyor"
        assert ayarlar.varsayilan_dpi == 300, "Yine de acilabilmeli"

    def test_liste_iceren_dosya_reddedilir(self, tmp_path):
        yol = tmp_path / "c.json"
        yol.write_text("[1, 2, 3]", encoding="utf-8")
        assert Ayarlar.yukle(yol).okuma_hatasi

    def test_taninmayan_alanlar_yok_sayilir(self, tmp_path):
        """Eski surumden kalan alan uygulamayi cokertmemeli."""
        yol = tmp_path / "c.json"
        yol.write_text(
            json.dumps({"kok_klasor": "D:/A", "kaldirilmis_ayar": 5}), encoding="utf-8"
        )
        assert Ayarlar.yukle(yol).kok_klasor == "D:/A"

    def test_eksik_alanlar_varsayilanla_tamamlanir(self, tmp_path):
        yol = tmp_path / "c.json"
        yol.write_text(json.dumps({"kok_klasor": "D:/A"}), encoding="utf-8")
        assert Ayarlar.yukle(yol).jpeg_kalite == 85


class TestYazma:
    def test_gidip_gelen_deger_korunur(self, tmp_path):
        yol = tmp_path / "c.json"
        Ayarlar(kok_klasor="D:/A", sube_adi="ŞUBE", jpeg_kalite=70).kaydet(yol)

        geri = Ayarlar.yukle(yol)
        assert geri.kok_klasor == "D:/A"
        assert geri.sube_adi == "ŞUBE"
        assert geri.jpeg_kalite == 70

    def test_gecici_uyari_diske_yazilmaz(self, tmp_path):
        yol = tmp_path / "c.json"
        ayarlar = Ayarlar()
        ayarlar.okuma_hatasi = "gecici uyari"
        ayarlar.kaydet(yol)

        assert "okuma_hatasi" not in json.loads(yol.read_text(encoding="utf-8"))

    def test_gecici_dosya_birakilmaz(self, tmp_path):
        Ayarlar().kaydet(tmp_path / "c.json")
        assert not list(tmp_path.glob("*.tmp"))


class TestDogrulama:
    def test_temiz_ayarda_sorun_yok(self):
        assert Ayarlar().dogrula() == []

    def test_bos_kok_klasor_yakalanir(self):
        assert Ayarlar(kok_klasor="   ").dogrula()

    def test_gecersiz_dpi_yakalanir(self):
        assert Ayarlar(varsayilan_dpi=137).dogrula()

    def test_sinir_disi_kalite_yakalanir(self):
        assert Ayarlar(jpeg_kalite=10).dogrula()
        assert Ayarlar(jpeg_kalite=120).dogrula()

    def test_drive_acik_ama_kok_yoksa_uyarilir(self):
        sorunlar = Ayarlar(drive_etkin=True, drive_kok_klasor_id="").dogrula()
        assert any("Drive" in s for s in sorunlar)

    def test_drive_acik_ve_kok_varsa_sorun_yok(self):
        assert Ayarlar(drive_etkin=True, drive_kok_klasor_id="abc123").dogrula() == []


class TestSubeOzelligi:
    def test_sube_adi_onceliklidir(self):
        assert Ayarlar(sube_kodu="MRK", sube_adi="MERKEZ").sube == "MERKEZ"

    def test_ad_yoksa_kod_kullanilir(self):
        assert Ayarlar(sube_kodu="MRK").sube == "MRK"

    def test_ikisi_de_bosken_sube_seviyesi_olusmaz(self):
        assert Ayarlar().sube == ""
        assert Ayarlar(sube_adi="   ").sube == ""
