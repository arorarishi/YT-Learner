@echo off
rem Start script — run from the project root or scripts/ folder
cd /d "%~dp0.."

if not exist .venv (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate

uvicorn app.main:app --host 127.0.0.1 --port 8000
