@echo off
setlocal
title moodCreator - stop

echo Looking for a moodCreator server on port 4444...

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":4444" ^| findstr "LISTENING"') do (
    echo Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)

if "%FOUND%"=="0" (
    echo Nothing was listening on port 4444.
) else (
    echo Done.
)
echo.
pause