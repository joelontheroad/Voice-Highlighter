# SPDX-FileCopyrightText: 2026 Voice Highlighter Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit and integration tests for external text editor launch, folder reveal, and disk-first burning.

Validates that Voice Highlighter respects user choice in desktop text editors (VS Code,
Sublime, gedit, Notepad), reveals folders in native file managers, exposes accurate
disk metadata via /api/ass-file-info, and strictly loads subtitles from disk on video burning.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import (
    BurnVideoRequest,
    OpenFileRequest,
    OpenFolderRequest,
    burn_video_endpoint,
    get_ass_file_info_endpoint,
    open_file_endpoint,
    open_folder_endpoint,
)


def test_open_file_endpoint_launches_editor(tmp_path: Path, monkeypatch):
    """Verify open-file invokes desktop opener with the discrete file argument vector."""
    target_file = tmp_path / "dialogue.ass"
    target_file.write_text("[Script Info]\nTitle: Test\n", encoding="utf-8")

    launched_cmds = []

    def mock_popen(cmd, **kwargs):
        launched_cmds.append(cmd)
        return None

    monkeypatch.setattr("backend.app.subprocess.Popen", mock_popen)
    monkeypatch.setattr("backend.app.platform.system", lambda: "Linux")

    req = OpenFileRequest(file_path=str(target_file))
    res = open_file_endpoint(req, auth="test_auth")

    assert res["success"] is True
    assert res["filename"] == "dialogue.ass"
    assert len(launched_cmds) == 1
    # Mitigate CWE-78: verified discrete argument list without shell=True
    assert launched_cmds[0] == ["xdg-open", str(target_file)]


def test_open_file_endpoint_404_on_missing(tmp_path: Path):
    """Verify open-file raises 404 when targeted file does not exist on disk."""
    req = OpenFileRequest(file_path=str(tmp_path / "nonexistent.ass"))
    with pytest.raises(HTTPException) as exc_info:
        open_file_endpoint(req, auth="test_auth")
    assert exc_info.value.status_code == 404


def test_open_folder_endpoint_launches_file_manager(tmp_path: Path, monkeypatch):
    """Verify open-folder opens directory containing the file in native file manager."""
    sub_dir = tmp_path / "video_project"
    sub_dir.mkdir()
    target_file = sub_dir / "clip.ass"
    target_file.write_text("[Script Info]\n", encoding="utf-8")

    launched_cmds = []

    def mock_popen(cmd, **kwargs):
        launched_cmds.append(cmd)
        return None

    monkeypatch.setattr("backend.app.subprocess.Popen", mock_popen)
    monkeypatch.setattr("backend.app.platform.system", lambda: "Linux")

    req = OpenFolderRequest(file_path=str(target_file))
    res = open_folder_endpoint(req, auth="test_auth")

    assert res["success"] is True
    assert res["directory"] == str(sub_dir)
    assert len(launched_cmds) == 1
    assert launched_cmds[0] == ["xdg-open", str(sub_dir)]


def test_ass_file_info_endpoint_returns_disk_metrics(tmp_path: Path):
    """Verify /api/ass-file-info computes live line and dialogue counts directly from disk."""
    ass_file = tmp_path / "subtitles.ass"
    ass_content = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello world\n"
        "Dialogue: 0,0:00:03.50,0:00:05.50,Default,,0,0,0,,Second sentence on disk\n"
    )
    ass_file.write_text(ass_content, encoding="utf-8")

    res = get_ass_file_info_endpoint(path=str(ass_file))
    assert res["success"] is True
    assert res["filename"] == "subtitles.ass"
    assert res["dialogue_count"] == 2
    assert res["line_count"] == 7
    assert res["size_bytes"] == len(ass_content.encode("utf-8"))
    assert res["size_kb"] >= 0.0


def test_burn_video_strictly_loads_from_disk_ignoring_memory(tmp_path: Path, monkeypatch):
    """Verify burn_video_endpoint strictly reads external disk edits, ignoring in-memory payload."""
    video_file = tmp_path / "interview.mp4"
    video_file.write_text("fake video stream", encoding="utf-8")

    # User manually edited the .ass file in an external text editor like VS Code or Notepad
    disk_ass = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Edited externally in VS Code!\n"
    )
    ass_file = tmp_path / "interview.ass"
    ass_file.write_text(disk_ass, encoding="utf-8")

    burned_ass_captured = []

    def mock_burn(video_in, ass_in, video_out, **kwargs):
        # Capture the content of the ASS file passed to FFmpeg
        with open(ass_in, "r", encoding="utf-8") as f:
            burned_ass_captured.append(f.read())
        Path(video_out).write_text("rendered mp4", encoding="utf-8")

    monkeypatch.setattr("backend.app._safe_burn", mock_burn)
    monkeypatch.setattr("backend.app.get_video_metadata", lambda _: {"width": 1920, "height": 1080, "duration": 3.0})

    # Client browser sends stale content in memory buffer
    stale_memory_content = "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,STALE IN-MEMORY TEXT"
    req = BurnVideoRequest(
        video_path=str(video_file),
        ass_path=str(ass_file),
        content=stale_memory_content,
        styling_modified=False,
    )

    res = burn_video_endpoint(req, auth="test_auth")
    assert res["success"] is True

    # Critical requirement: FFmpeg burned the external disk edits, NOT the stale in-memory text
    assert len(burned_ass_captured) == 1
    assert "Edited externally in VS Code!" in burned_ass_captured[0]
    assert "STALE IN-MEMORY TEXT" not in burned_ass_captured[0]
