# 🎙️ Voice Highlighter

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_3.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Standards: 100% Compliant](https://img.shields.io/badge/Open_Source_Standards-100%25_PASS-success.svg)](AGENTS.md)

> **A high-performance, privacy-respecting AI tool for generating, editing, and burning word-highlighted animated subtitles directly into videos.**

Accelerated with **WhisperX AI** (word-level forced alignment) and hardware-accelerated **FFmpeg** rendering (e.g., **NVIDIA NVENC** on Windows/Linux, **Apple Silicon VideoToolbox** on macOS, and **CPU libx264** fallback).

---

## ✨ Features

- **Precision Word Timing**: WhisperX AI delivers phoneme- and word-level synchronized subtitle timing.
- **Dynamic Word Highlighting**: Karaoke/pop-style animated subtitle styling rendered in clean `.ass` format.
- **Zero Telemetry & Local Data**: Runs entirely on your local hardware. No remote telemetry, no external font CDNs, no cloud dependencies.
- **XDG Base Directory Presets**: Presets stored in standard `$XDG_CONFIG_HOME/voice-highlighter/presets/` in readable YAML with strict schema validation.
- **Hardened Local Server**: Strictly binds to `127.0.0.1` with ephemeral launch token authentication and W3C Content Security Policy (CSP).
- **Two Flexible Workflows**:
  - **Standard 3-Step Production**: Generate Subtitles → Verify & Edit in Inline Drawer → Fast Hardware Burn.
  - **1-Click Draft**: Transcribe and burn directly into video in a single pass without manual review.
- **Inline Text & Timing Editor**: Correct misheard proper nouns, dialogue, and timestamps before final render.
- **Native Desktop & Web CLI**: Run via unified Unix CLI (`voice-highlighter`), standalone desktop window, or browser UI.

---

## 🚀 3-Step Quickstart

1. **Install Dependencies**:
   ```bash
   pip install -e .
   ```
   *(Or run `./install.sh` on macOS/Linux or `install.bat` on Windows for automated setup).*

2. **Launch the Hardened Web Studio**:
   ```bash
   voice-highlighter serve
   ```
   *Opens strictly on `127.0.0.1:8000` with an ephemeral single-session launch token.*

3. **Or Launch in Desktop Window Mode**:
   ```bash
   voice-highlighter desktop
   ```

---

## 💻 CLI Flags Reference

The `voice-highlighter` command conforms strictly to POSIX CLI stream separation (machine data to `stdout`, logs/status to `stderr`):

| Flag / Subcommand | Arguments | Description |
|---|---|---|
| `-h, --help` | None | Display command help and exit (< 200ms). |
| `-v, --version` | None | Output tool version, GNU AGPLv3 license, and repository URL. |
| `-q, --quiet` | None | Suppress all informational banners (errors and machine data only). |
| `--verbose` | None | Enable verbose diagnostic logging to `stderr`. |
| `--json` | None | Output machine-readable structured JSON to `stdout`. |
| `--reset-config` | None | Purge user presets/config and restore factory defaults. |
| `serve` | `[--host 127.0.0.1] [--port 8000]` | Start the local web studio on localhost. |
| `desktop` | None | Launch standalone chromeless desktop window. |
| `preset list` | `[--json]` | List all locally available style presets. |
| `preset show` | `[name] [--json]` | Display preset configuration in YAML or JSON format. |
| `run` | `[input] [--preset default]` | Process input subtitle/audio file, or read from standard input (`-`). |

### Unix Composability Examples

```bash
# Read input text directly from standard input (stdin)
cat transcript.txt | voice-highlighter run - --json

# List available presets as machine-readable JSON
voice-highlighter preset list --json

# Reset all local presets and state to clean defaults
voice-highlighter --reset-config
```

---

## ⚙️ YAML Style Preset Configuration

Presets are stored in `$XDG_CONFIG_HOME/voice-highlighter/presets/<name>.yaml` (default: `~/.config/voice-highlighter/presets/` on Linux/macOS, `%APPDATA%\voice-highlighter\presets\` on Windows) with secure mode `0600` permissions:

```yaml
# Voice Highlighter Style Preset: tiktok-bold
# Auto-generated configuration file adhering to open-source standards.
name: tiktok-bold
description: Punchy TikTok/Shorts vertical subtitles
font_name: Montserrat
font_size: 72
bold: true
italic: false
primary_color: '#FFFFFF'
outline_color: '#000000'
outline_width: 3.0
highlight_style: color
highlight_color: '#00FFAA'
box_bg_color: '#000000'
box_opacity: 0.75
box_font_color: '#FFFFFF'
box_type: word
highlight_scale_pct: 110
pos_x_pct: 50.0
pos_y_pct: 75.0
line_width_pct: 85.0
max_lines: 1
max_chars_per_line: 28
```

---

## 🔒 Security Policy

Please review our [SECURITY.md](SECURITY.md) for details on responsible vulnerability disclosure. Local servers strictly bind to `127.0.0.1` and require an ephemeral launch token generated via `secrets.token_hex(32)`.

---

## 📄 License & Source Notice

This project is licensed under the **GNU Affero General Public License v3.0 or later** ([GNU AGPLv3+](LICENSE)).

In accordance with Section 13 of GNU AGPLv3, the corresponding source code is available at:
<https://github.com/joelontheroad/Voice-Highlighter>

