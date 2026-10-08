"""A lineplot selection that matches no row is named, not dropped in silence.

The lineplot draws the names that match and leaves the rest out. A typo, or a
single accession "P1" typed where the row carries the whole group "P1;P2"
(workflow selections match the complete group identifier), used to vanish
without a word. The page now says which names were not plotted, under the
figure (GUI only), and the assistant's evidence says the same.
"""
from __future__ import annotations

import json
from urllib.parse import unquote

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.services import ai_functions
from app.services.annotation_store import save_annotation
from app.services.dataset_store import save_table_dataset
from app.services.single_protein_tools import _feature_match_mask, _unmatched_names


@pytest.fixture
def grouped_dataset() -> None:
    samples = [f"{group}_{i}" for group in "AB" for i in range(1, 4)]
    frame = pd.DataFrame(np.random.default_rng(1).normal(12, 1, (4, 6)), columns=samples)
    frame.insert(0, "ProteinNames", ["P1;P2", "P3", "P4", "P5"])
    frame.insert(1, "GeneNames", ["G1;G2", "G3", "G4", "G5"])
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})
    save_table_dataset(filename="groups.csv", kind="protein", frame=frame)
    save_annotation(kind="protein", source_data=frame, metadata=metadata, log2_data=frame,
        filtered_data=frame, is_log2_transformed=True, metadata_source="manual",
        filter_config=AnnotationFilterConfig(minPresent=1), auto_detected=False, warnings=[])


CONDITIONS = json.dumps(["A", "B"])


@pytest.mark.parametrize("kind,identifier,values", [
    ("protein", "workflow", ["P1;P2", " P3 ", "P4"]),
    ("protein", "genes", ["G1;G2", "g3", "G4 "]),
    ("phospho", "workflow", ["S1~X_S5", " S2~Y_T7 "]),
])
def test_the_names_reported_are_exactly_the_ones_the_plot_cannot_match(kind, identifier, values) -> None:
    column = pd.Series(values)
    candidates = ["P1", "P2", "P1;P2", "P3", "p3", "G2", "G3", "g4", "X", "S1~X_S5", "S2~Y_T7", "S1"]
    unmatched = _unmatched_names(column, candidates, kind, identifier)
    for name in candidates:
        matched = bool(_feature_match_mask(column, {name}, kind, identifier).any())
        assert (name in unmatched) is not matched, name


def test_the_lineplot_names_what_it_left_out_under_the_figure(client, grouped_dataset) -> None:
    response = client.get("/api/plots/single-protein/protein/lineplot.png",
        params={"proteins": json.dumps(["P1", "P3", "P9"]), "conditions": CONDITIONS})
    assert response.status_code == 200
    assert unquote(response.headers["x-copylot-notice"]) == (
        "Not found in this dataset, so not plotted: P1, P9.")


def test_a_selection_that_all_matches_carries_no_notice(client, grouped_dataset) -> None:
    response = client.get("/api/plots/single-protein/protein/lineplot.png",
        params={"proteins": json.dumps(["P1;P2", "P3"]), "conditions": CONDITIONS})
    assert response.status_code == 200
    assert "x-copylot-notice" not in response.headers


def test_pages_that_draw_the_plot_as_an_image_ask_for_the_same_notice(client, grouped_dataset) -> None:
    response = client.get("/api/plots/single-protein/protein/lineplot-unmatched",
        params={"proteins": json.dumps(["G2", "g3", "Nope"]), "identifier": "genes"})
    assert response.json() == {"notice": "Not found in this dataset, so not plotted: Nope."}


def test_the_assistant_is_told_which_names_were_not_plotted(grouped_dataset) -> None:
    summary = ai_functions.single_protein_lineplot(
        "protein", {"kind": "protein", "tab": "lineplot", "proteins": ["P1", "P3"], "conditions": ["A", "B"]}
    )["summary"]
    line = next(line for line in summary.splitlines() if line.startswith("single_protein_lineplot_not_found|"))
    values = json.loads(line.split("|values=", 1)[1].split("|", 1)[0])
    assert values == ["P1"]
