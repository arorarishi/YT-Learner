# start.ps1 — run from the project root or the scripts/ folder
# Starts the FastAPI server. Run .\setup.ps1 first if you haven't already.

Set-StrictMode -Version Latest

$root = Split-Path $PSScriptRoot -Parent
$venvPath = Join-Path $root ".venv"

if (-not (Test-Path $venvPath)) {
    Write-Error "Virtual environment not found. Run .\setup.ps1 first."
    exit 1
}

$python = Join-Path $venvPath "Scripts\python.exe"

Set-Location $root
Write-Host "Starting the FastAPI server..."
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
