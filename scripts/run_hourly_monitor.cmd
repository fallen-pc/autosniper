@echo off
set ROOT=%~dp0..
set LOGDIR=%ROOT%\logs\scheduled
set LOGFILE=%LOGDIR%\hourly_active_monitor.log

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%ROOT%"

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set PYTHON=%ROOT%\.venv\Scripts\python.exe
) else if exist "%ROOT%\venv\Scripts\python.exe" (
    set PYTHON=%ROOT%\venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [%date% %time%] START hourly-monitor with "%PYTHON%" >> "%LOGFILE%"
"%PYTHON%" "%ROOT%\scripts\scheduled_jobs.py" --job hourly-monitor >> "%LOGFILE%" 2>&1
set ERR=%ERRORLEVEL%
echo [%date% %time%] END hourly-monitor exit=%ERR% >> "%LOGFILE%"
exit /b %ERR%
