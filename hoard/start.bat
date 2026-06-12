@echo off
cd /d "%~dp0"

if not exist config.json (
    echo config.json not found. Copy config.json.example to config.json and edit it.
    pause
    exit /b 1
)

if not exist venv\ (
	where python >nul 2>&1
	if errorlevel 1 (
		echo Python not found. Download it from https://www.python.org/downloads/
		pause
		exit /b 1
	)

	echo Paste here which python.exe you want to use ^(the full python.exe path^):
	set /p pypath=
	echo %pypath%

    echo First run: setting up...
	%pypath% -m venv venv
    if errorlevel 1 ( pause & exit /b 1 )
    venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 ( pause & exit /b 1 )
)

venv\Scripts\python main.py
