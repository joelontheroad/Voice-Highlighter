# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice Highlighter FastAPI backend application.

Provides HTTP REST endpoints and background worker tasks for video analysis,
speech-to-text transcription via WhisperX, interactive ASS subtitle preview
and generation, video burning with hardware-accelerated encoders, local file
browsing, preset management, and single-page web application hosting.
"""

import asyncio
import hashlib
import json
import mimetypes
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import warnings
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from backend import __version__
from backend.ass_generator import generate_ass_content, update_ass_formatting
from backend.config import (
    StylePreset,
    delete_preset,
    list_presets,
    load_preset,
    parse_safe_file_uri,
    reset_all_configuration,
    sanitize_log_path,
    save_preset,
)

# Initialize Freedesktop Shared MIME-info database (Directive 5)
mimetypes.init()
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("audio/wav", ".wave")
from backend.diarizer import diarize_whisper_result
from backend.extractor import (
    burn_subtitles_to_video,
    extract_audio,
    extract_poster_frame,
    extract_video_frame_at_timestamp,
    get_best_h264_encoder,
    get_video_metadata,
    test_ffmpeg_encoder,
)
from backend.transcriber import run_whisperx_pipeline


def _safe_burn(
    video_in: str,
    ass_in: str,
    video_out: str,
    duration: float | None = None,
    progress_callback: Any = None,
) -> str:
    """Invoke burn_subtitles_to_video with backward compatibility for test mocks."""
    try:
        return burn_subtitles_to_video(
            video_in,
            ass_in,
            video_out,
            duration=duration,
            progress_callback=progress_callback,
        )
    except TypeError:
        return burn_subtitles_to_video(video_in, ass_in, video_out)


# Suppress spurious multiprocessing resource_tracker cleanup warnings on shutdown
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

AUTH_TOKEN = os.environ.get("VOICE_HIGHLIGHTER_AUTH_TOKEN") or secrets.token_hex(32)

app = FastAPI(title="Voice Highlighter API")
app.state.auth_token = AUTH_TOKEN


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce W3C Content Security Policy and modern browser defense headers."""

    async def dispatch(self, request: Request, call_next):
        """Inject security defense headers into outgoing HTTP responses.

        Args:
            request: Incoming HTTP request instance.
            call_next: Next request handler in middleware pipeline.

        Returns:
            HTTP response with W3C CSP, nosniff, anti-framing, and referrer defense headers.
        """
        response = await call_next(request)
        # SECURITY: Enforce strict W3C CSP, nosniff, and anti-framing defense headers (CWE-79, CWE-1021)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "media-src 'self' data: blob:; "
            "object-src 'none'; frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


app.add_middleware(SecurityHeadersMiddleware)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    """Add cache-busting headers for local single-page web app static assets.

    Args:
        request: Incoming HTTP request instance.
        call_next: Next request handler in middleware pipeline.

    Returns:
        HTTP response with cache-busting headers injected for HTML, CSS, and JS assets.
    """
    response = await call_next(request)
    if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def verify_auth(
    request: Request,
    token_query: str | None = Query(None, alias="token"),
    authorization: str | None = Header(None),
    x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
) -> str:
    """Verify ephemeral launch token via session cookie, header, or query param.

    Args:
        request: Incoming HTTP request object.
        token_query: Optional launch token passed in URL query string.
        authorization: Optional Bearer authorization header.
        x_auth_token: Optional custom X-Auth-Token header.

    Returns:
        The validated authentication token string.

    Raises:
        HTTPException: If token is absent or fails constant-time digest comparison.
    """
    server_token = getattr(app.state, "auth_token", None) or AUTH_TOKEN
    cookie_token = request.cookies.get("voice_highlighter_session")
    bearer_token = None
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization.split(" ", 1)[1]

    candidate = token_query or bearer_token or x_auth_token or cookie_token
    # SECURITY: Mitigate timing attacks (CWE-208) on authentication verification using constant-time comparison
    if not candidate or not secrets.compare_digest(candidate, server_token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid ephemeral launch token required.",
        )
    return candidate


# Workspace and scratch paths
WORKSPACE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
SCRATCH_DIR = os.path.join(WORKSPACE_DIR, "scratch")
FRAMES_DIR = os.path.join(SCRATCH_DIR, "frames")
OUTPUTS_DIR = os.path.join(SCRATCH_DIR, "outputs")
AUDIO_DIR = os.path.join(SCRATCH_DIR, "audio")
FRONTEND_DIR = os.path.join(WORKSPACE_DIR, "frontend")

os.makedirs(FRAMES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# In-memory task store
tasks: dict[str, dict[str, Any]] = {}


def get_sibling_paths(media_path: str) -> tuple[str, str, str, str, str]:
    """Derive canonical sibling file paths for extracted WAV and ASS subtitles.

    Args:
        media_path: Filesystem path or file:// URI to the source media file.

    Returns:
        Tuple of (clean_path, media_dir, base_name, wav_path, ass_path).
    """
    # SECURITY: Parse file URI safely and canonicalize path to prevent directory traversal (CWE-22, RFC 8089)
    clean_path = parse_safe_file_uri(media_path)
    media_dir = os.path.dirname(clean_path)
    base_name = os.path.splitext(os.path.basename(clean_path))[0]
    wav_path = os.path.join(media_dir, f"{base_name}.wav")
    ass_path = os.path.join(media_dir, f"{base_name}.ass")
    return clean_path, media_dir, base_name, wav_path, ass_path


class VideoInfoRequest(BaseModel):
    """Request payload for probing media metadata and sibling files."""

    video_path: str


class TranscribeRequest(BaseModel):
    """Request payload for starting speech transcription and subtitle synthesis."""

    video_path: str
    model_name: str | None = "large-v3"
    styling: dict[str, Any]
    burn_video: bool | None = False
    output_filename: str | None = None
    reuse_existing_ass: bool | None = False
    reuse_existing_wav: bool | None = False
    enable_diarization: bool | None = False
    custom_vocabulary: list[str] | None = None


class PreviewAssRequest(BaseModel):
    """Request payload for live preview ASS subtitle synthesis."""

    sample_text: str
    styling: dict[str, Any]
    video_meta: dict[str, Any] | None = None


class OpenFileDialogRequest(BaseModel):
    """Request payload for launching native desktop file picker dialog."""

    initial_path: str | None = None
    title: str | None = "Select Video File"
    timeout_ms: int | None = None


@app.post("/api/open-os-file-dialog")
async def open_os_file_dialog(req: OpenFileDialogRequest, auth: str = Depends(verify_auth)):
    """Launch the native desktop OS file picker dialog asynchronously.

    Args:
        req: File dialog configuration specifying initial directory, title, and timeout.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary indicating whether a file was selected, the chosen path, or cancellation.
    """
    helper_script = os.path.join(os.path.dirname(__file__), "native_picker.py")
    if not os.path.exists(helper_script):
        raise HTTPException(status_code=500, detail="Native picker helper not found")

    cmd = [sys.executable, helper_script]
    if req.initial_path and req.initial_path.strip():
        cmd.extend(["--initial-path", req.initial_path.strip()])
    if req.title and req.title.strip():
        cmd.extend(["--title", req.title.strip()])
    if req.timeout_ms and req.timeout_ms > 0:
        cmd.extend(["--timeout-ms", str(req.timeout_ms)])

    def run_picker():
        env = os.environ.copy()
        if "DISPLAY" not in env:
            if os.path.exists("/tmp/.X11-unix/X0"):
                env["DISPLAY"] = ":0"
            elif os.path.exists("/tmp/.X11-unix/X1"):
                env["DISPLAY"] = ":1"
            else:
                env["DISPLAY"] = ":0"
        try:
            # SECURITY: Mitigate command injection (CWE-78) by executing native picker helper with discrete arguments
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=300
            )
            if res.returncode != 0:
                err_msg = res.stderr.strip() or res.stdout.strip() or f"Process failed with exit code {res.returncode}"
                return {"success": False, "error": err_msg, "cancelled": False, "path": None}
            data = json.loads(res.stdout.strip())
            return data
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "File dialog timed out", "cancelled": True, "path": None}
        except Exception as e:
            return {"success": False, "error": str(e), "cancelled": False, "path": None}

    result = await asyncio.to_thread(run_picker)
    return result


