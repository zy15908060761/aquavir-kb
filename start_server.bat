@echo off
REM ============================================================
REM start_server.bat — Launch AquaVir-KB FastAPI web server (Windows)
REM Usage: start_server.bat [--port PORT] [--host HOST]
REM ============================================================
cd /d "%~dp0"

set PORT=8000
set HOST=0.0.0.0

:parse
if "%~1"=="--port" set PORT=%~2& shift & shift & goto parse
if "%~1"=="--host" set HOST=%~2& shift & shift & goto parse

echo ============================================
echo  AquaVir-KB Web Server
echo -------------------------------------------
echo  Host:     %HOST%
echo  Port:     %PORT%
echo  Database: crustacean_virus_core.db
echo  API Docs: http://localhost:%PORT%/docs
echo  Dashboard: http://localhost:%PORT%/
echo ============================================

python -m uvicorn backend:app --host %HOST% --port %PORT% --workers 1 --log-level info
pause
