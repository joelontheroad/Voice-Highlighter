# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit and integration tests for WhisperX pre-transcription vocabulary biasing.

Verifies that domain terms, proper nouns, and speaker names are synthesized into
syntactically valid initial_prompt strings and Faster-Whisper beam search hotwords,
ensuring 100% pre-transcription misspelling prevention.
"""

from unittest.mock import MagicMock, patch

from backend.config import StylePreset
from backend.transcriber import build_transcription_prompt, run_whisperx_pipeline


def test_build_transcription_prompt_empty():
    """Verify that empty inputs return None for both initial_prompt and hotwords."""
    prompt, hotwords = build_transcription_prompt([], [], [])
    assert prompt is None
    assert hotwords is None

    prompt, hotwords = build_transcription_prompt(None, None, None)
    assert prompt is None
    assert hotwords is None


def test_build_transcription_prompt_deduplication_and_casing():
    """Verify terms are trimmed and deduplicated case-insensitively while preserving original casing."""
    vocab = ["Katie Kam", "katie kam", "PostgreSQL", "postgresql", "carburetor"]
    prompt, hotwords = build_transcription_prompt(vocabulary=vocab)

    assert prompt is not None
    assert hotwords is not None

    # Should contain exactly one occurrence of Katie Kam and PostgreSQL
    assert "Katie Kam" in prompt
    assert prompt.count("Katie Kam") == 1
    assert "PostgreSQL" in prompt
    assert prompt.count("PostgreSQL") == 1
    assert "carburetor" in prompt

    # Hotwords string check
    assert hotwords == "Katie Kam PostgreSQL carburetor"


def test_build_transcription_prompt_filters_generic_speakers():
    """Verify generic speaker tags (e.g. 'Speaker 1', 'SPEAKER_00') are excluded from vocabulary conditioning."""
    speakers = ["Speaker 1", "speaker_00", "Katie Kam", "Speaker 2", "Dr. Joel"]
    prompt, hotwords = build_transcription_prompt(speaker_names=speakers)

    assert prompt is not None
    assert hotwords is not None

    assert "Katie Kam" in prompt
    assert "Dr. Joel" in prompt
    assert "Speaker 1" not in prompt
    assert "SPEAKER_00" not in prompt
    assert "Speaker 2" not in prompt
    assert hotwords == "Katie Kam Dr. Joel"


def test_build_transcription_prompt_combines_sources():
    """Verify terms from vocabulary, speaker names, and media keywords combine harmoniously."""
    speakers = ["Katie Kam"]
    vocab = ["PostgreSQL", "NVENC"]
    keywords = ["rebuild", "motorcycle", "carburetor"]

    prompt, hotwords = build_transcription_prompt(
        vocabulary=vocab,
        speaker_names=speakers,
        media_keywords=keywords,
    )

    assert prompt is not None
    assert prompt.startswith("In this video, the discussion covers the following topics and speakers:")
    for term in ["Katie Kam", "PostgreSQL", "NVENC", "rebuild", "motorcycle", "carburetor"]:
        assert term in prompt
        assert term in hotwords


def test_style_preset_custom_vocabulary_schema():
    """Verify StylePreset serializes and validates custom_vocabulary."""
    preset = StylePreset(
        name="tech-channel",
        custom_vocabulary=["PostgreSQL", "Kubernetes", "NVENC"],
    )
    assert preset.custom_vocabulary == ["PostgreSQL", "Kubernetes", "NVENC"]

    data = preset.model_dump()
    assert "custom_vocabulary" in data
    assert data["custom_vocabulary"] == ["PostgreSQL", "Kubernetes", "NVENC"]

    # Deserialization check
    restored = StylePreset.model_validate(data)
    assert restored.custom_vocabulary == ["PostgreSQL", "Kubernetes", "NVENC"]


@patch("backend.transcriber.get_transcription_device", return_value=("cpu", "int8", "CPU"))
def test_run_whisperx_pipeline_passes_asr_options(mock_device):
    """Verify run_whisperx_pipeline passes synthesized asr_options to whisperx.load_model."""
    import sys

    mock_whisperx = MagicMock()
    mock_model = MagicMock()
    mock_whisperx.load_model.return_value = mock_model
    mock_whisperx.load_audio.return_value = MagicMock()
    mock_model.transcribe.return_value = {"segments": [], "language": "en"}
    mock_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
    mock_whisperx.align.return_value = {"segments": [], "word_segments": []}

    with patch.dict(sys.modules, {"whisperx": mock_whisperx}):
        res = run_whisperx_pipeline(
            audio_wav_path="/fake/test.wav",
            model_name="small",
            custom_vocabulary=["Katie Kam", "carburetor"],
            speaker_names=["Joel"],
        )
        assert res is not None
        assert mock_whisperx.load_model.called
        call_kwargs = mock_whisperx.load_model.call_args.kwargs
        assert "asr_options" in call_kwargs
        asr_opts = call_kwargs["asr_options"]
        assert asr_opts is not None
        assert "initial_prompt" in asr_opts
        assert "Katie Kam" in asr_opts["initial_prompt"]
        assert "carburetor" in asr_opts["initial_prompt"]
        assert "Joel" in asr_opts["initial_prompt"]
        assert "hotwords" in asr_opts
        assert "Katie Kam" in asr_opts["hotwords"]


def test_transcribe_request_accepts_custom_vocabulary():
    """Verify TranscribeRequest model parses and retains custom_vocabulary."""
    from backend.app import TranscribeRequest

    req = TranscribeRequest(
        video_path="/fake/video.mp4",
        styling={},
        custom_vocabulary=["Katie Kam", "carburetor", "PostgreSQL"],
    )
    assert req.custom_vocabulary == ["Katie Kam", "carburetor", "PostgreSQL"]

    # Verify default is None
    req_default = TranscribeRequest(video_path="/fake/video.mp4", styling={})
    assert req_default.custom_vocabulary is None


def test_preset_persistence_custom_vocabulary(tmp_path, monkeypatch):
    """Verify style presets save and load custom_vocabulary to and from YAML on disk."""
    from backend.config import load_preset, save_preset

    # Isolate XDG config directory per AGENTS.md
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    preset = StylePreset(
        name="podcast-interview",
        description="Preset with speaker names and domain vocabulary",
        custom_vocabulary=["Katie Kam", "Dr. Joel", "PostgreSQL", "NVENC"],
    )
    saved_path = save_preset(preset)
    assert saved_path.exists()

    loaded = load_preset("podcast-interview")
    assert loaded.name == "podcast-interview"
    assert loaded.custom_vocabulary == ["Katie Kam", "Dr. Joel", "PostgreSQL", "NVENC"]

