from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

SAMPLES = [f"s{i}" for i in range(6)]
OFFSETS = np.array([0.0, 1.2, -0.9, 0.6, -1.5, 0.3])


def _notebook():
    spec = importlib.util.spec_from_file_location(
        "_nb_guards", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nb_guards"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def notebook():
    return _notebook()


def _frame(n_features: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    values = rng.normal(20.0, 2.0, (n_features, len(SAMPLES))) + OFFSETS
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n_features)])
    return frame


def _meta() -> pd.DataFrame:
    return pd.DataFrame({"sample": SAMPLES, "condition": ["a"] * 3 + ["b"] * 3})


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalize_data_accepts_a_metadata_frame(notebook, method: str) -> None:
    frame = _frame()
    from_meta = notebook.normalize_data(frame.copy(), _meta(), method)[SAMPLES].to_numpy()
    from_list = notebook.normalize_data(frame.copy(), SAMPLES, method)[SAMPLES].to_numpy()
    assert np.allclose(from_meta, from_list, equal_nan=True), (
        "normalize_data is the only public function whose second argument is not a "
        "metadata frame; passing meta must normalize, not return the input unchanged"
    )


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalize_data_actually_changes_the_data(notebook, method: str) -> None:
    frame = _frame()
    before = frame[SAMPLES].median().to_numpy().std()
    after = notebook.normalize_data(frame.copy(), _meta(), method)[SAMPLES].median().to_numpy().std()
    assert before > 0.5, "fixture lost its loading offsets"
    assert after < before / 10, (
        f"sample-median spread went {before:.4f} -> {after:.4f}; the call returned "
        "something that was not normalized"
    )


def test_normalize_data_rejects_columns_that_match_nothing(notebook) -> None:
    with pytest.raises(ValueError, match="nothing would be normalized"):
        notebook.normalize_data(_frame(20), ["not_a_column"], "median")


def test_normalize_data_rejects_a_partial_match(notebook) -> None:
    with pytest.raises(ValueError, match="not in the data"):
        notebook.normalize_data(_frame(20), SAMPLES + ["not_a_column"], "median")


def test_normalize_data_says_so_when_metadata_has_no_sample_column(notebook) -> None:
    with pytest.raises(ValueError, match="'sample' column"):
        notebook.normalize_data(_frame(20), pd.DataFrame({"run": SAMPLES}), "median")


def test_requesting_no_normalization_is_still_a_no_op(notebook) -> None:
    frame = _frame(20)
    pd.testing.assert_frame_equal(
        notebook.normalize_data(frame.copy(), ["not_a_column"], "none"), frame
    )


def _dup_meta() -> pd.DataFrame:
    meta = _meta()
    return pd.concat([meta, meta[meta["condition"] == "b"]], ignore_index=True)


@pytest.mark.parametrize(
    "call",
    [
        "filter_data",
        "volcano_data_f",
        "anova_data_f",
        "impute_values",
    ],
)
def test_duplicated_metadata_samples_are_refused(notebook, call: str) -> None:
    frame = _frame()
    runners = {
        "filter_data": lambda m: notebook.filter_data(frame.copy(), m, 2),
        "volcano_data_f": lambda m: notebook.volcano_data_f(frame.copy(), m, "a", "b"),
        "anova_data_f": lambda m: notebook.anova_data_f(frame.copy(), m),
        "impute_values": lambda m: notebook.impute_values(frame.copy(), m),
    }
    runners[call](_meta())
    with pytest.raises(ValueError, match="more than once"):
        runners[call](_dup_meta())


def test_the_duplicate_message_names_the_offending_samples(notebook) -> None:
    with pytest.raises(ValueError) as excinfo:
        notebook.volcano_data_f(_frame().copy(), _dup_meta(), "a", "b")
    message = str(excinfo.value)
    assert "s3" in message or "s4" in message or "s5" in message
    assert "exactly once" in message


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"method": "percentage", "percentage": 500}, "between 0 and 100"),
        ({"method": "percentage", "percentage": -10}, "between 0 and 100"),
        ({"method": "percentage", "percentage": "many"}, "must be a number"),
        ({"num": -5}, "zero or greater"),
        ({"num": None}, "whole number"),
    ],
)
def test_filter_thresholds_that_cannot_describe_completeness_are_refused(
    notebook, kwargs: dict, match: str
) -> None:
    num = kwargs.pop("num", 1)
    with pytest.raises(ValueError, match=match):
        notebook.filter_data(_frame(20).copy(), _meta(), num, "overall", **kwargs)


def test_a_filter_that_keeps_nothing_is_allowed(notebook) -> None:
    kept = notebook.filter_data(_frame(20).copy(), _meta(), 99, "overall")
    assert len(kept) == 0, "an unreachable-but-meaningful threshold should filter, not raise"


def test_the_strictest_legitimate_percentage_is_allowed(notebook) -> None:
    kept = notebook.filter_data(
        _frame(20).copy(), _meta(), 1, "overall", method="percentage", percentage=100
    )
    assert len(kept) == 20


@pytest.mark.parametrize("scope", ["per group", "per_group", "PER_GROUP"])
def test_scope_spellings_agree_with_the_backend(notebook, scope: str) -> None:
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.functions import filter_data as backend_filter

    frame, meta = _frame(20), _meta()
    from_pip = len(notebook.filter_data(frame.copy(), meta, 2, scope))
    from_backend = len(backend_filter(frame.copy(), meta, 2, scope))
    assert from_pip == from_backend, (
        f"scope {scope!r} kept {from_pip} rows in the package and {from_backend} in the "
        "backend; the same spelling must mean the same thing in both"
    )
