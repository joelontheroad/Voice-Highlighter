# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for 3-second longer audio snippets and keyframe/speaker identification in video burning.

Validates that:
1. Diarization audio snippets are extended by 3 seconds (~5.5-6.0 seconds duration).
2. Keyframe timeline transitions (e.g. single-speaker at t=0 to multi-speaker halfway through)
   are accurately baked into ASS dialogue lines with speaker identification text.
3. Speaker renames in multi-speaker channels update the dialogue text prefix [Speaker Name]:.
4. The /api/burn-video endpoint synchronizes timeline keyframes and speaker configurations
   to the disk ASS file prior to executing video burning.
"""
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.app import BurnVideoRequest, burn_video_endpoint, open_browser_window
from backend.ass_generator import update_ass_formatting
from backend.diarizer import diarize_whisper_result


def _generate_synthetic_speech_wav(file_path: str, duration: float = 12.0, sample_rate: int = 16000) -> None:
    """Generate a multi-second WAV file with synthetic pitch variation."""
    t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    # Dual frequency composite signal
    tone1 = np.sin(2 * np.pi * 320 * t)
    tone2 = np.sin(2 * np.pi * 640 * t)
    composite = ((tone1 + tone2) * 0.45 * 32767).astype(np.int16)

    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(composite.tobytes())


def test_voice_snippet_duration_extended_by_three_seconds(tmp_path: Path):
    """Verify acoustic voice snippets are ~5.5-6.0 seconds (3 seconds longer than legacy 2.5-3.0s)."""
    wav_path = str(tmp_path / "long_speech.wav")
    _generate_synthetic_speech_wav(wav_path, duration=15.0)

    # 4 distinct segments spanning 12 seconds with multiple speakers
    whisper_result = {
        "segments": [
            {
                "start": 0.5,
                "end": 6.5,
                "text": "First speaker delivering an extended commentary on the event.",
                "words": [
                    {"word": "First", "start": 0.5, "end": 1.5},
                    {"word": "speaker", "start": 1.6, "end": 2.8},
                    {"word": "commentary", "start": 3.0, "end": 6.5},
                ],
            },
            {
                "start": 7.0,
                "end": 13.0,
                "text": "Second speaker providing a detailed counter-perspective response.",
                "words": [
                    {"word": "Second", "start": 7.0, "end": 8.0},
                    {"word": "speaker", "start": 8.2, "end": 9.5},
                    {"word": "response", "start": 10.0, "end": 13.0},
                ],
            },
        ]
    }

    result, samples = diarize_whisper_result(
        audio_wav_path=wav_path,
        whisper_result=whisper_result,
        min_speakers=2,
        max_speakers=2,
        target_speakers=2,
    )

    assert len(samples) >= 1
    for spk_id, meta in samples.items():
        dur = meta["duration"]
        # Snippets must be at least 4.5 seconds and capped at ~6.0s (extended by 3s from legacy 2.5s)
        assert dur >= 4.5, f"Snippet for {spk_id} duration {dur}s is too short (expected >= 4.5s)"
        assert dur <= 6.5, f"Snippet for {spk_id} duration {dur}s is too long (expected <= 6.5s)"
        # Verify valid WAV bytes matching duration
        assert len(meta["bytes"]) > 0
        assert meta["bytes"][:4] == b"RIFF"


def test_single_speaker_fallback_duration_extended(tmp_path: Path):
    """Verify single-speaker fallback snippet duration is ~5.5-6.0 seconds."""
    wav_path = str(tmp_path / "solo.wav")
    _generate_synthetic_speech_wav(wav_path, duration=8.0)

    whisper_result = {
        "segments": [
            {
                "start": 0.0,
                "end": 7.0,
                "text": "Single presenter keynote address.",
                "words": [{"word": "Single", "start": 0.0, "end": 7.0}],
            }
        ]
    }

    result, samples = diarize_whisper_result(
        audio_wav_path=wav_path,
        whisper_result=whisper_result,
        min_speakers=2,
        max_speakers=2,
    )

    assert "SPEAKER_00" in samples
    solo_dur = samples["SPEAKER_00"]["duration"]
    assert solo_dur >= 4.5
    assert solo_dur <= 6.5


def test_keyframe_boundary_single_to_multi_speaker_burn_identification():
    """Verify keyframes properly toggle single-speaker vs multi-speaker and burn speaker names in text.

    Scenario:
    - User drops Keyframe 1 at t=0.0s (Single speaker mode, no other voices yet).
    - User drops Keyframe 2 at t=30.0s (Multi-speaker mode, other speakers start speaking).
    - Resulting ASS file must have:
      - Dialogue at t=5.0s: Style 'Default', NO speaker prefix text.
      - Dialogue at t=35.0s: Style 'Speaker_SPEAKER_01', speaker prefix '[Alice]: ' baked into text.
    """
    existing_ass = (
        "[Script Info]\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000DFFF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,{\an2\pos(960,950)}{\c&H0000DFFF&}Early{\c&H00FFFFFF&} solo voice" + "\n"
        r"Dialogue: 0,0:00:35.00,0:00:38.00,Speaker_SPEAKER_01,Alice,0,0,0,,{\an2\pos(960,950)}{\c&H0000DFFF&}Second{\c&H00FFFFFF&} speaker joins in" + "\n"
    )

    config = {
        "keyframes": [
            {
                "time": 0.0,
                "label": "Keyframe 1: Solo Intro",
                "styling": {
                    "isMultiSpeaker": False,
                    "pos_y_pct": 88.0,
                },
            },
            {
                "time": 30.0,
                "label": "Keyframe 2: Other Speakers Start",
                "styling": {
                    "isMultiSpeaker": True,
                    "pos_y_pct": 75.0,
                    "speaker_channels": {
                        "SPEAKER_00": {
                            "id": "SPEAKER_00",
                            "name": "Host",
                            "highlight_color": "#FFDF00",
                            "show_speaker_name": True,
                        },
                        "SPEAKER_01": {
                            "id": "SPEAKER_01",
                            "name": "Alice",
                            "highlight_color": "#00E5FF",
                            "show_speaker_name": True,
                        },
                    },
                },
            },
        ],
        "speaker_channels": {
            "SPEAKER_00": {"id": "SPEAKER_00", "name": "Host", "highlight_color": "#FFDF00"},
            "SPEAKER_01": {"id": "SPEAKER_01", "name": "Alice", "highlight_color": "#00E5FF"},
        },
    }

    updated_ass = update_ass_formatting(existing_ass, config=config)
    dialogue_lines = [line for line in updated_ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == 2

    # Line 1 (t=5.0s, Keyframe 1 active): Style is Default, no speaker prefix in text
    d1_parts = dialogue_lines[0].split(",", 9)
    assert d1_parts[3] == "Default"
    assert d1_parts[4] == ""
    assert "[Host]:" not in d1_parts[9]
    assert "[Alice]:" not in d1_parts[9]
    # Pos Y updated according to Keyframe 1 (88% of 1080 = 950)
    assert r"\pos(960,950)" in d1_parts[9]

    # Line 2 (t=35.0s, Keyframe 2 active): Multi-speaker active!
    d2_parts = dialogue_lines[1].split(",", 9)
    assert d2_parts[3] == "Speaker_SPEAKER_01"
    assert d2_parts[4] == "Alice"
    # Speaker name Alice MUST be identified in text for FFmpeg burning!
    assert "\\NAlice" in d2_parts[9]
    # Highlight color for Alice (#00E5FF -> &H00FFE500&) must be present in word tags
    assert "&H00FFE500&" in d2_parts[9]
    # Pos Y updated according to Keyframe 2 (75% of 1080 = 810)
    assert r"\pos(960,810)" in d2_parts[9]


def test_speaker_rename_updates_dialogue_text_prefix():
    """Verify renaming a speaker channel updates the text prefix in ASS dialogue lines."""
    existing_ass = (
        "[Script Info]\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n"
        "Style: Speaker_SPEAKER_01,Arial,50,&H00FFFFFF&,&H0000E5FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:10.00,0:00:14.00,Speaker_SPEAKER_01,Speaker 2,0,0,0,,{\an2\pos(960,950)}[Speaker 2]: {\c&H00E5FF00&}Old{\c&H00FFFFFF&} label" + "\n"
    )

    config = {
        "is_multi_speaker": True,
        "speaker_channels": {
            "SPEAKER_01": {
                "id": "SPEAKER_01",
                "name": "Dr. Watson",
                "highlight_color": "#FF007F",
                "show_speaker_name": True,
            }
        },
    }

    updated = update_ass_formatting(existing_ass, config=config)
    d_line = [line for line in updated.splitlines() if line.startswith("Dialogue:")][0]
    d_parts = d_line.split(",", 9)

    assert d_parts[4] == "Dr. Watson"
    assert "[Speaker 2]:" not in d_parts[9]
    assert "\\NDr. Watson" in d_parts[9]


def test_burn_video_endpoint_synchronizes_keyframes_to_disk(tmp_path: Path, monkeypatch):
    """Verify /api/burn-video synchronizes keyframes and speaker prefixes to disk ASS before burning."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    media_dir = tmp_path / "videos"
    media_dir.mkdir(parents=True)
    video_file = media_dir / "interview.mp4"
    video_file.write_bytes(b"\x00" * 1024)
    ass_file = media_dir / "interview.ass"

    # Initial ASS on disk without keyframe positions or speaker labels
    ass_file.write_text(
        "[Script Info]\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:02.00,0:00:05.00,Default,,0,0,0,,{\an2\pos(960,950)}{\c&H0000D4FF&}Early{\c&H00FFFFFF&} speech" + "\n"
        r"Dialogue: 0,0:00:25.00,0:00:28.00,Speaker_SPEAKER_01,Speaker 2,0,0,0,,{\an2\pos(960,950)}{\c&H0000D4FF&}Late{\c&H00FFFFFF&} speech" + "\n",
        encoding="utf-8",
    )

    req = BurnVideoRequest(
        video_path=str(video_file),
        ass_path=str(ass_file),
        task_id="test_burn_kf_task",
        output_filename="interview_burned",
        styling={
            "keyframes": [
                {
                    "time": 0.0,
                    "styling": {"isMultiSpeaker": False, "pos_y_pct": 90.0},
                },
                {
                    "time": 20.0,
                    "styling": {
                        "isMultiSpeaker": True,
                        "pos_y_pct": 70.0,
                        "speaker_channels": {
                            "SPEAKER_01": {"id": "SPEAKER_01", "name": "Co-Host", "highlight_color": "#00FF66", "show_speaker_name": True}
                        },
                    },
                },
            ],
            "is_multi_speaker": True,
            "speaker_channels": {
                "SPEAKER_01": {"id": "SPEAKER_01", "name": "Co-Host", "highlight_color": "#00FF66", "show_speaker_name": True}
            },
        },
        # Even if styling_modified was sent as False, backend must detect keyframes and synchronize
        styling_modified=False,
    )

    with patch("backend.app.burn_subtitles_to_video") as mock_burner:
        mock_burner.return_value = 0

        res = burn_video_endpoint(req, auth="test_auth")
        assert res["success"] is True

        # Verify disk ASS file was updated with keyframes and speaker names before burning
        disk_content = ass_file.read_text(encoding="utf-8")
        assert "\\NCo-Host" in disk_content
        # 70% of 1080 = 756
        assert r"\pos(960,756)" in disk_content


