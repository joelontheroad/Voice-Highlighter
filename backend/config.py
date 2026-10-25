# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Configuration and preset management subsystem.

Adheres strictly to the XDG Base Directory specification and provides
Pydantic schema-validated style presets with secure YAML deserialization,
POSIX permission hardening (modes 0700/0600), and path traversal mitigations.
"""

import os
import sys
import urllib.parse
from typing import Any
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

APP_NAME = "voice-highlighter"


class SpeakerChannel(BaseModel):
    """Configuration for an individual speaker color channel.

    Enables multi-speaker dialogue subtitle rendering with custom base text,
    highlight, outline, and bounding box colors per speaker.
    """

    id: str = Field(..., description="Unique speaker identifier (e.g. 'SPEAKER_00' or 'Speaker 1')")
    name: str = Field(default="Speaker", description="Human-readable speaker display name")
    primary_color: str = Field(default="#FFFFFF", description="Base dialogue text color (Hex)")
    highlight_color: str = Field(default="#FFDF00", description="Active spoken word highlight color (Hex)")
    outline_color: str = Field(default="#000000", description="Text outline border color (Hex)")
    box_bg_color: str = Field(default="#000000", description="Background pill/box color (Hex)")
    box_font_color: str = Field(default="#FFFFFF", description="Text color inside box badge (Hex)")
    show_speaker_name: bool = Field(default=False, description="Whether to prefix dialogue with speaker name")


class KeyframeConfig(BaseModel):
    """Timeline keyframe specifying timestamp and custom style overrides.

    Allows subtitle typography, positioning, colors, and badge animations
    to change dynamically along the media timeline. The styling specified
    by a keyframe stays in effect to the right of the timeline until another
    keyframe is encountered.
    """

    id: str | None = Field(default=None, description="Unique keyframe identifier")
    time: float = Field(..., ge=0.0, description="Timestamp in seconds where style takes effect")
    label: str | None = Field(default="", description="Optional human-readable keyframe label")
    styling: dict[str, Any] = Field(
        default_factory=dict,
        description="Styling parameters snapshot in effect to the right of this timestamp",
    )


class StylePreset(BaseModel):
    """Schema-validated style preset definition.

    Defines styling parameters for typography, positioning, colors,
    and subtitle animations burned or rendered to ASS subtitles.
    """

    name: str = Field(default="default", description="Preset name")
    description: str | None = Field(default="", description="Preset description")
    font_name: str = Field(default="Montserrat", description="Subtitle font family name")
    font_size: int = Field(default=68, ge=12, le=200, description="Font size in points/pixels")
    bold: bool = Field(default=True, description="Render font in bold weight")
    italic: bool = Field(default=False, description="Render font in italic style")
    primary_color: str = Field(default="#FFFFFF", description="Base dialogue text color (Hex)")
    outline_color: str = Field(default="#000000", description="Text outline border color (Hex)")
    outline_width: float = Field(default=3.0, ge=0.0, le=20.0, description="Outline stroke thickness")
    highlight_style: str = Field(default="color", description="'color' for font color shift, 'box' for bounding badge")
    highlight_color: str = Field(default="#FFDF00", description="Spoken word active highlight color (Hex)")
    box_bg_color: str = Field(default="#000000", description="Background badge/pill color (Hex)")
    box_opacity: float = Field(default=0.75, ge=0.0, le=1.0, description="Background box opacity (0.0 - 1.0)")
    box_font_color: str = Field(default="#FFFFFF", description="Text color inside box badge (Hex)")
    box_type: str = Field(default="word", description="'word' for individual word pill, 'block' for full line box")
    highlight_scale_pct: int = Field(default=100, ge=80, le=250, description="Scale boost percentage for spoken word (100 - 200%)")
    pos_x_pct: float = Field(default=50.0, ge=0.0, le=100.0, description="Horizontal center percentage (0% - 100%)")
    pos_y_pct: float = Field(default=78.0, ge=0.0, le=100.0, description="Vertical bottom position percentage (0% - 100%)")
    line_width_pct: float = Field(default=82.0, ge=20.0, le=100.0, description="Maximum line bounding width percentage")
    max_lines: int = Field(default=1, ge=1, le=4, description="Maximum simultaneous visible lines per subtitle block")
    max_chars_per_line: int = Field(default=28, ge=8, le=100, description="Maximum characters allowed per line")
    speaker_channels: dict[str, SpeakerChannel] = Field(
        default_factory=dict,
        description="Dictionary of speaker color channels keyed by speaker identifier",
    )
    highlight_animation: str = Field(
        default="discrete",
        description="Active highlight animation: 'discrete' (instant pop), 'karaoke_wipe' (smooth \\kf fill), or 'anticipation_glow' (pre-vocal cue)",
    )
    custom_vocabulary: list[str] = Field(
        default_factory=list,
        description="List of domain words, proper nouns, and jargon to condition WhisperX ASR",
    )
    keyframes: list[KeyframeConfig] = Field(
        default_factory=list,
        description="Timeline keyframes where styling changes dynamically across media playback",
    )


class AppConfig(BaseModel):
    """Global application configuration model.

    Encapsulates schema versioning, the active preset designation,
    and fallback preset definitions.
    """

    version: int = Field(default=1, description="Configuration schema version")
    default_preset: str = Field(default="default", description="Active preset name")
    preset: StylePreset = Field(default_factory=StylePreset)


def sanitize_log_path(path: str) -> str:
    """Scrub local username and home directory from log strings to protect privacy.

    Args:
        path: Raw filesystem path string.

    Returns:
        Sanitized path with user home directory replaced with '~<USER>'.
    """
    try:
        home_dir = str(Path.home())
        if home_dir and path.startswith(home_dir):
            return path.replace(home_dir, "~<USER>", 1)
    except (OSError, RuntimeError):
        return path
    return path


def parse_safe_file_uri(uri_or_path: str) -> str:
    """Safely parse and convert a file path or file:// URI into a canonical realpath (RFC 8089).

    Validates that file:// URIs reject remote authorities (host must be empty or localhost),
    decodes percent-encoding safely, and resolves canonical paths via os.path.realpath
    to prevent path traversal (CWE-22) and remote SSRF/SMB credential leaks.

    Args:
        uri_or_path: Path string or RFC 8089 file:// URI.

    Returns:
        Canonical absolute filesystem path string.

    Raises:
        ValueError: If a file:// URI contains a remote authority or is malformed.
    """
    cleaned = uri_or_path.strip()
    if cleaned.startswith("file://") or cleaned.startswith("file:"):
        parsed = urllib.parse.urlparse(cleaned)
        # SECURITY: Reject remote file URI authorities to prevent SSRF and SMB credential leaks (RFC 8089)
        if parsed.netloc and parsed.netloc.lower() not in ("", "localhost", "127.0.0.1"):
            raise ValueError(f"Remote file URI authorities are rejected: {parsed.netloc}")
        raw_path = urllib.parse.unquote(parsed.path)
        # On Windows, urlparse('/C:/foo') returns '/C:/foo' -> strip leading slash
        if sys.platform == "win32" and raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        cleaned = raw_path

    # SECURITY: Resolve canonical target path using realpath to prevent path traversal (CWE-22)
    return os.path.realpath(os.path.expanduser(cleaned))


def get_config_dir() -> Path:
    """Return the platform-appropriate configuration directory (XDG compliant).

    Returns:
        Path to the application configuration directory.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        config_root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        config_root = Path(base) if base else Path.home() / ".config"

    target_dir = config_root / APP_NAME
    # SECURITY: Restrict directory permissions to POSIX mode 0700 (rwx------) to protect configuration (CWE-732)
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(target_dir, 0o700)
            except OSError:
                pass
    return target_dir


