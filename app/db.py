"""SQLite veritabani: musteriler, kayitlar, sayfalar, yukleme kuyrugu, denetim.

Tek dosyalik yerel veritabani. Her sube kendi veritabaniyla bagimsiz calisir;
tum kayitlarda sube_kodu tutuldugu icin ileride merkezi raporlama icin
birlestirilebilir.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import sqlite3
from pathlib import Path

from app.validation import tr_lower

SEMA_SURUMU = 1

_SEMA = """
CREATE TABLE IF NOT EXISTS musteriler (
    id            INTEGER PRIMARY KEY,
    tc            TEXT    NOT NULL UNIQUE,
    ad            TEXT    NOT NULL,
    soyad         TEXT    NOT NULL,
    dogum_tarihi  TEXT,
    -- Turkce'ye duyarli kucuk harfli 'ad soyad'. SQLite'in LIKE'i yalnizca
    -- ASCII'de buyuk/kucuk harf duyarsizdir; 'ö' ile 'Ö' eslesmez. Aramalar
    -- bu yuzden dogrudan ad/soyad uzerinde degil bu sutun uzerinde yapilir.
    arama         TEXT    NOT NULL DEFAULT '',
    olusturma     TEXT    NOT NULL,
    guncelleme    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_musteri_ad ON musteriler (ad, soyad);
CREATE INDEX IF NOT EXISTS ix_musteri_arama ON musteriler (arama);

CREATE TABLE IF NOT EXISTS kayitlar (
    id            INTEGER PRIMARY KEY,
    musteri_id    INTEGER NOT NULL REFERENCES musteriler(id),
    tarih         TEXT    NOT NULL,          -- YYYY-MM-DD
    klasor_yolu   TEXT    NOT NULL,
    goreli_yol    TEXT    NOT NULL,          -- kok klasore gore, Drive ile ortak
    sube_kodu     TEXT    NOT NULL DEFAULT '',
    pdf_adi       TEXT,
    sayfa_sayisi  INTEGER NOT NULL DEFAULT 0,
    olusturma     TEXT    NOT NULL,
    olusturan     TEXT    NOT NULL,
    UNIQUE (musteri_id, tarih, sube_kodu)
);
CREATE INDEX IF NOT EXISTS ix_kayit_tarih ON kayitlar (tarih);

CREATE TABLE IF NOT EXISTS sayfalar (
    id            INTEGER PRIMARY KEY,
    kayit_id      INTEGER NOT NULL REFERENCES kayitlar(id) ON DELETE CASCADE,
    sira          INTEGER NOT NULL,
    dosya_adi     TEXT    NOT NULL,
    bayt          INTEGER NOT NULL DEFAULT 0,
    sha256        TEXT,
    olusturma     TEXT    NOT NULL,
    UNIQUE (kayit_id, sira)
);

CREATE TABLE IF NOT EXISTS yukleme_kuyrugu (
    id              INTEGER PRIMARY KEY,
    kayit_id        INTEGER REFERENCES kayitlar(id) ON DELETE CASCADE,
    yerel_yol       TEXT    NOT NULL,
    hedef_parcalar  TEXT    NOT NULL,        -- JSON listesi: Drive klasor agaci
    dosya_adi       TEXT    NOT NULL,
    durum           TEXT    NOT NULL DEFAULT 'bekliyor',
    deneme          INTEGER NOT NULL DEFAULT 0,
    son_hata        TEXT,
    sonraki_deneme  TEXT,                    -- ISO zaman; bu ana kadar beklenir
    drive_file_id   TEXT,
    olusturma       TEXT    NOT NULL,
    guncelleme      TEXT    NOT NULL,
    UNIQUE (yerel_yol)
);
CREATE INDEX IF NOT EXISTS ix_kuyruk_durum ON yukleme_kuyrugu (durum, sonraki_deneme);

CREATE TABLE IF NOT EXISTS drive_klasor_cache (
    yol_anahtari  TEXT PRIMARY KEY,          -- 'MERKEZ/2026/01.2026/02.01.26'
    drive_id      TEXT NOT NULL,
    olusturma     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS denetim_kaydi (
    id         INTEGER PRIMARY KEY,
    zaman      TEXT NOT NULL,
    kullanici  TEXT NOT NULL,
    eylem      TEXT NOT NULL,
    kayit_id   INTEGER,
    ayrinti    TEXT
);
CREATE INDEX IF NOT EXISTS ix_denetim_zaman ON denetim_kaydi (zaman);
"""

# Kuyruk durumlari
BEKLIYOR = "bekliyor"
YUKLENIYOR = "yukleniyor"
TAMAM = "tamam"
MANUEL = "manuel"  # azami deneme asildi, kullanici mudahalesi gerekli


def _simdi() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class Veritabani:
    """SQLite baglantisini ve sorgulari kapsuller."""

    def __init__(self, yol: str | Path):
        self.yol = Path(yol)
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        self.baglanti = sqlite3.connect(str(self.yol), check_same_thread=False)
        self.baglanti.row_factory = sqlite3.Row
        # WAL, arka plandaki yukleme worker'i ile UI'in ayni anda yazmasini saglar
        self.baglanti.execute("PRAGMA journal_mode = WAL")
        self.baglanti.execute("PRAGMA foreign_keys = ON")
        self.baglanti.execute("PRAGMA busy_timeout = 5000")
        self._sema_kur()

    def _sema_kur(self) -> None:
        self.baglanti.executescript(_SEMA)
        self.baglanti.execute(
            "CREATE TABLE IF NOT EXISTS sema_bilgi (surum INTEGER NOT NULL)"
        )
        satir = self.baglanti.execute("SELECT surum FROM sema_bilgi").fetchone()
        if satir is None:
            self.baglanti.execute("INSERT INTO sema_bilgi (surum) VALUES (?)", (SEMA_SURUMU,))
        self.baglanti.commit()

    def kapat(self) -> None:
        self.baglanti.close()

    # --- Musteriler -------------------------------------------------------

    def musteri_kaydet(
        self, tc: str, ad: str, soyad: str, dogum_tarihi: str | None = None
    ) -> int:
        """Musteriyi ekler veya bilgilerini gunceller; musteri id'sini dondurur."""
        simdi = _simdi()
        arama = tr_lower(f"{ad} {soyad}")
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO musteriler
                    (tc, ad, soyad, dogum_tarihi, arama, olusturma, guncelleme)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tc) DO UPDATE SET
                    ad = excluded.ad,
                    soyad = excluded.soyad,
                    dogum_tarihi = COALESCE(excluded.dogum_tarihi, musteriler.dogum_tarihi),
                    arama = excluded.arama,
                    guncelleme = excluded.guncelleme
                """,
                (tc, ad, soyad, dogum_tarihi, arama, simdi, simdi),
            )
        satir = self.baglanti.execute(
            "SELECT id FROM musteriler WHERE tc = ?", (tc,)
        ).fetchone()
        return int(satir["id"])

    def musteri_bul(self, tc: str) -> sqlite3.Row | None:
        return self.baglanti.execute(
            "SELECT * FROM musteriler WHERE tc = ?", (tc,)
        ).fetchone()

    def musteri_listesi(self, sinir: int = 1000) -> list[sqlite3.Row]:
        """Kayitli musterileri kayit sayisi ve tarih ozetiyle dondurur.

        Hizli musteri secme listesi bunu kullanir: musteri basina tek satir
        gelir, ayni musteri kac kez geldiyse 'kayit_sayisi'nda gorunur.
        """
        return self.baglanti.execute(
            """
            SELECT m.tc, m.ad, m.soyad, m.dogum_tarihi,
                   COUNT(k.id)  AS kayit_sayisi,
                   MIN(k.tarih) AS ilk_kayit,
                   MAX(k.tarih) AS son_kayit
            FROM musteriler m
            LEFT JOIN kayitlar k ON k.musteri_id = m.id
            GROUP BY m.id
            ORDER BY son_kayit DESC, m.guncelleme DESC
            LIMIT ?
            """,
            (sinir,),
        ).fetchall()

    def musteri_gecmisi(self, tc: str, sinir: int = 20) -> list[sqlite3.Row]:
        """Musterinin onceki kayitlarini yeniden eskiye dondurur."""
        return self.baglanti.execute(
            """
            SELECT k.* FROM kayitlar k
            JOIN musteriler m ON m.id = k.musteri_id
            WHERE m.tc = ?
            ORDER BY k.tarih DESC, k.id DESC
            LIMIT ?
            """,
            (tc, sinir),
        ).fetchall()

    def ara(self, metin: str, sinir: int = 100) -> list[sqlite3.Row]:
        """TC veya ad/soyad ile kayit arar.

        Ad aramasi Turkce'ye duyarli kucuk harfe cevrilmis 'arama' sutunu
        uzerinden yapilir; boylece 'özdem' yazan kasiyer 'ÖZDEMİR' kaydini
        bulur (SQLite'in LIKE'i bunu tek basina yapamaz).
        """
        metin = metin.strip()
        desen_ad = f"%{tr_lower(metin)}%"
        desen_tc = f"%{metin}%"
        return self.baglanti.execute(
            """
            SELECT k.*, m.tc, m.ad, m.soyad
            FROM kayitlar k JOIN musteriler m ON m.id = k.musteri_id
            WHERE m.arama LIKE ? OR m.tc LIKE ?
            ORDER BY k.tarih DESC, k.id DESC
            LIMIT ?
            """,
            (desen_ad, desen_tc, sinir),
        ).fetchall()

    def son_kayitlar(self, sinir: int = 100) -> list[sqlite3.Row]:
        """Arama kutusu bosken gosterilen en son kayitlar."""
        return self.baglanti.execute(
            """
            SELECT k.*, m.tc, m.ad, m.soyad
            FROM kayitlar k JOIN musteriler m ON m.id = k.musteri_id
            ORDER BY k.tarih DESC, k.id DESC
            LIMIT ?
            """,
            (sinir,),
        ).fetchall()

    # --- Kayitlar ---------------------------------------------------------

    def kayit_ac(
        self,
        musteri_id: int,
        tarih: _dt.date,
        klasor_yolu: str,
        goreli_yol: str,
        sube_kodu: str,
        pdf_adi: str | None,
    ) -> int:
        """Kaydi olusturur; ayni musteri/gun/sube icin varsa mevcut id'yi doner.

        Ayni musteri ayni gun tekrar geldiginde yeni klasor acilmaz, sayfalar
        mevcut kayda eklenir.
        """
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO kayitlar
                    (musteri_id, tarih, klasor_yolu, goreli_yol, sube_kodu, pdf_adi,
                     olusturma, olusturan)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(musteri_id, tarih, sube_kodu) DO UPDATE SET
                    pdf_adi = excluded.pdf_adi
                """,
                (
                    musteri_id,
                    tarih.isoformat(),
                    klasor_yolu,
                    goreli_yol,
                    sube_kodu,
                    pdf_adi,
                    _simdi(),
                    getpass.getuser(),
                ),
            )
        satir = self.baglanti.execute(
            "SELECT id FROM kayitlar WHERE musteri_id = ? AND tarih = ? AND sube_kodu = ?",
            (musteri_id, tarih.isoformat(), sube_kodu),
        ).fetchone()
        return int(satir["id"])

    def sayfa_ekle(
        self, kayit_id: int, sira: int, dosya_adi: str, bayt: int, sha256: str
    ) -> None:
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO sayfalar (kayit_id, sira, dosya_adi, bayt, sha256, olusturma)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kayit_id, sira) DO UPDATE SET
                    dosya_adi = excluded.dosya_adi,
                    bayt = excluded.bayt,
                    sha256 = excluded.sha256
                """,
                (kayit_id, sira, dosya_adi, bayt, sha256, _simdi()),
            )
            self.baglanti.execute(
                """
                UPDATE kayitlar
                SET sayfa_sayisi = (SELECT COUNT(*) FROM sayfalar WHERE kayit_id = ?)
                WHERE id = ?
                """,
                (kayit_id, kayit_id),
            )

    def kayit_getir(self, kayit_id: int) -> sqlite3.Row | None:
        return self.baglanti.execute(
            "SELECT * FROM kayitlar WHERE id = ?", (kayit_id,)
        ).fetchone()

    # --- Yukleme kuyrugu --------------------------------------------------

    def kuyruga_ekle(
        self, kayit_id: int, yerel_yol: str, hedef_parcalar: list[str], dosya_adi: str
    ) -> None:
        """Dosyayi Drive yukleme kuyruguna alir.

        Ayni yerel yol tekrar eklenirse (PDF her sayfa eklendiginde yeniden
        uretilir) kayit sifirlanir ki guncel dosya yeniden yuklensin.
        """
        simdi = _simdi()
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO yukleme_kuyrugu
                    (kayit_id, yerel_yol, hedef_parcalar, dosya_adi, durum,
                     olusturma, guncelleme)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(yerel_yol) DO UPDATE SET
                    durum = ?,
                    deneme = 0,
                    son_hata = NULL,
                    sonraki_deneme = NULL,
                    guncelleme = ?
                """,
                (
                    kayit_id,
                    yerel_yol,
                    json.dumps(hedef_parcalar, ensure_ascii=False),
                    dosya_adi,
                    BEKLIYOR,
                    simdi,
                    simdi,
                    BEKLIYOR,
                    simdi,
                ),
            )

    def kuyruk_sirada(self, sinir: int = 10) -> list[sqlite3.Row]:
        """Yuklenmeye hazir (bekleme suresi dolmus) kayitlari dondurur."""
        return self.baglanti.execute(
            """
            SELECT * FROM yukleme_kuyrugu
            WHERE durum = ?
              AND (sonraki_deneme IS NULL OR sonraki_deneme <= ?)
            ORDER BY id
            LIMIT ?
            """,
            (BEKLIYOR, _simdi(), sinir),
        ).fetchall()

    def kuyruk_durum_yaz(
        self,
        kuyruk_id: int,
        durum: str,
        son_hata: str | None = None,
        sonraki_deneme: str | None = None,
        deneme_artir: bool = False,
        drive_file_id: str | None = None,
    ) -> None:
        with self.baglanti:
            self.baglanti.execute(
                f"""
                UPDATE yukleme_kuyrugu
                SET durum = ?,
                    son_hata = ?,
                    sonraki_deneme = ?,
                    deneme = deneme + {1 if deneme_artir else 0},
                    drive_file_id = COALESCE(?, drive_file_id),
                    guncelleme = ?
                WHERE id = ?
                """,
                (durum, son_hata, sonraki_deneme, drive_file_id, _simdi(), kuyruk_id),
            )

    def kuyruk_ozeti(self) -> dict[str, int]:
        """Durum -> adet sozlugu; UI durum gostergesi bunu kullanir."""
        satirlar = self.baglanti.execute(
            "SELECT durum, COUNT(*) AS adet FROM yukleme_kuyrugu GROUP BY durum"
        ).fetchall()
        return {satir["durum"]: int(satir["adet"]) for satir in satirlar}

    def kuyruk_sifirla(self, sadece_manuel: bool = True) -> int:
        """Basarisiz kayitlari yeniden denemeye alir; etkilenen satir sayisini doner."""
        kosul = "durum = ?" if sadece_manuel else "durum != ?"
        parametre = MANUEL if sadece_manuel else TAMAM
        with self.baglanti:
            imlec = self.baglanti.execute(
                f"""
                UPDATE yukleme_kuyrugu
                SET durum = ?, deneme = 0, son_hata = NULL, sonraki_deneme = NULL,
                    guncelleme = ?
                WHERE {kosul}
                """,
                (BEKLIYOR, _simdi(), parametre),
            )
            return imlec.rowcount

    # --- Drive klasor onbellegi -------------------------------------------

    def klasor_id_getir(self, yol_anahtari: str) -> str | None:
        satir = self.baglanti.execute(
            "SELECT drive_id FROM drive_klasor_cache WHERE yol_anahtari = ?",
            (yol_anahtari,),
        ).fetchone()
        return satir["drive_id"] if satir else None

    def klasor_id_yaz(self, yol_anahtari: str, drive_id: str) -> None:
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO drive_klasor_cache (yol_anahtari, drive_id, olusturma)
                VALUES (?, ?, ?)
                ON CONFLICT(yol_anahtari) DO UPDATE SET drive_id = excluded.drive_id
                """,
                (yol_anahtari, drive_id, _simdi()),
            )

    def klasor_onbellegi_temizle(self) -> None:
        """Drive kok klasoru degistiginde onbellek gecersiz kalir."""
        with self.baglanti:
            self.baglanti.execute("DELETE FROM drive_klasor_cache")

    # --- Denetim ----------------------------------------------------------

    def denetim_yaz(self, eylem: str, kayit_id: int | None = None, ayrinti: str = "") -> None:
        with self.baglanti:
            self.baglanti.execute(
                """
                INSERT INTO denetim_kaydi (zaman, kullanici, eylem, kayit_id, ayrinti)
                VALUES (?, ?, ?, ?, ?)
                """,
                (_simdi(), getpass.getuser(), eylem, kayit_id, ayrinti),
            )
