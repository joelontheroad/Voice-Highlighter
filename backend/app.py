import os
import sys
import uuid
import threading
import hashlib
import re
import subprocess
import platform
import asyncio
import json
import warnings
from typing import Dict, Any, Optional

# Suppress spurious multiprocessing resource_tracker cleanup warnings on shutdown
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.extractor import (
    get_video_metadata,
    extract_poster_frame,
    extract_audio,
    burn_subtitles_to_video,
    get_best_h264_encoder,
    test_ffmpeg_encoder,
)
from backend.transcriber import run_whisperx_pipeline
from backend.ass_generator import generate_ass_content

app = FastAPI(title="Voice Highlighter API")

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.endswith((".css", ".js", ".html")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Workspace and scratch paths
WORKSPACE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
SCRATCH_DIR = os.path.join(WORKSPACE_DIR, "scratch")
FRAMES_DIR = os.path.join(SCRATCH_DIR, "frames")
OUTPUTS_DIR = os.path.join(SCRATCH_DIR, "outputs")
AUDIO_DIR = os.path.join(SCRATCH_DIR, "audio")

os.makedirs(FRAMES_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# In-memory task store
tasks: Dict[str, Dict[str, Any]] = {}

def get_sibling_paths(media_path: str):
    clean_path = os.path.expanduser(media_path.strip())
    media_dir = os.path.dirname(os.path.abspath(clean_path))
    base_name = os.path.splitext(os.path.basename(clean_path))[0]
    wav_path = os.path.join(media_dir, f"{base_name}.wav")
    ass_path = os.path.join(media_dir, f"{base_name}.ass")
    return clean_path, media_dir, base_name, wav_path, ass_path

class VideoInfoRequest(BaseModel):
    video_path: str

class TranscribeRequest(BaseModel):
    video_path: str
    model_name: Optional[str] = "large-v3"
    styling: Dict[str, Any]
    burn_video: Optional[bool] = False
    output_filename: Optional[str] = None
    reuse_existing_ass: Optional[bool] = True
    reuse_existing_wav: Optional[bool] = True

class PreviewAssRequest(BaseModel):
    sample_text: str
    styling: Dict[str, Any]
    video_meta: Optional[Dict[str, Any]] = None

class OpenFileDialogRequest(BaseModel):
    initial_path: Optional[str] = None
    title: Optional[str] = "Select Video File"
    timeout_ms: Optional[int] = None

@app.post("/api/open-os-file-dialog")
async def open_os_file_dialog(req: OpenFileDialogRequest):
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
    """Detects and formats the CPU processor model name (e.g., 'Intel Core i7-11850H')."""
    model = ""
    try:
        with open("/proc/cpuinfo") as f:
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
    """Performs a live probe to verify if GPU NVENC video rendering is active."""
    return test_ffmpeg_encoder("h264_nvenc")

def get_gpu_diagnostic() -> Optional[str]:
    """Detects if an NVIDIA GPU is physically present but unavailable due to driver/power state."""
    try:
        res = subprocess.run(["nvidia-smi", "-q", "-d", "POWER"], capture_output=True, text=True, timeout=2)
        if "GPU requires reset" in res.stdout:
            return "NVIDIA GPU requires system/driver reset (currently falling back to CPU)"
    except Exception:
        pass
    return None

@app.get("/api/system-info")
def get_system_info():
    """
    Returns detected hardware execution environment:
    - Real-time probe of whether GPU or CPU is actively rendering
    - Actual GPU hardware name if active, or CPU processor model name if CPU
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
        "gpu_diagnostic": gpu_diagnostic
    }

@app.get("/api/browse-files")
def browse_filesystem(dir: Optional[str] = None):
    default_candidates = [
        os.path.expanduser("~/Videos"),
        os.path.expanduser("~/Movies"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~"),
        WORKSPACE_DIR
    ]
    
    target_dir = None
    if dir and dir.strip():
        p = os.path.expanduser(dir.strip())
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

        # Check for existing sibling WAV and ASS in same directory
        is_direct_wav = clean_path.lower().endswith(".wav")
        has_wav = is_direct_wav or os.path.exists(sibling_wav)
        actual_wav_path = clean_path if is_direct_wav else (sibling_wav if os.path.exists(sibling_wav) else None)
        has_ass = os.path.exists(sibling_ass)
        ass_preview = None
        ass_dialogue_count = 0

        if has_ass:
            try:
                with open(sibling_ass, "r", encoding="utf-8") as af:
                    ass_raw = af.read()
                    ass_lines = ass_raw.splitlines()
                    ass_preview = "\n".join(ass_lines[:60])
                    ass_dialogue_count = sum(1 for l in ass_lines if l.startswith("Dialogue:"))
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
            "has_existing_wav": bool(has_wav),
            "existing_wav_path": actual_wav_path,
            "existing_wav_name": os.path.basename(actual_wav_path) if actual_wav_path else None,
            "has_existing_ass": bool(has_ass),
            "existing_ass_path": sibling_ass if has_ass else None,
            "existing_ass_name": os.path.basename(sibling_ass) if has_ass else None,
            "existing_ass_preview": ass_preview,
            "existing_ass_dialogues": ass_dialogue_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/frame/{frame_name}", methods=["GET", "HEAD"])
def serve_frame(frame_name: str):
    frame_path = os.path.join(FRAMES_DIR, frame_name)
    if not os.path.exists(frame_path):
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(frame_path, media_type="image/jpeg")

def process_transcription_job(
    task_id: str,
    video_path: str,
    model_name: str,
    styling: Dict[str, Any],
    burn_video: bool = False,
    output_filename: Optional[str] = None,
    reuse_existing_ass: bool = True,
    reuse_existing_wav: bool = True
):
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
            if is_direct_wav:
                wav_path = clean_path
                update_progress("Using source WAV audio directly...", 15)
            elif reuse_existing_wav and os.path.exists(sibling_wav):
                wav_path = sibling_wav
                update_progress(f"Reusing existing audio: {os.path.basename(sibling_wav)}...", 15)
            else:
                update_progress("Extracting audio to source directory (ffmpeg)...", 10)
                wav_path = sibling_wav
                try:
                    extract_audio(clean_path, wav_path)
                except Exception:
                    # Fallback to scratch audio dir if source dir is not writable
                    wav_path = os.path.join(AUDIO_DIR, f"{task_id}.wav")
                    extract_audio(clean_path, wav_path)

            update_progress("Initializing WhisperX on NVIDIA RTX A5000 GPU...", 20)
            whisper_result = run_whisperx_pipeline(
                audio_wav_path=wav_path,
                model_name=model_name,
                progress_callback=update_progress
            )

            update_progress("Formatting word-highlighted ASS subtitles...", 88)
            ass_content = generate_ass_content(
                whisper_result=whisper_result,
                config=styling,
                video_meta=meta
            )

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

        if burn_video:
            update_progress("Burning subtitles into video with GPU acceleration (RTX A5000 NVENC)...", 94)
            target_mp4 = os.path.join(media_dir, f"{clean_name}.mp4")
            try:
                burn_subtitles_to_video(clean_path, effective_ass, target_mp4)
                tasks[task_id]["video_file"] = target_mp4
            except Exception:
                scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{task_id}.mp4")
                burn_subtitles_to_video(clean_path, effective_ass, scratch_mp4)
                tasks[task_id]["video_file"] = scratch_mp4

        tasks[task_id]["status"] = "completed"
        tasks[task_id]["progress"] = 100
        tasks[task_id]["stage_message"] = "Processing complete! Deliverables ready."

        # Save metadata to disk so server reloads do not lose download references
        try:
            import json
            meta_file = os.path.join(OUTPUTS_DIR, f"{task_id}.json")
            with open(meta_file, "w") as mf:
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
def start_transcribe(req: TranscribeRequest):
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
        "custom_filename": req.output_filename
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
            bool(req.reuse_existing_ass if req.reuse_existing_ass is not None else True),
            bool(req.reuse_existing_wav if req.reuse_existing_wav is not None else True)
        ),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id}

def _get_or_load_task(task_id: str) -> Optional[Dict[str, Any]]:
    if task_id in tasks:
        return tasks[task_id]
    import json
    meta_path = os.path.join(OUTPUTS_DIR, f"{task_id}.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as mf:
                data = json.load(mf)
                tasks[task_id] = data
                return data
        except Exception:
            pass
    return None

@app.get("/api/status/{task_id}")
def get_task_status(task_id: str):
    t = _get_or_load_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    
    is_completed = (t["status"] == "completed")
    burn_enabled = t.get("burn_video", False)
    has_video = bool(t.get("video_file"))

    return {
        "task_id": task_id,
        "status": t["status"],
        "progress": t["progress"],
        "stage_message": t["stage_message"],
        "error": t.get("error"),
        "ass_preview": t.get("ass_preview"),
        "burn_video": burn_enabled,
        "custom_filename": t.get("custom_filename"),
        "video_file": t.get("video_file"),
        "video_filename": os.path.basename(t.get("video_file")) if t.get("video_file") else None,
        "download_url": f"/api/download/{task_id}" if is_completed else None,
        "video_download_url": f"/api/download-video/{task_id}" if (is_completed and burn_enabled and has_video) else None
    }

@app.get("/api/download/{task_id}")
def download_ass(task_id: str):
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
        filename=filename
    )

@app.get("/api/download-video/{task_id}")
def download_video(task_id: str):
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
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=filename
    )

@app.post("/api/preview-ass")
def preview_ass_code(req: PreviewAssRequest):
    words_list = []
    current_time = 1.0
    for w in req.sample_text.split():
        words_list.append({
            "word": w,
            "start": round(current_time, 2),
            "end": round(current_time + 0.35, 2)
        })
        current_time += 0.40

    mock_whisper = {
        "segments": [{
            "text": req.sample_text,
            "start": 1.0,
            "end": current_time,
            "words": words_list
        }]
    }

    ass_text = generate_ass_content(
        whisper_result=mock_whisper,
        config=req.styling,
        video_meta=req.video_meta
    )
    return {"ass_content": ass_text}

class UpdateAssRequest(BaseModel):
    content: str
    reburn_video: Optional[bool] = False
    media_path: Optional[str] = None
    ass_path: Optional[str] = None
    output_filename: Optional[str] = None

class BurnVideoRequest(BaseModel):
    video_path: str
    ass_path: Optional[str] = None
    task_id: Optional[str] = None
    output_filename: Optional[str] = None
    content: Optional[str] = None

class OpenVideoRequest(BaseModel):
    video_path: Optional[str] = None
    task_id: Optional[str] = None

def _resolve_ass_file_path(
    task_or_path: Optional[str] = None,
    media_path: Optional[str] = None,
    ass_path: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolves the actual .ass file path from task ID, media path, or explicit ass_path.
    Returns (resolved_file_path, display_filename).
    """
    # 1. Explicit ass_path
    if ass_path:
        p = os.path.expanduser(ass_path.strip())
        if os.path.exists(p):
            return p, os.path.basename(p)

    # 2. task_or_path can be an ASS file path, media path, or task_id
    if task_or_path:
        p = os.path.expanduser(task_or_path.strip())
        if p.endswith(".ass") and os.path.exists(p):
            return p, os.path.basename(p)
        if os.path.exists(p):
            # Treat as media path: find sibling .ass
            _, _, _, _, sib_ass = get_sibling_paths(p)
            if os.path.exists(sib_ass):
                return sib_ass, os.path.basename(sib_ass)
        # Check task in memory or on disk
        t = _get_or_load_task(task_or_path)
        if t and t.get("ass_file") and os.path.exists(t["ass_file"]):
            custom = t.get("custom_filename")
            return t["ass_file"], f"{custom}.ass" if custom else os.path.basename(t["ass_file"])
        disk_ass = os.path.join(OUTPUTS_DIR, f"{task_or_path}.ass")
        if os.path.exists(disk_ass):
            return disk_ass, f"{task_or_path}.ass"

    # 3. media_path fallback
    if media_path:
        mp = os.path.expanduser(media_path.strip())
        if os.path.exists(mp):
            _, _, _, _, sib_ass = get_sibling_paths(mp)
            if os.path.exists(sib_ass):
                return sib_ass, os.path.basename(sib_ass)

    return None, None

@app.get("/api/ass-content")
@app.get("/api/ass-content/{task_id}")
def get_ass_content(
    task_id: Optional[str] = None,
    media_path: Optional[str] = None,
    ass_path: Optional[str] = None
):
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
    for idx, line in enumerate(lines):
        if line.startswith("Dialogue:"):
            # Format: Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            parts = line.split(",", 9)
            if len(parts) >= 10:
                raw_text = parts[9]
                clean_text = re.sub(r'\{[^}]*\}', '', raw_text)
                clean_text = clean_text.replace('\\N', ' ').replace('\\n', ' ').replace('\\h', ' ')
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                dialogues.append({
                    "line_index": idx,
                    "layer": parts[0].replace("Dialogue:", "").strip(),
                    "start": parts[1].strip(),
                    "end": parts[2].strip(),
                    "style": parts[3].strip(),
                    "raw_text": raw_text,
                    "clean_text": clean_text
                })

    t = _get_or_load_task(task_id) if task_id else None

    return {
        "success": True,
        "task_id": task_id,
        "file_path": file_path,
        "filename": display_name or os.path.basename(file_path),
        "content": content,
        "dialogues": dialogues,
        "has_burned_video": bool(t.get("video_file") if t else False)
    }

@app.post("/api/ass-content")
@app.post("/api/ass-content/{task_id}")
def update_ass_content(
    req: Any = None,
    task_id: Optional[str] = None
):
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

    file_path, display_name = _resolve_ass_file_path(task_id, media_p, ass_p)
    if not file_path:
        if media_p:
            clean_path, media_dir, base_name, _, sib_ass = get_sibling_paths(media_p)
            file_path = sib_ass
        else:
            file_path = os.path.join(OUTPUTS_DIR, f"{task_id or 'edited_subtitles'}.ass")

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
def burn_video_endpoint(req: BurnVideoRequest):
    video_clean = os.path.expanduser(req.video_path.strip())
    if not os.path.exists(video_clean):
        raise HTTPException(status_code=404, detail=f"Source video not found: {video_clean}")

    file_path, display_name = _resolve_ass_file_path(req.task_id, video_clean, req.ass_path)
    clean_path, media_dir, base_name, _, sib_ass = get_sibling_paths(video_clean)

    if not file_path or not os.path.exists(file_path):
        if os.path.exists(sib_ass):
            file_path = sib_ass
        elif req.content is not None and req.content.strip():
            file_path = sib_ass
        else:
            raise HTTPException(
                status_code=404,
                detail="Subtitle (.ass) file not found to burn. Please generate subtitles first."
            )

    # If updated content is provided from the inline editor, save it first
    if req.content is not None and req.content.strip():
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(req.content)

    # Determine output MP4 path
    raw_name = (req.output_filename or "").strip()
    if not raw_name:
        raw_name = f"{base_name}_voice_titles"
    clean_name = re.sub(r'[^\w\-. ]', '_', raw_name)
    clean_name = re.sub(r'\.(ass|mp4)$', '', clean_name, flags=re.IGNORECASE)
    target_mp4 = os.path.join(media_dir, f"{clean_name}.mp4")

    burn_task_id = req.task_id or str(uuid.uuid4())
    saved_target = target_mp4

    try:
        burn_subtitles_to_video(clean_path, file_path, target_mp4)
    except Exception:
        scratch_mp4 = os.path.join(OUTPUTS_DIR, f"{burn_task_id}.mp4")
        burn_subtitles_to_video(clean_path, file_path, scratch_mp4)
        saved_target = scratch_mp4

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
        "download_url": f"/api/download/{burn_task_id}",
        "video_download_url": f"/api/download-video/{burn_task_id}",
        "message": f"Successfully burned subtitles into {os.path.basename(saved_target)} with NVIDIA RTX A5000 NVENC."
    }

@app.post("/api/open-video")
def open_video_endpoint(req: OpenVideoRequest):
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

# Mount static frontend files
FRONTEND_DIR = os.path.join(WORKSPACE_DIR, "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
