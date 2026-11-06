@echo off
setlocal
cd /d "%~dp0"
title IMNID Hub - Health Information Interoperability Platform

echo ================================================================
echo   Starting IMNID Hub...
echo   Open your browser to: http://localhost:8085
echo ================================================================

if exist "IMNID-Hub.exe" (
    start "" "http://localhost:8085"
    "IMNID-Hub.exe" --no-browser --port 8085
) else (
    start "" "http://localhost:8085"
    python run_hub.py --no-browser --port 8085
)

pause
