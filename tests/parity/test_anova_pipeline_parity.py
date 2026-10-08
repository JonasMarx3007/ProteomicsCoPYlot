"""The three ANOVA pipelines must agree, and so must the app's own path.

CoPYlot ships the same analysis three times on purpose -- `stats_tools.py` for
the web app, `notebook_functions.py` for the pip package, `notebook_functions.R`
for the R functions -- and `test_triplicate_parity.py` checks that the *names* line
up. Names are not results: the app once returned the same 7,430 rows as the
packages in a different order, because a sort fix reached three of four places.

These tests compare what the pipelines actually return. 2026-10-02: the fourth
place, an unused `functions.anova_data_f` copy, was removed; the app's own path
(`stats_tools._anova_dataframe`) is now the reference.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from app.schemas.stats import AnovaRequest
from app.services.stats_tools import _anova_dataframe, _stats_source
from proteomicscopylot import notebook_functions as pip_package

NUMERIC = ("f_statistic", "pval", "adj_pval")


@pytest.fixture(scope="module")
def loaded(example_project):
    _, frame, metadata, _ = _stats_source("protein", data_source="data")
    return frame, metadata


@pytest.fixture(scope="module")
def tables(loaded):
    frame, metadata = loaded
    return {
        "pip": pip_package.anova_data_f(frame.copy(), metadata.copy(), workflow="Protein"),
        "app": _anova_dataframe(AnovaRequest(kind="protein"))[2],
    }


def test_all_pipelines_select_the_same_features(tables) -> None:
    sets = {name: set(t["ProteinNames"].astype(str)) for name, t in tables.items()}
    assert sets["pip"] == sets["app"], {
        name: len(value) for name, value in sets.items()
    }


@pytest.mark.parametrize("column", NUMERIC)
def test_the_numbers_are_identical(tables, column: str) -> None:
    """Same numbers is the part that changes conclusions."""
    other = "pip"
    left = tables["app"][["ProteinNames", column]]
    right = tables[other][["ProteinNames", column]]
    merged = left.merge(right, on="ProteinNames", suffixes=("_a", "_b"))
    a = merged[f"{column}_a"].to_numpy(dtype=float)
    b = merged[f"{column}_b"].to_numpy(dtype=float)
    finite = np.isfinite(a) & np.isfinite(b)
    assert finite.sum() > 1000
    worst = float(np.max(np.abs(a[finite] - b[finite])))
    assert worst < 1e-12, f"app vs {other}: {column} differs by {worst:.3e}"


def test_the_row_order_is_identical(tables) -> None:
    """Row order decides cluster numbering, so it is pinned too.

    The clustering relabels clusters in dendrogram leaf order, and the leaf order
    comes from the matrix in the order the ANOVA table left it.
    """
    assert (
        tables["app"]["ProteinNames"].astype(str).tolist()
        == tables["pip"]["ProteinNames"].astype(str).tolist()
    ), "the app and the pip package order the same features differently"


def test_ties_are_broken_by_raw_p_then_label(tables) -> None:
    for name, table in tables.items():
        adj = table["adj_pval"].to_numpy(dtype=float)
        raw = table["pval"].to_numpy(dtype=float)
        for i in range(len(adj) - 1):
            if abs(adj[i] - adj[i + 1]) < 1e-15:
                assert raw[i] <= raw[i + 1] + 1e-12, f"{name}: tie at {i} unbroken"


def test_too_few_replicates_raises_in_the_pip_package(loaded) -> None:
    """An empty table reads as 'nothing significant'; it must not be returned."""
    frame, metadata = loaded
    blanked = frame.copy()
    for column in metadata["sample"].astype(str):
        if column in blanked.columns:
            blanked[column] = np.nan
    with pytest.raises(ValueError, match="enough replicate values"):
        pip_package.anova_data_f(blanked, metadata.copy(), workflow="Protein")


def test_phosphoprotein_carries_the_gene_and_site_columns() -> None:
    """The gene column and the site provenance, in that order."""
    samples = [f"{c}_{i}" for c in ("A", "B") for i in (1, 2, 3)]
    frame = pd.DataFrame(
        {
            "Phosphoprotein": [f"P{i}" for i in range(12)],
            "Gene_group": [f"G{i}" for i in range(12)],
            "site_num": list(range(12)),
            "PTM_Collapse_keys": [f"K{i}" for i in range(12)],
            **{s: np.random.default_rng(i).normal(20, 1, 12) for i, s in enumerate(samples)},
        }
    )
    metadata = pd.DataFrame(
        {"sample": samples, "condition": [c for c in ("A", "B") for _ in range(3)]}
    )
    table = pip_package.anova_data_f(frame.copy(), metadata.copy(), workflow="Phosphoprotein")
    for column in ("Gene_group", "site_num", "PTM_Collapse_keys"):
        assert column in table.columns, f"pip dropped {column}"


@pytest.mark.requires_r()
def test_the_r_pipeline_agrees_with_python(loaded, tables, tmp_path, rscript) -> None:
    frame, metadata = loaded
    frame.to_csv(tmp_path / "data.csv", index=False)
    metadata.to_csv(tmp_path / "meta.csv", index=False)
    script = f"""
      source({str(ROOT / 'proteomicscopylot' / 'notebook_functions.R')!r})
      data <- read.csv({str(tmp_path / 'data.csv')!r}, check.names = FALSE)
      meta <- read.csv({str(tmp_path / 'meta.csv')!r}, check.names = FALSE)
      out <- anova_data_f(data, meta, workflow = "Protein")
      write.csv(out[, c("ProteinNames", "f_statistic", "pval", "adj_pval")],
                {str(tmp_path / 'r.csv')!r}, row.names = FALSE)
    """
    result = subprocess.run(
        [rscript, "-e", script], capture_output=True, text=True, timeout=900
    )
    assert result.returncode == 0, result.stderr[-2000:]

    r_table = pd.read_csv(tmp_path / "r.csv")
    python_table = tables["app"][["ProteinNames", *NUMERIC]]
    merged = r_table.merge(python_table, on="ProteinNames", suffixes=("_r", "_py"))
    assert len(merged) > 1000, f"only {len(merged)} features aligned"

    for column in NUMERIC:
        a = merged[f"{column}_r"].to_numpy(dtype=float)
        b = merged[f"{column}_py"].to_numpy(dtype=float)
        finite = np.isfinite(a) & np.isfinite(b)
        worst = float(np.max(np.abs(a[finite] - b[finite])))
        assert worst < 1e-9, f"R vs the app: {column} differs by {worst:.3e}"

    assert (
        r_table["ProteinNames"].astype(str).tolist()
        == python_table["ProteinNames"].astype(str).tolist()
    ), "R and the app order the same features differently"
