#!/usr/bin/env bash
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Ensure portable static bin directory is in PATH if present
if [ -d "$DIR/bin" ]; then
    export PATH="$DIR/bin:$PATH"
fi

if [ ! -d ".venv" ]; then
    echo "Virtual environment .venv not found. Running installer..."
    ./install.sh
fi

source .venv/bin/activate

# Suppress spurious multiprocessing resource_tracker cleanup warnings on shutdown
export PYTHONWARNINGS="ignore:resource_tracker"

# Run dedicated desktop app window mode if requested
if [[ "$*" == *"--app"* ]] || [[ "$*" == *"--desktop"* ]]; then
    exec python3 desktop_launcher.py "$@"
fi

DEFAULT_PORT="${VOICE_HIGHLIGHTER_PORT:-8672}"

echo "=========================================================="
echo " Starting Voice Highlighter Studio"
echo " Adaptive hardware acceleration (NVIDIA / Apple Silicon / CPU)"
echo " Open http://127.0.0.1:$DEFAULT_PORT in your browser"
echo "=========================================================="

# Check if development reload flag was requested (--reload or --dev)
RELOAD_FLAG=""
if [[ "$*" == *"--reload"* ]] || [[ "$*" == *"--dev"* ]]; then
    RELOAD_FLAG="--reload"
fi

exec python3 -m backend.cli serve --host 127.0.0.1 $RELOAD_FLAG "$@"
