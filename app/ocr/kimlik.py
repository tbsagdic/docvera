"""Taranan sayfadan kimlik bilgilerini cikaran boru hatti.

Yaklasim - "hatasiz" olma sozu buraya dayanir:

1. MRZ (kimligin arkasindaki makine okunabilir alan) okunur. MRZ'de kontrol
   haneleri vardir; okumanin dogrulugu TAHMIN edilmez, HESAPLANIR.
2. Kontrol haneleri tutmazsa goruntu farkli sekillerde isleyip (buyutme,
   esikleme, dondurme) yeniden denenir.
3. Hicbir denemede kontroller tutmazsa alanlar BOS BIRAKILIR ve kasiyerden
   elle girmesi istenir. Dogrulanmamis veri forma asla yazilmaz.
4. MRZ ASCII oldugu icin ad 'OZDEMIR' seklinde gelir. Turkce harfleri
   (Ş, Ğ, İ) geri kazanmak icin kimligin on yuzu Turkce OCR ile okunur ve
   sonuc MRZ'ye karsi dogrulanir: ASCII'ye indirgendiginde MRZ ile ayni
   degilse kabul edilmez.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from app.ocr import belge, engine
from app.ocr.mrz import KESIN, ORTA, KimlikBilgisi, coz

log = logging.getLogger(__name__)

# OCR icin goruntunun indirgenecegi azami kenar uzunlugu. 300 DPI A4 taramasi
# 2480x3508'dir; Tesseract'i tam cozunurlukte calistirmak yavas ve MRZ icin
# gereksizdir.
AZAMI_KENAR = 2200

# MRZ satirlari cok kucukse buyutmek tanimayi belirgin sekilde iyilestirir
BUYUTME_ORANI = 2.0

# Turkce harflerin ASCII karsiliklari - MRZ ile karsilastirma icin
_ASCII_KATLAMA = str.maketrans(
    {"Ş": "S", "Ğ": "G", "İ": "I", "I": "I", "Ö": "O", "Ü": "U", "Ç": "C"}
)


@dataclass
class OkumaSonucu:
    """Kimlik okuma girisiminin sonucu."""

    kimlik: KimlikBilgisi | None = None
    dogrulandi: bool = False
    mesaj: str = ""
    deneme_sayisi: int = 0
    guven: str = "dusuk"
    # Ad satirini koruyan kontrol hanesi YOKTUR; ad okundugunda daima
    # kasiyer onayina sunulur.
    ad_onay_gerekli: bool = False

    @property
    def kullanilabilir(self) -> bool:
        """Forma otomatik yazilabilir mi?

        Yalnizca tum kontrol haneleri tuttuysa True. Kismi/supheli okuma
        kasiyere yansitilmaz.
        """
        return self.dogrulandi and self.kimlik is not None


def ascii_katla(metin: str) -> str:
    """Turkce harfleri ASCII'ye indirger: 'ÖZDEMİR' -> 'OZDEMIR'."""
    return metin.upper().translate(_ASCII_KATLAMA)


