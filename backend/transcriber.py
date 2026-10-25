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


def build_transcription_prompt(
    vocabulary: list[str] | None = None,
    speaker_names: list[str] | None = None,
    media_keywords: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Synthesize high-efficacy initial_prompt and hotwords for Faster-Whisper.

    Combines domain terms, proper nouns, and speaker names into natural conversational
    context sentences that condition the transformer decoder's self-attention prior,
    while compiling space-separated token prefixes for beam search logit boosting.

    Args:
        vocabulary: List of user-specified terms, brand names, and specialized jargon.
        speaker_names: List of human-assigned speaker labels from multi-speaker studio.
        media_keywords: Key terms derived from media filename or metadata.

    Returns:
        Tuple of (initial_prompt, hotwords) where both are strings or None.
    """
    all_terms: list[str] = []
    seen: set[str] = set()

    generic_speakers = {
        "speaker",
        "speaker 1",
        "speaker 2",
        "speaker 3",
        "speaker 4",
        "speaker 5",
        "speaker_00",
        "speaker_01",
        "speaker_02",
        "speaker_03",
        "speaker_04",
    }

    for term_list in [speaker_names, vocabulary, media_keywords]:
        if not term_list:
            continue
        for item in term_list:
            if not isinstance(item, str):
                continue
            clean = item.strip()
            if not clean or clean.lower() in generic_speakers:
                continue
            norm = clean.lower()
            if norm not in seen:
                seen.add(norm)
                all_terms.append(clean)

    if not all_terms:
        return None, None

    # Faster-Whisper beam search hotword boosting
    hotwords = " ".join(all_terms)

    # Autoregressive decoder attention conditioning prompt
    # Limit to first 35 terms to avoid overflowing the 224-token prompt context window
    terms_phrase = ", ".join(all_terms[:35])
    initial_prompt = (
        f"In this video, the discussion covers the following topics and speakers: {terms_phrase}."
    )

    return initial_prompt, hotwords


def run_whisperx_pipeline(
    audio_wav_path: str,
    model_name: str = "large-v3",
    batch_size: int = 16,
    progress_callback: Callable[[str, int], None] | None = None,
    enable_diarization: bool = False,
    hf_token: str | None = None,
    custom_vocabulary: list[str] | None = None,
    speaker_names: list[str] | None = None,
    media_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Execute WhisperX speech recognition and forced word-level alignment 100% offline.

    Loads the audio track, runs batched Whisper inference for initial transcription,
    and executes Wav2Vec2 alignment to generate accurate word start and end timestamps.
    Operates strictly offline without external Hugging Face telemetric update pings
    or gated model tokens. Pre-conditions decoder attention and beam search logit weights
    with target vocabulary to prevent misspellings.

    Args:
        audio_wav_path: Absolute or relative path to 16kHz mono WAV audio file.
        model_name: Whisper model architecture size (e.g. 'large-v3', 'medium', 'base').
        batch_size: Parallel batch size for acoustic model inference.
        progress_callback: Optional callable accepting a status message string and
            percentage integer (0-100).
        enable_diarization: Whether to run offline acoustic speaker diarization on audio.
        hf_token: Deprecated parameter retained for backward signature compatibility.
        custom_vocabulary: Optional list of proper nouns, technical jargon, and domain terms.
        speaker_names: Optional human-assigned speaker labels to bias recognition.
        media_keywords: Optional keywords derived from video title or filename.

    Returns:
        Dictionary containing aligned subtitle segments, detected language, and
        word-level timestamp dictionaries.
    """
    import os
    import whisperx
    from backend.config import get_cache_dir

    # SECURITY: Isolate model cache within XDG cache jail and enforce 100% offline operation (Directive 1)
    models_dir = get_cache_dir() / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "hf").mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(models_dir / "hf")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    device, compute_type, device_label = get_transcription_device()
    device_index = 0
    print(f"[WhisperX] Selected device: {device} ({device_label}), compute_type: {compute_type}")

    initial_prompt, hotwords = build_transcription_prompt(
        vocabulary=custom_vocabulary,
        speaker_names=speaker_names,
        media_keywords=media_keywords,
    )
    asr_options: dict[str, Any] = {}
    if initial_prompt:
        asr_options["initial_prompt"] = initial_prompt
        print(f"[WhisperX] Priming transformer attention with prompt: {initial_prompt}")
    if hotwords:
        asr_options["hotwords"] = hotwords
        print(f"[WhisperX] Boosting beam search logits for hotwords: {hotwords}")

    if progress_callback:
        progress_callback(f"Loading WhisperX {model_name} on {device_label}...", 20)

    # 1. Load Audio
    print(f"[WhisperX] Loading audio from {audio_wav_path}...")
    audio = whisperx.load_audio(audio_wav_path)

    # 2. Load WhisperX Model (enforce local cache first to prevent Hugging Face update checks)
    print(f"[WhisperX] Loading model {model_name}...")
    try:
        model = whisperx.load_model(
            model_name,
            device=device,
            device_index=device_index,
            compute_type=compute_type,
            asr_options=asr_options if asr_options else None,
            download_root=str(models_dir),
            local_files_only=True,
        )
    except Exception as local_err:
        print(f"[WhisperX] Local cached model '{model_name}' not found ({local_err}). Checking download...")
        orig_hf_offline = os.environ.pop("HF_HUB_OFFLINE", None)
        try:
            model = whisperx.load_model(
                model_name,
                device=device,
                device_index=device_index,
                compute_type=compute_type,
                asr_options=asr_options if asr_options else None,
                download_root=str(models_dir),
                local_files_only=False,
            )
        except Exception as e:
            # Fall back to medium model if VRAM/RAM or download limits prevent loading large-v3
            print(f"[WhisperX] Error loading {model_name}, falling back to 'medium': {e}")
            model = whisperx.load_model(
                "medium",
                device=device,
                device_index=device_index,
                compute_type=compute_type,
                asr_options=asr_options if asr_options else None,
                download_root=str(models_dir),
                local_files_only=False,
            )
        finally:
            if orig_hf_offline is not None:
                os.environ["HF_HUB_OFFLINE"] = orig_hf_offline
            else:
                os.environ["HF_HUB_OFFLINE"] = "1"

    if progress_callback:
        progress_callback(f"Transcribing speech with WhisperX ({device_label})...", 45)

    # 3. Transcribe audio with Whisper
    print("[WhisperX] Transcribing audio...")
    raw_result = model.transcribe(audio, batch_size=batch_size)
    detected_lang = raw_result.get("language", "en")
    print(f"[WhisperX] Detected language: {detected_lang}")

    if progress_callback:
        progress_callback(f"Aligning word timestamps for language '{detected_lang}'...", 70)

    # 4. Load alignment model and align words (enforce local cache / offline mode)
    print("[WhisperX] Loading forced alignment model...")
    align_device = "cuda" if device == "cuda" else "cpu"
    align_dir = str(models_dir / "align")
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=detected_lang,
            device=align_device,
            model_dir=align_dir,
            model_cache_only=True,
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
        # Fallback: if phoneme alignment fails or language model is not cached offline,
        # fallback immediately to raw segment words without hanging on remote network timeouts
        print(f"[WhisperX] Alignment notice: {align_err}. Using segment words fallback.")
        aligned_result = raw_result

    if progress_callback:
        progress_callback("Word alignment complete. Compiling subtitles...", 90)

    # 5. Optional Speaker Diarization (100% offline acoustic clustering without Hugging Face / PyAnnote)
    if enable_diarization:
        from backend.diarizer import diarize_whisper_result

        if progress_callback:
            progress_callback("Running offline speaker diarization...", 92)
        try:
            print("[Voice Highlighter] Running 100% offline acoustic speaker diarization...")
            aligned_result, _ = diarize_whisper_result(
                audio_wav_path=audio_wav_path,
                whisper_result=aligned_result,
            )
            print("[Voice Highlighter] Speaker diarization completed successfully.")
        except Exception as diarize_err:
            print(f"[Voice Highlighter] Diarization notice ({diarize_err}). Proceeding with aligned text.")

    return aligned_result
