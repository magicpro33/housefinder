@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================================================
echo   House Finder App (Streamlit) - Install prerequisites
echo ================================================================================
echo.

set "PY="
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
  set "PY=python"
) else (
  where py >nul 2>&1
  if %ERRORLEVEL% equ 0 (
    set "PY=py -3"
  )
)

if not defined PY (
  echo ERROR: Python was not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  pause
  exit /b 1
)

echo Using: %PY%
%PY% --version
echo.

if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
  )
)

echo Upgrading pip ...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo Installing packages from requirements.txt ...
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo ================================================================================
echo   Install complete.
echo ================================================================================
echo.
echo   Start the web app:  run_app.bat
echo   Or run:             .venv\Scripts\streamlit run app.py
echo.
echo   Copy .env.example to .env and add your RENTCAST_API_KEY.
echo.
pause
exit /b 0

:fail
echo ERROR: Install failed.
pause
exit /b 1