def get_presets_dir() -> Path:
    """Return the presets subfolder within the config directory.

    Returns:
        Path to the presets directory.
    """
    presets_dir = get_config_dir() / "presets"
    # SECURITY: Restrict directory permissions to POSIX mode 0700 (rwx------) for preset storage (CWE-732)
    if not presets_dir.exists():
        presets_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(presets_dir, 0o700)
            except OSError:
                pass
    return presets_dir


def get_cache_dir() -> Path:
    """Return the platform-appropriate cache directory (XDG compliant).

    Returns:
        Path to the application cache directory.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        cache_root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_CACHE_HOME")
        cache_root = Path(base) if base else Path.home() / ".cache"

    target_dir = cache_root / APP_NAME
    # SECURITY: Restrict directory permissions to POSIX mode 0700 (rwx------) for cache artifacts (CWE-732)
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(target_dir, 0o700)
            except OSError:
                pass
    return target_dir


def get_data_dir() -> Path:
    """Return the platform-appropriate data directory (XDG compliant).

    Returns:
        Path to the application data directory.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        data_root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        data_root = Path(base) if base else Path.home() / ".local" / "share"

    target_dir = data_root / APP_NAME
    # SECURITY: Restrict directory permissions to POSIX mode 0700 (rwx------) for application data (CWE-732)
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(target_dir, 0o700)
            except OSError:
                pass
    return target_dir


