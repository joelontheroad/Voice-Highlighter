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

def split_segments_on_word_pauses(
    segments: list[dict[str, Any]],
    min_pause_sec: float = 1.5,
) -> list[dict[str, Any]]:
    """Split aligned dialogue segments containing intra-segment word pauses into distinct sub-segments.

    Prevents distinct speakers within a single VAD speech chunk from being collapsed into
    a single acoustic turn prior to clustering.

    Args:
        segments: List of speech segment dictionaries containing word timestamps.
        min_pause_sec: Minimum silence duration between words in seconds to trigger a split (default 1.5s).

    Returns:
        Refined list of segment dictionaries with accurate temporal boundaries and word lists.
    """
    refined: list[dict[str, Any]] = []
    for seg in segments:
        words = seg.get("words", [])
        if not words or len(words) < 2:
            refined.append(seg)
            continue

        current_words: list[dict[str, Any]] = [words[0]]
        for w in words[1:]:
            prev_end = current_words[-1].get("end")
            curr_start = w.get("start")
            if (
                prev_end is not None
                and curr_start is not None
                and (curr_start - prev_end >= min_pause_sec)
            ):
                sub_text = " ".join(str(cw.get("word", "")).strip() for cw in current_words)
                sub_seg = dict(seg)
                sub_seg.update({
                    "start": float(current_words[0].get("start", seg.get("start", 0.0))),
                    "end": float(current_words[-1].get("end", seg.get("end", 0.0))),
                    "text": sub_text,
                    "words": list(current_words),
                })
                refined.append(sub_seg)
                current_words = [w]
            else:
                current_words.append(w)

        if current_words:
            sub_text = " ".join(str(cw.get("word", "")).strip() for cw in current_words)
            sub_seg = dict(seg)
            sub_seg.update({
                "start": float(current_words[0].get("start", seg.get("start", 0.0))),
                "end": float(current_words[-1].get("end", seg.get("end", 0.0))),
                "text": sub_text,
                "words": list(current_words),
            })
            refined.append(sub_seg)

    return refined


def group_segments_into_turns(
    segments: list[dict[str, Any]],
    seg_embeddings: list[np.ndarray] | None = None,
    target_k: int | None = None,
    max_gap_sec: float = 0.85,
    min_sim: float = 0.985,
) -> list[list[int]]:
    """Group adjacent segment indices into continuous conversational turns.

    Segments separated by short breath pauses (<= max_gap_sec) with consistent voice timbre
    (cosine similarity >= min_sim) belong to the same continuous conversational turn.
    Guarantees that merging does not artificially collapse turns below requested target_k speakers.

    Args:
        segments: List of speech segment dictionaries containing 'start' and 'end' floats.
        seg_embeddings: Optional list of acoustic embedding vectors for each segment.
        target_k: Optional target speaker cluster count.
        max_gap_sec: Maximum pause duration in seconds to consider speech continuous (default 0.85s).
        min_sim: Minimum acoustic cosine similarity to consider speech from same speaker (default 0.980).

    Returns:
        List of turns, where each turn is a list of segment indices.
    """
    n = len(segments)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    turns: list[list[int]] = []
    current_turn: list[int] = [0]

    for i in range(1, n):
        prev_end = float(segments[i - 1].get("end", 0.0))
        curr_start = float(segments[i].get("start", prev_end))
        gap = curr_start - prev_end

        sim = 1.0
        if seg_embeddings and i < len(seg_embeddings) and i - 1 < len(seg_embeddings):
            sim = float(np.dot(seg_embeddings[i - 1], seg_embeddings[i]))

        # High-similarity speech (sim >= 0.990) can bridge natural conversational pauses up to 2.5s
        can_merge_k = True
        if target_k is not None:
            can_merge_k = (len(turns) + (n - i)) >= target_k
        is_close_gap = (gap <= max_gap_sec and sim >= min_sim and can_merge_k)

        if is_close_gap:
            current_turn.append(i)
        else:
            turns.append(current_turn)
            current_turn = [i]

    turns.append(current_turn)
    return turns


