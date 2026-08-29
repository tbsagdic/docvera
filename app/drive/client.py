"""Google Drive istemcisi: klasor agaci kurma ve dosya yukleme.

Klasor kimlikleri SQLite'ta onbelleklenir; aksi halde her dosya yuklemesinde
klasor agaci icin 4-5 ek API cagrisi yapilirdi.
"""

from __future__ import annotations

import logging
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

log = logging.getLogger(__name__)

KLASOR_TURU = "application/vnd.google-apps.folder"

# 5 MB'lik parcalar halinde yukleme - kesilen baglantida bastan baslanmaz
PARCA_BOYUTU = 5 * 1024 * 1024

# Yeniden denemenin anlamli oldugu HTTP durumlari
GECICI_DURUMLAR = frozenset({403, 408, 429, 500, 502, 503, 504})


class DriveHatasi(Exception):
    """Drive islemi hatasi."""

    def __init__(self, mesaj: str, gecici: bool = False):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.gecici = gecici


def _http_hatasini_cevir(hata: HttpError) -> DriveHatasi:
    durum = getattr(getattr(hata, "resp", None), "status", None)
    gecici = durum in GECICI_DURUMLAR
    if durum == 401:
        return DriveHatasi(
            "Google Drive yetkilendirmesi geçersiz. Ayarlardan yeniden bağlanın.",
            gecici=False,
        )
    if durum == 403:
        return DriveHatasi(
            "Drive kotası aşıldı veya erişim reddedildi. Daha sonra yeniden denenecek.",
            gecici=True,
        )
    if durum == 404:
        return DriveHatasi(
            "Drive'daki hedef klasör bulunamadı. Kök klasör silinmiş olabilir.",
            gecici=False,
        )
    return DriveHatasi(f"Drive hatası (HTTP {durum}): {hata}", gecici=gecici)


def _tirnak_kacir(ad: str) -> str:
    """Drive sorgu dilinde tek tirnak ve ters bolu kacirilmalidir."""
    return ad.replace("\\", "\\\\").replace("'", "\\'")


class DriveIstemcisi:
    """Drive v3 uzerinde klasor/dosya islemleri."""

    def __init__(self, kimlik, klasor_onbellegi=None):
        """klasor_onbellegi: app.db.Veritabani benzeri, klasor_id_getir/yaz sunan nesne."""
        self.servis = build("drive", "v3", credentials=kimlik, cache_discovery=False)
        self.onbellek = klasor_onbellegi

    # --- Klasorler --------------------------------------------------------

    def kok_klasor_olustur(self, ad: str) -> str:
        """Drive'in kokunde arsiv klasorunu olusturur ve id'sini dondurur.

        drive.file kapsami mevcut bir klasore yazmaya izin vermedigi icin kok
        klasorun uygulama tarafindan olusturulmasi zorunludur.
        """
        try:
            sonuc = (
                self.servis.files()
                .create(
                    body={"name": ad, "mimeType": KLASOR_TURU},
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise _http_hatasini_cevir(exc) from exc
        return sonuc["id"]

    def klasor_bul_veya_olustur(self, ad: str, ust_id: str) -> str:
        """Ust klasor altinda adi gecen klasoru bulur, yoksa olusturur."""
        sorgu = (
            f"name = '{_tirnak_kacir(ad)}' and '{ust_id}' in parents "
            f"and mimeType = '{KLASOR_TURU}' and trashed = false"
        )
        try:
            sonuc = (
                self.servis.files()
                .list(
                    q=sorgu,
                    fields="files(id, name)",
                    pageSize=1,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            dosyalar = sonuc.get("files", [])
            if dosyalar:
                return dosyalar[0]["id"]

            olusan = (
                self.servis.files()
                .create(
                    body={"name": ad, "mimeType": KLASOR_TURU, "parents": [ust_id]},
                    fields="id",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise _http_hatasini_cevir(exc) from exc
        return olusan["id"]

    def yolu_coz(self, parcalar: list[str], kok_id: str) -> str:
        """Klasor agacini kurar ve en alttaki klasorun id'sini dondurur.

        Ara klasorler onbellekten okunur; boylece ayni gun icindeki her yeni
        musteri icin yil/ay/gun klasorleri tekrar sorgulanmaz.
        """
        ust_id = kok_id
        anahtar_parcalari: list[str] = []
        for parca in parcalar:
            anahtar_parcalari.append(parca)
            anahtar = f"{kok_id}/" + "/".join(anahtar_parcalari)

            onbellekli = self.onbellek.klasor_id_getir(anahtar) if self.onbellek else None
            if onbellekli:
                ust_id = onbellekli
                continue

            ust_id = self.klasor_bul_veya_olustur(parca, ust_id)
            if self.onbellek:
                self.onbellek.klasor_id_yaz(anahtar, ust_id)
        return ust_id

    # --- Dosyalar ---------------------------------------------------------

    def dosya_bul(self, ad: str, ust_id: str) -> dict | None:
        sorgu = (
            f"name = '{_tirnak_kacir(ad)}' and '{ust_id}' in parents "
            f"and trashed = false"
        )
        try:
            sonuc = (
                self.servis.files()
                .list(
                    q=sorgu,
                    fields="files(id, name, md5Checksum, size)",
                    pageSize=1,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise _http_hatasini_cevir(exc) from exc
        dosyalar = sonuc.get("files", [])
        return dosyalar[0] if dosyalar else None

    def dosya_yukle(self, yerel_yol: str | Path, ad: str, ust_id: str) -> str:
        """Dosyayi yukler; ayni adli dosya varsa icerigini gunceller.

        Ayni ad tekrar yuklendiginde yeni kopya olusturmak yerine guncelleme
        yapilir - PDF her sayfa eklendiginde yeniden uretildigi icin bu sart.
        """
        yerel_yol = Path(yerel_yol)
        if not yerel_yol.is_file():
            raise DriveHatasi(f"Yüklenecek dosya bulunamadı: {yerel_yol}", gecici=False)

        ortam = MediaFileUpload(
            str(yerel_yol),
            resumable=yerel_yol.stat().st_size > PARCA_BOYUTU,
            chunksize=PARCA_BOYUTU,
        )
        mevcut = self.dosya_bul(ad, ust_id)

        try:
            if mevcut:
                sonuc = (
                    self.servis.files()
                    .update(
                        fileId=mevcut["id"],
                        media_body=ortam,
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            else:
                sonuc = (
                    self.servis.files()
                    .create(
                        body={"name": ad, "parents": [ust_id]},
                        media_body=ortam,
                        fields="id",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
        except HttpError as exc:
            raise _http_hatasini_cevir(exc) from exc
        return sonuc["id"]

    def baglanti_testi(self) -> str:
        """Yetkilendirmenin calistigini dogrular; hesap e-postasini dondurur."""
        try:
            bilgi = self.servis.about().get(fields="user(emailAddress)").execute()
        except HttpError as exc:
            raise _http_hatasini_cevir(exc) from exc
        return bilgi.get("user", {}).get("emailAddress", "")