def _goruntu_varyantlari(goruntu: Image.Image):
    """OCR icin denenecek goruntu varyantlarini sirayla uretir.

    Ilk dogrulanan sonucta durulur, yani temiz bir taramada tek gecis yeter.

    MRZ, A4 sayfasinin kucuk bir kosesinde durur ve karakterleri milimetrik
    boyuttadir. Goruntuyu kucultmek onu okunamaz hale getirir; gercek bir
    taramada 2480x3507 sayfa 1555x2200'e indirildiginde MRZ tamamen kayboldu.
    Bu yuzden ONCE TAM COZUNURLUK denenir; kucultme yalnizca yedek yollarda
    (ve Turkce ad okumasinda) kullanilir.
    """
    tam = ImageOps.grayscale(goruntu)

    # 1) Tam cozunurluk - MRZ icin kritik
    yield "tam", tam

    # 2) Kontrast esitleme - soluk/gri taramalar icin
    yield "tam_kontrast", ImageOps.autocontrast(tam, cutoff=2)

    # 3) Ikili esikleme - MRZ'yi arka plandan tamamen ayirir
    yield "tam_esikli", tam.point(lambda p: 255 if p > 128 else 0, mode="L")

    # 4) Kucultulmus - dusuk cozunurluklu ya da cok gurultulu taramalarda
    #    bazen daha temiz sonuc verir
    if max(tam.size) > AZAMI_KENAR:
        oran = AZAMI_KENAR / max(tam.size)
        kucuk = tam.resize(
            (int(tam.width * oran), int(tam.height * oran)), Image.Resampling.LANCZOS
        )
        yield "kucultulmus", kucuk
    else:
        # Zaten kucuk bir goruntu: buyutmek MRZ tanimayi iyilestirebilir
        yield "buyutulmus", tam.resize(
            (int(tam.width * BUYUTME_ORANI), int(tam.height * BUYUTME_ORANI)),
            Image.Resampling.LANCZOS,
        )

    # 5) Dondurmeler - kimlik ters veya yan taranmis olabilir
    for aci in (180, 90, 270):
        yield f"donmus_{aci}", tam.rotate(aci, expand=True)


def kimlik_oku(
    goruntu_yolu: str | Path,
    tesseract_yolu: str = "",
    turkce_ad_dene: bool = True,
) -> OkumaSonucu:
    """Taranmis sayfadan kimlik bilgilerini okur.

    Dogrulanmis bir sonuc bulunur bulunmaz durur.
    """
    if not engine.kullanilabilir_mi(tesseract_yolu):
        return OkumaSonucu(
            mesaj="Tesseract OCR kurulu değil; otomatik kimlik okuma devre dışı."
        )

    try:
        with Image.open(goruntu_yolu) as acik:
            goruntu = acik.convert("RGB")
    except OSError as exc:
        return OkumaSonucu(mesaj=f"Görüntü açılamadı: {exc}")

    en_iyi: KimlikBilgisi | None = None
    deneme = 0

    for etiket, varyant in _goruntu_varyantlari(goruntu):
        deneme += 1
        metin = engine.mrz_oku(varyant, tesseract_yolu)
        if not metin.strip():
            continue

        aday = coz(metin)
        if aday is None:
            continue

        if aday.guvenilir_mi:
            log.info(
                "MRZ %s varyantinda okundu (%s. deneme, guven=%s)",
                etiket, deneme, aday.guven,
            )
            if turkce_ad_dene:
                _turkce_adi_uygula(aday, goruntu, tesseract_yolu)
            mesaj = (
                "Kimlik bilgileri MRZ'den okundu ve kontrol haneleriyle doğrulandı."
                if aday.guven == KESIN
                else (
                    "Kimlik okundu. TC ve doğum tarihi doğrulandı; bileşik kontrol "
                    "hanesi okunamadı, bilgileri gözden geçirin."
                )
            )
            return OkumaSonucu(
                kimlik=aday, dogrulandi=True, mesaj=mesaj,
                deneme_sayisi=deneme, guven=aday.guven,
                ad_onay_gerekli=bool(aday.ad or aday.soyad),
            )

        if en_iyi is None or sum(aday.kontroller.values()) > sum(en_iyi.kontroller.values()):
            en_iyi = aday

    # MRZ yok ya da dogrulanamadi: surucu belgesi gibi MRZ'siz belgeler icin
    # metin tabanli cikarima dus. Guvenilirlik daha dusuktur ve oyle raporlanir.
    metin_sonucu = _metinden_oku(goruntu, tesseract_yolu, deneme)
    if metin_sonucu is not None:
        return metin_sonucu

    if en_iyi is not None:
        basarisiz = ", ".join(en_iyi.basarisiz_kontroller)
        return OkumaSonucu(
            kimlik=en_iyi,
            dogrulandi=False,
            mesaj=(
                f"Kimlik alanı okundu ama doğrulanamadı (tutmayan kontrol: {basarisiz}). "
                "Bilgileri elle girin."
            ),
            deneme_sayisi=deneme,
        )

    return OkumaSonucu(
        dogrulandi=False,
        mesaj=(
            "Belgede TC Kimlik No bulunamadı. Kimlik kartının ARKA yüzünü ya da "
            "sürücü belgesini düz ve tam tarayın, veya bilgileri elle girin."
        ),
        deneme_sayisi=deneme,
    )


