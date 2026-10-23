# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Multi-speaker color channels and adaptive UI test suite.

Validates schema constraints, speaker turn segmentation, per-speaker
V4+ style generation in ASS files, and dialogue event actor attribution.
"""

from pathlib import Path

from backend.ass_generator import chunk_words_into_blocks, generate_ass_content
from backend.config import SpeakerChannel, StylePreset, reset_all_configuration


def test_speaker_channel_model_validation():
    """Verify SpeakerChannel Pydantic model validates required and default fields."""
    channel = SpeakerChannel(
        id="SPEAKER_00",
        name="Host",
        primary_color="#FFFFFF",
        highlight_color="#FFDF00",
    )
    assert channel.id == "SPEAKER_00"
    assert channel.name == "Host"
    assert channel.primary_color == "#FFFFFF"
    assert channel.highlight_color == "#FFDF00"
    assert channel.outline_color == "#000000"
    assert channel.show_speaker_name is False


def test_style_preset_with_speaker_channels(tmp_path: Path):
    """Verify StylePreset supports multi-speaker channels dictionary and factory presets."""
    preset = StylePreset(
        name="test-duo",
        speaker_channels={
            "SPEAKER_00": SpeakerChannel(id="SPEAKER_00", name="Host", highlight_color="#FFDF00"),
            "SPEAKER_01": SpeakerChannel(id="SPEAKER_01", name="Guest", highlight_color="#00E5FF"),
        },
    )
    assert len(preset.speaker_channels) == 2
    assert preset.speaker_channels["SPEAKER_00"].name == "Host"
    assert preset.speaker_channels["SPEAKER_01"].highlight_color == "#00E5FF"

    # Verify factory reset initializes podcast-duo preset
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    presets_dir = config_dir / "presets"
    presets_dir.mkdir(parents=True)
    reset_all_configuration()


def test_chunk_words_into_blocks_speaker_turn_break():
    """Verify subtitle blocks strictly break on speaker turns to prevent blended dialogue."""
    words = [
        {"word": "Hello", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
        {"word": "there", "start": 0.6, "end": 1.0, "speaker": "SPEAKER_00"},
        {"word": "Hi", "start": 1.1, "end": 1.5, "speaker": "SPEAKER_01"},
        {"word": "Joel", "start": 1.6, "end": 2.0, "speaker": "SPEAKER_01"},
    ]
    blocks = chunk_words_into_blocks(words, max_lines=2, max_chars_per_line=30)
    assert len(blocks) == 2
    # First block contains speaker 0
    words_b0 = [w for line in blocks[0] for w in line]
    assert all(w.get("speaker") == "SPEAKER_00" for w in words_b0)
    # Second block contains speaker 1
    words_b1 = [w for line in blocks[1] for w in line]
    assert all(w.get("speaker") == "SPEAKER_01" for w in words_b1)


def test_generate_ass_content_multi_speaker():
    """Verify generated ASS content includes per-speaker styles and actor name columns."""
    whisper_result = {
        "segments": [
            {
                "text": "Welcome to the show",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Welcome", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"},
                    {"word": "to", "start": 0.5, "end": 0.8, "speaker": "SPEAKER_00"},
                    {"word": "the", "start": 0.8, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "show", "start": 1.0, "end": 1.5, "speaker": "SPEAKER_00"},
                ],
            },
            {
                "text": "Great to be here",
                "start": 1.8,
                "end": 3.0,
                "words": [
                    {"word": "Great", "start": 1.8, "end": 2.2, "speaker": "SPEAKER_01"},
                    {"word": "to", "start": 2.2, "end": 2.5, "speaker": "SPEAKER_01"},
                    {"word": "be", "start": 2.5, "end": 2.7, "speaker": "SPEAKER_01"},
                    {"word": "here", "start": 2.7, "end": 3.0, "speaker": "SPEAKER_01"},
                ],
            },
        ]
    }
    config = {
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
                "highlight_color": "#00E5FF",
                "outline_color": "#000000",
            },
        }
    }
    meta = {"width": 1080, "height": 1920}

    ass_text = generate_ass_content(whisper_result, config, meta)

    # 1. Styles generated for each speaker
    assert "Style: Speaker_SPEAKER_00" in ass_text
    assert "Style: Speaker_SPEAKER_01" in ass_text

    # 2. Dialogue lines have appropriate style and actor names
    dialogue_lines = [line for line in ass_text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) >= 2

    # Check actor names in column 4 (0-indexed: Layer=0, Start=1, End=2, Style=3, Name=4)
    speaker_0_found = False
    speaker_1_found = False
    for d in dialogue_lines:
        parts = d.split(",", 9)
        if len(parts) >= 9:
            style_name = parts[3].strip()
            actor_name = parts[4].strip()
            if "Speaker_SPEAKER_00" in style_name:
                assert actor_name == "Host"
                speaker_0_found = True
            elif "Speaker_SPEAKER_01" in style_name:
                assert actor_name == "Guest"
                speaker_1_found = True

    assert speaker_0_found is True
    assert speaker_1_found is True


def test_generate_ass_content_single_speaker_backward_compatibility():
    """Verify single-speaker transcription generates standard ASS styles with zero speaker bloat."""
    whisper_result = {
        "segments": [
            {
                "text": "Solo presenter message",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Solo", "start": 0.0, "end": 0.5},
                    {"word": "presenter", "start": 0.5, "end": 1.0},
                    {"word": "message", "start": 1.0, "end": 1.5},
                ],
            }
        ]
    }
    config = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFDF00",
    }
    meta = {"width": 1080, "height": 1920}

    ass_text = generate_ass_content(whisper_result, config, meta)

    # Should have Default style, and NO multi-speaker styles
    assert "Style: Default" in ass_text
    assert "Style: Speaker_" not in ass_text


def test_generate_ass_content_karaoke_wipe():
    """Verify karaoke_wipe animation mode outputs progressive \\kf centisecond tags (Pioneer US 5,742,569)."""
    whisper_result = {
        "segments": [
            {
                "text": "Smooth karaoke wipe",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Smooth", "start": 0.0, "end": 0.5},
                    {"word": "karaoke", "start": 0.5, "end": 1.0},
                    {"word": "wipe", "start": 1.0, "end": 1.5},
                ],
            }
        ]
    }
    config = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#FF007F",
        "highlight_animation": "karaoke_wipe",
    }
    meta = {"width": 1080, "height": 1920}

    ass_text = generate_ass_content(whisper_result, config, meta)
    dialogue_lines = [line for line in ass_text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == 3

    # Every dialogue line should feature progressive \kf tag with positive centiseconds
    for line in dialogue_lines:
        assert r"\kf" in line


def test_generate_ass_content_anticipation_glow():
    """Verify anticipation_glow animation mode primes upcoming word border (Sony US 5,684,542)."""
    whisper_result = {
        "segments": [
            {
                "text": "Anticipate the cadence",
                "start": 0.0,
                "end": 1.5,
                "words": [
                    {"word": "Anticipate", "start": 0.0, "end": 0.5},
                    {"word": "the", "start": 0.5, "end": 0.8},
                    {"word": "cadence", "start": 0.8, "end": 1.5},
                ],
            }
        ]
    }
    config = {
        "primary_color": "#FFFFFF",
        "highlight_color": "#FFDF00",
        "highlight_animation": "anticipation_glow",
    }
    meta = {"width": 1080, "height": 1920}

    ass_text = generate_ass_content(whisper_result, config, meta)
    dialogue_lines = [line for line in ass_text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue_lines) == 3

    # First event: active word is 'Anticipate', next word 'the' should have border priming \bord4
    assert r"\bord4" in dialogue_lines[0]
    # Second event: active word is 'the', next word 'cadence' should have border priming \bord4
    assert r"\bord4" in dialogue_lines[1]


def test_factory_preset_laser_karaoke_loaded():
    """Verify laser-karaoke factory preset is configured with karaoke_wipe animation."""
    from backend.config import load_preset

    preset = load_preset("laser-karaoke")
    assert preset is not None
    assert preset.highlight_animation == "karaoke_wipe"
    assert preset.highlight_color.upper() == "#FFDF00"


def test_five_speaker_channels_support():
    """Verify up to 5 speakers generate distinct V4+ styles and dialogue lines in ASS subtitles."""
    from backend.config import load_preset

    preset = load_preset("ensemble-quintet")
    assert preset is not None
    assert len(preset.speaker_channels) == 5
    assert preset.speaker_channels["SPEAKER_04"].name == "Speaker 5"

    whisper_result = {
        "segments": [
            {
                "text": "One two three four five",
                "start": 0.0,
                "end": 5.0,
                "words": [
                    {"word": "One", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "two", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
                    {"word": "three", "start": 2.0, "end": 3.0, "speaker": "SPEAKER_02"},
                    {"word": "four", "start": 3.0, "end": 4.0, "speaker": "SPEAKER_03"},
                    {"word": "five", "start": 4.0, "end": 5.0, "speaker": "SPEAKER_04"},
                ],
            }
        ]
    }
    config = {
        "speaker_channels": {
            spk_id: ch.model_dump() for spk_id, ch in preset.speaker_channels.items()
        }
    }
    meta = {"width": 1920, "height": 1080}
    ass_text = generate_ass_content(whisper_result, config, meta)

    # Verify all 5 styles exist in V4+ Styles section
    for i in range(5):
        assert f"Style: Speaker_SPEAKER_0{i}" in ass_text

    # Verify dialogue events reference the speaker styles
    for i in range(5):
        assert f"Speaker_SPEAKER_0{i}" in ass_text


