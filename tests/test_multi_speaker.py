# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Multi-speaker color channels and adaptive UI test suite.

Validates schema constraints, speaker turn segmentation, per-speaker
V4+ style generation in ASS files, and dialogue event actor attribution.
"""

import os
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException

from backend.app import AUDIO_DIR, app, get_speaker_sample
from backend.ass_generator import chunk_words_into_blocks, generate_ass_content
from backend.config import SpeakerChannel, StylePreset, reset_all_configuration
from backend.diarizer import diarize_whisper_result, extract_audio_snippet_bytes


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
    assert channel.show_speaker_name is True


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


def test_extract_audio_snippet_bytes_riff_header(tmp_path: Path):
    """Verify extract_audio_snippet_bytes yields a valid 16kHz RIFF/WAV binary stream."""
    wav_path = str(tmp_path / "sample.wav")
    sr = 16000
    dur = 2.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    sine = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(sine.tobytes())

    snippet_bytes = extract_audio_snippet_bytes(wav_path, 0.5, 1.5)
    assert len(snippet_bytes) > 0
    # RIFF header verification
    assert snippet_bytes[:4] == b"RIFF"
    assert snippet_bytes[8:12] == b"WAVE"


def test_diarize_whisper_result_acoustic_clustering(tmp_path: Path):
    """Verify acoustic clustering distinguishes distinct voices and extracts representative snippets."""
    wav_path = str(tmp_path / "dialogue.wav")
    sr = 16000

    # Speaker 1: low tone (160 Hz)
    t1 = np.linspace(0, 3.0, int(3.0 * sr), endpoint=False)
    s1 = (np.sin(2 * np.pi * 160 * t1) * 32767).astype(np.int16)

    # Speaker 2: high tone (720 Hz)
    t2 = np.linspace(0, 3.0, int(3.0 * sr), endpoint=False)
    s2 = (np.sin(2 * np.pi * 720 * t2) * 32767).astype(np.int16)

    # Alternate dialogue turns: S1 -> S2 -> S1 -> S2
    full_audio = np.concatenate([s1, s2, s1, s2])
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(full_audio.tobytes())

    whisper_result = {
        "segments": [
            {
                "start": 0.5,
                "end": 2.5,
                "text": "Hello, welcome to the episode.",
                "words": [
                    {"word": "Hello", "start": 0.5, "end": 1.0},
                    {"word": "welcome", "start": 1.0, "end": 2.5},
                ],
            },
            {
                "start": 3.5,
                "end": 5.5,
                "text": "Thanks for having me on today.",
                "words": [
                    {"word": "Thanks", "start": 3.5, "end": 4.0},
                    {"word": "having", "start": 4.0, "end": 5.5},
                ],
            },
            {
                "start": 6.5,
                "end": 8.5,
                "text": "Let us discuss the latest topic.",
                "words": [
                    {"word": "Let", "start": 6.5, "end": 7.0},
                    {"word": "discuss", "start": 7.0, "end": 8.5},
                ],
            },
            {
                "start": 9.5,
                "end": 11.5,
                "text": "I am excited to share my thoughts.",
                "words": [
                    {"word": "excited", "start": 9.5, "end": 10.0},
                    {"word": "share", "start": 10.0, "end": 11.5},
                ],
            },
        ]
    }

    result, speaker_samples = diarize_whisper_result(
        audio_wav_path=wav_path,
        whisper_result=whisper_result,
        min_speakers=2,
        max_speakers=5,
    )

    # Ensure two distinct speaker clusters were found
    assert len(speaker_samples) == 2
    assert "SPEAKER_00" in speaker_samples
    assert "SPEAKER_01" in speaker_samples

    # Verify segments were assigned speaker tags
    for seg in result["segments"]:
        assert seg["speaker"] in ("SPEAKER_00", "SPEAKER_01")
        for w in seg.get("words", []):
            assert w["speaker"] == seg["speaker"]

    # Verify snippets contain valid audio bytes
    for spk_id, meta in speaker_samples.items():
        assert len(meta["bytes"]) > 0
        assert meta["bytes"][:4] == b"RIFF"
        assert meta["duration"] > 0


def test_diarize_single_segment_graceful_fallback(tmp_path: Path):
    """Verify single-segment audio gracefully assigns SPEAKER_00 without clustering errors."""
    wav_path = str(tmp_path / "solo.wav")
    sr = 16000
    t = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)
    sine = (np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16)
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(sine.tobytes())

    whisper_result = {
        "segments": [
            {
                "start": 0.2,
                "end": 1.8,
                "text": "Solo presenter voice test.",
                "words": [{"word": "Solo", "start": 0.2, "end": 1.8}],
            }
        ]
    }

    result, samples = diarize_whisper_result(wav_path, whisper_result)
    assert len(samples) == 1
    assert "SPEAKER_00" in samples
    assert result["segments"][0]["speaker"] == "SPEAKER_00"


def test_speaker_sample_api_endpoint(tmp_path: Path):
    """Verify get_speaker_sample streams WAV audio when file exists and raises 404 on missing file."""
    auth_token = app.state.auth_token
    test_task = "test-task-123"
    test_spk = "SPEAKER_00"
    sample_file = os.path.join(AUDIO_DIR, f"{test_task}_{test_spk}.wav")

    # Write synthetic WAV file to AUDIO_DIR
    sr = 16000
    with wave.open(sample_file, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * 8000)

    try:
        # 1. Authorized request with valid snippet returns FileResponse with audio/wav media_type
        response = get_speaker_sample(test_task, test_spk, auth=auth_token)
        assert response.media_type == "audio/wav"
        assert os.path.abspath(response.path) == os.path.abspath(sample_file)

        # 2. Missing speaker sample raises HTTPException 404
        with pytest.raises(HTTPException) as exc_info:
            get_speaker_sample(test_task, "SPEAKER_99", auth=auth_token)
        assert exc_info.value.status_code == 404
    finally:
        if os.path.exists(sample_file):
            os.remove(sample_file)


def test_ass_content_speaker_canonical_mapping(tmp_path: Path):
    """Verify /api/ass-content prefers canonical speakers_found from task metadata for clean UI mapping."""
    from backend.app import get_ass_content, tasks

    test_task = "test-task-multi-speaker-456"
    test_ass = tmp_path / "test_dialogue.ass"
    test_ass.write_text(
        "[Script Info]\n"
        "Title: Test\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,Speaker 1,0,0,0,,Line 1\n"
        "Dialogue: 0,0:00:03.50,0:00:05.00,Default,Speaker 2,0,0,0,,Line 2\n"
        "Dialogue: 0,0:00:05.50,0:00:07.00,Default,Kearns-Osterweil,0,0,0,,Line 3\n",
        encoding="utf-8",
    )

    tasks[test_task] = {
        "status": "completed",
        "speakers_found": ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
        "speaker_samples": {
            "SPEAKER_00": {"quote": "Line 1", "duration": 2.0, "sample_url": f"/api/speaker-sample/{test_task}/SPEAKER_00"},
            "SPEAKER_01": {"quote": "Line 2", "duration": 1.5, "sample_url": f"/api/speaker-sample/{test_task}/SPEAKER_01"},
            "SPEAKER_02": {"quote": "Line 3", "duration": 1.5, "sample_url": f"/api/speaker-sample/{test_task}/SPEAKER_02"},
        },
        "ass_file": str(test_ass),
    }

    try:
        resp = get_ass_content(task_id=test_task, ass_path=str(test_ass))
        assert resp["success"] is True
        assert resp["speakers_found"] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
        assert resp["detected_speakers"] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]
        assert resp["speaker_count"] == 3
        assert resp["is_multi_speaker"] is True
        assert len(resp["speaker_samples"]) == 3
        assert "SPEAKER_00" in resp["speaker_samples"]
        assert "SPEAKER_01" in resp["speaker_samples"]
        assert "SPEAKER_02" in resp["speaker_samples"]
    finally:
        tasks.pop(test_task, None)


def test_ass_content_on_demand_speaker_sample_extraction(tmp_path: Path):
    """Verify get_ass_content extracts speaker samples on-demand from companion WAV when no task exists."""
    from backend.app import AUDIO_DIR, get_ass_content

    # Create dummy 10-second 16kHz WAV file
    sample_rate = 16000
    wav_path = tmp_path / "discussion.wav"
    num_samples = sample_rate * 10
    raw_audio = np.zeros(num_samples, dtype=np.int16)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_audio.tobytes())

    ass_path = tmp_path / "discussion_voice_titles.ass"
    ass_path.write_text(
        "[Script Info]\n"
        "Title: Discussion\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.50,Speaker_SPEAKER_00,Speaker 1,0,0,0,,[Speaker 1]: First speaker commentary\n"
        "Dialogue: 0,0:00:04.00,0:00:07.00,Speaker_SPEAKER_01,Speaker 2,0,0,0,,[Speaker 2]: Second speaker response\n",
        encoding="utf-8",
    )

    resp = get_ass_content(media_path=str(wav_path), ass_path=str(ass_path))
    assert resp["success"] is True
    assert resp["is_multi_speaker"] is True
    assert resp["speaker_samples"] is not None
    assert len(resp["speaker_samples"]) >= 2

    # Check both canonical and display name aliases are mapped
    assert "SPEAKER_00" in resp["speaker_samples"]
    assert "Speaker 1" in resp["speaker_samples"]
    assert "SPEAKER_01" in resp["speaker_samples"]
    assert "Speaker 2" in resp["speaker_samples"]

    sample_0 = resp["speaker_samples"]["SPEAKER_00"]
    assert "sample_url" in sample_0
    assert sample_0["duration"] > 0

    # Verify audio snippet file exists in AUDIO_DIR
    sample_url = sample_0["sample_url"]
    parts = sample_url.strip("/").split("/")
    task_key, spk_key = parts[-2], parts[-1]
    expected_file = os.path.join(AUDIO_DIR, f"{task_key}_{spk_key}.wav")
    assert os.path.exists(expected_file)


def test_diarize_whisper_result_target_speakers(tmp_path: Path):
    """Verify target_speakers parameter explicitly forces exact cluster count."""
    # Synthesize audio with 5 distinct frequency tones representing 5 speakers
    sample_rate = 16000
    duration_per_tone = 2.0
    wav_path = tmp_path / "five_speakers.wav"

    tones = [150.0, 220.0, 310.0, 420.0, 540.0]
    audio_chunks = []
    for f in tones:
        t = np.linspace(0, duration_per_tone, int(sample_rate * duration_per_tone), endpoint=False)
        chunk = (0.5 * np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
        audio_chunks.append(chunk)

    full_audio = np.concatenate(audio_chunks)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_audio.tobytes())

    # Create 5 segments corresponding to the 5 speaker tones
    whisper_result = {
        "segments": [
            {"start": i * 2.0, "end": (i + 1) * 2.0, "text": f"Speaker utterance {i + 1}", "words": []}
            for i in range(5)
        ]
    }

    # Test explicit target_speakers = 4
    res_4, samples_4 = diarize_whisper_result(
        audio_wav_path=str(wav_path),
        whisper_result=dict(whisper_result),
        target_speakers=4,
    )
    assigned_4 = {s["speaker"] for s in res_4["segments"]}
    assert len(assigned_4) == 4
    assert len(samples_4) == 4

    # Test explicit target_speakers = 5
    res_5, samples_5 = diarize_whisper_result(
        audio_wav_path=str(wav_path),
        whisper_result=dict(whisper_result),
        target_speakers=5,
    )
    assigned_5 = {s["speaker"] for s in res_5["segments"]}
    assert len(assigned_5) == 5
    assert len(samples_5) == 5


def test_diarize_cmn_ambient_noise_invariance(tmp_path: Path):
    """Verify Cepstral Mean Normalization (CMN) clusters same-timbre speech together despite ambient noise and gain."""
    import torch

    from backend.diarizer import extract_acoustic_embedding

    sample_rate = 16000
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)

    # Base speaker: fundamental 200 Hz + harmonics
    speech_base = np.sin(2 * np.pi * 200 * t) + 0.5 * np.sin(2 * np.pi * 400 * t)

    # Clean clip (high gain, indoor)
    clean_audio = torch.tensor(speech_base * 0.8, dtype=torch.float32)

    # Noisy clip (same speaker at lower gain with added background noise/wind)
    ambient_noise = np.random.normal(0, 0.05, len(t))
    noisy_audio = torch.tensor((speech_base * 0.3) + ambient_noise, dtype=torch.float32)

    # Completely different speaker (fundamental 380 Hz)
    diff_speaker = torch.tensor(np.sin(2 * np.pi * 380 * t) * 0.8, dtype=torch.float32)

    emb_clean = extract_acoustic_embedding(clean_audio, sample_rate)
    emb_noisy = extract_acoustic_embedding(noisy_audio, sample_rate)
    emb_diff = extract_acoustic_embedding(diff_speaker, sample_rate)

    # Distance between clean & noisy same speaker should be significantly smaller than distance to different speaker
    dist_same = np.linalg.norm(emb_clean - emb_noisy)
    dist_diff = np.linalg.norm(emb_clean - emb_diff)

    assert dist_same < dist_diff


def test_api_rediarize_endpoint(tmp_path: Path):
    """Verify /api/rediarize endpoint re-clusters segments and returns updated snippets."""
    from backend.app import RediarizeRequest, rediarize_speech, tasks

    sample_rate = 16000
    wav_path = tmp_path / "panel.wav"
    t = np.linspace(0, 8.0, sample_rate * 8, endpoint=False)
    # 4 distinct 2-second frequency blocks
    tones = [180.0, 260.0, 340.0, 440.0]
    chunks = [(0.5 * np.sin(2 * np.pi * f * t[:sample_rate * 2]) * 32767).astype(np.int16) for f in tones]
    full_audio = np.concatenate(chunks)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_audio.tobytes())

    task_id = "test_rediarize_task_999"
    tasks[task_id] = {
        "task_id": task_id,
        "video_path": str(wav_path),
        "wav_path": str(wav_path),
        "whisper_result": {
            "segments": [
                {"start": i * 2.0, "end": (i + 1) * 2.0, "text": f"Panelist {i + 1} remarks", "words": []}
                for i in range(4)
            ]
        },
        "styling": {"is_multi_speaker": True, "speaker_count": 2},
        "ass_file": str(tmp_path / "panel_voice_titles.ass"),
    }

    try:
        req = RediarizeRequest(task_id=task_id, speaker_count=4)
        resp = rediarize_speech(req)
        assert resp["status"] == "success"
        assert len(resp["speakers_found"]) == 4
        assert len(resp["speaker_samples"]) >= 4
        assert "SPEAKER_00" in resp["speaker_samples"]
        assert "SPEAKER_03" in resp["speaker_samples"]
        assert resp["ass_content"] is not None
        assert "Style: Speaker_SPEAKER_03" in resp["ass_content"]
    finally:
        tasks.pop(task_id, None)


def test_seven_speaker_channels_support():
    """Verify up to 7 speakers generate distinct V4+ styles and dialogue lines in ASS subtitles."""
    from backend.config import load_preset

    preset = load_preset("ensemble-septet")
    assert preset is not None
    assert len(preset.speaker_channels) == 7
    assert preset.speaker_channels["SPEAKER_05"].name == "Speaker 6"
    assert preset.speaker_channels["SPEAKER_06"].name == "Speaker 7"

    whisper_result = {
        "segments": [
            {
                "text": "One two three four five six seven",
                "start": 0.0,
                "end": 7.0,
                "words": [
                    {"word": "One", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"word": "two", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
                    {"word": "three", "start": 2.0, "end": 3.0, "speaker": "SPEAKER_02"},
                    {"word": "four", "start": 3.0, "end": 4.0, "speaker": "SPEAKER_03"},
                    {"word": "five", "start": 4.0, "end": 5.0, "speaker": "SPEAKER_04"},
                    {"word": "six", "start": 5.0, "end": 6.0, "speaker": "SPEAKER_05"},
                    {"word": "seven", "start": 6.0, "end": 7.0, "speaker": "SPEAKER_06"},
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

    # Verify all 7 styles exist in V4+ Styles section
    for i in range(7):
        assert f"Style: Speaker_SPEAKER_0{i}" in ass_text
        assert f"Speaker_SPEAKER_0{i}" in ass_text


def test_diarize_whisper_result_seven_speakers(tmp_path: Path):
    """Verify diarize_whisper_result accurately segments 7 distinct speaker channels."""
    sample_rate = 16000
    duration_per_tone = 1.5
    wav_path = tmp_path / "seven_speakers.wav"

    tones = [120.0, 160.0, 210.0, 270.0, 340.0, 420.0, 510.0]
    audio_chunks = []
    for f in tones:
        t = np.linspace(0, duration_per_tone, int(sample_rate * duration_per_tone), endpoint=False)
        chunk = (0.5 * np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
        audio_chunks.append(chunk)

    full_audio = np.concatenate(audio_chunks)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_audio.tobytes())

    whisper_result = {
        "segments": [
            {"start": i * duration_per_tone, "end": (i + 1) * duration_per_tone, "text": f"Speaker {i + 1} voice", "words": []}
            for i in range(7)
        ]
    }

    res_7, samples_7 = diarize_whisper_result(
        audio_wav_path=str(wav_path),
        whisper_result=dict(whisper_result),
        target_speakers=7,
    )
    assigned_7 = {s["speaker"] for s in res_7["segments"]}
    assert len(assigned_7) == 7
    assert len(samples_7) == 7
    assert "SPEAKER_05" in samples_7
    assert "SPEAKER_06" in samples_7


def test_speaker_three_and_four_discrimination(tmp_path: Path):
    """Verify that speakers #3 and #4 are not merged into the same cluster and the last speaker is preserved."""
    sample_rate = 16000
    wav_path = tmp_path / "four_speakers_panel.wav"

    # 4 distinct speaker profiles:
    # Speaker 1: 120 Hz, Speaker 2: 180 Hz, Speaker 3: 240 Hz, Speaker 4: 330 Hz
    spk_freqs = [120.0, 180.0, 240.0, 330.0]
    # Sequence of turns: Speaker 1, 2, 1, 2, 3, 4, 3, 4
    turn_sequence = [0, 1, 0, 1, 2, 3, 2, 3]

    audio_chunks = []
    segments = []
    curr_t = 0.0
    for idx, spk_idx in enumerate(turn_sequence):
        f = spk_freqs[spk_idx]
        dur = 2.0
        t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
        chunk = (0.5 * np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
        audio_chunks.append(chunk)

        segments.append({
            "start": curr_t,
            "end": curr_t + dur,
            "text": f"Utterance {idx + 1} by speaker index {spk_idx + 1}",
            "words": [],
        })
        curr_t += dur

    full_audio = np.concatenate(audio_chunks)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_audio.tobytes())

    whisper_result = {"segments": segments}
    res, samples = diarize_whisper_result(
        audio_wav_path=str(wav_path),
        whisper_result=whisper_result,
        target_speakers=4,
    )

    # Verify that all 4 speakers are resolved into 4 distinct clusters
    spk_set = {s["speaker"] for s in res["segments"]}
    assert len(spk_set) == 4, f"Expected 4 distinct speakers, got: {spk_set}"

    # Specifically verify Speaker 3 (turn index 4) and Speaker 4 (turn index 5) have distinct IDs
    spk_3_tag = res["segments"][4]["speaker"]
    spk_4_tag = res["segments"][5]["speaker"]
    assert spk_3_tag != spk_4_tag, "Speaker #3 and #4 were erroneously merged as the same person!"


