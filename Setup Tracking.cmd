@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" track_actuators.py --check
if errorlevel 1 goto :error

echo.
echo Setup complete. Double-click Run Tracking.cmd to begin.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the error above.
pause
exit /b 1
