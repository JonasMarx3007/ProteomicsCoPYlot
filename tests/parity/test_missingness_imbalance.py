"""Median and quantile normalization warn when missingness differs strongly between samples.

Both methods use each sample's observed values. Missing values are mostly
low-abundance, so a sample that lost many of them has a higher observed median
and is shifted down. The bundled phosphosite report shows it: the five GRK
samples miss 20-31 % of sites against 5-6 % for WT, and after median centring
the sites measured in every sample sit 0.42 log2 lower in GRK. The check names
the samples, measures that shift and says when one condition carries it; the
backend, the pip package and the R package compute the same table and message.
"""
from __future__ import annotations

import subprocess
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]

from app.services import functions as backend  # noqa: E402

EXAMPLE = ROOT / "proteomicscopylot" / "example_data"
SITES = EXAMPLE / "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv"
SITE_META = EXAMPLE / "phospho_metadata_full.csv"
COLUMNS = ["sample", "condition", "missing_fraction", "reference_missing_fraction", "flagged",
           "complete_features", "complete_offset"]


def _rscript() -> str | None:
    try:
        from app.services.r_runtime import detect_r_runtime
    except Exception:
        return None
    runtime = detect_r_runtime()
    return str(runtime["executable"]) if runtime.get("available") else None


RSCRIPT = _rscript()


def _simulated(missing_b: float = 0.30, seed: int = 11) -> tuple[pd.DataFrame, pd.DataFrame]:
    """No true difference between A and B; B loses its lowest values to missingness."""
    rng = np.random.default_rng(seed)
    samples = ["A1", "A2", "A3", "B1", "B2", "B3"]
    base = rng.normal(22, 2.5, 400)
    values = {sample: base + rng.normal(0, 0.3, base.size) for sample in samples}
    for sample in samples:
        share = missing_b if sample.startswith("B") else 0.05
        column = values[sample].copy()
        column[column < np.quantile(column, share)] = np.nan
        values[sample] = column
    frame = pd.DataFrame({"Protein": [f"P{i}" for i in range(base.size)], **values})
    meta = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    return frame, meta


def _example() -> tuple[pd.DataFrame, pd.DataFrame]:
    meta = pd.read_csv(SITE_META)
    frame = pd.read_csv(SITES, sep="\t")
    samples = meta["sample"].astype(str).tolist()
    # The bundled report is already on a log2 scale (viewer_config.json:
    # log2_transform_phospho), so it is used as the app uses it.
    return frame[samples].apply(pd.to_numeric, errors="coerce"), meta


def test_a_condition_with_far_more_missing_values_is_flagged_with_its_shift() -> None:
    frame, meta = _simulated()
    with pytest.warns(UserWarning) as caught:
        normalized = notebook.normalize_data(frame, meta, "median")
    table = notebook.missingness_imbalance(normalized, meta)
    assert table.columns.tolist() == COLUMNS
    assert table.loc[table["flagged"], "sample"].tolist() == ["B1", "B2", "B3"]
    # With no true difference the complete features should sit together; median
    # centring on all observed values pushes B down instead.
    flagged_shift = table.loc[table["flagged"], "complete_offset"].mean() - table.loc[~table["flagged"], "complete_offset"].mean()
    assert flagged_shift < -0.3
    message = str(caught[0].message)
    assert message == notebook.missingness_imbalance_warning(table, "median")
    assert message.startswith("Missing values differ strongly between samples: 3 of 6 samples")
    assert "Median centering uses each sample's observed values" in message
    assert f"they sit {abs(flagged_shift):.2f} log2 below the other samples" in message
    assert "All of them are in condition B" in message


@pytest.mark.parametrize("method", ["none", "median", "quantile"])
def test_balanced_missingness_and_no_normalization_stay_quiet(method) -> None:
    balanced, meta = _simulated(missing_b=0.05)
    imbalanced, _ = _simulated()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        notebook.normalize_data(balanced, meta, method)
        if method == "none":
            notebook.normalize_data(imbalanced, meta, method)
    assert notebook.missingness_imbalance_warning(notebook.missingness_imbalance(balanced, meta), method) is None


def test_quantile_normalization_is_named_in_its_warning() -> None:
    frame, meta = _simulated()
    with pytest.warns(UserWarning, match="Quantile normalization uses each sample's observed values"):
        notebook.normalize_data(frame, meta, "quantile")


