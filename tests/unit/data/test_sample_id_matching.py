from __future__ import annotations

from contextlib import ExitStack, contextmanager
from pathlib import Path

import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

import app.services.completeness_tools as ct
import app.services.peptide_tools as pt
from app.services.functions import extract_sample_id, sample_id_map

SEQUENCES = ["PEPTIDEK", "SEQVENCER", "AAAAAKPEPR", "LLLLLRAAKGGR"]

COLLIDING_RUNS = [
    f"20240110_HeLa_{condition}_{replicate:02d}.raw"
    for condition in ("ctrl", "treat")
    for replicate in (1, 2, 3)
]
DISTINCT_RUNS = [
    f"20240110_HeLa_{condition}_{number}.raw"
    for condition, number in zip(
        ["ctrl"] * 3 + ["treat"] * 3, ["01", "02", "03", "04", "05", "06"]
    )
]
CONDITIONS = [condition for condition in ("ctrl", "treat") for _ in range(3)]

CTRL_INTENSITY = 1000.0
TREAT_INTENSITY = 5.0


def _frame(runs: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "File.Name": run,
                "Modified.Sequence": sequence,
                "Stripped.Sequence": sequence,
                "Precursor.Quantity": (
                    CTRL_INTENSITY if "ctrl" in run else TREAT_INTENSITY
                ),
            }
            for run in runs
            for sequence in SEQUENCES
        ]
    )


def _patched(runs: list[str], sample_names: list[str]):
    frame = _frame(runs)
    meta = pd.DataFrame({"sample": sample_names, "condition": CONDITIONS})

    class _Store:
        empty = False

    _Store.frame = meta

    class _Annotation:
        metadata = meta

    return frame, meta, _Store(), _Annotation()


@contextmanager
def _peptide_environment(runs: list[str], sample_names: list[str]):
    frame, meta, store, annotation = _patched(runs, sample_names)
    with ExitStack() as stack:
        stack.enter_context(patch.object(pt, "get_peptide_frame", return_value=frame))
        stack.enter_context(patch.object(pt, "get_peptide_metadata", return_value=store))
        stack.enter_context(patch.object(pt, "get_current_dataset", return_value=None))
        yield frame, meta, annotation


def test_the_convention_that_breaks_id_extraction_is_real() -> None:
    assert extract_sample_id("20240110_HeLa_ctrl_01.raw") == "01"
    assert extract_sample_id("20240110_HeLa_treat_01.raw") == "01"


def test_unique_ids_map_cleanly() -> None:
    assert sample_id_map(DISTINCT_RUNS) == {
        "01": "20240110_HeLa_ctrl_01.raw",
        "02": "20240110_HeLa_ctrl_02.raw",
        "03": "20240110_HeLa_ctrl_03.raw",
        "04": "20240110_HeLa_treat_04.raw",
        "05": "20240110_HeLa_treat_05.raw",
        "06": "20240110_HeLa_treat_06.raw",
    }


def test_colliding_ids_raise_instead_of_picking_one() -> None:
    with pytest.raises(ValueError) as excinfo:
        sample_id_map(COLLIDING_RUNS)
    message = str(excinfo.value)
    assert "20240110_HeLa_ctrl_01.raw" in message, "the message must name the files"
    assert "20240110_HeLa_treat_01.raw" in message
    assert "'01'" in message


def test_a_repeated_name_is_not_a_collision() -> None:
    assert sample_id_map(["run_1.raw", "run_1.raw", "run_2.raw"]) == {
        "1": "run_1.raw",
        "2": "run_2.raw",
    }


def test_names_without_numbers_fall_back_to_the_whole_name() -> None:
    assert sample_id_map(["alpha", "beta"]) == {"alpha": "alpha", "beta": "beta"}


@pytest.mark.parametrize("runs", [DISTINCT_RUNS, COLLIDING_RUNS], ids=["distinct", "colliding"])
def test_exact_name_matching_never_needs_the_number_fallback(runs: list[str]) -> None:
    with _peptide_environment(runs, runs) as (frame, _, _annotation):
        meta = pt._prepare_metadata(frame, include_id=False)

    wide = (
        frame.pivot_table(
            index="File.Name",
            columns="Modified.Sequence",
            values="Precursor.Quantity",
            aggfunc="max",
        )
        .T.reset_index()
    )
    wide.columns = [str(column) for column in wide.columns]
    wide = wide.rename(
        columns=pt._sample_rename_map(wide.columns, meta, "Modified.Sequence")
    )

    columns = [name for name in meta["new_sample"] if name in wide.columns]
    assert len(columns) == 6, "a sample was lost"
    selected = wide[["Modified.Sequence", *columns]]
    assert not pd.Index(selected.columns).duplicated().any(), "duplicate column labels"
    assert selected.shape == (len(SEQUENCES), 7)

    for column in columns:
        expected = CTRL_INTENSITY if column.startswith("ctrl") else TREAT_INTENSITY
        assert (selected[column] == expected).all(), (
            f"{column} carries the other condition's data"
        )


