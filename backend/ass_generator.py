# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Advanced SubStation Alpha (ASS) subtitle generator.

Synthesizes SSA/ASS v4+ subtitle scripts with karaoke-style active word
highlighting, custom typography, positional anchoring, bounding badge styling,
and responsive multi-line layout algorithms.
"""

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


def chunk_words_into_blocks(
    words: list[dict[str, Any]],
    max_lines: int = 1,
    max_chars_per_line: int = 32,
    max_gap_seconds: float = 0.6,
) -> list[list[list[dict[str, Any]]]]:
    """Partition a continuous sequence of timed words into readable subtitle blocks.

    Breaks streams based on natural speech pauses, punctuation boundaries,
    line character limits, and maximum lines per visual subtitle block.

    Args:
        words: List of aligned word dictionaries containing 'word', 'start', and 'end'.
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

    for w in words:
        word_text = w.get("word", "").strip()
        if not word_text:
            continue

        start_time = w.get("start", 0.0)
        end_time = w.get("end", start_time + 0.1)

        # Check for natural break: long pause or sentence ending punctuation
        pause_break = last_end_time is not None and (start_time - last_end_time) > max_gap_seconds

        # Check if line would exceed char limit
        would_exceed_line = (current_line_len + len(word_text) + (1 if current_line_len > 0 else 0)) > max_chars_per_line

        if pause_break or (would_exceed_line and current_line_words):
            current_block_lines.append(current_line_words)
            current_line_words = []
            current_line_len = 0

            if len(current_block_lines) >= max_lines or pause_break:
                blocks.append(current_block_lines)
                current_block_lines = []

        current_line_words.append(w)
        current_line_len += len(word_text) + (1 if current_line_len > 0 else 0)
        last_end_time = end_time

        # If word ends with strong sentence terminator, break block naturally
        if word_text.endswith((".", "!", "?")) and current_line_len >= (max_chars_per_line * 0.6):
            current_block_lines.append(current_line_words)
            blocks.append(current_block_lines)
            current_block_lines = []
            current_line_words = []
            current_line_len = 0

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

    # ASS Color strings
    ass_primary = hex_to_ass_color(primary_color_hex, 1.0)
    ass_outline = hex_to_ass_color(outline_color_hex, 1.0)
    ass_highlight = hex_to_ass_color(highlight_color_hex, 1.0)
    ass_box_bg = hex_to_ass_color(box_bg_color_hex, box_opacity)
    ass_box_font = hex_to_ass_color(box_font_color_hex, 1.0)

    # Determine border style
    border_style = 3 if (highlight_style == "box" and box_type == "block") else 1
    back_color = ass_box_bg if border_style == 3 else "&H80000000&"

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
Style: Default,{font_name},{font_size},{ass_primary},&H000000FF&,{ass_outline},{back_color},{bold},{italic},0,0,100,100,0,0,{border_style},{outline_width},0,2,{margin_lr},{margin_lr},{margin_v},1
Style: HighlightBox,{font_name},{font_size},{ass_box_font},&H000000FF&,{ass_box_bg},{ass_box_bg},{bold},{italic},0,0,100,100,0,0,3,6,0,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    all_words = []
    segments = whisper_result.get("segments", [])
    for seg in segments:
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
            slices.append({
                "block": block,
                "block_words": block_words,
                "active_word": w,
                "w_idx": w_idx,
                "is_last_in_block": (w_idx == len(block_words) - 1),
                "is_first_in_block": (w_idx == 0),
                "b_idx": b_idx,
            })

    if not slices:
        return header

    event_lines = []
    prev_event_end = 0.0

    for k in range(len(slices)):
        curr = slices[k]
        raw_start = float(curr["active_word"]["start"])

        if k == 0:
            start_time = raw_start
        else:
            start_time = max(raw_start, prev_event_end)

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
                    if highlight_style == "color":
                        line_parts.append(
                            f"{{{scale_tag}\\c{ass_highlight}\\3c{ass_outline}}}{raw_word}{{{scale_reset}\\c{ass_primary}\\3c{ass_outline}}}"
                        )
                    elif highlight_style == "box":
                        if box_type == "word":
                            line_parts.append(
                                f"{{{scale_tag}\\bord8\\3c{ass_box_bg}\\c{ass_box_font}}}{raw_word}{{{scale_reset}\\rDefault}}"
                            )
                        else:
                            line_parts.append(
                                f"{{{scale_tag}\\c{ass_highlight}}}{raw_word}{{{scale_reset}\\c{ass_primary}}}"
                            )
                else:
                    line_parts.append(raw_word)
            rendered_lines.append(" ".join(line_parts))

        dialogue_text = "\\N".join(rendered_lines)
        pos_tag = f"{{\\an2\\pos({pos_x},{pos_y})}}"

        event_lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{pos_tag}{dialogue_text}")

    return header + "\n".join(event_lines) + "\n"
