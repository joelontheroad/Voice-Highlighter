# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Multimedia extraction and subtitle burning pipeline.

Manages external FFmpeg/FFprobe binary discovery, hardware-accelerated H.264
encoder selection (Apple VideoToolbox, NVIDIA NVENC, Intel QSV, AMD AMF, CPU),
waveform extraction for speech alignment, poster frame generation, and ASS
subtitle filter burning.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

# Cache for tested encoders
_ENCODER_CACHE: dict[str, bool] = {}


def get_ffmpeg_binary() -> str:
    """Find the available FFmpeg executable binary.

    Searches across system PATH, active virtual environment bin directory,
    and portable local project bin directory.

    Returns:
        Path to the resolved FFmpeg binary executable or 'ffmpeg' fallback.
    """
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg
    # Check active .venv/bin directory
    venv_bin = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            ".venv",
            "bin",
            "ffmpeg" + (".exe" if sys.platform == "win32" else ""),
        )
    )
    if os.path.isfile(venv_bin) and (sys.platform == "win32" or os.access(venv_bin, os.X_OK)):
        return venv_bin
    # Check local project bin directory (where portable static ffmpeg is unpacked)
    project_bin = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "bin",
            "ffmpeg" + (".exe" if sys.platform == "win32" else ""),
        )
    )
    if os.path.isfile(project_bin) and (sys.platform == "win32" or os.access(project_bin, os.X_OK)):
        return project_bin
    return "ffmpeg"


def get_ffprobe_binary() -> str:
    """Find the available FFprobe executable binary.

    Searches across system PATH, active virtual environment bin directory,
    and portable local project bin directory.

    Returns:
        Path to the resolved FFprobe binary executable or 'ffprobe' fallback.
    """
    which_ffprobe = shutil.which("ffprobe")
    if which_ffprobe:
        return which_ffprobe
    # Check active .venv/bin directory
    venv_bin = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            ".venv",
            "bin",
            "ffprobe" + (".exe" if sys.platform == "win32" else ""),
        )
    )
    if os.path.isfile(venv_bin) and (sys.platform == "win32" or os.access(venv_bin, os.X_OK)):
        return venv_bin
    # Check local project bin directory
    project_bin = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "bin",
            "ffprobe" + (".exe" if sys.platform == "win32" else ""),
        )
    )
    if os.path.isfile(project_bin) and (sys.platform == "win32" or os.access(project_bin, os.X_OK)):
        return project_bin
    return "ffprobe"


