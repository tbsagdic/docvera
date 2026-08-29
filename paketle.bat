@echo off
rem Dagitilabilir .exe uretir -> dist\Docvera\
cd /d "%~dp0"

rem Surum numarasini git commit sayisindan tazele
.venv\Scripts\python.exe tools\surum_yaz.py

.venv\Scripts\python.exe -m PyInstaller --onedir --noconfirm --windowed ^
    --name Docvera --paths . app\__main__.py
echo.
echo Paket hazir: dist\Docvera\Docvera.exe
pause
