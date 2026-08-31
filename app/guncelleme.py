"""GitHub Releases uzerinden surum denetimi ve kurulum.

Akis:
    1. Son yayin sorgulanir (GitHub API, anonim).
    2. Yeni surum varsa kullaniciya notlariyla gosterilir.
    3. Kullanici onaylarsa zip indirilir, SHA-256 ile dogrulanir.
    4. Paket uygulamanin *yanina* acilir, uygulama kapanir ve klasorleri yer
       degistiren bagimsiz bir cmd betigi calisir; yeni surum kendiliginden
       acilir.

Calisan .exe kendi klasorunun uzerine yazamaz. Bu yuzden asil degisiklik
uygulamadan bagimsiz bir betikte yapilir. Yer degistirme kopyalama degil `move`
ile yapilir: ayni diskte anlik bir islemdir ve yarim kalmis bir kopyalama
sonucu bozuk kurulum birakmaz. Basarisiz olursa eski klasor geri alinir.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import UYGULAMA_SURUMU, veri_klasoru

log = logging.getLogger(__name__)

DEPO = "tbsagdic/docvera"
API_ADRESI = f"https://api.github.com/repos/{DEPO}/releases/latest"
YAYIN_SAYFASI = f"https://github.com/{DEPO}/releases/latest"
EXE_ADI = "Docvera.exe"

# Kurulum sihirbazinin (tools/docvera.iss) actigi kaldirma kaydi. Guncelleme
# surum numarasini burada da tazeler; AppId ile birebir ayni olmali.
KURULUM_KAYDI = (
    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{7F3A6C21-9E44-4C2B-A6D1-2C5B0E8D4F17}_is1"
)

_KULLANICI_ARACISI = f"Docvera/{UYGULAMA_SURUMU} (+https://github.com/{DEPO})"
_SHA_KALIBI = re.compile(r"sha-?256[^0-9a-fA-F]{0,12}([0-9a-fA-F]{64})", re.IGNORECASE)

# Kurulum betiginin sonucu birakacagi dosya; uygulama acilista okuyup siler
SONUC_DOSYASI = "guncelleme_sonuc.txt"

# Betigin bekleme dongusundeki esikler (bir tik ~1 saniye). Uygulama once
# kendiliginden kapanmali; kapanmazsa betik once nazikce kapanmasini ister,
# sonra zorlar. Bekleyip pes etmek yeterli degildi: uygulama kapanmadan bir
# pencere gosterirse sayac doluyor ve guncelleme yarim kaliyordu.
NAZIK_KAPATMA_TIKI = 3
ZORLA_KAPATMA_TIKI = 15
AZAMI_BEKLEME_TIKI = 60


class GuncellemeHatasi(Exception):
    """Kullaniciya gosterilebilir guncelleme hatasi."""


class GuncellemeIptal(Exception):
    """Kullanici indirmeyi iptal etti."""


@dataclass(frozen=True)
class Yayin:
    """GitHub'daki bir yayinin bu uygulamayi ilgilendiren alanlari."""

    surum: str
    etiket: str
    notlar: str
    indirme_url: str
    dosya_adi: str
    boyut: int
    sayfa_url: str
    sha256: str = ""

    @property
    def boyut_metni(self) -> str:
        if self.boyut <= 0:
            return "boyut bilinmiyor"
        return f"{self.boyut / (1024 * 1024):.1f} MB"


# --- Surum karsilastirma ---------------------------------------------------


def surum_demeti(metin: str) -> tuple[int, ...]:
    """'v1.0.12' -> (1, 0, 12). Sayi bulunamazsa bos demet."""
    return tuple(int(p) for p in re.findall(r"\d+", metin or ""))


