@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The local Python environment is missing.
    echo Run Setup Web App.cmd first.
    pause
    exit /b 1
)

set "OPEN_BROWSER=1"
echo Starting Motion Tracker at http://127.0.0.1:8000
echo Press Ctrl+C in this window when you are finished.
echo.
".venv\Scripts\python.exe" app.py
pause
