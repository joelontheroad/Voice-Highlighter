<!--
SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Voice Highlighter — Questions & Answers (Q&A)

This document addresses frequently asked questions, architectural mechanics, and operational details for **Voice Highlighter Studio**.

---

### Q1: Does Voice Highlighter currently identify multiple speakers automatically?

**Short Answer:** **No, not automatically during the speech transcription step.**

**Detailed Explanation:**
1. **Speech Recognition vs. Speaker Diarization:**
   - When you click **Step 1: Generate Subtitles** (or **Transcribe & Burn**), Voice Highlighter runs **WhisperX**, which executes two discrete machine learning stages:
     1. **Acoustic Transcription** (`faster-whisper` / Whisper large-v3): Decodes spoken phonemes into text tokens.
     2. **Forced Phoneme Alignment** (`wav2vec2`): Aligns acoustic waveform features to each word to determine exact millisecond-accurate start and end timestamps.
   - Neither of these two foundational stages classifies *who* is speaking; they only determine *what* words were uttered and *when*.
2. **Why Diarization Is Currently Disabled in the Pipeline:**
   - In `backend/transcriber.py`, an optional diarization hook exists via `whisperx.DiarizationPipeline()`, but it defaults to `enable_diarization=False`.
   - In `backend/app.py` (`execute_task`), the transcription call does not activate this flag because WhisperX's native diarization engine depends on **PyAnnote.audio** (`pyannote/speaker-diarization-3.1`), which is a **gated model on Hugging Face**. It requires users to register a Hugging Face account, accept PyAnnote's user license agreement, and generate a personal `HF_TOKEN`.
   - To keep Voice Highlighter 100% self-contained, local-first, and zero-telemetry out of the box, automated remote-token-dependent diarization was left inactive by default.

---

### Q2: Why is all my subtitle text formatted and highlighted with the exact same color?

**Detailed Explanation:**
- When WhisperX completes transcription without diarization, the returned JSON structure contains word timestamps, but the `speaker` key on each word is `None`.
- In `backend/ass_generator.py` (`generate_ass_content`), the subtitle compiler loops through all words. If a word lacks a speaker tag, it defaults to:
  ```python
  curr_speaker = w.get("speaker") or seg_speaker or "SPEAKER_00"
  ```
- Because every word is labeled `"SPEAKER_00"`, the subtitle generator styles all events using the **Speaker 1 / Default** visual style (typically white text with yellow active-word highlight `#FFDF00`).
- The multi-speaker rendering engine is fully implemented in the compiler and styles, but because no acoustic diarization classified the voices into separate speaker IDs, all text flows through Channel 1.

---

### Q3: Can I distinguish between multiple speakers right now without automated diarization?

**Yes, via the Interactive Subtitle Drawer (Step 2: Inspect & Edit Text).**

Voice Highlighter includes an interactive multi-speaker workflow:
1. **Multi-Speaker Color Channels:**
   - In the subtitle settings panel, you can configure distinct primary colors, outline colors, and active-word highlight colors for up to 5 speakers (e.g., Speaker 1 = Yellow highlight, Speaker 2 = Cyan highlight, Speaker 3 = Coral highlight).
2. **Interactive Line Reassignment:**
   - Expand the **Step 2: Inspect & Edit Text** drawer (`#cardSubtitleDrawer`).
   - Every dialogue event line displays a speaker badge pill (e.g., `Speaker 1`).
   - Click the badge on any line: it instantly cycles the line to `Speaker 2`, `Speaker 3`, etc.
   - The dialogue event immediately binds to that speaker channel's custom ASS style (`Speaker_SPEAKER_01`, `Speaker_SPEAKER_02`).
3. **Burn Video:**
   - When you click **Burn Video**, the NVENC hardware pipeline renders each speaker's lines using their distinct assigned colors and styles.

---

### Q4: What is the plan to enable automatic multi-speaker identification?

To enable automatic speaker identification out of the box, the following architectural enhancements are planned:

#### Plan Phases:
1. **Phase 1: Hugging Face PyAnnote Integration (Opt-in Token)**
   - Add a configuration field in the Settings panel / CLI (`--hf-token` or `$HF_TOKEN`) and a UI toggle: `[✓] Enable AI Speaker Diarization`.
   - When enabled, `run_whisperx_pipeline()` invokes `whisperx.DiarizationPipeline(use_auth_token=token)`.
   - WhisperX automatically clusters acoustic voice embeddings and assigns `SPEAKER_00`, `SPEAKER_01`, `SPEAKER_02` tags directly to each word segment.
   - Subtitles automatically render in distinct colors per speaker upon initial generation.

2. **Phase 2: Fully Offline, Zero-Config Diarization (Token-Free)**
   - Integrate a lightweight, local-only ONNX acoustic embedding model (e.g. SpeechBrain ECAPA-TDNN or 3D-Speaker CAM++) that runs on local GPU/CPU without requiring Hugging Face accounts or API tokens.
   - Apply local spectral or agglomerative hierarchical clustering (AHC) to segment audio into speaker clusters.
   - Adheres strictly to the project's zero-telemetry and local-privacy principles.

3. **Phase 3: Visual Speaker Identifiers**
   - Support optional speaker name labels (e.g., `[Alex]`, `[Sam]`) or avatar icons positioned above the subtitle envelope.
   - Allow renaming speaker channels (e.g., changing `Speaker 1` to `Host` and `Speaker 2` to `Guest`) directly in the UI.

---

### Q5: How does Voice Highlighter render multi-speaker styling under the hood?

Voice Highlighter uses the Advanced SubStation Alpha (`.ass` v4.00+) format:
1. **V4+ Styles Table:**
   - Registers independent styles for each detected speaker:
     ```text
     Style: Speaker_SPEAKER_00,Montserrat,68,&H00FFFFFF,&H0000DFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,0,2,172,172,422,1
     Style: Speaker_SPEAKER_01,Montserrat,68,&H00FFFFFF,&H00FFE500,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3.5,0,2,172,172,422,1
     ```
2. **Dialogue Event Binding:**
   - Dialogue lines are mapped to their corresponding speaker style:
     ```text
     Dialogue: 0,0:00:01.20,0:00:01.85,Speaker_SPEAKER_00,,0,0,0,,{\c&H0000DFFF&}Welcome{\c&H00FFFFFF&} to the show.
     Dialogue: 0,0:00:02.10,0:00:02.90,Speaker_SPEAKER_01,,0,0,0,,{\c&H00FFE500&}Thanks{\c&H00FFFFFF&} for having me!
     ```
3. **GPU Burning:**
   - FFmpeg compiles the `.ass` script using `libass` and burns the styled glyphs directly into the video stream via NVIDIA NVENC hardware acceleration in ~3 seconds.
