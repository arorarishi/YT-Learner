#!/usr/bin/env bash
# Start script — run from the project root or scripts/ folder
set -e
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source .venv/Scripts/activate

echo "Starting the FastAPI server..."
uvicorn app.main:app --host 127.0.0.1 --port 8000
