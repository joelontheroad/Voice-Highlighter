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

---

### Q8: How does Voice Highlighter prevent WhisperX from misspelling names, technical jargon, or acronyms?

**Short Answer:** **Voice Highlighter uses pre-inference acoustic and language model conditioning to prevent misspellings at the source, eliminating the need to search-and-replace after subtitles are created.**

**Detailed Explanation:**
1. **The Core Problem with General ASR**:
   - Neural speech recognition models like Whisper decode spoken phonemes using prior probabilities learned from massive web datasets. When hearing ambiguous sounds or rare words (e.g. *Katie Kam*, *carburetor*, *PostgreSQL*, *FFmpeg*, *Brembo*), Whisper defaults to generic English words (*"Katie Cam"*, *"car predator"*, *"post grass"*).
2. **Pre-Transcription Prevention Mechanisms**:
   - **Autoregressive Decoder Self-Attention Conditioning (`initial_prompt`)**: An intelligent prompt synthesizer compiles target terms into natural conversational context sentences (`"In this video, the discussion covers the following topics and speakers: Katie Kam, PostgreSQL, carburetor..."`), shifting transformer attention weights toward the exact spellings and casing before the first audio frame is processed.
   - **Beam Search Prefix Logit Boosting (`hotwords`)**: In Faster-Whisper / CTranslate2, the tokens of your target vocabulary are directly boosted during beam search, ensuring candidate hypotheses containing your chosen words survive beam pruning over generic English words.
3. **User-Friendly Pre-Flight Workflows**:
   - **Word Spelling List CRUD**: Type any word or phrase (e.g. *Katie Kam*, *carburetor*) and press `Enter` or click `+ Add Word`. Click any word chip or the `✎` icon to edit spellings in place, or click `&times;` to delete words.
   - **Automatic Metadata Ingestion**: Click `[ 📁 From Filename ]` or `[ 👥 From Speakers ]` to harvest terms with zero duplicate typing.
   - **Preset Persistence**: Custom vocabulary is stored directly inside your Style Presets (`~/.config/voice-highlighter/presets/*.yaml`), so recurring guest names and channel terms are remembered across every video.

---

### Q9: How can creators verify subtitle placement, contrast, and layout across different points in the video before rendering?

**Short Answer:** **Voice Highlighter includes an interactive timeline scrubber, automated 5-point scene snapshot filmstrip, and dialogue-linked scene jumping that lets creators test subtitle placement across changing video backgrounds in sub-50ms without freezing the UI.**

**Detailed Explanation:**
1. **The Video Background Challenge**:
   - Subtitle styling (such as text placement, font size, stroke thickness, and shadow box opacity) might look great against dark clothing at the start of a video, but can become unreadable or clash with lower thirds, white shirts, or camera pans later on.
2. **Sub-50ms Frame Extraction Architecture**:
   - Rather than slow output seeking (`ffmpeg -i ... -ss ...`), Voice Highlighter utilizes fast input seeking (`ffmpeg -ss <timestamp> -i <path> -frames:v 1 -q:v 2`).
   - Frame captures finish in 25–50ms and are cached locally in `$XDG_CACHE_HOME/voice-highlighter/frames/<hash>_<ts>.jpg`.
3. **Three Interactive Scene Jumping Methods**:
   - **Timeline Slider & Step Buttons**: Drag the scrubber slider or use step buttons (`-5s`, `-1s`, `+1s`, `+5s`) to scrub through any timestamp in real time.
   - **5-Point Filmstrip Tray**: Five representative scene checkpoints (`0%`, `25%`, `50%`, `75%`, and `End`) are automatically extracted upon video selection and presented as clickable thumbnails directly beneath the video canvas.
   - **Dialogue-Linked Preview (`[ 👁️ Preview Scene ]`)**: In the Stage Preview, click `Dialog Transcript` to preview actual spoken phrases against frames.
   - **5-Point Filmstrip Tray**: Five representative scene checkpoints (`0%`, `25%`, `50%`, `75%`, and `End`) are automatically extracted upon video selection and presented as clickable thumbnails directly beneath the video canvas.

---

### Q10: Why does Voice Highlighter use an External Text Editor and strictly burn subtitles from disk?

**Short Answer:** **Web browsers are clunky for text editing. Creators already have full-featured text editors (VS Code, Sublime, gedit, Notepad) with syntax highlighting, multi-cursor editing, and regex search/replace. Voice Highlighter integrates directly with your system's default text editor and enforces a strict disk-first pipeline where FFmpeg burns directly from disk.**

**Detailed Explanation:**
1. **The In-App Subtitle Editing Anti-Pattern**:
   - Complex in-browser subtitle tables and drawers with hundreds of text inputs add unnecessary UI friction, consume heavy DOM memory, and lack standard text editing power tools (e.g. `Ctrl+H` regex find/replace, multi-cursor selection, undo trees, syntax plugins).
   - Users prefer opening the `.ass` file in the professional code or text editor of their choice.
2. **Subtitle File & External Editor Hub (Step 2)**:
   - **Prominent File Identity**: The active `.ass` filename and its full filesystem location are prominently displayed in a highlighted badge on the interface.
   - **`[ 📝 Open in Text Editor ]`**: Executes the system's default text editor via native discrete argument vectors (`xdg-open` on Linux, `open -t` on macOS, `os.startfile` on Windows), opening the `.ass` file in VS Code, Sublime, gedit, or Notepad in < 100ms.
   - **`[ 📁 Show in File Manager ]`**: Reveals the subtitle file in your operating system's native file explorer (Nautilus, Finder, Windows Explorer).
   - **`[ 📋 Copy File Path ]`**: One-click clipboard copy of the full absolute path for terminal or scripts.
   - **`[ 🔄 Reload from Disk ]`**: Live querying of file stats (size, line count, dialogue count, last modified timestamp).
3. **Strict Disk-First Burning Guarantee (Zero Stale Buffer Overwrite)**:
   - In earlier web architectures, browser client memory buffers could accidentally overwrite manual edits made on disk.
   - Voice Highlighter strictly enforces that **disk is the single source of truth**:
     - The frontend never transmits in-memory subtitle text during burning (`content: null`).
     - `backend/app.py` reads the `.ass` file strictly from the filesystem at the moment `POST /api/burn-video` is received.
     - An isolated immutable snapshot (`.<name>.burn_<task_id>.ass`) is copied directly on disk for FFmpeg encoding, guaranteeing that any spelling corrections, timing adjustments, or custom tags you saved in your external text editor are 100% burned into the resulting MP4 video.


