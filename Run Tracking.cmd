@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo The local Python environment is missing.
    echo Run Setup Tracking.cmd first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" track_actuators.py
echo.
pause
