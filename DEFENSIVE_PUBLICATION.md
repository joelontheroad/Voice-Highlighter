<!--
SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# DEFENSIVE PRIOR ART PUBLICATION: VOICE HIGHLIGHTER

> **PUBLICATION DATE**: October 18, 2026  
> **AUTHOR / INVENTOR**: Joel Gonzales (`joelontheroad`)  
> **PROJECT**: Voice Highlighter  
> **LEGAL NOTICE**: Published publicly under 35 U.S.C. § 102(a)(1) to irrevocably place the algorithms, architectures, data structures, and workflows disclosed herein into the public domain and establish unchallengeable prior art against subsequent patent filings by third parties. Licensed under the **GNU Affero General Public License v3.0 (GNU AGPL-3.0)**, including the Section 11 patent license grant.

---

## 1. Executive Summary & Purpose of Defensive Publication

Voice Highlighter is a fully open-source, local-first automated video subtitle and spoken-word karaoke highlighting application. To protect the open-source community, downstream contributors, and commercial end-users from opportunistic patent claims, patent assertion entities (PAEs), or closed-source competitors (e.g., proprietary SaaS video editors), this technical specification formally discloses the core architectural innovations, algorithms, and system integrations of Voice Highlighter.

Under **35 U.S.C. § 102(a)(1)** and international patent harmonization treaties (EPC Article 54, PCT Article 33), a person shall not be entitled to a patent if the claimed invention was patented, described in a printed publication, or in public use, on sale, or otherwise available to the public before the effective filing date of the claimed invention.

By publicly publishing this document within the public repository, any subsequent patent application claiming:
1. Discrete subtitle event slicing with synchronous font scaling and color highlight swaps,
2. Co-located sibling asset lifecycle caching (`.mp4`, `.wav`, `.ass`),
3. Speaker-turn isolation in multi-line block word wrapping,
4. Probed hardware acceleration fallback matrices with null-frame test execution, or
5. Ephemeral launch tokens on localhost-bound Unix socket servers for media tools,

is permanently anticipated under § 102 and/or rendered obvious under § 103 by this disclosure.

---

## 2. Core Architectural Disclosures

```
+---------------------------------------------------------------------------------------+
|                               VOICE HIGHLIGHTER ARCHITECTURE                          |
+---------------------------------------------------------------------------------------+
|                                                                                       |
|   +--------------------+     +-----------------------+     +----------------------+   |
|   | Source Video File  | --> | Sibling Asset Manager | --> | Probed HW Encoder    |   |
|   |   (/dir/media.mp4) |     |  (.wav & .ass cache)  |     |   Matrix (NVENC/etc) |   |
|   +--------------------+     +-----------------------+     +----------------------+   |
|             |                            |                            |               |
|             v                            v                            v               |
|   +--------------------+     +-----------------------+     +----------------------+   |
|   | 16kHz Mono Extr.   |     | WhisperX Neural ASR   |     | ASS Event Slicing    |   |
|   | (FFmpeg / -vn)     | --> | (Phoneme Alignment &  | --> | (`chunk_words` &     |   |
|   |                    |     |  Speaker Diarization) |     |  Discrete Events)    |   |
|   +--------------------+     +-----------------------+     +----------------------+   |
|                                                                       |               |
|                                                                       v               |
|   +--------------------+     +-----------------------+     +----------------------+   |
|   | Direct Web Dialogue| <-- | Localhost Web UI      | <-- | libass Subtitle Burn |   |
|   | Editor (Zero-Burn) |     | (127.0.0.1 + Token)   |     | (Single-Pass NVENC)  |   |
|   +--------------------+     +-----------------------+     +----------------------+   |
|                                                                                       |
+---------------------------------------------------------------------------------------+
```

### 2.1 Discrete Event Slicing Algorithm (`chunk_words_into_blocks`)

Voice Highlighter processes word-level timestamped transcripts produced by speech recognition models (e.g., OpenAI Whisper, WhisperX phoneme alignment) and converts continuous speech into readable, non-cluttered subtitle events.

#### A. Multi-Line Block Chunking with Speaker Isolation
Given a chronological sequence of timestamped words $W = [w_1, w_2, \dots, w_n]$ where each word $w_i = (\text{text}_i, t_{s,i}, t_{e,i}, \text{speaker}_i)$:

1. **Character Budget Normalization**:
   The effective line length threshold $L_{\text{max}}$ is dynamically derived from both user character limits and canvas line width constraints:
   $$L_{\text{max}} = \min\left(C_{\text{max}}, \max\left(12, \left\lfloor \frac{W_{\text{pct}}}{100} \times 35 \right\rfloor \right)\right)$$
   where $C_{\text{max}}$ is the user character limit (e.g., 28 chars) and $W_{\text{pct}}$ is the percentage width of the subtitle bounding box.

