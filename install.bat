@echo off
rem ============================================================
rem  YouTube Shorts Studio - first-time installer (Windows 10/11)
rem  ASCII only: non-ASCII text + chcp 65001 breaks the cmd parser
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   YouTube Shorts Studio - installer
echo ============================================================
echo.

rem ---- 1) locate a supported Python (3.10 / 3.11) -------------
set PY=
for %%C in (py python) do (
  if not defined PY (
    %%C -c "import sys;sys.exit(0 if sys.version_info[:2] in ((3,10),(3,11)) else 1)" >nul 2>&1
    if not errorlevel 1 set PY=%%C
  )
)
if not defined PY (
  echo [ERROR] Python 3.10 or 3.11 was not found.
  echo.
  echo   install it first :  winget install Python.Python.3.11
  echo   note             : Python 3.12+ has no torch 2.5.1+cu118 wheel - unsupported
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set PYVER=%%V
echo [1/7] Python %PYVER% found

rem ---- 2) virtual environment --------------------------------
if not exist "venv\Scripts\python.exe" (
  echo [2/7] creating virtual environment ^(venv^) ...
  %PY% -m venv venv
  if errorlevel 1 (
    echo [ERROR] venv creation failed.
    pause
    exit /b 1
  )
) else (
  echo [2/7] venv already exists - reusing it
)
set VPY=venv\Scripts\python.exe
"%VPY%" -m pip install --upgrade pip setuptools wheel >nul 2>&1

rem ---- 3) torch (CUDA 11.8 build) ----------------------------
echo [3/7] checking torch ...
"%VPY%" -c "import torch" >nul 2>&1
if errorlevel 1 (
  echo       installing torch 2.5.1+cu118 - about 2.5 GB, 10-30 min ...
  "%VPY%" -m pip install torch==2.5.1+cu118 torchvision==0.20.1+cu118 torchaudio==2.5.1+cu118 --index-url https://download.pytorch.org/whl/cu118
  if errorlevel 1 goto :piperr
) else (
  echo       torch already installed - skipping
)

rem ---- 4) requirements --------------------------------------
echo [4/7] installing requirements ...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :piperr

rem ---- 5) ffmpeg (not shipped: downloaded here) --------------
echo [5/7] checking FFmpeg ...
if exist "ffmpeg8\ffmpeg-n8.1-latest-win64-gpl-8.1\bin\ffmpeg.exe" (
  echo       ffmpeg already present
) else (
  "%VPY%" -X utf8 scripts\download_ffmpeg.py
  if errorlevel 1 echo       [WARN] ffmpeg download failed - see README troubleshooting
)

rem ---- 6) GPU + model --------------------------------------
echo [6/7] GPU / image model check ...
"%VPY%" -X utf8 scripts\check_gpu.py
echo.
choice /C YN /N /M "Download the recommended image model now? several GB, 20-60 min [Y/N] "
if errorlevel 2 goto :skipmodel
"%VPY%" -X utf8 scripts\check_gpu.py --download
:skipmodel

rem ---- 7) .env ---------------------------------------------
echo [7/7] .env setup ...
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo       .env created - open it and paste your API keys
) else (
  echo       .env already exists - keeping it
)

echo.
echo ============================================================
echo   Install finished
echo ============================================================
echo   1. edit .env and paste GEMINI_API_KEY   free, 1 minute
echo   2. run start_web.bat                    browser editor opens
echo   3. on failure: run doctor.bat and attach doctor_report.txt
echo.
pause
exit /b 0

:piperr
echo.
echo [ERROR] a pip step failed. Check internet / proxy, then run install.bat again.
pause
exit /b 1
