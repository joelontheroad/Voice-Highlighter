#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice Highlighter desktop application launcher.

Spawns the local FastAPI backend server and orchestrates a dedicated,
chromeless desktop application window via PyWebView or browser app mode
across macOS, Windows, and Linux.
"""

import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

SERVER_HOST = "127.0.0.1"
DEFAULT_PORT = 8672
AUTH_TOKEN = os.environ.get("VOICE_HIGHLIGHTER_AUTH_TOKEN") or secrets.token_hex(32)


def resolve_port(custom_port: int | None = None) -> int:
    """Resolve the TCP port applying Directive 4 5-tier precedence.

    Order of evaluation:
    1. CLI argument or explicit function parameter
    2. VOICE_HIGHLIGHTER_PORT environment variable
    3. Built-in default port 8672

    Args:
        custom_port: Optional port explicitly provided by caller.

    Returns:
        Validated TCP port integer.
    """
    if custom_port is not None:
        return custom_port

    if "--port" in sys.argv:
        try:
            idx = sys.argv.index("--port")
            if idx + 1 < len(sys.argv):
                return int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass

    env_port = os.environ.get("VOICE_HIGHLIGHTER_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass

    return DEFAULT_PORT


def get_server_url(port: int, host: str = SERVER_HOST) -> str:
    """Generate authenticated local loopback URL with ephemeral token."""
    return f"http://{host}:{port}/?token={AUTH_TOKEN}"


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Test whether a network port is actively bound by a listening socket.

    Args:
        port: TCP port number to check.
        host: Host interface address to inspect.

    Returns:
        True if the port is currently listening; False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def wait_for_server(host: str = SERVER_HOST, port: int = DEFAULT_PORT, timeout: float = 12.0) -> bool:
    """Poll the backend server health check endpoint until it responds.

    Args:
        host: Target IP address or hostname.
        port: Listening port number.
        timeout: Maximum seconds to poll before returning failure.

    Returns:
        True if the server responded with HTTP 200; False on timeout.
    """
    check_url = f"http://{host}:{port}/api/system-info"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(check_url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def start_backend_server(port: int = DEFAULT_PORT, host: str = SERVER_HOST) -> subprocess.Popen | None:
    """Launch the Uvicorn web server in a background subprocess.

    Args:
        port: TCP port number to bind.
        host: Host loopback interface to bind.

    Returns:
        A subprocess.Popen instance representing the server, or None if already running.
    """
    if is_port_in_use(port, host):
        # Verify if the existing service is indeed Voice Highlighter
        if wait_for_server(host=host, port=port, timeout=1.0):
            print(f"[Desktop Launcher] Voice Highlighter server already running on port {port}")
            return None
        sys.stderr.write(
            f"[Desktop Launcher] Error: Port {port} is already in use by another application.\n"
            f"[Desktop Launcher] Please specify a different port using --port <port> or VOICE_HIGHLIGHTER_PORT=<port>.\n"
        )
        sys.stderr.flush()
        sys.exit(1)

    project_root = os.path.dirname(os.path.abspath(__file__))
    # SECURITY: Pass discrete arguments and enforce loopback host 127.0.0.1 (CWE-78)
    cmd = [
        sys.executable, "-m", "uvicorn",
        "backend.app:app",
        "--host", host,
        "--port", str(port),
    ]
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "ignore:resource_tracker"
    env["VOICE_HIGHLIGHTER_AUTH_TOKEN"] = AUTH_TOKEN
    print(f"[Desktop Launcher] Starting backend server: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=project_root, env=env)
    return proc


def launch_browser_app_mode(url: str) -> bool:
    """Launch system Chromium, Chrome, or Edge in standalone chromeless app mode.

    Args:
        url: Full application URL including ephemeral authentication token.

    Returns:
        True if a dedicated browser window was spawned; False if fallback default was used.
    """
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
        # Linux candidate browser binaries
        candidates = [
            ["google-chrome", f"--app={url}"],
            ["chromium", f"--app={url}"],
            ["chromium-browser", f"--app={url}"],
            ["microsoft-edge", f"--app={url}"],
            ["brave-browser", f"--app={url}"],
        ]

    for cmd in candidates:
        try:
            # SECURITY: Launch browser with discrete parameter list (CWE-78)
            subprocess.Popen(cmd)
            return True
        except FileNotFoundError:
            continue
        except Exception:
            continue

    # Universal fallback to default browser tab
    webbrowser.open(url)
    return False


def main(port: int | None = None) -> None:
    """Orchestrate desktop server startup, window presentation, and graceful exit."""
    active_port = resolve_port(port)
    server_url = get_server_url(active_port)

    server_proc = start_backend_server(port=active_port)
    if not wait_for_server(host=SERVER_HOST, port=active_port):
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
            webview.create_window(
                title="Voice Highlighter",
                url=server_url,
                width=1400,
                height=900,
                min_size=(1024, 680),
                background_color="#0a0e17",
            )
            webview.start()
        except Exception as e:
            print(f"[Desktop Launcher] PyWebView display initialization failed ({e}). Falling back to App Mode.")
            launch_browser_app_mode(server_url)
    else:
        print("[Desktop Launcher] Launching in App Mode...")
        launch_browser_app_mode(server_url)

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
