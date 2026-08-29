"""Uygulama ayarlari.

Ayarlar %APPDATA%\\Docvera\\config.json dosyasinda tutulur. Dosya yoksa
makul varsayilanlarla olusturulur; eksik alanlar varsayilanla tamamlanir,
boylece surum yukseltmelerinde eski dosya bozulmaz.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

UYGULAMA_ADI = "Docvera"
try:
    from app.surum import SURUM as UYGULAMA_SURUMU
except ImportError:  # surum.py henuz uretilmedi (bkz. tools/surum_yaz.py)
    UYGULAMA_SURUMU = "1.0.0"


def veri_klasoru() -> Path:
    """Ayar, veritabani ve gunluk dosyalarinin tutuldugu klasor."""
    taban = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(taban) / UYGULAMA_ADI


def gecici_klasor() -> Path:
    """Onaylanmamis taramalarin tutuldugu gecici klasor.

    Onaylanmayan sayfa arsive hic yazilmaz; burada olusur ve iptal/kayit
    sonrasi silinir.
    """
    taban = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(taban) / UYGULAMA_ADI / "tmp"


def dil_klasoru() -> Path:
    """Uygulamanin indirdigi Tesseract dil paketlerinin klasoru.

    Program Files altina yazmak yonetici yetkisi ister; dil paketleri bu
    yuzden kullanici klasorunde tutulur ve Tesseract'a --tessdata-dir ile
    gosterilir.
    """
    taban = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(taban) / UYGULAMA_ADI / "tessdata"


@dataclass
class Ayarlar:
    """Uygulama ayarlari."""

    # --- Arsiv ---
    kok_klasor: str = r"C:\DocveraArsiv"
    sube_kodu: str = ""  # bos ise klasor agacinda sube seviyesi olusmaz
    sube_adi: str = ""

    # --- Tarama ---
    varsayilan_dpi: int = 300
    renkli_tara: bool = True
    jpeg_kalite: int = 85
    son_cihaz_id: str = ""

    # --- Google Drive ---
    drive_etkin: bool = False
    drive_kok_klasor_id: str = ""
    drive_kok_adi: str = "DOCVERA ARSIV"
    drive_azami_deneme: int = 8

    # --- Otomatik kimlik okuma (OCR) ---
    otomatik_kimlik_oku: bool = True
    tesseract_yolu: str = ""  # bos ise PATH ve olagan kurulum konumlari denenir
    kurulum_sorma: bool = False  # eksik bilesen uyarisi bir daha gosterilmesin

    # --- Guncelleme ---
    guncelleme_otomatik_denetle: bool = True
    guncelleme_son_denetim: str = ""  # ISO tarih-saat; gunde bir sorgu icin
    guncelleme_atlanan_surum: str = ""  # kullanicinin "atla" dedigi surum

    # --- Diger ---
    pdf_olustur: bool = True

    # Kalici degil: bozuk ayar dosyasi uyarisini UI'a tasir, diske yazilmaz
    okuma_hatasi: str = field(default="", compare=False)

    @classmethod
    def varsayilan_yol(cls) -> Path:
        return veri_klasoru() / "config.json"

    @classmethod
    def yukle(cls, yol: str | Path | None = None) -> "Ayarlar":
        """Ayarlari okur. Dosya yoksa varsayilanlarla doner (dosya yazmaz).

        Bozuk bir dosya uygulamanin acilmasini engellemez ama SESSIZCE de
        gecilmez: gunluge yazilir ve `okuma_hatasi` doldurulur. Aksi halde
        "kok klasoru degistirdim ama uygulama eskisini kullaniyor" gibi
        tespiti cok zor bir durum olusur.
        """
        yol = Path(yol) if yol else cls.varsayilan_yol()
        if not yol.is_file():
            return cls()

        try:
            ham = json.loads(yol.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            log.error("Ayar dosyasi okunamadi (%s): %s", yol, exc)
            varsayilan = cls()
            varsayilan.okuma_hatasi = (
                f"{yol} okunamadı ({exc}). Varsayılan ayarlarla açıldı; "
                "kaydederseniz dosyanın üzerine yazılır."
            )
            return varsayilan

        if not isinstance(ham, dict):
            log.error("Ayar dosyasi beklenen bicimde degil: %s", yol)
            varsayilan = cls()
            varsayilan.okuma_hatasi = f"{yol} beklenen biçimde değil."
            return varsayilan

        gecerli = {f.name for f in fields(cls)}
        bilinmeyen = set(ham) - gecerli
        if bilinmeyen:
            log.warning("Ayar dosyasinda taninmayan alanlar yok sayildi: %s", bilinmeyen)
        return cls(**{k: v for k, v in ham.items() if k in gecerli})

    def kaydet(self, yol: str | Path | None = None) -> Path:
        """Ayarlari diske yazar (once gecici dosyaya, sonra yer degistirerek)."""
        yol = Path(yol) if yol else self.varsayilan_yol()
        yol.parent.mkdir(parents=True, exist_ok=True)
        gecici = yol.with_suffix(".json.tmp")
        veri = {k: v for k, v in asdict(self).items() if k != "okuma_hatasi"}
        gecici.write_text(
            json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        gecici.replace(yol)
        return yol

    def dogrula(self) -> list[str]:
        """Kullaniciya gosterilecek ayar sorunlarini dondurur."""
        sorunlar: list[str] = []
        if self.okuma_hatasi:
            sorunlar.append(self.okuma_hatasi)
        if not self.kok_klasor.strip():
            sorunlar.append("Arsiv kok klasoru bos birakilamaz.")
        if self.varsayilan_dpi not in (100, 150, 200, 300, 400, 600):
            sorunlar.append("Cozunurluk 100, 150, 200, 300, 400 veya 600 DPI olmali.")
        if not 40 <= self.jpeg_kalite <= 100:
            sorunlar.append("JPEG kalitesi 40 ile 100 arasinda olmali.")
        if self.drive_etkin and not self.drive_kok_klasor_id:
            sorunlar.append(
                "Google Drive acik ama kok klasor secilmemis. Ayarlar penceresinden "
                "Drive baglantisini tamamlayin."
            )
        return sorunlar

    @property
    def sube(self) -> str:
        """Klasor agacinda kullanilacak sube adi (bos ise sube seviyesi yok)."""
        return (self.sube_adi or self.sube_kodu).strip()

    @property
    def veritabani_yolu(self) -> Path:
        return veri_klasoru() / "tarama.db"
