# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test suite for preset update workflows and built-in preset protection.

Validates that user-defined presets can be created, updated, and persisted to disk,
while built-in factory presets (default, tiktok-bold, podcast-duo, laser-karaoke)
are strictly immutable and protected against user modification or deletion.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import delete_preset_endpoint, save_preset_endpoint
from backend.config import (
    DEFAULT_PRESET_NAMES,
    StylePreset,
    delete_preset,
    load_preset,
    save_preset,
)


def test_cannot_overwrite_builtin_presets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that attempting to overwrite any built-in preset raises ValueError."""
    test_presets_dir = tmp_path / "presets"
    test_presets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.config.get_presets_dir", lambda: test_presets_dir)

    for name in DEFAULT_PRESET_NAMES:
        preset = StylePreset(
            name=name,
            font_size=99,
            highlight_color="#FF0000",
        )
        with pytest.raises(ValueError, match="Cannot overwrite protected built-in preset"):
            save_preset(preset, allow_builtin=False)


def test_cannot_delete_builtin_presets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that attempting to delete any built-in preset returns False."""
    test_presets_dir = tmp_path / "presets"
    test_presets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.config.get_presets_dir", lambda: test_presets_dir)

    for name in DEFAULT_PRESET_NAMES:
        deleted = delete_preset(name)
        assert deleted is False, f"Expected delete_preset('{name}') to return False"


def test_custom_preset_create_and_update_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that custom presets can be created, updated with new styling, and reloaded."""
    test_presets_dir = tmp_path / "presets"
    test_presets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.config.get_presets_dir", lambda: test_presets_dir)

    # 1. Initial creation
    initial_preset = StylePreset(
        name="creator_neon",
        font_name="Montserrat",
        font_size=64,
        highlight_color="#00E5FF",
        pos_y_pct=72.0,
        line_width_pct=80.0,
    )
    saved_path = save_preset(initial_preset)
    assert saved_path.exists()

    loaded = load_preset("creator_neon")
    assert loaded.font_size == 64
    assert loaded.highlight_color == "#00E5FF"
    assert loaded.line_width_pct == 80.0

    # 2. Update existing custom preset with new styling
    updated_preset = StylePreset(
        name="creator_neon",
        font_name="Outfit",
        font_size=74,
        highlight_color="#FFDF00",
        pos_y_pct=68.0,
        line_width_pct=86.0,
        max_lines=2,
    )
    updated_path = save_preset(updated_preset)
    assert updated_path == saved_path

    # 3. Verify updated values on reload
    reloaded = load_preset("creator_neon")
    assert reloaded.font_name == "Outfit"
    assert reloaded.font_size == 74
    assert reloaded.highlight_color == "#FFDF00"
    assert reloaded.pos_y_pct == 68.0
    assert reloaded.line_width_pct == 86.0
    assert reloaded.max_lines == 2

    # 4. Clean deletion
    assert delete_preset("creator_neon") is True
    assert not saved_path.exists()


def test_api_endpoints_preset_protection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate that API endpoints return HTTP 400 when attempting to overwrite or delete default presets."""
    test_presets_dir = tmp_path / "presets"
    test_presets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.config.get_presets_dir", lambda: test_presets_dir)

    # Attempt to overwrite 'default' via API endpoint
    default_payload = StylePreset(name="default", font_size=80)
    with pytest.raises(HTTPException) as exc_info:
        save_preset_endpoint(default_payload, auth="test-token")
    assert exc_info.value.status_code == 400
    assert "Cannot overwrite protected built-in preset" in exc_info.value.detail

    # Attempt to delete 'tiktok-bold' via API endpoint
    with pytest.raises(HTTPException) as del_exc_info:
        delete_preset_endpoint("tiktok-bold", auth="test-token")
    assert del_exc_info.value.status_code == 400
    assert "Cannot delete default preset" in del_exc_info.value.detail
