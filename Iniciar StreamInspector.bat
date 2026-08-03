@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Find one compatible interpreter and run bootstrap exactly once.
call :is_supported py -3.13
if not errorlevel 1 goto :run_py313
call :is_supported py -3.12
if not errorlevel 1 goto :run_py312
call :is_supported python
if not errorlevel 1 goto :run_python
call :is_supported python3
if not errorlevel 1 goto :run_python3
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" goto :run_known312

echo [StreamInspector] No se encontro Python 3.12 o superior.
where winget >nul 2>nul
if errorlevel 1 goto :no_python

echo [StreamInspector] Instalando Python 3.12 automaticamente...
winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements --scope user
if errorlevel 1 goto :install_failed

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" goto :run_known312
call :is_supported py -3.12
if not errorlevel 1 goto :run_py312
call :is_supported python
if not errorlevel 1 goto :run_python

echo.
echo Python se instalo, pero Windows aun no ha actualizado PATH.
echo Cierra esta ventana y vuelve a ejecutar este archivo.
pause
exit /b 1

:run_py313
py -3.13 bootstrap.py
goto :finish

:run_py312
py -3.12 bootstrap.py
goto :finish

:run_python
python bootstrap.py
goto :finish

:run_python3
python3 bootstrap.py
goto :finish

:run_known312
"%LocalAppData%\Programs\Python\Python312\python.exe" bootstrap.py
goto :finish

:is_supported
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
exit /b %errorlevel%

:finish
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo StreamInspector no pudo iniciarse.
    echo Revisa los mensajes anteriores para identificar el error.
    pause
)
exit /b %APP_EXIT%

:no_python
echo.
echo No se encontro Python compatible ni el instalador winget.
echo Instala Python 3.12 desde python.org marcando Add Python to PATH.
pause
exit /b 1

:install_failed
echo.
echo No se pudo instalar Python automaticamente mediante winget.
echo Revisa la conexion o ejecuta este archivo como administrador.
pause
exit /b 1
