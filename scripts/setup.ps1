# setup.ps1 — run from the project root or the scripts/ folder
# Creates the virtual environment and installs all dependencies.

Set-StrictMode -Version Latest

$root = Split-Path $PSScriptRoot -Parent
$venvPath = Join-Path $root ".venv"

if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment in .venv..."
    python -m venv $venvPath
} else {
    Write-Host "Virtual environment already exists, skipping creation."
}

$python = Join-Path $venvPath "Scripts\python.exe"

Write-Host "Upgrading pip..."
& $python -m pip install --upgrade pip

Write-Host "Installing dependencies from requirements.txt..."
& $python -m pip install -r (Join-Path $root "requirements.txt")

Write-Host "Setup complete. Run .\start.ps1 to start the server."
