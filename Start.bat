@echo off
title AI Video Translator
color 0B
echo ===================================================
echo   Starting AI Video Translator Server...
echo   Please wait while the system warms up.
echo ===================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] Python environment not found!
    echo You must run Install.bat first before starting the app.
    pause
    exit /b
)

:: Add current folder to PATH in case ffmpeg.exe is dropped in the root folder
set PATH=%CD%;%PATH%

call venv\Scripts\activate.bat
python backend/launcher.py

pause
