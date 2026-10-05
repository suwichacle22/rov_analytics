@echo off
rem Run on the PC, after the repo is cloned on the server. Copies what git does not carry
rem (.env.local, screenshots, unsaved drafts, hero art) and then starts everything there.
rem
rem   server\send.cmd user@server                 the repo is in ~/rov_analytics
rem   server\send.cmd user@server /srv/rov        the repo is somewhere else
rem   server\send.cmd user@server again           copy once more, over what the server holds
setlocal
if "%~1"=="" (
  echo Usage: server\send.cmd user@server [folder on the server] [again]
  exit /b 1
)
set "TARGET=%~1"
set "DIR=%~2"
set "AGAIN=%~3"
if /i "%DIR%"=="again" (
  set "DIR="
  set "AGAIN=again"
)
if "%DIR%"=="" set "DIR=rov_analytics"

cd /d "%~dp0.."
if not exist .env.local (
  echo .env.local is not in %CD%. Nothing sent.
  exit /b 1
)

echo Sending .env.local, data\series, data\ref\art and data\ref\crops to %TARGET%:%DIR% ...
tar -cf - --exclude=*.bak .env.local data/series data/ref/art data/ref/crops | ssh %TARGET% "cd '%DIR%' 2>/dev/null && test -d .git || { echo 'No clone of the repo in %DIR% on the server. Clone it there first.'; exit 1; }; if test -e .env.local && test '%AGAIN%' != again; then echo 'The server already has its data. Add the word again to copy over it.'; exit 1; fi; tar -xf - && sh server/up.sh"
if errorlevel 1 (
  echo.
  echo Not finished, see the message above.
  exit /b 1
)