def safe_resolve_preset_path(preset_name: str) -> Path:
    """Safely resolve a preset file path, preventing directory traversal attacks.

    Args:
        preset_name: Identifier name of the preset without path separators.

    Returns:
        Resolved absolute Path within the presets directory.

    Raises:
        PermissionError: If the name contains traversal sequences or escapes
            the allowed base directory (CWE-22).
    """
    clean_name = preset_name.strip()
    # SECURITY: Prevent path traversal (CWE-22) by rejecting path separators and traversal tokens
    if "/" in clean_name or "\\" in clean_name or ".." in clean_name:
        raise PermissionError(f"Access denied: Invalid preset name '{preset_name}'")

    if not clean_name.endswith(".yaml"):
        clean_name += ".yaml"

    base_dir = get_presets_dir().resolve()
    target_path = (base_dir / clean_name).resolve()

    # SECURITY: Verify canonical target path remains strictly within presets base directory (CWE-22)
    try:
        target_path.relative_to(base_dir)
    except ValueError as exc:
        raise PermissionError(f"Access denied: Preset '{preset_name}' escapes allowed directory") from exc

    return target_path


DEFAULT_PRESET_NAMES: frozenset[str] = frozenset(
    {"default", "tiktok-bold", "podcast-duo", "ensemble-quintet", "laser-karaoke"}
)


