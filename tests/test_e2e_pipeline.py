# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""End-to-End Test Harness for Subtitle Keyframe Burning Parity.

Verifies:
1. Disk ASS file as the Single Source of Truth for timeline keyframes and speaker channels.
2. Parity between frontend ASS dialogue queries and video burning output.
3. Transition from solo monologue (t < 28s) to multi-speaker soundbites (t >= 28s)
   with accurate Style names, Actor fields, and speaker name prefixes baked into disk ASS.
4. Video burning execution via FFmpeg creating valid MP4 video streams.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app import (
    BurnVideoRequest,
    KeyframeUpdateRequest,
    SpeakerChannelUpdateRequest,
    burn_video_endpoint,
    get_ass_content,
    update_keyframe_endpoint,
    update_speaker_channel_endpoint,
)
from backend.ass_generator import extract_ass_metadata, parse_ass_timestamp, update_ass_formatting

# Path to real project reference assets
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_ASS_PATH = PROJECT_ROOT / "scratch" / "uploads" / "win-win-parking-benefits-pgm-rough-cut_voice_titles.ass"
REAL_MP4_PATH = PROJECT_ROOT / "scratch" / "uploads" / "katie-height35.mp4"


def _create_fast_test_video(output_mp4: Path, duration: float = 6.0) -> None:
    """Generate a lightweight valid MP4 test video via FFmpeg testsrc filter.

    Args:
        output_mp4: Path where test MP4 should be created.
        duration: Duration in seconds.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=1080x1920:rate=24",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output_mp4),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_end_to_end_keyframe_burning_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify keyframe timeline transition and burning parity using real project assets.

    Keyframe 1 (t=0.0s): Single-speaker monologue (Default style, no prefix).
    Keyframe 2 (t=28.0s): Multi-speaker soundbites (Diane, Stephanie, Jennifer)
    with accurate Actor fields and [Speaker Name]: prefixes.
    """
    # Isolate environment directories
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)

    # 1. Setup real ASS script on disk
    assert REAL_ASS_PATH.exists(), f"Reference ASS fixture missing at {REAL_ASS_PATH}"
    ass_file = media_dir / "parking_benefits.ass"
    shutil.copy2(REAL_ASS_PATH, ass_file)

    # Setup fast test video in sibling directory
    video_file = media_dir / "parking_benefits.mp4"
    _create_fast_test_video(video_file, duration=5.0)

    # Ground truth soundbite segments for parking benefits
    segments = [
        {"start": 0.03, "end": 26.71, "speaker": "SPEAKER_00"},
        {"start": 30.85, "end": 34.80, "speaker": "SPEAKER_01"},  # Diane Kearns-Osterweil ("Street lights.")
        {"start": 35.17, "end": 39.50, "speaker": "SPEAKER_02"},  # Stephanie Bazan ("Inventures. Benches.")
        {"start": 40.24, "end": 45.02, "speaker": "SPEAKER_03"},  # Jennifer Franklin ("Parking benefit district...")
    ]

    speaker_channels = {
        "SPEAKER_01": {
            "id": "SPEAKER_01",
            "name": "Diane Kearns-Osterweil",
            "highlight_color": "#00E5FF",
            "primary_color": "#FFFFFF",
            "show_speaker_name": True,
        },
        "SPEAKER_02": {
            "id": "SPEAKER_02",
            "name": "Stephanie Bazan",
            "highlight_color": "#00FF66",
            "primary_color": "#FFFFFF",
            "show_speaker_name": True,
        },
        "SPEAKER_03": {
            "id": "SPEAKER_03",
            "name": "Jennifer Franklin",
            "highlight_color": "#FF007F",
            "primary_color": "#FFFFFF",
            "show_speaker_name": True,
        },
    }

    keyframes = [
        {
            "id": "kf_intro",
            "time": 0.0,
            "label": "Keyframe @ 00:00",
            "styling": {
                "isMultiSpeaker": False,
                "is_multi_speaker": False,
                "font_name": "Montserrat",
                "font_size": 68,
                "pos_y_pct": 77.0,
            },
        },
        {
            "id": "kf_soundbites",
            "time": 28.0,
            "label": "Keyframe @ 00:28",
            "styling": {
                "isMultiSpeaker": True,
                "is_multi_speaker": True,
                "font_name": "Montserrat",
                "font_size": 68,
                "pos_y_pct": 77.0,
                "speaker_channels": speaker_channels,
                "speaker_count": 4,
            },
        },
    ]

    # 2. Invoke update_keyframe_endpoint to persist keyframes to disk ASS
    kf_req = KeyframeUpdateRequest(
        task_id="task_e2e_kf",
        media_path=str(video_file),
        ass_path=str(ass_file),
        keyframes=keyframes,
        styling={
            "font_name": "Montserrat",
            "font_size": 68,
            "segments": segments,
            "speaker_channels": speaker_channels,
            "is_multi_speaker": True,
        },
    )

    update_resp = update_keyframe_endpoint(kf_req, auth="dummy")
    assert update_resp["status"] == "success"
    assert update_resp["dialogue_count"] > 0

    # 3. Inspect disk ASS file directly - assert Single Source of Truth
    disk_ass_content = ass_file.read_text(encoding="utf-8")
    meta = extract_ass_metadata(disk_ass_content)

    assert meta.get("keyframes") is not None, "Missing ; VoiceHighlighterKeyframes comment on disk"
    assert len(meta["keyframes"]) == 2
    assert float(meta["keyframes"][0]["time"]) == 0.0
    assert float(meta["keyframes"][1]["time"]) == 28.0

    # 4. Assert dialogue lines before t=28s have Default style, empty Actor, and no prefix
    intro_lines = [
        line for line in disk_ass_content.splitlines()
        if line.startswith("Dialogue:") and parse_ass_timestamp(line.split(",", 9)[1]) < 28.0
    ]
    assert len(intro_lines) > 0, "Expected dialogue lines before 28s"
    for line in intro_lines[:15]:
        parts = line.split(",", 9)
        assert parts[3].strip() == "Default", f"Intro line should be Default style: {line}"
        assert parts[4].strip() == "", f"Intro line should have empty actor: {line}"
        assert not re.search(r'\[[^\]]+\]:\s*', parts[9]), f"Intro line should have no speaker prefix: {line}"

    # 5. Assert dialogue soundbite lines after t=28s have Speaker styles, Actor, and prefix
    soundbite_lines = [
        line for line in disk_ass_content.splitlines()
        if line.startswith("Dialogue:") and parse_ass_timestamp(line.split(",", 9)[1]) >= 28.0
    ]
    assert len(soundbite_lines) > 0, "Expected dialogue soundbites after 28s"

    # Find specific speaker soundbites
    diane_lines = [d_line for d_line in soundbite_lines if "lights" in d_line.lower()]
    stephanie_lines = [d_line for d_line in soundbite_lines if "benches" in d_line.lower()]
    jennifer_lines = [d_line for d_line in soundbite_lines if "parking benefit" in d_line.lower() and "revenue" in d_line.lower()]

    assert len(diane_lines) > 0, "Missing Diane Kearns-Osterweil soundbite ('street lights')"
    diane_parts = diane_lines[0].split(",", 9)
    assert diane_parts[3].strip() == "Speaker_SPEAKER_01"
    assert diane_parts[4].strip() == "Diane Kearns-Osterweil"
    assert "\\NDiane Kearns-Osterweil" in diane_parts[9]

    assert len(stephanie_lines) > 0, "Missing Stephanie Bazan soundbite ('and benches')"
    stephanie_parts = stephanie_lines[0].split(",", 9)
    assert stephanie_parts[3].strip() == "Speaker_SPEAKER_02"
    assert stephanie_parts[4].strip() == "Stephanie Bazan"
    assert "\\NStephanie Bazan" in stephanie_parts[9]

    assert len(jennifer_lines) > 0, "Missing Jennifer Franklin soundbite ('Parking benefit district revenue')"
    jennifer_parts = jennifer_lines[0].split(",", 9)
    assert jennifer_parts[3].strip() == "Speaker_SPEAKER_03"
    assert jennifer_parts[4].strip() == "Jennifer Franklin"
    assert "\\NJennifer Franklin" in jennifer_parts[9]

    # 6. Verify GET /api/ass-content returns exact matching dialogues
    content_resp = get_ass_content(task_id="task_e2e_kf", media_path=str(video_file), ass_path=str(ass_file))
    assert content_resp["dialogue_count"] == len([d_line for d_line in disk_ass_content.splitlines() if d_line.startswith("Dialogue:")])
    assert content_resp["keyframes"] == meta["keyframes"]

    # 7. Execute burn_video_endpoint to verify full burning pipeline
    burn_req = BurnVideoRequest(
        video_path=str(video_file),
        ass_path=str(ass_file),
        task_id="task_e2e_kf",
        output_filename="parking_benefits_burned",
        styling_modified=False,
    )
    burn_resp = burn_video_endpoint(burn_req, auth="dummy")
    burned_mp4 = Path(burn_resp["video_path"])
    assert burned_mp4.exists(), f"Burned MP4 does not exist at {burned_mp4}"
    assert burned_mp4.stat().st_size > 10000, f"Burned MP4 is too small ({burned_mp4.stat().st_size} bytes)"

    # Verify MP4 stream health via ffprobe
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(burned_mp4),
    ]
    probe_res = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    burned_dur = float(probe_res.stdout.strip())
    assert burned_dur > 0, "Burned video has invalid 0 duration"


