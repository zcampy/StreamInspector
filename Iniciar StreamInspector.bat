@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 bootstrap.py
) else (
    python bootstrap.py
)

if not %errorlevel%==0 (
    echo.
    echo StreamInspector no pudo iniciarse.
    echo Comprueba que Python 3.12 o superior este instalado y disponible en PATH.
    pause
)
