@echo off
cd /d "%~dp0"
if exist ".venv_local\Scripts\streamlit.exe" (
    call .venv_local\Scripts\activate.bat
) else if exist "venv\Scripts\streamlit.exe" (
    call venv\Scripts\activate.bat
)
echo Starting AutoSniper app (app.py is the real entry point - it builds the sidebar nav)...
streamlit run app.py
pause
