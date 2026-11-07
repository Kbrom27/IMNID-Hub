@echo off
setlocal
title Stopping IMNID Hub...

echo ================================================================
echo   Stopping IMNID Hub Service...
echo ================================================================
echo.

tasklist /FI "IMAGENAME eq IMNID-Hub.exe" 2>NUL | find /I /N "IMNID-Hub.exe" >NUL
if "%ERRORLEVEL%"=="0" (
    taskkill /F /IM "IMNID-Hub.exe" /T >nul 2>&1
    echo [SUCCESS] IMNID Hub has been successfully stopped.
) else (
    echo [INFO] IMNID Hub service is not currently running.
)

echo.
timeout /t 3 >nul
exit /b 0
