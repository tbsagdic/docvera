"""Guncelleme sistemi testleri.

Ag baglantisi kullanilmaz: GitHub yaniti ve indirme sahte nesnelerle
taklit edilir. Kurulum betigi gercekten calistirilmaz, yalnizca uretilen
icerigi ve baslatma cagrisi denetlenir.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile

import pytest

from app import guncelleme
from app.guncelleme import GuncellemeHatasi, GuncellemeIptal, Yayin


# --- Surum karsilastirma ---------------------------------------------------


@pytest.mark.parametrize(
    "metin, beklenen",
    [
        ("v1.0.12", (1, 0, 12)),
        ("1.0.3", (1, 0, 3)),
        ("Docvera 2.10.0", (2, 10, 0)),
        ("", ()),
        ("surum-yok", ()),
    ],
)
def test_surum_demeti(metin, beklenen):
    assert guncelleme.surum_demeti(metin) == beklenen


@pytest.mark.parametrize(
    "aday, mevcut, beklenen",
    [
        ("1.0.4", "1.0.3", True),
        ("v1.0.4", "1.0.3", True),
        ("1.0.3", "1.0.3", False),
        ("1.0.2", "1.0.3", False),
        ("1.0.10", "1.0.9", True),  # sayisal karsilastirma, metin degil
        ("1.1", "1.0.9", True),
        ("1.0", "1.0.0", False),  # eksik hane sifirla tamamlanir
        ("surum-yok", "1.0.3", False),  # bozuk etiket guncelleme sayilmaz
    ],
)
def test_daha_yeni_mi(aday, mevcut, beklenen):
    assert guncelleme.daha_yeni_mi(aday, mevcut) is beklenen


# --- GitHub yaniti ---------------------------------------------------------


def _api_yaniti(**degisiklik) -> dict:
    veri = {
        "tag_name": "v1.0.7",
        "html_url": "https://github.com/tbsagdic/docvera/releases/tag/v1.0.7",
        "body": "Docvera 1.0.7\n\nSHA-256: `" + "a" * 64 + "`",
        "assets": [
            {
                "name": "Docvera-1.0.7-win64.zip",
                "browser_download_url": "https://example.invalid/Docvera.zip",
                "size": 12345,
            }
        ],
    }
    veri.update(degisiklik)
    return veri


def test_yayini_ayristir():
    yayin = guncelleme.yayini_ayristir(_api_yaniti())
    assert yayin.surum == "1.0.7"
    assert yayin.etiket == "v1.0.7"
    assert yayin.dosya_adi == "Docvera-1.0.7-win64.zip"
    assert yayin.boyut == 12345
    assert yayin.sha256 == "a" * 64  # notlardaki ozet okundu


def test_yayini_ayristir_digest_notlardan_once_gelir():
    veri = _api_yaniti()
    veri["assets"][0]["digest"] = "sha256:" + "b" * 64
    assert guncelleme.yayini_ayristir(veri).sha256 == "b" * 64


def test_yayini_ayristir_paketsiz_yayin_hata_vermez():
    """Eki eksik bir yayin, guncel surumde calisan kullaniciyi ilgilendirmez."""
    veri = _api_yaniti(assets=[{"name": "kaynak.tar.gz", "browser_download_url": "x"}])
    assert guncelleme.yayini_ayristir(veri).indirme_url == ""


def test_guncelleme_var_mi_eski_surum_icin_paketsizligi_umursamaz(monkeypatch):
    yayin = guncelleme.yayini_ayristir(_api_yaniti(tag_name="v1.0.1", assets=[]))
    monkeypatch.setattr(guncelleme, "son_yayin", lambda *a, **k: yayin)
    assert guncelleme.guncelleme_var_mi("1.0.7") is None


def test_guncelleme_var_mi_yeni_surum_paketsizse_uyarir(monkeypatch):
    yayin = guncelleme.yayini_ayristir(_api_yaniti(assets=[]))
    monkeypatch.setattr(guncelleme, "son_yayin", lambda *a, **k: yayin)
    with pytest.raises(GuncellemeHatasi, match="elle indirmeniz"):
        guncelleme.guncelleme_var_mi("1.0.3")


def test_guncelleme_var_mi_yeni_surumu_dondurur(monkeypatch):
    yayin = guncelleme.yayini_ayristir(_api_yaniti())
    monkeypatch.setattr(guncelleme, "son_yayin", lambda *a, **k: yayin)
    assert guncelleme.guncelleme_var_mi("1.0.3").surum == "1.0.7"


def test_yayini_ayristir_bozuk_etiket():
    with pytest.raises(GuncellemeHatasi):
        guncelleme.yayini_ayristir(_api_yaniti(tag_name="son-surum"))


def test_paket_sec_windows_paketini_tercih_eder():
    varliklar = [
        {"name": "Docvera-linux.zip", "browser_download_url": "a"},
        {"name": "Docvera-1.0.7-win64.zip", "browser_download_url": "b"},
    ]
    assert guncelleme._paket_sec(varliklar)["browser_download_url"] == "b"


# --- Indirme ---------------------------------------------------------------


class _SahteYanit(io.BytesIO):
    """urlopen yanitini taklit eder."""

    def __init__(self, veri: bytes):
        super().__init__(veri)
        self.headers = {"Content-Length": str(len(veri))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False


def _zip_baytlari() -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as arsiv:
        arsiv.writestr("Docvera/Docvera.exe", "MZ sahte")
    return tampon.getvalue()


def _yayin(veri: bytes, sha: str = "") -> Yayin:
    return Yayin(
        surum="1.0.7",
        etiket="v1.0.7",
        notlar="",
        indirme_url="https://example.invalid/Docvera.zip",
        dosya_adi="Docvera-1.0.7-win64.zip",
        boyut=len(veri),
        sayfa_url="https://example.invalid/",
        sha256=sha,
    )


@pytest.fixture
def veri_klasoru(tmp_path, monkeypatch):
    """Uygulama veri klasorunu geçici klasore tasir."""
    monkeypatch.setattr(guncelleme, "veri_klasoru", lambda: tmp_path)
    return tmp_path


def test_indir_dogru_ozetle_basarili(veri_klasoru, monkeypatch):
    veri = _zip_baytlari()
    sha = hashlib.sha256(veri).hexdigest()
    monkeypatch.setattr(guncelleme, "urlopen", lambda *a, **k: _SahteYanit(veri))

    yol = guncelleme.indir(_yayin(veri, sha))

    assert yol.read_bytes() == veri
    assert yol.name == "Docvera-1.0.7-win64.zip"


def test_indir_ozet_tutmazsa_dosyayi_birakmaz(veri_klasoru, monkeypatch):
    veri = _zip_baytlari()
    monkeypatch.setattr(guncelleme, "urlopen", lambda *a, **k: _SahteYanit(veri))

    with pytest.raises(GuncellemeHatasi, match="doğrulaması"):
        guncelleme.indir(_yayin(veri, "c" * 64))

    kalanlar = list((veri_klasoru / "guncelleme").iterdir())
    assert kalanlar == []  # yarim/kusurlu paket diskte birakilmaz


def test_indir_boyut_eksikse_hata(veri_klasoru, monkeypatch):
    veri = _zip_baytlari()
    monkeypatch.setattr(guncelleme, "urlopen", lambda *a, **k: _SahteYanit(veri))
    # Sunucu beklenenden az veri gonderdi: yayin boyutu tutmuyor
    yayin = Yayin(
        surum="1.0.7",
        etiket="v1.0.7",
        notlar="",
        indirme_url="https://example.invalid/Docvera.zip",
        dosya_adi="Docvera-1.0.7-win64.zip",
        boyut=len(veri) + 1000,
        sayfa_url="https://example.invalid/",
    )

    with pytest.raises(GuncellemeHatasi, match="eksik"):
        guncelleme.indir(yayin)


def test_indir_zip_degilse_hata(veri_klasoru, monkeypatch):
    veri = b"bu bir zip degil" * 100
    monkeypatch.setattr(guncelleme, "urlopen", lambda *a, **k: _SahteYanit(veri))

    with pytest.raises(GuncellemeHatasi, match="geçerli bir paket"):
        guncelleme.indir(_yayin(veri))


def test_indir_iptal_edilebilir(veri_klasoru, monkeypatch):
    veri = _zip_baytlari() * 50
    monkeypatch.setattr(guncelleme, "urlopen", lambda *a, **k: _SahteYanit(veri))

    with pytest.raises(GuncellemeIptal):
        guncelleme.indir(_yayin(veri), iptal=lambda: True)

    assert list((veri_klasoru / "guncelleme").iterdir()) == []


# --- Paket koku ------------------------------------------------------------


def test_paket_koku_alt_klasoru_bulur(tmp_path):
    alt = tmp_path / "Docvera"
    alt.mkdir()
    (alt / "Docvera.exe").write_text("MZ")
    assert guncelleme._paket_koku(tmp_path) == alt


def test_paket_koku_exe_yoksa_hata(tmp_path):
    (tmp_path / "okuma.txt").write_text("x")
    with pytest.raises(GuncellemeHatasi):
        guncelleme._paket_koku(tmp_path)


# --- Kurulum betigi --------------------------------------------------------


def test_kur_betigi_uretir_ve_baslatir(tmp_path, monkeypatch):
    kurulum = tmp_path / "program" / "Docvera"
    kurulum.mkdir(parents=True)
    (kurulum / "Docvera.exe").write_text("eski")
    veri = tmp_path / "veri"
    veri.mkdir()

    paket_zip = tmp_path / "paket.zip"
    with zipfile.ZipFile(paket_zip, "w") as arsiv:
        arsiv.writestr("Docvera/Docvera.exe", "yeni")
        arsiv.writestr("Docvera/_internal/veri.dat", "x")

    monkeypatch.setattr(guncelleme, "kurulum_klasoru", lambda: kurulum)
    monkeypatch.setattr(guncelleme, "kurulabilir_mi", lambda: (True, ""))
    monkeypatch.setattr(guncelleme, "veri_klasoru", lambda: veri)

    baslatilan = {}

    def sahte_popen(komut, **kwargs):
        baslatilan["komut"] = komut
        baslatilan["bayraklar"] = kwargs.get("creationflags", 0)
        return object()

    monkeypatch.setattr(guncelleme.subprocess, "Popen", sahte_popen)

    betik = guncelleme.kur(paket_zip, _yayin(b"x"))

    icerik = betik.read_text(encoding="ascii")
    assert str(kurulum) in icerik  # hedef klasor
    assert "move" in icerik and "Docvera.exe" in icerik
    # Kurulum sihirbaziyla gelen kaldirici yeni pakette yok; korunmali
    assert "unins000" in icerik
    assert baslatilan["komut"][:2] == ["cmd", "/c"]
    # Betik kendi konsolunda calismali: konsolsuz baslatilirsa cmd ilk echo
    # satirinda oluyor ve guncelleme sessizce yarim kaliyor
    assert baslatilan["bayraklar"] & 0x00000010
    # Paket, hedefin yaninda acilmis olmali (move ayni diskte anlik olsun diye)
    assert (kurulum.parent / f".docvera_paket_{os.getpid()}").is_dir()


def test_yarim_kalan_kurulum_tespit_edilir(veri_klasoru, monkeypatch):
    """Betik kalmis ama sonuc yazilmamissa kurulum hic calismamistir."""
    monkeypatch.setattr(guncelleme, "kurulum_klasoru", lambda: None)
    klasor = veri_klasoru / "guncelleme"
    klasor.mkdir()
    (klasor / "kur_123.bat").write_text("x")
    (klasor / "Docvera-1.0.7-win64.zip").write_text("y")

    assert guncelleme.yarim_kalan_kurulum() is True
    assert list(klasor.iterdir()) == []  # kalintilar temizlendi
    assert guncelleme.yarim_kalan_kurulum() is False  # ikinci kez uyarmaz


def test_kur_izin_yoksa_indirmeden_once_durur(monkeypatch):
    monkeypatch.setattr(guncelleme, "kurulabilir_mi", lambda: (False, "izin yok"))
    with pytest.raises(GuncellemeHatasi, match="izin yok"):
        guncelleme.kur("olmayan.zip", _yayin(b"x"))


# --- Kurulum sonucu --------------------------------------------------------


@pytest.mark.parametrize(
    "icerik, durum",
    [
        ("TAMAM 1.0.7", "tamam"),
        ("HATA Eski surum klasoru kilitli.", "hata"),
        ("anlamsiz", ""),
    ],
)
def test_sonucu_al(veri_klasoru, icerik, durum):
    dosya = veri_klasoru / guncelleme.SONUC_DOSYASI
    dosya.write_text(icerik, encoding="utf-8")

    sonuc, mesaj = guncelleme.sonucu_al()

    assert sonuc == durum
    assert not dosya.exists()  # sonuc bir kez gosterilir
    if durum:
        assert mesaj


def test_sonucu_al_dosya_yoksa_bos(veri_klasoru):
    assert guncelleme.sonucu_al() == ("", "")
