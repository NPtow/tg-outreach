#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=== TG Outreach ==="

# Python venv
if [ ! -d ".venv" ]; then
  echo "Creating Python venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "Installing Python dependencies..."
pip install -q -r requirements.txt

# Frontend deps + build
if [ ! -d "frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  cd frontend && npm install --silent && cd ..
fi

echo "Building frontend..."
cd frontend && npm run build --silent && cd ..

echo ""
echo "Starting → http://localhost:8000"
echo ""

PYTHONPATH="$ROOT" uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
