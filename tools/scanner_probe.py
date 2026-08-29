"""WIA teshis araci.

Faz 0 dogrulamasi icin: bagli tarayicilari listeler, WIA ozelliklerini doker
ve gercek bir tarama alarak donanim riskini erkenden kapatir.

Kullanim:
    python tools/scanner_probe.py --list
    python tools/scanner_probe.py --props
    python tools/scanner_probe.py --scan cikti.jpg [--dpi 300] [--gri] [--besleyici]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pythoncom
import win32com.client

# --- WIA sabitleri (wiadef.h) ---------------------------------------------
WIA_DEVICE_TYPE_SCANNER = 1

# Cihaz (device) ozellikleri
DPS_HORIZONTAL_BED_SIZE = 3074
DPS_VERTICAL_BED_SIZE = 3075
DPS_DOCUMENT_HANDLING_CAPABILITIES = 3086
DPS_DOCUMENT_HANDLING_STATUS = 3087
DPS_DOCUMENT_HANDLING_SELECT = 3088
DPS_PAGES = 3096
DPS_OPTICAL_XRES = 3090
DPS_OPTICAL_YRES = 3091

# Ogeye (item) ait ozellikler
IPA_DATATYPE = 4103
IPA_DEPTH = 4104
IPA_PIXELS_PER_LINE = 4108
IPA_NUMBER_OF_LINES = 4109
IPS_CUR_INTENT = 6146
IPS_XRES = 6147
IPS_YRES = 6148
IPS_XPOS = 6149
IPS_YPOS = 6150
IPS_XEXTENT = 6151
IPS_YEXTENT = 6152
IPS_BRIGHTNESS = 6154
IPS_CONTRAST = 6155

# DOCUMENT_HANDLING_SELECT degerleri
FEEDER = 0x001
FLATBED = 0x002
DUPLEX = 0x004

# DOCUMENT_HANDLING_CAPABILITIES bayraklari
CAP_FLAGS = {
    0x001: "FEEDER (besleyici)",
    0x002: "FLATBED (cam)",
    0x004: "DUPLEX (cift yuz)",
    0x008: "DETECT_FLATBED",
    0x010: "DETECT_FEEDER",
    0x020: "DETECT_SCAN",
    0x040: "ADVANCED_DUPLEX",
}

# Veri tipleri
DATATYPE_THRESHOLD = 0
DATATYPE_GRAYSCALE = 2
DATATYPE_COLOR = 3

FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"
FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"
FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"


def _props_to_dict(collection) -> dict:
    """WIA Properties koleksiyonunu {PropertyID: (Ad, Deger)} sozlugune cevirir."""
    out = {}
    for prop in collection:
        try:
            value = prop.Value
        except Exception as exc:  # bazi ozellikler okunamaz
            value = f"<okunamadi: {exc}>"
        out[int(prop.PropertyID)] = (str(prop.Name), value)
    return out


def _set_prop(collection, prop_id: int, value) -> bool:
    """Verilen PropertyID'yi ayarlar. Cihaz desteklemiyorsa sessizce False doner."""
    for prop in collection:
        if int(prop.PropertyID) == prop_id:
            try:
                prop.Value = value
                return True
            except Exception as exc:
                print(f"  ! {prop_id} ayarlanamadi ({prop.Name}): {exc}")
                return False
    return False


def scanner_device_infos():
    """Sisteme bagli WIA tarayicilarinin DeviceInfo nesnelerini dondurur."""
    manager = win32com.client.Dispatch("WIA.DeviceManager")
    infos = []
    for info in manager.DeviceInfos:
        if int(info.Type) != WIA_DEVICE_TYPE_SCANNER:
            continue
        infos.append(info)
    return infos


def cmd_list() -> int:
    infos = scanner_device_infos()
    if not infos:
        print("Tarayici bulunamadi.")
        return 1
    print(f"{len(infos)} tarayici bulundu:\n")
    for index, info in enumerate(infos, start=1):
        props = _props_to_dict(info.Properties)
        name = props.get(7, ("", "?"))[1]  # WIA_DIP_DEV_NAME
        desc = props.get(9, ("", ""))[1]  # WIA_DIP_DEV_DESC
        port = props.get(5, ("", ""))[1]  # WIA_DIP_PORT_NAME
        print(f"  [{index}] {name}")
        print(f"      DeviceID : {info.DeviceID}")
        print(f"      Aciklama : {desc}")
        print(f"      Port     : {port}")
        print()
    return 0


