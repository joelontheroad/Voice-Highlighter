# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Acoustic speaker diarization and voice snippet extraction subsystem.

Provides 100% offline, privacy-respecting multi-speaker voice distinction (1-5 voices)
and acoustic clustering without requiring external Hugging Face tokens, gated models,
or telemetric phone-home endpoints. Extracts representative 2-3 second voice snippets
for interactive human identification and semantic speaker renaming.
"""

import io
import os
import wave
from typing import Any

import numpy as np
import torch
import torchaudio.functional as F
import torchaudio.transforms as T
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score

# Cache for initialized feature extractors
_MFCC_TRANSFORM: T.MFCC | None = None


def _get_mfcc_transform(sample_rate: int = 16000) -> T.MFCC:
    """Lazily initialize and cache the 20-band Mel-Frequency Cepstral Coefficients transform."""
    global _MFCC_TRANSFORM
    if _MFCC_TRANSFORM is None:
        _MFCC_TRANSFORM = T.MFCC(
            sample_rate=sample_rate,
            n_mfcc=20,
            melkwargs={
                "n_fft": 400,
                "hop_length": 160,
                "n_mels": 40,
                "center": False,
            },
        )
    return _MFCC_TRANSFORM


def extract_audio_slice_waveform(
    wav_path: str, start_sec: float, end_sec: float
) -> tuple[torch.Tensor, int]:
    """Read a temporal audio slice from a PCM WAV file into a normalized 1D float tensor.

    Args:
        wav_path: Path to 16kHz mono WAV audio file.
        start_sec: Offset in seconds for slice onset.
        end_sec: Offset in seconds for slice termination.

    Returns:
        Tuple of (waveform_tensor, sample_rate).
    """
    if not os.path.exists(wav_path):
        return torch.zeros(1600), 16000

    with wave.open(wav_path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        total_frames = wf.getnframes()

        start_frame = max(0, min(total_frames, int(start_sec * sample_rate)))
        end_frame = max(start_frame, min(total_frames, int(end_sec * sample_rate)))
        num_frames = end_frame - start_frame

        if num_frames <= 0:
            return torch.zeros(1600), sample_rate

        wf.setpos(start_frame)
        raw_bytes = wf.readframes(num_frames)

    # Convert PCM bytes into normalized float32 tensor
    if sampwidth == 2:
        audio_np = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio_np = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        audio_np = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0

    # Downmix multi-channel audio to mono if necessary
    if n_channels > 1:
        audio_np = audio_np.reshape(-1, n_channels).mean(axis=1)

    waveform = torch.from_numpy(audio_np)
    return waveform, sample_rate


def extract_audio_snippet_bytes(
    wav_path: str, start_sec: float, end_sec: float
) -> bytes:
    """Extract an audio slice from a WAV file and encode as an in-memory WAV byte stream.

    Args:
        wav_path: Path to source WAV audio file.
        start_sec: Offset in seconds for snippet start.
        end_sec: Offset in seconds for snippet end.

    Returns:
        Standard RIFF/WAV binary byte string suitable for HTTP audio streaming.
    """
    if not os.path.exists(wav_path):
        return b""

    with wave.open(wav_path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        total_frames = wf.getnframes()

        start_frame = max(0, min(total_frames, int(start_sec * sample_rate)))
        end_frame = max(start_frame, min(total_frames, int(end_sec * sample_rate)))
        num_frames = end_frame - start_frame

        if num_frames <= 0:
            return b""

        wf.setpos(start_frame)
        raw_bytes = wf.readframes(num_frames)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out_wf:
        out_wf.setnchannels(n_channels)
        out_wf.setsampwidth(sampwidth)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(raw_bytes)

    return buf.getvalue()


def extract_acoustic_embedding(
    waveform: torch.Tensor, sample_rate: int = 16000
) -> np.ndarray:
    """Extract an 80-dimensional acoustic timbre vector from a speech waveform.

    Computes 20 MFCCs, first-order temporal deltas, and statistical aggregates
    (mean, standard deviation) across time, normalized to unit L2 Euclidean length.

    Args:
        waveform: 1D or 2D audio tensor.
        sample_rate: Audio sampling frequency in Hz (typically 16000).

    Returns:
        80-dimensional unit-normalized numpy vector.
    """
    if waveform.ndim > 1:
        waveform = waveform.squeeze()

    # Minimum padding: require at least 400 samples (25ms)
    if waveform.numel() < 400:
        waveform = torch.nn.functional.pad(waveform, (0, 400 - waveform.numel()))

    mfcc_op = _get_mfcc_transform(sample_rate)
    with torch.no_grad():
        mfcc = mfcc_op(waveform)
        # Handle single-frame or multi-frame results
        if mfcc.ndim == 1:
            mfcc = mfcc.unsqueeze(-1)
        deltas = F.compute_deltas(mfcc)

        mean_mfcc = mfcc.mean(dim=-1)
        std_mfcc = mfcc.std(dim=-1) if mfcc.shape[-1] > 1 else torch.zeros_like(mean_mfcc)

        mean_delta = deltas.mean(dim=-1)
        std_delta = deltas.std(dim=-1) if deltas.shape[-1] > 1 else torch.zeros_like(mean_delta)

        feat_tensor = torch.cat([mean_mfcc, std_mfcc, mean_delta, std_delta], dim=0)
        feat_np = feat_tensor.cpu().numpy()

    norm = np.linalg.norm(feat_np)
    if norm > 0:
        feat_np = feat_np / norm
    return feat_np


def diarize_whisper_result(
    audio_wav_path: str,
    whisper_result: dict[str, Any],
    min_speakers: int = 2,
    max_speakers: int = 5,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Cluster speech segments and word tokens into distinct speaker channels (1-5 voices).

    Performs unsupervised acoustic agglomerative clustering over speech utterances,
    annotates all segments and word timestamps with chronological SPEAKER_0X tags,
    and isolates 2-3 second voice snippets for auditory user verification.

    Args:
        audio_wav_path: Path to the 16kHz mono audio file.
        whisper_result: Whisper transcript dictionary with segments and aligned words.
        min_speakers: Minimum number of speaker clusters to consider (default 2).
        max_speakers: Maximum number of speaker clusters to consider (default 5).

    Returns:
        A tuple of (diarized_whisper_result, speaker_samples_dict) where
        speaker_samples_dict maps speaker ID ('SPEAKER_00', etc.) to snippet metadata.
    """
    segments = whisper_result.get("segments") or []
    if not segments:
        return whisper_result, {}

    # Extract acoustic embedding for each dialogue segment
    embeddings: list[np.ndarray] = []
    valid_segment_indices: list[int] = []

    for idx, seg in enumerate(segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 0.1))
        # Skip micro-silence or degenerate durations < 0.2s
        if end - start < 0.2:
            continue

        wf, sr = extract_audio_slice_waveform(audio_wav_path, start, end)
        emb = extract_acoustic_embedding(wf, sr)
        embeddings.append(emb)
        valid_segment_indices.append(idx)

    # If insufficient segments for multi-speaker clustering, assign all to SPEAKER_00
    if len(embeddings) < 2:
        for seg in segments:
            seg["speaker"] = "SPEAKER_00"
            for w in seg.get("words", []):
                w["speaker"] = "SPEAKER_00"

        sample_bytes = b""
        if segments:
            first_s = float(segments[0].get("start", 0.0))
            first_e = min(first_s + 3.0, float(segments[0].get("end", first_s + 2.0)))
            sample_bytes = extract_audio_snippet_bytes(audio_wav_path, first_s, first_e)

        return whisper_result, {
            "SPEAKER_00": {
                "bytes": sample_bytes,
                "quote": segments[0].get("text", "").strip() if segments else "",
                "duration": 2.5,
                "speaker_name": "Speaker 1",
            }
        }

    emb_matrix = np.vstack(embeddings)
    n_samples = emb_matrix.shape[0]

    # Select optimal cluster count between min_speakers and max_speakers
    upper_k = min(max_speakers, n_samples)
    lower_k = max(1, min(min_speakers, upper_k))

    best_k = lower_k
    best_score = -1.0

    if lower_k == upper_k:
        best_k = lower_k
    else:
        # Determine optimal cluster count using silhouette score over cosine distance
        for k in range(lower_k, upper_k + 1):
            if k == 1:
                continue
            try:
                clusterer = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
                lbls = clusterer.fit_predict(emb_matrix)
                # Ensure clusterer produced more than 1 cluster
                if len(np.unique(lbls)) > 1:
                    score = float(silhouette_score(emb_matrix, lbls, metric="cosine"))
                    if score > best_score:
                        best_score = score
                        best_k = k
            except Exception:
                pass

    if best_k < 1:
        best_k = 2

    # Fit final model with chosen best_k
    final_clusterer = AgglomerativeClustering(n_clusters=best_k, metric="cosine", linkage="average")
    raw_labels = final_clusterer.fit_predict(emb_matrix)

    # Remap cluster IDs chronologically (first voice heard in video is SPEAKER_00)
    cluster_order: list[int] = []
    for lbl in raw_labels:
        if lbl not in cluster_order:
            cluster_order.append(lbl)

    label_to_speaker_id: dict[int, str] = {
        old_lbl: f"SPEAKER_{idx:02d}" for idx, old_lbl in enumerate(cluster_order)
    }

    # Annotate valid segments with their assigned speaker
    for seg_idx, old_lbl in zip(valid_segment_indices, raw_labels, strict=False):
        spk_tag = label_to_speaker_id[old_lbl]
        segments[seg_idx]["speaker"] = spk_tag
        for w in segments[seg_idx].get("words", []):
            w["speaker"] = spk_tag

    # Forward-fill any skipped short segments from adjacent segment
    last_known_spk = "SPEAKER_00"
    for seg in segments:
        if "speaker" not in seg:
            seg["speaker"] = last_known_spk
            for w in seg.get("words", []):
                w["speaker"] = last_known_spk
        else:
            last_known_spk = seg["speaker"]

    # Extract clean 2-3 second voice snippets for each speaker cluster
    speaker_samples: dict[str, dict[str, Any]] = {}

    for old_lbl in cluster_order:
        spk_id = label_to_speaker_id[old_lbl]
        member_indices = [
            seg_idx
            for seg_idx, lbl_val in zip(valid_segment_indices, raw_labels, strict=False)
            if lbl_val == old_lbl
        ]

        if not member_indices:
            continue

        # Compute cluster centroid
        member_embs = [
            emb
            for emb, lbl_val in zip(embeddings, raw_labels, strict=False)
            if lbl_val == old_lbl
        ]
        centroid = np.mean(member_embs, axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-8)

        # Rank member segments by duration and cosine closeness to centroid
        best_seg = segments[member_indices[0]]
        best_rank_score = -1e9

        for seg_idx in member_indices:
            candidate = segments[seg_idx]
            c_start = float(candidate.get("start", 0.0))
            c_end = float(candidate.get("end", c_start + 1.0))
            c_dur = c_end - c_start

            # Preferred duration window: 1.5s to 3.5s
            dur_score = 1.0 if (1.5 <= c_dur <= 3.5) else max(0.1, 1.0 - abs(c_dur - 2.5) * 0.3)
            # Find candidate embedding index
            emb_pos = valid_segment_indices.index(seg_idx)
            sim_to_centroid = float(np.dot(embeddings[emb_pos], centroid))

            rank = dur_score * 0.6 + sim_to_centroid * 0.4
            if rank > best_rank_score:
                best_rank_score = rank
                best_seg = candidate

        snippet_start = float(best_seg.get("start", 0.0))
        snippet_end = min(snippet_start + 3.0, float(best_seg.get("end", snippet_start + 2.5)))
        # Ensure at least 1.5 seconds if available
        if snippet_end - snippet_start < 1.5:
            snippet_end = snippet_start + 1.5

        snippet_bytes = extract_audio_snippet_bytes(audio_wav_path, snippet_start, snippet_end)
        speaker_num = int(spk_id.replace("SPEAKER_", "")) + 1

        speaker_samples[spk_id] = {
            "bytes": snippet_bytes,
            "quote": best_seg.get("text", "").strip(),
            "duration": round(snippet_end - snippet_start, 2),
            "speaker_name": f"Speaker {speaker_num}",
            "start": snippet_start,
            "end": snippet_end,
        }

    return whisper_result, speaker_samples
