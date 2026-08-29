@echo off
rem Dagitilabilir .exe uretir -> dist\Docvera\
rem
rem credentials.json varsa pakete GOMULUR. Boylece son kullanici hicbir
rem Google kurulumu yapmaz: "Google Drive'a baglan" -> onayla -> biter.
rem Dosya yoksa uygulama yine calisir, sadece Drive yuklemesi kapali kalir.
cd /d "%~dp0"
setlocal

rem PyInstaller DLL ararken PATH'teki ilgisiz program klasorlerini de tarar.
rem Temiz bir PATH, Poppler gibi araclarin ICU/Qt DLL'lerinin pakete sizmasini
rem ve hedef bilgisayarda Qt ile cakismasini engeller.
set "PATH=%~dp0.venv\Scripts;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem"

if exist "credentials.json" (
    echo [+] credentials.json bulundu, pakete gomulecek.
    .venv\Scripts\python.exe -m PyInstaller --clean --onedir --noconfirm --windowed ^
        --name Docvera --paths . ^
        --icon "app\varliklar\docvera-simge.ico" ^
        --add-data "app\varliklar;app\varliklar" ^
        --add-data "credentials.json;." ^
        app\__main__.py
) else (
    echo [!] credentials.json YOK - Drive baglantisi son kullanicida calismaz.
    echo     Google Cloud Console'dan Masaustu OAuth istemcisi indirip
    echo     bu klasore credentials.json adiyla koyun, sonra tekrar calistirin.
    echo.
    .venv\Scripts\python.exe -m PyInstaller --clean --onedir --noconfirm --windowed ^
        --name Docvera --paths . ^
        --icon "app\varliklar\docvera-simge.ico" ^
        --add-data "app\varliklar;app\varliklar" ^
        app\__main__.py
)

if errorlevel 1 exit /b 1

echo [+] Paket acilis denetimi yapiliyor...
start "" /wait "dist\Docvera\Docvera.exe" --paket-denetle
if errorlevel 1 (
    echo [HATA] Paket Qt/UI acilis denetimini gecemedi. Yayinlamayin.
    exit /b 1
)

echo.
echo Paket hazir: dist\Docvera\Docvera.exe
pause
