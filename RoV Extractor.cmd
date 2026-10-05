@echo off
title RoV Draft Extractor
rem The extractor lives in apps\extractor. It finds data\ and .env.local in the repo root on its own.
cd /d "%~dp0apps\extractor"
where uv >nul 2>nul
if %errorlevel%==0 (set UV=uv) else (set UV=python -m uv)
echo Installing or updating dependencies (first run takes a minute)...
%UV% sync --quiet
if errorlevel 1 (
  echo.
  echo Setup failed. Make sure Python 3.12+ and uv are installed.
  pause
  exit /b 1
)
echo Starting the extractor. Close this window to stop it.
%UV% run rov-extract serve --open --lan --reload
pause
