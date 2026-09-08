@echo off
set ROOT=%~dp0..
set LOGDIR=%ROOT%\logs\scheduled
set LOGFILE=%LOGDIR%\repair_ledger_refresh.log

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "%ROOT%"

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set PYTHON=%ROOT%\.venv\Scripts\python.exe
) else if exist "%ROOT%\venv\Scripts\python.exe" (
    set PYTHON=%ROOT%\venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [%date% %time%] START repair-ledger-refresh with "%PYTHON%" >> "%LOGFILE%"
"%PYTHON%" "%ROOT%\scripts\refresh_local_repair_ledgers.py" >> "%LOGFILE%" 2>&1
set ERR=%ERRORLEVEL%
echo [%date% %time%] END repair-ledger-refresh exit=%ERR% >> "%LOGFILE%"
exit /b %ERR%
