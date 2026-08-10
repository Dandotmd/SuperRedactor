@echo off
REM Double-click this file to start SuperRedactor.
REM It sets itself up the first time, then opens your browser.

cd /d "%~dp0"

echo Starting SuperRedactor...
echo.

if not exist .venv (
    echo First run - setting up. This takes a minute and only happens once.
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist .venv (
        echo.
        echo Python 3 is not installed, or is not on your PATH.
        echo Install it from https://www.python.org/downloads/
        echo and tick "Add Python to PATH" during setup, then run this again.
        echo.
        pause
        exit /b 1
    )
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    .venv\Scripts\python -m pip install --quiet -e .
    if errorlevel 1 (
        echo.
        echo Setup could not download what it needs.
        echo If you are on a work network, ask IT for your organisation's
        echo certificate file and see the README section on locked-down computers.
        echo.
        pause
        exit /b 1
    )
    echo Setup finished.
    echo.
)

echo SuperRedactor is running at http://127.0.0.1:8321
echo Leave this window open while you use it.
echo Close it, or press Ctrl-C, when you are done.
echo.

.venv\Scripts\superredactor
pause
