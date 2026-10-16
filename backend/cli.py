# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command-line interface implementation adhering to POSIX standards and stream discipline."""

import argparse
import json
import os
import signal
import sys

from backend import __license__, __repository__, __version__
from backend.config import (
    list_presets,
    load_preset,
    reset_all_configuration,
)


def setup_signal_handlers() -> None:
    """Gracefully handle SIGINT and SIGTERM without dumping tracebacks."""
    def _sig_handler(signum, frame):
        sys.stderr.write("\n[voice-highlighter] Process interrupted by user. Exiting.\n")
        sys.stderr.flush()
        sys.exit(130)

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)


def should_colorize() -> bool:
    """Determine whether terminal ANSI colors should be emitted."""
    if "NO_COLOR" in os.environ:
        return False
    return sys.stdout.isatty()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point function."""
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
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__} ({__license__})\nSource: {__repository__}",
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
    serve_parser = subparsers.add_parser("serve", parents=[common_parser], help="Launch the local web interface strictly on localhost.")
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port number to bind (default: 8000).",
    )
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

    # 'desktop' subcommand
    subparsers.add_parser("desktop", parents=[common_parser], help="Launch native desktop chromeless window.")

    # 'preset' subcommand
    preset_parser = subparsers.add_parser("preset", parents=[common_parser], help="Inspect and manage local YAML presets.")
    preset_sub = preset_parser.add_subparsers(dest="preset_action")
    preset_sub.add_parser("list", parents=[common_parser], help="List all locally available presets.")
    
    show_preset = preset_sub.add_parser("show", parents=[common_parser], help="Display preset configuration.")
    show_preset.add_argument("name", nargs="?", default="default", help="Preset name (default: 'default').")

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

    args = parser.parse_args(argv)

    # Handle global reset
    if args.reset_config:
        reset_all_configuration()
        if not args.quiet:
            sys.stderr.write("[voice-highlighter] Local configuration reset to factory defaults.\n")
        return 0

    if not args.subcommand:
        parser.print_help(sys.stderr)
        return 2

    # Handler: serve (Lazy import to maintain sub-200ms startup for CLI commands)
    if args.subcommand == "serve":
        from backend.app import run_server
        run_server(port=args.port, host=args.host, reload=args.reload)
        return 0

    # Handler: desktop
    if args.subcommand == "desktop":
        from desktop_launcher import main as desktop_main
        desktop_main()
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

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
