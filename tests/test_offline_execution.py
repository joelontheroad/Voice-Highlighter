# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit and integration tests for 100% offline model execution.

Validates that speech transcription, alignment, and acoustic speaker diarization
execute completely offline without attempting outbound network connections to
Hugging Face or external servers, preventing UI freezes when internet is down.
"""

import os
import socket
import sys
from unittest.mock import MagicMock, patch

import pytest

from backend.transcriber import run_whisperx_pipeline


def test_offline_execution_blocks_huggingface_network():
    """Verify run_whisperx_pipeline sets offline flags and does not attempt network connections."""
    connected_hosts: list[tuple] = []

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        connected_hosts.append(address)
        raise OSError("Network unreachable (offline enforcement test)")

    mock_whisperx = MagicMock()
    mock_model = MagicMock()
    mock_whisperx.load_model.return_value = mock_model
    mock_whisperx.load_audio.return_value = MagicMock()
    mock_model.transcribe.return_value = {"segments": [], "language": "en"}
    mock_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
    mock_whisperx.align.return_value = {"segments": [], "word_segments": []}

    with patch.object(socket.socket, "connect", guarded_connect):
        with patch.dict(sys.modules, {"whisperx": mock_whisperx}):
            result = run_whisperx_pipeline(
                audio_wav_path="/mock/test.wav",
                model_name="small",
            )
            assert result is not None

    # Verify local_files_only=True was passed to load_model
    call_kwargs = mock_whisperx.load_model.call_args.kwargs
    assert call_kwargs.get("local_files_only") is True

    # Verify model_cache_only=True was passed to load_align_model
    align_kwargs = mock_whisperx.load_align_model.call_args.kwargs
    assert align_kwargs.get("model_cache_only") is True

    # Verify no external internet sockets were contacted
    assert len(connected_hosts) == 0


def test_offline_fallback_to_cached_model():
    """Verify that when requested model is missing and network is offline, it falls back to a cached model."""
    from backend.transcriber import run_whisperx_pipeline

    mock_whisperx = MagicMock()
    mock_model = MagicMock()
    # First call (for 'medium') fails with LocalEntryNotFoundError
    # Second call (for fallback 'large-v3') succeeds
    mock_whisperx.load_model.side_effect = [
        OSError("Model not found locally"),
        mock_model,
    ]
    mock_whisperx.load_audio.return_value = MagicMock()
    mock_model.transcribe.return_value = {"segments": [], "language": "en"}
    mock_whisperx.load_align_model.return_value = (MagicMock(), MagicMock())
    mock_whisperx.align.return_value = {"segments": [], "word_segments": []}

    with patch("backend.transcriber.is_network_available", return_value=False):
        with patch("backend.transcriber.get_locally_cached_whisper_models", return_value=["base", "large-v3"]):
            with patch.dict(sys.modules, {"whisperx": mock_whisperx}):
                result = run_whisperx_pipeline(
                    audio_wav_path="/mock/test.wav",
                    model_name="medium",
                )
                assert result is not None

    # Verify fallback to large-v3 was called with local_files_only=True
    assert mock_whisperx.load_model.call_count == 2
    second_call_args, second_call_kwargs = mock_whisperx.load_model.call_args_list[1]
    assert second_call_args[0] == "large-v3"
    assert second_call_kwargs.get("local_files_only") is True


def test_diarization_pipeline_no_hf_token():
    """Verify that multi-speaker diarization uses local acoustic clustering without pyannote or HF tokens."""
    import backend.diarizer as diarizer

    # Confirm diarizer module has no Hugging Face or pyannote dependencies
    assert not hasattr(diarizer, "DiarizationPipeline")
    assert not hasattr(diarizer, "use_auth_token")

    # Mock audio slice waveform and verify clustering executes 100% locally
    mock_result = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello world", "words": [{"word": "Hello", "start": 0.0, "end": 0.8}, {"word": "world", "start": 1.0, "end": 1.8}]},
            {"start": 2.5, "end": 4.5, "text": "Welcome to studio", "words": [{"word": "Welcome", "start": 2.5, "end": 3.2}, {"word": "to", "start": 3.3, "end": 3.5}, {"word": "studio", "start": 3.6, "end": 4.4}]},
        ]
    }

    with patch("backend.diarizer.extract_audio_slice_waveform") as mock_extract:
        import torch
        mock_extract.return_value = (torch.randn(32000), 16000)

        diarized_result, samples = diarizer.diarize_whisper_result(
            audio_wav_path="/fake/path.wav",
            whisper_result=mock_result,
            min_speakers=1,
            max_speakers=2,
        )

        assert diarized_result is not None
        assert "segments" in diarized_result
        for seg in diarized_result["segments"]:
            assert "speaker" in seg
            assert seg["speaker"].startswith("SPEAKER_")
