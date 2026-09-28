"""The phosphoprotein-regulation plot runs on the data source the user picked.

It sums significant phosphosite log2 fold changes from a volcano it computes
itself. That volcano was hard-wired to the unfiltered, non-imputed matrix while
the Statistics volcano offers data / filtered / imputed, so the two could
disagree on which sites are significant. The three regulation routes (PNG,
HTML, table) and KSEA now take `dataSource`, the page sends one shared choice
for both, and `_volcano_dataframe` reports the source it was given instead of
stamping every override frame "filtered".
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.services import phospho_tools, stats_tools

ROOT = Path(__file__).resolve().parents[2]

SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]


def _matrices() -> dict[str, pd.DataFrame]:
    # Site s1: strongly up in B, complete -> significant on every source.
    # Site s2: same effect but one B value missing; imputation fills it, so the
    # imputed source finds it with n=3 while the raw one tests with n=2.
    base = pd.DataFrame(
        {
            "PTM_Collapse_key": ["P1_S1", "P1_S2"],
            "Protein_group": ["P1", "P1"],
            "Genes": ["G1", "G1"],
            "A1": [10.0, 10.0],
            "A2": [10.1, 10.1],
            "A3": [9.9, 9.9],
            "B1": [14.0, 14.0],
            "B2": [14.1, 14.1],
            "B3": [13.9, np.nan],
        }
    )
    imputed = base.copy()
    imputed.loc[1, "B3"] = 13.9
    return {"data": base, "filtered": base.copy(), "imputed": imputed}


@pytest.fixture
def phospho_sources(monkeypatch):
    matrices = _matrices()
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A"] * 3 + ["B"] * 3})
    seen: list[str] = []

    def select(kind, data_source="data"):
        seen.append(data_source)
        return data_source, matrices[data_source].copy(), meta.copy()

    monkeypatch.setattr(phospho_tools, "select_matrix", select)
    monkeypatch.setattr(stats_tools, "select_matrix", select)
    monkeypatch.setattr(
        phospho_tools, "get_annotation", lambda kind: SimpleNamespace(metadata=meta.copy())
    )
    return seen


def _table(source: str) -> pd.DataFrame:
    return phospho_tools.phosprot_regulation_table(
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        test_type="unpaired",
        use_uncorrected=True,
        data_source=source,
    )


def test_the_table_reads_the_requested_matrix(phospho_sources):
    for source in ("data", "filtered", "imputed"):
        phospho_sources.clear()
        _table(source)
        assert phospho_sources == [source], f"{source}: select_matrix saw {phospho_sources}"


def test_imputation_changes_the_summed_effect_but_not_the_sites(phospho_sources):
    raw = _table("data")
    imputed = _table("imputed")
    # log2FC is condition1 - condition2 (A - B): both sites read as down in A.
    assert int(raw.loc[0, "Downregulated_count"]) == 2
    assert int(imputed.loc[0, "Downregulated_count"]) == 2
    assert imputed.loc[0, "Downregulated_sites"] == raw.loc[0, "Downregulated_sites"]
    # With the missing replicate filled, the second site's effect is computed
    # from three values instead of two, so the summed coordinate moves.
    assert float(raw.loc[0, "y"]) == pytest.approx(8.05)
    assert float(imputed.loc[0, "y"]) == pytest.approx(8.0)


def test_an_unknown_source_is_refused(phospho_sources):
    with pytest.raises(ValueError, match="data source"):
        _table("raw")


@pytest.mark.parametrize("source", ["filtered", "imputed"])
def test_missing_annotation_never_falls_back_to_unfiltered_data(monkeypatch, source):
    monkeypatch.setattr(phospho_tools, "get_annotation", lambda kind: None)
    monkeypatch.setattr(phospho_tools, "_phospho_context", lambda: pytest.fail("Unfiltered fallback"))
    with pytest.raises(ValueError, match="annotations"):
        phospho_tools._phospho_regulation_context(source)


def test_volcano_reports_the_callers_source_for_override_frames(phospho_sources):
    matrices = _matrices()
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A"] * 3 + ["B"] * 3})
    for source in ("data", "imputed"):
        source_used, *_ = stats_tools._volcano_dataframe(
            kind="phospho",
            data_source=source,
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=1.0,
            test_type="unpaired",
            use_uncorrected=True,
            frame_override=matrices[source],
            metadata_override=meta,
        )
        assert source_used == source


def test_all_three_regulation_routes_accept_data_source():
    tree = ast.parse((ROOT / "backend" / "app" / "api" / "routes_plots.py").read_text(encoding="utf-8"))
    routes = {
        node.name: {arg.arg for arg in node.args.args + node.args.kwonlyargs}
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("phospho_phosprot_regulation")
    }
    assert set(routes) == {
        "phospho_phosprot_regulation_route",
        "phospho_phosprot_regulation_html_route",
        "phospho_phosprot_regulation_table_route",
    }
    for name, args in routes.items():
        assert "dataSource" in args, name


def test_the_page_sends_the_data_source_for_regulation():
    """KSEA has its own page (KseaPage) with its own selector; the phospho page
    sends the choice for the regulation plot and its table."""
    page = (ROOT / "frontend" / "src" / "features" / "phospho" / "PhosphoSpecificPage.tsx").read_text(
        encoding="utf-8"
    )
    # the regulation html and its table, plus the view's context mode for the assistant
    assert page.count("dataSource: debouncedDataSource,") == 3
    assert 'key="dataSource"' in page
    assert "useDataSourceChoice(persisted.dataSource)" in page
