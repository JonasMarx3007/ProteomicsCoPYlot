"""One localization probability cutoff decides which phosphosites every module sees.

The cutoff is a single session value (services/phospho_localization.py). It is
applied where a phosphosite matrix is read -- `select_matrix`, the
Phospho-specific plots and completeness -- so statistics, QC and the Kinase
Library export all analyse the same sites. At 0 every site is kept; above 0 a
site without a probability is left out. The phosphosite-to-phosphoprotein
collapse takes its own cutoff and records it. The pip package and R mirror the
filter as `filter_localization`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.stats import VolcanoRequest
from app.services import completeness_tools, functions, phospho_tools, stats_tools
from app.services.annotation_store import get_annotation
from app.services.phospho_localization import (
    get_localization_cutoff,
    localization_cutoff_description,
    reset_localization_cutoff,
    set_localization_cutoff,
)
from app.services.viewer_bootstrap import load_viewer_state
from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[3]


def _sites():
    return pd.DataFrame({
        "PTM_Collapse_key": ["a", "b", "c", "d", "e", "f"],
        "PTM_localization": [0.99, 0.75, 0.74, np.nan, "bad", 1.5],
        "s1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    })


@pytest.mark.parametrize("module", [functions, notebook])
@pytest.mark.parametrize("cutoff,kept", [
    (0.0, ["a", "b", "c", "d", "e", "f"]),
    (0.75, ["a", "b"]),
    (0.99, ["a"]),
    (1.0, []),
])
def test_filter_keeps_sites_at_or_above_and_drops_unknown_probabilities(module, cutoff, kept):
    assert module.filter_localization(_sites(), cutoff)["PTM_Collapse_key"].tolist() == kept


@pytest.mark.parametrize("module", [functions, notebook])
def test_filter_refuses_out_of_range_and_missing_columns(module):
    with pytest.raises(ValueError, match="between 0 and 1"):
        module.filter_localization(_sites(), 1.2)
    with pytest.raises(ValueError, match="PTM_localization"):
        module.filter_localization(_sites().drop(columns="PTM_localization"), 0.5)
    assert len(module.filter_localization(_sites().drop(columns="PTM_localization"), 0)) == 6


def test_report_sentence():
    assert localization_cutoff_description(0) == "All phosphosites are included, whatever their localization probability."
    assert "at least 0.75" in localization_cutoff_description(0.75)
    assert "without a localization probability are excluded" in localization_cutoff_description(0.75)


@pytest.fixture
def example():
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    reset_localization_cutoff()
    yield
    reset_localization_cutoff()


def _volcano_rows(kind="phospho"):
    return stats_tools.run_volcano(VolcanoRequest(
        kind=kind, dataSource="filtered", condition1="GRK", condition2="WT", identifier="workflow",
        pValueThreshold=0.05, log2fcThreshold=1.0, testType="unpaired", useUncorrected=False,
    )).totalRows


def test_every_phosphosite_entry_point_uses_the_session_cutoff(example):
    annotation = get_annotation("phospho")
    probability = pd.to_numeric(annotation.filtered_data["PTM_localization"], errors="coerce")
    passing = int((probability >= 0.75).sum())
    before_volcano, before_protein = _volcano_rows(), _volcano_rows("protein")
    overview_before = dict(phospho_tools.phosphosite_plot_table()[["Term", "Count"]].values)

    set_localization_cutoff(0.75)
    _, frame, _ = functions.select_matrix("phospho", "filtered")
    assert len(frame) == passing
    assert (pd.to_numeric(frame["PTM_localization"]) >= 0.75).all()
    assert _volcano_rows() < before_volcano, "the cached volcano must be recomputed"
    assert _volcano_rows("protein") == before_protein, "protein data is not phosphosite data"
    overview = dict(phospho_tools.phosphosite_plot_table()[["Term", "Count"]].values)
    assert overview["Phosphosites"] < overview_before["Phosphosites"]
    site_frame, _ = completeness_tools._frame_and_meta("phospho")
    assert (pd.to_numeric(site_frame["PTM_localization"]) >= 0.75).all()
    table = phospho_tools.ksea_table(condition1="GRK", condition2="WT", organism="none", data_source="data")
    _, all_data, _ = functions.select_matrix("phospho", "data")
    assert set(table["PTM_Collapse_key"]) <= set(all_data["PTM_Collapse_key"])
    assert (pd.to_numeric(all_data["PTM_localization"]) >= 0.75).all()


def test_a_cutoff_nothing_passes_is_an_explained_error(example, monkeypatch):
    low = _sites().iloc[[2]]
    monkeypatch.setattr(functions, "_select_matrix_all_rows", lambda kind, source: (source, low, None))
    set_localization_cutoff(0.9)
    with pytest.raises(ValueError, match="Lower the localization probability cutoff"):
        functions.select_matrix("phospho", "filtered")
    monkeypatch.setattr(functions, "_select_matrix_all_rows",
                        lambda kind, source: (source, low.drop(columns="PTM_localization"), None))
    with pytest.raises(ValueError, match="Set the cutoff to 0"):
        functions.select_matrix("phospho", "filtered")


def test_api_round_trip_and_validation(example):
    with TestClient(app) as client:
        assert client.get("/api/data-tools/phospho-localization-cutoff").json() == {"cutoff": 0.0, "available": True}
        assert client.post("/api/data-tools/phospho-localization-cutoff", json={"cutoff": 0.5}).json()["cutoff"] == 0.5
        assert client.post("/api/data-tools/phospho-localization-cutoff", json={"cutoff": 1.5}).status_code == 422
        assert client.get("/api/data-tools/phospho-localization-cutoff").json()["cutoff"] == 0.5


def test_collapse_uses_and_records_its_own_cutoff(example):
    from app.services.phosprot_tools import aggregate_from_phospho

    everything = aggregate_from_phospho(mode="mean", localization_cutoff=0.0)
    all_sites = everything.phosprot_lineage.siteCount
    stored = aggregate_from_phospho(mode="mean", localization_cutoff=0.75)
    assert stored.phosprot_lineage.localizationCutoff == 0.75
    assert stored.phosprot_lineage.siteCount < all_sites
    assert any("at least 0.75" in warning for warning in stored.warnings)
    # The package collapses the same sites to the same values.
    phospho = get_annotation("phospho")
    source = phospho.filtered_data
    expected = notebook.transform_phosprot(
        source, phospho.metadata, mode="mean", data_scale="log2", coverage_data=source,
        localization_cutoff=0.75,
    )
    assert sorted(expected["Phosphoprotein"]) == sorted(stored.source_data["Phosphoprotein"])


def test_restore_state_keeps_the_cutoff(example):
    from app.services import restore_state

    set_localization_cutoff(0.6)
    payload = restore_state._parse_state_blob(restore_state.export_state_blob())
    assert payload["backend"]["phosphoLocalizationCutoff"] == 0.6
    reset_localization_cutoff()
    assert get_localization_cutoff() == 0.0
