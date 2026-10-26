# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for timeline keyframe configuration, serialization, and ASS generation.

Validates that:
1. KeyframeConfig validates timestamps, labels, and styling snapshots.
2. StylePreset persists and restores keyframes from YAML.
3. resolve_styling_at_time keeps keyframe styles in effect to the right
   of the timeline until another keyframe is encountered.
4. generate_ass_content applies distinct styling to dialogue events
   based on the active keyframe at their start time.
5. update_ass_formatting updates existing dialogue lines according
   to keyframe timeline ranges.
"""

from pathlib import Path

from backend.ass_generator import (
    generate_ass_content,
    parse_ass_timestamp,
    resolve_styling_at_time,
    update_ass_formatting,
)
from backend.config import (
    KeyframeConfig,
    StylePreset,
    load_preset,
    save_preset,
)


def test_keyframe_config_validation():
    """Verify KeyframeConfig validates non-negative time and accepts arbitrary styling snapshot dicts."""
    kf = KeyframeConfig(
        id="kf_test_1",
        time=12.5,
        label="Chorus Intro",
        styling={
            "font_size": 72,
            "primary_color": "#00FFFF",
            "pos_y_pct": 65.0,
        },
    )
    assert kf.time == 12.5
    assert kf.label == "Chorus Intro"
    assert kf.styling["font_size"] == 72
    assert kf.styling["primary_color"] == "#00FFFF"


def test_style_preset_with_keyframes_yaml_roundtrip(tmp_path: Path, monkeypatch):
    """Verify StylePreset with keyframes serializes to YAML and roundtrips without data loss."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    preset = StylePreset(
        name="custom-keyframe-showcase",
        description="Preset with two distinct timeline keyframes",
        font_name="Montserrat",
        font_size=68,
        primary_color="#FFFFFF",
        highlight_color="#FFDF00",
        keyframes=[
            KeyframeConfig(
                id="kf_0",
                time=0.0,
                label="Opening",
                styling={
                    "font_size": 60,
                    "highlight_color": "#FFDF00",
                    "pos_y_pct": 80.0,
                },
            ),
            KeyframeConfig(
                id="kf_1",
                time=15.0,
                label="Midpoint Action",
                styling={
                    "font_size": 75,
                    "highlight_color": "#FF007F",
                    "pos_y_pct": 50.0,
                },
            ),
        ],
    )

    saved_path = save_preset(preset)
    assert saved_path.exists()

    loaded = load_preset("custom-keyframe-showcase")
    assert loaded.name == "custom-keyframe-showcase"
    assert len(loaded.keyframes) == 2
    assert loaded.keyframes[0].time == 0.0
    assert loaded.keyframes[0].styling["highlight_color"] == "#FFDF00"
    assert loaded.keyframes[1].time == 15.0
    assert loaded.keyframes[1].styling["highlight_color"] == "#FF007F"
    assert loaded.keyframes[1].styling["pos_y_pct"] == 50.0


def test_style_stays_in_effect_to_the_right_of_timeline_until_next_keyframe():
    """Verify that a keyframe's style remains in effect for all time points to the right

    of its timestamp until the exact moment the subsequent keyframe is encountered.
    """
    keyframes = [
        {
            "id": "kf_1",
            "time": 10.0,
            "styling": {
                "font_size": 80,
                "highlight_color": "#FF0000",
                "pos_y_pct": 70.0,
            },
        },
        {
            "id": "kf_2",
            "time": 25.0,
            "styling": {
                "font_size": 55,
                "highlight_color": "#00FF00",
                "pos_y_pct": 30.0,
            },
        },
    ]

    base_config = {
        "font_size": 68,
        "highlight_color": "#FFFFFF",
        "pos_y_pct": 80.0,
    }

    # 1. Before first keyframe (< 10.0s): Base config applies
    res_early = resolve_styling_at_time(0.0, keyframes, base_config)
    assert res_early["font_size"] == 68
    assert res_early["highlight_color"] == "#FFFFFF"

    res_pre = resolve_styling_at_time(9.99, keyframes, base_config)
    assert res_pre["font_size"] == 68
    assert res_pre["highlight_color"] == "#FFFFFF"

    # 2. At first keyframe (10.0s): KF 1 takes effect
    res_kf1 = resolve_styling_at_time(10.0, keyframes, base_config)
    assert res_kf1["font_size"] == 80
    assert res_kf1["highlight_color"] == "#FF0000"
    assert res_kf1["pos_y_pct"] == 70.0

    # 3. To the right of KF 1 (10.0s to 24.99s): KF 1 style STAYS in effect
    res_mid1 = resolve_styling_at_time(12.5, keyframes, base_config)
    assert res_mid1["font_size"] == 80
    assert res_mid1["highlight_color"] == "#FF0000"

    res_mid2 = resolve_styling_at_time(24.95, keyframes, base_config)
    assert res_mid2["font_size"] == 80
    assert res_mid2["highlight_color"] == "#FF0000"

    # 4. At second keyframe (25.0s): KF 2 takes effect
    res_kf2 = resolve_styling_at_time(25.0, keyframes, base_config)
    assert res_kf2["font_size"] == 55
    assert res_kf2["highlight_color"] == "#00FF00"
    assert res_kf2["pos_y_pct"] == 30.0

    # 5. To the right of KF 2 (25.0s and beyond): KF 2 style STAYS in effect
    res_late1 = resolve_styling_at_time(45.0, keyframes, base_config)
    assert res_late1["font_size"] == 55
    assert res_late1["highlight_color"] == "#00FF00"

    res_late2 = resolve_styling_at_time(300.0, keyframes, base_config)
    assert res_late2["font_size"] == 55
    assert res_late2["highlight_color"] == "#00FF00"


