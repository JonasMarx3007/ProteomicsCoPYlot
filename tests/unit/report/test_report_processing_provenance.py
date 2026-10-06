"""Every report says which numbers a reader is looking at.

Filtering was stated in each level's preamble and imputation was not, so a
project that imputes at load time and whose report contains no volcano never
mentioned imputation at all. And a PCA -- built from the rows that survived the
filter, and from drawn values when its source is imputed -- carried a bare
"Data source" line while a volcano beside it carried the full provenance.

Both now carry the same block, in the same order and the same words:
Data source, then Filtering, then Imputation.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]

from app.main import app
from app.schemas.annotation import AnnotationImputationInfo
from app.schemas.summary import SummaryReportRequest
from app.services.annotation_store import get_annotation
from app.services.report_function import (
    _data_provenance_html,
    _pca_completeness_description,
    _level_imputation_html,
    report_function,
)
from app.services.viewer_bootstrap import load_viewer_state

CONFIG = ROOT / "tests" / "fixtures" / "viewer_config.json"


pytestmark = pytest.mark.usefixtures("example_project")


def _text(html_fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_fragment)).strip()


@contextmanager
def recorded_imputation(kind: str, info: AnnotationImputationInfo):
    """Temporarily give a level a recorded imputation.

    The store hands back the live annotation object, so this sets the field and
    puts the original back rather than rewriting the whole annotation.
    """
    annotation = get_annotation(kind)
    original = annotation.imputation
    annotation.imputation = info
    try:
        yield
    finally:
        annotation.imputation = original


QUANTILE = AnnotationImputationInfo(
    mode="quantile",
    applied=True,
    qValue=0.01,
    adjustStd=0.3,
    downShift=1.8,
    width=0.3,
    seed=1337,
    sampleWise=True,
    sampleCount=6,
    missingBefore=100,
    missingAfter=0,
)


# --- the level preamble ------------------------------------------------------


def test_the_level_preamble_states_the_imputation_beside_the_filtering() -> None:
    """The failure this prevents: a report that never mentions imputation.

    A viewer project imputes at load time. If its report has no volcano and no
    imputed PCA, nothing else in the document would say so, and a collaborator
    would read drawn values as measured ones.
    """
    with recorded_imputation("protein", QUANTILE):
        said = _text(_level_imputation_html("protein"))
        assert "Imputation:" in said
        assert "0.01" in said and "0.3" in said, f"the settings are missing: {said}"
        # Random seeds are deliberately not reported (no scientific information).
        assert "seed" not in said
        assert "dataset-wide parameters" in said or "sample-wise parameters" in said
        assert "states its own source" in said, (
            "the preamble must not imply every plot used imputed values"
        )


def test_a_level_without_imputation_says_so_rather_than_staying_silent() -> None:
    said = _text(_level_imputation_html("protein"))
    assert "No imputation was applied" in said, said


def test_the_preamble_is_where_the_filtering_already_is() -> None:
    """Both sentences must reach the reader before the level's first plot."""
    body = report_function(SummaryReportRequest(title="T", author="A")).html
    filtering = body.index("<strong>Filtering:</strong>")
    imputation = body.index("<strong>Imputation:</strong>", filtering)
    first_section = re.search(r"<h2[^>]*>[^<]*Coverage Plot</h2>", body)
    assert first_section is not None
    assert filtering < imputation, "imputation should follow the filtering it qualifies"
    assert imputation < first_section.start(), (
        "the processing statement must precede the plots it describes"
    )
    scope = body.index("QC plots use the unfiltered, non-imputed data unless another data source is stated.")
    assert scope < filtering
    assert "PCA also uses its stated data source" in body[scope:filtering]


# --- one block for every plot whose numbers depend on it ---------------------


