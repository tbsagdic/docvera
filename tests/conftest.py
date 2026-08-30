"""Tum testler icin ortak koruma: gercek kullanici klasorune asla yazilmasin.

`app.config.veri_klasoru()` konumu APPDATA'dan okur. Bir test - ya da test
icinde kurulan bir pencere - `Ayarlar.kaydet()` cagirdiginda parametresiz
surum kullanicinin gercek `%APPDATA%\\Docvera\\config.json` dosyasinin
uzerine yazar; arsiv kok klasoru gecici bir dizine donebilir ve kaydedilen
evrak yanlis yere duser.

Bu fikstur her testte APPDATA/LOCALAPPDATA'yi gecici bir klasore cevirir:
kaza olsa bile gercek ayarlar, veritabani ve gunluk dosyalari korunur.
"""

import pytest


@pytest.fixture(autouse=True)
def kullanici_klasorunu_yalit(tmp_path_factory, monkeypatch):
    taban = tmp_path_factory.mktemp("kullanici")
    for degisken in ("APPDATA", "LOCALAPPDATA"):
        hedef = taban / degisken.lower()
        hedef.mkdir(exist_ok=True)
        monkeypatch.setenv(degisken, str(hedef))
    return taban