2. **Speaker Turn Partitioning**:
   Unlike standard subtitle wrapping algorithms that break exclusively on character counts or punctuation, Voice Highlighter enforces a strict speaker boundary condition. If $\text{speaker}_i \neq \text{speaker}_{i-1}$, any currently accumulating block is immediately terminated and flushed to output, ensuring that dialogue from distinct speakers is never conjoined on the same visual card.

3. **Natural Linguistic Break Penalties**:
   Line breaks are preferred immediately following punctuation tokens (`,`, `.`, `?`, `!`, `;`, `:`). A break occurs when:
   $$\text{length}(\text{line}) + \text{length}(w_i) + 1 > L_{\text{max}} \quad \lor \quad w_{i-1} \in \mathcal{P}_{\text{terminal}}$$

#### B. Discrete ASS Event Generation
Rather than emitting a single SubStation Alpha (ASS) dialogue event spanning an entire sentence and attempting complex multi-color override timers, Voice Highlighter generates a discrete, distinct `Dialogue:` line for *every single spoken word* $w_k$:

- **Event Lifetime**: The dialogue line starts at $t_{s,k}$ and ends at $t_{s,k+1}$ (or $t_{e,k} + \Delta t$ if $w_k$ is the final word in the block).
- **Static Multi-Line Context**: The full block of $M$ lines ($M \le \text{max\_lines}$) is rendered in every slice. Words $w_j$ ($j \ne k$) are rendered in base primary font color (`\c<Primary>`).
- **Dynamic Active Word Transformation**: Active word $w_k$ is injected with real-time styling overrides:
  - Font scaling boost: `{\fscx<S>\fscy<S>\c<Highlight>\3c<Outline>}` where $S \in [100, 180]\%$.
  - Pillar box styling: `{\bord8\3c<BoxBg>\c<BoxFont>}` for Hormozi-style pill backgrounds.
  - Progressive Karaoke Wipe: `{\kf<duration_cs>\c<Highlight>}` where $\text{duration\_cs} = \text{round}((t_{e,k} - t_{s,k}) \times 100)$.
  - Pre-vocal cadence glow: For word $w_{k+1}$, outline border color is primed with `{\3c<Highlight>\bord4}`.

This discrete slicing architecture prevents ASS parser desynchronization across video containers, supports variable framerate (VFR) media, and renders identically on both CPU software (`libass`) and GPU-accelerated decoders (`vf_subtitles`).

---

### 2.2 Sibling Asset Lifecycle State Machine

Video subtitle workflows are traditionally plagued by redundant audio extraction and transcription passes. Voice Highlighter establishes an automated, deterministic filesystem lifecycle based on file co-location:

```
[Input Video]: /path/to/my_video.mp4
      |
      +---> [Sibling Audio]:  /path/to/my_video.wav  (Extracted 16kHz mono)
      |
      +---> [Sibling Subtitle]: /path/to/my_video.ass  (Synchronized word-level ASS)
      |
      +---> [Burned Output]:   /path/to/my_video_subtitled.mp4
```

1. **Existence Probing**: Upon receiving a path `/dir/name.ext`, the system inspects `/dir/name.wav` and `/dir/name.ass`.
2. **Conditional Skip Pipeline**:
   - If `/dir/name.wav` exists with non-zero size, audio extraction is skipped (saving 2–10 seconds of FFmpeg demuxing).
   - If `/dir/name.ass` exists and `reuse_existing_ass` is asserted, WhisperX neural model loading and inference are skipped entirely (saving 30–120 seconds of GPU compute).
3. **In-Browser Zero-Burn Dialogue Correction**:
   Users can load `/dir/name.ass` directly into an in-browser timeline editor, correct spelling, adjust punctuation, or modify timestamps, and save changes back to disk with zero video re-encoding required. Video burning is deferred until final delivery.

---

### 2.3 Probed Hardware Acceleration Fallback Matrix

Voice Highlighter implements a zero-latency hardware encoder discovery mechanism that eliminates transcoding failures caused by missing GPU drivers:

1. **Candidate Encoders**:
   - macOS: `h264_videotoolbox`
   - Linux / Windows NVIDIA: `h264_nvenc`
   - Intel: `h264_qsv`
   - AMD: `h264_amf`
   - Generic CPU: `libx264`

