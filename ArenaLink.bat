@echo off
title ArenaLink v1.0.3

:: ── Check Python is available ─────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on your PATH.
    echo.
    echo         Download Python 3.10 or higher from:
    echo           https://www.python.org/downloads/
    echo.
    echo         During installation, make sure to tick:
    echo           [x] Add Python to PATH
    echo           [x] tcl/tk and IDLE  ^(required for the ArenaLink interface^)
    echo.
    pause
    exit /b 1
)

:: ── Check tkinter is available (requires tcl/tk to be selected at install) ────
python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python's tkinter module is not available.
    echo.
    echo         This is caused by tkinter not being installed with Python.
    echo         To fix this:
    echo.
    echo           1. Open the Windows Control Panel
    echo           2. Go to Apps, find your Python installation and click Modify
    echo           3. On the Optional Features screen, ensure tcl/tk and IDLE is ticked
    echo           4. Complete the installation, then re-run ArenaLink.bat
    echo.
    echo         Alternatively, re-run the Python installer from:
    echo           https://www.python.org/downloads/
    echo         and tick [x] tcl/tk and IDLE during setup.
    echo.
    pause
    exit /b 1
)

:: ── Setup venv if not present ─────────────────────────────────────────────────
if not exist "%~dp0venv\Scripts\activate.bat" (
    echo [SETUP] Creating virtual environment...
    python -m venv "%~dp0venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo         Is Python installed and on your PATH?
        pause
        exit /b 1
    )
    echo [SETUP] Installing dependencies...
    "%~dp0venv\Scripts\pip" install -r "%~dp0requirements.txt" --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo [SETUP] Setup complete.
)

:: ── Launch app ────────────────────────────────────────────────────────────────
"%~dp0venv\Scripts\python" "%~dp0ArenaLink.py"