def cmd_props(device_index: int) -> int:
    infos = scanner_device_infos()
    if not infos:
        print("Tarayici bulunamadi.")
        return 1
    info = infos[device_index - 1]
    device = info.Connect()

    print("=== CIHAZ OZELLIKLERI ===")
    dev_props = _props_to_dict(device.Properties)
    for pid in sorted(dev_props):
        name, value = dev_props[pid]
        print(f"  {pid:>5}  {name:<38} = {value!r}")

    caps = dev_props.get(DPS_DOCUMENT_HANDLING_CAPABILITIES, (None, 0))[1]
    if isinstance(caps, int):
        aktif = [ad for bayrak, ad in CAP_FLAGS.items() if caps & bayrak]
        print(f"\n  Belge besleme yetenekleri ({caps}): {', '.join(aktif) or 'yok'}")

    print("\n=== TARAMA OGELERI (Items) ===")
    for i, item in enumerate(device.Items, start=1):
        item_props = _props_to_dict(item.Properties)
        ad = item_props.get(4128, ("", f"Item{i}"))[1]
        print(f"\n  --- Item {i}: {ad} ---")
        for pid in sorted(item_props):
            name, value = item_props[pid]
            print(f"    {pid:>5}  {name:<36} = {value!r}")
    return 0


def cmd_scan(hedef: str, device_index: int, dpi: int, gri: bool, besleyici: bool) -> int:
    infos = scanner_device_infos()
    if not infos:
        print("Tarayici bulunamadi.")
        return 1
    info = infos[device_index - 1]
    print(f"Baglaniliyor: {info.DeviceID}")
    device = info.Connect()

    if besleyici:
        ok = _set_prop(device.Properties, DPS_DOCUMENT_HANDLING_SELECT, FEEDER)
        print(f"Kaynak: besleyici (ADF) -> {'ayarlandi' if ok else 'AYARLANAMADI'}")
    else:
        _set_prop(device.Properties, DPS_DOCUMENT_HANDLING_SELECT, FLATBED)

    item = device.Items(1)
    _set_prop(item.Properties, IPS_XRES, dpi)
    _set_prop(item.Properties, IPS_YRES, dpi)
    _set_prop(item.Properties, IPA_DATATYPE, DATATYPE_GRAYSCALE if gri else DATATYPE_COLOR)

    print(f"Taraniyor ({dpi} DPI, {'gri tonlama' if gri else 'renkli'})...")
    image = item.Transfer(FORMAT_JPEG)

    import os

    if os.path.exists(hedef):
        os.remove(hedef)
    image.SaveFile(hedef)
    boyut = os.path.getsize(hedef)
    print(f"OK -> {hedef}  ({boyut:,} bayt, {image.Width}x{image.Height} px)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="WIA tarayici teshis araci")
    parser.add_argument("--list", action="store_true", help="Tarayicilari listele")
    parser.add_argument("--props", action="store_true", help="Tum WIA ozelliklerini dok")
    parser.add_argument("--scan", metavar="DOSYA", help="Tek sayfa tara ve kaydet")
    parser.add_argument("--cihaz", type=int, default=1, help="Cihaz sirasi (varsayilan 1)")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--gri", action="store_true", help="Gri tonlama tara")
    parser.add_argument("--besleyici", action="store_true", help="Besleyiciden (ADF) tara")
    args = parser.parse_args(argv)

    pythoncom.CoInitialize()
    try:
        if args.list:
            return cmd_list()
        if args.props:
            return cmd_props(args.cihaz)
        if args.scan:
            return cmd_scan(args.scan, args.cihaz, args.dpi, args.gri, args.besleyici)
        parser.print_help()
        return 0
    except IndexError:
        print(f"HATA: {args.cihaz}. sirada cihaz yok. --list ile listeyi gorun.")
        return 1
    except Exception as exc:
        # Cevrimdisi cihaz gibi olagan durumlarda traceback yerine anlasilir
        # mesaj goster - bu araci sahada teknik olmayan kisi de calistirabilir.
        from app.scanner.errors import com_hatasini_cevir

        hata = com_hatasini_cevir(exc)
        print(f"HATA: {hata.mesaj}")
        if hata.kod is not None:
            print(f"      (WIA kodu 0x{hata.kod:08X})")
        return 1
    # CoUninitialize bilerek cagrilmiyor: WIA nesneleri surec sonunda serbest
    # birakilirken COM kapaliysa "releasing IUnknown" uyarilari olusuyor.


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
