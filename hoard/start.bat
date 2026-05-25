@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found. Download it from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist config.json (
    echo config.json not found. Copy config.json.example to config.json and edit it.
    pause
    exit /b 1
)

if not exist venv\ (
    echo First run: setting up...
    python -m venv venv
    if errorlevel 1 ( pause & exit /b 1 )
    venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
)

venv\Scripts\python main.py
