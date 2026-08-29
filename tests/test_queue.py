"""Drive yukleme kuyrugu testleri - sahte istemciyle, ag baglantisi olmadan."""

import datetime as dt

import pytest

from app.db import BEKLIYOR, MANUEL, TAMAM, Veritabani
from app.drive.client import DriveHatasi
from app.drive.queue import YuklemeKuyrugu, bekleme_suresi


class SahteIstemci:
    """DriveIstemcisi arayuzunu taklit eder."""

    def __init__(self, hata: Exception | None = None, kac_kez: int = 0):
        """hata: firlatilacak istisna. kac_kez: kacinci cagridan sonra duzelsin."""
        self.hata = hata
        self.kalan_hata = kac_kez if kac_kez else (999 if hata else 0)
        self.yuklenenler: list[str] = []
        self.cozulen_yollar: list[list[str]] = []

    def yolu_coz(self, parcalar, kok_id):
        self.cozulen_yollar.append(list(parcalar))
        return "klasor-" + "-".join(parcalar)

    def dosya_yukle(self, yerel_yol, ad, ust_id):
        if self.hata and self.kalan_hata > 0:
            self.kalan_hata -= 1
            raise self.hata
        self.yuklenenler.append(ad)
        return f"drive-id-{ad}"


@pytest.fixture
def vt(tmp_path):
    veritabani = Veritabani(tmp_path / "test.db")
    yield veritabani
    veritabani.kapat()


@pytest.fixture
def dosya(tmp_path):
    yol = tmp_path / "01.jpg"
    yol.write_bytes(b"sahte jpeg verisi")
    return yol


def kuyruk_kur(vt, istemci, azami_deneme=8):
    return YuklemeKuyrugu(vt, lambda: istemci, "kok-id", azami_deneme=azami_deneme)


class TestBeklemeSuresi:
    def test_ustel_olarak_artar(self):
        sureler = [bekleme_suresi(n) for n in range(1, 6)]
        assert sureler == [5, 30, 120, 600, 3600]

    def test_ust_sinirda_sabitlenir(self):
        assert bekleme_suresi(20) == 3600

    def test_ilk_denemede_beklenmez(self):
        assert bekleme_suresi(0) == 0


