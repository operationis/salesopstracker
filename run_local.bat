@echo off
REM Local run (Windows) — waitress on port 5004.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PORT=5004
if "%PORTAL_BASE_URL%"=="" set PORTAL_BASE_URL=http://127.0.0.1:5004
python -m pip install -r requirements.txt >nul 2>&1
waitress-serve --listen=0.0.0.0:%PORT% --threads=8 wsgi:application
