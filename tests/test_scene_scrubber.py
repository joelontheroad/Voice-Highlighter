# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit and integration tests for video timeline scrubbing and 5-point scene checkpoints.

Verifies sub-50ms frame seeking logic, input-seek FFmpeg argument composition,
caching in XDG frames directory, 5-point filmstrip snapshot generation in fetch_video_info,
and secure HTTP frame streaming endpoints.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from backend.app import VideoInfoRequest, fetch_video_info, get_video_frame, stream_video
from backend.extractor import extract_poster_frame, extract_video_frame_at_timestamp


def test_extract_video_frame_audio_fallback(tmp_path: Path):
    """Verify audio-only or non-video media generates a fallback PIL card."""
    audio_path = tmp_path / "test_audio.wav"
    audio_path.write_bytes(b"RIFF" + b"\x00" * 36)
    out_img = tmp_path / "out_audio_poster.jpg"

    with patch("backend.extractor.get_video_metadata", return_value={"has_video": False, "duration": 42.0}):
        result = extract_video_frame_at_timestamp(str(audio_path), str(out_img), timestamp_sec=5.0)

    assert os.path.exists(result)
    assert os.path.getsize(result) > 0


def test_extract_video_frame_ffmpeg_cmd_structure(tmp_path: Path):
    """Verify FFmpeg receives discrete argument vector with input-seeking flags and optional scale."""
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"\x00" * 100)
    out_img = tmp_path / "frame_5.jpg"

    mock_run = MagicMock()
    with (
        patch("backend.extractor.get_video_metadata", return_value={"has_video": True, "duration": 120.0}),
        patch("backend.extractor.get_ffmpeg_binary", return_value="/usr/bin/ffmpeg"),
        patch("subprocess.run", mock_run),
    ):
        extract_video_frame_at_timestamp(
            str(video_path),
            str(out_img),
            timestamp_sec=35.5,
            scale_width=240,
        )

    assert mock_run.called
    cmd_args = mock_run.call_args[0][0]
    # SECURITY: Verify discrete argument vector (no shell=True)
    assert isinstance(cmd_args, list)
    assert cmd_args[0] == "/usr/bin/ffmpeg"
    assert "-ss" in cmd_args
    # Input seek: -ss must precede -i for sub-50ms keyframe alignment
    ss_idx = cmd_args.index("-ss")
    i_idx = cmd_args.index("-i")
    assert ss_idx < i_idx
    assert cmd_args[ss_idx + 1] == "35.500"
    assert "-frames:v" in cmd_args
    assert "1" in cmd_args
    assert "-vf" in cmd_args
    assert "scale=240:-1" in cmd_args


def test_extract_poster_frame_delegates_to_timestamp(tmp_path: Path):
    """Verify legacy extract_poster_frame delegates to extract_video_frame_at_timestamp."""
    video_path = tmp_path / "clip.mp4"
    out_img = tmp_path / "poster.jpg"

    with patch("backend.extractor.extract_video_frame_at_timestamp", return_value=str(out_img)) as mock_extract:
        res = extract_poster_frame(str(video_path), str(out_img), timestamp_sec=3.0)
        assert res == str(out_img)
        mock_extract.assert_called_once_with(
            video_path=str(video_path),
            output_image_path=str(out_img),
            timestamp_sec=3.0,
        )


def test_get_video_frame_missing_file():
    """Verify get_video_frame raises 404 when media file does not exist."""
    with pytest.raises(HTTPException) as exc_info:
        get_video_frame(path="/non/existent/video.mp4", t=5.0)
    assert exc_info.value.status_code == 404
    assert "Media file not found" in exc_info.value.detail