def extract_acoustic_embedding(
    waveform: torch.Tensor | np.ndarray, sample_rate: int = 16000
) -> np.ndarray:
    """Extract a robust, channel-normalized acoustic timbre vector from a speech waveform.

    Applies energy-based Voice Activity Detection (VAD) to isolate voiced speech from ambient
    background noise. Computes 8-octave subband vocal tract energy distribution ratios,
    fundamental pitch (F0) statistics, spectral centroid, and Cepstral Mean Normalization (CMN)
    first-order temporal deltas to distinguish speaker identity independently of microphone
    or room acoustics.

    Args:
        waveform: 1D or 2D audio tensor or numpy array.
        sample_rate: Audio sampling frequency in Hz (typically 16000).

    Returns:
        Unit L2-normalized numpy embedding vector.
    """
    if isinstance(waveform, np.ndarray):
        waveform = torch.from_numpy(waveform)

    if waveform.ndim > 1:
        waveform = waveform.squeeze()

    # Minimum padding: require at least 400 samples (25ms)
    if waveform.numel() < 400:
        waveform = torch.nn.functional.pad(waveform, (0, 400 - waveform.numel()))

    # 1. Energy-gated Voice Activity Detection (VAD) to strip silent / ambient noise frames
    frame_len = 400
    hop = 160
    if waveform.numel() > frame_len:
        unfolded = waveform.unfold(0, frame_len, hop)
        frame_energies = (unfolded**2).mean(dim=1)
        max_e = frame_energies.max()
        if max_e > 1e-6:
            speech_mask = frame_energies > (max_e * 0.05)
            if speech_mask.sum() >= 5:
                speech_frames = unfolded[speech_mask]
                waveform = speech_frames.reshape(-1)

    # 2. Fundamental pitch (F0) estimation to differentiate speakers across shared channels
    pitch = F.detect_pitch_frequency(waveform, sample_rate=sample_rate)
    valid_pitch = pitch[(pitch >= 60.0) & (pitch <= 450.0)]
    if valid_pitch.numel() > 0:
        p_med = float(valid_pitch.median()) / 300.0
        p_mean = float(valid_pitch.mean()) / 300.0
        p_q25 = float(torch.quantile(valid_pitch, 0.25)) / 300.0
        p_q75 = float(torch.quantile(valid_pitch, 0.75)) / 300.0
        p_iqr = max(0.0, p_q75 - p_q25)
        p_std = float(valid_pitch.std()) / 100.0 if valid_pitch.numel() > 1 else 0.0
        voiced_ratio = float(valid_pitch.numel()) / float(max(1, pitch.numel()))
    else:
        p_med = 0.5
        p_mean = 0.5
        p_q25 = 0.4
        p_q75 = 0.6
        p_iqr = 0.2
        p_std = 0.0
        voiced_ratio = 0.0

    # 3. Spectral centroid estimation (frequency balance / vocal brightness)
    if waveform.numel() >= 400:
        win = torch.hann_window(400, device=waveform.device)
        try:
            sc = F.spectral_centroid(waveform, sample_rate, 0, win, 400, 160, 400)
            sc_mean = float(sc.mean()) / 3000.0
            sc_std = float(sc.std()) / 1500.0 if sc.numel() > 1 else 0.0
        except Exception:
            sc_mean = 0.5
            sc_std = 0.0
    else:
        sc_mean = 0.5
        sc_std = 0.0

    # 4. Octave band vocal tract resonance distribution
    # Dissects vocal formant distribution across key resonance centers
    try:
        fft = torch.fft.rfft(waveform)
        power = torch.abs(fft) ** 2
        freqs = torch.fft.rfftfreq(len(waveform), 1.0 / sample_rate)
        bands = [
            (80, 250), (250, 500), (500, 1000), (1000, 1800),
            (1800, 2800), (2800, 4200), (4200, 6000), (6000, 8000),
        ]
        b_energies = []
        for f_low, f_high in bands:
            m = (freqs >= f_low) & (freqs < f_high)
            e = float(power[m].mean()) if m.sum() > 0 else 0.0
            b_energies.append(e)
        total_e = sum(b_energies) + 1e-12
        b_ratios = np.array([e / total_e for e in b_energies], dtype=np.float32)
    except Exception:
        b_ratios = np.zeros(8, dtype=np.float32)

    # 5. MFCC with Cepstral Mean Normalization (CMN) and temporal deltas
    mfcc_op = _get_mfcc_transform(sample_rate)
    with torch.no_grad():
        mfcc = mfcc_op(waveform)
        if mfcc.ndim == 1:
            mfcc = mfcc.unsqueeze(-1)

        mfcc_sub = mfcc[1:, :] if mfcc.shape[0] > 1 else mfcc
        cmn_mfcc = mfcc_sub - mfcc_sub.mean(dim=-1, keepdim=True)
        deltas = F.compute_deltas(cmn_mfcc)

        mean_delta = deltas.mean(dim=-1)
        std_delta = deltas.std(dim=-1) if deltas.shape[-1] > 1 else torch.zeros_like(mean_delta)

        # Weighting factors:
        # - pitch & centroid are multiplied by 4.0
        # - subband formant energy ratios are multiplied by 5.0
        pitch_centroid_vec = torch.tensor(
            [p_med, p_mean, p_q25, p_q75, p_iqr, p_std, voiced_ratio, sc_mean, sc_std],
            dtype=torch.float32,
            device=waveform.device,
        ) * 4.0
        band_vec = torch.from_numpy(b_ratios * 5.0).to(waveform.device)

        feat_tensor = torch.cat([pitch_centroid_vec, band_vec, mean_delta, std_delta], dim=0)
        feat_np = feat_tensor.cpu().numpy()

    norm = np.linalg.norm(feat_np)
    if norm > 0:
        feat_np = feat_np / norm
    return feat_np


