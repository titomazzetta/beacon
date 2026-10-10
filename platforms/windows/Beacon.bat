@echo off
rem Beacon launcher for Windows 10/11. Double-click to start.
setlocal
cd /d "%~dp0"
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
title Beacon - keep this window open

set "PY=%HERE%\runtime\python-windows\python.exe"
set "OLLAMA=%HERE%\ollama\windows\ollama.exe"
if not exist "%PY%" (
  echo Beacon's Windows files are missing on this drive.
  echo Rebuild the drive without the --no-windows option.
  pause
  exit /b 1
)
if not exist "%OLLAMA%" (
  echo The AI engine for Windows is missing. Rebuild the drive.
  pause
  exit /b 1
)
if not exist "%HERE%\data" mkdir "%HERE%\data"

rem Our own port, so it never clashes with an Ollama already installed on this PC.
set "OLLAMA_HOST=127.0.0.1:11435"
set "OLLAMA_MODELS=%HERE%\models"
set "BEACON_OLLAMA_URL=http://127.0.0.1:11435"
set "BEACON_DATA_ROOT=%HERE%"
set "PYTHONPATH=%HERE%\runtime\site-windows;%HERE%\app"
set "PYTHONNOUSERSITE=1"

echo Starting Beacon...
set "OPID="
curl -s http://127.0.0.1:11435/api/version >nul 2>&1
if errorlevel 1 (
  for /f %%p in ('powershell -NoProfile -Command "(Start-Process -FilePath '%OLLAMA%' -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardError '%HERE%\data\ollama.log' -PassThru).Id"') do set "OPID=%%p"
  for /l %%i in (1,1,60) do (
    curl -s http://127.0.0.1:11435/api/version >nul 2>&1 && goto :up
    timeout /t 1 /nobreak >nul
  )
)
:up
"%PY%" -m beacon
if defined OPID taskkill /pid %OPID% /f >nul 2>&1
endlocal