def test_the_threshold_is_ten_points_above_the_most_complete_sample() -> None:
    frame, meta = _simulated(missing_b=0.05)
    rows = len(frame)
    # A1 keeps its 5 %; B1 loses exactly 9 more points, B2 exactly 10 more.
    for sample, extra in (("B1", 0.09), ("B2", 0.10)):
        observed = frame[sample].dropna().sort_values().index[: int(round(extra * rows))]
        frame.loc[observed, sample] = np.nan
    table = notebook.missingness_imbalance(frame, meta)
    assert table.set_index("sample").loc[["B1", "B2"], "flagged"].tolist() == [False, True]


def test_too_few_complete_features_report_no_shift() -> None:
    frame, meta = _simulated()
    frame.loc[frame.index[:390], "A1"] = np.nan  # leaves at most 10 complete rows
    table = notebook.missingness_imbalance(frame, meta)
    assert table["complete_offset"].isna().all()
    message = notebook.missingness_imbalance_warning(table, "median")
    assert message is not None and "features measured in every sample" not in message


@pytest.mark.parametrize("source", ["simulated", "example"])
def test_backend_and_pip_agree(source) -> None:
    frame, meta = _simulated() if source == "simulated" else _example()
    normalized = backend.normalize_data(frame, meta, "median")
    expected = notebook.missingness_imbalance(normalized, meta)
    actual = backend.missingness_imbalance(normalized, meta)
    pd.testing.assert_frame_equal(actual, expected)
    assert backend.missingness_imbalance_warning(actual, "median") == notebook.missingness_imbalance_warning(expected, "median")


def test_the_bundled_phosphosites_show_the_grk_shift() -> None:
    log2, meta = _example()
    with pytest.warns(UserWarning) as caught:
        normalized = notebook.normalize_data(log2, meta, "median")
    table = notebook.missingness_imbalance(normalized, meta)
    assert set(table.loc[table["flagged"], "condition"]) == {"GRK"}
    assert table["flagged"].sum() == 5
    message = str(caught[0].message)
    assert "they sit 0.42 log2 below the other samples" in message
    assert "All of them are in condition GRK" in message


@pytest.mark.requires_r()
@pytest.mark.parametrize("source,method", [("simulated", "median"), ("simulated", "quantile"),
                                           ("example", "median"), ("simulated", "none")])
def test_r_matches_python(tmp_path, source, method) -> None:
    frame, meta = _simulated() if source == "simulated" else _example()
    frame.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    script = f"""
    suppressPackageStartupMessages(source("{(ROOT / 'proteomicscopylot' / 'notebook_functions.R').as_posix()}"))
    data <- read.csv("{(tmp_path / 'data.csv').as_posix()}", check.names = FALSE, stringsAsFactors = FALSE)
    meta <- read.csv("{(tmp_path / 'meta.csv').as_posix()}", check.names = FALSE, stringsAsFactors = FALSE)
    caught <- character()
    normalized <- withCallingHandlers(
      normalize_data(data, meta, "{method}"),
      warning = function(w) {{ caught <<- c(caught, conditionMessage(w)); invokeRestart("muffleWarning") }}
    )
    table <- missingness_imbalance(normalized, meta)
    write.csv(table, "{(tmp_path / 'table.csv').as_posix()}", row.names = FALSE)
    writeLines(if (length(caught)) caught else "<none>", "{(tmp_path / 'warning.txt').as_posix()}", useBytes = TRUE)
    """
    completed = subprocess.run([RSCRIPT, "-e", script], capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        normalized = notebook.normalize_data(frame, meta, method)
    expected = notebook.missingness_imbalance(normalized, meta)
    r_table = pd.read_csv(tmp_path / "table.csv")
    assert r_table.columns.tolist() == COLUMNS
    assert r_table["sample"].astype(str).tolist() == expected["sample"].tolist()
    assert r_table["condition"].astype(str).tolist() == expected["condition"].astype(str).tolist()
    assert r_table["flagged"].tolist() == expected["flagged"].tolist()
    assert r_table["complete_features"].tolist() == expected["complete_features"].tolist()
    for column in ("missing_fraction", "reference_missing_fraction", "complete_offset"):
        np.testing.assert_allclose(r_table[column].to_numpy(float), expected[column].to_numpy(float),
                                   rtol=0, atol=1e-9, equal_nan=True)
    python_messages = [str(item.message) for item in caught if issubclass(item.category, UserWarning)]
    r_message = (tmp_path / "warning.txt").read_text(encoding="utf-8").strip()
    assert r_message == (python_messages[0] if python_messages else "<none>")
