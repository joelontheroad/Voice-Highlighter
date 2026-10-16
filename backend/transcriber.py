# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Speech recognition and word alignment subsystem.

Integrates WhisperX and Wav2Vec2 forced alignment models with adaptive hardware
acceleration across NVIDIA CUDA GPUs, Apple Silicon Neural Engine / CPU, and
x86_64 host processors.
"""

import sys
from collections.abc import Callable
from typing import Any

import torch


def get_transcription_device() -> tuple[str, str, str]:
    """Determine the optimal compute device and precision for transcription.

    Inspects CUDA availability and operating system architecture to select the
    fastest supported inference engine.

    Returns:
        A tuple of (device, compute_type, device_label) where device is 'cuda'
        or 'cpu', compute_type is 'float16' or 'int8', and device_label is a
        descriptive hardware string.
    """
    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        gpu_name = torch.cuda.get_device_name(0)
        return "cuda", "float16", gpu_name

    # Check for Apple Silicon / macOS
    if sys.platform == "darwin":
        return "cpu", "int8", "Apple Silicon (CPU/NE)"

    return "cpu", "int8", "CPU"


def run_whisperx_pipeline(
    audio_wav_path: str,
    model_name: str = "large-v3",
    batch_size: int = 16,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    """Execute WhisperX speech recognition and forced word-level alignment.

    Loads the audio track, runs batched Whisper inference for initial transcription,
    and executes Wav2Vec2 alignment to generate accurate word start and end timestamps.

    Args:
        audio_wav_path: Absolute or relative path to 16kHz mono WAV audio file.
        model_name: Whisper model architecture size (e.g. 'large-v3', 'medium', 'base').
        batch_size: Parallel batch size for acoustic model inference.
        progress_callback: Optional callable accepting a status message string and
            percentage integer (0-100).

    Returns:
        Dictionary containing aligned subtitle segments, detected language, and
        word-level timestamp dictionaries.
    """
    import whisperx

    device, compute_type, device_label = get_transcription_device()
    device_index = 0
    print(f"[WhisperX] Selected device: {device} ({device_label}), compute_type: {compute_type}")

    if progress_callback:
        progress_callback(f"Loading WhisperX {model_name} on {device_label}...", 20)

    # 1. Load Audio
    print(f"[WhisperX] Loading audio from {audio_wav_path}...")
    audio = whisperx.load_audio(audio_wav_path)

    # 2. Load WhisperX Model
    print(f"[WhisperX] Loading model {model_name}...")
    try:
        model = whisperx.load_model(
            model_name,
            device=device,
            device_index=device_index,
            compute_type=compute_type,
        )
    except Exception as e:
        # Fall back to medium model if VRAM/RAM or download limits prevent loading large-v3
        print(f"[WhisperX] Error loading {model_name}, falling back to 'medium': {e}")
        model = whisperx.load_model(
            "medium",
            device=device,
            device_index=device_index,
            compute_type=compute_type,
        )

    if progress_callback:
        progress_callback(f"Transcribing speech with WhisperX ({device_label})...", 45)

    # 3. Transcribe audio with Whisper
    print("[WhisperX] Transcribing audio...")
    raw_result = model.transcribe(audio, batch_size=batch_size)
    detected_lang = raw_result.get("language", "en")
    print(f"[WhisperX] Detected language: {detected_lang}")

    if progress_callback:
        progress_callback(f"Aligning word timestamps for language '{detected_lang}'...", 70)

    # 4. Load alignment model and align words
    print("[WhisperX] Loading forced alignment model...")
    align_device = "cuda" if device == "cuda" else "cpu"
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=detected_lang,
            device=align_device,
        )
        print("[WhisperX] Aligning word-level timestamps...")
        aligned_result = whisperx.align(
            raw_result["segments"],
            model_a,
            metadata,
            audio,
            align_device,
            return_char_alignments=False,
        )
    except Exception as align_err:
        # Fallback: if phoneme alignment fails for an unindexed language dialect, retain raw segments
        print(f"[WhisperX] Alignment error: {align_err}. Using segment words fallback.")
        aligned_result = raw_result

    if progress_callback:
        progress_callback("Word alignment complete. Compiling subtitles...", 90)

    return aligned_result
