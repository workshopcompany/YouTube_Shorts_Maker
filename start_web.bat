@echo off
rem YouTube Shorts Web Editor launcher
rem (ASCII only in this file: chcp 65001 + multibyte text breaks cmd's batch parser)
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   YouTube Shorts Web Editor  (browser will open)
echo ============================================================
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -X utf8 webapp.py --open
) else (
    echo [WARN] venv python not found. Using system python instead.
    echo        Local SD image generation requires the venv python.
    echo        First run? Execute install.bat before start_web.bat.
    python -X utf8 webapp.py --open
)
echo.
echo Web editor has stopped.
pause
