@echo off
setlocal

echo ============================================
echo Crustacean Virus Database Stopper
echo ============================================
echo.

set "TARGET_PID="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    set "TARGET_PID=%%a"
    goto :found
)

echo No process is listening on port 8000.
goto :end

:found
echo Found backend PID: %TARGET_PID%
taskkill /PID %TARGET_PID% /F
if errorlevel 1 (
    echo Failed to stop PID %TARGET_PID%.
) else (
    echo Backend stopped.
)

:end
echo.
pause
