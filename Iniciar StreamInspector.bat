@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Use an already installed compatible Python, regardless of launcher configuration.
call :try_python py -3.13
if not errorlevel 1 exit /b 0
call :try_python py -3.12
if not errorlevel 1 exit /b 0
call :try_python python
if not errorlevel 1 exit /b 0
call :try_python python3
if not errorlevel 1 exit /b 0

echo [StreamInspector] No se encontro Python 3.12 o superior.
where winget >nul 2>nul
if errorlevel 1 goto :no_python

echo [StreamInspector] Instalando Python 3.12 automaticamente...
winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements --scope user
if errorlevel 1 goto :install_failed

rem Winget may not refresh PATH in this window, so try known locations first.
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" bootstrap.py
    if not errorlevel 1 exit /b 0
)
call :try_python py -3.12
if not errorlevel 1 exit /b 0
call :try_python python
if not errorlevel 1 exit /b 0

echo.
echo Python se instalo, pero Windows aun no ha actualizado PATH.
echo Cierra esta ventana y vuelve a ejecutar este archivo.
pause
exit /b 1

:try_python
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
%* bootstrap.py
exit /b %errorlevel%

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
