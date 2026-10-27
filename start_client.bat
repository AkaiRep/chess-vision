@echo off
rem chess-vision client: double-click to run. Installs everything it needs on first start.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if exist ".venv\Scripts\python.exe" goto deps

set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.11+ not found, installing it with winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo Could not install Python automatically. Install it from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo.
    echo Python installed. Close this window and run start_client.bat again.
    pause
    exit /b 0
)

echo Creating virtual environment...
%PY% -m venv .venv || goto fail

:deps
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements-client.txt || goto fail
".venv\Scripts\python.exe" -m client %*
exit /b %errorlevel%

:fail
echo.
echo Setup failed, see the messages above.
pause
exit /b 1
