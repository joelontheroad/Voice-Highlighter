#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Voice Highlighter Desktop App Launcher
Spawns the local FastAPI backend server and launches a dedicated, chromeless
desktop application window on macOS, Windows, and Linux.
"""
import os
import sys
import time
import socket
import secrets
import urllib.request
import subprocess
import webbrowser
from typing import Optional

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
AUTH_TOKEN = os.environ.get("VOICE_HIGHLIGHTER_AUTH_TOKEN") or secrets.token_hex(32)
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/?token={AUTH_TOKEN}"

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a socket port is actively listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def wait_for_server(target: str = SERVER_HOST, port: int = SERVER_PORT, timeout: float = 12.0) -> bool:
    """Polls backend health check until it responds or timeout expires."""
    check_url = f"http://{SERVER_HOST}:{SERVER_PORT}/api/system-info"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(check_url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False

def start_backend_server() -> Optional[subprocess.Popen]:
    """Starts the Uvicorn server in a background process if not already running."""
    if is_port_in_use(SERVER_PORT, SERVER_HOST):
        print(f"[Desktop Launcher] Server already running on port {SERVER_PORT}")
        return None

    project_root = os.path.dirname(os.path.abspath(__file__))
    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.app:app",
        "--host", SERVER_HOST,
        "--port", str(SERVER_PORT)
    ]
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "ignore:resource_tracker"
    env["VOICE_HIGHLIGHTER_AUTH_TOKEN"] = AUTH_TOKEN
    print(f"[Desktop Launcher] Starting backend server: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=project_root, env=env)
    return proc

def launch_browser_app_mode(url: str) -> bool:
    """Launches system Chromium, Chrome, or Edge in standalone chromeless --app mode."""
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", f"--app={url}"],
            ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", f"--app={url}"],
            ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", f"--app={url}"],
        ]
    elif sys.platform == "win32":
        candidates = [
            ["msedge.exe", f"--app={url}"],
            ["chrome.exe", f"--app={url}"],
        ]
    else:
        # Linux
        candidates = [
            ["google-chrome", f"--app={url}"],
            ["chromium", f"--app={url}"],
            ["chromium-browser", f"--app={url}"],
            ["microsoft-edge", f"--app={url}"],
            ["brave-browser", f"--app={url}"],
        ]

    for cmd in candidates:
        try:
            subprocess.Popen(cmd)
            return True
        except FileNotFoundError:
            continue
        except Exception:
            continue

    # Universal fallback to default browser tab
    webbrowser.open(url)
    return False

def main():
    server_proc = start_backend_server()
    if not wait_for_server(SERVER_URL):
        print("[Desktop Launcher] Waiting for server took longer than expected; proceeding to UI.")

    has_pywebview = False
    try:
        import webview
        has_pywebview = True
    except ImportError:
        has_pywebview = False

    if has_pywebview:
        try:
            print("[Desktop Launcher] Opening native desktop window with PyWebView...")
            window = webview.create_window(
                title="Voice Highlighter",
                url=SERVER_URL,
                width=1400,
                height=900,
                min_size=(1024, 680),
                background_color="#0a0e17"
            )
            webview.start()
        except Exception as e:
            print(f"[Desktop Launcher] PyWebView display initialization failed ({e}). Falling back to App Mode.")
            launch_browser_app_mode(SERVER_URL)
    else:
        print("[Desktop Launcher] Launching in App Mode...")
        launch_browser_app_mode(SERVER_URL)

    # Graceful shutdown of backend server when window closes
    if server_proc and server_proc.poll() is None:
        print("[Desktop Launcher] Shutting down backend server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()

if __name__ == "__main__":
    main()
