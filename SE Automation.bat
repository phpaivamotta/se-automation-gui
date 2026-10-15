@echo off
rem Starts SE Automation. The first run sets up a private Python environment in
rem %LOCALAPPDATA%\SE Automation\venv (needs Python 3.9+ installed). Later runs start right away.
setlocal EnableExtensions
title SE Automation
set "APP_DIR=%~dp0"
set "VENV=%LOCALAPPDATA%\SE Automation\venv"
set "REQ=%APP_DIR%se_automation\requirements.txt"
set "STAMP=%VENV%\installed-requirements.txt"

rem Rebuild the environment if it's missing or its Python was uninstalled/upgraded.
if exist "%VENV%\Scripts\pythonw.exe" (
    "%VENV%\Scripts\python.exe" -c "import tkinter" >nul 2>&1
    if not errorlevel 1 goto :check_requirements
    echo The Python used by SE Automation changed - setting it up again...
    rmdir /s /q "%VENV%"
)

echo Setting up SE Automation for the first time (this takes a minute)...
set "PY="
py -3 -c "import sys, tkinter; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys, tkinter; sys.exit(sys.version_info < (3, 9))" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto :no_python
%PY% -m venv "%VENV%"
if errorlevel 1 goto :failed

:check_requirements
fc /b "%REQ%" "%STAMP%" >nul 2>&1
if not errorlevel 1 goto :launch
echo Installing required packages...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r "%REQ%"
if errorlevel 1 goto :failed
copy /y "%REQ%" "%STAMP%" >nul

:launch
start "" "%VENV%\Scripts\pythonw.exe" "%APP_DIR%se_automation_app.pyw"
exit /b 0

:no_python
echo.
echo Python 3.9 or newer was not found on this computer.
echo Install it from https://www.python.org/downloads/  (tick "Add python.exe to PATH"),
echo then double-click this file again.
echo.
pause
exit /b 1

:failed
echo.
echo Setup failed - see the messages above.
echo If it keeps failing, delete the folder "%LOCALAPPDATA%\SE Automation\venv" and try again.
echo.
pause
exit /b 1
