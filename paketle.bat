@echo off
rem Dagitilabilir .exe uretir -> dist\Docvera\ klasoru
rem
rem OAuth istemci dosyasi (credentials.json) BILEREK dagitilmaz: her kurulum
rem kendi Google projesini kullanir. Boylece kota, sorumluluk ve olasi bir
rem askiya alinma her musteride ayri kalir; tek bir proje uzerinden gidilseydi
rem biri kotayi doldurdugunda herkesin yuklemesi dururdu.
rem Kullanici kendi dosyasini Ayarlar > Google Drive > Dosya sec ile yukler.
rem
rem Ozel bir dagitim icin gomulu istemci isteniyorsa proje kokune
rem credentials.json koymak yeterli; asagidaki dal onu pakete gomer.
cd /d "%~dp0"
setlocal

rem PyInstaller DLL ararken PATH'teki ilgisiz program klasorlerini de tarar.
rem Temiz bir PATH, Poppler gibi araclarin ICU/Qt DLL'lerinin pakete sizmasini
rem ve hedef bilgisayarda Qt ile cakismasini engeller.
set "PATH=%~dp0.venv\Scripts;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem"

if exist "credentials.json" (
    echo [i] credentials.json bulundu - ozel dagitim, pakete gomulecek.
    .venv\Scripts\python.exe -m PyInstaller --clean --onedir --noconfirm --windowed ^
        --name Docvera --paths . ^
        --icon "app\varliklar\docvera-simge.ico" ^
        --add-data "app\varliklar;app\varliklar" ^
        --add-data "credentials.json;." ^
        app\__main__.py
) else (
    echo [i] Standart paket: Drive baglantisini her kullanici kendi kurar.
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