2. **Null-Frame Verification Subprocess**:
   Rather than parsing `ffmpeg -encoders` text output (which frequently reports encoders as supported even when hardware initialization fails), Voice Highlighter executes an instantaneous 1-frame test using a synthetic source:
   ```bash
   ffmpeg -y -f lavfi -i nullsrc=s=64x64:d=0.04 -c:v <encoder_candidate> -f null -
   ```
3. **Result Caching**: The fastest functional encoder is cached in-memory for the lifetime of the process, ensuring that subsequent batch burns execute at maximum GPU throughput without probing latency.

---

### 2.4 Ephemeral Launch Tokens & Localhost Web Security

Unlike conventional web applications that expose HTTP ports to the local area network, Voice Highlighter enforces strict security invariants for local desktop execution:

1. **Localhost Binding**: Servers bind exclusively to loopback interfaces (`127.0.0.1` or `::1`). External interface binding (`0.0.0.0`) is prohibited unless explicitly overridden with `--host`.
2. **CSPRNG Launch Token**: Upon initialization, the server generates a cryptographically random launch token via `secrets.token_hex(32)`. The token is printed to `stderr` as an OSC 8 clickable hyperlink:
   ```
   http://127.0.0.1:8080/?token=7f9a8b1c4e2d3f...
   ```
3. **Strict Session Auth**: Accessing the URL installs a `SameSite=Strict; HttpOnly` session cookie. Any request without a valid bearer token or cookie is rejected with HTTP 401 Unauthorized, preventing Cross-Site Request Forgery (CSRF) from malicious browser tabs.
4. **W3C Content Security Policy**: Every response includes:
   ```http
   Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none';
   X-Content-Type-Options: nosniff
   X-Frame-Options: DENY
   Referrer-Policy: no-referrer
   ```
5. **Zero External CDNs**: All CSS, fonts (Inter, Montserrat, Outfit), icons, and JS scripts are bundled locally and served from the application package, guaranteeing 100% offline functionality and zero remote telemetry.

---

## 3. Public Domain Prior Art Inheritance

Voice Highlighter explicitly incorporates techniques from expired patents and historical public standards, affirming their status as unencumbered public domain technologies:

### 3.1 Pioneer LaserKaraoke Progressive Wipe (US 5,742,569 A)
- **Original Assignee**: Pioneer Electronic Corporation
- **Status**: **EXPIRED (Public Domain)**
- **Disclosed Invention**: Continuous horizontal character fill ("progressive wipe") synchronized with vocal duration.
- **Voice Highlighter Implementation**: Implemented via SubStation Alpha `\kf<duration_cs>` tags. Continuous color transitions across glyphs are generated by computing exact syllable centisecond offsets from WhisperX phoneme alignment.

### 3.2 Sony Dual-Tone & Speaker-Indexed Display (US 5,684,542 A)
- **Original Assignee**: Sony Corporation
- **Status**: **EXPIRED (Public Domain)**
- **Disclosed Invention**: Multi-speaker color indexing and pre-vocal cadence guide highlighting.
- **Voice Highlighter Implementation**: Implemented via per-speaker ASS style sheets (`Speaker_SPEAKER_00`, `Speaker_SPEAKER_01`) and pre-vocal outline priming tags (`\3c<Highlight>\bord4`) applied to upcoming words prior to voice onset.

### 3.3 SubStation Alpha (SSA / ASS v4.00+ Standard)
- **Origin**: CS Low (Kotus, 1996), ASS v4.00+ specification (~2001), `libass` (~2006).
- **Status**: **25+ Year Old Universal Open Standard**
- **Disclosed Elements**: Formatting tags `\c`, `\3c`, `\bord`, `\pos`, `\an`, `\fscx`, `\fscy`, `\k`, `\kf`.
- **Legal Effect**: Any claim by third parties to have invented word-level font scaling, color overrides, or absolute positioning within subtitle streams is completely anticipated by the SubStation Alpha standard.

---

## 4. Statutory Prior Art Affirmation & Licensing

- **Prior Art Status**: This publication constitutes prior art under **35 U.S.C. § 102(a)(1)** and **Article 54(2) EPC**. Any future patent application filed by any entity claiming priority after October 18, 2026 that incorporates the concepts disclosed herein is invalid for lack of novelty and/or obviousness.
- **License**: All software and documentation in Voice Highlighter are released under the **GNU Affero General Public License v3.0 (GNU AGPL-3.0)**.
- **Patent Grant**: Pursuant to Section 11 of the GNU AGPL-3.0, any contributor or distributor automatically grants a perpetual, worldwide, royalty-free patent license to any recipient of the software covering all patent claims owned or controlled by that contributor that are infringed by making, using, or selling their contribution.

---
*End of Defensive Prior Art Publication.*
