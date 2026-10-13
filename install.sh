#!/usr/bin/env bash
# ==============================================================================
# Voice Highlighter Automated Cross-Platform Installer (macOS & Linux)
# ==============================================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo " 🎙️  Voice Highlighter Setup (macOS / Linux)"
echo "=========================================================="

OS="$(uname -s)"
ARCH="$(uname -m)"

echo "[1/4] Detecting operating system: $OS ($ARCH)"

# ------------------------------------------------------------------------------
# 1. Python Check
# ------------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ Error: Python 3 was not found on your system."
    if [ "$OS" = "Darwin" ]; then
        echo "Please install Python 3 via Homebrew ('brew install python') or from https://python.org."
    else
        echo "Please install Python 3 ('sudo apt install python3 python3-venv' on Debian/Ubuntu/Pop!_OS)."
    fi
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "✓ Python $PY_VER detected."

# ------------------------------------------------------------------------------
# 2. FFmpeg Verification & Portable Static Auto-Download
# ------------------------------------------------------------------------------
echo "[2/4] Verifying FFmpeg & FFprobe..."
mkdir -p "$DIR/bin"

HAS_FFMPEG=false
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    HAS_FFMPEG=true
elif [ -x "$DIR/bin/ffmpeg" ] && [ -x "$DIR/bin/ffprobe" ]; then
    HAS_FFMPEG=true
elif [ -x "$DIR/.venv/bin/ffmpeg" ] && [ -x "$DIR/.venv/bin/ffprobe" ]; then
    HAS_FFMPEG=true
fi

if [ "$HAS_FFMPEG" = false ]; then
    echo "FFmpeg not detected in system PATH. Downloading portable static build..."
    if [ "$OS" = "Darwin" ]; then
        # macOS static binary download from Evermeet
        echo "Fetching static FFmpeg for macOS..."
        curl -sL "https://evermeet.cx/ffmpeg/getrelease/zip" -o /tmp/ffmpeg-mac.zip
        curl -sL "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip" -o /tmp/ffprobe-mac.zip
        unzip -q -o /tmp/ffmpeg-mac.zip -d "$DIR/bin/"
        unzip -q -o /tmp/ffprobe-mac.zip -d "$DIR/bin/"
        chmod +x "$DIR/bin/ffmpeg" "$DIR/bin/ffprobe"
        rm -f /tmp/ffmpeg-mac.zip /tmp/ffprobe-mac.zip
        echo "✓ Portable FFmpeg installed to $DIR/bin"
    elif [ "$OS" = "Linux" ] && [ "$ARCH" = "x86_64" ]; then
        # Linux x86_64 static build from John Van Sickle
        echo "Fetching static FFmpeg for Linux x86_64..."
        curl -sL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" -o /tmp/ffmpeg-linux.tar.xz
        mkdir -p /tmp/ffmpeg-static
        tar -xf /tmp/ffmpeg-linux.tar.xz -C /tmp/ffmpeg-static --strip-components=1
        cp /tmp/ffmpeg-static/ffmpeg "$DIR/bin/"
        cp /tmp/ffmpeg-static/ffprobe "$DIR/bin/"
        chmod +x "$DIR/bin/ffmpeg" "$DIR/bin/ffprobe"
        rm -rf /tmp/ffmpeg-linux.tar.xz /tmp/ffmpeg-static
        echo "✓ Portable FFmpeg installed to $DIR/bin"
    else
        echo "⚠️ Note: Please install FFmpeg via your package manager ('brew install ffmpeg' or 'sudo apt install ffmpeg')."
    fi
else
    echo "✓ FFmpeg & FFprobe are available."
fi

# ------------------------------------------------------------------------------
# 3. Virtual Environment & Python Dependencies
# ------------------------------------------------------------------------------
echo "[3/4] Configuring Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip --quiet

echo "Installing Python dependencies (WhisperX, PyTorch, FastAPI, PyWebView)..."
if [ "$OS" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
    # NVIDIA CUDA on Linux
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet || true
fi

pip install -r requirements.txt --quiet
echo "✓ Python environment ready."

# ------------------------------------------------------------------------------
# 4. Desktop Shortcut & Application Launcher
# ------------------------------------------------------------------------------
echo "[4/4] Creating Desktop application launcher..."

if [ "$OS" = "Darwin" ]; then
    # macOS Desktop .command launcher
    DESKTOP_DIR="$HOME/Desktop"
    LAUNCHER="$DESKTOP_DIR/Voice Highlighter.command"
    cat <<EOF > "$LAUNCHER"
#!/bin/bash
cd "$DIR"
source .venv/bin/activate
export PATH="$DIR/bin:\$PATH"
python3 desktop_launcher.py
EOF
    chmod +x "$LAUNCHER"
    echo "✓ Created macOS launcher: $LAUNCHER"
else
    # Linux Desktop Entry
    DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    APPS_DIR="$HOME/.local/share/applications"
    mkdir -p "$APPS_DIR"

    DESKTOP_ENTRY="$APPS_DIR/voice-highlighter.desktop"
    cat <<EOF > "$DESKTOP_ENTRY"
[Desktop Entry]
Version=1.0
Type=Application
Name=Voice Highlighter
Comment=AI Word-Highlighted Subtitle Studio
Exec=bash -c 'cd "$DIR" && source .venv/bin/activate && export PATH="$DIR/bin:\$PATH" && python3 desktop_launcher.py'
Terminal=false
Categories=AudioVideo;Audio;Video;Graphics;
StartupNotify=true
EOF
    chmod +x "$DESKTOP_ENTRY"

    if [ -d "$DESKTOP_DIR" ]; then
        cp "$DESKTOP_ENTRY" "$DESKTOP_DIR/Voice Highlighter.desktop"
        chmod +x "$DESKTOP_DIR/Voice Highlighter.desktop"
        echo "✓ Created Linux desktop launcher on your Desktop."
    fi
fi

echo "=========================================================="
echo " 🎉 Voice Highlighter is successfully installed!"
echo " Launch it via your Desktop icon or run: ./run.sh"
echo "=========================================================="