def test_generate_ass_content_with_multiple_keyframes():
    """Verify generate_ass_content applies distinct positions and colors based on keyframes."""
    whisper_result = {
        "segments": [
            {
                "text": "Hello early scene. Welcome to middle action.",
                "start": 2.0,
                "end": 20.0,
                "words": [
                    {"word": "Hello", "start": 2.0, "end": 2.5},
                    {"word": "early", "start": 2.6, "end": 3.0},
                    {"word": "scene.", "start": 3.1, "end": 3.8},
                    {"word": "Welcome", "start": 12.0, "end": 12.5},
                    {"word": "to", "start": 12.6, "end": 12.8},
                    {"word": "middle", "start": 12.9, "end": 13.5},
                    {"word": "action.", "start": 13.6, "end": 14.2},
                ],
            }
        ]
    }

    config = {
        "pos_x_pct": 50.0,
        "pos_y_pct": 80.0,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFDF00",
        "font_size": 60,
        "keyframes": [
            {
                "time": 0.0,
                "styling": {
                    "pos_y_pct": 85.0,
                    "highlight_color": "#00FFAA",
                },
            },
            {
                "time": 10.0,
                "styling": {
                    "pos_y_pct": 40.0,
                    "highlight_color": "#FF0055",
                },
            },
        ],
    }

    video_meta = {"width": 1080, "height": 1920}
    ass_out = generate_ass_content(whisper_result, config, video_meta)

    # 1. First block at 2.0s is in KF 1 range (0.0s <= t < 10.0s)
    # y position = 1920 * 0.85 = 1632
    assert "\\pos(540,1632)" in ass_out
    # Active color for 0.0s keyframe is #00FFAA -> ASS color &H00AAFF00&
    assert "&H00AAFF00&" in ass_out

    # 2. Second block at 12.0s is in KF 2 range (t >= 10.0s)
    # y position = 1920 * 0.40 = 768
    assert "\\pos(540,768)" in ass_out
    # Active color for 10.0s keyframe is #FF0055 -> ASS color &H005500FF&
    assert "&H005500FF&" in ass_out


def test_parse_ass_timestamp():
    """Verify ASS timestamp parsing into decimal seconds."""
    assert parse_ass_timestamp("0:00:00.00") == 0.0
    assert abs(parse_ass_timestamp("0:01:15.50") - 75.50) < 1e-3
    assert abs(parse_ass_timestamp("1:02:03.25") - 3723.25) < 1e-3
    assert abs(parse_ass_timestamp("02:30.00") - 150.0) < 1e-3


def test_update_ass_formatting_with_keyframes_right_stay_in_effect():
    """Verify that update_ass_formatting keeps keyframe styles in effect to the right

    of each keyframe on the timeline until the next keyframe is encountered.
    """
    sample_ass = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1000\n"
        "PlayResY: 1000\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,50,&H00FFFFFF&,&H0000FFFF&,&H00000000&,&H80000000&,0,0,0,0,100,100,0,0,1,2,0,2,10,10,50,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:03.00,0:00:05.00,Default,,0,0,0,,{\an5\pos(500,850)}{\c&H0000FFFF&\3c&H00000000&}Early{\c&H00FFFFFF&\3c&H00000000&} line" + "\n"
        r"Dialogue: 0,0:00:14.00,0:00:16.00,Default,,0,0,0,,{\an5\pos(500,850)}{\c&H0000FFFF&\3c&H00000000&}Mid{\c&H00FFFFFF&\3c&H00000000&} line" + "\n"
        r"Dialogue: 0,0:00:22.00,0:00:24.00,Default,,0,0,0,,{\an5\pos(500,850)}{\c&H0000FFFF&\3c&H00000000&}Late{\c&H00FFFFFF&\3c&H00000000&} line" + "\n"
    )

    config = {
        "pos_x_pct": 50.0,
        "pos_y_pct": 80.0,
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFFFFF",
        "keyframes": [
            {
                "time": 10.0,
                "styling": {
                    "pos_y_pct": 70.0,
                    "highlight_color": "#FF0000",
                },
            },
            {
                "time": 20.0,
                "styling": {
                    "pos_y_pct": 30.0,
                    "highlight_color": "#00FF00",
                },
            },
        ],
    }

    video_meta = {"width": 1000, "height": 1000}
    updated_ass = update_ass_formatting(sample_ass, config=config, video_meta=video_meta)
    dialogue_lines = [line for line in updated_ass.splitlines() if line.startswith("Dialogue:")]

    assert len(dialogue_lines) == 3

    # 1. Dialogue at 3.0s (< 10.0s KF1): uses base config y=800, highlight=#FFFFFF (&H00FFFFFF&)
    d1 = dialogue_lines[0]
    assert r"\pos(500,800)" in d1
    assert "&H00FFFFFF&" in d1

    # 2. Dialogue at 14.0s (in [10.0s, 20.0s)): KF1 style stays into effect to the right!
    # y = 1000 * 0.70 = 700, highlight = #FF0000 (&H000000FF&)
    d2 = dialogue_lines[1]
    assert r"\pos(500,700)" in d2
    assert "&H000000FF&" in d2

    # 3. Dialogue at 22.0s (>= 20.0s): KF2 style takes effect at 20.0s and stays into effect to the right!
    # y = 1000 * 0.30 = 300, highlight = #00FF00 (&H0000FF00&)
    d3 = dialogue_lines[2]
    assert r"\pos(500,300)" in d3
    assert "&H0000FF00&" in d3

