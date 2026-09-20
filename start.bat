@echo off
setlocal
cd /d "%~dp0"
title moodCreator

echo ========================================
echo   moodCreator - starting
echo ========================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10 or newer and try again.
    pause
    exit /b 1
)

REM --- Virtual environment ---
if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create venv.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    echo [setup] Installing dependencies...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency install failed.
        pause
        exit /b 1
    )
) else (
    call ".venv\Scripts\activate.bat"
)

REM --- Start server ---
echo.
echo Server starting on http://127.0.0.1:4444
echo Press Ctrl+C to stop.
echo.
python -m uvicorn server:app --host 0.0.0.0 --port 4444
echo.
echo Server stopped.
pause