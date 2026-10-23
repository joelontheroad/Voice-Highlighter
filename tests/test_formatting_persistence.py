# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Test suite for subtitle formatting persistence on burning and re-burning.

Validates that all formatting modifications (highlight colors, styles, positions,
and direct edits to .ass files) are faithfully synchronized and respected whenever
burning occurs without requiring re-transcription.
"""

import os
from pathlib import Path

from backend import __version__
from backend.app import (
    BurnVideoRequest,
    UpdateAssRequest,
    _resolve_ass_file_path,
    burn_video_endpoint,
    get_ass_content,
    get_system_info,
    update_ass_content,
)
from backend.ass_generator import generate_ass_content, hex_to_ass_color, update_ass_formatting
from backend.config import StylePreset, delete_preset, load_preset, save_preset


def _create_sample_whisper_result() -> dict:
    """Generate a deterministic single-speaker Whisper transcript result."""
    return {
        "segments": [
            {
                "text": "Hello and welcome to this video presentation.",
                "start": 0.0,
                "end": 2.5,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.4, "speaker": "SPEAKER_00"},
                    {"word": "and", "start": 0.4, "end": 0.6, "speaker": "SPEAKER_00"},
                    {"word": "welcome", "start": 0.6, "end": 1.1, "speaker": "SPEAKER_00"},
                    {"word": "to", "start": 1.1, "end": 1.3, "speaker": "SPEAKER_00"},
                    {"word": "this", "start": 1.3, "end": 1.6, "speaker": "SPEAKER_00"},
                    {"word": "video", "start": 1.6, "end": 2.0, "speaker": "SPEAKER_00"},
                    {"word": "presentation", "start": 2.0, "end": 2.5, "speaker": "SPEAKER_00"},
                ],
            }
        ]
    }


def _create_multi_speaker_whisper_result() -> dict:
    """Generate a deterministic multi-speaker Whisper transcript result."""
    return {
        "segments": [
            {
                "text": "Welcome to the podcast.",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Welcome", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
                    {"word": "to", "start": 0.5, "end": 0.8, "speaker": "SPEAKER_00"},
                    {"word": "the", "start": 0.8, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "podcast", "start": 1.0, "end": 1.5, "speaker": "SPEAKER_00"},
                ],
            },
            {
                "text": "Thanks for having me.",
                "start": 1.8,
                "end": 3.0,
                "words": [
                    {"word": "Thanks", "start": 1.8, "end": 2.2, "speaker": "SPEAKER_01"},
                    {"word": "for", "start": 2.2, "end": 2.4, "speaker": "SPEAKER_01"},
                    {"word": "having", "start": 2.4, "end": 2.7, "speaker": "SPEAKER_01"},
                    {"word": "me", "start": 2.7, "end": 3.0, "speaker": "SPEAKER_01"},
                ],
            },
        ]
    }


def test_update_ass_formatting_direct_secondary_colour_edit():
    """Verify that editing SecondaryColour directly in .ass syncs dialogue active tags without config."""
    initial_config = {
        "font_name": "Arial",
        "font_size": 22,
        "primary_color": "#FFFFFF",
        "highlight_color": "#00E5FF",  # Default cyan
        "outline_color": "#000000",
    }
    meta = {"width": 1920, "height": 1080}
    ass_content = generate_ass_content(_create_sample_whisper_result(), initial_config, meta)

    # Initial highlight in ASS format is &H00FFE500& (cyan &HAABBGGRR&)
    initial_ass_hl = hex_to_ass_color("#00E5FF", 1.0)
    assert f"\\c{initial_ass_hl}" in ass_content

    # Simulate user opening .ass file and changing highlight color to pure red: #FF0000 -> &H000000FF&
    target_red_ass = "&H000000FF&"
    edited_ass = ass_content.replace(initial_ass_hl, target_red_ass)

    # Run update_ass_formatting with NO config (direct disk burn)
    synced_ass = update_ass_formatting(edited_ass, config=None, video_meta=meta)

    # Styles table must preserve the user-edited SecondaryColour
    assert target_red_ass in synced_ass
    # Dialogue lines must have active word \\c tags updated to &H000000FF&
    assert f"\\c{target_red_ass}" in synced_ass
    # Old cyan highlight tag must not appear anywhere
    assert f"\\c{initial_ass_hl}" not in synced_ass


def test_update_ass_formatting_ui_styling_changes():
    """Verify that changing UI styling parameters updates styles and dialogue events."""
    initial_config = {
        "font_name": "Arial",
        "font_size": 20,
        "primary_color": "#FFFFFF",
        "highlight_color": "#00E5FF",
        "outline_color": "#000000",
        "outline_width": 2,
        "position": "bottom",
    }
    meta = {"width": 1920, "height": 1080}
    ass_content = generate_ass_content(_create_sample_whisper_result(), initial_config, meta)

    # User re-styles in UI without re-transcribing
    new_styling = {
        "font_name": "Roboto",
        "font_size": 30,
        "primary_color": "#D0D0D0",
        "highlight_color": "#FF00FF",  # Magenta
        "outline_color": "#333333",
        "outline_width": 4,
        "bold": True,
        "italic": True,
        "position": "top",
        "highlight_animation": "pop_zoom",
    }
    synced_ass = update_ass_formatting(ass_content, config=new_styling, video_meta=meta)

    expected_hl = hex_to_ass_color("#FF00FF", 1.0)
    expected_pri = hex_to_ass_color("#D0D0D0", 1.0)
    expected_out = hex_to_ass_color("#333333", 1.0)

    # Verify Style line in [V4+ Styles]
    assert "Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour" in synced_ass
    assert "Roboto" in synced_ass
    assert expected_hl in synced_ass
    assert expected_pri in synced_ass
    assert expected_out in synced_ass

    # Verify active word tags in Dialogue lines
    assert f"\\c{expected_hl}" in synced_ass
    assert f"\\c{expected_pri}" in synced_ass
    assert f"\\3c{expected_out}" in synced_ass
    assert "\\fscx108\\fscy108" in synced_ass


def test_update_ass_formatting_multi_speaker_channels():
    """Verify per-speaker highlight colors update independently for multi-speaker turns."""
    config = {
        "speaker_channels": {
            "SPEAKER_00": {
                "id": "SPEAKER_00",
                "name": "Host",
                "primary_color": "#FFFFFF",
                "highlight_color": "#FFDF00",  # Yellow
                "outline_color": "#000000",
            },
            "SPEAKER_01": {
                "id": "SPEAKER_01",
                "name": "Guest",
                "primary_color": "#FFFFFF",
                "highlight_color": "#00E5FF",  # Cyan
                "outline_color": "#000000",
            },
        }
    }
    meta = {"width": 1920, "height": 1080}
    ass_content = generate_ass_content(_create_multi_speaker_whisper_result(), config, meta)

    # Now update Guest (SPEAKER_01) highlight color to green
    updated_config = {
        "speaker_channels": {
            "SPEAKER_00": {
                "id": "SPEAKER_00",
                "name": "Host",
                "primary_color": "#FFFFFF",
                "highlight_color": "#FFDF00",
                "outline_color": "#000000",
            },
            "SPEAKER_01": {
                "id": "SPEAKER_01",
                "name": "Guest",
                "primary_color": "#FFFFFF",
                "highlight_color": "#00FF00",  # Green
                "outline_color": "#000000",
            },
        }
    }
    synced_ass = update_ass_formatting(ass_content, config=updated_config, video_meta=meta)

    green_ass = hex_to_ass_color("#00FF00", 1.0)
    yellow_ass = hex_to_ass_color("#FFDF00", 1.0)

    assert f"\\c{green_ass}" in synced_ass
    assert f"\\c{yellow_ass}" in synced_ass


def test_resolve_ass_file_path_selects_newest_mtime(tmp_path: Path):
    """Verify _resolve_ass_file_path always picks the most recently edited .ass candidate."""
    video_file = tmp_path / "interview.mp4"
    video_file.write_text("fake video data", encoding="utf-8")

    ass_sibling = tmp_path / "interview.ass"
    ass_sibling.write_text("[Events]\nDialogue: 0", encoding="utf-8")

    ass_custom = tmp_path / "interview_voice_titles.ass"
    ass_custom.write_text("[Events]\nDialogue: 1", encoding="utf-8")

    # Set sibling as older, custom as newer
    os.utime(ass_sibling, (1000, 1000))
    os.utime(ass_custom, (2000, 2000))

    resolved_path, _ = _resolve_ass_file_path(media_path=str(video_file))
    assert resolved_path == str(ass_custom)

    # Now user directly edits interview.ass on disk (newer timestamp)
    os.utime(ass_sibling, (3000, 3000))

    resolved_path2, _ = _resolve_ass_file_path(media_path=str(video_file))
    assert resolved_path2 == str(ass_sibling)


def test_burn_video_endpoint_preserves_external_ass_edits(tmp_path: Path, monkeypatch):
    """Verify burn_video_endpoint reads user .ass edits, synchronizes formatting, and burns."""
    video_file = tmp_path / "demo.mp4"
    video_file.write_text("fake video bytes", encoding="utf-8")

    meta = {"width": 1920, "height": 1080}
    initial_config = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#00E5FF",
        "outline_color": "#000000",
    }
    ass_content = generate_ass_content(_create_sample_whisper_result(), initial_config, meta)

    # User changed SecondaryColour in file to purple: #AA00FF -> &H00FF00AA&
    purple_ass = hex_to_ass_color("#AA00FF", 1.0)
    initial_cyan_ass = hex_to_ass_color("#00E5FF", 1.0)
    edited_ass = ass_content.replace(initial_cyan_ass, purple_ass)

    ass_file = tmp_path / "demo.ass"
    ass_file.write_text(edited_ass, encoding="utf-8")

    # Mock burn_subtitles_to_video and get_video_metadata
    burned_ass_paths = []

    def mock_burn(video_in, ass_in, video_out):
        burned_ass_paths.append(ass_in)
        Path(video_out).write_text("burned video", encoding="utf-8")

    monkeypatch.setattr("backend.app.burn_subtitles_to_video", mock_burn)
    monkeypatch.setattr("backend.app.get_video_metadata", lambda _: meta)

    # Call burn_video_endpoint without styling payload (re-burn existing)
    req = BurnVideoRequest(video_path=str(video_file), ass_path=str(ass_file))
    result = burn_video_endpoint(req, auth="test_token")

    assert result["success"] is True
    assert len(burned_ass_paths) == 1

    # Verify the ASS file content burned and saved on disk now has the purple highlight tag
    saved_ass = ass_file.read_text(encoding="utf-8")
    assert f"\\c{purple_ass}" in saved_ass
    assert f"\\c{initial_cyan_ass}" not in saved_ass


def test_update_ass_content_endpoint_reburn(tmp_path: Path, monkeypatch):
    """Verify update_ass_content saves synchronized ASS formatting and re-burns video."""
    video_file = tmp_path / "clip.mp4"
    video_file.write_text("fake video", encoding="utf-8")

    meta = {"width": 1920, "height": 1080}
    initial_config = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#00E5FF",
        "outline_color": "#000000",
    }
    ass_content = generate_ass_content(_create_sample_whisper_result(), initial_config, meta)

    ass_file = tmp_path / "clip.ass"
    ass_file.write_text(ass_content, encoding="utf-8")

    reburned_videos = []

    def mock_burn(video_in, ass_in, video_out):
        reburned_videos.append(video_out)
        Path(video_out).write_text("reburned mp4", encoding="utf-8")

    monkeypatch.setattr("backend.app.burn_subtitles_to_video", mock_burn)
    monkeypatch.setattr("backend.app.get_video_metadata", lambda _: meta)

    # Change highlight color in payload
    updated_styling = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#FF5500",  # Orange
        "outline_color": "#000000",
    }

    req = UpdateAssRequest(
        content=ass_content,
        reburn_video=True,
        media_path=str(video_file),
        ass_path=str(ass_file),
        styling=updated_styling,
        styling_modified=True,
    )

    result = update_ass_content(req=req, auth="test_token")
    assert result["success"] is True
    assert result["reburned"] is True
    assert len(reburned_videos) == 1

    # Verify disk content was updated with the orange highlight color
    orange_ass = hex_to_ass_color("#FF5500", 1.0)
    saved_disk_ass = ass_file.read_text(encoding="utf-8")
    assert f"\\c{orange_ass}" in saved_disk_ass


def test_system_info_version_compliance() -> None:
    """Validate that /api/system-info returns the canonical application SemVer version."""
    info = get_system_info()
    assert info["success"] is True
    assert "version" in info
    assert info["version"] == __version__
    assert info["version"] == "1.1.0"


def test_preset_persistence_cycle(tmp_path: Path, monkeypatch) -> None:
    """Validate that style presets can be serialized, persisted to disk as YAML, and reloaded."""
    test_presets_dir = tmp_path / "presets"
    test_presets_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.config.get_presets_dir", lambda: test_presets_dir)

    preset = StylePreset(
        name="test_custom_style",
        description="My Custom Test Style",
        font_name="Outfit",
        font_size=72,
        bold=True,
        highlight_style="box",
        box_bg_color="#1E293B",
        box_opacity=0.9,
    )

    saved_path = save_preset(preset)
    assert saved_path.exists()
    assert saved_path.name == "test_custom_style.yaml"

    loaded = load_preset("test_custom_style")
    assert loaded.name == "test_custom_style"
    assert loaded.description == "My Custom Test Style"
    assert loaded.font_name == "Outfit"
    assert loaded.box_bg_color == "#1E293B"
    assert loaded.box_opacity == 0.9

    deleted = delete_preset("test_custom_style")
    assert deleted is True
    assert not saved_path.exists()


def test_get_ass_content_includes_video_deliverable_metadata(tmp_path: Path) -> None:
    """Validate that get_ass_content includes video_file and video_filename deliverables."""
    dummy_ass = tmp_path / "sample.ass"
    dummy_ass.write_text(
        "[Script Info]\nTitle: Test\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\k20}Hello\n",
        encoding="utf-8",
    )

    from backend.app import tasks

    test_task_id = "test-task-deliverables-123"
    tasks[test_task_id] = {
        "task_id": test_task_id,
        "ass_file": str(dummy_ass),
        "video_file": "/tmp/media/sample_voice_titles.mp4",
        "custom_filename": "sample_voice_titles",
    }

    res = get_ass_content(task_id=test_task_id)
    assert res["success"] is True
    assert res["has_burned_video"] is True
    assert res["video_file"] == "/tmp/media/sample_voice_titles.mp4"
    assert res["video_filename"] == "sample_voice_titles.mp4"


def test_frontend_deliverable_bar_clean_layout() -> None:
    """Validate that index.html and style.css implement the clean full-filename deliverable bar without overlapping badges."""
    repo_root = Path(__file__).resolve().parent.parent
    html_path = repo_root / "frontend" / "index.html"
    css_path = repo_root / "frontend" / "style.css"

    html_content = html_path.read_text(encoding="utf-8")
    css_content = css_path.read_text(encoding="utf-8")

    # Confirm clean deliverable label and input wrap
    assert 'class="studio-filename-label"' in html_content
    assert "Deliverable Base Name:" in html_content
    assert 'id="outputFilenameInput"' in html_content
    assert 'class="text-input filename-base-input"' in html_content

    # Confirm full filename deliverable chips
    assert 'id="chipActiveAss"' in html_content
    assert 'id="valActiveAss"' in html_content
    assert 'id="statusActiveAss"' in html_content
    assert 'id="chipActiveVideo"' in html_content
    assert 'id="valActiveVideo"' in html_content
    assert 'id="statusActiveVideo"' in html_content

    # Confirm removal of broken extension badge .ass / .mp4
    assert ".ass / .mp4" not in html_content

    # Confirm CSS does not position badges absolutely over input/label
    assert ".studio-filename-bar" in css_content
    assert ".deliverable-asset-chip" in css_content
    assert ".deliverable-chip-name" in css_content


def test_transcode_telemetry_status_reporting() -> None:
    """Verify get_task_status exposes ass_ready and burn_telemetry for UI anti-stall feedback."""
    from backend.app import get_task_status, tasks

    task_id = "test-telemetry-task-999"
    tasks[task_id] = {
        "task_id": task_id,
        "status": "processing",
        "progress": 92.5,
        "stage_message": "Burning subtitles: 45% • ~24s remaining",
        "ass_ready": True,
        "burn_telemetry": {
            "frame": 5400,
            "fps": 182.0,
            "speed": 7.4,
            "current_seconds": 90.0,
            "duration": 200.0,
            "burn_pct": 45.0,
            "eta_seconds": 14.8,
        },
        "burn_video": True,
    }

    res = get_task_status(task_id)
    assert res["status"] == "processing"
    assert res["ass_ready"] is True
    assert res["burn_telemetry"] is not None
    assert res["burn_telemetry"]["fps"] == 182.0
    assert res["burn_telemetry"]["speed"] == 7.4
    assert res["burn_telemetry"]["burn_pct"] == 45.0
    assert res["download_url"] == f"/api/download/{task_id}"


def test_ffmpeg_progress_telemetry_calculation(tmp_path: Path, monkeypatch) -> None:
    """Verify _execute_ffmpeg_with_progress parses out_time_us, speed, and computes ETA."""
    from backend.extractor import _execute_ffmpeg_with_progress

    simulated_stdout = [
        "frame=100\n",
        "fps=50.0\n",
        "speed=2.0x\n",
        "out_time_us=50000000\n",  # 50 seconds
        "progress=continue\n",
        "progress=end\n",
    ]

    class FakeProc:
        def __init__(self):
            self.stdout = simulated_stdout
            self.stderr = []
            self.returncode = 0

        def wait(self):
            return 0

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())

    captured_telemetry = []

    def on_progress(metrics):
        captured_telemetry.append(metrics)

    rc, stderr = _execute_ffmpeg_with_progress(
        cmd=["ffmpeg"],
        cwd=str(tmp_path),
        duration=100.0,  # 100 seconds total
        progress_callback=on_progress,
    )

    assert rc == 0
    assert len(captured_telemetry) >= 1
    last = captured_telemetry[-1]
    assert last["current_seconds"] == 50.0
    assert last["burn_pct"] == 50.0
    assert last["speed"] == 2.0
    assert last["fps"] == 50.0
    assert last["frame"] == 100
    # Remaining 50s / speed 2.0x = 25s ETA
    assert last["eta_seconds"] == 25.0