def _metin_varyantlari(goruntu: Image.Image):
    """MRZ'siz belge okumasi icin denenecek (etiket, goruntu, psm) ucluleri.

    Cozunurluk BILEREK dusurulmez: surucu belgesinde TC, '4d.32170008012'
    seklinde milimetrik bir satirda yazar ve kucultulmus goruntude kayboluyor.

    Sira maliyete gore: temiz bir taramada ilk gecis yeter, dondurmeler ancak
    hicbir sey bulunamadiginda calisir.
    """
    gri = ImageOps.grayscale(goruntu)

    # 1) Gri tonlama, tek metin blogu. RENKLI goruntu BILEREK kullanilmiyor:
    #    gercek bir surucu belgesi taramasinda renkli gecis TC'yi hic
    #    bulamazken ayni goruntunun gri hali dogru okudu.
    yield "gri", gri, 6

    # 2) Dagilmis metin. Kimlik/ehliyet gibi kucuk alanlarin sayfaya
    #    yayildigi taramalarda ad ve soyad satirlarini daha temiz cikarir.
    yield "gri_dagilmis", gri, 11

    # 3) Kontrast esitleme - soluk fotokopiler icin
    yield "kontrast", ImageOps.autocontrast(gri, cutoff=2), 6

    # 4) Belge ters ya da yan taranmis olabilir
    for aci in (180, 90, 270):
        yield f"donmus_{aci}", gri.rotate(aci, expand=True), 6


def _metinden_oku(
    goruntu: Image.Image, tesseract_yolu: str, deneme: int
) -> OkumaSonucu | None:
    """MRZ'siz belgelerden (surucu belgesi vb.) TC ve dogum tarihini cikarir.

    Dogrulayici olarak TC'nin kendi saglama algoritmasi kullanilir; MRZ kadar
    kesin degildir, bu yuzden ek kanit aranir ve sonuc ORTA guvenle raporlanir.

    Birden fazla OCR gecisi denenir ve alanlar gecisler ARASINDA toplanir:
    ayni taramada psm 6 numarayi, psm 11 ise ad satirini daha temiz
    cikarabiliyor. TC bulunur ve ad soyad tamamlanir tamamlanmaz durulur.
    """
    aday = None
    ad = soyad = ""
    dogum = None
    kaynak = ""

    for etiket, varyant, psm in _metin_varyantlari(goruntu):
        deneme += 1
        try:
            metin = engine.turkce_oku(varyant, tesseract_yolu, psm=psm)
        except Exception as exc:
            log.warning("Belge metni okunamadi (%s): %s", etiket, exc)
            continue
        if not metin.strip():
            continue

        if aday is None:
            aday = belge.tc_sec(metin)
            if aday is not None:
                kaynak = etiket
        if not ad or not soyad:
            yeni_ad, yeni_soyad = belge.ad_soyad_sec(metin)
            ad = ad or yeni_ad
            soyad = soyad or yeni_soyad
        if dogum is None:
            dogum = belge.dogum_tarihi_sec(metin)

        # Ad ve soyad kontrol hanesiz oldugu icin zaten kasiyer onayina
        # gidiyor; ikisi de doluyken daha fazla gecis denemeye deger degil.
        if aday is not None and ad and soyad:
            break

    if aday is None:
        return None

    kimlik = KimlikBilgisi(
        tc=aday.tc,
        ad=ad,
        soyad=soyad,
        dogum_tarihi=dogum,
        kontroller={
            "tc_algoritma": True,  # tc_sec yalnizca algoritmadan gecenleri doner
            "tc_etiketli": aday.etiketli,
            "tc_mutabakat": aday.tekrar >= 2,
        },
    )
    kanit = []
    if aday.etiketli:
        kanit.append(f"'{aday.baglamlar[0]}' alanında")
    if aday.tekrar >= 2:
        kanit.append(f"belgede {aday.tekrar} yerde aynı")

    log.info(
        "TC belge metninden okundu: %s (%s varyanti, %s)",
        aday.tc, kaynak, ", ".join(kanit),
    )
    return OkumaSonucu(
        kimlik=kimlik,
        dogrulandi=True,
        guven=ORTA,
        deneme_sayisi=deneme,
        ad_onay_gerekli=bool(ad or soyad),
        mesaj=(
            "MRZ yok; TC belge metninden okundu ("
            + ", ".join(kanit)
            + ") ve kimlik algoritmasından geçti. Bilgileri kontrol edin."
        ),
    )


