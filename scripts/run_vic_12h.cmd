@echo off
set ROOT=%~dp0..
set PYTHON=C:\Users\ewanf\AppData\Local\Programs\Python\Python311\python.exe
"%PYTHON%" "%ROOT%\scripts\scheduled_jobs.py" --job vic-12h
