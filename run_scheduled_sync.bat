@echo off
setlocal

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"
cd /d "%APP_DIR%"

if not exist "sync_runtime" mkdir "sync_runtime"

python scheduled_sync_runner.py %* >> "sync_runtime\scheduled_sync.log" 2>&1
exit /b %errorlevel%