def test_four_speaker_identification_real_audio():
    """Empirical verification on user's reference file: win-win-parking-benefits-pgm-v1.3.wav.

    Four unique ground truth speakers:
    - Segments 0-4 (0.03s - 26.71s): Katie Kam
    - Segment 5 (30.85s - 31.49s): Diane Kearns-Osterweil ("Street lights.")
    - Segment 6 (35.17s - 35.75s): Stephanie Bazan ("Inventures.")
    - Segment 7 (36.82s - 41.36s): Jennifer Franklin ("Parking benefit district revenue...")

    Diarization must cluster into exactly 4 distinct speakers, assigning Katie Kam to SPEAKER_00,
    Diane to SPEAKER_01, Stephanie to SPEAKER_02, and Jennifer to SPEAKER_03.
    """
    audio_path = Path("/mnt/joelg-docs/Personal/Politics/Katie Kam City Council District 9/katie-videos/Win-Win-Katie/Creative-Funding-Parking-Benefit-Districts/Rendered Movies/win-win-parking-benefits-pgm-v1.3.wav")
    if not audio_path.exists():
        pytest.skip("Reference audio file not present in test environment.")

    whisper_result = {
        "segments": [
            {"start": 0.03, "end": 7.04, "text": "West Campus faces significant challenges with walkability..."},
            {"start": 7.04, "end": 13.56, "text": "and safety. Broken sidewalks, poor lighting, and insufficient..."},
            {"start": 13.56, "end": 15.02, "text": "Let me tell you more about it."},
            {"start": 15.02, "end": 21.00, "text": "Parking benefit districts allow us to dedicate meter revenue..."},
            {"start": 21.00, "end": 26.71, "text": "directly to neighborhood improvements."},
            {"start": 30.85, "end": 31.49, "text": "Street lights."},
            {"start": 35.17, "end": 35.75, "text": "Inventures."},
            {"start": 36.82, "end": 41.36, "text": "Parking benefit district revenue can be used to fix our sidewalks in West Campus."},
        ]
    }

    res, samples = diarize_whisper_result(str(audio_path), whisper_result, target_speakers=4)
    segments = res["segments"]
    assert len(segments) == 8

    # Segments 0-4 must belong to Katie Kam (SPEAKER_00)
    katie_speaker = segments[0]["speaker"]
    for i in range(5):
        assert segments[i]["speaker"] == katie_speaker, f"Segment {i} ({segments[i]['text']}) should be Katie Kam ({katie_speaker}), got {segments[i]['speaker']}"

    # Diane Kearns-Osterweil (Seg 5)
    diane_speaker = segments[5]["speaker"]
    assert diane_speaker != katie_speaker, "Diane Kearns-Osterweil must not be merged with Katie Kam"

    # Stephanie Bazan (Seg 6)
    stephanie_speaker = segments[6]["speaker"]
    assert stephanie_speaker != katie_speaker, "Stephanie Bazan must not be merged with Katie Kam"
    assert stephanie_speaker != diane_speaker, "Stephanie Bazan must not be merged with Diane Kearns-Osterweil"

    # Jennifer Franklin (Seg 7)
    jennifer_speaker = segments[7]["speaker"]
    assert jennifer_speaker != katie_speaker, "Jennifer Franklin must not be merged with Katie Kam"
    assert jennifer_speaker != diane_speaker, "Jennifer Franklin must not be merged with Diane Kearns-Osterweil"
    assert jennifer_speaker != stephanie_speaker, "Jennifer Franklin must not be merged with Stephanie Bazan"

    # Verify 4 distinct speaker samples with 4.5-6.5s duration
    assert len(samples) == 4
    for spk_id, meta in samples.items():
        assert 4.5 <= meta["duration"] <= 6.5, f"Sample for {spk_id} duration {meta['duration']} out of range"
        assert meta["bytes"].startswith(b"RIFF")


