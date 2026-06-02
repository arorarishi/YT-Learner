#!/usr/bin/env bash
# Setup script — run from the project root or scripts/ folder
set -e
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    python -m venv .venv
else
    echo "Virtual environment already exists, skipping creation."
fi

source .venv/Scripts/activate

pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete. Run ./start.sh to start the server."
