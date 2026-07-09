@echo off
REM SalesOps Ticket Tracker -> http://127.0.0.1:5004
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Users\Waheed.Rasool\AppData\Local\Programs\Python\Python313\python.exe" wsgi.py