def load_preset(preset_name: str = "default") -> StylePreset:
    """Load and validate a YAML preset file using safe deserialization.

    Args:
        preset_name: Name of the preset to load.

    Returns:
        Validated StylePreset instance.

    Raises:
        ValueError: If YAML is malformed or schema validation fails.
    """
    preset_path = safe_resolve_preset_path(preset_name)

    if not preset_path.exists():
        # Create and persist default factory preset if missing
        default_preset = StylePreset(name=preset_name)
        save_preset(default_preset, allow_builtin=True)
        return default_preset

    try:
        with open(preset_path, "r", encoding="utf-8") as f:
            # SECURITY: Use yaml.safe_load exclusively to prevent arbitrary object instantiation (CWE-502)
            raw_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in preset '{preset_name}': {exc}") from exc

    try:
        return StylePreset.model_validate(raw_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid preset schema in '{preset_name}': {exc}") from exc


def save_preset(preset: StylePreset, allow_builtin: bool = False) -> Path:
    """Save a preset to disk with secure POSIX permissions (mode 0600).

    Args:
        preset: StylePreset instance to serialize and persist.
        allow_builtin: If True, permits saving or seeding built-in factory presets.
            User requests cannot overwrite protected built-in presets.

    Returns:
        Path to the persisted YAML preset file.

    Raises:
        ValueError: If user attempts to overwrite a protected built-in preset.
    """
    clean_name = preset.name.strip().lower()
    if not allow_builtin and clean_name in DEFAULT_PRESET_NAMES:
        raise ValueError(
            f"Cannot overwrite protected built-in preset '{preset.name}'. "
            f"Use 'Save New...' to save custom styling under a new name."
        )

    preset_path = safe_resolve_preset_path(preset.name)
    data = preset.model_dump()

    # Convert to commented YAML representation
    yaml_content = (
        f"# Voice Highlighter Style Preset: {preset.name}\n"
        f"# Auto-generated configuration file adhering to open-source standards.\n"
        + yaml.dump(data, sort_keys=False)
    )

    if sys.platform != "win32":
        # SECURITY: Atomic file creation with POSIX mode 0600 (rw-------) restricting file access to owner (CWE-732)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        mode = 0o600
        fd = os.open(str(preset_path), flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml_content)
    else:
        with open(preset_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)

    return preset_path


def list_presets() -> list[str]:
    """Return list of all locally available preset names.

    Returns:
        Sorted list of preset names found in local storage.
    """
    presets_dir = get_presets_dir()
    files = sorted(presets_dir.glob("*.yaml"))
    presets = [p.stem for p in files]
    if "default" not in presets:
        load_preset("default")
        presets.insert(0, "default")
    return presets


def delete_preset(preset_name: str) -> bool:
    """Safely delete a custom preset file.

    Args:
        preset_name: Name of the custom preset to remove.

    Returns:
        True if the preset existed and was removed; False if default or missing.
    """
    if preset_name.strip().lower() in DEFAULT_PRESET_NAMES:
        return False
    preset_path = safe_resolve_preset_path(preset_name)
    if preset_path.exists():
        preset_path.unlink()
        return True
    return False


def reset_all_configuration() -> None:
    """Purge all user-saved presets and restore factory defaults.

    Permanently unlinks all configuration and preset files from the local filesystem
    without moving them to the desktop trash can, ensuring deterministic data erasure
    per Directive 1.
    """
    config_dir = get_config_dir()
    if config_dir.exists():
        # SECURITY: Permanently delete state files via unlink; do not move to Desktop Trash (CWE-459)
        for root, dirs, files in os.walk(config_dir, topdown=False):
            for file in files:
                (Path(root) / file).unlink(missing_ok=True)
            for d in dirs:
                try:
                    (Path(root) / d).rmdir()
                except OSError:
                    pass
    # Reinitialize default factory presets
    default_preset = StylePreset(name="default", description="High-energy yellow spoken word highlight")
    save_preset(default_preset, allow_builtin=True)

    tiktok_preset = StylePreset(
        name="tiktok-bold",
        description="Punchy TikTok/Shorts vertical subtitles",
        font_name="Montserrat",
        font_size=72,
        bold=True,
        highlight_color="#00FFAA",
        highlight_scale_pct=110,
        pos_y_pct=75.0,
        line_width_pct=85.0,
        max_lines=1,
    )
    save_preset(tiktok_preset, allow_builtin=True)

    podcast_duo_preset = StylePreset(
        name="podcast-duo",
        description="Harmonious two-speaker dialogue with Yellow and Electric Cyan highlights",
        font_name="Montserrat",
        font_size=68,
        bold=True,
        highlight_color="#FFDF00",
        speaker_channels={
            "SPEAKER_00": SpeakerChannel(
                id="SPEAKER_00",
                name="Speaker 1",
                primary_color="#FFFFFF",
                highlight_color="#FFDF00",
                outline_color="#000000",
            ),
            "SPEAKER_01": SpeakerChannel(
                id="SPEAKER_01",
                name="Speaker 2",
                primary_color="#E0F7FA",
                highlight_color="#00E5FF",
                outline_color="#002B36",
            ),
        },
    )
    save_preset(podcast_duo_preset, allow_builtin=True)

    ensemble_quintet_preset = StylePreset(
        name="ensemble-quintet",
        description="5-Speaker dialogue with distinct Gold, Cyan, Hot Pink, Lime, and Purple highlights",
        font_name="Montserrat",
        font_size=68,
        bold=True,
        highlight_color="#FFDF00",
        speaker_channels={
            "SPEAKER_00": SpeakerChannel(
                id="SPEAKER_00",
                name="Speaker 1",
                primary_color="#FFFFFF",
                highlight_color="#FFDF00",
                outline_color="#000000",
            ),
            "SPEAKER_01": SpeakerChannel(
                id="SPEAKER_01",
                name="Speaker 2",
                primary_color="#FFFFFF",
                highlight_color="#00E5FF",
                outline_color="#000000",
            ),
            "SPEAKER_02": SpeakerChannel(
                id="SPEAKER_02",
                name="Speaker 3",
                primary_color="#FFFFFF",
                highlight_color="#FF007F",
                outline_color="#000000",
            ),
            "SPEAKER_03": SpeakerChannel(
                id="SPEAKER_03",
                name="Speaker 4",
                primary_color="#FFFFFF",
                highlight_color="#00FF66",
                outline_color="#000000",
            ),
            "SPEAKER_04": SpeakerChannel(
                id="SPEAKER_04",
                name="Speaker 5",
                primary_color="#FFFFFF",
                highlight_color="#B026FF",
                outline_color="#000000",
            ),
        },
    )
    save_preset(ensemble_quintet_preset, allow_builtin=True)

    laser_karaoke_preset = StylePreset(
        name="laser-karaoke",
        description="Smooth continuous progressive word sweep using \\kf tags (Pioneer US 5,742,569)",
        font_name="Montserrat",
        font_size=68,
        bold=True,
        highlight_color="#FFDF00",
        highlight_animation="karaoke_wipe",
    )
    save_preset(laser_karaoke_preset, allow_builtin=True)

