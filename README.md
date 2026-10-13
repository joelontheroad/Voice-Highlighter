# 🎙️ Voice Highlighter

> **A high-performance AI studio for generating, editing, and burning word-highlighted animated subtitles directly into videos.**

Accelerated with **WhisperX AI** (word-level forced alignment) and hardware-accelerated **FFmpeg** rendering (NVIDIA NVENC / Apple Silicon VideoToolbox / CPU).

---

## ✨ Features

- **Precision Word Timing**: WhisperX AI delivers phoneme- and word-level synchronized subtitle timing.
- **Dynamic Word Highlighting**: Karaoke/pop-style animated subtitle styling rendered in clean `.ass` format.
- **Two Flexible Workflows**:
  - **Standard 3-Step Production**: Generate Subtitles → Verify & Edit in Inline Drawer → Fast Hardware Burn.
  - **1-Click Draft**: Transcribe and burn directly into video in a single pass without manual review.
- **Inline Text & Timing Editor**: Correct misheard proper nouns, dialogue, and timestamps before final render.
- **Hardware Acceleration**: Built-in support for NVIDIA GPU (NVENC), Apple Silicon (VideoToolbox), and CPU fallback.
- **Cross-Platform**: Designed for Linux, macOS, and Windows.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10, 3.11, or 3.12
- [FFmpeg](https://ffmpeg.org/) (with `libass` support)

### Installation & Launch

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/Voice-Highlighter.git
cd Voice-Highlighter

# Launch Voice Highlighter (creates .venv and installs dependencies on first run)
./run.sh
```

Open `http://localhost:8000` in your web browser.

---

## 🛠️ Project Architecture

```
Voice-Highlighter/
├── backend/
│   ├── app.py              # FastAPI server & async task orchestration
│   ├── transcriber.py      # WhisperX speech recognition & alignment pipeline
│   ├── extractor.py        # Media extraction & FFmpeg hardware video burner
│   ├── ass_generator.py    # Word-level animated ASS subtitle generator
│   └── native_picker.py    # OS-native file chooser dialogs
├── frontend/
│   ├── index.html          # Studio UI layout & subtitle drawer
│   ├── app.js              # State management, websocket/polling & animations
│   └── style.css           # Premium dark-mode design system
├── run.sh                  # Application launcher
└── requirements.txt        # Python dependencies
```

---

## 📄 License

MIT License. See `LICENSE` for details.
