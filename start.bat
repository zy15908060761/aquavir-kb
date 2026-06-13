@echo off
setlocal

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

echo ============================================
echo Crustacean Virus Database Launcher
echo ============================================
echo.
echo [1/3] Switching to app directory...
cd /d "%APP_DIR%"
if errorlevel 1 (
    echo Failed to enter app directory:
    echo   %APP_DIR%
    pause
    exit /b 1
)

echo [2/3] Starting backend...
start "CrustaVirus DB Backend" /min python -m uvicorn backend:app --host 127.0.0.1 --port 8000

echo [3/3] Waiting for server and opening browser...
timeout /t 3 /nobreak >nul

set "URL=http://127.0.0.1:8000/"
set "CHROME_EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"

if exist "%CHROME_EXE%" (
    start "" "%CHROME_EXE%" "%URL%"
) else (
    start "" "%URL%"
)

echo.
echo Server URL: %URL%
echo API Docs : http://127.0.0.1:8000/docs
echo.
echo Use stop.bat to stop the server.
echo.
pause