def test_open_browser_window_standalone_flags(monkeypatch):
    """Verify open_browser_window launches browser with standalone window arguments (--new-window)."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOICE_HIGHLIGHTER_TESTING", raising=False)

    test_url = "http://127.0.0.1:8672/?token=abc123token"

    # 1. Linux with brave-browser or chrome
    with patch("sys.platform", "linux"), \
         patch("shutil.which") as mock_which, \
         patch("subprocess.Popen") as mock_popen:
        mock_which.side_effect = lambda cmd: "/usr/bin/" + cmd if cmd in ["xdg-settings", "brave-browser"] else None
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="brave-browser.desktop\n")
            open_browser_window(test_url)
            assert mock_popen.called
            call_args = mock_popen.call_args[0][0]
            assert call_args[0] == "brave-browser"
            assert "--new-window" in call_args
            assert test_url in call_args

    # 2. macOS with 'open -n'
    with patch("sys.platform", "darwin"), \
         patch("shutil.which", return_value="/usr/bin/open"), \
         patch("subprocess.Popen") as mock_popen:
        open_browser_window(test_url)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args == ["open", "-n", test_url]

    # 3. Windows with cmd /c start
    with patch("sys.platform", "win32"), \
         patch("subprocess.Popen") as mock_popen:
        open_browser_window(test_url)
        assert mock_popen.called
        call_args = mock_popen.call_args[0][0]
        assert call_args == ["cmd", "/c", "start", "", test_url]


def test_keyframe_burning_preserves_speaker_names_via_segments_lookup():
    """Verify update_ass_formatting uses task segments to restore speaker names when styles were Default."""
    existing_ass = (
        "[Script Info]\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000D4FF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:02.00,0:00:05.00,Default,,0,0,0,,{\an2\pos(960,950)}{\c&H0000D4FF&}Solo{\c&H00FFFFFF&} intro" + "\n"
        r"Dialogue: 0,0:00:30.85,0:00:31.49,Default,,0,0,0,,{\an2\pos(960,950)}{\c&H0000D4FF&}Street{\c&H00FFFFFF&} lights" + "\n"
        r"Dialogue: 0,0:00:36.82,0:00:41.36,Default,,0,0,0,,{\an2\pos(960,950)}{\c&H0000D4FF&}Parking{\c&H00FFFFFF&} revenue" + "\n"
    )

    config = {
        "keyframes": [
            {
                "time": 0.0,
                "styling": {"isMultiSpeaker": False, "pos_y_pct": 88.0},
            },
            {
                "time": 25.0,
                "styling": {
                    "isMultiSpeaker": True,
                    "pos_y_pct": 75.0,
                    "speaker_channels": {
                        "SPEAKER_00": {"id": "SPEAKER_00", "name": "Katie Kam", "highlight_color": "#FFDF00", "show_speaker_name": True},
                        "SPEAKER_01": {"id": "SPEAKER_01", "name": "Diane", "highlight_color": "#00E5FF", "show_speaker_name": True},
                        "SPEAKER_03": {"id": "SPEAKER_03", "name": "Jennifer", "highlight_color": "#00FF66", "show_speaker_name": True},
                    },
                },
            },
        ],
        "speaker_channels": {
            "SPEAKER_00": {"id": "SPEAKER_00", "name": "Katie Kam", "highlight_color": "#FFDF00", "show_speaker_name": True},
            "SPEAKER_01": {"id": "SPEAKER_01", "name": "Diane", "highlight_color": "#00E5FF", "show_speaker_name": True},
            "SPEAKER_03": {"id": "SPEAKER_03", "name": "Jennifer", "highlight_color": "#00FF66", "show_speaker_name": True},
        },
    }

    segments = [
        {"start": 2.0, "end": 5.0, "speaker": "SPEAKER_00"},
        {"start": 30.85, "end": 31.49, "speaker": "SPEAKER_01"},
        {"start": 36.82, "end": 41.36, "speaker": "SPEAKER_03"},
    ]

    updated = update_ass_formatting(existing_ass, config=config, segments=segments)
    dialogues = [line for line in updated.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 3

    # Dialogue 0 (0-25s solo zone): Style Default, no speaker name
    d0_parts = dialogues[0].split(",", 9)
    assert d0_parts[3] == "Default"
    assert "[Katie Kam]:" not in d0_parts[9]

    # Dialogue 1 (30.85s multi zone): Diane matched from segments!
    d1_parts = dialogues[1].split(",", 9)
    assert d1_parts[3] == "Speaker_SPEAKER_01"
    assert d1_parts[4] == "Diane"
    assert "\\NDiane" in d1_parts[9]

    # Dialogue 2 (36.82s multi zone): Jennifer matched from segments!
    d2_parts = dialogues[2].split(",", 9)
    assert d2_parts[3] == "Speaker_SPEAKER_03"
    assert d2_parts[4] == "Jennifer"
    assert "\\NJennifer" in d2_parts[9]
