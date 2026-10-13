# 🎙️ Voice Highlighter

> **A high-performance AI studio for generating, editing, and burning word-highlighted animated subtitles directly into videos.**

Accelerated with **WhisperX AI** (word-level forced alignment) and hardware-accelerated **FFmpeg** rendering (**NVIDIA NVENC** on Windows/Linux, **Apple Silicon VideoToolbox** on macOS, and **CPU** fallback).

---

## ✨ Features

- **Precision Word Timing**: WhisperX AI delivers phoneme- and word-level synchronized subtitle timing.
- **Dynamic Word Highlighting**: Karaoke/pop-style animated subtitle styling rendered in clean `.ass` format.
- **Two Flexible Workflows**:
  - **Standard 3-Step Production**: Generate Subtitles → Verify & Edit in Inline Drawer → Fast Hardware Burn.
  - **1-Click Draft**: Transcribe and burn directly into video in a single pass without manual review.
- **Inline Text & Timing Editor**: Correct misheard proper nouns, dialogue, and timestamps before final render.
- **Native Desktop Experience**: Runs as a standalone desktop application window or in your browser.
- **Adaptive Hardware Acceleration**: Auto-detects NVIDIA NVENC (GPU), Apple Silicon VideoToolbox (Hardware), and CPU libx264.
- **Cross-Platform Native Dialogs**: Uses Finder on macOS, Windows Explorer on Windows, and GTK/Zenity on Linux.

---

## 🚀 Quickstart: 1-Click Consumer Download (No Git Required)

> **Latest Version**: [**Download Voice-Highlighter-v1.0.0.zip**](https://github.com/joelontheroad/Voice-Highlighter/releases/download/v1.0.0/Voice-Highlighter-v1.0.0.zip) 📦

1. **Download & Extract**: Download [`Voice-Highlighter-v1.0.0.zip`](https://github.com/joelontheroad/Voice-Highlighter/releases/download/v1.0.0/Voice-Highlighter-v1.0.0.zip) and unzip the folder.
2. **Run the Installer**:
   * **🍎 macOS & 🐧 Linux**: Double-click **`install.sh`** (or run `./install.sh` in Terminal).
   * **🪟 Windows**: Double-click **`install.bat`**.
3. **Launch Anytime**: Double-click the **Voice Highlighter** icon created on your Desktop!

---

### Alternative: Git Clone (For Developers)

```bash
# Clone the repository
git clone https://github.com/joelontheroad/Voice-Highlighter.git
cd Voice-Highlighter

# Run installer or launcher
./install.sh      # Full automated setup
./run.sh          # Web browser interface (http://localhost:8000)
./run.sh --app    # Standalone desktop window
```

---

## 🛠️ Project Structure

```
Voice-Highlighter/
├── backend/
│   ├── app.py              # FastAPI server & async task orchestration
│   ├── transcriber.py      # WhisperX speech recognition & alignment pipeline
│   ├── extractor.py        # Media extraction & adaptive FFmpeg hardware burner
│   ├── ass_generator.py    # Word-level animated ASS subtitle generator
│   └── native_picker.py    # Cross-platform native file chooser dialogs
├── frontend/
│   ├── index.html          # Studio UI layout & subtitle drawer
│   ├── app.js              # State management, websocket/polling & animations
│   └── style.css           # Premium dark-mode design system
├── desktop_launcher.py     # Standalone native desktop window runner (PyWebView / App Mode)
├── install.sh              # 1-click installer for macOS and Linux
├── install.bat             # 1-click installer for Windows
├── run.sh                  # Terminal runner for macOS / Linux
├── run.bat                 # Terminal runner for Windows
└── requirements.txt        # Python dependencies
```

---

## 📄 License

MIT License.
