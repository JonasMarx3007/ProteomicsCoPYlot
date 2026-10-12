"""Selected names reach the drawing, the table and the AI context unchanged.

Condition and protein names are free text: commas, pipes, equals signs, percent
signs, quotes and non-ASCII letters all occur in real projects. The browser sends
selections as JSON arrays so none of those characters can split or merge a name
on the way. These tests load a project that uses such names and call the real
routes, then read back what the renderer actually drew from: the settings and
the condition column of the data it recorded for the notebook export.

Semicolons separate members of a protein group. The complete group identifier
must survive transport too: "P1;P2" is selected as "P1;P2", not "P1".
"""
from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services import ai_functions, stats_tools
from app.services.annotation_store import reset_all_annotations, save_annotation
from app.services.dataset_store import reset_all_datasets, save_table_dataset
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id

CONDITIONS = ["Drug, high", "A;B|δ", "x=y", "100% ready", 'quote"name']
PROTEINS = ["P1;P2", "Drug, high", "A|B=δ", "100% ready", 'quote"name']
SITE_PROTEIN = "P1;P2|δ"
PATHWAY = "Path|δ, test"


@pytest.fixture
def awkward_project(monkeypatch):
    """Protein and phosphosite data whose condition and protein names are hard to transport.

    tests/conftest.py restores the stores after this module.
    """
    reset_all_datasets()
    reset_all_annotations()
    rng = np.random.default_rng(5)

    samples = [f"s{condition}_{replicate}" for condition in range(5) for replicate in range(3)]
    proteins = pd.DataFrame(rng.normal(20, 1, (12, len(samples))), columns=samples)
    proteins.insert(0, "ProteinNames", ["P1;P2", *PROTEINS[1:], *[f"Q{index}" for index in range(7)]])
    proteins.insert(1, "GeneNames", [f"G{index}" for index in range(12)])
    save_table_dataset("awkward.tsv", "protein", proteins)
    save_annotation(kind="protein", source_data=proteins, log2_data=proteins, filtered_data=proteins,
                    metadata=pd.DataFrame({"sample": samples, "condition": [CONDITIONS[i // 3] for i in range(15)]}),
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])

    site_samples = [f"p{condition}_{replicate}" for condition in range(4) for replicate in range(3)]
    sites = pd.DataFrame(rng.normal(12, 1, (6, len(site_samples))), columns=site_samples)
    sites["Protein_group"] = [SITE_PROTEIN] * 3 + ["Q"] * 3
    sites["Gene_group"] = ["G1"] * 3 + ["GQ"] * 3
    sites["PTM_Collapse_key"] = [f"{SITE_PROTEIN}_S{index}_M1" for index in range(3)] + [f"Q_S{index}_M1" for index in range(3)]
    sites["PTM_localization"] = 0.9
    sites["UPD_seq"] = [f"SEQ{index}" for index in range(6)]
    save_table_dataset("sites.csv", "phospho", sites)
    save_annotation(kind="phospho", source_data=sites, log2_data=sites, filtered_data=sites,
                    metadata=pd.DataFrame({"sample": site_samples, "condition": [CONDITIONS[i // 3] for i in range(12)]}),
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])

    database = pd.DataFrame([("BP", "GO:1", PATHWAY, "G0;G1;G2;G3")],
                            columns=["ontology", "term", "description", "genes"])
    monkeypatch.setattr(stats_tools, "load_go_db", lambda organism="human": database.copy())
    yield
    reset_all_datasets()
    reset_all_annotations()


def _setting(settings: dict, key: str):
    """A recorded setting, whether the renderer stores it flat or per stage."""
    if key in settings:
        return settings[key]
    for stage in settings.values():
        if isinstance(stage, dict) and key in stage:
            return stage[key]
    raise KeyError(key)


def _drawn_from(response) -> tuple[dict, list[str]]:
    """The settings the renderer used and the conditions present in the data it drew."""
    assert response.status_code == 200, response.text[:300]
    # Drawn by the notebook renderer, not by its fallback. Heatmaps add an
    # informational notice of their own ("Heatmap-usable genes: 4 of 4").
    assert response.headers.get("x-copylot-notebook"), response.headers.get("x-copylot-notice")
    assert "Notebook%20export%20unavailable" not in response.headers.get("x-copylot-notice", "")
    recipe = snapshots.get(get_session_id(), response.headers["x-copylot-notebook"])
    # The plotted table where the renderer keeps one; some keep the whole sample
    # sheet as metadata and select from it while drawing.
    table = (pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"]))
             if "table.parquet" in recipe.resources else pd.DataFrame())
    sheet = pd.read_parquet(io.BytesIO(recipe.resources["metadata.parquet"]))["condition"].astype(str)
    if "Condition" in table:
        drawn = table["Condition"].astype(str).drop_duplicates().tolist()
    elif any(column.startswith(f"{condition}_") for column in table.columns for condition in sheet):
        # A wide table: one "<condition>_<replicate>" column per plotted sample.
        drawn = [condition for condition in sheet.drop_duplicates()
                 if any(column.startswith(f"{condition}_") for column in table.columns)]
    else:
        drawn = sheet.drop_duplicates().tolist()
    return recipe.settings, drawn


def test_literal_selection_reaches_plot_table_and_ai_context(awkward_project):
    # Four of the five conditions, in reverse: the plot must drop the fifth and
    # order its samples by the selection, not by the sample sheet.
    chosen = CONDITIONS[:4][::-1]
    query = {"proteins": json.dumps(PROTEINS), "conditions": json.dumps(chosen)}
    with TestClient(app) as client:
        image = client.get("/api/plots/single-protein/protein/lineplot.png", params=query)
        table = client.get("/api/plots/single-protein/protein/lineplot-table", params=query)
        bad = {"proteins": json.dumps(PROTEINS), "conditions": "[1]"}
        assert client.get("/api/plots/single-protein/protein/lineplot.png", params=bad).status_code == 400
        assert client.get("/api/plots/single-protein/protein/lineplot-table", params=bad).status_code == 400

    settings, drawn_conditions = _drawn_from(image)
    assert _setting(settings, "proteins") == PROTEINS
    assert _setting(settings, "conditions") == chosen
    assert drawn_conditions == chosen

    assert table.status_code == 200, table.text[:300]
    rows = pd.DataFrame(table.json()["rows"])
    assert set(rows["Feature"]) == set(PROTEINS)
    assert rows["Condition"].drop_duplicates().tolist() == chosen

    # The assistant gets the same five proteins and four conditions. Its lines use
    # "|" as the field separator, so a pipe inside a name is written as "/".
    summary = ai_functions.single_protein_lineplot(
        mode={"proteins": PROTEINS, "conditions": chosen, "kind": "protein"})["summary"]
    assert "single_protein_lineplot_counts|entity_count=5|condition_count=4" in summary
    for name in PROTEINS:
        assert f"single_protein_lineplot_entity_summary|entity={name.replace('|', '/')}|" in summary
    assert ai_functions._mode_fields({"protein": "P1;P2|δ", "header": "false"})["protein"] == "P1;P2|δ"


@pytest.mark.parametrize("path,extra", [
    ("/api/plots/stats/protein/pathway-heatmap.png", {"pathway": PATHWAY}),
    ("/api/plots/single-protein/phospho/heatmap.png", {"protein": SITE_PROTEIN}),
    ("/api/plots/single-protein/protein/boxplot.png", {"protein": "A|B=δ"}),
    ("/api/plots/phospho/coverage.png", {}),
])
def test_condition_selection_arrays_reach_other_plot_families(awkward_project, path, extra):
    chosen = CONDITIONS[:3][::-1]
    with TestClient(app) as client:
        response = client.get(path, params={**extra, "conditions": json.dumps(chosen)})
        assert client.get(path, params={**extra, "conditions": "[1]"}).status_code == 400
    settings, drawn_conditions = _drawn_from(response)
    assert _setting(settings, "conditions") == chosen
    for key, value in extra.items():
        assert _setting(settings, key) == value
    assert set(drawn_conditions) == set(chosen)
    assert CONDITIONS[3] not in drawn_conditions
