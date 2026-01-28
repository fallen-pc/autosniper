@echo off
set ROOT=%~dp0..
set PYTHON=%ROOT%\.venv\Scripts\python.exe
"%PYTHON%" "%ROOT%\scripts\scheduled_jobs.py" --job vic-12h
