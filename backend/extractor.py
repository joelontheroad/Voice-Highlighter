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


def burn_subtitles_to_video(video_path: str, ass_path: str, output_video_path: str) -> str:
    """Burn ASS subtitles into the video stream using hardware-accelerated encoding.

    Attempts hardware-accelerated encoding first (Apple VideoToolbox, NVENC, QSV, AMF)
    and automatically falls back to CPU-based libx264 if hardware encoding encounters
    an error.

    Args:
        video_path: Path to the source video file.
        ass_path: Path to the Advanced SubStation Alpha (.ass) subtitle file.
        output_video_path: Destination path for the rendered MP4 file.

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
        os.path.abspath(output_video_path),
    ]
    res = subprocess.run(cmd_primary, cwd=ass_dir, capture_output=True, text=True)
    if res.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
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
            os.path.abspath(output_video_path),
        ]
        res_cpu = subprocess.run(cmd_cpu, cwd=ass_dir, capture_output=True, text=True)
        if res_cpu.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
            return output_video_path

        err_msg = res_cpu.stderr or res.stderr
        raise RuntimeError(f"FFmpeg subtitle burning failed: {err_msg}")

    raise RuntimeError(f"FFmpeg subtitle burning failed: {res.stderr}")
