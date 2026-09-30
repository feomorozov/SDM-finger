@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements-web-local.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -c "import app; print('Web app setup check passed.')"
if errorlevel 1 goto :error

echo.
echo Setup complete. Double-click Run Web App.cmd to launch the app.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the error above.
pause
exit /b 1