def test_get_video_frame_cache_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify repeat seeks to identical timestamps stream directly from the cache directory."""
    video_path = tmp_path / "interview.mp4"
    video_path.write_bytes(b"\x00" * 100)

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.app.FRAMES_DIR", str(frames_dir))

    # Mock frame extractor to write a dummy jpg
    def mock_extract(src, dst, timestamp_sec=0.0, scale_width=None):
        Path(dst).write_bytes(b"JPEG_DATA")
        return dst

    monkeypatch.setattr("backend.app.extract_video_frame_at_timestamp", mock_extract)

    # First call: triggers extraction
    resp1 = get_video_frame(str(video_path), t=12.5, thumb=0)
    assert isinstance(resp1, FileResponse)
    assert os.path.exists(resp1.path)

    # Second call: served from existing cached file without re-extracting
    with patch("backend.app.extract_video_frame_at_timestamp") as mock_no_call:
        resp2 = get_video_frame(str(video_path), t=12.5, thumb=0)
        assert isinstance(resp2, FileResponse)
        assert resp2.path == resp1.path
        mock_no_call.assert_not_called()


def test_fetch_video_info_includes_5_scene_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify fetch_video_info generates and returns 5 scene checkpoints across duration."""
    video_path = tmp_path / "lecture.mp4"
    video_path.write_bytes(b"\x00" * 100)

    frames_dir = tmp_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.app.FRAMES_DIR", str(frames_dir))

    mock_meta = {
        "width": 1080,
        "height": 1920,
        "duration": 60.0,
        "is_vertical": True,
        "has_video": True,
    }

    monkeypatch.setattr("backend.app.get_video_metadata", lambda p: mock_meta)
    monkeypatch.setattr("backend.app.extract_poster_frame", lambda src, dst, **kw: dst)
    monkeypatch.setattr("backend.app.extract_video_frame_at_timestamp", lambda src, dst, **kw: dst)

    req = VideoInfoRequest(video_path=str(video_path))
    info = fetch_video_info(req)

    assert "scene_snapshots" in info
    snapshots = info["scene_snapshots"]
    assert len(snapshots) == 5

    labels = [s["label"] for s in snapshots]
    assert labels == ["0%", "25%", "50%", "75%", "End"]

    # Timestamps should be increasing
    ts = [s["timestamp"] for s in snapshots]
    assert ts == sorted(ts)
    assert ts[0] >= 0.0
    assert ts[-1] <= 60.0

    # Each checkpoint provides a serving URL
    for s in snapshots:
        assert s["url"].startswith("/api/frame/")


def test_frontend_timeline_and_header_cleanup():
    """Verify frontend template keeps timeline scrubber unhidden and moves AGPL link strictly to footer."""
    index_path = Path("frontend/index.html")
    assert index_path.exists(), "frontend/index.html must exist"
    content = index_path.read_text(encoding="utf-8")

    # Header cleanup: "Source Code (GNU AGPLv3)" must NOT be inside <header>
    header_start = content.find("<header")
    header_end = content.find("</header>")
    assert header_start != -1 and header_end != -1
    header_content = content[header_start:header_end]
    assert "Source Code" not in header_content, "Header must not contain source code pill"

    # Footer compliance: AGPL Section 13 notice must be present in <footer>
    footer_start = content.find("<footer")
    footer_end = content.find("</footer>")
    assert footer_start != -1 and footer_end != -1
    footer_content = content[footer_start:footer_end]
    assert "Source Code (GNU AGPLv3)" in footer_content, "Footer must maintain Section 13 AGPL notice"
    assert "https://github.com/joelontheroad/Voice-Highlighter" in footer_content

    # Timeline scrubber & controls markup presence & visibility
    assert '<div class="stage-timeline-wrap" id="stageTimelineWrap">' in content, (
        "stageTimelineWrap must not have 'hidden' class by default"
    )
    assert 'id="stageTimelineSlider"' in content
    assert 'id="btnPlayPause"' in content
    assert 'id="stageVideo"' in content
    assert 'id="btnStepBack5"' in content
    assert 'id="btnStepBack1"' in content
    assert 'id="btnStepFwd1"' in content
    assert 'id="btnStepFwd5"' in content
    assert 'id="sceneFilmstripTray"' in content


def test_stream_video_endpoint_success(tmp_path: Path):
    """Verify /api/video-stream returns a FileResponse with correct media_type for video playback."""
    clip = tmp_path / "sample.mp4"
    clip.write_bytes(b"\x00" * 256)

    res = stream_video(path=str(clip))
    assert isinstance(res, FileResponse)
    assert res.path == str(clip)
    assert res.media_type == "video/mp4"


def test_stream_video_missing_file_raises_404(tmp_path: Path):
    """Verify /api/video-stream raises 404 when file does not exist on disk."""
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(HTTPException) as exc_info:
        stream_video(path=str(missing))
    assert exc_info.value.status_code == 404


def test_stream_video_media_type_detection(tmp_path: Path):
    """Verify /api/video-stream detects appropriate media types based on file extension."""
    webm = tmp_path / "sample.webm"
    webm.write_bytes(b"\x00" * 32)
    res_webm = stream_video(path=str(webm))
    assert res_webm.media_type == "video/webm"

    wav = tmp_path / "sample.wav"
    wav.write_bytes(b"\x00" * 32)
    res_wav = stream_video(path=str(wav))
    assert res_wav.media_type == "audio/wav"

    mp3 = tmp_path / "sample.mp3"
    mp3.write_bytes(b"\x00" * 32)
    res_mp3 = stream_video(path=str(mp3))
    assert res_mp3.media_type == "audio/mpeg"


