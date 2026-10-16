# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Subprocess-level CLI compliance and standards test suite.

Validates process exit codes, separation of stdout vs stderr streams,
help and version flags, JSON machine output, XDG directory isolation,
and standard input piping (-).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def isolated_env(tmp_path: Path) -> dict[str, str]:
    """Isolate XDG directories so tests never modify user configuration.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Returns:
        Dictionary of environment variables pointing to isolated test directories.
    """
    env = os.environ.copy()
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "data"

    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    env["XDG_CONFIG_HOME"] = str(config_dir)
    env["XDG_CACHE_HOME"] = str(cache_dir)
    env["XDG_DATA_HOME"] = str(data_dir)
    env["NO_COLOR"] = "1"
    return env


def run_cli(*args: str, env: dict[str, str], input_data: str | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI entry point as a distinct subprocess.

    Args:
        *args: Command line argument tokens.
        env: Environment variables dictionary.
        input_data: Optional standard input string to pipe.

    Returns:
        CompletedProcess instance with captured stdout and stderr.
    """
    cmd = [sys.executable, "-m", "backend.cli", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input=input_data,
        timeout=10,
        check=False,
    )


def test_cli_help(isolated_env):
    """Verify --help returns exit code 0 within 2000ms and prints usage."""
    start = time.perf_counter()
    res = run_cli("--help", env=isolated_env)
    duration = time.perf_counter() - start

    assert res.returncode == 0
    assert "usage: voice-highlighter" in res.stdout.lower()
    assert res.stderr == ""
    assert duration < 2.0


def test_cli_version(isolated_env):
    """Verify single source of version, AGPLv3 mention, and repository URL."""
    res = run_cli("--version", env=isolated_env)
    assert res.returncode == 0
    assert "1.0.0" in res.stdout
    assert "AGPL" in res.stdout
    assert "https://github.com/joelontheroad/Voice-Highlighter" in res.stdout


def test_cli_invalid_argument_exit_code(isolated_env):
    """Verify argument/syntax errors exit with code 2 and write to stderr."""
    res = run_cli("--non-existent-flag-xyz", env=isolated_env)
    assert res.returncode == 2
    assert "unrecognized arguments" in res.stderr.lower()


def test_cli_reset_config(isolated_env):
    """Verify --reset-config resets local state and defaults."""
    res = run_cli("--reset-config", env=isolated_env)
    assert res.returncode == 0
    assert "reset to factory defaults" in res.stderr.lower()

    # Verify default preset file exists in isolated XDG directory
    config_dir = Path(isolated_env["XDG_CONFIG_HOME"]) / "voice-highlighter" / "presets"
    assert (config_dir / "default.yaml").exists()


def test_cli_preset_list_and_show(isolated_env):
    """Verify preset subcommands output formatted text or JSON."""
    # List presets formatted
    res_list = run_cli("preset", "list", env=isolated_env)
    assert res_list.returncode == 0
    assert "default" in res_list.stdout

    # List presets JSON
    res_json = run_cli("preset", "list", "--json", env=isolated_env)
    assert res_json.returncode == 0
    data = json.loads(res_json.stdout)
    assert "presets" in data
    assert "default" in data["presets"]

    # Show preset
    res_show = run_cli("preset", "show", "default", "--json", env=isolated_env)
    assert res_show.returncode == 0
    preset_data = json.loads(res_show.stdout)
    assert preset_data["name"] == "default"
    assert "font_size" in preset_data


def test_cli_stdin_support(isolated_env):
    """Verify support for '-' to read input from stdin with stream separation."""
    sample_text = "Hello world this is an automated subtitle alignment test."
    res = run_cli("run", "-", "--json", env=isolated_env, input_data=sample_text)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["status"] == "success"
    assert data["characters_processed"] == len(sample_text)


def test_cli_serve_no_browser_flag(isolated_env):
    """Verify that the serve subcommand provides the --no-browser flag in its help text."""
    res = run_cli("serve", "--help", env=isolated_env)
    assert res.returncode == 0
    assert "--no-browser" in res.stdout
    assert "Suppress automatic launch" in res.stdout


def test_format_clickable_url():
    """Verify OSC 8 hyperlink formatting on TTY streams and plain-text fallback."""
    from backend.cli import format_clickable_url

    class MockTTYStream:
        def isatty(self) -> bool:
            return True

    class MockNonTTYStream:
        def isatty(self) -> bool:
            return False

    url = "http://127.0.0.1:8000/?token=abc123xyz"

    # Test interactive TTY without NO_COLOR
    orig_no_color = os.environ.pop("NO_COLOR", None)
    try:
        formatted = format_clickable_url(url, stream=MockTTYStream())
        assert formatted == f"\033]8;;{url}\033\\{url}\033]8;;\033\\"

        formatted_label = format_clickable_url(url, label="Open Studio", stream=MockTTYStream())
        assert formatted_label == f"\033]8;;{url}\033\\Open Studio\033]8;;\033\\"

        # Fallback when non-TTY stream
        fallback_nontty = format_clickable_url(url, stream=MockNonTTYStream())
        assert fallback_nontty == url

        # Fallback when NO_COLOR is active
        os.environ["NO_COLOR"] = "1"
        fallback_no_color = format_clickable_url(url, stream=MockTTYStream())
        assert fallback_no_color == url
    finally:
        if orig_no_color is not None:
            os.environ["NO_COLOR"] = orig_no_color
        else:
            os.environ.pop("NO_COLOR", None)


def test_is_headless():
    """Verify detection of headless environments via CI and desktop display variables."""
    from backend.cli import is_headless

    orig_ci = os.environ.get("CI")
    orig_display = os.environ.get("DISPLAY")
    orig_wayland = os.environ.get("WAYLAND_DISPLAY")

    try:
        # Case 1: CI=true forces headless mode
        os.environ["CI"] = "true"
        os.environ["DISPLAY"] = ":0"
        assert is_headless() is True

        # Case 2: CI absent or false
        os.environ.pop("CI", None)

        if sys.platform.startswith("linux"):
            # Missing both DISPLAY and WAYLAND_DISPLAY is headless
            os.environ.pop("DISPLAY", None)
            os.environ.pop("WAYLAND_DISPLAY", None)
            assert is_headless() is True

            # DISPLAY present is not headless
            os.environ["DISPLAY"] = ":0"
            assert is_headless() is False

            # WAYLAND_DISPLAY present is not headless
            os.environ.pop("DISPLAY", None)
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"
            assert is_headless() is False
    finally:
        for var, val in [("CI", orig_ci), ("DISPLAY", orig_display), ("WAYLAND_DISPLAY", orig_wayland)]:
            if val is not None:
                os.environ[var] = val
            else:
                os.environ.pop(var, None)