def daha_yeni_mi(aday: str, mevcut: str) -> bool:
    """Aday surum mevcuttan yeni mi?

    Farkli uzunluktaki numaralar sifirla tamamlanir: 1.1 > 1.0.9, 1.0 == 1.0.0.
    Ayristirilamayan aday asla yeni sayilmaz; boylece bozuk bir etiket
    kullaniciyi gereksiz bir guncellemeye surukleyemez.
    """
    a = surum_demeti(aday)
    b = surum_demeti(mevcut)
    if not a:
        return False
    uzunluk = max(len(a), len(b))
    a += (0,) * (uzunluk - len(a))
    b += (0,) * (uzunluk - len(b))
    return a > b


# --- GitHub sorgusu --------------------------------------------------------


def _ssl_baglami() -> ssl.SSLContext:
    """Sertifika deposu olan bir SSL baglami.

    Paketlenmis .exe'de sistem deposu her zaman erisilebilir olmayabilir;
    certifi bagimlilik agacinda bulundugu icin varsa o tercih edilir.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # certifi yoksa Windows sertifika deposu kullanilir
        return ssl.create_default_context()


def _paket_sec(varliklar: list[dict]) -> dict | None:
    """Yayina eklenen dosyalardan Windows paketini secer."""
    zipler = [
        v
        for v in varliklar
        if str(v.get("name", "")).lower().endswith(".zip")
        and v.get("browser_download_url")
    ]
    if not zipler:
        return None
    for anahtar in ("win", "windows"):
        for varlik in zipler:
            if anahtar in str(varlik["name"]).lower():
                return varlik
    return zipler[0]


def _sha_bul(varlik: dict, notlar: str) -> str:
    """Beklenen SHA-256 ozeti: once API'nin digest alani, sonra yayin notlari."""
    ozet = str(varlik.get("digest") or "")
    if ozet.lower().startswith("sha256:"):
        aday = ozet.split(":", 1)[1].strip().lower()
        if len(aday) == 64:
            return aday
    eslesme = _SHA_KALIBI.search(notlar or "")
    return eslesme.group(1).lower() if eslesme else ""


def yayini_ayristir(veri: dict) -> Yayin:
    """GitHub API yanitini Yayin nesnesine cevirir."""
    etiket = str(veri.get("tag_name") or veri.get("name") or "").strip()
    if not surum_demeti(etiket):
        raise GuncellemeHatasi("Yayın etiketi okunamadı.")

    notlar = str(veri.get("body") or "").strip()
    # Paketsiz yayin burada hata sayilmaz: eski bir yayinin eki eksik olabilir
    # ve bu, guncel surumde calisan kullaniciyi ilgilendirmez. Eksiklik ancak
    # guncelleme gercekten gerekiyorsa (bkz. guncelleme_var_mi) bildirilir.
    varlik = _paket_sec(list(veri.get("assets") or [])) or {}

    return Yayin(
        surum=".".join(str(p) for p in surum_demeti(etiket)),
        etiket=etiket,
        notlar=notlar,
        indirme_url=str(varlik.get("browser_download_url") or ""),
        dosya_adi=str(varlik.get("name") or "Docvera.zip"),
        boyut=int(varlik.get("size") or 0),
        sayfa_url=str(veri.get("html_url") or YAYIN_SAYFASI),
        sha256=_sha_bul(varlik, notlar),
    )