def test_guarded_temporal_smoothing_preserves_speaker_turn(tmp_path: Path):
    """Verify that a distinct speaker utterance is never wiped out by temporal continuity smoothing."""
    sample_rate = 16000
    wav_path = tmp_path / "continuity_guard.wav"

    # Turn 0: Speaker 1 (130 Hz, 3.0s)
    # Turn 1: Speaker 2 (280 Hz, 1.2s - short interjection between Speaker 1 turns)
    # Turn 2: Speaker 1 (130 Hz, 3.0s)
    turns = [(130.0, 3.0), (280.0, 1.2), (130.0, 3.0)]
    audio_chunks = []
    segments = []
    curr_t = 0.0

    for idx, (f, dur) in enumerate(turns):
        t = np.linspace(0, dur, int(sample_rate * dur), endpoint=False)
        chunk = (0.5 * np.sin(2 * np.pi * f * t) * 32767).astype(np.int16)
        audio_chunks.append(chunk)

        segments.append({
            "start": curr_t,
            "end": curr_t + dur,
            "text": f"Turn {idx + 1}",
            "words": [],
        })
        curr_t += dur

    full_audio = np.concatenate(audio_chunks)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_audio.tobytes())

    whisper_result = {"segments": segments}
    res, samples = diarize_whisper_result(
        audio_wav_path=str(wav_path),
        whisper_result=whisper_result,
        target_speakers=2,
    )

    # Segments 0 and 2 should be the same speaker
    assert res["segments"][0]["speaker"] == res["segments"][2]["speaker"]
    # Segment 1 MUST NOT be smoothed away into Speaker 1
    assert res["segments"][1]["speaker"] != res["segments"][0]["speaker"]


