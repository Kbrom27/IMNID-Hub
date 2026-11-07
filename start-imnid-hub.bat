@echo off
setlocal
cd /d "%~dp0"
title IMNID Hub - Launcher

echo ================================================================
echo   IMNID Hub - Health Information Interoperability Platform
echo ================================================================
echo.

:: Check if IMNID Hub is already running
tasklist /FI "IMAGENAME eq IMNID-Hub.exe" 2>NUL | find /I /N "IMNID-Hub.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    echo [INFO] IMNID Hub is already running.
    echo Opening browser to http://localhost:8085 ...
    start "" "http://localhost:8085"
    timeout /t 3 >nul
    exit /b 0
)

echo Starting IMNID Hub service...

:: Launch executable minimized so user is not blocked by a console window
if exist "IMNID-Hub.exe" (
    start "IMNID Hub Service" /min "%~dp0IMNID-Hub.exe" --port 8085
) else if exist "run_hub.py" (
    start "IMNID Hub Service" /min python run_hub.py --port 8085
) else (
    echo [ERROR] IMNID-Hub.exe was not found in %~dp0
    pause
    exit /b 1
)

echo Waiting for IMNID Hub to initialize...
timeout /t 3 /nobreak >nul

echo Opening browser at http://localhost:8085 ...
start "" "http://localhost:8085"

echo.
echo ================================================================
echo   IMNID Hub service is active!
echo   Web interface: http://localhost:8085
echo   To stop the service, double-click the "Stop IMNID Hub" shortcut.
echo ================================================================
timeout /t 5 >nul
exit /b 0
