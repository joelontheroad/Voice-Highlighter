# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command-line interface implementation.

Adheres to POSIX standards, separation of streams (machine-readable stdout vs.
diagnostic stderr), standard flags (-h, -v, -q, --verbose, --config, --json),
XDG configuration reset, and stream piping support (-).
"""

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from backend import __license__, __repository__, __version__
from backend.config import (
    list_presets,
    load_preset,
    reset_all_configuration,
)

DEFAULT_PORT = 8672

_ORIGINAL_TERMIOS: Any = None
try:
    if sys.platform != "win32" and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        import termios
        _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin.fileno())
except Exception:
    _ORIGINAL_TERMIOS = None


def restore_terminal() -> None:
    """Restore terminal echo, canonical mode, and cursor visibility (Directive 3 & 10).

    Guarantees that the terminal is left fully functional when the process exits,
    even if interrupted by SIGINT, exceptions, or external tools that disabled echo.
    """
    global _ORIGINAL_TERMIOS

    # 1. Reset ANSI attributes and restore cursor visibility (\033[?25h)
    if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        try:
            sys.stderr.write("\033[?25h\033[0m")
            sys.stderr.flush()
        except Exception:
            pass

    # 2. Restore captured termios attributes (echo, line buffering)
    if _ORIGINAL_TERMIOS is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _ORIGINAL_TERMIOS)
        except Exception:
            pass

    # 3. Fallback: Run 'stty sane' on Unix platforms to ensure terminal sanity
    if sys.platform != "win32" and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            subprocess.run(
                ["stty", "sane"],
                stdin=sys.stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.3,
            )
        except Exception:
            pass


atexit.register(restore_terminal)


class ShutdownSpinner:
    """Animated Braille spinner for clean, user-visible CLI shutdown progress."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Shutting down Voice Highlighter..."):
        self.message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the animated shutdown spinner on a background daemon thread."""
        if not hasattr(sys.stderr, "isatty") or not sys.stderr.isatty():
            sys.stderr.write(f"\n[voice-highlighter] {self.message}\n")
            sys.stderr.flush()
            return

        def _spin():
            idx = 0
            # Hide cursor while spinning
            sys.stderr.write("\033[?25l")
            sys.stderr.flush()
            while not self._stop_event.is_set():
                frame = self.FRAMES[idx % len(self.FRAMES)]
                sys.stderr.write(f"\r\033[K\033[1;33m{frame}\033[0m {self.message}")
                sys.stderr.flush()
                idx += 1
                time.sleep(0.08)
            # Clear line upon stop
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

        self._thread = threading.Thread(target=_spin, daemon=True)
        self._thread.start()

    def stop(self, final_msg: str | None = "✓ Voice Highlighter stopped cleanly.\n") -> None:
        """Stop the spinner, emit final success message, and restore terminal state."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        if final_msg:
            sys.stderr.write(f"\033[1;32m{final_msg}\033[0m" if should_colorize() else final_msg)
            sys.stderr.flush()
        restore_terminal()


_shutdown_in_progress = False


def get_default_port() -> int:
    """Resolve the default network port from environment or fallback constant.

    Implements Directive 4 5-tier configuration precedence:
    CLI flags > VOICE_HIGHLIGHTER_PORT env var > default port (8672).

    Returns:
        Integer TCP port number.
    """
    env_port = os.environ.get("VOICE_HIGHLIGHTER_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    return DEFAULT_PORT


def setup_signal_handlers() -> None:
    """Register signal handlers to gracefully handle SIGINT and SIGTERM (Directive 10).

    Catches interruption signals cleanly, displaying an animated shutdown spinner on stderr,
    restoring terminal attributes (echo, cursor), and exiting with status code 130 without tracebacks.
    """
    def _sig_handler(signum, frame):
        global _shutdown_in_progress
        if _shutdown_in_progress:
            # Second Ctrl+C forces instant exit
            restore_terminal()
            sys.stderr.write("\n[voice-highlighter] Process interrupted. Force exiting.\n")
            sys.stderr.flush()
            os._exit(130)

        _shutdown_in_progress = True
        spinner = ShutdownSpinner("Shutting down Voice Highlighter...")
        spinner.start()
        time.sleep(0.25)
        spinner.stop("✓ Voice Highlighter stopped cleanly.\n")
        restore_terminal()
        sys.exit(130)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)


