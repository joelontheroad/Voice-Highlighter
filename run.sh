#!/usr/bin/env bash
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Virtual environment .venv not found. Creating..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Suppress spurious multiprocessing resource_tracker cleanup warnings on shutdown
export PYTHONWARNINGS="ignore:resource_tracker"

echo "=========================================================="
echo " Starting Voice Highlighter"
echo " Accelerated on NVIDIA RTX A5000 (CUDA)"
echo " Open http://localhost:8000 in your browser"
echo "=========================================================="

# Check if development reload flag was requested (--reload or --dev)
RELOAD_FLAG=""
if [[ "$*" == *"--reload"* ]] || [[ "$*" == *"--dev"* ]]; then
    # When reloading in development mode, restrict file watch to backend/
    # so scratch files and large media outputs don't trigger recursive reloads
    RELOAD_FLAG="--reload --reload-dir backend"
fi

exec python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 $RELOAD_FLAG

