"""The exported heatmap keeps the identifier its values were read under.

`single_protein_heatmap_table` ended with

    matrix.reset_index().rename(columns={"index": "Site"})

and that rename never fired: the index is named `PTM_Collapse_key`, which
`reset_index()` restores, so the column pandas produced was never called
`index`. The intended `Site` column had therefore never existed, and the
exported CSV went out headed `PTM_Collapse_key` over values that were not
collapse keys -- the protein accession had already been split off for the plot
axis. `A0JLT2~MED19_S226_M1` reached the user as `MED19_S226`, under a header
naming the thing that had been removed.

The table now carries both: `Site` is the label drawn on the figure, so a row
can be found on the plot, and `PTM_Collapse_key` is the whole identifier, so a
row can be traced back to the matrix. The figure itself is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services.annotation_store import get_annotation
from app.services.single_protein_tools import (
    _site_label,
    single_protein_heatmap_table,
    single_protein_options,
)
from app.services.viewer_bootstrap import load_viewer_state


@pytest.fixture(scope="module")
def project():
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    options = single_protein_options("phospho", tab="heatmap", identifier="workflow")
    return options


def _first_drawable(options) -> tuple[str, list[str]]:
    """The first protein whose heatmap can actually be built on this project.

    Most groups have too few complete rows to cluster; this is not the subject
    of the test, so it walks past them.
    """
    conditions = list(options["conditions"])
    for protein in options["proteins"]:
        try:
            table = single_protein_heatmap_table(
                kind="phospho", protein=protein, conditions=conditions, filter_m1=True
            )
        except ValueError:
            continue
        if not table.empty:
            return protein, conditions
    pytest.skip("no phosphoprotein group in this project produces a heatmap")


# --- both labels are present, and both are true -------------------------------


@pytest.mark.parametrize("filter_m1", [True, False])
def test_the_table_carries_the_whole_collapse_key(project, filter_m1: bool) -> None:
    """The column named PTM_Collapse_key holds keys that exist in the matrix."""
    protein, conditions = _first_drawable(project)
    table = single_protein_heatmap_table(
        kind="phospho", protein=protein, conditions=conditions, filter_m1=filter_m1
    )
    assert list(table.columns[:2]) == ["Site", "PTM_Collapse_key"]

    annotation = get_annotation("phospho")
    known = set(annotation.log2_data["PTM_Collapse_key"].astype(str))
    exported = table["PTM_Collapse_key"].astype(str).tolist()
    assert exported, "the heatmap produced no rows"
    assert set(exported) <= known, (
        "the exported key is not a key the matrix holds: "
        f"{sorted(set(exported) - known)[:3]}"
    )
    assert all("~" in key for key in exported), (
        "the protein accession was split off again, so the key is partial"
    )
    assert len(set(exported)) == len(exported), "collapse keys must be unique per row"


@pytest.mark.parametrize("filter_m1", [True, False])
def test_the_site_column_is_the_label_the_plot_draws(project, filter_m1: bool) -> None:
    """The two columns have to describe the same row, or the table is useless."""
    protein, conditions = _first_drawable(project)
    table = single_protein_heatmap_table(
        kind="phospho", protein=protein, conditions=conditions, filter_m1=filter_m1
    )
    for site, key in zip(table["Site"].astype(str), table["PTM_Collapse_key"].astype(str)):
        assert site == _site_label(key, filter_m1)
        assert site != key, "the short label should be shorter than the key"


def test_the_exported_label_is_no_longer_a_key_that_is_not_one(project) -> None:
    """The defect, stated directly: a header that named what had been removed."""
    protein, conditions = _first_drawable(project)
    table = single_protein_heatmap_table(
        kind="phospho", protein=protein, conditions=conditions, filter_m1=True
    )
    annotation = get_annotation("phospho")
    known = set(annotation.log2_data["PTM_Collapse_key"].astype(str))
    assert not set(table["Site"].astype(str)) & known, (
        "Site now holds full keys; then it is not the label on the figure"
    )
    assert set(table["PTM_Collapse_key"].astype(str)) <= known


# --- the label helper ---------------------------------------------------------


@pytest.mark.parametrize(
    "key,filter_m1,expected",
    [
        ("A0JLT2~MED19_S226_M1", True, "MED19_S226"),
        ("A0JLT2~MED19_S226_M1", False, "MED19_S226_M1"),
        ("A0JLT2~MED19_S226_M2", True, "MED19_S226_M2"),
        ("MED19_S226_M1", True, "MED19_S226"),
        ("", True, ""),
    ],
)
def test_the_site_label_strips_only_what_it_should(key, filter_m1, expected) -> None:
    assert _site_label(key, filter_m1) == expected


def test_the_multiplicity_suffix_survives_when_the_view_is_not_filtered() -> None:
    """With mixed multiplicities on screen, dropping _M1 would merge the labels."""
    assert _site_label("P1~GENE_S10_M1", False) == "GENE_S10_M1"
    assert _site_label("P1~GENE_S10_M2", False) == "GENE_S10_M2"


# --- the numbers are untouched -------------------------------------------------


def test_adding_a_column_did_not_move_a_value(project) -> None:
    """Both label columns are text; every sample column stays numeric."""
    protein, conditions = _first_drawable(project)
    table = single_protein_heatmap_table(
        kind="phospho", protein=protein, conditions=conditions, filter_m1=True
    )
    numeric = table.drop(columns=["Site", "PTM_Collapse_key"])
    assert not numeric.empty
    assert all(str(dtype).startswith("float") for dtype in numeric.dtypes)
    assert numeric.notna().to_numpy().any()
