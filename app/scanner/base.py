"""Tarayici arka ucu arayuzu ve ortak veri yapilari.

UI yalnizca bu arayuzu tanir; WIA'ya ozgu hicbir sey UI katmanina sizmaz.
Boylece ileride farkli bir arka uc (orn. NAPS2 konsol) eklendiginde UI
degismeden calisir.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol


class Kaynak:
    """Tarama kaynagi."""

    CAM = "cam"
    BESLEYICI = "besleyici"


@dataclass(frozen=True)
class TarayiciCihaz:
    """Sistemde bulunan bir tarayici."""

    cihaz_id: str
    ad: str
    uretici: str = ""
    besleyici_var: bool = False
    duplex_var: bool = False

    def __str__(self) -> str:
        return self.ad


@dataclass(frozen=True)
class TaramaAyarlari:
    """Tek bir tarama isleminin parametreleri."""

    dpi: int = 300
    renkli: bool = True
    kaynak: str = Kaynak.CAM
    # Besleyiciden en fazla kac sayfa alinacak (0 = kagit bitene kadar)
    azami_sayfa: int = 0

    def __post_init__(self) -> None:
        if self.dpi not in (100, 150, 200, 300, 400, 600):
            raise ValueError(f"Desteklenmeyen cozunurluk: {self.dpi}")


# Her sayfa tarandiginda cagrilir: (sayfa_sirasi, gecici_dosya_yolu)
SayfaGeriCagirim = Callable[[int, Path], None]


class TarayiciArkaUcu(Protocol):
    """Tarayici arka uclarinin uygulamasi gereken arayuz."""

    def cihazlari_listele(self) -> list[TarayiciCihaz]:
        """Sisteme bagli tarayicilari dondurur. Hicbiri yoksa bos liste."""
        ...

    def tara(
        self,
        cihaz_id: str,
        ayarlar: TaramaAyarlari,
        hedef_klasor: Path,
        geri_cagirim: SayfaGeriCagirim | None = None,
    ) -> list[Path]:
        """Tarar ve olusan gecici JPG dosyalarinin yollarini dondurur.

        Hata durumunda app.scanner.errors.TaramaHatasi firlatir.
        """
        ...
