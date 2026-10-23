# 🎙️ Voice Highlighter

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_3.0-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Standards: 100% Compliant](https://img.shields.io/badge/Open_Source_Standards-100%25_PASS-success.svg)](AGENTS.md)
[![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-emerald.svg)](pyproject.toml)

> **A high-performance, privacy-respecting AI tool for generating, editing, and burning word-highlighted animated subtitles directly into videos.**

Accelerated with **WhisperX AI** (word-level forced phoneme alignment) and hardware-accelerated **FFmpeg** rendering (including **NVIDIA NVENC** on Linux/Windows, **Apple Silicon VideoToolbox** on macOS, **Intel QSV**, **AMD AMF**, and CPU **libx264** fallback).

---

## ✨ Features

- **Precision Word Timing**: WhisperX AI delivers phoneme- and word-level synchronized subtitle timing for maximum accuracy.
- **Dynamic Word Highlighting Animations**:
  - **Discrete Word Pop**: High-energy color shift and scale boost (100%–180%) on the active spoken word.
  - **Progressive Karaoke Wipe (`\kf`)**: Smooth continuous syllable fill sweep (Pioneer US 5,742,569 expired prior art).
  - **Pre-Vocal Cadence Glow**: Subtitle outline border priming on upcoming words prior to voice onset (Sony US 5,684,542 expired prior art).
  - **Hormozi Pill Box**: Full-line or word-level background badges with customizable opacity and colors.
- **Multi-Speaker Dialogue Channels**: Configure separate primary and highlight colors for up to multiple speakers (`SPEAKER_00`, `SPEAKER_01`, etc.) with optional speaker name prefix badges (`[Alex]:`, `[Maria]:`) and speaker-turn isolated line chunking.
- **Interactive Live Subtitle Preview**:
  - **Drag-and-Drop Placement**: Click and drag the subtitle card directly on the video canvas to adjust positioning in real time.
  - **`[ ⛶ Text Bounds ]` Envelope**: Toggleable visual boundary envelope displaying the exact maximum perimeter where dialogue can appear across all 5 layout controls (**Line Width %**, **Max Characters Per Line**, **Font Size & Family**, **Active Word Font Size Boost**, and **Lines Displayed**).
  - **Social Media Safe Zones**: Preview layout under YouTube Shorts, Instagram Reels, and Facebook video UI overlays in Mobile App and Web Browser modes.
- **Style Presets with 1-Click Update**:
  - **Factory Templates**: Built-in, high-converting presets including *Viral TikTok (Yellow Pop)*, *Hormozi Pill Box*, *Classic Subtitle*, *Clean Minimalist*, *Podcast Duo*, and *LaserKaraoke Wipe*.
  - **Default Preset Immutability**: Built-in presets are protected against accidental overwrites or deletion on both the frontend and backend.
  - **1-Click Preset Update**: Instantly update active custom presets with your current styling modifications with a single click.
  - **Export & Import JSON**: Easily share custom presets between machines or backup configurations.
- **Sibling Asset Lifecycle State Machine**: Automatically detects co-located `.wav` (16kHz mono audio) and `.ass` (word-level subtitles), skipping redundant extraction or transcription steps when re-styling or re-burning.
- **Zero-Burn Inline Transcript Editor**: Review transcribed speech, fix proper nouns, and tweak timestamps directly in the web UI without re-encoding video.
- **Zero Telemetry & 100% Local**: Strictly binds to loopback interface `127.0.0.1` with a single-session CSPRNG launch token. No external font CDNs, no tracking, and complete offline capability.

---

## 🚀 3-Step Quickstart

1. **Install Dependencies**:
   ```bash
   pip install -e .
   ```
   *(Or run `./install.sh` on macOS/Linux or `install.bat` on Windows for automated virtualenv setup).*

2. **Launch the Hardened Web Studio**:
   ```bash
   voice-highlighter serve
   ```
   *Automatically opens your default browser at `http://127.0.0.1:8672/?token=...` with an ephemeral single-session launch token.*

3. **Or Launch in Desktop Window Mode**:
   ```bash
   voice-highlighter desktop
   ```

---

## 💻 CLI Flags Reference

The `voice-highlighter` command conforms strictly to POSIX/GNU CLI stream separation (machine data to `stdout`, logs/status to `stderr`):

| Flag / Subcommand | Arguments | Description |
|---|---|---|
| `-h, --help` | None | Display command help and exit (< 200ms). |
| `-v, --version` | None | Output tool version (`1.0.0`), GNU AGPLv3 license, and repository URL. |
| `-q, --quiet` | None | Suppress all informational banners (errors and machine data only). |
| `--verbose` | None | Enable verbose diagnostic output on `stderr`. |
| `--json` | None | Output structured machine-readable JSON to `stdout`. |
| `--config <path>` | File Path | Specify path to custom YAML configuration or preset file. |
| `--reset-config` | None | Purge user presets/config and restore factory defaults. |
| `serve` | `[--host 127.0.0.1] [--port 8672] [--no-browser] [--reload]` | Start the local web studio strictly on localhost (default port `8672` or via `VOICE_HIGHLIGHTER_PORT`). Automatically launches default browser unless `--no-browser` or headless. |
| `desktop` | `[--port 8672]` | Launch standalone native chromeless desktop window. |
| `preset list` | `[--json]` | List all locally available style presets. |
| `preset show` | `[name] [--json]` | Display preset configuration in YAML or JSON format. |
| `run` | `[input] [--preset default]` | Process input subtitle/audio file, or read from standard input (`-`). |

### Unix Composability Examples

```bash
# Read input text directly from standard input (stdin)
cat transcript.txt | voice-highlighter run - --json

# List available presets as machine-readable JSON
voice-highlighter preset list --json

# Inspect a specific preset in detail
voice-highlighter preset show tiktok-bold

# Reset all local presets and state to factory defaults
voice-highlighter --reset-config
```

---

## ⚙️ YAML Style Preset Configuration

Presets are stored in `$XDG_CONFIG_HOME/voice-highlighter/presets/<name>.yaml` (default: `~/.config/voice-highlighter/presets/` on Linux/macOS, `%APPDATA%\voice-highlighter\presets\` on Windows) with secure mode `0600` POSIX permissions:

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
highlight_animation: discrete
pos_x_pct: 50.0
pos_y_pct: 75.0
line_width_pct: 85.0
max_lines: 1
max_chars_per_line: 28
speaker_channels:
  SPEAKER_00:
    id: SPEAKER_00
    name: Speaker 1
    primary_color: '#FFFFFF'
    highlight_color: '#FFDF00'
    outline_color: '#000000'
    box_bg_color: '#000000'
    box_font_color: '#FFFFFF'
    show_speaker_name: false
```

---

## 🔒 Security Policy

Please review our [SECURITY.md](SECURITY.md) for details on responsible vulnerability disclosure. Local servers strictly bind to `127.0.0.1` and require an ephemeral launch token generated via `secrets.token_hex(32)`.

---

## 📄 License & Source Notice

This project is licensed under the **GNU Affero General Public License v3.0 or later** ([GNU AGPLv3+](LICENSE)).

In accordance with Section 13 of GNU AGPLv3, the corresponding source code is available at:  
<https://github.com/joelontheroad/Voice-Highlighter>