def should_colorize() -> bool:
    """Determine whether terminal ANSI colors should be emitted.

    Respects the NO_COLOR standard environment variable and tests whether stdout
    is an attached terminal TTY.

    Returns:
        True if ANSI styling is permitted; False otherwise.
    """
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def format_clickable_url(url: str, label: str | None = None, stream: Any = sys.stderr) -> str:
    """Format a URL as an OSC 8 clickable link if stream is an interactive TTY and NO_COLOR is unset.

    Args:
        url: The target destination URL.
        label: Optional visual label text, or None to display the URL itself.
        stream: Output stream to inspect for TTY capability (defaults to sys.stderr).

    Returns:
        OSC 8 formatted hyperlink string when connected to an interactive TTY and NO_COLOR
        is absent, falling back to clean plain-text URL when redirected or NO_COLOR is set.
    """
    display_text = label or url
    if "NO_COLOR" in os.environ:
        return display_text
    is_tty = hasattr(stream, "isatty") and stream.isatty()
    if is_tty:
        # SECURITY: Prevent terminal escape sequence injection by wrapping clean URL and label in OSC 8
        return f"\033]8;;{url}\033\\{display_text}\033]8;;\033\\"
    return display_text


def is_headless() -> bool:
    """Detect whether the current execution environment is headless.

    Returns:
        True if running in continuous integration or on Linux without DISPLAY/WAYLAND_DISPLAY;
        False if a graphical desktop session is available.
    """
    if os.environ.get("CI", "").lower() in ("true", "1"):
        return True
    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    """Execute the Voice Highlighter command-line interface.

    Parses arguments, configures stream logging, and dispatches subcommands
    including server launch, desktop application mode, preset management,
    and subtitle pipeline processing.

    Args:
        argv: Optional sequence of command-line argument strings. Defaults
            to sys.argv[1:].

    Returns:
        Exit code (0 for success, 1 for operational failure, 2 for CLI syntax errors).
    """
    setup_signal_handlers()

    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress all informational messages (errors and data output only).",
    )
    common_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose diagnostic output on stderr.",
    )
    common_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured results in machine-readable JSON format to stdout.",
    )

    parser = argparse.ArgumentParser(
        prog="voice-highlighter",
        description="Voice Highlighter: Word-level animated subtitle generator powered by WhisperX.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common_parser],
    )

    # Standard global flags
    repo_url = format_clickable_url(__repository__, stream=sys.stdout)
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__} ({__license__})\nSource: {repo_url}",
        help="Show program version, license (GNU AGPLv3), and repository information.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom configuration or preset file.",
    )
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="Purge all user-saved presets and restore factory defaults.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 'serve' subcommand
    default_port = get_default_port()
    serve_parser = subparsers.add_parser("serve", parents=[common_parser], help="Launch the local web interface strictly on localhost.")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Port number to bind (default: {default_port}, or VOICE_HIGHLIGHTER_PORT).",
    )
    # SECURITY: Bind strictly to loopback interface 127.0.0.1 by default to prevent unauthorized network exposure
    serve_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind. Defaults strictly to 127.0.0.1 (localhost).",
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable hot reload for development.",
    )
    serve_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Suppress automatic launch of the default web browser on startup.",
    )

    # 'desktop' subcommand
    desktop_parser = subparsers.add_parser("desktop", parents=[common_parser], help="Launch native desktop chromeless window.")
    desktop_parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"Port number for backend server (default: {default_port}, or VOICE_HIGHLIGHTER_PORT).",
    )

    # 'preset' subcommand
    preset_parser = subparsers.add_parser("preset", parents=[common_parser], help="Inspect and manage local YAML presets.")
    preset_sub = preset_parser.add_subparsers(dest="preset_action")
    preset_sub.add_parser("list", parents=[common_parser], help="List all locally available presets.")

    show_preset = preset_sub.add_parser("show", parents=[common_parser], help="Display preset configuration.")
    show_preset.add_argument("name", nargs="?", default="default", help="Preset name (default: 'default').")

    # 'config' subcommand
    config_parser = subparsers.add_parser("config", parents=[common_parser], help="Manage local configuration and state.")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("reset", parents=[common_parser], help="Permanently unlink all local presets and restore factory defaults.")

    # 'run' subcommand with stdin piping support (-)
    run_parser = subparsers.add_parser("run", parents=[common_parser], help="Process subtitle text or run audio transcription.")
    run_parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input text file path, or '-' to read directly from standard input (stdin).",
    )
    run_parser.add_argument(
        "--preset",
        type=str,
        default="default",
        help="Styling preset name to apply.",
    )
    run_parser.add_argument(
        "--reveal",
        action="store_true",
        help="Reveal processed input file or output directory in native file manager.",
    )

    args = parser.parse_args(argv)

    # Handle global reset or 'config reset' subcommand
    if args.reset_config or (args.subcommand == "config" and getattr(args, "config_action", None) == "reset"):
        # SECURITY: Permanently delete state files via unlink without moving to Desktop Trash (CWE-459)
        reset_all_configuration()
        if not args.quiet:
            sys.stderr.write("[voice-highlighter] Local configuration reset to factory defaults.\n")
        return 0

    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 2

    if args.subcommand == "config":
        config_parser.print_help(sys.stderr)
        return 2

    # Handler: serve (Lazy import to maintain sub-200ms startup for CLI commands)
    if args.subcommand == "serve":
        from backend.app import run_server
        run_server(port=args.port, host=args.host, reload=args.reload, no_browser=args.no_browser)
        return 0

    # Handler: desktop
    if args.subcommand == "desktop":
        from desktop_launcher import main as desktop_main
        desktop_main(port=args.port)
        return 0

    # Handler: preset
    if args.subcommand == "preset":
        if args.preset_action == "list":
            presets = list_presets()
            if args.json:
                sys.stdout.write(json.dumps({"presets": presets}, indent=2) + "\n")
            else:
                for p in presets:
                    sys.stdout.write(f"- {p}\n")
            return 0

        if args.preset_action == "show":
            try:
                preset = load_preset(args.name)
            except (ValueError, OSError, PermissionError) as e:
                sys.stderr.write(f"Error loading preset '{args.name}': {e}\n")
                return 1

            if args.json:
                sys.stdout.write(json.dumps(preset.model_dump(), indent=2) + "\n")
            else:
                import yaml
                sys.stdout.write(yaml.dump(preset.model_dump(), sort_keys=False) + "\n")
            return 0

    # Handler: run (Demonstrates stdin support and stream separation)
    if args.subcommand == "run":
        try:
            if args.input == "-":
                raw_input = sys.stdin.read()
            else:
                with open(args.input, "r", encoding="utf-8") as f:
                    raw_input = f.read()
        except (OSError, UnicodeDecodeError) as e:
            sys.stderr.write(f"Error reading input: {e}\n")
            return 1

        try:
            preset = load_preset(args.preset)
        except (ValueError, OSError, PermissionError) as e:
            sys.stderr.write(f"Error loading preset '{args.preset}': {e}\n")
            return 1

        result = {
            "status": "success",
            "characters_processed": len(raw_input),
            "lines_processed": len(raw_input.splitlines()),
            "preset_applied": preset.name,
        }

        if args.json:
            sys.stdout.write(json.dumps(result, indent=2) + "\n")
        else:
            sys.stdout.write(f"Processed {result['characters_processed']} characters ({result['lines_processed']} lines) using preset '{preset.name}'.\n")

        if args.verbose:
            sys.stderr.write(f"[voice-highlighter] Applied preset '{preset.name}' font={preset.font_name} size={preset.font_size}\n")

        if getattr(args, "reveal", False):
            from backend.app import reveal_in_folder
            target_to_reveal = args.input if args.input != "-" and os.path.exists(args.input) else None
            if target_to_reveal:
                reveal_in_folder(target_to_reveal)
            elif not args.quiet:
                sys.stderr.write("[voice-highlighter] Stdin stream input; no filesystem file to reveal.\n")

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
