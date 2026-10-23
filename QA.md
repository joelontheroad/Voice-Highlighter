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

### Q3: How do I configure and highlight up to 5 speakers in the current interface?

**Voice Highlighter includes a dedicated Multi-Speaker Voice Studio directly in the "Highlight Style" panel:**

1. **Activate Multi-Speaker Mode:**
   - In the right-hand column under **Highlight Style**, locate the **Voice Highlighting Mode** selector at the very top.
   - Switch from `[ 👤 Single Voice ]` to `[ 👥 Multi-Speaker (1–5 Voices) ]`.
2. **Select Up to 5 Voices:**
   - Click the **`5`** button in the `Voices: [ 2 ] [ 3 ] [ 4 ] [ 5 ]` count selector.
   - Or click the **`🎨 5-Voice Quintet`** theme chip to instantly assign our 5 curated high-contrast colors:
     - **Speaker 1 (`SPEAKER_00`)**: 🟡 Gold (`#FFDF00`)
     - **Speaker 2 (`SPEAKER_01`)**: 🔵 Cyan (`#00E5FF`)
     - **Speaker 3 (`SPEAKER_02`)**: 🌸 Hot Pink (`#FF007F`)
     - **Speaker 4 (`SPEAKER_03`)**: 🟢 Bright Lime (`#00FF66`)
     - **Speaker 5 (`SPEAKER_04`)**: 🟣 Electric Purple (`#B026FF`)
3. **Customize Each Voice (Optional):**
   - Click any tab in the horizontal bar (`Speaker 1` through `Speaker 5`).
   - Change the Display Name (e.g. `Katie`, `Host`, `Guest 1`) or pick a custom highlight color.
   - In the live video preview, clicking a speaker tab instantly previews that voice's highlight animation!
4. **Assign Dialogue Lines to Speakers (Step 2: Verify & Edit Words):**
   - Once your video is transcribed or an `.ass` subtitle file is loaded, open **Step 2 (Verify & Edit Words)**.
   - Every spoken phrase row has an interactive speaker badge (e.g., `[ 🟡 Speaker 1 ]`).
   - Click the badge on any line to cycle through `Speaker 1` → `Speaker 2` → `Speaker 3` → `Speaker 4` → `Speaker 5`.
   - The line immediately re-binds to that speaker channel and updates its ASS subtitle style.
5. **Burn Video:**
   - Click **Burn Video** in Step 3. FFmpeg and NVENC burn each speaker's lines with their custom highlight colors.
6. **Factory Template Shortcut:**
   - In the **Style Presets** card, select **`🎭 Ensemble Quintet (5 Voices)`** from the Factory Templates dropdown and click **Apply** to load 5-speaker highlighting in 1 click anytime!

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

---

### Q6: Can I verify or edit subtitles while the program is actively burning? Will there be read/write collisions?

**Short Answer:** **Yes, you can safely view and edit subtitles while video burning runs in the background. There are no read/write collisions.**

**Technical Mechanics:**
1. **FFmpeg & libass Filter Ingestion**:
   - When FFmpeg initializes the `-vf subtitles='file.ass'` filter, `libass` reads the entire subtitle file into memory at startup (`ass_read_file`) and builds an in-memory `ASS_Track` object.
   - During frame-by-frame video rendering (e.g., across thousands of frames), FFmpeg never re-reads the file from disk. It renders all glyphs purely from RAM.
2. **Execution Snapshotting & Atomic Writes**:
   - To guarantee zero file contention, the backend generates an immutable execution copy (`name.burn_<task_id>.ass`) for FFmpeg.
   - When you edit lines in **Step 2 (Verify & Edit Text)**, writes to the primary `.ass` file execute atomically via temporary file replacement (`os.replace`).
   - If you save edits during a burn, the in-flight burn finishes cleanly using its initial snapshot. The UI informs you that an updated `.ass` is ready for a quick re-burn whenever you choose.

---

### Q7: Why does the progress bar seem to freeze at 94% on long videos, and how can we get accurate time estimates?

**Why It Appeared Stuck at 94%:**
- In the initial implementation, `app.py` set `tasks[task_id]["progress"] = 94` immediately before launching `burn_subtitles_to_video()` as a synchronous `subprocess.run(capture_output=True)`.
- Because Python waited for the entire FFmpeg process to exit before reading stdout/stderr, no intermediate progress was reported to the frontend during encoding. On a 15-minute video taking 3 minutes to encode, the thermometer stayed frozen at 94% the entire time even though the GPU was working at 100%.

**How FFmpeg Progress Telemetry Solves This:**
1. **Real-Time Pipe Polling (`-progress pipe:1`)**:
   - By running FFmpeg with `-progress pipe:1 -nostats` via `subprocess.Popen`, FFmpeg streams live key-value pairs every few frames (`out_time_us`, `fps`, `speed`).
2. **Mathematical Time & ETA Derivation**:
   - Knowing the total media duration $T_{\text{total}}$ from video probing, the current encoded seconds $t_{\text{current}} = \text{out\_time\_us} / 10^6$ directly yields the exact burning progress percentage:
     $$\text{Burn}_{\text{pct}} = \frac{t_{\text{current}}}{T_{\text{total}}} \times 100$$
   - Estimated Time Remaining (ETA) is dynamically calculated from the live encoding speed multiplier $S$:
     $$\text{ETA}_{\text{seconds}} = \frac{T_{\text{total}} - t_{\text{current}}}{S}$$
3. **Three Human-Factor UX Protections Against "Frozen Bar Anxiety"**:
   - **Active Telemetry Pill**: Displays live encoding speed and framerate (`⚡ 182 fps • 7.4x Speed • Frame 14,820`).
   - **Dynamic Time Ratio & Countdown**: Displays live progress (`Burning: 94% • ~24s remaining • 14:06 / 15:00`).
   - **Liveness Shimmer & Elapsed Clock**: An animated wave shimmer and ticking elapsed stopwatch prove the worker process is actively encoding frames even through complex visual scenes.