@pytest.mark.parametrize(
    "plot", [pt.peptide_modification_plot, pt.peptide_missed_cleavage_plot]
)
@pytest.mark.parametrize("runs", [DISTINCT_RUNS, COLLIDING_RUNS], ids=["distinct", "colliding"])
def test_plots_render_when_names_match_exactly(plot, runs: list[str]) -> None:
    with _peptide_environment(runs, runs):
        assert len(plot()) > 0


FUZZY_NAMES = [
    f"{condition}_{replicate:02d}"
    for condition in ("ctrl", "treat")
    for replicate in (1, 2, 3)
]


@pytest.mark.parametrize(
    "plot", [pt.peptide_modification_plot, pt.peptide_missed_cleavage_plot]
)
def test_plots_refuse_ambiguous_fuzzy_matching(plot) -> None:
    with _peptide_environment(COLLIDING_RUNS, FUZZY_NAMES):
        with pytest.raises(ValueError, match="ambiguous"):
            plot()


def test_completeness_refuses_ambiguous_fuzzy_matching() -> None:
    frame, _, _, annotation = _patched(COLLIDING_RUNS, FUZZY_NAMES)
    with patch.object(pt, "get_annotation", return_value=annotation), patch.object(pt, "get_current_dataset", return_value=object()):
        with pytest.raises(ValueError, match="ambiguous"):
            ct._peptide_sample_columns(frame)


@pytest.mark.parametrize("runs", [DISTINCT_RUNS, COLLIDING_RUNS], ids=["distinct", "colliding"])
def test_completeness_keeps_every_run_when_names_match_exactly(runs: list[str]) -> None:
    frame, _, _, annotation = _patched(runs, runs)
    with patch.object(pt, "get_annotation", return_value=annotation), patch.object(pt, "get_current_dataset", return_value=object()):
        assert sorted(ct._peptide_sample_columns(frame)) == sorted(runs)


def test_completeness_still_matches_unambiguous_shortened_names() -> None:
    frame, _, _, annotation = _patched(
        DISTINCT_RUNS, [f"sample_{n}" for n in ("01", "02", "03", "04", "05", "06")]
    )
    with patch.object(pt, "get_annotation", return_value=annotation), patch.object(pt, "get_current_dataset", return_value=object()):
        assert sorted(ct._peptide_sample_columns(frame)) == sorted(DISTINCT_RUNS)


@pytest.mark.parametrize('builder_name', ['peptide_modification_plot', 'peptide_missed_cleavage_plot'])
def test_ai_uses_exact_sample_mapping_and_rejects_ambiguous_fallback(monkeypatch, builder_name):
    from app.services import ai_functions
    builder = getattr(ai_functions, builder_name)
    with _peptide_environment(COLLIDING_RUNS, COLLIDING_RUNS) as (frame, _, _):
        monkeypatch.setattr(ai_functions, 'get_peptide_frame', lambda: frame)
        # Observe the input to the actual shared counting routine, not just success text.
        name = '_peptide_modification_counts' if 'modification' in builder_name else '_peptide_missed_cleavage_summary'
        calculate = getattr(ai_functions, name)
        seen = []
        def capture(wide, **kwargs):
            samples = kwargs['sample_columns']
            assert len(samples) == 6 and len(set(samples)) == 6
            assert wide[samples[:3]].eq(CTRL_INTENSITY).all().all()
            assert wide[samples[3:]].eq(TREAT_INTENSITY).all().all()
            seen.append(True)
            return calculate(wide, **kwargs)
        monkeypatch.setattr(ai_functions, name, capture)
        result = builder()['data']['text']
        assert seen and 'status=error' not in result
    with _peptide_environment(COLLIDING_RUNS, FUZZY_NAMES):
        result = builder()['data']['text']
        assert 'ambiguous' in result and 'status=error' in result
