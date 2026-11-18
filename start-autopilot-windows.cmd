@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python-Umgebung fehlt. Bitte zuerst den Windows-Abschnitt im README ausfuehren.
  popd
  exit /b 1
)
if not exist "data\autopilot.env" (
  echo Lokale Radar-Zugangsdaten fehlen. Bitte data\autopilot.env einrichten.
  popd
  exit /b 1
)
set "PATH=%CD%\.venv\Scripts;%PATH%"
set "VISIBILITY=%~1"
if not defined VISIBILITY set "VISIBILITY=off"
set "TIKTOK_FLAG="
if /I "%~2"=="inbox" set "TIKTOK_FLAG=--tiktok-inbox"
".venv\Scripts\python.exe" -m vo autopilot --model qwen3-vl:2b --watch --youtube "%VISIBILITY%" %TIKTOK_FLAG% --env-file data/autopilot.env
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
