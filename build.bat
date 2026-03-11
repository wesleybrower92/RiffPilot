@echo off
echo ============================================
echo   Building Riff Pilot
echo ============================================
echo.

echo [1/2] Building executable with PyInstaller...
python -m PyInstaller --clean --noconfirm RiffPilot.spec
if %ERRORLEVEL% neq 0 (
    echo BUILD FAILED
    pause
    exit /b 1
)

echo.
echo [2/2] Build complete!
echo.
echo Output folder: dist\RiffPilot\
echo Executable:    dist\RiffPilot\RiffPilot.exe
echo.
echo To create an installer, install Inno Setup and compile installer.iss
echo   Download: https://jrsoftware.org/isdl.php
echo.
pause
