@echo off
rem ============================================================
rem  YouTube Shorts Studio - diagnostics
rem  Collects environment info into doctor_report.txt
rem  Attach that file to your GitHub issue.
rem  ASCII only: Korean text + chcp 65001 breaks the cmd parser
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set PY=venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo ============================================================
echo   Doctor - collecting diagnostics (up to 1 minute)
echo ============================================================
echo.
"%PY%" -X utf8 scripts\doctor.py
if errorlevel 1 (
  echo.
  echo [WARN] doctor.py reported a problem. Report may be incomplete.
)
echo.
echo Report file: %~dp0doctor_report.txt
echo Attach it to your issue on GitHub.
pause
