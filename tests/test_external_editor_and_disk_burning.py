# SPDX-FileCopyrightText: 2026 Voice Highlighter Contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit and integration tests for external text editor launch, folder reveal, and disk-first burning.

Validates that Voice Highlighter respects user choice in desktop text editors (VS Code,
Sublime, gedit, Notepad), reveals folders in native file managers, exposes accurate
disk metadata via /api/ass-file-info, and strictly loads subtitles from disk on video burning.
"""

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app import (
    BurnVideoRequest,
    OpenFileRequest,
    OpenFolderRequest,
    VideoInfoRequest,
    burn_video_endpoint,
    fetch_video_info,
    get_ass_file_info_endpoint,
    get_task_status,
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


def test_fetch_video_info_detects_voice_titles_ass_variant(tmp_path: Path, monkeypatch):
    """Verify fetch_video_info detects <base_name>_voice_titles.ass as sibling subtitles."""
    video_file = tmp_path / "ad_spot.mp4"
    video_file.write_bytes(b"\x00" * 50)

    # Subtitle file produced by default Voice Highlighter naming convention
    vt_ass_file = tmp_path / "ad_spot_voice_titles.ass"
    vt_content = (
        "[Script Info]\n"
        "Title: Katie Ad\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,Katie Kam for City Council\n"
        "Dialogue: 0,0:00:02.10,0:00:04.00,Default,,0,0,0,,Working for Austin families\n"
    )
    vt_ass_file.write_text(vt_content, encoding="utf-8")

    monkeypatch.setattr(
        "backend.app.get_video_metadata",
        lambda _: {"width": 1080, "height": 1080, "duration": 4.5, "has_video": True, "is_vertical": False},
    )
    monkeypatch.setattr("backend.app.extract_poster_frame", lambda s, d, **kw: d)

    req = VideoInfoRequest(video_path=str(video_file))
    info = fetch_video_info(req)

    assert info["has_existing_ass"] is True
    assert info["existing_ass_path"] == str(vt_ass_file)
    assert info["existing_ass_name"] == "ad_spot_voice_titles.ass"
    assert info["existing_ass_dialogues"] == 2
    assert "Katie Kam for City Council" in info["existing_ass_preview"]


def test_fetch_video_info_picks_newest_mtime_candidate(tmp_path: Path, monkeypatch):
    """Verify fetch_video_info resolves candidate .ass files based on most recent modification time."""
    video_file = tmp_path / "presentation.mp4"
    video_file.write_bytes(b"\x00" * 50)

    older_ass = tmp_path / "presentation.ass"
    older_ass.write_text("[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Older text\n", encoding="utf-8")

    newer_ass = tmp_path / "presentation_voice_titles.ass"
    newer_ass.write_text("[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Newer external edit\n", encoding="utf-8")

    os.utime(older_ass, (1000, 1000))
    os.utime(newer_ass, (2000, 2000))

    monkeypatch.setattr(
        "backend.app.get_video_metadata",
        lambda _: {"width": 1920, "height": 1080, "duration": 5.0, "has_video": True, "is_vertical": False},
    )
    monkeypatch.setattr("backend.app.extract_poster_frame", lambda s, d, **kw: d)

    info = fetch_video_info(VideoInfoRequest(video_path=str(video_file)))
    assert info["has_existing_ass"] is True
    assert info["existing_ass_path"] == str(newer_ass)
    assert info["existing_ass_name"] == "presentation_voice_titles.ass"

    # Now user edits presentation.ass externally
    os.utime(older_ass, (3000, 3000))
    info2 = fetch_video_info(VideoInfoRequest(video_path=str(video_file)))
    assert info2["has_existing_ass"] is True
    assert info2["existing_ass_path"] == str(older_ass)


def test_burn_video_endpoint_handles_fresh_burn_task_id(tmp_path: Path, monkeypatch):
    """Verify burn_video_endpoint creates a unique task record with canonical ass_file and video paths."""
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"\x00" * 100)

    ass_file = tmp_path / "clip_voice_titles.ass"
    ass_file.write_text(
        "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Fresh task burn test\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("backend.app._safe_burn", lambda v_in, a_in, v_out, **kw: Path(v_out).write_text("mp4", encoding="utf-8"))
    monkeypatch.setattr("backend.app.get_video_metadata", lambda _: {"width": 1080, "height": 1080, "duration": 2.0})

    fresh_task_id = "burn_test_unique_12345"
    req = BurnVideoRequest(
        video_path=str(video_file),
        ass_path=str(ass_file),
        task_id=fresh_task_id,
        styling_modified=False,
    )

    res = burn_video_endpoint(req, auth="test_auth")
    assert res["success"] is True
    assert res["task_id"] == fresh_task_id
    assert res["ass_file"] == str(ass_file)

    # Verify task status reflects the completed burn task and contains ass_file
    status = get_task_status(fresh_task_id)
    assert status["status"] == "completed"
    assert status["task_id"] == fresh_task_id
    assert status["ass_file"] == str(ass_file)
    assert status["ass_filename"] == "clip_voice_titles.ass"
    assert status["video_file"] is not None

