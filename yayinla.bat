@echo off
rem Paketlenmis surumu GitHub Releases'e yayimlar.
rem Once paketle.bat calistirilmis olmali (dist\Docvera hazir).
cd /d "%~dp0"
.venv\Scripts\python.exe tools\yayinla.py %*
pause
