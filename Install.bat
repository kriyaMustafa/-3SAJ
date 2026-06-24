@echo off
title AI Video Translator - Installer
color 0A
echo ===================================================
echo       AI Video Translator - First Time Setup
echo ===================================================
echo.
echo Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not in your system PATH!
    echo Please install Python 3.10 or 3.11 from python.org
    echo IMPORTANT: Make sure to check the box "Add Python to PATH" during installation.
    pause
    exit /b
)

echo.
echo Creating an isolated Virtual Environment...
if not exist venv (
    python -m venv venv
)

echo.
echo Installing AI Models and Dependencies...
echo (This will take a few minutes as it downloads PyTorch and heavy models)
call venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ===================================================
echo Installation Complete!
echo You can now double-click Start.bat to run the app.
echo ===================================================
pause