@pytest.mark.parametrize(
    "data_source,label",
    [("data", "Data"), ("filtered", "Filtered Data"), ("imputed", "Imputed Data")],
)
def test_the_provenance_block_names_source_filtering_and_imputation(
    data_source: str, label: str
) -> None:
    """All three, not two.

    The block used to take a boolean, which was right while the only choices
    were imputed and not. Once `filtered` existed, a filtered plot was headed
    "Data" -- and the PCA was re-rendered on the unfiltered matrix to match.
    """
    block = _data_provenance_html(
        kind="protein", data_source=data_source, subject="this plot"
    )
    said = _text(block)
    assert f"Data source: {label}" in said, said
    assert "Filtering:" in said, said
    assert "Imputation:" in said, said
    # Order is part of the contract: what was used, then which rows, then which values.
    assert (
        said.index("Data source:") < said.index("Filtering:") < said.index("Imputation:")
    ), said


def test_an_unknown_source_falls_back_to_data_rather_than_inventing_a_label() -> None:
    said = _text(
        _data_provenance_html(kind="protein", data_source="log2", subject="this plot")
    )
    assert "Data source: Data" in said


@pytest.mark.parametrize("data_source", ["data", "filtered"])
def test_a_non_imputed_plot_says_so_explicitly(data_source: str) -> None:
    said = _text(
        _data_provenance_html(kind="protein", data_source=data_source, subject="this plot")
    )
    assert "Not applied; this plot uses the non-imputed data" in said


def test_a_projection_states_how_much_of_the_matrix_reached_it() -> None:
    """A PCA is complete-case, and the report used not to say so.

    The panel showed it; the report did not, so a reader with only the document
    could not tell that a tenth of the proteins never entered the figure.
    """
    block = _data_provenance_html(
        kind="protein",
        data_source="data",
        subject="this plot",
        completeness=_pca_completeness_description("protein", "data"),
    )
    said = _text(block)
    assert "Features used:" in said, said
    assert "%" in said and "complete across every sample" in said, said
    assert said.index("Imputation:") < said.index("Features used:"), (
        "the completeness qualifies the matrix named above it"
    )


def test_the_completeness_sentence_counts_the_matrix_that_was_asked_for() -> None:
    """Filtering changes the denominator, so the share has to move with it."""
    unfiltered = _pca_completeness_description("protein", "data")
    filtered = _pca_completeness_description("protein", "filtered")
    assert unfiltered and filtered, (unfiltered, filtered)
    assert unfiltered != filtered, (
        "filtering removes rows, so the denominator and the share must move"
    )


@pytest.mark.parametrize("complete,used", [(3, 3), (4, 3), (3, 2), (4, 4)])
def test_pca_wording_covers_missingness_and_constant_features(monkeypatch, complete, used):
    from app.services import report_function as module

    monkeypatch.setattr(module, "qc_pca_feature_summary", lambda *a, **k: {
        "featuresTotal": 4, "featuresComplete": complete, "featuresUsed": used,
    })
    description = module._pca_completeness_description("protein", "data")
    assert f"{used} of 4 features" in description
    assert "showed variation" in description
    if used < 4:
        assert f"remaining {4 - used} were excluded because of missing values or no variation" in description
    else:
        assert "excluded" not in description


def test_a_source_this_project_does_not_have_says_nothing(monkeypatch) -> None:
    """Silence rather than a number from a matrix that is not there.

    The shipped example has no imputed matrix; asking for one must not produce
    a completeness sentence describing some other matrix.
    """
    assert _pca_completeness_description("protein", "imputed") == ""
    assert _pca_completeness_description("protein", "not-a-source") == ""


def test_unfiltered_pca_distinguishes_configured_filtering_from_applied_filtering() -> None:
    """Two descriptions of one filter would eventually disagree.

    Levels legitimately differ from each other; what must not differ is the
    preamble and a plot block within the same level.
    """
    from app.services.report_function import _filter_description

    report_html = _report_with_pca_source("data")
    expected = _filter_description(get_annotation("protein")).strip()

    preamble = re.search(r"<strong>Filtering:</strong>\s*([^<]+)", report_html)
    assert preamble is not None and preamble.group(1).strip() == expected

    in_pca = re.search(
        r"<strong>Filtering:</strong>\s*([^<]+)", _pca_block(report_html)
    )
    assert in_pca is not None, "the PCA block should carry its own filtering line"
    # A plot that skipped the filter states that, with the row counts, rather
    # than repeating the recipe the preamble already gives.
    annotation = get_annotation("protein")
    assert in_pca.group(1).strip() == (
        f"Not applied to this plot; it uses all {len(annotation.source_data)} rows. "
        f"(The filtered matrix used by other sections of this report keeps "
        f"{len(annotation.filtered_data)} rows.)"
    ), f"the PCA block describes the filter differently:\n  pca: {in_pca.group(1).strip()}"


