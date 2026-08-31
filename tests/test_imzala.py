"""Kod imzalama adimi.

Imza, Akilli Uygulama Denetimi acik makinelerde kurulumun hic baslamamasina
karsi tek kalici cozum; bu yuzden davranisi sozlesme gibi sabit olmali:
degisken yoksa paketleme sessizce surmeli, degisken varsa TEK BIR dosya bile
atlanmamali. Testler signtool cagirmaz, komutu taklit eder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import imzala


class SahteSonuc:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = "signtool: erisim reddedildi" if returncode else ""


@pytest.fixture
def cagrilar(monkeypatch):
    """subprocess.run cagrilarini toplar; disari hicbir sey calismaz."""
    kayit: list[list[str]] = []

    def sahte_run(komut, **_):
        kayit.append(list(komut))
        return SahteSonuc()

    monkeypatch.setattr(imzala.subprocess, "run", sahte_run)
    return kayit


def paket_kur(kok: Path) -> Path:
    """Ornek bir dist\\Docvera agaci: imzalanacak ve imzalanmayacak dosyalar."""
    klasor = kok / "Docvera"
    (klasor / "_internal" / "PySide6").mkdir(parents=True)
    for ad in (
        "Docvera.exe",
        "unins000.exe",
        "_internal/python314.dll",
        "_internal/_socket.pyd",
        "_internal/PySide6/Qt6Core.dll",
        "_internal/base_library.zip",
        "_internal/app/varliklar/docvera-simge.ico",
    ):
        hedef = klasor / ad
        hedef.parent.mkdir(parents=True, exist_ok=True)
        hedef.write_bytes(b"x")
    return klasor


class TestSablon:
    def test_degisken_yoksa_imza_atlanir(self, monkeypatch, cagrilar, tmp_path):
        monkeypatch.delenv(imzala.DEGISKEN, raising=False)

        assert imzala.hazir_mi() is False
        assert imzala.paketi_imzala(paket_kur(tmp_path)) == 0
        assert cagrilar == []

    def test_bos_degisken_tanimsiz_sayilir(self, monkeypatch):
        monkeypatch.setenv(imzala.DEGISKEN, "   ")
        assert imzala.hazir_mi() is False

    def test_windows_yolundaki_ters_bolu_kacis_degil(self, monkeypatch):
        """C:\\Program Files\\... yolu tek parca kalmali, \\P kacisi olmamali."""
        monkeypatch.setenv(
            imzala.DEGISKEN,
            r'signtool.exe sign /f "C:\Program Files\imza\docvera.pfx" /a $f',
        )
        assert imzala._bol(imzala.sablon()) == [
            "signtool.exe",
            "sign",
            "/f",
            r"C:\Program Files\imza\docvera.pfx",
            "/a",
            "$f",
        ]

    def test_yer_tutucusuz_sablon_reddedilir(self, monkeypatch, cagrilar, tmp_path):
        """$f yoksa signtool'a dosya hic gitmez; sessizce imzasiz paket cikardi."""
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a")

        with pytest.raises(SystemExit, match=r"\$f"):
            imzala.dosyalari_imzala([tmp_path / "Docvera.exe"])
        assert cagrilar == []


class TestPaketiImzala:
    def test_calistirilabilir_dosyalarin_hepsi_imzalanir(
        self, monkeypatch, cagrilar, tmp_path
    ):
        """DLL/PYD atlanirsa uygulama acilirken ilkeye takilip duser."""
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a $f")
        klasor = paket_kur(tmp_path)

        sayi = imzala.paketi_imzala(klasor)

        imzalanan = {Path(p).name for c in cagrilar for p in c[3:]}
        assert imzalanan == {
            "Docvera.exe",
            "unins000.exe",
            "python314.dll",
            "_socket.pyd",
            "Qt6Core.dll",
        }
        assert sayi == 5

    def test_veri_dosyalari_imzalanmaz(self, monkeypatch, cagrilar, tmp_path):
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a $f")
        imzala.paketi_imzala(paket_kur(tmp_path))

        gecenler = " ".join(p for c in cagrilar for p in c)
        assert "base_library.zip" not in gecenler
        assert "docvera-simge.ico" not in gecenler

    def test_dosyalar_obek_obek_verilir(self, monkeypatch, cagrilar, tmp_path):
        """Windows komut satiri ~32k; tek cagrida yuzlerce yol sigmaz."""
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a $f")
        yollar = [tmp_path / f"kutuphane{i}.dll" for i in range(imzala.OBEK * 2 + 3)]

        imzala.dosyalari_imzala(yollar)

        assert len(cagrilar) == 3
        assert all(len(c) - 3 <= imzala.OBEK for c in cagrilar)
        assert sum(len(c) - 3 for c in cagrilar) == len(yollar)

    def test_sabit_parametreler_her_obekte_tekrarlanir(
        self, monkeypatch, cagrilar, tmp_path
    ):
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /fd SHA256 $f")
        imzala.dosyalari_imzala([tmp_path / f"a{i}.dll" for i in range(imzala.OBEK + 1)])

        assert len(cagrilar) == 2
        for komut in cagrilar:
            assert komut[:4] == ["signtool.exe", "sign", "/fd", "SHA256"]

    def test_imza_basarisizsa_yayin_durur(self, monkeypatch, tmp_path):
        """Yarim imzalanmis paket yayimlanmamali; hata yutulmaz."""
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a $f")
        monkeypatch.setattr(
            imzala.subprocess, "run", lambda komut, **_: SahteSonuc(returncode=1)
        )

        with pytest.raises(SystemExit, match="erisim reddedildi"):
            imzala.paketi_imzala(paket_kur(tmp_path))


class TestYayinBaglantisi:
    def test_iss_sablonu_ayni_degiskenden_beslenir(self, monkeypatch):
        """Inno de $f bilir: PyInstaller ciktisi ve sihirbaz tek sablonla imzalanir."""
        monkeypatch.setenv(imzala.DEGISKEN, "signtool.exe sign /a $f")

        from tools import yayinla

        cagri: list[list[str]] = []
        monkeypatch.setattr(yayinla, "iscc_bul", lambda: "ISCC.exe")
        monkeypatch.setattr(
            yayinla.subprocess,
            "run",
            lambda komut, **_: (cagri.append(list(komut)), SahteSonuc())[1],
        )
        monkeypatch.setattr(Path, "is_file", lambda self: True)

        yayinla.kurulum_uret("1.0.27")

        assert "/DIMZALI" in cagri[0]
        assert f"/Sdocvera={imzala.sablon()}" in cagri[0]

    def test_imzasiz_derlemede_bayrak_gecmez(self, monkeypatch):
        monkeypatch.delenv(imzala.DEGISKEN, raising=False)

        from tools import yayinla

        cagri: list[list[str]] = []
        monkeypatch.setattr(yayinla, "iscc_bul", lambda: "ISCC.exe")
        monkeypatch.setattr(
            yayinla.subprocess,
            "run",
            lambda komut, **_: (cagri.append(list(komut)), SahteSonuc())[1],
        )
        monkeypatch.setattr(Path, "is_file", lambda self: True)

        yayinla.kurulum_uret("1.0.27")

        assert not [p for p in cagri[0] if p.startswith(("/DIMZALI", "/Sdocvera"))]