def diarize_whisper_result(
    audio_wav_path: str,
    whisper_result: dict[str, Any],
    min_speakers: int = 2,
    max_speakers: int = 7,
    target_speakers: int | None = None,
    keyframes: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Cluster speech segments and word tokens into distinct speaker channels (1-7 voices).

    Performs turn-level acoustic agglomerative clustering over speech utterances, annotates all
    segments and word timestamps with chronological SPEAKER_0X tags, respects timeline keyframe
    single-to-multi-speaker transitions, and isolates 4.5-6.0 second voice snippets for auditory verification.

    Args:
        audio_wav_path: Path to the 16kHz mono audio file.
        whisper_result: Whisper transcript dictionary with segments and aligned words.
        min_speakers: Minimum number of speaker clusters to consider (default 2).
        max_speakers: Maximum number of speaker clusters to consider (default 7).
        target_speakers: Optional explicit speaker count override (e.g., 4, 5, 6, 7) configured by user.
        keyframes: Optional list of timeline keyframe dictionaries defining single-vs-multi-speaker zones.

    Returns:
        A tuple of (diarized_whisper_result, speaker_samples_dict) where
        speaker_samples_dict maps speaker ID ('SPEAKER_00', etc.) to snippet metadata.
    """
    segments = whisper_result.get("segments") or []
    if not segments:
        return whisper_result, {}

    # Refine segments: Split any segment containing internal word pauses >= 1.5s
    # so multi-speaker turns within a single VAD chunk are separated into distinct turns.
    segments = split_segments_on_word_pauses(segments, min_pause_sec=1.5)
    whisper_result["segments"] = segments

    # 1. Identify valid dialogue segments with duration >= 0.2s
    valid_segment_indices: list[int] = []
    for idx, seg in enumerate(segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 0.1))
        if end - start >= 0.2:
            valid_segment_indices.append(idx)

    if len(valid_segment_indices) < 2:
        for seg in segments:
            seg["speaker"] = "SPEAKER_00"
            for w in seg.get("words", []):
                w["speaker"] = "SPEAKER_00"

        sample_bytes = b""
        duration_val = 5.5
        if segments:
            first_s = float(segments[0].get("start", 0.0))
            first_e = min(first_s + 6.0, float(segments[0].get("end", first_s + 5.5)))
            if first_e - first_s < 4.5:
                first_e = first_s + 4.5
            duration_val = round(first_e - first_s, 2)
            sample_bytes = extract_audio_snippet_bytes(audio_wav_path, first_s, first_e)

        return whisper_result, {
            "SPEAKER_00": {
                "bytes": sample_bytes,
                "quote": segments[0].get("text", "").strip() if segments else "",
                "duration": duration_val,
                "speaker_name": "Speaker 1",
            }
        }

    # 2. Extract acoustic embedding for each valid dialogue segment
    valid_segs_list = [segments[idx] for idx in valid_segment_indices]
    seg_embeddings: list[np.ndarray] = []
    for s_meta in valid_segs_list:
        s_start = float(s_meta.get("start", 0.0))
        s_end = float(s_meta.get("end", s_start + 0.1))
        wf, sr = extract_audio_slice_waveform(audio_wav_path, s_start, s_end)
        emb = extract_acoustic_embedding(wf, sr)
        seg_embeddings.append(emb)

    # 3. Partition valid segments into conversational turns (gaps <= 0.85s, acoustic similarity >= 0.980)
    raw_turns = group_segments_into_turns(
        valid_segs_list,
        seg_embeddings=seg_embeddings,
        target_k=target_speakers,
        max_gap_sec=0.85,
        min_sim=0.980,
    )
    turns: list[list[int]] = [
        [valid_segment_indices[sub_idx] for sub_idx in turn_group]
        for turn_group in raw_turns
    ]

    # 4. Extract acoustic embedding for each conversational turn
    turn_embeddings: list[np.ndarray] = []
    for turn_idx, turn_members in enumerate(raw_turns):
        if len(turn_members) == 1:
            turn_embeddings.append(seg_embeddings[turn_members[0]])
        else:
            t_start = float(valid_segs_list[turn_members[0]].get("start", 0.0))
            t_end = float(valid_segs_list[turn_members[-1]].get("end", t_start + 1.0))
            wf, sr = extract_audio_slice_waveform(audio_wav_path, t_start, t_end)
            emb = extract_acoustic_embedding(wf, sr)
            turn_embeddings.append(emb)

    n_turns = len(turn_embeddings)
    if n_turns < 2:
        for seg in segments:
            seg["speaker"] = "SPEAKER_00"
            for w in seg.get("words", []):
                w["speaker"] = "SPEAKER_00"
        return whisper_result, {
            "SPEAKER_00": {
                "bytes": extract_audio_snippet_bytes(audio_wav_path, 0.0, 5.5),
                "quote": segments[0].get("text", "").strip(),
                "duration": 5.5,
                "speaker_name": "Speaker 1",
            }
        }

    turn_emb_matrix = np.vstack(turn_embeddings)

    # 4. Check for keyframe-guided single-speaker to multi-speaker transition
    multi_spk_onset_time: float | None = None
    if keyframes:
        for kf in keyframes:
            st = kf.get("styling") or {}
            is_multi = st.get("is_multi_speaker") or st.get("isMultiSpeaker") or (st.get("speaker_count", 1) >= 2)
            if is_multi:
                multi_spk_onset_time = float(kf.get("time", 0.0))
                break

    target_k = target_speakers if (target_speakers is not None and target_speakers >= 1) else None

    # If keyframe guidance defines a single-speaker section prior to multi-speaker:
    if multi_spk_onset_time is not None and multi_spk_onset_time > 0.5:
        single_turn_indices = [
            i for i, turn_m in enumerate(turns)
            if float(segments[turn_m[-1]].get("end", 0.0)) <= multi_spk_onset_time + 0.1
        ]
        multi_turn_indices = [
            i for i, turn_m in enumerate(turns)
            if float(segments[turn_m[-1]].get("end", 0.0)) > multi_spk_onset_time + 0.1
        ]
    else:
        single_turn_indices = []
        multi_turn_indices = list(range(n_turns))

    turn_labels: list[int] = [0] * n_turns

    if single_turn_indices and multi_turn_indices:
        # All turns before keyframe belong to Cluster 0 (Speaker 1)
        for i in single_turn_indices:
            turn_labels[i] = 0

        # Cluster remaining turns among (target_k - 1) clusters
        remaining_k = max(1, (target_k - 1) if target_k else min(len(multi_turn_indices), max_speakers - 1))
        remaining_k = min(remaining_k, len(multi_turn_indices))

        if remaining_k <= 1 or len(multi_turn_indices) <= 1:
            for i in multi_turn_indices:
                turn_labels[i] = 1
        else:
            multi_embs = turn_emb_matrix[multi_turn_indices]
            if target_k is not None:
                sub_k = remaining_k
            else:
                best_sub_k = 2
                best_sub_score = -1.0
                for k_cand in range(2, remaining_k + 1):
                    try:
                        m_clusterer = AgglomerativeClustering(n_clusters=k_cand, metric="cosine", linkage="average")
                        m_lbls = m_clusterer.fit_predict(multi_embs)
                        if len(np.unique(m_lbls)) > 1:
                            sc_val = float(silhouette_score(multi_embs, m_lbls, metric="cosine"))
                            if sc_val > best_sub_score:
                                best_sub_score = sc_val
                                best_sub_k = k_cand
                    except Exception:
                        pass
                sub_k = best_sub_k
            sub_clusterer = AgglomerativeClustering(n_clusters=sub_k, metric="cosine", linkage="average")
            sub_lbls = sub_clusterer.fit_predict(multi_embs)
            for idx, orig_i in enumerate(multi_turn_indices):
                turn_labels[orig_i] = int(sub_lbls[idx]) + 1
    else:
        # Standard unconstrained turn clustering
        if target_k is not None:
            best_k = min(target_k, n_turns)
        else:
            upper_k = min(max_speakers, n_turns)
            lower_k = max(1, min(min_speakers, upper_k))
            best_k = lower_k
            best_score = -1.0

            if lower_k == upper_k:
                best_k = lower_k
            else:
                for k in range(lower_k, upper_k + 1):
                    if k == 1:
                        continue
                    try:
                        c_model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
                        lbl_pred = c_model.fit_predict(turn_emb_matrix)
                        if len(np.unique(lbl_pred)) > 1:
                            sc_val = float(silhouette_score(turn_emb_matrix, lbl_pred, metric="cosine"))
                            adjusted_score = sc_val * (1.0 + 0.06 * (k - 2))
                            if adjusted_score > best_score:
                                best_score = adjusted_score
                                best_k = k
                    except Exception:
                        pass

            if best_k < 1:
                best_k = 2

        final_clusterer = AgglomerativeClustering(n_clusters=best_k, metric="cosine", linkage="average")
        turn_labels = list(final_clusterer.fit_predict(turn_emb_matrix))

    # 5. Apply guarded temporal continuity smoothing: merge short isolated turns (<1.0s) between same speaker
    for i in range(1, len(turn_labels) - 1):
        prev_lbl = turn_labels[i - 1]
        next_lbl = turn_labels[i + 1]
        curr_lbl = turn_labels[i]
        if prev_lbl == next_lbl and curr_lbl != prev_lbl:
            t_m = turns[i]
            t_dur = float(segments[t_m[-1]].get("end", 0.0)) - float(segments[t_m[0]].get("start", 0.0))
            if t_dur < 1.0 and turn_labels.count(curr_lbl) > 1:
                dist = 1.0 - float(np.dot(turn_emb_matrix[i], turn_emb_matrix[i - 1]))
                if dist < 0.15:
                    turn_labels[i] = prev_lbl

    # 6. Remap cluster IDs chronologically (first voice heard in video is SPEAKER_00)
    cluster_order: list[int] = []
    for lbl in turn_labels:
        if lbl not in cluster_order:
            cluster_order.append(lbl)

    label_to_speaker_id: dict[int, str] = {
        old_lbl: f"SPEAKER_{idx:02d}" for idx, old_lbl in enumerate(cluster_order)
    }

    # 7. Annotate all segments and words in each turn with their assigned speaker
    for turn_m, old_lbl in zip(turns, turn_labels, strict=False):
        spk_tag = label_to_speaker_id[old_lbl]
        for seg_idx in turn_m:
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

    # 8. Extract clean, representative voice snippets for each speaker cluster
    speaker_samples: dict[str, dict[str, Any]] = {}

    for old_lbl in cluster_order:
        spk_id = label_to_speaker_id[old_lbl]
        member_turns = [
            t_idx for t_idx, lbl_val in enumerate(turn_labels)
            if lbl_val == old_lbl
        ]

        if not member_turns:
            continue

        # Compute speaker centroid
        member_embs = [turn_embeddings[t_idx] for t_idx in member_turns]
        centroid = np.mean(member_embs, axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-8)

        # Rank member turns by duration and cosine closeness to centroid
        best_seg = segments[turns[member_turns[0]][0]]
        best_rank_score = -1e9

        for t_idx in member_turns:
            t_members = turns[t_idx]
            for seg_idx in t_members:
                candidate = segments[seg_idx]
                c_start = float(candidate.get("start", 0.0))
                c_end = float(candidate.get("end", c_start + 1.0))
                c_dur = c_end - c_start

                dur_score = 1.0 if (4.5 <= c_dur <= 6.5) else max(0.1, 1.0 - abs(c_dur - 5.5) * 0.2)
                sim_to_centroid = float(np.dot(turn_embeddings[t_idx], centroid))

                rank = dur_score * 0.6 + sim_to_centroid * 0.4
                if rank > best_rank_score:
                    best_rank_score = rank
                    best_seg = candidate

        snippet_start = float(best_seg.get("start", 0.0))
        snippet_end = min(snippet_start + 6.0, float(best_seg.get("end", snippet_start + 5.5)))
        if snippet_end - snippet_start < 4.5:
            snippet_end = snippet_start + 4.5

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
