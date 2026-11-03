# SPDX-FileCopyrightText: 2026 Joel Gonzales <joelontheroad>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Permanent diarization benchmark suite across multi-speaker campaign reference media.

Enforces strict closed-loop quality gates:
1. Every candidate diarization implementation must be benchmarked simultaneously against:
   - win-win-parking-benefits-pgm-v1.3.wav (4 ground truth speakers)
   - win-win-pleasant-valley-v1.1.wav (4 ground truth speakers)
2. Speaker turn purity must be >= 95.0% on both files.
3. Obliterated speakers (speakers lost or merged into another speaker's cluster) must be 0.
4. Any heuristic or algorithm that improves one reference file while degrading the other
   is strictly rejected.
"""

from pathlib import Path

import pytest

from backend.diarizer import diarize_whisper_result


def _calculate_speaker_purity(diarized_speakers: list[str], ground_truth: list[str]) -> tuple[float, set[str], dict[str, dict[str, int]]]:
    """Calculate cluster purity percentage and identify any obliterated ground-truth speakers.

    Args:
        diarized_speakers: List of cluster tags assigned by diarizer for each segment.
        ground_truth: List of human ground-truth speaker names for each segment.

    Returns:
        Tuple of (purity_percentage, set_of_obliterated_speakers, confusion_dict).
    """
    clusters = set(diarized_speakers)
    gt_speakers = set(ground_truth)

    # Confusion matrix: cluster_id -> {gt_speaker: count}
    cluster_counts: dict[str, dict[str, int]] = {c: {} for c in clusters}
    for pred_c, true_s in zip(diarized_speakers, ground_truth):
        cluster_counts[pred_c][true_s] = cluster_counts[pred_c].get(true_s, 0) + 1

    correct_assignments = 0
    majority_gt_covered: set[str] = set()
    for c, counts in cluster_counts.items():
        if counts:
            best_spk, majority_count = max(counts.items(), key=lambda kv: kv[1])
            correct_assignments += majority_count
            majority_gt_covered.add(best_spk)

    purity = (correct_assignments / len(ground_truth)) * 100.0 if ground_truth else 0.0
    obliterated = gt_speakers - majority_gt_covered
    return purity, obliterated, cluster_counts


def test_diarization_benchmark_parking_benefits():
    """Benchmark win-win-parking-benefits-pgm-v1.3.wav: 27s solo monologue + 3 isolated soundbites."""
    audio_path = Path(
        "/mnt/joelg-docs/Personal/Politics/Katie Kam City Council District 9/katie-videos/Win-Win-Katie/Creative-Funding-Parking-Benefit-Districts/Rendered Movies/win-win-parking-benefits-pgm-v1.3.wav"
    )
    if not audio_path.exists():
        pytest.skip(f"Reference media not found at: {audio_path}")

    # Segments representing the entire 55s video
    segments = [
        {"start": 0.03, "end": 3.49, "text": "Hi, I'm Katie Cam and I'm running for Austin City Council District 9."},
        {"start": 3.51, "end": 14.00, "text": "We're here in West Campus and I'm standing next to a parking meter..."},
        {"start": 14.10, "end": 15.10, "text": "Let me tell you more about it."},
        {"start": 15.86, "end": 22.21, "text": "In parking benefit districts, 51% of the parking meter revenue goes towards improvements..."},
        {"start": 22.49, "end": 26.71, "text": "Here's the sticker indicating that parking meter revenue can go towards bike lanes."},
        {"start": 30.85, "end": 31.49, "text": "Street lights."},
        {"start": 35.17, "end": 35.75, "text": "Inventures."},
        {"start": 36.82, "end": 41.36, "text": "Parking benefit district revenue can be used to fix our sidewalks in West Campus."},
    ]
    ground_truth = [
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Diane Kearns-Osterweil",
        "Stephanie Bazan",
        "Jennifer Franklin",
    ]

    whisper_result = {"segments": [dict(s) for s in segments]}
    res, samples = diarize_whisper_result(str(audio_path), whisper_result, target_speakers=4)
    pred_speakers = [s["speaker"] for s in res["segments"]]

    purity, obliterated, confusion = _calculate_speaker_purity(pred_speakers, ground_truth)
    assert purity >= 95.0, f"Parking benefits speaker purity {purity:.1f}% fell below 95% threshold! Confusion: {confusion}"
    assert len(obliterated) == 0, f"Speakers were obliterated: {obliterated}! Confusion: {confusion}"
    assert len(set(pred_speakers)) == 4, f"Expected 4 distinct clusters, got {len(set(pred_speakers))}"
    assert len(samples) == 4, f"Expected 4 representative audio snippets, got {len(samples)}"


def test_diarization_benchmark_pleasant_valley():
    """Benchmark win-win-pleasant-valley-v1.1.wav: Parkland intro + multi-speaker board meeting."""
    audio_path = Path(
        "/mnt/joelg-docs/Personal/Politics/Katie Kam City Council District 9/katie-videos/Win-Win-Katie/Pleasant-Valley/win-win-pleasant-valley-v1.1.wav"
    )
    if not audio_path.exists():
        pytest.skip(f"Reference media not found at: {audio_path}")

    # Key segments spanning Katie Kam, Stephanie Bazan, Speaker 3, and Speaker 4
    segments = [
        {"start": 0.55, "end": 7.00, "text": "Hi, I'm Katie Kam and I'm running for Austin City Council District 9..."},
        {"start": 7.01, "end": 22.00, "text": "Country Club Creek Greenbelt Parkland..."},
        {"start": 22.67, "end": 33.50, "text": "The City of Austin is proposing a four-lane road..."},
        {"start": 39.03, "end": 48.00, "text": "Notice how there is nothing on the kiosk here..."},
        {"start": 52.24, "end": 59.50, "text": "If you come to this park, you have no idea that you're about to lose this parkland."},
        {"start": 59.94, "end": 63.88, "text": "Currently, South Pleasant Valley Road is two lanes approaching the parkland."},
        {"start": 64.80, "end": 80.69, "text": "If this is expanded to match the proposed four-lane road through the parkland..."},
        {"start": 87.40, "end": 95.13, "text": "Hi, Board Member Kearns-Osterweil, it's disappointing that only two people attended your open house..."},
    ]
    ground_truth = [
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Katie Kam",
        "Stephanie Bazan",
        "Speaker 3",
        "Speaker 4",
    ]

    whisper_result = {"segments": [dict(s) for s in segments]}
    res, samples = diarize_whisper_result(str(audio_path), whisper_result, target_speakers=4)
    pred_speakers = [s["speaker"] for s in res["segments"]]

    purity, obliterated, confusion = _calculate_speaker_purity(pred_speakers, ground_truth)
    assert purity >= 95.0, f"Pleasant Valley speaker purity {purity:.1f}% fell below 95% threshold! Confusion: {confusion}"
    assert len(obliterated) == 0, f"Speakers were obliterated: {obliterated}! Confusion: {confusion}"
    assert len(set(pred_speakers)) == 4, f"Expected 4 distinct clusters, got {len(set(pred_speakers))}"
    assert len(samples) == 4, f"Expected 4 representative audio snippets, got {len(samples)}"