class TestBasariliYukleme:
    def test_dosya_yuklenir_ve_tamam_isaretlenir(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026", "01.2026"], "01.jpg")
        istemci = SahteIstemci()

        islenen = kuyruk_kur(vt, istemci).bir_tur_isle()

        assert islenen == 1
        assert istemci.yuklenenler == ["01.jpg"]
        assert vt.kuyruk_ozeti() == {TAMAM: 1}

    def test_klasor_agaci_dogru_kurulur(self, vt, dosya):
        parcalar = ["MERKEZ", "2026", "01.2026", "02.01.26", "ALİ ÖZDEMİR 0146"]
        vt.kuyruga_ekle(None, str(dosya), parcalar, "01.jpg")
        istemci = SahteIstemci()

        kuyruk_kur(vt, istemci).bir_tur_isle()

        assert istemci.cozulen_yollar == [parcalar]

    def test_bos_kuyrukta_is_yok(self, vt):
        assert kuyruk_kur(vt, SahteIstemci()).bir_tur_isle() == 0


class TestCevrimdisiSenaryosu:
    def test_gecici_hata_yeniden_denemeye_alinir(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci(DriveHatasi("Ag yok", gecici=True))

        kuyruk_kur(vt, istemci).bir_tur_isle()

        assert vt.kuyruk_ozeti() == {BEKLIYOR: 1}
        kayit = vt.baglanti.execute("SELECT * FROM yukleme_kuyrugu").fetchone()
        assert kayit["deneme"] == 1
        assert kayit["son_hata"] == "Ag yok"
        assert kayit["sonraki_deneme"] is not None

    def test_bekleme_suresi_dolmadan_tekrar_denenmez(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci(DriveHatasi("Ag yok", gecici=True))
        kuyruk = kuyruk_kur(vt, istemci)

        kuyruk.bir_tur_isle()
        # Sonraki deneme zamani gelecekte oldugu icin sira bos gorunmeli
        assert vt.kuyruk_sirada() == []
        assert kuyruk.bir_tur_isle() == 0

    def test_baglanti_gelince_yuklenir(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        # Ilk cagri hata verir, ikincisi basarili olur
        istemci = SahteIstemci(DriveHatasi("Ag yok", gecici=True), kac_kez=1)
        kuyruk = kuyruk_kur(vt, istemci)

        kuyruk.bir_tur_isle()
        assert vt.kuyruk_ozeti() == {BEKLIYOR: 1}

        # Bekleme suresini gecmis yaparak "zaman gecti" durumunu taklit et
        gecmis = (dt.datetime.now() - dt.timedelta(minutes=1)).isoformat(timespec="seconds")
        vt.baglanti.execute("UPDATE yukleme_kuyrugu SET sonraki_deneme = ?", (gecmis,))
        vt.baglanti.commit()

        kuyruk.bir_tur_isle()
        assert vt.kuyruk_ozeti() == {TAMAM: 1}
        assert istemci.yuklenenler == ["01.jpg"]


class TestKaliciHatalar:
    def test_kalici_hata_hemen_manuele_duser(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci(DriveHatasi("Yetki gecersiz", gecici=False))

        kuyruk_kur(vt, istemci).bir_tur_isle()

        assert vt.kuyruk_ozeti() == {MANUEL: 1}

    def test_deneme_hakki_bitince_manuele_duser(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci(DriveHatasi("Ag yok", gecici=True))
        kuyruk = kuyruk_kur(vt, istemci, azami_deneme=3)

        gecmis = (dt.datetime.now() - dt.timedelta(hours=2)).isoformat(timespec="seconds")
        for _ in range(3):
            kuyruk.bir_tur_isle()
            vt.baglanti.execute("UPDATE yukleme_kuyrugu SET sonraki_deneme = ?", (gecmis,))
            vt.baglanti.commit()

        assert vt.kuyruk_ozeti() == {MANUEL: 1}

    def test_silinmis_yerel_dosya_kuyrugu_tikamaz(self, vt, tmp_path):
        yok = tmp_path / "silinmis.jpg"
        vt.kuyruga_ekle(None, str(yok), ["2026"], "silinmis.jpg")
        istemci = SahteIstemci()

        kuyruk_kur(vt, istemci).bir_tur_isle()

        assert vt.kuyruk_ozeti() == {MANUEL: 1}
        assert istemci.yuklenenler == []

    def test_manuel_kayitlar_sifirlanabilir(self, vt, dosya):
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci(DriveHatasi("Yetki gecersiz", gecici=False))
        kuyruk_kur(vt, istemci).bir_tur_isle()
        assert vt.kuyruk_ozeti() == {MANUEL: 1}

        assert vt.kuyruk_sifirla(sadece_manuel=True) == 1
        assert vt.kuyruk_ozeti() == {BEKLIYOR: 1}


class TestYenidenKuyruklama:
    def test_ayni_dosya_tekrar_eklenirse_yeniden_yuklenir(self, vt, dosya):
        """PDF her sayfa eklendiginde yeniden uretilir; guncel hali yuklenmeli."""
        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        istemci = SahteIstemci()
        kuyruk_kur(vt, istemci).bir_tur_isle()
        assert vt.kuyruk_ozeti() == {TAMAM: 1}

        vt.kuyruga_ekle(None, str(dosya), ["2026"], "01.jpg")
        assert vt.kuyruk_ozeti() == {BEKLIYOR: 1}, "Tekrar eklenen dosya sifirlanmali"

        kuyruk_kur(vt, istemci).bir_tur_isle()
        assert istemci.yuklenenler == ["01.jpg", "01.jpg"]
