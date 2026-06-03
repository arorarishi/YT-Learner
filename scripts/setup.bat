@echo off
rem Setup script — run from the project root or scripts/ folder
cd /d "%~dp0.."

if exist .venv (
    echo Virtual environment already exists, skipping creation.
) else (
    echo Creating virtual environment in .venv...
    python -m venv .venv
)

call .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

echo Setup complete. Run start.bat to start the server.