def test_ffmpeg_encoder(encoder_name: str) -> bool:
    """Test whether a specific FFmpeg video encoder is available and operational.

    Executes a minimal null-render subprocess to verify hardware and driver
    support, caching test results in memory.

    Args:
        encoder_name: FFmpeg encoder codec name (e.g. 'h264_nvenc', 'libx264').

    Returns:
        True if the encoder completed successfully; False otherwise.
    """
    if encoder_name in _ENCODER_CACHE:
        return _ENCODER_CACHE[encoder_name]

    ffmpeg = get_ffmpeg_binary()
    try:
        # Use 256x256 test frame to comply with hardware encoder minimum dimension limits
        # SECURITY: Mitigate command injection (CWE-78) by executing binaries via discrete argument vectors
        cmd = [ffmpeg, "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.04", "-c:v", encoder_name, "-f", "null", "-"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        working = res.returncode == 0
        _ENCODER_CACHE[encoder_name] = working
        return working
    except Exception:
        _ENCODER_CACHE[encoder_name] = False
        return False


def get_best_h264_encoder() -> tuple[str, list[str], str]:
    """Select the highest-performing available H.264 video encoder.

    Evaluates hardware acceleration options in order of performance:
    Apple VideoToolbox (macOS), NVIDIA NVENC, Intel Quick Sync (QSV),
    AMD AMF, and universal CPU libx264.

    Returns:
        A tuple of (encoder_name, encoder_flags, friendly_label).
    """
    if sys.platform == "darwin" and test_ffmpeg_encoder("h264_videotoolbox"):
        return "h264_videotoolbox", ["-b:v", "6000k"], "Apple VideoToolbox (Hardware)"

    if test_ffmpeg_encoder("h264_nvenc"):
        return "h264_nvenc", ["-preset", "p4", "-cq", "22"], "NVIDIA NVENC (GPU)"

    if test_ffmpeg_encoder("h264_qsv"):
        return "h264_qsv", ["-preset", "veryfast", "-global_quality", "22"], "Intel Quick Sync (QSV)"

    if test_ffmpeg_encoder("h264_amf"):
        return "h264_amf", ["-quality", "speed"], "AMD AMF (GPU)"

    return "libx264", ["-preset", "veryfast", "-crf", "22"], "FFmpeg libx264 (CPU)"


def get_video_metadata(video_path: str) -> dict[str, Any]:
    """Extract media dimensions, duration, and stream properties via FFprobe.

    Supports both video containers and standalone audio tracks.

    Args:
        video_path: Absolute or relative path to the media file.

    Returns:
        Dictionary containing width, height, duration in seconds, aspect ratio,
        and media type flags.

    Raises:
        FileNotFoundError: If the specified media file does not exist.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Media file not found: {video_path}")

    ffprobe = get_ffprobe_binary()
    # SECURITY: Prevent command injection (CWE-78) by executing ffprobe as discrete argument list
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "stream=codec_type,width,height,duration,r_frame_rate,sample_rate,channels:format=duration",
        "-of", "json",
        os.path.abspath(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except Exception:
        data = {}

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    has_video = video_stream is not None
    width = int(video_stream.get("width", 1080)) if has_video else 1080
    height = int(video_stream.get("height", 1920)) if has_video else 1920

    duration_str = None
    if video_stream and video_stream.get("duration"):
        duration_str = video_stream.get("duration")
    elif audio_stream and audio_stream.get("duration"):
        duration_str = audio_stream.get("duration")
    elif fmt.get("duration"):
        duration_str = fmt.get("duration")

    try:
        duration = float(duration_str) if duration_str else 0.0
    except (ValueError, TypeError):
        duration = 0.0

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "has_video": has_video,
        "is_audio_only": not has_video,
        "aspect_ratio": f"{width}:{height}",
        "is_vertical": height > width,
    }


def extract_poster_frame(video_path: str, output_image_path: str, timestamp_sec: float = 2.0) -> str:
    """Extract a representative still image or generate an audio placeholder card.

    Args:
        video_path: Path to the input video or audio file.
        output_image_path: Path where the extracted JPEG poster will be written.
        timestamp_sec: Offset in seconds from which to grab the video frame.

    Returns:
        The output image path on success.
    """
    # SECURITY: Canonicalize output path and verify directory existence
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
    meta = get_video_metadata(video_path)

    if not meta.get("has_video", True):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1080, 1920), color=(11, 15, 25))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([140, 700, 940, 1220], radius=40, fill=(18, 24, 38), outline=(30, 41, 59), width=2)
        img.save(output_image_path, "JPEG", quality=85)
        return output_image_path

    if meta["duration"] > 0 and timestamp_sec >= meta["duration"]:
        timestamp_sec = max(0.5, meta["duration"] * 0.1)

    ffmpeg = get_ffmpeg_binary()
    # SECURITY: Execute ffmpeg with discrete argument vector (CWE-78)
    cmd = [
        ffmpeg,
        "-y",
        "-ss", str(timestamp_sec),
        "-i", os.path.abspath(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        os.path.abspath(output_image_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        from PIL import Image
        img = Image.new("RGB", (1080, 1920), color=(11, 15, 25))
        img.save(output_image_path, "JPEG", quality=85)

    return output_image_path


def extract_audio(video_path: str, output_wav_path: str) -> str:
    """Extract and transcode media audio into 16kHz mono 16-bit PCM WAV.

    Generates the optimal audio format required by WhisperX acoustic models
    and Wav2Vec2 forced aligners.

    Args:
        video_path: Path to the input media container.
        output_wav_path: Target path for the extracted 16kHz WAV file.

    Returns:
        Path to the successfully extracted WAV file.

    Raises:
        RuntimeError: If FFmpeg fails or the output file is empty.
    """
    # SECURITY: Canonicalize target path and prepare containing directory
    os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
    ffmpeg = get_ffmpeg_binary()
    # SECURITY: Discrete argument vector prevents shell injection (CWE-78)
    cmd = [
        ffmpeg,
        "-y",
        "-i", os.path.abspath(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        os.path.abspath(output_wav_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) == 0:
        raise RuntimeError(f"Audio extraction failed for {video_path}")
    return output_wav_path


def _execute_ffmpeg_with_progress(
    cmd: list[str],
    cwd: str,
    duration: float = 0.0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, str]:
    """Execute FFmpeg with real-time stream pipe polling (-progress pipe:1).

    SECURITY: Runs discrete command argument array (CWE-78 mitigation).
    Reads stdout line-by-line for telemetry key-value pairs without buffering,
    streaming out_time_us, fps, speed, and frame while a separate daemon thread
    captures stderr to prevent process buffer deadlocks.

    Args:
        cmd: Discrete command argument list.
        cwd: Working directory for process execution.
        duration: Total video duration in seconds for progress percentage calculation.
        progress_callback: Optional callback receiving live telemetry metrics.

    Returns:
        Tuple of (returncode, captured_stderr_string).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: list[str] = []

    def capture_stderr():
        if proc.stderr:
            for line in proc.stderr:
                stderr_lines.append(line)

    stderr_thread = threading.Thread(target=capture_stderr, daemon=True)
    stderr_thread.start()

    current_metrics: dict[str, Any] = {
        "frame": 0,
        "fps": 0.0,
        "speed": 1.0,
        "current_seconds": 0.0,
        "duration": duration,
        "burn_pct": 0.0,
        "eta_seconds": 0.0,
    }

    if proc.stdout:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()

            if key == "frame":
                try:
                    current_metrics["frame"] = int(val)
                except ValueError:
                    pass
            elif key == "fps":
                try:
                    current_metrics["fps"] = float(val)
                except ValueError:
                    pass
            elif key == "speed":
                if val.endswith("x"):
                    try:
                        current_metrics["speed"] = max(0.01, float(val[:-1]))
                    except ValueError:
                        pass
            elif key in ("out_time_us", "out_time_ms"):
                try:
                    us = int(val)
                    cur_sec = us / 1_000_000.0
                    current_metrics["current_seconds"] = cur_sec
                    if duration > 0:
                        burn_pct = min(99.5, max(0.0, (cur_sec / duration) * 100.0))
                        current_metrics["burn_pct"] = burn_pct
                        rem_sec = max(0.0, duration - cur_sec)
                        speed = current_metrics["speed"]
                        current_metrics["eta_seconds"] = rem_sec / speed if speed > 0 else 0.0
                except ValueError:
                    pass
            elif key == "progress":
                if progress_callback:
                    try:
                        progress_callback(dict(current_metrics))
                    except Exception:
                        pass

    proc.wait()
    stderr_thread.join(timeout=2.0)
    full_stderr = "".join(stderr_lines)
    return proc.returncode, full_stderr


def burn_subtitles_to_video(
    video_path: str,
    ass_path: str,
    output_video_path: str,
    duration: float | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Burn ASS subtitles into the video stream using hardware-accelerated encoding.

    Attempts hardware-accelerated encoding first (Apple VideoToolbox, NVENC, QSV, AMF)
    and automatically falls back to CPU-based libx264 if hardware encoding encounters
    an error. Streams real-time transcode telemetry via -progress pipe:1.

    Args:
        video_path: Path to the source video file.
        ass_path: Path to the Advanced SubStation Alpha (.ass) subtitle file.
        output_video_path: Destination path for the rendered MP4 file.
        duration: Optional media duration in seconds for progress and ETA calculations.
        progress_callback: Optional callable receiving periodic telemetry dictionaries.

    Returns:
        Path to the generated MP4 file.

    Raises:
        RuntimeError: If both hardware and software subtitle burning fail.
    """
    # SECURITY: Ensure output directory exists with canonical absolute path
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    ass_dir = os.path.dirname(os.path.abspath(ass_path))
    ass_filename = os.path.basename(ass_path)
    ffmpeg = get_ffmpeg_binary()

    if duration is None or duration <= 0:
        try:
            meta = get_video_metadata(video_path)
            duration = float(meta.get("duration", 0.0))
        except Exception:
            duration = 0.0

    encoder_name, encoder_flags, friendly_label = get_best_h264_encoder()

    # SECURITY: Discrete argument array mitigating command injection (CWE-78)
    cmd_primary = [
        ffmpeg, "-y",
        "-i", os.path.abspath(video_path),
        "-vf", f"subtitles={ass_filename}",
        "-c:v", encoder_name,
        *encoder_flags,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        os.path.abspath(output_video_path),
    ]
    rc, stderr_out = _execute_ffmpeg_with_progress(
        cmd_primary, cwd=ass_dir, duration=duration, progress_callback=progress_callback
    )
    if rc == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
        return output_video_path

    # Fallback to libx264 CPU if the primary hardware encoder fails
    if encoder_name != "libx264":
        cmd_cpu = [
            ffmpeg, "-y",
            "-i", os.path.abspath(video_path),
            "-vf", f"subtitles={ass_filename}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            os.path.abspath(output_video_path),
        ]
        rc_cpu, stderr_cpu = _execute_ffmpeg_with_progress(
            cmd_cpu, cwd=ass_dir, duration=duration, progress_callback=progress_callback
        )
        if rc_cpu == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
            return output_video_path

        err_msg = stderr_cpu or stderr_out
        raise RuntimeError(f"FFmpeg subtitle burning failed: {err_msg}")

    raise RuntimeError(f"FFmpeg subtitle burning failed: {stderr_out}")

