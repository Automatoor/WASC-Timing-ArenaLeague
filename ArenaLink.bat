@echo off
title ArenaLink v1.0

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