# --- PCA gets what the volcano gets ------------------------------------------


def _report_with_pca_source(source: str) -> str:
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/summary/report",
            json={
                "title": "PCA",
                "author": "A",
                "reportContext": {
                    "qcSettings": {"protein": {"pca": {"dataSource": source}}}
                },
            },
        )
    assert response.status_code == 200, response.text
    return response.json()["html"]


def _pca_block(report_html: str) -> str:
    """The PCA section itself, not its table-of-contents entry."""
    match = re.search(r"<h2[^>]*>[^<]*PCA Plot</h2>", report_html)
    assert match is not None, "no PCA section in the report"
    rest = report_html[match.end() :]
    end = re.search(r"<h2[^>]*>", rest)
    return rest[: end.start() if end else 4000]


@pytest.mark.parametrize(
    "source,expected", [("data", "Data"), ("imputed", "Imputed Data")]
)
def test_the_pca_block_states_its_own_source_and_filtering(
    source: str, expected: str
) -> None:
    block = _pca_block(_report_with_pca_source(source))
    said = _text(block)
    assert f"Data source: {expected}" in said, said[:400]
    assert "Filtering:" in said, "a PCA is built from the rows that survived the filter"
    assert "Imputation:" in said


def test_an_imputed_pca_describes_the_settings_it_used() -> None:
    with recorded_imputation("protein", QUANTILE):
        said = _text(_pca_block(_report_with_pca_source("imputed")))
        assert "Imputed Data" in said
        assert "0.01" in said and "0.3" in said, f"the settings never reached the PCA block: {said[:400]}"
        assert "seed" not in said


def _sections(report_html: str, heading: str) -> list[str]:
    """Every h2 section whose heading ends with `heading`, up to the next h2."""
    sections = []
    for match in re.finditer(rf"<h2[^>]*>[^<]*{re.escape(heading)}</h2>", report_html):
        rest = report_html[match.end():]
        end = re.search(r"<h2[^>]*>", rest)
        sections.append(rest[: end.start() if end else len(rest)])
    return sections


def test_the_pca_and_volcano_blocks_are_built_by_the_same_function(monkeypatch) -> None:
    """Pins the shape rather than the wording, so the two cannot drift apart.

    The shared block builder is wrapped so that everything it returns carries an
    invisible marker. A report with a PCA at both levels and a volcano must
    then show the marker, once, in each of the three sections; a section that
    writes its provenance some other way has none.
    """
    from app.services import report_function as module

    marker = "<!-- shared provenance block -->"
    real = module._data_provenance_html
    monkeypatch.setattr(module, "_data_provenance_html", lambda **kwargs: marker + real(**kwargs))

    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/summary/report", json={
            "title": "T", "author": "A",
            "reportContext": {
                "qcSettings": {"protein": {"pca": {"dataSource": "data"}}, "phospho": {"pca": {"dataSource": "data"}}},
                "volcanoEntries": [{"kind": "protein", "condition1": "WT", "condition2": "GRK"}],
            },
        })
    assert response.status_code == 200, response.text
    report_html = response.json()["html"]

    pca_sections = _sections(report_html, "PCA Plot")
    volcano_sections = _sections(report_html, "Volcano Plot")
    assert len(pca_sections) == 2, "expected a PCA section at the protein and the phosphosite level"
    assert len(volcano_sections) == 1
    for name, section in [("protein PCA", pca_sections[0]), ("phosphosite PCA", pca_sections[1]),
                          ("volcano", volcano_sections[0])]:
        assert section.count(marker) == 1, f"the {name} section does not use the shared provenance block"
        said = _text(section[section.index(marker):])
        assert said.index("Data source:") < said.index("Filtering:") < said.index("Imputation:"), name
