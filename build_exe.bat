@echo off
title AI Video Translator - PyInstaller Build Script
color 0A

echo ===================================================
echo     Packaging AI App to .exe using PyInstaller
echo ===================================================

echo.
echo 1. Installing PyInstaller...
call venv\Scripts\activate.bat
pip install pyinstaller auto-py-to-exe

echo.
echo 2. Preparing Frontend Files...
if not exist "backend\dist" mkdir "backend\dist"
xcopy /E /I /Y "frontend\dist\*" "backend\dist\"

echo.
echo 3. Compiling to .exe...
echo WARNING: This process might take 15-30 minutes for a heavy AI app.
echo.

pyinstaller --noconfirm --onedir --windowed --name "AIVideoTranslator" ^
    --icon "app_icon.ico" ^
    --add-data "backend/dist;dist" ^
    --add-data "backend/.env;." ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "sqlalchemy.sql.default_comparator" ^
    --hidden-import "faster_whisper" ^
    --hidden-import "pyannote.audio" ^
    "backend/launcher.py"

echo.
echo ===================================================
echo Build Complete!
echo Your compiled application is inside the "dist/AIVideoTranslator" folder.
echo You can run it by double-clicking "AIVideoTranslator.exe".
echo ===================================================
pause