def test_e2e_single_source_of_truth_metadata_roundtrip(tmp_path: Path):
    """Verify ASS metadata comments survive formatting updates and roundtrips cleanly."""
    base_ass = (
        "[Script Info]\n"
        "; VoiceHighlighterKeyframes: [{\"id\": \"kf_1\", \"time\": 5.0, \"styling\": {\"font_size\": 72}}]\n"
        "; VoiceHighlighterSpeakers: {\"SPEAKER_01\": {\"id\": \"SPEAKER_01\", \"name\": \"Speaker Two\"}}\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,{\pos(960,950)}Early text" + "\n"
        r"Dialogue: 0,0:00:06.00,0:00:09.00,Default,,0,0,0,,{\pos(960,950)}Late text" + "\n"
    )

    # Calling update_ass_formatting with empty config must retain existing keyframes and speakers
    reformatted = update_ass_formatting(base_ass, config={})
    meta = extract_ass_metadata(reformatted)

    assert meta.get("keyframes") is not None
    assert len(meta["keyframes"]) == 1
    assert meta["keyframes"][0]["id"] == "kf_1"
    assert meta["keyframes"][0]["time"] == 5.0
    assert meta.get("speaker_channels") is not None
    assert meta["speaker_channels"]["SPEAKER_01"]["name"] == "Speaker Two"


