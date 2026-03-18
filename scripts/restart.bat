@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "PIDFILE=%PROJECT_DIR%\data\.bot.pid"
set "LOGFILE=%PROJECT_DIR%\data\bot.log"

cd /d "%PROJECT_DIR%"

if "%~1"=="" set "ACTION=restart"
if not "%~1"=="" set "ACTION=%~1"

if "%ACTION%"=="start" goto :start
if "%ACTION%"=="stop" goto :stop
if "%ACTION%"=="restart" goto :restart
echo Usage: %~nx0 {start^|stop^|restart}
exit /b 1

:restart
call :stop
call :start
goto :eof

:stop
echo Stopping bot...

REM Try PID file first
if exist "%PIDFILE%" (
    set /p PID=<"%PIDFILE%"
    tasklist /fi "PID eq !PID!" 2>nul | find "!PID!" >nul 2>&1
    if !errorlevel! equ 0 (
        echo Killing PID !PID!...
        taskkill /PID !PID! /F >nul 2>&1
    ) else (
        echo Stale PID file.
    )
    del /f "%PIDFILE%" >nul 2>&1
    goto :eof
)

REM Fallback: kill by window title or command line
for /f "tokens=2" %%p in ('wmic process where "commandline like '%%src.main%%' and name='python.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo Killing process %%p...
    taskkill /PID %%p /F >nul 2>&1
)
echo Stopped.
goto :eof

:start
if not exist "%PROJECT_DIR%\data" mkdir "%PROJECT_DIR%\data"
echo Starting bot...

REM Unset CLAUDECODE to avoid nested session error
set "CLAUDECODE="

start /b "" cmd /c "poetry run claude-telegram-bot > "%LOGFILE%" 2>&1 & echo !errorlevel!"

REM Get PID of the just-started python process (brief delay for startup)
timeout /t 2 /nobreak >nul
for /f "tokens=2" %%p in ('wmic process where "commandline like '%%src.main%%' and name='python.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo %%p> "%PIDFILE%"
    echo Bot started ^(PID %%p^).
    goto :started
)
echo Bot started. Could not capture PID.
:started
echo Log: %LOGFILE%
goto :eof
