"""Negative values decide for log2; when the magnitude says linear, the page says so.

A linear intensity cannot be negative, so a reproducible share of negative
values (>= 0.1 %) makes the detector call the matrix log2 -- and it used to stop
there. A background-subtracted linear matrix with a handful of negative cells
was therefore treated as log2 without a word, and every log2 plot showed raw
intensities. The detection is unchanged (no new heuristic, no "undetermined"
state); the two existing tests now both run, and when they disagree the reason,
the annotation warning and the note under the scale checkbox say so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.annotation_processor import (
    detect_log2_transformed,
    log2_scale_hint,
    resolve_log2_state,
)

SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]


def _linear_with_negatives(negatives: int = 15, rows: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    values = np.power(2.0, rng.normal(22, 2, (rows, len(SAMPLES))))
    flat = values.ravel()
    flat[rng.choice(flat.size, negatives, replace=False)] = -100.0  # background subtraction
    frame = pd.DataFrame(flat.reshape(values.shape), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(rows)])
    return frame


def _log2_ratios(rows: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame(rng.normal(0, 1, (rows, len(SAMPLES))), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(rows)])
    return frame


def test_negatives_still_decide_for_log2_but_the_disagreement_is_named() -> None:
    detection = detect_log2_transformed(_linear_with_negatives(), SAMPLES)
    assert detection.is_log2_transformed is True  # unchanged call
    assert detection.conflict is True
    assert "negative" in detection.reason and "linear intensities" in detection.reason
    assert "set it explicitly" in detection.reason


def test_the_annotation_warning_starts_with_the_check_request() -> None:
    state, auto_detected, warning = resolve_log2_state(_linear_with_negatives(), SAMPLES, None)
    assert state is True and auto_detected is True
    assert warning is not None and warning.startswith("Check the data scale. ")
    assert "looks like linear intensities" in warning


def test_the_note_under_the_checkbox_says_what_to_do() -> None:
    hint = log2_scale_hint(_linear_with_negatives(), SAMPLES)
    assert hint is not None
    assert hint.startswith("0.1% of the values are negative")
    assert "untick it if these are linear values" in hint


def test_log2_ratios_with_negatives_raise_no_conflict() -> None:
    """Centred data: negatives and a small magnitude agree on log2."""
    detection = detect_log2_transformed(_log2_ratios(), SAMPLES)
    assert detection.is_log2_transformed is True and detection.conflict is False
    assert detection.reason == "selected sample values include a reproducible negative-value signal"
    _, _, warning = resolve_log2_state(_log2_ratios(), SAMPLES, None)
    assert warning is not None and not warning.startswith("Check")
    assert log2_scale_hint(_log2_ratios(), SAMPLES) is None


def test_an_explicit_choice_is_not_second_guessed() -> None:
    state, auto_detected, warning = resolve_log2_state(_linear_with_negatives(), SAMPLES, False)
    assert (state, auto_detected, warning) == (False, False, None)
