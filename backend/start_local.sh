#!/usr/bin/env bash
set -euo pipefail

# Start the backend uvicorn in the foreground (useful for testing and debugging)
ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT_DIR"
source .venv/bin/activate
echo "Starting uvicorn on 0.0.0.0:8000 (CTRL-C to stop)"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level debug