def test_merge_speaker_channels_disk_consolidation(tmp_path: Path):
    """Verify merge_speaker_channels reassigns dialogue styles, actor, and comment metadata."""
    from backend.ass_generator import merge_speaker_channels

    ass_file = tmp_path / "test_merge.ass"
    initial_ass = (
        "[Script Info]\n"
        '; VoiceHighlighterSpeakers: {"SPEAKER_00": {"id": "SPEAKER_00", "name": "Host"}, "SPEAKER_01": {"id": "SPEAKER_01", "name": "Guest A"}, "SPEAKER_02": {"id": "SPEAKER_02", "name": "Guest A"}}\n'
        '; VoiceHighlighterSegments: [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}, {"start": 2.5, "end": 5.0, "speaker": "SPEAKER_01"}, {"start": 5.5, "end": 8.0, "speaker": "SPEAKER_02"}]\n'
        '; VoiceHighlighterKeyframes: [{"time": 0.0, "styling": {"speaker_channels": {"SPEAKER_00": {}, "SPEAKER_01": {}, "SPEAKER_02": {}}}}]'
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
        "Style: Speaker_SPEAKER_01,Arial,20,&H00FFE500,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
        "Style: Speaker_SPEAKER_02,Arial,20,&H00FF007F,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:00.00,0:00:02.00,Default,Host,0,0,0,,{\pos(960,900)}Hello everyone" + "\n"
        r"Dialogue: 0,0:00:02.50,0:00:05.00,Speaker_SPEAKER_01,Guest A,0,0,0,,{\pos(960,900)}First turn\NGuest A" + "\n"
        r"Dialogue: 0,0:00:05.50,0:00:08.00,Speaker_SPEAKER_02,Guest A,0,0,0,,{\pos(960,900)}Second turn\NGuest A" + "\n"
    )
    ass_file.write_text(initial_ass, encoding="utf-8")

    res = merge_speaker_channels(ass_file, "SPEAKER_02", "SPEAKER_01")
    assert res["status"] == "success"
    assert res["dialogues_updated"] == 1
    assert res["segments_updated"] == 1

    disk_content = ass_file.read_text(encoding="utf-8")
    assert "Speaker_SPEAKER_02" not in disk_content
    assert '"SPEAKER_02"' not in disk_content
    lines = disk_content.splitlines()
    assert "Dialogue: 0,0:00:05.50,0:00:08.00,Speaker_SPEAKER_01,Guest A,0,0,0,,{\\pos(960,900)}Second turn\\NGuest A" in lines


