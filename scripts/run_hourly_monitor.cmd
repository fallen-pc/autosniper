@echo off
set ROOT=%~dp0..
set PYTHON=%ROOT%\.venv\Scripts\python.exe
"%PYTHON%" "%ROOT%\scripts\scheduled_jobs.py" --job hourly-monitor