def test_speaker_channel_live_endpoint_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify POST /api/speaker-channel modifies disk ASS immediately and updates dialogues."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    media_dir = tmp_path / "media"
    media_dir.mkdir(parents=True)
    ass_file = media_dir / "interview.ass"
    video_file = media_dir / "interview.mp4"
    _create_fast_test_video(video_file, duration=2.0)

    ass_file.write_text(
        "[Script Info]\n"
        "; VoiceHighlighterSpeakers: {\"SPEAKER_01\": {\"id\": \"SPEAKER_01\", \"name\": \"Original Name\"}}\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n"
        "Style: Speaker_SPEAKER_01,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:00.50,0:00:01.50,Speaker_SPEAKER_01,Original Name,0,0,0,,{\pos(960,950)}[Original Name]: Hello world" + "\n",
        encoding="utf-8",
    )

    req = SpeakerChannelUpdateRequest(
        task_id="task_spk_live",
        media_path=str(video_file),
        ass_path=str(ass_file),
        speaker_id="SPEAKER_01",
        name="Dr. Jane Doe",
        color="#00FF66",
        styling={"is_multi_speaker": True},
    )

    resp = update_speaker_channel_endpoint(req, auth="dummy")
    assert resp["status"] == "success"
    assert len(resp["dialogues"]) == 1
    assert "Dr. Jane Doe" in resp["dialogues"][0]["clean_text"]

    # Inspect disk
    disk_content = ass_file.read_text(encoding="utf-8")
    assert "\\NDr. Jane Doe" in disk_content
    assert "Original Name" not in disk_content