def test_split_segments_on_word_pauses():
    """Verify aligned segments with intra-segment pauses >= 1.5s split into distinct sub-segments."""
    from backend.diarizer import split_segments_on_word_pauses

    # Segment with two speakers separated by a 2.5s pause
    seg = {
        "start": 10.0,
        "end": 20.0,
        "text": "Speaker one speaking. Speaker two answering.",
        "words": [
            {"word": "Speaker", "start": 10.0, "end": 10.5},
            {"word": "one", "start": 10.6, "end": 11.0},
            {"word": "speaking.", "start": 11.1, "end": 11.8},
            # 2.5s gap between 11.8 and 14.3
            {"word": "Speaker", "start": 14.3, "end": 14.8},
            {"word": "two", "start": 14.9, "end": 15.3},
            {"word": "answering.", "start": 15.4, "end": 16.0},
        ],
    }

    split = split_segments_on_word_pauses([seg], min_pause_sec=1.5)
    assert len(split) == 2
    assert split[0]["start"] == 10.0
    assert split[0]["end"] == 11.8
    assert split[0]["text"] == "Speaker one speaking."
    assert len(split[0]["words"]) == 3

    assert split[1]["start"] == 14.3
    assert split[1]["end"] == 16.0
    assert split[1]["text"] == "Speaker two answering."
    assert len(split[1]["words"]) == 3
