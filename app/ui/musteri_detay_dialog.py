"""Müşteri detay ekranı: bir müşterinin tüm evrakları tarih tarih.

Geçmiş kayıtlar listesinde klasör yolu okumak yerine "Müşteri bilgisi gör"
denildiğinde bu pencere açılır. Müşterinin her gelişi ayrı bir başlık olur,
altında o gün taranan sayfalar ve birleşik PDF listelenir; bir belgeye
çift tıklamak dosyayı doğrudan açar.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from app.musteri import MusteriKaydi, musteri_kayitlari
from app.storage.writer import META_DOSYASI
from app.ui.kabuk import ac as kabukta_ac
from app.validation import tr_lower

# Ogenin tasidigi dosya/klasor yolu bu rolde saklanir
YOL_ROLU = Qt.ItemDataRole.UserRole

_SAYFA_ADI = re.compile(r"^(\d+)\.jpg$", re.IGNORECASE)
_GECICI_UZANTILAR = {".tmp"}

# Musterinin ilk kaydi: kimlik/musteri formunun tarandigi gelis
ILK_KAYIT_ETIKETI = "Müşteri Formu"


def _boyut_metni(bayt: int) -> str:
    if bayt >= 1 << 20:
        return f"{bayt / (1 << 20):.1f} MB"
    return f"{max(bayt, 0) / 1024:.0f} KB"


def klasor_dosyalari(klasor: Path) -> list[Path]:
    """Kayit klasorundeki evraklari sayfa sirasiyla dondurur.

    meta.json ve yarim kalmis .tmp dosyalari kasiyeri ilgilendirmez.
    """
    if not klasor.is_dir():
        return []

    dosyalar = [
        dosya
        for dosya in klasor.iterdir()
        if dosya.is_file()
        and dosya.name != META_DOSYASI
        and dosya.suffix.lower() not in _GECICI_UZANTILAR
    ]

    def sira(dosya: Path):
        eslesme = _SAYFA_ADI.match(dosya.name)
        # Once 01.jpg, 02.jpg... sayisal sirayla; sonra PDF ve digerleri
        return (0, int(eslesme.group(1)), "") if eslesme else (1, 0, tr_lower(dosya.name))

    return sorted(dosyalar, key=sira)


class MusteriDetayDiyalogu(QDialog):
    """Tek bir musterinin kimlik bilgisi ve evrak gecmisi."""

    def __init__(self, ayarlar, vt, tc: str, parent=None, belge_ekle=None):
        """belge_ekle: verilirse "Yeni belge ekle" dugmesi cikar ve TC ile cagrilir."""
        super().__init__(parent)
        self.ayarlar = ayarlar
        self.vt = vt
        self.tc = tc
        self._belge_ekle = belge_ekle

        self.setWindowTitle("Müşteri Bilgisi")
        self.resize(760, 560)

        self.baslik = QLabel()
        baslik_yazi = self.baslik.font()
        baslik_yazi.setPointSize(baslik_yazi.pointSize() + 3)
        baslik_yazi.setBold(True)
        self.baslik.setFont(baslik_yazi)

        self.ozet = QLabel()
        self.ozet.setStyleSheet("color: #555;")
        self.ozet.setWordWrap(True)

        self.agac = QTreeWidget()
        self.agac.setColumnCount(2)
        self.agac.setHeaderLabels(["Evrak", "Bilgi"])
        self.agac.setRootIsDecorated(True)
        self.agac.itemDoubleClicked.connect(self._ogeyi_ac)
        self.agac.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.agac.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )

        ac_dugmesi = QPushButton("Aç")
        ac_dugmesi.setToolTip("Seçili evrakı veya klasörü açar")
        ac_dugmesi.clicked.connect(lambda: self._ogeyi_ac(self.agac.currentItem()))

        alt = QHBoxLayout()
        alt.addWidget(ac_dugmesi)
        if self._belge_ekle is not None:
            ekle_dugmesi = QPushButton("Bu müşteriye yeni belge ekle")
            ekle_dugmesi.setToolTip(
                "Müşteri bilgilerini forma yükler; taradığınız evrak bugünün "
                "klasörüne eklenir."
            )
            ekle_dugmesi.clicked.connect(self._belge_eklemeye_gec)
            alt.addWidget(ekle_dugmesi)
        alt.addStretch(1)
        # Kapat "reject" doner: cagiran pencere yalnizca "yeni belge ekle"
        # secildiginde (accept) kendini kapatir
        kapat = QPushButton("Kapat")
        kapat.clicked.connect(self.reject)
        alt.addWidget(kapat)

        duzen = QVBoxLayout(self)
        duzen.addWidget(self.baslik)
        duzen.addWidget(self.ozet)
        duzen.addWidget(self.agac, 1)
        duzen.addLayout(alt)

        self.yenile()

    # --- Doldurma ---------------------------------------------------------

    def yenile(self) -> None:
        ad_soyad, dogum = self._kimlik_bilgisi()
        kayitlar = musteri_kayitlari(self.ayarlar.kok_klasor, self.tc, self.vt)

        self.baslik.setText(ad_soyad)
        self.ozet.setText(self._ozet_metni(dogum, kayitlar))
        self._agaci_doldur(kayitlar)

    def _kimlik_bilgisi(self) -> tuple[str, str | None]:
        """(ad soyad, dogum tarihi) - once yerel veritabani, sonra arsiv rehberi.

        Kayit baska bir bilgisayarda alinmis olabilir; o zaman musteri bu
        veritabaninda yoktur ama arsivdeki rehberde vardir.
        """
        musteri = self.vt.musteri_bul(self.tc)
        if musteri is not None:
            return f"{musteri['ad']} {musteri['soyad']}", musteri["dogum_tarihi"]

        from app.storage import rehber

        girdi = rehber.musteri_getir(self.ayarlar.kok_klasor, self.tc) or {}
        ad_soyad = f"{girdi.get('ad', '')} {girdi.get('soyad', '')}".strip()
        return ad_soyad or self.tc, girdi.get("dogum_tarihi")

    def _ozet_metni(self, dogum: str | None, kayitlar: list[MusteriKaydi]) -> str:
        parcalar = [f"TC: {self.tc}"]
        if dogum:
            try:
                gun = _dt.date.fromisoformat(dogum)
                parcalar.append(f"Doğum: {gun.day:02d}.{gun.month:02d}.{gun.year}")
            except ValueError:
                pass
        toplam_sayfa = sum(k.sayfa_sayisi for k in kayitlar)
        parcalar.append(f"{len(kayitlar)} kayıt · {toplam_sayfa} sayfa")
        if kayitlar:
            parcalar.append(
                f"İlk geliş: {kayitlar[0].tarih.strftime('%d.%m.%Y')}"
                f" · Son geliş: {kayitlar[-1].tarih.strftime('%d.%m.%Y')}"
            )
        return "   |   ".join(parcalar)

    def _agaci_doldur(self, kayitlar: list[MusteriKaydi]) -> None:
        self.agac.clear()
        klasor_simgesi = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        dosya_simgesi = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

        if not kayitlar:
            bos = QTreeWidgetItem(["Bu müşteri için kayıt bulunamadı.", ""])
            self.agac.addTopLevelItem(bos)
            return

        # En son geliş en üstte: kasiyer genelde son evraki arar
        for kayit in reversed(kayitlar):
            baslik = kayit.tarih.strftime("%d.%m.%Y")
            if kayit.ilk_mi:
                baslik = f"{baslik}  ({ILK_KAYIT_ETIKETI})"
            if kayit.sube:
                baslik = f"{baslik}  ·  {kayit.sube}"

            ust = QTreeWidgetItem([baslik, f"{kayit.sayfa_sayisi} sayfa"])
            ust.setIcon(0, klasor_simgesi)
            ust.setData(0, YOL_ROLU, str(kayit.klasor))
            if kayit.ilk_mi:
                yazi = ust.font(0)
                yazi.setBold(True)
                ust.setFont(0, yazi)
            self.agac.addTopLevelItem(ust)

            dosyalar = klasor_dosyalari(kayit.klasor)
            if not dosyalar:
                yok = QTreeWidgetItem(["Dosyalar bulunamadı", ""])
                yok.setForeground(0, Qt.GlobalColor.gray)
                ust.addChild(yok)
                continue

            for dosya in dosyalar:
                oge = QTreeWidgetItem(
                    [self._dosya_etiketi(dosya), _boyut_metni(dosya.stat().st_size)]
                )
                oge.setIcon(0, dosya_simgesi)
                oge.setData(0, YOL_ROLU, str(dosya))
                ust.addChild(oge)

            ust.setExpanded(True)

    @staticmethod
    def _dosya_etiketi(dosya: Path) -> str:
        eslesme = _SAYFA_ADI.match(dosya.name)
        if eslesme:
            return f"Sayfa {int(eslesme.group(1))}  ({dosya.name})"
        if dosya.suffix.lower() == ".pdf":
            return f"PDF  ({dosya.name})"
        return dosya.name

    # --- Eylemler ---------------------------------------------------------

    def _ogeyi_ac(self, oge: QTreeWidgetItem | None, sutun: int = 0) -> None:
        if oge is None:
            return
        yol = oge.data(0, YOL_ROLU)
        if yol:
            kabukta_ac(yol, self)

    def _belge_eklemeye_gec(self) -> None:
        if self._belge_ekle is None:
            return
        self._belge_ekle(self.tc)
        self.accept()
