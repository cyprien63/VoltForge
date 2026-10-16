@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name VoltForge --icon "assets\icons\voltforge.ico" --add-data "assets\icons;assets\icons" main.py
