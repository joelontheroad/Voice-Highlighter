# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Advanced SubStation Alpha (ASS) subtitle generator.

Synthesizes SSA/ASS v4+ subtitle scripts with karaoke-style active word
highlighting, custom typography, positional anchoring, bounding badge styling,
and responsive multi-line layout algorithms.
"""

import re
from typing import Any


def hex_to_ass_color(hex_color: str, opacity: float = 1.0) -> str:
    """Convert a CSS hex color code and opacity into ASS color format.

    Translates RGB/RRGGBB hex values into the ASS inverted-alpha BGR representation:
    `&HAABBGGRR&`. In ASS format, an alpha byte of 00 represents fully opaque,
    and FF represents fully transparent.

    Args:
        hex_color: Web hex color string (e.g., '#FFFFFF' or '#FFF').
        opacity: Normalized opacity value ranging from 0.0 (transparent) to 1.0 (opaque).

    Returns:
        Formatted ASS color string (&HAABBGGRR&).
    """
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(c * 2 for c in cleaned)
    elif len(cleaned) != 6:
        cleaned = "FFFFFF"

    r = cleaned[0:2]
    g = cleaned[2:4]
    b = cleaned[4:6]

    # Invert alpha for ASS: 1.0 opacity -> 0 alpha; 0.0 opacity -> 255 alpha
    alpha_val = int(round((1.0 - max(0.0, min(1.0, opacity))) * 255))
    alpha_hex = f"{alpha_val:02X}"

    return f"&H{alpha_hex}{b}{g}{r}&"


def format_timestamp(seconds: float) -> str:
    """Convert a decimal duration in seconds to an ASS timestamp string.

    Args:
        seconds: Time offset in seconds (e.g., 65.432).

    Returns:
        Formatted timestamp string in 'H:MM:SS.cs' representation.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def parse_ass_timestamp(ts_str: str) -> float:
    """Parse an ASS timestamp string ('H:MM:SS.cs') into seconds.

    Args:
        ts_str: Formatted ASS timestamp string.

    Returns:
        Float value in total elapsed seconds.
    """
    try:
        parts = ts_str.strip().split(":")
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            s = float(parts[2])
            return h * 3600.0 + m * 60.0 + s
        elif len(parts) == 2:
            m = float(parts[0])
            s = float(parts[1])
            return m * 60.0 + s
    except Exception:
        pass
    return 0.0


