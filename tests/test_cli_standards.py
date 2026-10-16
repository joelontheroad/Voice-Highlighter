# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Subprocess-level CLI compliance and standards test suite."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def isolated_env(tmp_path: Path):
    """Isolate XDG directories so tests never modify user configuration."""
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


def run_cli(*args: str, env: dict, input_data: str | None = None) -> subprocess.CompletedProcess:
    """Helper invoking CLI entry point as a distinct subprocess."""
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
    """Standard 3 & 10: Verify --help returns exit code 0 within 2000ms and prints usage."""
    start = time.perf_counter()
    res = run_cli("--help", env=isolated_env)
    duration = time.perf_counter() - start

    assert res.returncode == 0
    assert "usage: voice-highlighter" in res.stdout.lower()
    assert res.stderr == ""
    # Generous margin for subprocess invocation while asserting quick execution
    assert duration < 2.0


def test_cli_version(isolated_env):
    """Standard 2: Single source of version, mentions AGPLv3 and repository URL."""
    res = run_cli("--version", env=isolated_env)
    assert res.returncode == 0
    assert "1.0.0" in res.stdout
    assert "AGPL" in res.stdout
    assert "https://github.com/joelontheroad/Voice-Highlighter" in res.stdout


def test_cli_invalid_argument_exit_code(isolated_env):
    """Standard 8: Argument/syntax errors MUST exit with code 2 and write to stderr."""
    res = run_cli("--non-existent-flag-xyz", env=isolated_env)
    assert res.returncode == 2
    assert "unrecognized arguments" in res.stderr.lower()


def test_cli_reset_config(isolated_env):
    """Standard 1 & 4: --reset-config resets local state and defaults."""
    res = run_cli("--reset-config", env=isolated_env)
    assert res.returncode == 0
    assert "reset to factory defaults" in res.stderr.lower()

    # Verify default preset file exists in isolated XDG directory
    config_dir = Path(isolated_env["XDG_CONFIG_HOME"]) / "voice-highlighter" / "presets"
    assert (config_dir / "default.yaml").exists()


def test_cli_preset_list_and_show(isolated_env):
    """Standard 3, 4 & 11: preset subcommands output formatted text or JSON."""
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
    """Standard 11: Support '-' to read input from stdin with stream separation."""
    sample_text = "Hello world this is an automated subtitle alignment test."
    res = run_cli("run", "-", "--json", env=isolated_env, input_data=sample_text)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["status"] == "success"
    assert data["characters_processed"] == len(sample_text)
