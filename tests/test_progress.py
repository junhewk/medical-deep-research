"""Tests for the monotonic ProgressTracker."""

from __future__ import annotations

import random

from medical_deep_research.progress import (
    PHASE_FLOORS,
    PHASE_ORDER,
    ProgressTracker,
)


def test_floor_applied_on_first_entry_only() -> None:
    tracker = ProgressTracker()
    label, percent = tracker.enter("searching")
    assert label == "searching"
    assert percent == PHASE_FLOORS["searching"]

    # Move forward, then come back: no floor re-application, percent holds.
    tracker.enter("verifying")
    held = tracker.percent
    label, percent = tracker.enter("searching")
    assert label == "searching (pass 2)"
    assert percent == held


def test_revisit_label_increments_only_on_backward_reentry() -> None:
    tracker = ProgressTracker()
    tracker.enter("searching")
    tracker.enter("searching")  # same phase again: still pass 1
    assert tracker.phase_label("searching") == "searching"

    tracker.enter("ranking")
    tracker.enter("searching")
    assert tracker.phase_label("searching") == "searching (pass 2)"
    tracker.enter("ranking")
    assert tracker.phase_label("ranking") == "ranking (pass 2)"


def test_advance_is_monotonic_and_capped() -> None:
    tracker = ProgressTracker()
    previous = 0
    for phase in ("planning", "searching", "ranking", "verifying", "synthesizing"):
        tracker.enter(phase)
        for _ in range(20):
            value = tracker.advance(phase)
            assert value >= previous
            assert value <= 97
            previous = value


def test_advance_after_rewind_keeps_rising_slowly() -> None:
    tracker = ProgressTracker()
    tracker.enter("searching")
    tracker.enter("ranking")
    tracker.enter("verifying")
    before = tracker.advance("verifying")

    tracker.enter("searching")  # rewind
    assert tracker.percent == before
    after = tracker.advance("searching")
    assert before <= after <= before + 5  # crawls, no jump and no regression


def test_random_walk_never_decreases() -> None:
    rng = random.Random(42)
    tracker = ProgressTracker()
    previous = 0
    phases = [p for p in PHASE_ORDER if p not in ("init", "complete")]
    for _ in range(500):
        phase = rng.choice(phases)
        if rng.random() < 0.5:
            _, value = tracker.enter(phase)
        else:
            value = tracker.advance(phase)
        assert value >= previous
        assert value <= 97
        previous = value


def test_complete_reaches_exactly_100() -> None:
    tracker = ProgressTracker()
    tracker.enter("synthesizing")
    for _ in range(50):
        assert tracker.advance("synthesizing") <= 97
    assert tracker.complete() == 100
    # advance after completion stays at 100
    assert tracker.advance("synthesizing") == 100


def test_unknown_phase_is_not_a_backward_jump() -> None:
    tracker = ProgressTracker()
    tracker.enter("verifying")
    held = tracker.percent
    label, percent = tracker.enter("mystery-phase")
    assert label == "mystery-phase"
    assert percent == held