def son_yayin(zaman_asimi: float = 15.0) -> Yayin:
    """GitHub'daki son yayini dondurur (on surumler haric)."""
    istek = Request(
        API_ADRESI,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _KULLANICI_ARACISI,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(istek, timeout=zaman_asimi, context=_ssl_baglami()) as yanit:
            veri = json.loads(yanit.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise GuncellemeHatasi("Henüz yayımlanmış bir sürüm yok.") from exc
        if exc.code == 403:
            raise GuncellemeHatasi(
                "Güncelleme sunucusunun sorgu sınırına takıldı. Bir süre "
                "sonra tekrar deneyin."
            ) from exc
        raise GuncellemeHatasi(
            f"Güncelleme sunucusu yanıt vermedi (HTTP {exc.code})."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GuncellemeHatasi(f"İnternet bağlantısı kurulamadı: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GuncellemeHatasi(
            "Güncelleme sunucusunun yanıtı çözümlenemedi."
        ) from exc

    return yayini_ayristir(veri)


def guncelleme_var_mi(mevcut: str = UYGULAMA_SURUMU) -> Yayin | None:
    """Yeni surum varsa Yayin, yoksa None. Ag hatalarinda istisna firlatir."""
    yayin = son_yayin()
    if not daha_yeni_mi(yayin.surum, mevcut):
        return None
    if not yayin.indirme_url:
        raise GuncellemeHatasi(
            f"Docvera {yayin.surum} yayımlanmış ama kurulabilir paket (.zip) "
            f"eklenmemiş. Yayın sayfasından elle indirmeniz gerekiyor:\n"
            f"{yayin.sayfa_url}"
        )
    return yayin


# --- Kurulum ortami --------------------------------------------------------


def paketlenmis_mi() -> bool:
    """Uygulama PyInstaller paketinden mi calisiyor?"""
    return bool(getattr(sys, "frozen", False))


def kurulum_klasoru() -> Path | None:
    """Calisan .exe'nin klasoru; kaynaktan calisiliyorsa None."""
    if not paketlenmis_mi():
        return None
    return Path(sys.executable).resolve().parent


def kurulabilir_mi() -> tuple[bool, str]:
    """Otomatik kurulum bu makinede mumkun mu? (uygun_mu, gerekce)

    Yazma izni indirmeden ONCE denetlenir; yuzlerce megabayt indirdikten sonra
    "erisim reddedildi" demek kullanicinin zamanini bosa harcar.
    """
    klasor = kurulum_klasoru()
    if klasor is None:
        return False, (
            "Uygulama kaynak koddan çalışıyor. Otomatik kurulum yalnızca "
            "paketlenmiş sürümde geçerli; kaynağı 'git pull' ile güncelleyin."
        )

    ust = klasor.parent
    deneme = ust / f".docvera_yazma_denemesi_{os.getpid()}"
    try:
        deneme.mkdir()
        deneme.rmdir()
    except OSError:
        return False, (
            f"{ust} klasörüne yazma izni yok. Uygulamayı yazma izniniz olan bir "
            "klasöre taşıyın ya da yöneticinizden kurulumu yapmasını isteyin."
        )
    return True, ""


# --- Indirme ---------------------------------------------------------------


def indirme_klasoru() -> Path:
    klasor = veri_klasoru() / "guncelleme"
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def indir(yayin: Yayin, ilerleme=None, iptal=None) -> Path:
    """Paketi indirir, ozetini dogrular ve zip yolunu dondurur.

    ilerleme(inen_bayt, toplam_bayt) her parcada cagrilir; iptal() True
    dondururse indirme birakilir ve yarim dosya silinir.
    """
    hedef = indirme_klasoru() / yayin.dosya_adi
    gecici = hedef.with_name(hedef.name + ".indiriliyor")
    istek = Request(
        yayin.indirme_url,
        headers={
            "User-Agent": _KULLANICI_ARACISI,
            "Accept": "application/octet-stream",
        },
    )
    ozet = hashlib.sha256()
    inen = 0

    try:
        with urlopen(istek, timeout=30, context=_ssl_baglami()) as yanit:
            toplam = int(yanit.headers.get("Content-Length") or yayin.boyut or 0)
            with open(gecici, "wb") as dosya:
                while True:
                    if iptal is not None and iptal():
                        raise GuncellemeIptal()
                    parca = yanit.read(262_144)
                    if not parca:
                        break
                    dosya.write(parca)
                    ozet.update(parca)
                    inen += len(parca)
                    if ilerleme is not None:
                        ilerleme(inen, toplam)
    except GuncellemeIptal:
        gecici.unlink(missing_ok=True)
        raise
    except (URLError, TimeoutError, OSError) as exc:
        gecici.unlink(missing_ok=True)
        raise GuncellemeHatasi(f"İndirme tamamlanamadı: {exc}") from exc

    if yayin.boyut and inen != yayin.boyut:
        gecici.unlink(missing_ok=True)
        raise GuncellemeHatasi(
            "İndirilen dosya eksik (bağlantı kesilmiş olabilir). Tekrar deneyin."
        )

    if yayin.sha256 and ozet.hexdigest() != yayin.sha256:
        gecici.unlink(missing_ok=True)
        raise GuncellemeHatasi(
            "İndirilen paketin doğrulaması başarısız oldu. Güvenlik gereği "
            "kurulum yapılmadı; bağlantınızı denetleyip tekrar deneyin."
        )

    if not zipfile.is_zipfile(gecici):
        gecici.unlink(missing_ok=True)
        raise GuncellemeHatasi("İndirilen dosya geçerli bir paket değil.")

    hedef.unlink(missing_ok=True)
    gecici.replace(hedef)
    return hedef


# --- Kurulum ---------------------------------------------------------------


def _paket_koku(klasor: Path) -> Path:
    """Acilan pakette Docvera.exe'yi barindiran klasoru bulur."""
    if (klasor / EXE_ADI).is_file():
        return klasor
    girisler = list(klasor.iterdir())
    if len(girisler) == 1 and girisler[0].is_dir():
        alt = girisler[0]
        if (alt / EXE_ADI).is_file():
            return alt
    for aday in klasor.rglob(EXE_ADI):
        return aday.parent
    raise GuncellemeHatasi(f"İndirilen pakette {EXE_ADI} bulunamadı; kurulum yapılmadı.")


BETIK_SABLONU = """@echo off
title Docvera guncelleniyor
setlocal
set "HEDEF={hedef}"
set "YENI={yeni}"
set "PAKET={paket}"
set "YEDEK={yedek}"
set "SONUC={sonuc}"
set "GUNLUK={gunluk}"

echo.
echo   Docvera {surum} kuruluyor, lutfen bekleyin...
echo   Bu pencere kendiliginden kapanacak.
echo.
echo [%date% %time%] {surum} kurulumu basladi >>"%GUNLUK%"

rem Uygulamanin kapanmasini bekle; kapanmazsa betik kendisi kapatir.
rem Once nazik istek (pencereye kapanma mesaji gider, uygulama olagan
rem kapanisini yapar), sonra zorlama.
rem
rem taskkill'e /T VERILMEZ: bu betik uygulamanin cocuk sureci oldugu icin
rem surec agacini oldurmek guncellemenin kendisini oldururdu.
set /a SAYAC=0
:bekle
tasklist /fi "PID eq {pid}" 2>nul | find "{pid}" >nul
if errorlevel 1 goto hazir
set /a SAYAC+=1
if %SAYAC%=={nazik} (
    echo [%date% %time%] kapanma istegi gonderiliyor >>"%GUNLUK%"
    taskkill /pid {pid} >>"%GUNLUK%" 2>&1
)
if %SAYAC%=={zorla} (
    echo [%date% %time%] uygulama kapanmadi, zorla kapatiliyor >>"%GUNLUK%"
    taskkill /f /pid {pid} >>"%GUNLUK%" 2>&1
)
if %SAYAC% gtr {azami} (
    echo HATA Uygulama kapanmadigi icin guncelleme yapilamadi.>"%SONUC%"
    echo [%date% %time%] uygulama kapatilamadi >>"%GUNLUK%"
    goto temizle
)
ping -n 2 127.0.0.1 >nul
goto bekle

:hazir
rem Dosya kilitlerinin birakilmasi icin kisa bir pay
ping -n 3 127.0.0.1 >nul

move "%HEDEF%" "%YEDEK%" >>"%GUNLUK%" 2>&1
if errorlevel 1 (
    echo HATA Eski surum klasoru kilitli oldugu icin degistirilemedi.>"%SONUC%"
    echo [%date% %time%] eski klasor tasinamadi >>"%GUNLUK%"
    goto temizle
)

move "%YENI%" "%HEDEF%" >>"%GUNLUK%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] yeni klasor tasinamadi, geri aliniyor >>"%GUNLUK%"
    move "%YEDEK%" "%HEDEF%" >>"%GUNLUK%" 2>&1
    echo HATA Yeni surum yerine konamadi; onceki surum geri alindi.>"%SONUC%"
    goto temizle
)

rem Kurulum sihirbaziyla kurulduysa kaldirici yeni pakette yoktur; silinirse
rem "Programlar ve Ozellikler" girdisi calismaz hale gelir.
if exist "%YEDEK%\\unins000.exe" (
    copy /y "%YEDEK%\\unins000.*" "%HEDEF%\\" >nul 2>&1
    rem Ayni listede surum numarasi da guncellenmeli; aksi halde kullanici
    rem "Programlar ve Ozellikler"de eski surumu gorur.
    reg query "{kayit}" >nul 2>&1 && (
        reg add "{kayit}" /v DisplayVersion /t REG_SZ /d "{surum}" /f >nul 2>&1
        reg add "{kayit}" /v DisplayName /t REG_SZ /d "Docvera {surum}" /f >nul 2>&1
    )
)

rmdir /s /q "%YEDEK%" 2>nul
echo TAMAM {surum}>"%SONUC%"
echo [%date% %time%] kurulum tamamlandi >>"%GUNLUK%"

:temizle
rmdir /s /q "%PAKET%" 2>nul
rmdir /s /q "%YENI%" 2>nul
if exist "%HEDEF%\\{exe}" start "" "%HEDEF%\\{exe}"
(goto) 2>nul & del "%~f0"
"""


def kur(zip_yolu: str | Path, yayin: Yayin) -> Path:
    """Paketi acar ve yer degistirme betigini baslatir.

    Betik uygulamanin kapanmasini bekler; bu yuzden bu cagridan hemen sonra
    uygulama kapatilmalidir. Betigin yolunu dondurur.
    """
    uygun, gerekce = kurulabilir_mi()
    if not uygun:
        raise GuncellemeHatasi(gerekce)

    hedef = kurulum_klasoru()
    if hedef is None:  # kurulabilir_mi() bunu zaten eler
        raise GuncellemeHatasi("Kurulum klasörü belirlenemedi.")
    ust = hedef.parent
    pid = os.getpid()

    paket = ust / f".docvera_paket_{pid}"
    yedek = ust / f".docvera_yedek_{pid}"
    shutil.rmtree(paket, ignore_errors=True)
    shutil.rmtree(yedek, ignore_errors=True)

    try:
        with zipfile.ZipFile(zip_yolu) as arsiv:
            bozuk = arsiv.testzip()
            if bozuk:
                raise GuncellemeHatasi(f"Paket bozuk görünüyor ({bozuk}).")
            arsiv.extractall(paket)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(paket, ignore_errors=True)
        raise GuncellemeHatasi(f"Paket açılamadı: {exc}") from exc

    try:
        yeni = _paket_koku(paket)
    except GuncellemeHatasi:
        shutil.rmtree(paket, ignore_errors=True)
        raise

    sonuc = veri_klasoru() / SONUC_DOSYASI
    sonuc.unlink(missing_ok=True)

    betik = indirme_klasoru() / f"kur_{pid}.bat"
    betik.write_text(
        BETIK_SABLONU.format(
            hedef=hedef,
            yeni=yeni,
            paket=paket,
            yedek=yedek,
            sonuc=sonuc,
            gunluk=veri_klasoru() / "guncelleme.log",
            kayit=KURULUM_KAYDI,
            surum=yayin.surum,
            pid=pid,
            exe=EXE_ADI,
            nazik=NAZIK_KAPATMA_TIKI,
            zorla=ZORLA_KAPATMA_TIKI,
            azami=AZAMI_BEKLEME_TIKI,
        ),
        encoding="ascii",
        errors="replace",
    )

    _betigi_baslat(betik, ust)
    log.info("Guncelleme betigi baslatildi: %s", betik)
    return betik


def _betigi_baslat(betik: Path, calisma_klasoru: Path) -> None:
    """Betigi uygulamadan bagimsiz bir surec olarak baslatir.

    Betik KENDI KONSOLUNDA calisir. DETACHED_PROCESS ile baslatilirsa cmd'nin
    gecerli bir cikti tanitici olmaz ve betik ilk `echo` satirinda sessizce
    oluyordu; guncelleme de hic yapilmadan yarim kaliyordu. Ayrica kullanici
    uygulama kapandiktan sonra bir seyin surdugunu gormeli - aksi halde
    exe'ye yeniden tiklar ve yer degistirmeyi kilitler.

    Uygulama bir is nesnesi (job object) icinde calistiriliyorsa - bazi
    baslatici, uzaktan yonetim ve kiosk yazilimlari boyle yapar - uygulama
    kapandigi anda cocuk surecler de oldurulur. Bu yuzden once is nesnesinden
    ayrilmayi deneriz; izin verilmiyorsa olagan yolla baslatiriz.
    """
    temel = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    ayril = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)

    son_hata: OSError | None = None
    for ek in (ayril, 0):
        try:
            subprocess.Popen(
                ["cmd", "/c", str(betik)],
                cwd=str(calisma_klasoru),
                creationflags=temel | ek,
                close_fds=True,
            )
        except OSError as exc:  # is nesnesi ayrilmaya izin vermiyor
            son_hata = exc
            continue
        else:
            return

    raise GuncellemeHatasi(f"Kurulum betiği başlatılamadı: {son_hata}")


# --- Kurulum sonrasi geri bildirim -----------------------------------------


def sonucu_al() -> tuple[str, str]:
    """Onceki kurulumun sonucunu okur ve dosyayi siler.

    ("tamam" | "hata" | "", mesaj) dondurur. Sessizce basarisiz olan bir
    kurulum en kotu durumdur: kullanici guncelledigini sanip eski surumde
    calismaya devam eder.
    """
    dosya = veri_klasoru() / SONUC_DOSYASI
    try:
        icerik = dosya.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return "", ""
    dosya.unlink(missing_ok=True)

    if icerik.startswith("TAMAM"):
        surum = icerik[5:].strip()
        return "tamam", f"Docvera {surum} sürümüne güncellendi."
    if icerik.startswith("HATA"):
        return "hata", icerik[4:].strip() or "Güncelleme tamamlanamadı."
    return "", ""


def yarim_kalan_kurulum() -> bool:
    """Betik uretilmis ama sonuc yazilmamissa True doner.

    Bu, kurulum betiginin hic calisamadigi anlamina gelir (surec kisitlamasi,
    virus tarayici, kapatilan oturum...). Kullanici guncellemeyi baslatmis ve
    uygulama kapanmis olur; ertesi acilista hicbir sey soylenmezse
    guncellendigini sanip eski surumde calismaya devam eder.

    Cagirandan sonra kalintilar silinir; yarim is bir dahaki denemeyi
    bozmamali.
    """
    klasor = veri_klasoru() / "guncelleme"
    if not klasor.is_dir():
        return False
    if not any(klasor.glob("kur_*.bat")):
        return False
    eski_dosyalari_temizle()
    return True


def eski_dosyalari_temizle() -> None:
    """Onceki guncellemelerden kalan indirme, betik ve acilmis paketleri siler."""
    klasor = veri_klasoru() / "guncelleme"
    if klasor.is_dir():
        for dosya in klasor.iterdir():
            try:
                if dosya.is_file():
                    dosya.unlink()
                else:
                    shutil.rmtree(dosya, ignore_errors=True)
            except OSError:
                pass

    # Kurulum klasorunun yanina acilmis paket/yedek kalintilari (yuzlerce MB)
    hedef = kurulum_klasoru()
    if hedef is None:
        return
    for kalinti in hedef.parent.glob(".docvera_*"):
        shutil.rmtree(kalinti, ignore_errors=True)
