@echo off
chcp 936 >nul
cd /d "%~dp0"
echo ============================================
echo   Tianma - build release exe (one single file)
echo ============================================
echo.
python publish.py
echo.
echo --------------------------------------------
echo   Done. Send  build\Tianma.exe  to friends.
echo --------------------------------------------
pause
