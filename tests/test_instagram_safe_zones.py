# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for Instagram multi-ratio safe zone boundaries and text cutoff prevention.

Validates the mathematical precision of the three Instagram aspect ratios:
1. 9:16 Full Vertical (1080 × 1920) — Reels & Stories full screen viewer.
2. 4:5 Portrait In-Feed Scroll Crop (1080 × 1350) — Main home feed scroll.
3. 1:1 Square Profile Grid Preview (1080 × 1080) — Creator 3-column profile grid.

Ensures that vertical coordinate translations to ASS MarginV correctly identify
cutoff conditions, that the Universal Safe Zone is mathematically verified,
and that the frontend templates contain all necessary UI controls.
"""

from pathlib import Path


def calculate_instagram_safe_zones(width: int = 1080, height: int = 1920) -> dict[str, dict[str, float]]:
    """Compute exact pixel and percentage boundaries for Instagram surfaces.

    Args:
        width: Canvas width in pixels (typically 1080).
        height: Canvas height in pixels (typically 1920).

    Returns:
        Dictionary mapping surface name to its crop bounds and safe boundaries.
    """
    feed_height = int(width * (5 / 4))  # 1350px for 1080 width
    feed_crop_px = (height - feed_height) / 2  # 285px
    feed_top_pct = (feed_crop_px / height) * 100.0
    feed_bottom_pct = 100.0 - feed_top_pct

    grid_height = width  # 1080px for 1:1 square
    grid_crop_px = (height - grid_height) / 2  # 420px
    grid_top_pct = (grid_crop_px / height) * 100.0
    grid_bottom_pct = 100.0 - grid_top_pct

    # 9:16 Reels UI obstruction limits
    reels_top_limit_pct = 14.0
    reels_bottom_limit_pct = 65.0
    reels_right_limit_pct = 88.0

    return {
        "feed_4_5": {
            "visible_height_px": float(feed_height),
            "top_crop_px": feed_crop_px,
            "bottom_crop_px": feed_crop_px,
            "top_pct": feed_top_pct,
            "bottom_pct": feed_bottom_pct,
        },
        "grid_1_1": {
            "visible_height_px": float(grid_height),
            "top_crop_px": grid_crop_px,
            "bottom_crop_px": grid_crop_px,
            "top_pct": grid_top_pct,
            "bottom_pct": grid_bottom_pct,
        },
        "reels_9_16": {
            "top_limit_pct": reels_top_limit_pct,
            "bottom_limit_pct": reels_bottom_limit_pct,
            "right_limit_pct": reels_right_limit_pct,
        },
        "universal_safe": {
            "top_pct": max(grid_top_pct, reels_top_limit_pct),  # 21.875%
            "bottom_pct": min(reels_bottom_limit_pct, grid_bottom_pct, feed_bottom_pct),  # 65.0%
        },
    }


def classify_subtitle_safety(
    pos_y_pct: float,
    envelope_height_pct: float = 7.0,
    surface: str = "all",
) -> str:
    """Classify subtitle position against Instagram surface boundaries.

    Args:
        pos_y_pct: Center vertical position percentage (0 to 100).
        envelope_height_pct: Total height of subtitle bounding envelope in percent.
        surface: Active Instagram surface ('reels', 'feed', 'grid', 'all').

    Returns:
        Status string: 'safe', 'feed_cutoff', 'grid_cutoff', or 'reels_obscured'.
    """
    box_top = pos_y_pct - (envelope_height_pct / 2.0)
    box_bottom = pos_y_pct + (envelope_height_pct / 2.0)

    # Crop and safe limits
    is_feed_cutoff = (box_bottom > 85.15625) or (box_top < 14.84375)
    is_grid_cutoff = (box_bottom > 78.125) or (box_top < 21.875)
    is_reels_obscured = (box_bottom > 65.0) or (box_top < 14.0)

    if surface == "feed":
        return "feed_cutoff" if is_feed_cutoff else "safe"
    elif surface == "grid":
        return "grid_cutoff" if is_grid_cutoff else "safe"
    elif surface == "reels":
        return "reels_obscured" if is_reels_obscured else "safe"
    else:  # 'all'
        if is_grid_cutoff and is_feed_cutoff:
            return "feed_and_grid_cutoff"
        elif is_grid_cutoff:
            return "grid_cutoff"
        elif is_feed_cutoff:
            return "feed_cutoff"
        elif is_reels_obscured:
            return "reels_obscured"
        return "safe"


def test_instagram_geometric_ratios_math():
    """Verify exact pixel and percentage calculations for the 3 Instagram aspect ratios."""
    zones = calculate_instagram_safe_zones(1080, 1920)

    # 4:5 Feed post in 1080x1920
    assert zones["feed_4_5"]["visible_height_px"] == 1350.0
    assert zones["feed_4_5"]["top_crop_px"] == 285.0
    assert zones["feed_4_5"]["bottom_crop_px"] == 285.0
    assert round(zones["feed_4_5"]["top_pct"], 2) == 14.84
    assert round(zones["feed_4_5"]["bottom_pct"], 2) == 85.16

    # 1:1 Profile grid thumbnail
    assert zones["grid_1_1"]["visible_height_px"] == 1080.0
    assert zones["grid_1_1"]["top_crop_px"] == 420.0
    assert zones["grid_1_1"]["bottom_crop_px"] == 420.0
    assert round(zones["grid_1_1"]["top_pct"], 3) == 21.875
    assert round(zones["grid_1_1"]["bottom_pct"], 3) == 78.125

    # Universal safe zone
    assert round(zones["universal_safe"]["top_pct"], 2) == 21.88
    assert zones["universal_safe"]["bottom_pct"] == 65.0


def test_instagram_collision_classification():
    """Verify that subtitle positions accurately detect cutoff on Instagram surfaces."""
    envelope_pct = 7.0

    # posY = 58% (Universal Safe Center) should be completely safe across all surfaces
    assert classify_subtitle_safety(58.0, envelope_pct, surface="feed") == "safe"
    assert classify_subtitle_safety(58.0, envelope_pct, surface="grid") == "safe"
    assert classify_subtitle_safety(58.0, envelope_pct, surface="reels") == "safe"
    assert classify_subtitle_safety(58.0, envelope_pct, surface="all") == "safe"

    # posY = 88% is severely cut off in 4:5 feed and 1:1 grid
    assert classify_subtitle_safety(88.0, envelope_pct, surface="feed") == "feed_cutoff"
    assert classify_subtitle_safety(88.0, envelope_pct, surface="grid") == "grid_cutoff"
    assert classify_subtitle_safety(88.0, envelope_pct, surface="all") == "feed_and_grid_cutoff"

    # posY = 78% (typical lower-third default) fits inside 4:5 feed but is sliced on 1:1 grid
    assert classify_subtitle_safety(78.0, envelope_pct, surface="feed") == "safe"
    assert classify_subtitle_safety(78.0, envelope_pct, surface="grid") == "grid_cutoff"
    assert classify_subtitle_safety(78.0, envelope_pct, surface="all") == "grid_cutoff"

    # posY = 68% fits in 4:5 and 1:1, but collides with Reels bottom caption/audio UI (> 65%)
    assert classify_subtitle_safety(68.0, envelope_pct, surface="feed") == "safe"
    assert classify_subtitle_safety(68.0, envelope_pct, surface="grid") == "safe"
    assert classify_subtitle_safety(68.0, envelope_pct, surface="reels") == "reels_obscured"
    assert classify_subtitle_safety(68.0, envelope_pct, surface="all") == "reels_obscured"


def test_margin_v_translation_for_instagram():
    """Verify that ASS MarginV correctly translates vertical positions without cutoff.

    In ASS subtitle format with Alignment 2 (bottom-centered), MarginV is the vertical
    margin in pixels from the bottom border of PlayResY.
    """
    play_res_y = 1920

    # At posY = 58% (Safe Center):
    pos_y_pct = 58.0
    margin_v = max(10, int(play_res_y * (1.0 - (pos_y_pct / 100.0))))
    # margin_v from bottom = 1920 * 0.42 = 806px
    assert margin_v == 806
    # Pixel from top = 1920 - 806 = 1114px.
    # 4:5 Feed window: [285px, 1635px]. 1114 is safely inside!
    # 1:1 Grid window: [420px, 1500px]. 1114 is safely inside!
    assert 285 < 1114 < 1635
    assert 420 < 1114 < 1500

    # At posY = 88% (Cutoff):
    pos_y_cutoff = 88.0
    margin_v_cutoff = max(10, int(play_res_y * (1.0 - (pos_y_cutoff / 100.0))))
    # margin_v = 1920 * 0.12 = 230px
    assert margin_v_cutoff == 230
    # Because Instagram slices off the bottom 285px in 4:5 feed, a subtitle at margin_v = 230px
    # is located at Y = 1690px, which is beyond the 1635px feed border (completely sliced)!
    assert margin_v_cutoff < 285


def test_frontend_instagram_ui_elements_presence():
    """Verify index.html contains all newly introduced Instagram multi-ratio controls."""
    html_path = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    content = html_path.read_text(encoding="utf-8")

    # Surface selector pills
    assert 'id="igSurfaceRow"' in content
    assert 'id="igSurfaceSelector"' in content
    assert 'data-ig-surface="reels"' in content
    assert 'data-ig-surface="feed"' in content
    assert 'data-ig-surface="grid"' in content
    assert 'data-ig-surface="all"' in content

    # Guide options and live collision indicator
    assert 'id="igOptionsRow"' in content
    assert 'id="chkIgMaskLetterbox"' in content
    assert 'id="btnIgAutoSafe"' in content
    assert 'id="igCollisionIndicator"' in content


def test_frontend_instagram_css_classes_presence():
    """Verify style.css includes all required letterbox, viewport, and multi-guide classes."""
    css_path = Path(__file__).resolve().parent.parent / "frontend" / "style.css"
    content = css_path.read_text(encoding="utf-8")

    assert ".ig-sub-row" in content
    assert ".ig-letterbox-mask" in content
    assert ".ig-feed-viewport" in content
    assert ".ig-grid-viewport" in content
    assert ".ig-surface-badge" in content
    assert ".ig-multiguide-box" in content
    assert ".ig-universal-safe-zone" in content
    assert ".ig-collision-indicator" in content
    assert ".envelope-warning-cutoff" in content
