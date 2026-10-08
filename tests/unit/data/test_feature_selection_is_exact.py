"""A selected protein means that protein, not everything its name is inside of.

The phosphosite-on-protein heatmap resolved its selection with a
case-insensitive **substring** search on the protein-group column, while the
boxplot, the lineplot and the single-protein table beside it all used the exact
`_feature_match_mask`. So selecting `P12345` also pulled in the isoform group
`P12345-2` and the multi-protein group `P12345;Q67890`, and drew all of their
sites under the heading of the one protein the user picked -- silently, because
a heatmap with more rows than expected looks like a protein with more sites.

The shipped example has no such collision (its phosphoprotein groups are none a
substring of another), which is exactly why this survived: it is wrong on data
nobody here has, and there is nothing in the output that says so. The project
below plants the collision.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import AnnotationFilterConfig
from app.services.annotation_store import save_annotation
from app.services.single_protein_tools import (
    _feature_match_mask,
    single_protein_boxplot_table,
    single_protein_heatmap_table,
    single_protein_lineplot_table,
    single_protein_options,
)
from app.services.viewer_bootstrap import load_viewer_state

# Three groups that a substring search cannot tell apart, and one that it can.
SELECTED = "P12345"
ISOFORM = "P12345-2"
MULTI = "P12345;Q67890"
UNRELATED = "Q99999"

SITES = {
    SELECTED: ["P12345~S10_M1", "P12345~T22_M1"],
    ISOFORM: ["P12345-2~S99_M1"],
    MULTI: ["P12345;Q67890~Y41_M1"],
    UNRELATED: ["Q99999~S7_M1"],
}


@pytest.fixture(scope="module")
def colliding_project():
    """A phospho project whose protein groups overlap as strings."""
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    rng = np.random.default_rng(20260916)
    samples = [f"{condition}_{replicate}" for condition in ("WT", "KO") for replicate in (1, 2, 3)]
    metadata = pd.DataFrame(
        {"sample": samples, "condition": [s.split("_")[0] for s in samples]}
    )

    rows = []
    for group, site_keys in SITES.items():
        for site_key in site_keys:
            rows.append(
                {
                    "PTM_Collapse_key": site_key,
                    "Protein_group": group,
                    "GeneNames": group.split(";")[0],
                    **{sample: 20.0 + rng.normal(0, 0.1) for sample in samples},
                }
            )
    frame = pd.DataFrame(rows)

    save_annotation(
        kind="phospho",
        source_data=frame,
        metadata=metadata,
        log2_data=frame,
        filtered_data=frame,
        is_log2_transformed=True,
        metadata_source="uploaded",
        filter_config=AnnotationFilterConfig(
            method="at_least_n",
            minPresent=2,
            minPercentage=70.0,
            mode="in_at_least_one_group",
            normalization="none",
        ),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
    )
    yield metadata
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")


def _heatmap_sites(protein: str) -> set[str]:
    table = single_protein_heatmap_table(
        kind="phospho",
        protein=protein,
        conditions=["WT", "KO"],
        identifier="workflow",
        filter_m1=True,
    )
    # The label column is whatever the matrix index was named; the heatmap
    # table puts the extracted site in the first column either way.
    return set(table[table.columns[0]].astype(str))


def _expected_sites(group: str) -> set[str]:
    return {key.split("~", 1)[1].rsplit("_", 1)[0] for key in SITES[group]}


# --- the defect ---------------------------------------------------------------


def test_the_heatmap_shows_only_the_selected_protein(colliding_project) -> None:
    """The one that fails on the old code: two extra proteins in one heatmap."""
    shown = _heatmap_sites(SELECTED)
    assert shown == _expected_sites(SELECTED), (
        "the heatmap drew sites belonging to another protein group under "
        f"{SELECTED!r}: {sorted(shown - _expected_sites(SELECTED))}"
    )
    assert not (shown & _expected_sites(ISOFORM)), "an isoform group was merged in"
    assert not (shown & _expected_sites(MULTI)), "a multi-protein group was merged in"


def test_each_colliding_group_is_reachable_on_its_own(colliding_project) -> None:
    """Exactness must not cost the user access to the groups themselves."""
    for group in (ISOFORM, MULTI, UNRELATED):
        assert _heatmap_sites(group) == _expected_sites(group), group


def test_the_selector_offers_every_group_it_can_resolve(colliding_project) -> None:
    """The option list and the matcher have to agree, or a choice draws nothing."""
    options = single_protein_options("phospho", tab="heatmap", identifier="workflow")
    offered = set(map(str, options["proteins"]))
    assert offered == set(SITES), offered
    for group in offered:
        assert _heatmap_sites(group), f"{group} is offered but resolves to nothing"


def test_a_selection_that_matches_nothing_says_so(colliding_project) -> None:
    """Rather than falling back to whatever it is a prefix of."""
    with pytest.raises(ValueError, match="No phosphosite rows found"):
        _heatmap_sites("P123")


# --- the same matcher everywhere ---------------------------------------------


PROTEIN_GROUPS = [SELECTED, ISOFORM, MULTI, UNRELATED]


@pytest.fixture(scope="module")
def colliding_protein_project(colliding_project):
    """The same four colliding names as protein groups, for the lineplot and boxplot.

    Built on top of `colliding_project`, which loads the viewer state and
    restores it afterwards, so the phosphosite project stays in place for the
    heatmap tests in the same module.
    """
    metadata = colliding_project
    samples = metadata["sample"].tolist()
    frame = pd.DataFrame(
        {
            "ProteinNames": PROTEIN_GROUPS,
            "GeneNames": [f"GENE{index}" for index in range(len(PROTEIN_GROUPS))],
            **{sample: [20.0, 21.0, 22.0, 23.0] for sample in samples},
        }
    )
    save_annotation(
        kind="protein",
        source_data=frame,
        metadata=metadata,
        log2_data=frame,
        filtered_data=frame,
        is_log2_transformed=True,
        metadata_source="uploaded",
        filter_config=AnnotationFilterConfig(
            method="at_least_n",
            minPresent=2,
            minPercentage=70.0,
            mode="in_at_least_one_group",
            normalization="none",
        ),
        auto_detected=False,
        warnings=[],
        log2_auto_detected=False,
    )
    return frame


def _source_features(table: pd.DataFrame) -> set[str]:
    """The protein groups a plot says it drew, from its SourceFeatures column."""
    return {
        feature.strip()
        for cell in table["SourceFeatures"].astype(str)
        for feature in cell.split("; ")
        if feature.strip()
    }


def test_the_lineplot_uses_the_same_exact_match(colliding_protein_project) -> None:
    """Selecting one group never includes another group with the same leader."""
    table = single_protein_lineplot_table("protein", [SELECTED], ["WT", "KO"])
    assert _source_features(table) == {SELECTED}


def test_the_boxplot_uses_the_same_exact_match(colliding_protein_project) -> None:
    summary = single_protein_boxplot_table("protein", SELECTED, ["WT", "KO"])
    assert _source_features(summary) == {SELECTED}


def test_complete_protein_groups_remain_distinct_in_tables_and_exports(colliding_protein_project):
    from app.services import notebook_single
    from app.services.analysis_functions import _selection_label
    from app.services.single_protein_tools import unmatched_lineplot_names
    from proteomicscopylot import notebook_functions

    frame = colliding_protein_project
    meta = pd.DataFrame({"sample": list(frame.columns[2:]), "condition": ["WT"] * 3 + ["KO"] * 3})
    options = single_protein_options("protein", tab="lineplot", identifier="workflow")
    assert set(options["proteins"]) == set(PROTEIN_GROUPS)
    assert unmatched_lineplot_names("protein", [MULTI, "P123"]) == ["P123"]
    assert _selection_label(kind="protein", identifier="workflow", label_value=MULTI) == MULTI
    table = single_protein_lineplot_table("protein", [SELECTED, MULTI], ["WT", "KO"])
    assert set(table.Feature) == {SELECTED, MULTI}
    assert table.groupby("Feature").Value.first().to_dict() == {SELECTED: 20.0, MULTI: 22.0}
    for group, value in [(SELECTED, 20.0), (MULTI, 22.0)]:
        summary = single_protein_boxplot_table("protein", group, ["WT", "KO"])
        assert _source_features(summary) == {group}
        assert (summary.SourceFeatureCount == 1).all()
        portable, _, _, _ = notebook_single.box_module().prepare_table(frame, meta, "protein", group, [], "workflow")
        assert all(np.array_equal(values, [value] * 3) for values in portable)
        standalone = notebook_functions.single_protein_values(frame, meta, group)
        assert standalone.value.tolist() == [value] * 6
    import matplotlib.pyplot as plt
    figure = notebook_functions.compare_prot_line(frame, meta, ["WT", "KO"], [SELECTED, MULTI], id=False)
    try:
        lines = figure.axes[0].get_lines()
        assert {line.get_label(): list(line.get_ydata()) for line in lines} == {
            SELECTED: [20.0] * 6, MULTI: [22.0] * 6,
        }
    finally:
        plt.close(figure)


@pytest.mark.requires_r()
def test_r_keeps_colliding_protein_groups_separate(colliding_protein_project, tmp_path, rscript):
    import subprocess
    colliding_protein_project.to_csv(tmp_path / "data.csv", index=False)
    script = f'''
    source("{(ROOT / 'proteomicscopylot/notebook_functions.R').as_posix()}")
    data <- read.csv("data.csv", check.names=FALSE)
    meta <- data.frame(sample=names(data)[3:8], condition=rep(c("WT", "KO"), each=3))
    stopifnot(all(single_protein_values(data, meta, "{SELECTED}")$value == 20))
    stopifnot(all(single_protein_values(data, meta, "{MULTI}")$value == 22))
    matplot <- function(x, ...) {{
      stopifnot(identical(colnames(x), c("{SELECTED}", "{MULTI}")))
      stopifnot(all(x[,1] == 20), all(x[,2] == 22))
      graphics::matplot(x, ...)
    }}
    pdf("plot.pdf")
    compare_prot_line(data, meta, c("WT", "KO"), c("{SELECTED}", "{MULTI}"), id=FALSE)
    dev.off()
    '''
    result = subprocess.run([rscript, "-e", script], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fragment", ["P123", "12345", "p12345"])
@pytest.mark.parametrize("plot", ["lineplot", "boxplot"])
def test_a_fragment_of_a_name_selects_nothing_in_the_lineplot_or_boxplot(
    colliding_protein_project, plot: str, fragment: str
) -> None:
    """A substring or case-folded search would resolve these; the exact match refuses."""
    with pytest.raises(ValueError, match="No rows? matched"):
        if plot == "lineplot":
            single_protein_lineplot_table("protein", [fragment], ["WT", "KO"])
        else:
            single_protein_boxplot_table("protein", fragment, ["WT", "KO"])


def test_the_matcher_ignores_surrounding_whitespace() -> None:
    """The options list strips; an unstripped compare would match nothing."""
    values = pd.Series([" P12345 ", "P12345-2", None])
    mask = _feature_match_mask(values, {"P12345"}, kind="phospho", identifier="workflow")
    assert mask.tolist() == [True, False, False]