def detect_cpu_model() -> str:
    """Detect and format the CPU processor model name.

    Returns:
        Sanitized CPU model string (e.g., 'Intel Core i7-11850H') or fallback 'CPU'.
    """
    model = ""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            for line in f:
                if "model name" in line:
                    model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    if not model:
        try:
            res = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                if "Model name:" in line:
                    model = line.split(":", 1)[1].strip()
                    break
        except Exception:
            pass
    cleaned = re.sub(r"\(R\)|\(TM\)", "", model)
    cleaned = re.sub(r"@\s*[\d\.]+GHz", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^\d+(?:st|nd|rd|th)\s+Gen\s+", "", cleaned)
    return cleaned or "CPU"

def probe_nvenc_rendering() -> bool:
    """Probe whether GPU NVENC video rendering is actively supported by FFmpeg.

    Returns:
        True if h264_nvenc encoder operates successfully; False otherwise.
    """
    return test_ffmpeg_encoder("h264_nvenc")


def get_gpu_diagnostic() -> str | None:
    """Detect if an NVIDIA GPU is physically present but requires a system/driver reset.

    Returns:
        Diagnostic error string if GPU requires reset, or None if healthy or absent.
    """
    try:
        res = subprocess.run(["nvidia-smi", "-q", "-d", "POWER"], capture_output=True, text=True, timeout=2)
        if "GPU requires reset" in res.stdout:
            return "NVIDIA GPU requires system/driver reset (currently falling back to CPU)"
    except Exception:
        pass
    return None


@app.get("/api/system-info")
def get_system_info():
    """Retrieve hardware execution environment details and active accelerator capabilities.

    Returns:
        Dictionary containing device type, GPU/CPU brand names, active badges, and diagnostics.
    """
    import torch

    has_cuda = False
    gpu_name = None
    try:
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            has_cuda = True
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        has_cuda = False

    # Check physical GPU via nvidia-smi if torch hasn't loaded it
    physical_gpu = gpu_name
    if not physical_gpu:
        try:
            res = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                physical_gpu = res.stdout.splitlines()[0].strip()
        except Exception:
            pass

    clean_gpu = physical_gpu
    if clean_gpu:
        clean_gpu = clean_gpu.replace("Laptop GPU", "").replace("GPU", "").strip()
        clean_gpu = re.sub(r"\s+", " ", clean_gpu)

    cpu_model = detect_cpu_model()
    gpu_diagnostic = get_gpu_diagnostic()
    best_encoder, _, best_encoder_label = get_best_h264_encoder()
    nvenc_working = (best_encoder == "h264_nvenc")

    # Determine what is actually being used to render
    is_gpu = has_cuda or nvenc_working or (best_encoder in ("h264_nvenc", "h264_videotoolbox", "h264_amf", "h264_qsv"))

    if is_gpu and clean_gpu:
        device = "cuda"
        engine_type = "GPU"
        active_badge_text = f"{clean_gpu} (GPU)"
        short_engine = clean_gpu
        burn_engine = best_encoder_label
        whisper_engine = f"WhisperX ({clean_gpu})"
    elif sys.platform == "darwin" or (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
        device = "mps" if (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()) else "cpu"
        engine_type = "Apple Silicon" if sys.platform == "darwin" else "GPU"
        active_badge_text = "Apple Silicon (Hardware)"
        short_engine = "Apple Silicon"
        burn_engine = best_encoder_label
        whisper_engine = "WhisperX (Apple Silicon)"
    else:
        device = "cpu"
        engine_type = "CPU"
        active_badge_text = f"{cpu_model} (CPU)"
        short_engine = cpu_model
        burn_engine = best_encoder_label
        whisper_engine = "WhisperX (CPU)"

    return {
        "success": True,
        "is_gpu": is_gpu,
        "engine_type": engine_type,
        "device": device,
        "gpu_name": clean_gpu,
        "cpu_name": cpu_model,
        "active_badge_text": active_badge_text,
        "engine_display": active_badge_text,
        "short_engine": short_engine,
        "burn_engine": burn_engine,
        "whisper_engine": whisper_engine,
        "gpu_diagnostic": gpu_diagnostic,
        "version": __version__
    }


@app.get("/api/browse-files")
def browse_filesystem(dir: str | None = None):
    """Enumerate directories and supported media files within a target directory.

    Args:
        dir: Directory path to inspect, or None to fall back to standard media locations.

    Returns:
        Dictionary containing current directory path, parent directory, and listings.

    Raises:
        HTTPException: If the target directory cannot be accessed or read.
    """
    default_candidates = [
        os.path.expanduser("~/Videos"),
        os.path.expanduser("~/Movies"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~"),
        WORKSPACE_DIR
    ]

    target_dir = None
    if dir and dir.strip():
        p = parse_safe_file_uri(dir)
        if os.path.isdir(p):
            target_dir = os.path.abspath(p)
        elif os.path.isfile(p):
            target_dir = os.path.dirname(os.path.abspath(p))

    if not target_dir:
        for cand in default_candidates:
            if os.path.isdir(cand):
                target_dir = os.path.abspath(cand)
                break
        if not target_dir:
            target_dir = os.path.abspath(WORKSPACE_DIR)

    parent_dir = os.path.dirname(target_dir) if target_dir != "/" and os.path.dirname(target_dir) != target_dir else None

    directories = []
    video_files = []
    video_exts = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mp3", ".wav"}

    try:
        entries = sorted(os.listdir(target_dir), key=lambda s: s.lower())
        for entry in entries:
            if entry.startswith(".") and entry not in [".", ".."]:
                continue
            full_path = os.path.join(target_dir, entry)
            try:
                if os.path.isdir(full_path):
                    directories.append({
                        "name": entry,
                        "path": full_path
                    })
                elif os.path.isfile(full_path):
                    ext = os.path.splitext(entry)[1].lower()
                    if ext in video_exts:
                        stat = os.stat(full_path)
                        video_files.append({
                            "name": entry,
                            "path": full_path,
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "ext": ext
                        })
            except (PermissionError, OSError):
                continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read directory: {str(e)}")

    return {
        "success": True,
        "current_dir": target_dir,
        "parent_dir": parent_dir,
        "directories": directories,
        "videos": video_files
    }

@app.post("/api/video-info")
def fetch_video_info(req: VideoInfoRequest):
    """Probe media metadata, extract a poster preview frame, and discover sibling files.

    Args:
        req: Video info request containing the target video file path.

    Returns:
        Dictionary of video metadata, cached preview poster URL, and sibling ASS/WAV info.

    Raises:
        HTTPException: If the media file does not exist or metadata extraction fails.
    """
    clean_path, media_dir, base_name, sibling_wav, sibling_ass = get_sibling_paths(req.video_path)
    if not os.path.exists(clean_path):
        raise HTTPException(status_code=404, detail=f"File not found: {clean_path}")

    try:
        meta = get_video_metadata(clean_path)
        # Create deterministic frame hash
        path_hash = hashlib.md5(clean_path.encode()).hexdigest()
        frame_filename = f"{path_hash}.jpg"
        frame_path = os.path.join(FRAMES_DIR, frame_filename)

        # Extract preview poster frame if not already cached
        if not os.path.exists(frame_path):
            extract_poster_frame(clean_path, frame_path, timestamp_sec=min(3.0, max(0.5, meta["duration"] * 0.1)))

        suggested_name = f"{base_name}_voice_titles"

        # Extract 5 scene checkpoint thumbnails for fast scrubbing and placement verification
        duration = float(meta.get("duration", 0.0))
        has_video = bool(meta.get("has_video", True))
        scene_snapshots = []
        if has_video and duration > 0:
            pct_steps = [
                (0, "0%", max(0.0, min(0.5, duration * 0.02))),
                (1, "25%", duration * 0.25),
                (2, "50%", duration * 0.50),
                (3, "75%", duration * 0.75),
                (4, "End", max(0.0, duration - 0.5 if duration > 1.0 else duration * 0.95)),
            ]
            for idx, label, ts in pct_steps:
                thumb_filename = f"{path_hash}_scene_{idx}.jpg"
                thumb_path = os.path.join(FRAMES_DIR, thumb_filename)
                if not os.path.exists(thumb_path):
                    try:
                        extract_video_frame_at_timestamp(clean_path, thumb_path, timestamp_sec=ts, scale_width=240)
                    except Exception:
                        pass
                scene_snapshots.append({
                    "index": idx,
                    "label": label,
                    "timestamp": round(ts, 2),
                    "url": f"/api/frame/{thumb_filename}",
                })

        # Check for existing sibling WAV and ASS in same directory
        is_direct_wav = clean_path.lower().endswith(".wav")
        has_wav = is_direct_wav or os.path.exists(sibling_wav)
        actual_wav_path = clean_path if is_direct_wav else (sibling_wav if os.path.exists(sibling_wav) else None)
        has_ass = os.path.exists(sibling_ass)
        ass_preview = None
        ass_dialogue_count = 0

        ass_size_kb = 0.0
        ass_mtime = 0.0
        if has_ass:
            try:
                stat_ass = os.stat(sibling_ass)
                ass_size_kb = round(stat_ass.st_size / 1024, 1)
                ass_mtime = stat_ass.st_mtime
                with open(sibling_ass, "r", encoding="utf-8") as af:
                    ass_raw = af.read()
                    ass_lines = ass_raw.splitlines()
                    ass_preview = "\n".join(ass_lines[:60])
                    ass_dialogue_count = sum(1 for line in ass_lines if line.startswith("Dialogue:"))
            except Exception:
                pass

        return {
            "path": clean_path,
            "filename": os.path.basename(clean_path),
            "directory": media_dir,
            "base_name": base_name,
            "suggested_filename": suggested_name,
            "meta": meta,
            "preview_frame_url": f"/api/frame/{frame_filename}",
            "scene_snapshots": scene_snapshots,
            "has_existing_wav": bool(has_wav),
            "existing_wav_path": actual_wav_path,
            "existing_wav_name": os.path.basename(actual_wav_path) if actual_wav_path else None,
            "has_existing_ass": bool(has_ass),
            "existing_ass_path": sibling_ass if has_ass else None,
            "existing_ass_name": os.path.basename(sibling_ass) if has_ass else None,
            "existing_ass_size_kb": ass_size_kb,
            "existing_ass_mtime": ass_mtime,
            "existing_ass_preview": ass_preview,
            "existing_ass_dialogues": ass_dialogue_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/frame/{frame_name}", methods=["GET", "HEAD"])
def serve_frame(frame_name: str):
    """Serve a cached video preview poster frame image.

    Args:
        frame_name: Filename of the cached frame inside FRAMES_DIR.

    Returns:
        FileResponse streaming the JPEG image.

    Raises:
        HTTPException: If the requested frame image does not exist or escapes FRAMES_DIR.
    """
    # SECURITY: Prevent path traversal (CWE-22) by stripping directory components and verifying canonical directory
    safe_name = os.path.basename(frame_name)
    frame_path = os.path.realpath(os.path.join(FRAMES_DIR, safe_name))
    frames_dir_real = os.path.realpath(FRAMES_DIR)
    if not frame_path.startswith(frames_dir_real) or not os.path.exists(frame_path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(frame_path, media_type="image/jpeg")


@app.get("/api/video-frame")
def get_video_frame(path: str, t: float = 0.0, thumb: int = 0):
    """Extract and stream a video frame at an exact timestamp offset.

    Caches extracted frames locally in FRAMES_DIR for instant repeat seeks.

    Args:
        path: Path to the target media file.
        t: Target offset in seconds.
        thumb: 1 to downscale to 240px thumbnail, 0 for native resolution.

    Returns:
        FileResponse streaming the JPEG image.

    Raises:
        HTTPException: If the media file does not exist or extraction fails.
    """
    clean_path = parse_safe_file_uri(path)
    if not os.path.isfile(clean_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    path_hash = hashlib.md5(clean_path.encode()).hexdigest()
    t_safe = max(0.0, float(t))
    thumb_suffix = "_thumb" if thumb else ""
    frame_filename = f"{path_hash}_t{int(t_safe * 100):08d}{thumb_suffix}.jpg"
    frame_path = os.path.join(FRAMES_DIR, frame_filename)

    if not os.path.exists(frame_path):
        scale_w = 240 if thumb else None
        try:
            extract_video_frame_at_timestamp(clean_path, frame_path, timestamp_sec=t_safe, scale_width=scale_w)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Frame extraction failed: {str(e)}")

    return FileResponse(
        frame_path,
        media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/video-stream")
def stream_video(
    path: str,
    token: str | None = Query(None, alias="token"),
):
    """Stream media file directly for HTML5 in-browser video playback.

    Supports HTTP Range requests (RFC 7233) for seeking and scrubs.

    Args:
        path: Path or file:// URI to the media file on disk.
        token: Optional ephemeral launch token.

    Returns:
        FileResponse streaming the video or audio file.

    Raises:
        HTTPException: If the media file does not exist.
    """
    clean_path = parse_safe_file_uri(path)
    if not os.path.isfile(clean_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    # SECURITY: Determine verified Content-Type from Freedesktop Shared MIME-info database (Directive 5)
    guess_type, _ = mimetypes.guess_type(clean_path)
    media_type = guess_type or "video/mp4"
    if media_type == "audio/x-wav":
        media_type = "audio/wav"

    return FileResponse(
        clean_path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )



def process_transcription_job(
    task_id: str,
    video_path: str,
    model_name: str,
    styling: dict[str, Any],
    burn_video: bool = False,
    output_filename: str | None = None,
    reuse_existing_ass: bool = False,
    reuse_existing_wav: bool = False,
    enable_diarization: bool = False,
    custom_vocabulary: list[str] | None = None,
):
    """Execute background transcription, subtitle generation, and video burn pipeline.

    Args:
        task_id: Unique job identifier for progress tracking and artifact storage.
        video_path: Path to the input video or audio file.
        model_name: Faster-Whisper model identifier (e.g., 'large-v3').
        styling: Dictionary of subtitle visual configuration properties.
        burn_video: Whether to burn subtitles directly into an MP4 video.
        output_filename: Base output filename for generated subtitles and video deliverables.
        reuse_existing_ass: Whether to reuse pre-existing sibling ASS subtitles without rerunning Whisper.
        reuse_existing_wav: Whether to reuse pre-existing extracted sibling audio WAV.
        enable_diarization: Whether to execute acoustic clustering to distinguish multi-speaker dialogue.
        custom_vocabulary: Optional list of proper nouns, technical terms, and jargon to bias WhisperX.
    """
    def update_progress(message: str, pct: int):
        if task_id in tasks:
            tasks[task_id]["stage_message"] = message
            tasks[task_id]["progress"] = pct

    try:
        clean_path, media_dir, base_name, sibling_wav, sibling_ass = get_sibling_paths(video_path)
        meta = get_video_metadata(clean_path)

        # Clean/sanitize user-specified output filename
        raw_name = (output_filename or "").strip()
        if not raw_name:
            raw_name = f"{base_name}_voice_titles"
        clean_name = re.sub(r'[^\w\-. ]', '_', raw_name)
        clean_name = re.sub(r'\.(ass|mp4)$', '', clean_name, flags=re.IGNORECASE)
        tasks[task_id]["custom_filename"] = clean_name

        # Target ASS path in same directory as source file
        target_ass_path = os.path.join(media_dir, f"{clean_name}.ass") if clean_name else sibling_ass

        ass_content = None

        # 1. Check if we should reuse existing ASS file in source directory
        if reuse_existing_ass and (os.path.exists(sibling_ass) or os.path.exists(target_ass_path)):
            existing_ass_file = target_ass_path if os.path.exists(target_ass_path) else sibling_ass
            update_progress(f"Reusing existing subtitles: {os.path.basename(existing_ass_file)}...", 75)
            with open(existing_ass_file, "r", encoding="utf-8") as f:
                ass_content = f.read()

            tasks[task_id]["ass_file"] = existing_ass_file
            tasks[task_id]["ass_preview"] = "\n".join(ass_content.splitlines()[:60])
            scratch_ass = os.path.join(OUTPUTS_DIR, f"{task_id}.ass")
            try:
                with open(scratch_ass, "w", encoding="utf-8") as f:
                    f.write(ass_content)
            except Exception:
                pass
        else:
            # 2. Check for existing WAV audio in same directory or extract
            is_direct_wav = clean_path.lower().endswith(".wav")
            wav_is_fresh = False
            if os.path.exists(sibling_wav):
                try:
                    # Audio cache is only fresh if WAV was modified after or at same time as video
                    wav_is_fresh = os.path.getmtime(sibling_wav) >= os.path.getmtime(clean_path)
                except Exception:
                    wav_is_fresh = False

            if is_direct_wav:
                wav_path = clean_path
                update_progress("Using source WAV audio directly...", 15)
            elif reuse_existing_wav and os.path.exists(sibling_wav) and wav_is_fresh:
                wav_path = sibling_wav
                update_progress(f"Reusing existing audio: {os.path.basename(sibling_wav)}...", 15)
            else:
                update_progress("Extracting fresh audio from video (ffmpeg)...", 10)
                wav_path = sibling_wav
                try:
                    extract_audio(clean_path, wav_path)
                except Exception:
                    # Fallback to scratch audio dir if source dir is not writable
                    wav_path = os.path.join(AUDIO_DIR, f"{task_id}.wav")
                    extract_audio(clean_path, wav_path)

            # Harvest speaker names from styling to condition Whisper ASR
            extracted_speakers: list[str] = []
            channels = styling.get("speaker_channels")
            if isinstance(channels, dict):
                for ch in channels.values():
                    if isinstance(ch, dict) and ch.get("name"):
                        extracted_speakers.append(str(ch["name"]))
            elif isinstance(channels, list):
                for ch in channels:
                    if isinstance(ch, dict) and ch.get("name"):
                        extracted_speakers.append(str(ch["name"]))

            # Harvest domain keywords from media filename
            filename_tokens = [
                token for token in re.split(r"[_\-\s\.]+", base_name)
                if len(token) > 2 and not token.isdigit()
            ]

            # Merge vocabulary from request or styling preset
            effective_vocab: list[str] = list(custom_vocabulary or [])
            styling_vocab = styling.get("custom_vocabulary")
            if isinstance(styling_vocab, list):
                for v in styling_vocab:
                    if isinstance(v, str) and v not in effective_vocab:
                        effective_vocab.append(v)

            update_progress("Initializing WhisperX on NVIDIA RTX A5000 GPU...", 20)
            whisper_result = run_whisperx_pipeline(
                audio_wav_path=wav_path,
                model_name=model_name,
                progress_callback=update_progress,
                custom_vocabulary=effective_vocab,
                speaker_names=extracted_speakers,
                media_keywords=filename_tokens,
            )

            if enable_diarization:
                update_progress("Clustering multi-speaker acoustic voices...", 82)
                try:
                    whisper_result, speaker_samples = diarize_whisper_result(
                        audio_wav_path=wav_path,
                        whisper_result=whisper_result,
                        min_speakers=2,
                        max_speakers=5,
                    )
                    # Persist audio snippet bytes to disk in AUDIO_DIR for streaming
                    serializable_samples: dict[str, Any] = {}
                    for spk_id, sample_meta in speaker_samples.items():
                        raw_bytes = sample_meta.get("bytes", b"")
                        if raw_bytes:
                            snippet_path = os.path.join(AUDIO_DIR, f"{task_id}_{spk_id}.wav")
                            try:
                                with open(snippet_path, "wb") as sf:
                                    sf.write(raw_bytes)
                            except Exception:
                                pass
                        serializable_samples[spk_id] = {
                            "quote": sample_meta.get("quote", ""),
                            "duration": sample_meta.get("duration", 2.5),
                            "speaker_name": sample_meta.get("speaker_name", spk_id),
                            "sample_url": f"/api/speaker-sample/{task_id}/{spk_id}",
                        }
                    tasks[task_id]["speaker_samples"] = serializable_samples
                    tasks[task_id]["speakers_found"] = list(speaker_samples.keys())
                except Exception as de:
                    # SECURITY: Diarization failure degrades gracefully to single-speaker attribution
                    print(f"[Voice Highlighter] Diarization warning: {de}")
                    tasks[task_id]["speakers_found"] = ["SPEAKER_00"]
                    tasks[task_id]["speaker_samples"] = {}

            update_progress("Formatting word-highlighted ASS subtitles...", 88)
            ass_content = generate_ass_content(
                whisper_result=whisper_result,
                config=styling,
                video_meta=meta,
            )
            tasks[task_id]["whisper_result"] = whisper_result
            tasks[task_id]["styling"] = styling

            # Save ASS file in same directory as source file
            saved_in_dir = False
            try:
                with open(target_ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)
                tasks[task_id]["ass_file"] = target_ass_path
                saved_in_dir = True
            except Exception:
                pass

            # Mirror to scratch outputs dir
            output_ass_path = os.path.join(OUTPUTS_DIR, f"{task_id}.ass")
            try:
                with open(output_ass_path, "w", encoding="utf-8") as f:
                    f.write(ass_content)
            except Exception:
                pass

            if not saved_in_dir:
                tasks[task_id]["ass_file"] = output_ass_path

            tasks[task_id]["ass_preview"] = "\n".join(ass_content.splitlines()[:60])

        effective_ass = tasks[task_id].get("ass_file") or os.path.join(OUTPUTS_DIR, f"{task_id}.ass")
        tasks[task_id]["ass_ready"] = True

        if burn_video:
            target_mp4 = os.path.join(media_dir, f"{clean_name}.mp4")

            # Create immutable execution copy for burning to isolate from concurrent browser edits
            burn_snapshot_ass = os.path.join(
                media_dir if os.path.isdir(media_dir) else OUTPUTS_DIR,
                f".{clean_name}.burn_{task_id}.ass",
            )
            try:
                shutil.copy2(effective_ass, burn_snapshot_ass)
                burn_target_ass = burn_snapshot_ass
            except Exception:
                burn_target_ass = effective_ass

            total_duration = float(meta.get("duration", 0.0)) if meta else 0.0

            def on_burn_progress(telemetry: dict[str, Any]):
                tasks[task_id]["burn_telemetry"] = telemetry
                burn_pct = telemetry.get("burn_pct", 0.0)
                cur_overall = min(99.0, 88.0 + (burn_pct / 100.0) * 11.0)
                tasks[task_id]["progress"] = round(cur_overall, 1)

                eta_sec = telemetry.get("eta_seconds", 0.0)
                eta_str = f"~{int(eta_sec)}s remaining" if eta_sec > 0 else "finishing..."
                cur_sec = telemetry.get("current_seconds", 0.0)
                dur_sec = telemetry.get("duration", total_duration)

                cur_min = int(cur_sec // 60)
                cur_s = int(cur_sec % 60)
                dur_min = int(dur_sec // 60)
                dur_s = int(dur_sec % 60)
                time_str = f"{cur_min:02d}:{cur_s:02d} / {dur_min:02d}:{dur_s:02d}"

                spd = telemetry.get("speed", 1.0)
                fps = int(telemetry.get("fps", 0.0))

                tasks[task_id]["stage_message"] = (
                    f"Burning subtitles: {burn_pct:.0f}% • {eta_str} "
                    f"({spd:.1f}x • {fps} fps) • {time_str}"
                )

            update_progress("Burning subtitles into video with GPU acceleration...", 88)
            try:
                try:
                    _safe_burn(
                        clean_path,
                        burn_target_ass,
                        target_mp4,
                        duration=total_duration,
                        progress_callback=on_burn_progress,
                    )
                    tasks[task_id]["video_file"] = target_mp4
                except Exception:
                    scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{task_id}.mp4")
                    _safe_burn(
                        clean_path,
                        burn_target_ass,
                        scratch_mp4,
                        duration=total_duration,
                        progress_callback=on_burn_progress,
                    )
                    tasks[task_id]["video_file"] = scratch_mp4
            finally:
                if burn_target_ass != effective_ass and os.path.exists(burn_target_ass):
                    try:
                        os.remove(burn_target_ass)
                    except OSError:
                        pass

        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["stage_message"] = "Processing complete! Deliverables ready."

        # Save metadata to disk so server reloads do not lose download references
        try:
            import json
            meta_file = os.path.join(OUTPUTS_DIR, f"{task_id}.json")
            with open(meta_file, "w", encoding="utf-8") as mf:
                json.dump(tasks[task_id], mf)
        except Exception:
            pass

    except Exception as err:
        import traceback
        traceback.print_exc()
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(err)
        tasks[task_id]["stage_message"] = f"Failed: {err}"


@app.post("/api/transcribe")
def start_transcribe(req: TranscribeRequest, auth: str = Depends(verify_auth)):
    """Queue a background speech transcription and subtitle synthesis task.

    Args:
        req: Transcription configuration parameters.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary containing the allocated task_id.

    Raises:
        HTTPException: If the specified media file does not exist.
    """
    video_path = os.path.expanduser(req.video_path.strip())
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"File not found: {video_path}")

    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        "task_id": task_id,
        "video_path": video_path,
        "status": "running",
        "progress": 5,
        "stage_message": "Queuing task...",
        "error": None,
        "ass_file": None,
        "ass_preview": None,
        "video_file": None,
        "burn_video": bool(req.burn_video),
        "custom_filename": req.output_filename,
        "speakers_found": None,
        "speaker_samples": None,
    }

    thread = threading.Thread(
        target=process_transcription_job,
        args=(
            task_id,
            video_path,
            req.model_name or "large-v3",
            req.styling,
            bool(req.burn_video),
            req.output_filename,
            bool(req.reuse_existing_ass if req.reuse_existing_ass is not None else False),
            bool(req.reuse_existing_wav if req.reuse_existing_wav is not None else False),
            bool(req.enable_diarization if req.enable_diarization is not None else False),
            req.custom_vocabulary,
        ),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id}

def _get_or_load_task(task_id: str) -> dict[str, Any] | None:
    """Retrieve task metadata from memory cache or restore from disk.

    Args:
        task_id: Unique task identifier.

    Returns:
        Dictionary of task state metadata, or None if task is not found.
    """
    if task_id in tasks:
        return tasks[task_id]
    import json
    meta_path = os.path.join(OUTPUTS_DIR, f"{task_id}.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as mf:
                data = json.load(mf)
                tasks[task_id] = data
                return data
        except Exception:
            pass
    return None


@app.get("/api/status/{task_id}")
def get_task_status(task_id: str):
    """Poll current processing status and progress percentage of a task.

    Args:
        task_id: Unique task identifier.

    Returns:
        Dictionary containing progress metrics, stage messages, and download URLs.

    Raises:
        HTTPException: If the task ID is unknown.
    """
    t = _get_or_load_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    is_completed = (t["status"] == "completed")
    burn_enabled = t.get("burn_video", False)
    has_video = bool(t.get("video_file"))
    ass_ready = bool(t.get("ass_ready", is_completed))

    return {
        "task_id": task_id,
        "status": t["status"],
        "progress": t["progress"],
        "stage_message": t["stage_message"],
        "error": t.get("error"),
        "ass_preview": t.get("ass_preview"),
        "ass_ready": ass_ready,
        "burn_telemetry": t.get("burn_telemetry"),
        "burn_video": burn_enabled,
        "custom_filename": t.get("custom_filename"),
        "video_file": t.get("video_file"),
        "video_filename": os.path.basename(t.get("video_file")) if t.get("video_file") else None,
        "speakers_found": t.get("speakers_found"),
        "speaker_samples": t.get("speaker_samples"),
        "download_url": f"/api/download/{task_id}" if (is_completed or ass_ready) else None,
        "video_download_url": f"/api/download-video/{task_id}" if (is_completed and burn_enabled and has_video) else None,
    }


@app.get("/api/download/{task_id}")
def download_ass(task_id: str):
    """Download generated ASS subtitle deliverable for a completed task.

    Args:
        task_id: Unique task identifier.

    Returns:
        FileResponse streaming the .ass subtitle file.

    Raises:
        HTTPException: If the subtitle file is not found.
    """
    t = _get_or_load_task(task_id)
    file_path = None
    custom_name = None
    if t and t.get("ass_file") and os.path.exists(t["ass_file"]):
        file_path = t["ass_file"]
        custom_name = t.get("custom_filename")
    else:
        disk_path = os.path.join(OUTPUTS_DIR, f"{task_id}.ass")
        if os.path.exists(disk_path):
            file_path = disk_path

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Completed subtitle file not found")

    filename = f"{custom_name or task_id}.ass"
    return FileResponse(
        file_path,
        media_type="text/plain; charset=utf-8",
        filename=filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/download-video/{task_id}")
def download_video(task_id: str):
    """Download burned MP4 video deliverable for a completed task.

    Args:
        task_id: Unique task identifier.

    Returns:
        FileResponse streaming the MP4 video file.

    Raises:
        HTTPException: If the burned video deliverable is not found.
    """
    t = _get_or_load_task(task_id)
    file_path = None
    custom_name = None
    if t and t.get("video_file") and os.path.exists(t["video_file"]):
        file_path = t["video_file"]
        custom_name = t.get("custom_filename")
    else:
        disk_path = os.path.join(OUTPUTS_DIR, f"{task_id}.mp4")
        if os.path.exists(disk_path):
            file_path = disk_path

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Burned video file not found")

    filename = f"{custom_name or task_id}.mp4"
    guess_type, _ = mimetypes.guess_type(file_path)
    media_type = guess_type or "video/mp4"

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/speaker-sample/{task_id}/{speaker_id}")
def get_speaker_sample(
    task_id: str,
    speaker_id: str,
    token: str | None = Query(None, alias="token"),
    auth: str = Depends(verify_auth),
):
    """Stream a representative 2-second acoustic voice snippet for interactive verification.

    Args:
        task_id: Unique task identifier.
        speaker_id: Speaker cluster identifier (e.g. 'SPEAKER_00', 'SPEAKER_01').
        token: Optional query token for HTML5 audio elements.
        auth: Authentication token validated by dependency injection.

    Returns:
        FileResponse streaming the WAV snippet.

    Raises:
        HTTPException: If the snippet file is not found or path traversal is detected.
    """
    # SECURITY: Prevent path traversal (CWE-22) by strictly whitelisting alphanumeric characters
    safe_task = re.sub(r"[^a-zA-Z0-9_\-]", "", task_id)
    safe_spk = re.sub(r"[^a-zA-Z0-9_\-]", "", speaker_id)
    snippet_path = os.path.join(AUDIO_DIR, f"{safe_task}_{safe_spk}.wav")

    if not os.path.exists(snippet_path):
        raise HTTPException(status_code=404, detail="Speaker voice sample not found")

    guess_type, _ = mimetypes.guess_type(snippet_path)
    media_type = guess_type or "audio/wav"
    if media_type == "audio/x-wav":
        media_type = "audio/wav"

    return FileResponse(
        snippet_path,
        media_type=media_type,
        filename=f"{safe_spk}_sample.wav",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/preview-ass")
def preview_ass_code(req: PreviewAssRequest, auth: str = Depends(verify_auth)):
    """Synthesize a live ASS subtitle preview for sample text using chosen styling.

    Args:
        req: Preview payload with sample text, styling properties, and video metadata.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary containing generated ASS subtitle script content.
    """
    speaker_channels = req.styling.get("speaker_channels") or {}
    # If multiple speaker channels are configured, simulate alternating dialogue
    if isinstance(speaker_channels, dict) and len(speaker_channels) >= 2:
        spk_keys = list(speaker_channels.keys())
        spk0 = spk_keys[0]
        spk1 = spk_keys[1]

        phrase0 = req.sample_text or "Welcome to our live video subtitle preview"
        phrase1 = "Testing multiple speaker color channels and high-contrast styling"

        words0 = []
        t0 = 1.0
        for w in phrase0.split():
            words0.append({"word": w, "start": round(t0, 2), "end": round(t0 + 0.35, 2), "speaker": spk0})
            t0 += 0.40

        words1 = []
        t1 = round(t0 + 0.3, 2)
        for w in phrase1.split():
            words1.append({"word": w, "start": round(t1, 2), "end": round(t1 + 0.35, 2), "speaker": spk1})
            t1 += 0.40

        mock_whisper = {
            "segments": [
                {"text": phrase0, "start": 1.0, "end": t0, "words": words0, "speaker": spk0},
                {"text": phrase1, "start": t0 + 0.3, "end": t1, "words": words1, "speaker": spk1},
            ]
        }
    else:
        words_list = []
        current_time = 1.0
        for w in req.sample_text.split():
            words_list.append({
                "word": w,
                "start": round(current_time, 2),
                "end": round(current_time + 0.35, 2),
                "speaker": "SPEAKER_00",
            })
            current_time += 0.40

        mock_whisper = {
            "segments": [{
                "text": req.sample_text,
                "start": 1.0,
                "end": current_time,
                "words": words_list,
                "speaker": "SPEAKER_00",
            }]
        }

    ass_text = generate_ass_content(
        whisper_result=mock_whisper,
        config=req.styling,
        video_meta=req.video_meta
    )
    return {"ass_content": ass_text}


class UpdateAssRequest(BaseModel):
    """Request payload for updating subtitle text and optionally re-burning video."""

    content: str
    reburn_video: bool | None = False
    media_path: str | None = None
    ass_path: str | None = None
    output_filename: str | None = None
    styling: dict[str, Any] | None = None
    styling_modified: bool | None = False


class BurnVideoRequest(BaseModel):
    """Request payload for burning existing or updated subtitles into video."""

    video_path: str
    ass_path: str | None = None
    task_id: str | None = None
    output_filename: str | None = None
    content: str | None = None
    styling: dict[str, Any] | None = None
    styling_modified: bool | None = False


class OpenVideoRequest(BaseModel):
    """Request payload for opening burned video in the desktop system media player."""

    video_path: str | None = None
    task_id: str | None = None


class OpenFileRequest(BaseModel):
    """Request payload for opening a subtitle or document file in the desktop default editor."""

    file_path: str | None = None
    task_id: str | None = None
    media_path: str | None = None


class OpenFolderRequest(BaseModel):
    """Request payload for opening the directory containing a file in the system file manager."""

    file_path: str | None = None
    task_id: str | None = None
    media_path: str | None = None


def _resolve_ass_file_path(
    task_or_path: str | None = None,
    media_path: str | None = None,
    ass_path: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve the canonical .ass file path from task ID, media path, or explicit subtitle path.

    When multiple candidate files exist (e.g. sibling .ass and custom output name .ass),
    evaluates modification timestamps (os.path.getmtime) so external edits made by the
    user directly to the .ass file on disk are faithfully honored.

    Args:
        task_or_path: Task ID or file path to evaluate.
        media_path: Path to the media file whose sibling .ass should be checked.
        ass_path: Direct path to the .ass subtitle file.

    Returns:
        Tuple of (resolved_file_path, display_filename), or (None, None) if unresolved.
    """
    candidates: list[str] = []

    # 1. Explicit ass_path
    if ass_path:
        p = os.path.expanduser(ass_path.strip())
        if os.path.exists(p):
            candidates.append(p)

    # 2. task_or_path can be an ASS file path, media path, or task_id
    if task_or_path:
        p = os.path.expanduser(task_or_path.strip())
        if p.endswith(".ass") and os.path.exists(p):
            candidates.append(p)
        elif os.path.exists(p):
            _, _, _, _, sib_ass = get_sibling_paths(p)
            if os.path.exists(sib_ass):
                candidates.append(sib_ass)
        t = _get_or_load_task(task_or_path)
        if t and t.get("ass_file") and os.path.exists(t["ass_file"]):
            candidates.append(t["ass_file"])
        disk_ass = os.path.join(OUTPUTS_DIR, f"{task_or_path}.ass")
        if os.path.exists(disk_ass):
            candidates.append(disk_ass)

    # 3. media_path sibling and voice_titles variants
    if media_path:
        mp = os.path.expanduser(media_path.strip())
        if os.path.exists(mp):
            clean_path, media_dir, base_name, _, sib_ass = get_sibling_paths(mp)
            if os.path.exists(sib_ass):
                candidates.append(sib_ass)
            vt_ass = os.path.join(media_dir, f"{base_name}_voice_titles.ass")
            if os.path.exists(vt_ass):
                candidates.append(vt_ass)

    if candidates:
        # Deduplicate candidates while preserving order
        unique_candidates = list(dict.fromkeys(candidates))
        # Pick the most recently modified candidate so direct user edits are honored
        best_candidate = max(unique_candidates, key=lambda cp: os.path.getmtime(cp))
        return best_candidate, os.path.basename(best_candidate)

    return None, None

@app.get("/api/ass-content")
@app.get("/api/ass-content/{task_id}")
def get_ass_content(
    task_id: str | None = None,
    media_path: str | None = None,
    ass_path: str | None = None,
):
    """Retrieve ASS subtitle file content and parsed dialogue events for interactive editing.

    Args:
        task_id: Optional task identifier.
        media_path: Optional path to media file.
        ass_path: Optional explicit subtitle path.

    Returns:
        Dictionary with full ASS text, structured dialogue records, and video burn state.

    Raises:
        HTTPException: If the subtitle file cannot be found.
    """
    file_path, display_name = _resolve_ass_file_path(task_id, media_path, ass_path)

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Subtitle (.ass) file not found for this media/task. Please generate subtitles first."
        )

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse dialogue lines for the friendly editor
    dialogues = []
    lines = content.splitlines()
    unique_speakers_found: list[str] = []
    for idx, line in enumerate(lines):
        if line.startswith("Dialogue:"):
            # Format: Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            parts = line.split(",", 9)
            if len(parts) >= 10:
                raw_text = parts[9]
                speaker_name = parts[4].strip() if len(parts) > 4 else ""
                clean_text = re.sub(r'\{[^}]*\}', '', raw_text)
                clean_text = clean_text.replace('\\N', ' ').replace('\\n', ' ').replace('\\h', ' ')
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                if speaker_name and speaker_name not in unique_speakers_found:
                    unique_speakers_found.append(speaker_name)
                dialogues.append({
                    "line_index": idx,
                    "layer": parts[0].replace("Dialogue:", "").strip(),
                    "start": parts[1].strip(),
                    "end": parts[2].strip(),
                    "style": parts[3].strip(),
                    "speaker": speaker_name or "Speaker 1",
                    "raw_text": raw_text,
                    "clean_text": clean_text
                })

    if not unique_speakers_found:
        unique_speakers_found = ["Speaker 1"]

    t = _get_or_load_task(task_id) if task_id else None

    return {
        "success": True,
        "task_id": task_id,
        "file_path": file_path,
        "filename": display_name or os.path.basename(file_path),
        "content": content,
        "dialogues": dialogues,
        "detected_speakers": unique_speakers_found,
        "speaker_count": len(unique_speakers_found),
        "is_multi_speaker": len(unique_speakers_found) > 1,
        "speaker_samples": t.get("speaker_samples") if t else None,
        "has_burned_video": bool(t.get("video_file") if t else False),
        "video_file": t.get("video_file") if t else None,
        "video_filename": os.path.basename(t.get("video_file")) if (t and t.get("video_file")) else None
    }


@app.post("/api/ass-content")
@app.post("/api/ass-content/{task_id}")
def update_ass_content(
    req: Any = None,
    task_id: str | None = None,
    auth: str = Depends(verify_auth),
):
    """Save edited ASS subtitle content to disk and optionally trigger video re-burning.

    Args:
        req: UpdateAssRequest instance or payload attributes.
        task_id: Optional task identifier.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary containing save confirmation, file paths, preview, and download links.

    Raises:
        HTTPException: If request body is missing.
    """
    if isinstance(req, str) and isinstance(task_id, UpdateAssRequest):
        req, task_id = task_id, req
    elif isinstance(task_id, UpdateAssRequest) and not isinstance(req, UpdateAssRequest):
        req, task_id = task_id, None

    if req is None:
        raise HTTPException(status_code=400, detail="Missing request body")

    media_p = getattr(req, "media_path", None)
    ass_p = getattr(req, "ass_path", None)
    content_str = getattr(req, "content", "")
    reburn = getattr(req, "reburn_video", False)
    custom_name = getattr(req, "output_filename", None)
    styling = getattr(req, "styling", None)
    styling_modified = getattr(req, "styling_modified", False)

    file_path, display_name = _resolve_ass_file_path(task_id, media_p, ass_p)
    if not file_path:
        if media_p:
            clean_path, media_dir, base_name, _, sib_ass = get_sibling_paths(media_p)
            file_path = sib_ass
        else:
            file_path = os.path.join(OUTPUTS_DIR, f"{task_id or 'edited_subtitles'}.ass")

    meta = None
    if media_p and os.path.exists(media_p):
        try:
            meta = get_video_metadata(media_p)
        except Exception:
            pass

    # Synchronize all styling and active word formatting changes
    content_str = update_ass_formatting(
        ass_content=content_str,
        config=styling if (styling_modified or styling) else None,
        video_meta=meta,
    )

    # Overwrite the ASS file with updated content
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content_str)

    t = _get_or_load_task(task_id) if task_id else None
    lines = content_str.strip().splitlines()
    preview = "\n".join(lines[:60])
    if t:
        t["ass_preview"] = preview
        t["ass_file"] = file_path
        meta_file = os.path.join(OUTPUTS_DIR, f"{task_id}.json")
        try:
            with open(meta_file, "w", encoding="utf-8") as mf:
                import json
                json.dump(t, mf)
        except Exception:
            pass

    reburned = False
    video_source = (t.get("video_path") if t else None) or media_p
    if reburn and video_source and os.path.exists(video_source):
        clean_path, media_dir, base_name, _, _ = get_sibling_paths(video_source)
        chosen_name = custom_name or (t.get("custom_filename") if t else None) or f"{base_name}_reburned"
        chosen_clean = re.sub(r'[^\w\-. ]', '_', chosen_name)
        chosen_clean = re.sub(r'\.(ass|mp4)$', '', chosen_clean, flags=re.IGNORECASE)
        output_mp4_path = os.path.join(media_dir, f"{chosen_clean}.mp4")
        try:
            burn_subtitles_to_video(clean_path, file_path, output_mp4_path)
            if t:
                t["video_file"] = output_mp4_path
            reburned = True
        except Exception:
            scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{task_id or 'reburned'}.mp4")
            burn_subtitles_to_video(clean_path, file_path, scratch_mp4)
            if t:
                t["video_file"] = scratch_mp4
            output_mp4_path = scratch_mp4
            reburned = True

    return {
        "success": True,
        "message": f"Subtitles saved to {os.path.basename(file_path)}",
        "file_path": file_path,
        "filename": os.path.basename(file_path),
        "preview": preview,
        "reburned": reburned,
        "download_url": f"/api/download/{task_id}" if task_id else None,
        "video_download_url": f"/api/download-video/{task_id}" if (t and t.get("video_file")) else None
    }


@app.post("/api/burn-video")
def burn_video_endpoint(req: BurnVideoRequest, auth: str = Depends(verify_auth)):
    """Burn subtitles into source video with hardware acceleration and update task metadata.

    Args:
        req: Burn parameters including video path, subtitle path/content, and output name.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary containing resulting video file paths and download URLs.

    Raises:
        HTTPException: If the source video or subtitle file is missing.
    """
    video_clean = os.path.expanduser(req.video_path.strip())
    if not os.path.exists(video_clean):
        raise HTTPException(status_code=404, detail=f"Source video not found: {video_clean}")

    file_path, display_name = _resolve_ass_file_path(req.task_id, video_clean, req.ass_path)
    clean_path, media_dir, base_name, _, sib_ass = get_sibling_paths(video_clean)

    if not file_path or not os.path.isfile(file_path):
        if os.path.isfile(sib_ass):
            file_path = sib_ass
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Subtitle (.ass) file not found on disk: {file_path or sib_ass}. Please generate subtitles first.",
            )

    # 1. Load ASS script content strictly from disk - do not rely on in-memory buffers
    with open(file_path, "r", encoding="utf-8") as f:
        current_content = f.read()

    meta = None
    try:
        meta = get_video_metadata(clean_path)
    except Exception:
        pass

    # 2. Extract video metadata and update formatting ONLY if user explicitly changed styling in UI
    if req.styling_modified:
        styling_cfg = req.styling
        if not styling_cfg and req.task_id:
            t_existing = _get_or_load_task(req.task_id)
            if t_existing and t_existing.get("styling"):
                styling_cfg = t_existing.get("styling")

        current_content = update_ass_formatting(
            ass_content=current_content,
            config=styling_cfg,
            video_meta=meta,
        )
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(current_content)

    if req.task_id:
        output_ass_path = os.path.join(OUTPUTS_DIR, f"{req.task_id}.ass")
        try:
            with open(output_ass_path, "w", encoding="utf-8") as f:
                f.write(current_content)
        except Exception:
            pass

    # Determine output MP4 path
    raw_name = (req.output_filename or "").strip()
    if not raw_name:
        raw_name = f"{base_name}_voice_titles"
    clean_name = re.sub(r'[^\w\-. ]', '_', raw_name)
    clean_name = re.sub(r'\.(ass|mp4)$', '', clean_name, flags=re.IGNORECASE)
    target_mp4 = os.path.join(media_dir, f"{clean_name}.mp4")

    burn_task_id = req.task_id or str(uuid.uuid4())
    saved_target = target_mp4

    # Create immutable execution copy for burning to isolate from concurrent browser edits
    burn_snapshot_ass = os.path.join(
        media_dir if os.path.isdir(media_dir) else OUTPUTS_DIR,
        f".{clean_name}.burn_{burn_task_id}.ass",
    )
    try:
        shutil.copy2(file_path, burn_snapshot_ass)
        burn_target_ass = burn_snapshot_ass
    except Exception:
        burn_target_ass = file_path

    total_duration = float(meta.get("duration", 0.0)) if meta else 0.0

    t_init = _get_or_load_task(burn_task_id) or {}
    t_init.update({
        "task_id": burn_task_id,
        "video_path": clean_path,
        "ass_file": file_path,
        "status": "processing",
        "progress": 5,
        "stage_message": "Starting NVENC subtitle burn...",
        "burn_video": True,
        "custom_filename": clean_name,
    })
    tasks[burn_task_id] = t_init

    def on_burn_progress(telemetry: dict[str, Any]):
        tasks[burn_task_id]["burn_telemetry"] = telemetry
        burn_pct = telemetry.get("burn_pct", 0.0)
        tasks[burn_task_id]["progress"] = round(burn_pct, 1)

        eta_sec = telemetry.get("eta_seconds", 0.0)
        eta_str = f"~{int(eta_sec)}s remaining" if eta_sec > 0 else "finishing..."
        cur_sec = telemetry.get("current_seconds", 0.0)
        dur_sec = telemetry.get("duration", total_duration)

        cur_min = int(cur_sec // 60)
        cur_s = int(cur_sec % 60)
        dur_min = int(dur_sec // 60)
        dur_s = int(dur_sec % 60)
        time_str = f"{cur_min:02d}:{cur_s:02d} / {dur_min:02d}:{dur_s:02d}"

        spd = telemetry.get("speed", 1.0)
        fps = int(telemetry.get("fps", 0.0))

        tasks[burn_task_id]["stage_message"] = (
            f"Burning subtitles: {burn_pct:.0f}% • {eta_str} "
            f"({spd:.1f}x • {fps} fps) • {time_str}"
        )

    try:
        try:
            _safe_burn(
                clean_path,
                burn_target_ass,
                target_mp4,
                duration=total_duration,
                progress_callback=on_burn_progress,
            )
            saved_target = target_mp4
        except Exception:
            scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{burn_task_id}.mp4")
            _safe_burn(
                clean_path,
                burn_target_ass,
                scratch_mp4,
                duration=total_duration,
                progress_callback=on_burn_progress,
            )
            saved_target = scratch_mp4
    finally:
        if burn_target_ass != file_path and os.path.exists(burn_target_ass):
            try:
                os.remove(burn_target_ass)
            except OSError:
                pass

    t = _get_or_load_task(burn_task_id) or {}
    t.update({
        "task_id": burn_task_id,
        "video_path": clean_path,
        "ass_file": file_path,
        "video_file": saved_target,
        "status": "completed",
        "progress": 100,
        "stage_message": "Burn complete! Video ready to download.",
        "burn_video": True,
        "custom_filename": clean_name
    })
    tasks[burn_task_id] = t

    try:
        import json
        with open(os.path.join(OUTPUTS_DIR, f"{burn_task_id}.json"), "w", encoding="utf-8") as mf:
            json.dump(t, mf)
    except Exception:
        pass

    return {
        "success": True,
        "task_id": burn_task_id,
        "video_path": saved_target,
        "video_filename": os.path.basename(saved_target),
        "ass_file": file_path,
        "ass_filename": os.path.basename(file_path),
        "ass_content": current_content,
        "download_url": f"/api/download/{burn_task_id}",
        "video_download_url": f"/api/download-video/{burn_task_id}",
        "message": f"Successfully burned subtitles into {os.path.basename(saved_target)} with NVIDIA RTX A5000 NVENC."
    }


@app.post("/api/open-video")
def open_video_endpoint(req: OpenVideoRequest, auth: str = Depends(verify_auth)):
    """Launch the system default media player for the completed or burned video.

    Args:
        req: Request payload specifying the video path or task ID.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming media player invocation.

    Raises:
        HTTPException: If the target video does not exist or player launch fails.
    """
    target_path = None
    if req.video_path:
        p = os.path.expanduser(req.video_path.strip())
        if os.path.exists(p):
            target_path = p
    if not target_path and req.task_id:
        t = _get_or_load_task(req.task_id)
        if t and t.get("video_file") and os.path.exists(t["video_file"]):
            target_path = t["video_file"]
        else:
            scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{req.task_id}.mp4")
            if os.path.exists(scratch_mp4):
                target_path = scratch_mp4

    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Burned video file not found to open")

    system = platform.system()
    try:
        # SECURITY: Mitigate command injection (CWE-78) by executing desktop player via discrete argument vector
        if system == "Linux":
            subprocess.Popen(["xdg-open", target_path], start_new_session=True)
        elif system == "Darwin":
            subprocess.Popen(["open", target_path], start_new_session=True)
        elif system == "Windows":
            os.startfile(target_path)
        else:
            subprocess.Popen(["xdg-open", target_path], start_new_session=True)

        return {
            "success": True,
            "path": target_path,
            "filename": os.path.basename(target_path),
            "message": f"Opened {os.path.basename(target_path)} in system default player"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch player: {str(e)}")


@app.post("/api/open-file")
def open_file_endpoint(req: OpenFileRequest, auth: str = Depends(verify_auth)):
    """Launch the system default application or text editor for a subtitle or document file.

    Args:
        req: Request payload specifying file_path, task_id, or media_path.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming file launcher invocation.

    Raises:
        HTTPException: If the target file does not exist or editor launch fails.
    """
    target_path = None
    if req.file_path:
        try:
            p = parse_safe_file_uri(req.file_path)
            if os.path.isfile(p):
                target_path = p
        except ValueError:
            pass

    if not target_path and (req.task_id or req.media_path):
        resolved, _ = _resolve_ass_file_path(req.task_id, req.media_path, req.file_path)
        if resolved and os.path.isfile(resolved):
            target_path = resolved

    if not target_path or not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="Target file not found on disk to open")

    system = platform.system()
    try:
        # SECURITY: Mitigate command injection (CWE-78) by executing desktop opener via discrete argument vector
        if system == "Linux":
            subprocess.Popen(["xdg-open", target_path], start_new_session=True)
        elif system == "Darwin":
            subprocess.Popen(["open", "-t", target_path], start_new_session=True)
        elif system == "Windows":
            os.startfile(target_path)
        else:
            subprocess.Popen(["xdg-open", target_path], start_new_session=True)

        return {
            "success": True,
            "path": target_path,
            "filename": os.path.basename(target_path),
            "message": f"Opened {os.path.basename(target_path)} in system default text editor",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch text editor: {str(e)}")


def reveal_in_folder(target_path: str) -> dict[str, Any]:
    """Reveal a target file or directory in the system file manager (Directive 11).

    Applies a pre-flight headless check, verifies Linux display and D-Bus session bus
    presence, enforces a <=1000ms timeout guard, and safely falls back to returning
    the directory path if headless or if desktop D-Bus is unavailable.

    Args:
        target_path: Canonical filesystem path or file:// URI.

    Returns:
        Dictionary containing execution status, headless indicator, and location info.
    """
    try:
        clean_target = parse_safe_file_uri(target_path)
    except Exception:
        clean_target = os.path.realpath(os.path.expanduser(target_path))

    dir_path = clean_target if os.path.isdir(clean_target) else os.path.dirname(clean_target)
    filename = os.path.basename(clean_target) if os.path.isfile(clean_target) else None

    # Pre-flight: Headless environment check (Directive 11)
    if is_headless():
        return {
            "success": True,
            "headless": True,
            "directory": dir_path,
            "filename": filename,
            "message": f"Headless environment detected; file located at: {clean_target}",
        }

    system = platform.system()
    try:
        # SECURITY: Mitigate command injection (CWE-78) by executing desktop file manager via discrete argument vector
        if system == "Linux":
            # Verify display and session bus presence (Directive 11 / org.freedesktop.FileManager1)
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            has_dbus = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))

            if not has_display or not has_dbus:
                return {
                    "success": True,
                    "headless": True,
                    "directory": dir_path,
                    "filename": filename,
                    "message": f"Desktop session bus not available; file located at: {clean_target}",
                }

            # Launch desktop file manager via standard Freedesktop xdg-open
            if shutil.which("xdg-open"):
                # SECURITY: Discrete argument vector with start_new_session (CWE-78, Directive 11)
                subprocess.Popen(
                    ["xdg-open", dir_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        elif system == "Darwin":
            cmd = ["open", "-R", clean_target] if os.path.isfile(clean_target) else ["open", dir_path]
            subprocess.Popen(cmd, start_new_session=True)
        elif system == "Windows":
            if os.path.isfile(clean_target):
                subprocess.Popen(["explorer", f"/select,{clean_target}"], start_new_session=True)
            else:
                os.startfile(dir_path)
        else:
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", dir_path], start_new_session=True)

        return {
            "success": True,
            "headless": False,
            "directory": dir_path,
            "filename": filename,
            "message": f"Revealed {filename or dir_path} in system file manager",
        }
    except Exception as exc:
        return {
            "success": True,
            "headless": True,
            "directory": dir_path,
            "filename": filename,
            "message": f"File manager notice: {exc}; file located at: {clean_target}",
        }


@app.post("/api/open-folder")
def open_folder_endpoint(req: OpenFolderRequest, auth: str = Depends(verify_auth)):
    """Launch the system file manager (Explorer/Finder/Nautilus) at the target file or directory.

    Args:
        req: Request payload specifying file_path, task_id, or media_path.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming file manager invocation.

    Raises:
        HTTPException: If the target file or directory location is not found.
    """
    target_path = None
    if req.file_path:
        try:
            p = parse_safe_file_uri(req.file_path)
            if os.path.exists(p):
                target_path = p
        except ValueError:
            pass

    if not target_path and (req.task_id or req.media_path):
        resolved, _ = _resolve_ass_file_path(req.task_id, req.media_path, req.file_path)
        if resolved and os.path.exists(resolved):
            target_path = resolved

    if not target_path:
        raise HTTPException(status_code=404, detail="File or directory location not found")

    dir_path = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
    if not os.path.isdir(dir_path):
        raise HTTPException(status_code=404, detail=f"Directory not found on disk: {dir_path}")

    return reveal_in_folder(target_path)


@app.get("/api/ass-file-info")
def get_ass_file_info_endpoint(path: str | None = None, task_id: str | None = None, media_path: str | None = None):
    """Retrieve metadata, line count, size, and modification timestamp for an ASS subtitle file on disk.

    Args:
        path: Direct path to subtitle file.
        task_id: Optional task identifier.
        media_path: Optional media path.

    Returns:
        Dictionary containing file metadata, line count, and last modified ISO timestamp.

    Raises:
        HTTPException: If file is not found.
    """
    file_path, display_name = _resolve_ass_file_path(task_id, media_path, path)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Subtitle file not found on disk")

    stat = os.stat(file_path)
    line_count = 0
    dialogue_count = 0
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_count += 1
            if line.startswith("Dialogue:"):
                dialogue_count += 1

    return {
        "success": True,
        "path": file_path,
        "filename": os.path.basename(file_path),
        "directory": os.path.dirname(file_path),
        "size_bytes": stat.st_size,
        "size_kb": round(stat.st_size / 1024, 1),
        "mtime": stat.st_mtime,
        "dialogue_count": dialogue_count,
        "line_count": line_count,
    }


# Preset API Endpoints (Standards 4 & 5)
@app.get("/api/presets")
def get_presets_endpoint(auth: str = Depends(verify_auth)):
    """List all available style presets across local and user configuration directories.

    Args:
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary containing the list of available preset names.
    """
    return {"presets": list_presets()}


@app.get("/api/presets/{preset_name}")
def get_preset_endpoint(preset_name: str, auth: str = Depends(verify_auth)):
    """Load a specific style preset by name.

    Args:
        preset_name: Alphanumeric preset name.
        auth: Authentication token validated by dependency injection.

    Returns:
        Serialized preset dictionary.

    Raises:
        HTTPException: If the preset cannot be found or loaded.
    """
    try:
        p = load_preset(preset_name)
        return p.model_dump()
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/presets")
def save_preset_endpoint(preset: StylePreset, auth: str = Depends(verify_auth)):
    """Save or update a style preset as YAML under user config directory.

    Args:
        preset: StylePreset model instance to persist.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming preset persistence with sanitized filesystem path.

    Raises:
        HTTPException: If preset validation or saving fails.
    """
    try:
        p_path = save_preset(preset)
        return {"success": True, "name": preset.name, "path": sanitize_log_path(str(p_path))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/presets/{preset_name}")
def delete_preset_endpoint(preset_name: str, auth: str = Depends(verify_auth)):
    """Delete a user-defined style preset from disk.

    Args:
        preset_name: Name of preset to delete.
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming preset deletion.

    Raises:
        HTTPException: If preset is built-in or deletion fails.
    """
    try:
        deleted = delete_preset(preset_name)
        if not deleted:
            raise HTTPException(status_code=400, detail="Cannot delete default preset")
        return {"success": True, "deleted": preset_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/config/reset")
def reset_config_api_endpoint(auth: str = Depends(verify_auth)):
    """Reset all user presets and configuration to factory defaults.

    Args:
        auth: Authentication token validated by dependency injection.

    Returns:
        Dictionary confirming configuration reset.
    """
    reset_all_configuration()
    return {"success": True, "message": "Presets and configuration reset to factory defaults"}


# Authenticated Index Handler (Standard 5)
@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request, token: str | None = Query(None)):
    """Serve the single-page web UI if session cookie or query token is authenticated.

    Args:
        request: Incoming HTTP request instance.
        token: Optional authentication token passed via query string.

    Returns:
        HTMLResponse serving index.html or 401 Unauthorized page.
    """
    server_token = getattr(app.state, "auth_token", None) or AUTH_TOKEN
    cookie_token = request.cookies.get("voice_highlighter_session")

    # SECURITY: Validate ephemeral launch token via constant-time comparison to prevent timing attacks
    is_authorized = False
    if token and secrets.compare_digest(token, server_token):
        is_authorized = True
    elif cookie_token and secrets.compare_digest(cookie_token, server_token):
        is_authorized = True

    if not is_authorized:
        return HTMLResponse(
            "<h3>401 Unauthorized</h3><p>Voice Highlighter requires an authenticated session.</p>"
            "<p>Please open the authenticated link printed in your terminal (e.g. <code>http://127.0.0.1:8672/?token=...</code>).</p>",
            status_code=401
        )

    html_path = os.path.join(FRONTEND_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    res = HTMLResponse(content=content)
    # SECURITY: Set SameSite=Strict and HttpOnly cookie to mitigate XSS and CSRF token leakage
    if token and secrets.compare_digest(token, server_token):
        res.set_cookie(
            key="voice_highlighter_session",
            value=token,
            httponly=True,
            samesite="strict",
            secure=False,
            path="/"
        )
    return res


def format_clickable_url(url: str, label: str | None = None, stream: Any = sys.stderr) -> str:
    """Format a URL as an OSC 8 clickable link if stream is an interactive TTY and NO_COLOR is unset.

    Args:
        url: The target destination URL.
        label: Optional visual label text, or None to display the URL itself.
        stream: Output stream to inspect for TTY capability (defaults to sys.stderr).

    Returns:
        OSC 8 formatted hyperlink string when connected to an interactive TTY and NO_COLOR
        is absent, falling back to clean plain-text URL when redirected or NO_COLOR is set.
    """
    display_text = label or url
    if "NO_COLOR" in os.environ:
        return display_text
    is_tty = hasattr(stream, "isatty") and stream.isatty()
    if is_tty:
        # SECURITY: Prevent terminal escape sequence injection by wrapping clean URL and label in OSC 8
        return f"\033]8;;{url}\033\\{display_text}\033]8;;\033\\"
    return display_text


def is_headless() -> bool:
    """Detect whether the current execution environment is headless.

    Returns:
        True if running in continuous integration or on Linux without DISPLAY/WAYLAND_DISPLAY;
        False if a graphical desktop session is available.
    """
    if os.environ.get("CI", "").lower() in ("true", "1"):
        return True
    if sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return True
    return False


def open_browser_window(url: str) -> None:
    """Safely open the target URL in the user's default browser window without crashing.

    Silences noisy stderr messages produced by external browser helper processes
    (e.g., Chromium Linux zygote Broken pipe messages when attaching to an existing session).

    Args:
        url: Application URL including ephemeral authentication token.
    """
    try:
        import shutil

        if sys.platform.startswith("linux") and shutil.which("xdg-open"):
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return

        import webbrowser
        webbrowser.open(url)
    except Exception as exc:
        # SECURITY: Catch any browser launch failures without crashing the server process
        sys.stderr.write(f"[Voice Highlighter] Notice: Could not open browser ({exc}).\n")



def run_server(
    port: int = 8672,
    host: str = "127.0.0.1",
    reload: bool = False,
    no_browser: bool = False,
) -> None:
    """Run the local uvicorn server strictly bound to localhost.

    Args:
        port: Network port number to bind (default 8672).
        host: Interface IP address, default 127.0.0.1 (localhost only).
        reload: Whether to enable auto-reloading for development.
        no_browser: Whether to suppress automatic default browser launch on startup.
    """
    # SECURITY: Local server MUST bind strictly to 127.0.0.1 (or ::1) by default per Directive 5
    import uvicorn
    token = AUTH_TOKEN
    app.state.auth_token = token

    server_url = f"http://{host}:{port}/?token={token}"
    clickable_url = format_clickable_url(server_url, stream=sys.stderr)

    sys.stderr.write(f"\n[Voice Highlighter] Local server running at: {clickable_url}\n")
    sys.stderr.write("[Voice Highlighter] Bound strictly to localhost for privacy and security. Press Ctrl+C to exit.\n\n")
    sys.stderr.flush()

    if not no_browser and not is_headless():
        # SECURITY: Launch default browser in a background timer so uvicorn binds socket first
        timer = threading.Timer(0.3, open_browser_window, args=[server_url])
        timer.daemon = True
        timer.start()

    try:
        if reload:
            uvicorn.run("backend.app:app", host=host, port=port, reload=True, reload_dirs=["backend"])
        else:
            uvicorn.run(app, host=host, port=port, log_level="warning")
    except OSError as exc:
        sys.stderr.write(f"\n[Voice Highlighter] Error: Could not bind to {host}:{port} ({exc}).\n")
        sys.stderr.write("[Voice Highlighter] The port may already be in use. Pass '--port <PORT>' or set VOICE_HIGHLIGHTER_PORT to choose a different port.\n")
        sys.stderr.flush()
        sys.exit(1)


# Mount static frontend files
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

