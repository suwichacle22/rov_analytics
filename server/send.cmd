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

rem Saved games and the reference lists travel with git. Anything of them not committed would stay behind.
set "DIRTY=0"
for /f %%i in ('git status --porcelain -- data ^| find /c /v ""') do set "DIRTY=%%i"
if not "%DIRTY%"=="0" (
  echo data\ has %DIRTY% changes that are not committed. Commit and push them, pull on the server, then run this again.
  exit /b 1
)

rem Only the files git ignores are sent, so the clone on the server stays clean for the next git pull.
set "LIST=%TEMP%\rov_send_list.txt"
git -c core.quotepath=off ls-files --others --ignored --exclude-standard -- data/series data/ref > "%LIST%"

echo Sending .env.local, screenshots, unsaved drafts and hero art to %TARGET%:%DIR% ...
tar -cf - --exclude=*.bak -T "%LIST%" .env.local | ssh %TARGET% "cd '%DIR%' 2>/dev/null && test -d .git || { echo 'No clone of the repo in %DIR% on the server. Clone it there first.'; exit 1; }; if test -e .env.local && test '%AGAIN%' != again; then echo 'The server already has its data. Add the word again to copy over it.'; exit 1; fi; tar -xf - && sh server/up.sh"
if errorlevel 1 (
  echo.
  echo Not finished, see the message above.
  exit /b 1
)
