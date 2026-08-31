"""Islem tarihi: dosyalama hangi gune yapilir.

Tarih bugune sabitken dun gelen musterinin evraki bugunun klasorune duserdi
ve elde kalmis eski dosyalar hic dogru yere konamazdi. Alan varsayilan olarak
bugunu gosterir, geriye alinabilir, ileriye alinamaz.

Testler pencereyi gercekten kurar; tarayici, Drive ve guncelleme denetimi gibi
disariya cikan isler devre disi birakilir.
"""

from __future__ import annotations

import datetime as _dt

import pytest

TC = "10000000146"
AD = "ALİ"
SOYAD = "ÖZDEMİR"


@pytest.fixture
def pencere(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from app.config import Ayarlar
    from app.db import Veritabani
    from app.ui import main_window as mw

    QApplication.instance() or QApplication([])

    # Disariya cikan acilis isleri: tarayici sorgusu, Drive durumu, guncelleme
    monkeypatch.setattr(mw.AnaPencere, "cihazlari_yenile", lambda self: None)
    monkeypatch.setattr(mw.AnaPencere, "_drive_durumunu_yenile", lambda self: None)
    monkeypatch.setattr(mw.AnaPencere, "_guncellemeyi_kur", lambda self: None)

    arsiv = tmp_path / "arsiv"
    arsiv.mkdir()
    vt = Veritabani(tmp_path / "t.db")
    pnc = mw.AnaPencere(Ayarlar(kok_klasor=str(arsiv), pdf_olustur=False), vt)
    pnc._durum_zamanlayici.stop()
    try:
        yield pnc
    finally:
        pnc.close()
        vt.kapat()


def formu_doldur(pnc) -> None:
    pnc.ad_alani.setText(AD)
    pnc.soyad_alani.setText(SOYAD)
    pnc.tc_alani.setText(TC)


def taslak_koy(pnc, tmp_path) -> None:
    """Kaydedilebilir tek sayfalik bir taslak hazirlar."""
    from PIL import Image

    from app.ui.main_window import TaslakSayfa

    kaynak = tmp_path / "tarama.jpg"
    Image.new("RGB", (40, 60), "white").save(kaynak, format="JPEG")
    pnc.taslaklar = [TaslakSayfa(str(kaynak))]
    pnc._formu_denetle()


class TestVarsayilan:
    def test_acilista_bugun_secili(self, pencere):
        assert pencere._islem_tarihi() == _dt.date.today()

    def test_bugunken_uyari_ve_dugme_yok(self, pencere):
        """Olagan akista ekranda fazladan hicbir sey gorunmemeli."""
        assert pencere.tarih_uyari.text() == ""
        assert pencere.bugun_dugmesi.isHidden()

    def test_ileri_tarih_secilemez(self, pencere):
        from PySide6.QtCore import QDate

        pencere.tarih_alani.setDate(QDate.currentDate().addDays(5))

        assert pencere._islem_tarihi() == _dt.date.today()

    def test_cok_eski_tarih_secilemez(self, pencere):
        from PySide6.QtCore import QDate

        from app.ui.main_window import EN_ESKI_ISLEM_YILI

        pencere.tarih_alani.setDate(QDate(1905, 6, 12))

        assert pencere._islem_tarihi().year == EN_ESKI_ISLEM_YILI


class TestGeriyeDonuk:
    def test_uyari_ve_bugun_dugmesi_gorunur(self, pencere):
        from PySide6.QtCore import QDate

        pencere.tarih_alani.setDate(QDate.currentDate().addDays(-3))

        assert not pencere.bugun_dugmesi.isHidden()
        assert "Geriye dönük" in pencere.tarih_uyari.text()

    def test_hedef_klasor_secilen_gune_gider(self, pencere):
        from PySide6.QtCore import QDate

        formu_doldur(pencere)
        pencere.tarih_alani.setDate(QDate(2026, 1, 2))

        yol = pencere._hedef_klasor()
        assert yol.parts[-4:-1] == ("2026", "01.2026", "02.01.26")

    def test_bugun_dugmesi_geri_alir(self, pencere):
        from PySide6.QtCore import QDate

        pencere.tarih_alani.setDate(QDate.currentDate().addDays(-3))
        pencere._bugune_don()

        assert pencere._islem_tarihi() == _dt.date.today()
        assert pencere.tarih_uyari.text() == ""
        assert pencere.bugun_dugmesi.isHidden()

    def test_kayittan_sonra_tarih_korunur(self, pencere, tmp_path):
        """Eski evrak toplu girilir; her sayfada tarihi yeniden secmek zulum."""
        from PySide6.QtCore import QDate

        formu_doldur(pencere)
        taslak_koy(pencere, tmp_path)
        pencere.tarih_alani.setDate(QDate(2026, 1, 2))
        pencere.kaydet()

        assert pencere._islem_tarihi() == _dt.date(2026, 1, 2)
        assert "Geriye dönük" in pencere.tarih_uyari.text()


class TestKayit:
    def test_evrak_secilen_gunun_klasorune_yazilir(self, pencere, tmp_path):
        from PySide6.QtCore import QDate

        formu_doldur(pencere)
        taslak_koy(pencere, tmp_path)
        pencere.tarih_alani.setDate(QDate(2026, 1, 2))
        pencere.kaydet()

        kok = pencere.ayarlar.kok_klasor
        hedef = next(iter((tmp_path / "arsiv" / "2026" / "01.2026" / "02.01.26").iterdir()))
        assert str(hedef).startswith(str(kok))
        assert (hedef / "01.jpg").is_file()

    def test_meta_secilen_tarihi_tasir(self, pencere, tmp_path):
        import json

        from PySide6.QtCore import QDate

        formu_doldur(pencere)
        taslak_koy(pencere, tmp_path)
        pencere.tarih_alani.setDate(QDate(2026, 1, 2))
        pencere.kaydet()

        hedef = next(iter((tmp_path / "arsiv" / "2026" / "01.2026" / "02.01.26").iterdir()))
        veri = json.loads((hedef / "meta.json").read_text(encoding="utf-8"))
        assert veri["tarih"] == "2026-01-02"
        # Gercek yazma ani ayrica duruyor: denetimde ikisi karsilastirilabilir
        assert veri["son_guncelleme"].startswith(_dt.date.today().isoformat())

    def test_geriye_donuk_kayit_denetime_yazilir(self, pencere, tmp_path):
        from PySide6.QtCore import QDate

        formu_doldur(pencere)
        taslak_koy(pencere, tmp_path)
        pencere.tarih_alani.setDate(QDate(2026, 1, 2))
        pencere.kaydet()

        satirlar = pencere.vt.baglanti.execute(
            "SELECT ayrinti FROM denetim_kaydi WHERE eylem = 'kayit_olusturuldu'"
        ).fetchall()
        assert any("geriye dönük: 02.01.2026" in s[0] for s in satirlar)

    def test_bugunku_kayitta_denetim_notu_yok(self, pencere, tmp_path):
        formu_doldur(pencere)
        taslak_koy(pencere, tmp_path)
        pencere.kaydet()

        satirlar = pencere.vt.baglanti.execute(
            "SELECT ayrinti FROM denetim_kaydi WHERE eylem = 'kayit_olusturuldu'"
        ).fetchall()
        assert satirlar and all("geriye dönük" not in s[0] for s in satirlar)
