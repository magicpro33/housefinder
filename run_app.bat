@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\streamlit.exe (
  call install.bat
)
.venv\Scripts\streamlit.exe run app.py %*
