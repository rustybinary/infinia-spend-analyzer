@echo off
setlocal
title Infinia Spend Analyzer
set "HERE=%~dp0"
set "SUPPORT=%LOCALAPPDATA%\CCSorter"
set "VENV=%SUPPORT%\venv"
set "LOG=%SUPPORT%\install.log"
if not exist "%SUPPORT%" mkdir "%SUPPORT%"
if exist "%VENV%\Scripts\python.exe" goto run

set "PY="
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto setup
python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto setup

echo.
echo Python 3 is not installed.
echo Install it from https://www.python.org/downloads/  (tick "Add python.exe to PATH"),
echo or run in a Command Prompt:  winget install Python.Python.3.12
echo Then double-click this file again.
echo.
pause
exit /b 1

:setup
echo First run: installing components. This takes 1-2 minutes and needs internet.
echo (Only the open-source Python packages are downloaded. Your files are never sent anywhere.)
%PY% -m venv "%VENV%" > "%LOG%" 2>&1
if errorlevel 1 goto fail
"%VENV%\Scripts\python.exe" -m pip install -q flask pdfplumber pandas openpyxl >> "%LOG%" 2>&1
if errorlevel 1 goto fail
goto run

:fail
if exist "%VENV%" rmdir /s /q "%VENV%"
echo.
echo Setup failed. Details are in: %LOG%
echo.
pause
exit /b 1

:run
echo.
echo Infinia Spend Analyzer is running. Your browser will open shortly.
echo Keep this window open while you use it. Closing the browser tab (or this window) stops it.
echo.
"%VENV%\Scripts\python.exe" "%HERE%app.py"
if errorlevel 1 pause
endlocal