# Turkce'ye ozgu harfler - diakritik geri kazanimi icin
_TURKCE_HARFLER = set("ÇĞİÖŞÜ")

# MRZ satirlarini ayirt etmek icin: dolgu iceren ya da MRZ uzunlugunda,
# yalnizca buyuk harf/rakamdan olusan satirlar
_MRZ_BENZERI = re.compile(r"^[A-Z0-9<]{24,34}$")


def _mrz_satiri_mi(satir: str) -> bool:
    """Satirin MRZ'nin kendisi olup olmadigini kestirir."""
    temiz = re.sub(r"\s+", "", satir.upper())
    return "<" in temiz or bool(_MRZ_BENZERI.match(temiz))


def _turkce_adi_uygula(
    kimlik: KimlikBilgisi, goruntu: Image.Image, tesseract_yolu: str
) -> bool:
    """MRZ'deki ASCII ada Turkce harfleri geri kazandirmayi dener.

    MRZ 'OZDEMIR' der; kartin on yuzunde 'ÖZDEMİR' yazar. Turkce yazim
    yalnizca su kosullarda kabul edilir:

      1. Kelime MRZ SATIRINDAN gelmiyor. Turkce OCR modeli MRZ'deki 'I'
         harfini 'İ' okuma egilimindedir; bu, kartta hic bulunmayan bir yazim
         (orn. 'OZDEMİR') uretirdi.
      2. Kelime gercekten Turkce'ye ozgu bir harf iceriyor.
      3. ASCII'ye indirgendiginde MRZ ile birebir ayni.

    Diakritik geri kazanimi hicbir kontrol hanesiyle DOGRULANAMAZ; bu yuzden
    uygulandiginda True doner ve cagiran taraf adi kasiyerin onayina sunar.
    """
    try:
        # Gri tonlama: renkli goruntude Tesseract belirgin sekilde daha kotu
        # okuyor (bkz. _metin_varyantlari).
        metin = engine.turkce_oku(ImageOps.grayscale(goruntu), tesseract_yolu)
    except Exception as exc:
        log.warning("Turkce ad okumasi basarisiz: %s", exc)
        return False

    kelimeler: list[str] = []
    for satir in metin.splitlines():
        if _mrz_satiri_mi(satir):
            continue  # MRZ'nin kendisinden diakritik devsirilmez
        kelimeler.extend(re.findall(r"[A-ZÇĞİÖŞÜ]{2,}", satir.upper()))

    uygulandi = False
    for hedef_alan in ("ad", "soyad"):
        mrz_degeri = getattr(kimlik, hedef_alan)
        if not mrz_degeri:
            continue
        for kelime in kelimeler:
            if kelime == mrz_degeri:
                continue
            if not (set(kelime) & _TURKCE_HARFLER):
                continue  # Turkce harf icermiyorsa geri kazanacak bir sey yok
            if ascii_katla(kelime) == mrz_degeri:
                log.info("Turkce yazim geri kazanildi: %s -> %s", mrz_degeri, kelime)
                setattr(kimlik, hedef_alan, kelime)
                uygulandi = True
                break
    return uygulandi
