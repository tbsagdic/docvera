; Docvera kurulum sihirbazi (Inno Setup 6)
;
; Uretim: tools/yayinla.py cagirir ->  ISCC.exe /DSURUM=1.0.8 tools\docvera.iss
;
; Kurulum YONETICI YETKISI ISTEMEZ ve %LOCALAPPDATA%\Programs\Docvera altina
; yapilir. Bu bilincli bir tercih: uygulama kendini guncellerken klasorun
; uzerine yazabilmeli. Program Files'a kurulsaydi her guncelleme UAC istoku
; olur, sube bilgisayarlarinda calisan kasiyer yonetici sifresini bilmedigi
; icin guncelleme hic yapilamazdi.

#ifndef SURUM
  #define SURUM "0.0.0"
#endif

#define UYGULAMA "Docvera"
#define YAYINCI "Docvera"
#define ADRES "https://github.com/tbsagdic/docvera"

[Setup]
; AppId sabittir: yeni surum kurulunca ayni kayit uzerine yazilir, Programlar
; listesinde ikinci bir Docvera girdisi olusmaz.
AppId={{7F3A6C21-9E44-4C2B-A6D1-2C5B0E8D4F17}
AppName={#UYGULAMA}
AppVersion={#SURUM}
AppVerName={#UYGULAMA} {#SURUM}
AppPublisher={#YAYINCI}
AppPublisherURL={#ADRES}
AppSupportURL={#ADRES}/issues
AppUpdatesURL={#ADRES}/releases
DefaultDirName={localappdata}\Programs\{#UYGULAMA}
DefaultGroupName={#UYGULAMA}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Docvera-{#SURUM}-kurulum
SetupIconFile=..\app\varliklar\docvera-simge.ico
UninstallDisplayIcon={app}\Docvera.exe
UninstallDisplayName={#UYGULAMA} {#SURUM}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
; Kurulum sirasinda Docvera acikse kapatilmasi istenir; aksi halde dosyalar
; kilitli kalir ve kurulum yeniden baslatma ister.
CloseApplications=yes
RestartApplications=no

; Kod imzalama. tools/yayinla.py, DOCVERA_IMZA ortam degiskeni tanimliysa
; ISCC'yi /DIMZALI ve /Sdocvera=<komut> ile cagirir. Imzasiz paket, Akilli
; Uygulama Denetimi acik Windows 11 makinelerinde "Hata 4551" ile durur:
; sihirbaz kendini %TEMP% klasorune acar, ilke o dosyayi calistirtmaz.
; SignedUninstaller kaldirma dosyasini da imzalar; imzasiz unins000.exe ayni
; ilkeye takilir ve program kaldirilamaz hale gelirdi.
#ifdef IMZALI
SignTool=docvera
SignedUninstaller=yes
#endif

[Languages]
Name: "turkce"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "masaustu"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Ek kısayollar:"

[Files]
Source: "..\dist\Docvera\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#UYGULAMA}"; Filename: "{app}\Docvera.exe"
Name: "{group}\{#UYGULAMA} kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#UYGULAMA}"; Filename: "{app}\Docvera.exe"; Tasks: masaustu

[Run]
Filename: "{app}\Docvera.exe"; Description: "Docvera'yı şimdi başlat"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Uygulamanin kendi guncellemesi sirasinda olusabilecek gecici klasorler
Type: filesandordirs; Name: "{app}\_internal"
