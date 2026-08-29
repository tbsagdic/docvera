"""Drive yukleme kuyrugu.

Kayit alindiginda dosyalar SQLite'taki kuyruga yazilir; arka plandaki tek
bir is parcacigi kuyrugu bosaltir. Internet kesikse dosyalar kuyrukta bekler,
baglanti gelince kaldigi yerden devam eder. Uygulama kapanip acilsa bile
kuyruk kaybolmaz - durum veritabaninda tutulur.

Qt'ye bagimli degildir; boylece testlerde sahte bir istemciyle dogrudan
calistirilabilir.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
from pathlib import Path
from typing import Callable

from app.db import BEKLIYOR, MANUEL, TAMAM, YUKLENIYOR, Veritabani

log = logging.getLogger(__name__)

# Ustel geri cekilme: 5sn, 30sn, 2dk, 10dk, 1sa (sonrasi 1sa'de sabit)
BEKLEME_SANIYE = (5, 30, 120, 600, 3600)


def bekleme_suresi(deneme: int) -> int:
    """Kacinci denemede ne kadar beklenecegini dondurur."""
    if deneme <= 0:
        return 0
    indeks = min(deneme - 1, len(BEKLEME_SANIYE) - 1)
    return BEKLEME_SANIYE[indeks]


class YuklemeKuyrugu:
    """Kuyrugu arka planda bosaltan is parcacigi."""

    def __init__(
        self,
        vt: Veritabani,
        istemci_uret: Callable[[], object],
        kok_klasor_id: str,
        azami_deneme: int = 8,
        dongu_araligi: float = 5.0,
    ):
        """istemci_uret: cagirildiginda DriveIstemcisi dondurur.

        Istemci tembel uretilir; boylece uygulama Drive'a hic baglanmadan
        acilabilir ve yetkilendirme sorunu acilisi engellemez.
        """
        self.vt = vt
        self.istemci_uret = istemci_uret
        self.kok_klasor_id = kok_klasor_id
        self.azami_deneme = azami_deneme
        self.dongu_araligi = dongu_araligi

        self._istemci = None
        self._dur = threading.Event()
        self._uyandir = threading.Event()
        self._is_parcacigi: threading.Thread | None = None

    # --- Yasam dongusu ----------------------------------------------------

    def basla(self) -> None:
        if self._is_parcacigi and self._is_parcacigi.is_alive():
            return
        self._dur.clear()
        self._is_parcacigi = threading.Thread(
            target=self._dongu, name="drive-yukleme", daemon=True
        )
        self._is_parcacigi.start()

    def durdur(self, zaman_asimi: float = 5.0) -> None:
        self._dur.set()
        self._uyandir.set()
        if self._is_parcacigi:
            self._is_parcacigi.join(timeout=zaman_asimi)

    def tetikle(self) -> None:
        """Yeni dosya eklendiginde beklemeden hemen isle."""
        self._uyandir.set()

    def _dongu(self) -> None:
        while not self._dur.is_set():
            try:
                islenen = self.bir_tur_isle()
            except Exception:
                log.exception("Yukleme dongusunde beklenmeyen hata")
                islenen = 0
            # Is varken hizli devam et, yokken bekle
            if islenen == 0:
                self._uyandir.wait(self.dongu_araligi)
                self._uyandir.clear()

    # --- Isleme -----------------------------------------------------------

    def _istemciyi_al(self):
        if self._istemci is None:
            self._istemci = self.istemci_uret()
        return self._istemci

    def bir_tur_isle(self, azami: int = 5) -> int:
        """Siradaki dosyalari yukler; islenen kayit sayisini dondurur."""
        sirada = self.vt.kuyruk_sirada(sinir=azami)
        if not sirada:
            return 0

        islenen = 0
        for kayit in sirada:
            if self._dur.is_set():
                break
            self._tek_kaydi_isle(kayit)
            islenen += 1
        return islenen

    def _tek_kaydi_isle(self, kayit) -> None:
        kuyruk_id = int(kayit["id"])
        yerel_yol = Path(kayit["yerel_yol"])
        deneme = int(kayit["deneme"])

        # Dosya silinmisse kuyrukta sonsuza dek beklemesin
        if not yerel_yol.is_file():
            self.vt.kuyruk_durum_yaz(
                kuyruk_id, MANUEL, son_hata="Yerel dosya bulunamadi (silinmis olabilir)."
            )
            return

        self.vt.kuyruk_durum_yaz(kuyruk_id, YUKLENIYOR)
        try:
            istemci = self._istemciyi_al()
            parcalar = json.loads(kayit["hedef_parcalar"])
            hedef_id = istemci.yolu_coz(parcalar, self.kok_klasor_id)
            dosya_id = istemci.dosya_yukle(yerel_yol, kayit["dosya_adi"], hedef_id)
        except Exception as exc:
            self._basarisiz(kuyruk_id, deneme, exc)
            return

        self.vt.kuyruk_durum_yaz(kuyruk_id, TAMAM, drive_file_id=dosya_id)
        log.info("Drive'a yuklendi: %s -> %s", kayit["dosya_adi"], dosya_id)

    def _basarisiz(self, kuyruk_id: int, deneme: int, hata: Exception) -> None:
        """Hatayi kaydeder ve gerekiyorsa yeniden denemeyi zamanlar."""
        yeni_deneme = deneme + 1
        mesaj = getattr(hata, "mesaj", str(hata))
        kalici = getattr(hata, "gecici", None) is False

        if kalici or yeni_deneme >= self.azami_deneme:
            # Kalici hata veya deneme hakki bitti: kullanici mudahalesi gerekli
            self.vt.kuyruk_durum_yaz(
                kuyruk_id, MANUEL, son_hata=mesaj, deneme_artir=True
            )
            log.error("Yukleme kalici olarak basarisiz (%s): %s", kuyruk_id, mesaj)
            return

        sonraki = _dt.datetime.now() + _dt.timedelta(seconds=bekleme_suresi(yeni_deneme))
        self.vt.kuyruk_durum_yaz(
            kuyruk_id,
            BEKLIYOR,
            son_hata=mesaj,
            sonraki_deneme=sonraki.isoformat(timespec="seconds"),
            deneme_artir=True,
        )
        log.warning(
            "Yukleme basarisiz (%s), %s saniye sonra yeniden denenecek: %s",
            kuyruk_id,
            bekleme_suresi(yeni_deneme),
            mesaj,
        )
