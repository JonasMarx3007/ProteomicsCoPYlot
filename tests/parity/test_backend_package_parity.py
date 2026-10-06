from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from app.services import functions as backend
from proteomicscopylot import notebook_functions as notebook

SAMPLES = [f"Ctrl_{i}" for i in range(1, 4)] + [f"Treat_{i}" for i in range(1, 4)]
MODES = [("per_group", "per group"), ("in_at_least_one_group", "in at least one group"), ("overall", "overall")]


def _meta() -> pd.DataFrame:
    return pd.DataFrame({"sample": SAMPLES, "condition": ["Ctrl"] * 3 + ["Treat"] * 3})


def _frame(seed: int = 5, missing: float = 0.25) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = rng.normal(20.0, 1.5, (120, len(SAMPLES)))
    values[rng.random(values.shape) < missing] = np.nan
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(len(frame))])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(len(frame))])
    return frame


@pytest.mark.parametrize("backend_mode,package_mode", MODES)
@pytest.mark.parametrize("min_present", [1, 2, 3])
def test_filtering_agrees_between_the_backend_and_the_package(
    backend_mode: str, package_mode: str, min_present: int
) -> None:
    frame, meta = _frame(), _meta()
    from_backend = backend.filter_data(frame.copy(), meta, min_present, backend_mode)
    from_package = notebook.filter_data(frame.copy(), meta, min_present, package_mode)
    assert list(from_backend["ProteinNames"]) == list(from_package["ProteinNames"]), (
        f"mode {backend_mode!r} with min_present={min_present} kept "
        f"{len(from_backend)} features in the web app and {len(from_package)} in the "
        "package; the two implementations must select the same rows"
    )


@pytest.mark.parametrize("percentage", [0.0, 50.0, 100.0])
def test_percentage_filtering_agrees(percentage: float) -> None:
    frame, meta = _frame(), _meta()
    from_backend = backend.filter_data(
        frame.copy(), meta, 1, "per_group", "percentage", percentage
    )
    from_package = notebook.filter_data(
        frame.copy(), meta, 1, "per group", "percentage", percentage
    )
    assert list(from_backend["ProteinNames"]) == list(from_package["ProteinNames"])


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalization_agrees_between_the_backend_and_the_package(method: str) -> None:
    frame, meta = _frame(missing=0.0), _meta()
    from_backend = backend.normalize_data(frame.copy(), SAMPLES, method)[SAMPLES].to_numpy()
    from_package = notebook.normalize_data(frame.copy(), meta, method)[SAMPLES].to_numpy()
    worst = np.nanmax(np.abs(from_backend - from_package))
    assert worst < 1e-12, f"{method} normalization differs by {worst:.3e}"


def test_the_zero_convention_agrees() -> None:
    frame = pd.DataFrame({"a": [0.0, 1.0, np.inf, -np.inf, 5.0]})
    from_backend = backend.raw_zero_to_nan(frame.copy(), ["a"])["a"]
    from_package = notebook.raw_zero_to_nan(frame.copy(), ["a"])["a"]
    assert from_backend.isna().tolist() == from_package.isna().tolist(), (
        "zero and non-finite handling must match; the package coerced these long "
        "before the web app did, and an -inf that survives ingest passes the "
        "completeness filter as though it were a measurement"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_present": -5},
        {"method": "percentage", "min_percentage": 500.0},
        {"method": "percentage", "min_percentage": -10.0},
    ],
)
def test_both_implementations_refuse_the_same_impossible_thresholds(kwargs: dict) -> None:
    frame, meta = _frame(), _meta()
    min_present = kwargs.pop("min_present", 1)
    method = kwargs.pop("method", "at_least_n")
    percentage = kwargs.pop("min_percentage", 70.0)

    with pytest.raises(ValueError):
        backend.filter_data(frame.copy(), meta, min_present, "overall", method, percentage)
    with pytest.raises(ValueError):
        notebook.filter_data(frame.copy(), meta, min_present, "overall", method, percentage)


def test_both_implementations_refuse_metadata_that_repeats_a_sample() -> None:
    """Named for both, and for a while it only called one of them.

    A repeated sample is counted twice by every group-wise mean and variance, so
    the fold change is untouched and only the p-values move -- downward. The web
    app catches it at upload, but restore and direct service calls reach
    filter_data without passing through that.
    """
    frame, meta = _frame(), _meta()
    duplicated = pd.concat([meta, meta.iloc[[0]]], ignore_index=True)
    seen = []
    for implementation in (backend.filter_data, notebook.filter_data):
        with pytest.raises(ValueError, match="more than once") as excinfo:
            implementation(frame.copy(), duplicated, 1, "overall")
        seen.append(str(excinfo.value))
    assert seen[0] == seen[1], seen


@pytest.mark.parametrize(
    "kwargs,named",
    [
        ({"mode": "nonsense"}, ("per_group", "overall")),
        ({"method": "nonsense"}, ("at_least_n", "percentage")),
    ],
)
def test_both_implementations_refuse_an_unknown_filter_setting(
    kwargs: dict, named: tuple[str, ...]
) -> None:
    """An unrecognised mode or method must not fall through to a default.

    Both spellings are validated after normalisation, so "per group" and
    "per_group" are equally acceptable while a typo is not -- letting one through
    would silently change which features survive the completeness filter.
    """
    frame, meta = _frame(), _meta()
    mode = kwargs.get("mode", "overall")
    method = kwargs.get("method", "at_least_n")
    seen = []
    for implementation in (backend.filter_data, notebook.filter_data):
        with pytest.raises(ValueError) as excinfo:
            implementation(frame.copy(), meta, 1, mode, method)
        message = str(excinfo.value)
        assert all(value in message for value in named), message
        seen.append(message)
    # The same mistake must read the same in both. They diverged once -- the web
    # app said "mode", the package said "scope" -- which is the kind of drift a
    # user hits when moving a call from a notebook into the app.
    assert seen[0] == seen[1], seen


@pytest.mark.parametrize("spelling", ["per group", "per_group"])
def test_both_implementations_accept_either_spelling_of_a_mode(spelling: str) -> None:
    frame, meta = _frame(), _meta()
    assert len(backend.filter_data(frame.copy(), meta, 1, spelling)) > 0
    assert len(notebook.filter_data(frame.copy(), meta, 1, spelling)) > 0