def resolve_styling_at_time(
    t: float,
    keyframes: list[dict[str, Any]],
    base_config: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the active styling configuration for a given timestamp.

    The style defined by a keyframe stays in effect to the right of the timeline
    until another keyframe is encountered. If the timestamp is before all keyframes,
    the base configuration applies.

    Args:
        t: Media timestamp in seconds.
        keyframes: Chronologically sorted list of keyframe dictionaries.
        base_config: Default/base styling configuration dictionary.

    Returns:
        Merged styling dictionary in effect at timestamp t.
    """
    if not keyframes:
        return base_config

    active_kf = None
    for kf in keyframes:
        kf_time = float(kf.get("time", 0.0))
        if kf_time <= t + 1e-4:
            active_kf = kf
        else:
            break

    if active_kf is None:
        return base_config

    raw_styling = active_kf.get("styling") or {}
    merged = dict(base_config)
    key_aliases = {
        "posX": "pos_x_pct",
        "posY": "pos_y_pct",
        "fontFamily": "font_name",
        "fontSize": "font_size",
        "primaryColor": "primary_color",
        "outlineColor": "outline_color",
        "outlineWidth": "outline_width",
        "highlightStyle": "highlight_style",
        "highlightColor": "highlight_color",
        "highlightScale": "highlight_scale_pct",
        "highlightAnimation": "highlight_animation",
        "boxType": "box_type",
        "boxOpacity": "box_opacity",
        "boxBgColor": "box_bg_color",
        "boxFontColor": "box_font_color",
        "maxLines": "max_lines",
        "lineWidthPct": "line_width_pct",
        "maxChars": "max_chars_per_line",
    }
    for k, v in raw_styling.items():
        merged[k] = v
        if k in key_aliases:
            merged[key_aliases[k]] = v

    return merged


def chunk_words_into_blocks(
    words: list[dict[str, Any]],
    max_lines: int = 1,
    max_chars_per_line: int = 32,
    max_gap_seconds: float = 0.6,
) -> list[list[list[dict[str, Any]]]]:
    """Partition a continuous sequence of timed words into readable subtitle blocks.

    Breaks streams based on natural speech pauses, punctuation boundaries,
    speaker turns, line character limits, and maximum lines per visual subtitle block.

    Args:
        words: List of aligned word dictionaries containing 'word', 'start', 'end',
            and optional 'speaker'.
        max_lines: Maximum simultaneous visible lines allowed per block.
        max_chars_per_line: Upper bound for characters across a single line.
        max_gap_seconds: Inter-word silence threshold triggering a block break.

    Returns:
        Nested structure: list of blocks -> list of lines -> list of word dicts.
    """
    if not words:
        return []

    blocks = []
    current_block_lines = []
    current_line_words = []
    current_line_len = 0
    last_end_time = None
    current_speaker = None

    for w in words:
        word_text = w.get("word", "").strip()
        if not word_text:
            continue

        start_time = w.get("start", 0.0)
        end_time = w.get("end", start_time + 0.1)
        word_speaker = w.get("speaker")

        # Check for natural break: long pause or speaker turn
        pause_break = last_end_time is not None and (start_time - last_end_time) > max_gap_seconds
        speaker_turn = (
            current_speaker is not None
            and word_speaker is not None
            and word_speaker != current_speaker
        )

        # Check if line would exceed char limit
        would_exceed_line = (current_line_len + len(word_text) + (1 if current_line_len > 0 else 0)) > max_chars_per_line

        if pause_break or speaker_turn or (would_exceed_line and current_line_words):
            if current_line_words:
                current_block_lines.append(current_line_words)
                current_line_words = []
                current_line_len = 0

            if len(current_block_lines) >= max_lines or pause_break or speaker_turn:
                if current_block_lines:
                    blocks.append(current_block_lines)
                    current_block_lines = []

        current_line_words.append(w)
        current_line_len += len(word_text) + (1 if current_line_len > 0 else 0)
        last_end_time = end_time
        if word_speaker is not None:
            current_speaker = word_speaker

        # If word ends with strong sentence terminator, break block naturally
        if word_text.endswith((".", "!", "?")) and current_line_len >= (max_chars_per_line * 0.6):
            current_block_lines.append(current_line_words)
            blocks.append(current_block_lines)
            current_block_lines = []
            current_line_words = []
            current_line_len = 0
            current_speaker = None

    if current_line_words:
        current_block_lines.append(current_line_words)
    if current_block_lines:
        blocks.append(current_block_lines)

    return blocks


def generate_ass_content(
    whisper_result: dict[str, Any],
    config: dict[str, Any],
    video_meta: dict[str, Any] | None = None,
) -> str:
    """Generate a complete ASS v4+ subtitle script with dynamic word-level highlights.

    Constructs script headers, typography styles, coordinate systems, and
    non-overlapping dialogue events with animated highlight color shifts or
    bounding badge badges.

    Args:
        whisper_result: Output dictionary from WhisperX transcription pipeline.
        config: Subtitle styling configuration dictionary or StylePreset dump.
        video_meta: Optional dictionary containing canvas dimensions ('width', 'height').

    Returns:
        UTF-8 encoded string content of the complete .ass subtitle document.
    """
    # Extract resolution
    play_res_x = 1080
    play_res_y = 1920
    if video_meta:
        play_res_x = int(video_meta.get("width", 1080))
        play_res_y = int(video_meta.get("height", 1920))

    # Styling params
    font_name = config.get("font_name", "Montserrat")
    font_size = int(config.get("font_size", 68 if play_res_y >= 1920 else 48))
    bold = -1 if config.get("bold", True) else 0
    italic = -1 if config.get("italic", False) else 0

    primary_color_hex = config.get("primary_color", "#FFFFFF")
    outline_color_hex = config.get("outline_color", "#000000")
    outline_width = float(config.get("outline_width", 3.0))

    highlight_style = config.get("highlight_style", "color")
    highlight_color_hex = config.get("highlight_color", "#FFDF00")

    # Bounding box options
    box_bg_color_hex = config.get("box_bg_color", "#000000")
    box_opacity = float(config.get("box_opacity", 0.75))
    box_font_color_hex = config.get("box_font_color", "#FFFFFF")
    box_type = config.get("box_type", "word")

    # Active word size boost percentage (100% to 200%)
    highlight_scale_pct = int(config.get("highlight_scale_pct", 100))
    scale_tag = f"\\fscx{highlight_scale_pct}\\fscy{highlight_scale_pct}" if highlight_scale_pct != 100 else ""
    scale_reset = "\\fscx100\\fscy100" if highlight_scale_pct != 100 else ""

    # Highlight animation style: 'discrete' (default), 'karaoke_wipe' (\\kf), or 'anticipation_glow'
    highlight_animation = str(config.get("highlight_animation", "discrete")).lower()

    # Positioning params
    pos_x_pct = float(config.get("pos_x_pct", 50.0))
    pos_y_pct = float(config.get("pos_y_pct", 78.0))

    pos_x = int(play_res_x * (pos_x_pct / 100.0))
    pos_y = int(play_res_y * (pos_y_pct / 100.0))

    # Line formatting & width
    line_width_pct = float(config.get("line_width_pct", 82.0))
    max_lines = int(config.get("max_lines", 1))

    # Calculate responsive margin based on line width
    margin_lr = max(10, int(play_res_x * (1.0 - (line_width_pct / 100.0)) / 2.0))
    margin_v = max(10, int(play_res_y * (1.0 - (pos_y_pct / 100.0))))

    # Adapt max characters per line if not explicitly small
    effective_width_px = play_res_x * (line_width_pct / 100.0)
    auto_max_chars = max(12, int(effective_width_px / (font_size * 0.58)))
    user_max_chars = int(config.get("max_chars_per_line", 28))
    max_chars_per_line = min(user_max_chars, auto_max_chars)

    # Parse and normalize speaker channels map
    speaker_channels_raw = config.get("speaker_channels") or {}
    speaker_channels: dict[str, dict[str, Any]] = {}
    if isinstance(speaker_channels_raw, dict):
        for k, v in speaker_channels_raw.items():
            if hasattr(v, "model_dump"):
                speaker_channels[k] = v.model_dump()
            elif isinstance(v, dict):
                speaker_channels[k] = dict(v)
            else:
                speaker_channels[k] = {"id": k, "name": str(v)}

    # ASS Color strings
    ass_primary = hex_to_ass_color(primary_color_hex, 1.0)
    ass_outline = hex_to_ass_color(outline_color_hex, 1.0)
    ass_highlight = hex_to_ass_color(highlight_color_hex, 1.0)
    ass_box_bg = hex_to_ass_color(box_bg_color_hex, box_opacity)
    ass_box_font = hex_to_ass_color(box_font_color_hex, 1.0)

    # Determine border style
    border_style = 3 if (highlight_style == "box" and box_type == "block") else 1
    back_color = ass_box_bg if border_style == 3 else "&H80000000&"

    # Register styles in [V4+ Styles]
    style_lines = [
        f"Style: Default,{font_name},{font_size},{ass_primary},{ass_highlight},{ass_outline},{back_color},{bold},{italic},0,0,100,100,0,0,{border_style},{outline_width},0,2,{margin_lr},{margin_lr},{margin_v},1",
        f"Style: HighlightBox,{font_name},{font_size},{ass_box_font},{ass_highlight},{ass_box_bg},{ass_box_bg},{bold},{italic},0,0,100,100,0,0,3,6,0,2,{margin_lr},{margin_lr},{margin_v},1",
    ]
    registered_styles = {"Default", "HighlightBox"}

    for spk_id, spk_cfg in speaker_channels.items():
        spk_pri = hex_to_ass_color(spk_cfg.get("primary_color", primary_color_hex), 1.0)
        spk_out = hex_to_ass_color(spk_cfg.get("outline_color", outline_color_hex), 1.0)
        spk_hl = hex_to_ass_color(spk_cfg.get("highlight_color", highlight_color_hex), 1.0)
        spk_style_name = f"Speaker_{spk_id}"
        style_lines.append(
            f"Style: {spk_style_name},{font_name},{font_size},{spk_pri},{spk_hl},{spk_out},{back_color},{bold},{italic},0,0,100,100,0,0,{border_style},{outline_width},0,2,{margin_lr},{margin_lr},{margin_v},1"
        )
        registered_styles.add(spk_style_name)

    v4_styles_block = "\n".join(style_lines)

    header = f"""[Script Info]
; Script generated by Voice Highlighter
Title: Voice Highlighter Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{v4_styles_block}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    all_words = []
    segments = whisper_result.get("segments", [])
    for seg in segments:
        seg_speaker = seg.get("speaker")
        words = seg.get("words", [])
        if words:
            for w in words:
                if "start" in w and "end" in w:
                    w_text = w.get("word", "").strip()
                    if w_text:
                        s = float(w["start"])
                        e = float(w["end"])
                        all_words.append({
                            "word": w_text,
                            "start": s,
                            "end": max(e, s + 0.08),
                            "speaker": w.get("speaker") or seg_speaker or "SPEAKER_00",
                        })
        else:
            w_text = seg.get("text", "").strip()
            if w_text:
                s = float(seg.get("start", 0.0))
                e = float(seg.get("end", s + 1.0))
                all_words.append({
                    "word": w_text,
                    "start": s,
                    "end": max(e, s + 0.1),
                    "speaker": seg_speaker or "SPEAKER_00",
                })

    if not all_words:
        return header

    blocks = chunk_words_into_blocks(all_words, max_lines=max_lines, max_chars_per_line=max_chars_per_line)

    slices = []
    for b_idx, block in enumerate(blocks):
        block_words = [w for line in block for w in line]
        if not block_words:
            continue
        for w_idx, w in enumerate(block_words):
            next_w = block_words[w_idx + 1] if (w_idx + 1 < len(block_words)) else None
            slices.append({
                "block": block,
                "block_words": block_words,
                "active_word": w,
                "next_word": next_w,
                "w_idx": w_idx,
                "is_last_in_block": (w_idx == len(block_words) - 1),
                "is_first_in_block": (w_idx == 0),
                "b_idx": b_idx,
            })

    if not slices:
        return header

    # Parse keyframes from config if present
    keyframes_raw = config.get("keyframes") or []
    keyframes: list[dict[str, Any]] = []
    if isinstance(keyframes_raw, list):
        for kf in keyframes_raw:
            if hasattr(kf, "model_dump"):
                kf_data = kf.model_dump()
            elif isinstance(kf, dict):
                kf_data = dict(kf)
            else:
                continue
            if "time" in kf_data:
                keyframes.append(kf_data)
        keyframes.sort(key=lambda k: float(k.get("time", 0.0)))

    event_lines = []
    prev_event_end = 0.0

    for k in range(len(slices)):
        curr = slices[k]
        raw_start = float(curr["active_word"]["start"])
        curr_speaker = curr["active_word"].get("speaker", "SPEAKER_00")

        if k == 0:
            start_time = raw_start
        else:
            start_time = max(raw_start, prev_event_end)

        # Resolve active styling for this dialogue event based on start_time.
        # Keyframe style stays in effect to the right of the timeline until another keyframe is encountered.
        kf_cfg = resolve_styling_at_time(start_time, keyframes, config) if keyframes else config

        kf_pos_x_pct = kf_cfg.get("pos_x_pct")
        event_pos_x = int(play_res_x * (float(kf_pos_x_pct) / 100.0)) if kf_pos_x_pct is not None else pos_x
        kf_pos_y_pct = kf_cfg.get("pos_y_pct")
        event_pos_y = int(play_res_y * (float(kf_pos_y_pct) / 100.0)) if kf_pos_y_pct is not None else pos_y

        event_hl_anim = str(kf_cfg.get("highlight_animation", highlight_animation)).lower()
        event_hl_style = str(kf_cfg.get("highlight_style", highlight_style)).lower()
        event_box_type = str(kf_cfg.get("box_type", box_type)).lower()
        event_scale_pct = int(kf_cfg.get("highlight_scale_pct", highlight_scale_pct))
        event_scale_tag = f"\\fscx{event_scale_pct}\\fscy{event_scale_pct}" if event_scale_pct != 100 else ""
        event_scale_reset = "\\fscx100\\fscy100" if event_scale_pct != 100 else ""

        kf_pri_hex = kf_cfg.get("primary_color", primary_color_hex)
        kf_out_hex = kf_cfg.get("outline_color", outline_color_hex)
        kf_hl_hex = kf_cfg.get("highlight_color", highlight_color_hex)
        kf_box_bg_hex = kf_cfg.get("box_bg_color", box_bg_color_hex)
        kf_box_font_hex = kf_cfg.get("box_font_color", box_font_color_hex)
        kf_box_opacity = float(kf_cfg.get("box_opacity", box_opacity))
        kf_out_w = float(kf_cfg.get("outline_width", outline_width))

        # Resolve speaker channel configuration
        channel = speaker_channels.get(curr_speaker)
        if channel:
            slice_primary = hex_to_ass_color(channel.get("primary_color", kf_pri_hex), 1.0)
            slice_outline = hex_to_ass_color(channel.get("outline_color", kf_out_hex), 1.0)
            slice_highlight = hex_to_ass_color(channel.get("highlight_color", kf_hl_hex), 1.0)
            slice_box_bg = hex_to_ass_color(channel.get("box_bg_color", kf_box_bg_hex), kf_box_opacity)
            slice_box_font = hex_to_ass_color(channel.get("box_font_color", kf_box_font_hex), 1.0)
            spk_display_name = channel.get("name", curr_speaker)
            show_name_prefix = channel.get("show_speaker_name", False)
            style_name = f"Speaker_{curr_speaker}" if f"Speaker_{curr_speaker}" in registered_styles else "Default"
        else:
            slice_primary = hex_to_ass_color(kf_pri_hex, 1.0)
            slice_outline = hex_to_ass_color(kf_out_hex, 1.0)
            slice_highlight = hex_to_ass_color(kf_hl_hex, 1.0)
            slice_box_bg = hex_to_ass_color(kf_box_bg_hex, kf_box_opacity)
            slice_box_font = hex_to_ass_color(kf_box_font_hex, 1.0)
            spk_display_name = curr_speaker if curr_speaker != "SPEAKER_00" else ""
            show_name_prefix = False
            style_name = "Default"

        if k + 1 < len(slices):
            next_slice = slices[k + 1]
            next_raw_start = float(next_slice["active_word"]["start"])
            next_start_clamped = max(next_raw_start, start_time + 0.05)

            if curr["is_last_in_block"]:
                word_end = float(curr["active_word"]["end"])
                if (next_start_clamped - word_end) > 0.35:
                    end_time = min(word_end + 0.08, next_start_clamped)
                else:
                    end_time = next_start_clamped
            else:
                end_time = next_start_clamped
        else:
            end_time = max(float(curr["active_word"]["end"]) + 0.25, start_time + 0.40)

        if end_time <= start_time:
            end_time = start_time + 0.08

        prev_event_end = end_time

        start_ts = format_timestamp(start_time)
        end_ts = format_timestamp(end_time)

        rendered_lines = []
        for line in curr["block"]:
            line_parts = []
            for w in line:
                raw_word = w.get("word", "").strip()
                if w is curr["active_word"]:
                    if event_hl_anim == "karaoke_wipe":
                        # Pioneer LaserKaraoke progressive sweep (US 5,742,569)
                        duration_cs = max(1, int(round((end_time - start_time) * 100)))
                        line_parts.append(
                            f"{{{event_scale_tag}\\kf{duration_cs}\\c{slice_highlight}\\3c{slice_outline}}}{raw_word}{{{event_scale_reset}\\c{slice_primary}\\3c{slice_outline}}}"
                        )
                    elif event_hl_style == "color":
                        line_parts.append(
                            f"{{{event_scale_tag}\\c{slice_highlight}\\3c{slice_outline}}}{raw_word}{{{event_scale_reset}\\c{slice_primary}\\3c{slice_outline}}}"
                        )
                    elif event_hl_style == "box":
                        if event_box_type == "word":
                            line_parts.append(
                                f"{{{event_scale_tag}\\bord8\\3c{slice_box_bg}\\c{slice_box_font}}}{raw_word}{{{event_scale_reset}\\r{style_name}}}"
                            )
                        else:
                            line_parts.append(
                                f"{{{event_scale_tag}\\c{slice_highlight}}}{raw_word}{{{event_scale_reset}\\c{slice_primary}}}"
                            )
                elif event_hl_anim == "anticipation_glow" and curr.get("next_word") and w is curr["next_word"]:
                    # Sony pre-vocal cadence cue (US 5,684,542)
                    line_parts.append(
                        f"{{\\3c{slice_highlight}\\bord4}}{raw_word}{{\\3c{slice_outline}\\bord{kf_out_w}}}"
                    )
                else:
                    line_parts.append(raw_word)
            rendered_lines.append(" ".join(line_parts))

        dialogue_text = "\\N".join(rendered_lines)
        if show_name_prefix and spk_display_name:
            dialogue_text = f"[{spk_display_name}]: {dialogue_text}"

        font_overrides = ""
        kf_fn = kf_cfg.get("font_name")
        if kf_fn and kf_fn != font_name:
            font_overrides += f"\\fn{kf_fn}"
        kf_fs = kf_cfg.get("font_size")
        if kf_fs and int(kf_fs) != font_size:
            font_overrides += f"\\fs{int(kf_fs)}"
        kf_b = kf_cfg.get("bold")
        if kf_b is not None:
            b_val = 1 if kf_b else 0
            base_b_val = 1 if bold == -1 else 0
            if b_val != base_b_val:
                font_overrides += f"\\b{b_val}"
        kf_i = kf_cfg.get("italic")
        if kf_i is not None:
            i_val = 1 if kf_i else 0
            base_i_val = 1 if italic == -1 else 0
            if i_val != base_i_val:
                font_overrides += f"\\i{i_val}"
        if kf_out_w != outline_width:
            font_overrides += f"\\bord{kf_out_w}"

        pos_tag = f"{{\\an2\\pos({event_pos_x},{event_pos_y}){font_overrides}}}"

        event_lines.append(f"Dialogue: 0,{start_ts},{end_ts},{style_name},{spk_display_name},0,0,0,,{pos_tag}{dialogue_text}")

    return header + "\n".join(event_lines) + "\n"


def update_ass_formatting(
    ass_content: str,
    config: dict[str, Any] | None = None,
    video_meta: dict[str, Any] | None = None,
) -> str:
    """Synchronize and update ASS subtitle formatting and active word highlight colors.

    Honors all user formatting changes when burning or re-burning subtitles.
    If the user directly edited SecondaryColour in [V4+ Styles] (or dialogue lines),
    synchronizes word highlight tags to match. If configuration is provided from
    the UI, updates the style table and overrides active word tags while preserving
    dialogue text, timings, and manual wording edits.

    Args:
        ass_content: Full raw ASS script content string.
        config: Optional dictionary containing updated styling parameters.
        video_meta: Optional dictionary containing video dimensions (width, height).

    Returns:
        Updated ASS script content string with synchronized styles and event tags.
    """
    config = config or {}
    keyframes_raw = config.get("keyframes") or []
    keyframes: list[dict[str, Any]] = []
    if isinstance(keyframes_raw, list):
        for kf in keyframes_raw:
            if hasattr(kf, "model_dump"):
                kf_data = kf.model_dump()
            elif isinstance(kf, dict):
                kf_data = dict(kf)
            else:
                continue
            if "time" in kf_data:
                keyframes.append(kf_data)
        keyframes.sort(key=lambda k: float(k.get("time", 0.0)))

    lines = ass_content.splitlines()

    play_res_x = 1920
    play_res_y = 1080
    if video_meta:
        play_res_x = video_meta.get("width", 1920) or 1920
        play_res_y = video_meta.get("height", 1080) or 1080
    for line in lines:
        if line.lower().startswith("playresx:"):
            try:
                play_res_x = int(line.split(":", 1)[1].strip())
            except Exception:
                pass
        elif line.lower().startswith("playresy:"):
            try:
                play_res_y = int(line.split(":", 1)[1].strip())
            except Exception:
                pass

    font_name = config.get("font_name")
    font_size = config.get("font_size")
    primary_color_hex = config.get("primary_color")
    highlight_color_hex = config.get("highlight_color")
    outline_color_hex = config.get("outline_color")
    outline_width = config.get("outline_width")
    bold = config.get("bold")
    italic = config.get("italic")
    position = config.get("position")
    margin_v = config.get("margin_v")
    highlight_animation = config.get("highlight_animation")
    box_bg_color_hex = config.get("box_bg_color")
    box_opacity = config.get("box_opacity")
    box_font_color_hex = config.get("box_font_color")
    speaker_channels = config.get("speaker_channels") or {}

    pos_x = play_res_x // 2
    pos_y = None

    pos_x_pct = config.get("pos_x_pct")
    pos_y_pct = config.get("pos_y_pct")
    if pos_x_pct is not None:
        try:
            pos_x = int(play_res_x * (float(pos_x_pct) / 100.0))
        except Exception:
            pass

    if pos_y_pct is not None:
        try:
            pos_y = int(play_res_y * (float(pos_y_pct) / 100.0))
        except Exception:
            pass
    elif position is not None or margin_v is not None or font_size is not None:
        effective_pos = position or "bottom"
        effective_mv = margin_v if margin_v is not None else 54
        effective_fs = font_size if font_size is not None else 22
        if effective_pos == "top":
            pos_y = effective_mv + (effective_fs * 2)
        elif effective_pos == "middle":
            pos_y = play_res_y // 2
        else:
            pos_y = play_res_y - effective_mv

    styles: dict[str, list[str]] = {}
    style_format_idx: dict[str, int] = {}
    style_line_indices: dict[str, int] = {}

    in_styles = False

    for idx, line in enumerate(lines):
        s_line = line.strip()
        if s_line == "[V4+ Styles]":
            in_styles = True
            continue
        elif s_line.startswith("[") and s_line.endswith("]"):
            in_styles = False
            continue

        if in_styles:
            if line.startswith("Format:"):
                fields = [f.strip() for f in line[7:].split(",")]
                style_format_idx = {name: f_idx for f_idx, name in enumerate(fields)}
            elif line.startswith("Style:"):
                parts = line[6:].split(",")
                style_name = parts[0].strip()
                styles[style_name] = [p.strip() for p in parts]
                style_line_indices[style_name] = idx

    def get_style_val(parts: list[str], field_name: str, default: str = "") -> str:
        f_idx = style_format_idx.get(field_name)
        if f_idx is not None and f_idx < len(parts):
            return parts[f_idx]
        return default

    def set_style_val(parts: list[str], field_name: str, value: Any) -> None:
        f_idx = style_format_idx.get(field_name)
        if f_idx is not None and f_idx < len(parts):
            parts[f_idx] = str(value)

    resolved_styles = {}
    for st_name, parts in styles.items():
        p = list(parts)
        is_spk = st_name.startswith("Speaker_")
        spk_id = st_name.replace("Speaker_", "") if is_spk else None
        spk_cfg = {}
        if is_spk and spk_id:
            spk_cfg = (
                speaker_channels.get(spk_id)
                or speaker_channels.get(spk_id.replace("SPEAKER_", ""))
                or speaker_channels.get(f"SPEAKER_{spk_id}")
                or {}
            )
            if hasattr(spk_cfg, "model_dump"):
                spk_cfg = spk_cfg.model_dump()
            elif hasattr(spk_cfg, "dict"):
                spk_cfg = spk_cfg.dict()

        effective_hl_hex = spk_cfg.get("highlight_color") or highlight_color_hex
        if effective_hl_hex is not None:
            st_hl = hex_to_ass_color(effective_hl_hex, 1.0)
            set_style_val(p, "SecondaryColour", st_hl)
        else:
            # Synchronize to user-edited SecondaryColour in [V4+ Styles]
            st_hl = get_style_val(p, "SecondaryColour", "&H0000D4FF&")

        effective_pri_hex = spk_cfg.get("primary_color") or primary_color_hex
        if effective_pri_hex is not None:
            st_pri = hex_to_ass_color(effective_pri_hex, 1.0)
            set_style_val(p, "PrimaryColour", st_pri)
        else:
            st_pri = get_style_val(p, "PrimaryColour", "&H00FFFFFF&")

        effective_out_hex = spk_cfg.get("outline_color") or outline_color_hex
        if effective_out_hex is not None:
            st_out = hex_to_ass_color(effective_out_hex, 1.0)
            set_style_val(p, "OutlineColour", st_out)
        else:
            st_out = get_style_val(p, "OutlineColour", "&H00000000&")

        if outline_width is not None:
            set_style_val(p, "Outline", outline_width)
        if font_name is not None:
            set_style_val(p, "Fontname", font_name)
        if font_size is not None:
            set_style_val(p, "Fontsize", font_size)
        if bold is not None:
            set_style_val(p, "Bold", 1 if bold else 0)
        if italic is not None:
            set_style_val(p, "Italic", 1 if italic else 0)
        if margin_v is not None:
            set_style_val(p, "MarginV", margin_v)

        box_bg = hex_to_ass_color(box_bg_color_hex or "#00E5FF", box_opacity if box_opacity is not None else 0.85)
        box_font = hex_to_ass_color(box_font_color_hex or "#000000", 1.0)

        resolved_styles[st_name] = {
            "parts": p,
            "hl": st_hl,
            "pri": st_pri,
            "out": st_out,
            "box_bg": box_bg,
            "box_font": box_font,
        }

    for st_name, res in resolved_styles.items():
        if st_name in style_line_indices:
            joined_parts = ",".join(res["parts"])
            lines[style_line_indices[st_name]] = f"Style: {joined_parts}"

    def_res = resolved_styles.get(
        "Default",
        {
            "hl": "&H0000D4FF&",
            "pri": "&H00FFFFFF&",
            "out": "&H00000000&",
            "box_bg": "&H26FFE500&",
            "box_font": "&H00000000&",
        },
    )

    updated_lines = []
    for line in lines:
        if line.startswith("Dialogue:"):
            d_parts = line.split(",", 9)
            if len(d_parts) >= 10:
                d_start = parse_ass_timestamp(d_parts[1])
                line_cfg = resolve_styling_at_time(d_start, keyframes, config) if keyframes else config

                line_pos_x = pos_x
                line_pos_y = pos_y
                if line_cfg.get("pos_x_pct") is not None:
                    try:
                        line_pos_x = int(play_res_x * (float(line_cfg["pos_x_pct"]) / 100.0))
                    except Exception:
                        pass
                if line_cfg.get("pos_y_pct") is not None:
                    try:
                        line_pos_y = int(play_res_y * (float(line_cfg["pos_y_pct"]) / 100.0))
                    except Exception:
                        pass

                d_style = d_parts[3].strip()
                st_info = resolved_styles.get(d_style, def_res)
                target_hl = hex_to_ass_color(line_cfg["highlight_color"], 1.0) if line_cfg.get("highlight_color") else st_info["hl"]
                target_pri = hex_to_ass_color(line_cfg["primary_color"], 1.0) if line_cfg.get("primary_color") else st_info["pri"]
                target_out = hex_to_ass_color(line_cfg["outline_color"], 1.0) if line_cfg.get("outline_color") else st_info["out"]
                target_box_bg = hex_to_ass_color(line_cfg["box_bg_color"], float(line_cfg.get("box_opacity", 0.85))) if line_cfg.get("box_bg_color") else st_info["box_bg"]
                target_box_font = hex_to_ass_color(line_cfg["box_font_color"], 1.0) if line_cfg.get("box_font_color") else st_info["box_font"]

                d_text = d_parts[9]

                if line_pos_y is not None:
                    d_text = re.sub(
                        r"\\pos\(\s*\d+\s*,\s*\d+\s*\)",
                        lambda _: f"\\pos({line_pos_x},{line_pos_y})",
                        d_text,
                    )

                def repl_active(match: re.Match) -> str:
                    tag1, word, tag2 = match.group(1), match.group(2), match.group(3)
                    new_tag1 = re.sub(r"\\c&H[0-9a-fA-F]{8}&", lambda _: f"\\c{target_hl}", tag1)
                    new_tag1 = re.sub(r"\\3c&H[0-9a-fA-F]{8}&", lambda _: f"\\3c{target_out}", new_tag1)
                    new_tag2 = re.sub(r"\\c&H[0-9a-fA-F]{8}&", lambda _: f"\\c{target_pri}", tag2)
                    new_tag2 = re.sub(r"\\3c&H[0-9a-fA-F]{8}&", lambda _: f"\\3c{target_out}", new_tag2)
                    if highlight_animation == "pop_zoom":
                        if "\\fscx" not in new_tag1:
                            new_tag1 = "\\fscx108\\fscy108" + new_tag1
                        if "\\fscx" not in new_tag2:
                            new_tag2 = "\\fscx100\\fscy100" + new_tag2
                    elif highlight_animation in ("none", "color"):
                        new_tag1 = re.sub(r"\\fscx\d+\\fscy\d+", "", new_tag1)
                        new_tag2 = re.sub(r"\\fscx\d+\\fscy\d+", "", new_tag2)
                    return f"{{{new_tag1}}}{word}{{{new_tag2}}}"

                pattern = r"\{([^}]*?\\c&H[0-9a-fA-F]{8}&[^}]*?)\}([^{]+)\{([^}]*?\\c&H[0-9a-fA-F]{8}&[^}]*?)\}"
                d_text = re.sub(pattern, repl_active, d_text)

                def repl_box(match: re.Match) -> str:
                    tag1, word, tag2 = match.group(1), match.group(2), match.group(3)
                    new_tag1 = re.sub(r"\\3c&H[0-9a-fA-F]{8}&", lambda _: f"\\3c{target_box_bg}", tag1)
                    new_tag1 = re.sub(r"\\c&H[0-9a-fA-F]{8}&", lambda _: f"\\c{target_box_font}", new_tag1)
                    return f"{{{new_tag1}}}{word}{{{tag2}}}"

                box_pattern = r"\{([^}]*?\\bord\d+[^}]*?\\3c&H[0-9a-fA-F]{8}&[^}]*?\\c&H[0-9a-fA-F]{8}&[^}]*?)\}([^{]+)(\{\\r[^}]*?\})"
                d_text = re.sub(box_pattern, repl_box, d_text)

                def repl_glow(match: re.Match) -> str:
                    tag1, word, tag2 = match.group(1), match.group(2), match.group(3)
                    new_tag1 = re.sub(r"\\3c&H[0-9a-fA-F]{8}&", lambda _: f"\\3c{target_hl}", tag1)
                    new_tag2 = re.sub(r"\\3c&H[0-9a-fA-F]{8}&", lambda _: f"\\3c{target_out}", tag2)
                    return f"{{{new_tag1}}}{word}{{{new_tag2}}}"

                glow_pattern = r"\{([^}]*?\\3c&H[0-9a-fA-F]{8}&\\bord4[^}]*?)\}([^{]+)(\{[^}]*?\\3c&H[0-9a-fA-F]{8}&\\bord\d+[^}]*?\})"
                d_text = re.sub(glow_pattern, repl_glow, d_text)

                d_parts[9] = d_text
                updated_lines.append(",".join(d_parts))
                continue

        updated_lines.append(line)

    return "\n".join(updated_lines) + ("\n" if ass_content.endswith("\n") else "")

