from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import ConditionAssignment
from app.services.annotation_processor import (
    compute_annotation,
    compute_annotation_from_metadata,
)

WT = [f"WT_{i}" for i in range(1, 6)]
KO = [f"KO_{i}" for i in range(1, 6)]
UNPARSEABLE = "could not be read as numbers"
DROPPED = "not a column in this dataset"


def _frame(decimal_comma_in: str | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(rng.normal(20, 1.2, (400, 10)), columns=WT + KO)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(400)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(400)])
    if decimal_comma_in:
        frame[decimal_comma_in] = [
            f"{value:.3f}".replace(".", ",") for value in frame[decimal_comma_in]
        ]
    return frame


def _via_conditions(frame: pd.DataFrame, wt=None, ko=None):
    return compute_annotation(
        frame,
        [
            ConditionAssignment(name="WT", columns=wt or WT),
            ConditionAssignment(name="KO", columns=ko or KO),
        ],
        True,
        3,
        "overall",
    )


def _via_metadata(frame: pd.DataFrame, wt=None, ko=None):
    samples = (wt or WT) + (ko or KO)
    metadata = pd.DataFrame(
        {"sample": samples, "condition": ["WT"] * len(wt or WT) + ["KO"] * len(ko or KO)}
    )
    return compute_annotation_from_metadata(frame, metadata, True, 3, "overall")


PATHS = {"conditions": _via_conditions, "metadata": _via_metadata}


@pytest.mark.parametrize("path", sorted(PATHS))
def test_clean_data_raises_no_data_quality_warning(path: str) -> None:
    result = PATHS[path](_frame())
    noise = [w for w in result.warnings if UNPARSEABLE in w or DROPPED in w]
    assert not noise, noise
    assert len(result.metadata) == 10


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_locale_mangled_column_is_reported(path: str) -> None:
    result = PATHS[path](_frame(decimal_comma_in="WT_3"))
    hits = [w for w in result.warnings if UNPARSEABLE in w]
    assert hits, (
        f"the {path} annotation path silently discarded an unreadable column; "
        f"warnings were {result.warnings}"
    )
    assert "WT_3" in hits[0]


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_sample_is_never_lost_without_saying_so(path: str) -> None:
    typo = [c if c != "WT_3" else "WT_3 " for c in WT]
    result = PATHS[path](_frame(), wt=typo)
    annotated = len(result.metadata)
    if annotated == 10:
        return
    assert [w for w in result.warnings if DROPPED in w], (
        f"the {path} path annotated {annotated} of 10 samples and said nothing; "
        f"a 5-vs-5 design silently became {annotated - 5}-vs-5. "
        f"warnings were {result.warnings}"
    )


def test_the_two_paths_agree_on_an_unreadable_column() -> None:
    kinds = {
        name: {
            marker
            for marker in (UNPARSEABLE, DROPPED)
            if any(marker in w for w in run(_frame(decimal_comma_in="WT_3")).warnings)
        }
        for name, run in PATHS.items()
    }
    assert kinds["conditions"] == kinds["metadata"], (
        f"the two annotation paths disagree about the same corrupt file: {kinds}"
    )


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_trailing_space_is_repaired_not_dropped(path: str) -> None:
    typo = [c if c != "WT_3" else "WT_3 " for c in WT]
    result = PATHS[path](_frame(), wt=typo)
    assert len(result.metadata) == 10, (
        f"the {path} path lost a sample to a trailing space; copying a header out "
        f"of Excel picks one up easily and a 5-vs-5 design becomes 4-vs-5"
    )
    assert not [w for w in result.warnings if DROPPED in w], (
        "nothing was lost, so nothing should be reported as dropped"
    )


@pytest.mark.parametrize("path", sorted(PATHS))
def test_a_column_that_does_not_exist_is_still_reported(path: str) -> None:
    absent = [c if c != "WT_3" else "NOT_A_COLUMN" for c in WT]
    result = PATHS[path](_frame(), wt=absent)
    assert len(result.metadata) == 9
    assert [w for w in result.warnings if DROPPED in w], (
        f"the {path} path dropped a sample that matches nothing and said nothing; "
        f"whitespace tolerance must not swallow a genuine typo"
    )


def test_a_column_whose_name_really_contains_spaces_still_matches() -> None:
    frame = _frame()
    frame = frame.rename(columns={"WT_3": " WT 3 "})
    conditions = [c if c != "WT_3" else " WT 3 " for c in WT]
    assert len(_via_conditions(frame, wt=conditions).metadata) == 10
