import os
import json
import subprocess
from typing import Dict, Any

def get_video_metadata(video_path: str) -> Dict[str, Any]:
    """
    Extracts media metadata including dimensions, duration, and stream properties using ffprobe.
    Supports video files (mp4, mov, mkv, etc.) and audio files (mp3, wav, m4a, flac, etc.).
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Media file not found: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type,width,height,duration,r_frame_rate,sample_rate,channels:format=duration",
        "-of", "json",
        video_path
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
    """
    Extracts a frame from the video, or generates a clean audio placeholder poster for audio files.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
    meta = get_video_metadata(video_path)

    if not meta.get("has_video", True):
        # Generate clean dark waveform/audio backdrop for audio files
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1080, 1920), color=(11, 15, 25))
        draw = ImageDraw.Draw(img)
        # Draw subtle center card for audio file
        draw.rounded_rectangle([140, 700, 940, 1220], radius=40, fill=(18, 24, 38), outline=(30, 41, 59), width=2)
        img.save(output_image_path, "JPEG", quality=85)
        return output_image_path

    if meta["duration"] > 0 and timestamp_sec >= meta["duration"]:
        timestamp_sec = max(0.5, meta["duration"] * 0.1)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(timestamp_sec),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_image_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
    except Exception:
        from PIL import Image
        img = Image.new("RGB", (1080, 1920), color=(11, 15, 25))
        img.save(output_image_path, "JPEG", quality=85)

    return output_image_path

def extract_audio(video_path: str, output_wav_path: str) -> str:
    """
    Extracts audio from a video file into a 16kHz mono 16-bit PCM WAV file
    optimized for WhisperX and Wav2Vec2 forced alignment.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) == 0:
        raise RuntimeError(f"Audio extraction failed for {video_path}")
    return output_wav_path

def burn_subtitles_to_video(video_path: str, ass_path: str, output_video_path: str) -> str:
    """
    Burns .ass subtitles into the source video using GPU hardware acceleration (h264_nvenc)
    on the NVIDIA RTX A5000, with fallback to libx264 if needed.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    ass_dir = os.path.dirname(os.path.abspath(ass_path))
    ass_filename = os.path.basename(ass_path)

    # Primary attempt: GPU NVENC encoding on RTX A5000
    cmd_nvenc = [
        "ffmpeg", "-y",
        "-i", os.path.abspath(video_path),
        "-vf", f"subtitles={ass_filename}",
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-cq", "22",
        "-c:a", "copy",
        os.path.abspath(output_video_path)
    ]
    res = subprocess.run(cmd_nvenc, cwd=ass_dir, capture_output=True, text=True)
    if res.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 0:
        return output_video_path

    # Fallback attempt: CPU libx264
    cmd_cpu = [
        "ffmpeg", "-y",
        "-i", os.path.abspath(video_path),
        "-vf", f"subtitles={ass_filename}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "copy",
        os.path.abspath(output_video_path)
    ]
    res_cpu = subprocess.run(cmd_cpu, cwd=ass_dir, capture_output=True, text=True)
    if res_cpu.returncode != 0:
        err_msg = res.stderr or res_cpu.stderr
        raise RuntimeError(f"FFmpeg subtitle burning failed: {err_msg}")

    return output_video_path

