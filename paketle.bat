@echo off
rem Dagitilabilir .exe uretir -> dist\Docvera\
rem
rem credentials.json varsa pakete GOMULUR. Boylece son kullanici hicbir
rem Google kurulumu yapmaz: "Google Drive'a baglan" -> onayla -> biter.
rem Dosya yoksa uygulama yine calisir, sadece Drive yuklemesi kapali kalir.
cd /d "%~dp0"

if exist "credentials.json" (
    echo [+] credentials.json bulundu, pakete gomulecek.
    .venv\Scripts\python.exe -m PyInstaller --onedir --noconfirm --windowed ^
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
    .venv\Scripts\python.exe -m PyInstaller --onedir --noconfirm --windowed ^
        --name Docvera --paths . ^
        --icon "app\varliklar\docvera-simge.ico" ^
        --add-data "app\varliklar;app\varliklar" ^
        app\__main__.py
)

echo.
echo Paket hazir: dist\Docvera\Docvera.exe
pause
