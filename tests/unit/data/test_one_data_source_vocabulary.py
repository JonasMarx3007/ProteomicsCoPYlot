"""One vocabulary, one resolver, and QC has no say in the matter.

The rule, decided 2026-09-15:

* **QC describes the data as loaded.** No selector: coverage, boxplot, CV,
  histogram, correlation, missing-value, completeness and *comparison* always
  read the annotated matrix, on whatever scale the statistic is defined on. PCA
  is the one exception, because it cannot use incomplete features.
* **PCA, the statistics modules, ORA and single-protein choose**, from
  `data | filtered | imputed`, offering only what exists.
* **`"data"` is the annotated log2 matrix, everywhere.** It used to mean the
  filtered matrix through one resolver and the unfiltered one through the
  other, so the same request returned 11,580 rows on the statistics path and
  11,916 on the visualization path with nothing in the response to say which.
* **The default is the most processed matrix available**, imputed > filtered >
  data, decided by the backend so two pages cannot disagree.

Nothing falls back. Every source names one matrix and raises when it is absent,
because a substituted matrix produces real numbers under the wrong label.

The browser half -- every selector offers exactly what the backend reports,
Comparison and the non-PCA QC plots offer none, and a restored choice that
still exists is kept -- is tested by mounting the pages:
frontend/tests/unit/data-source-options.test.tsx.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Literal, get_args, get_origin

import pytest


from app.main import app
from app.schemas.annotation import DataSource, ResolvedSource
from app.services import functions
from app.services.analysis_matrix import DATA_SOURCES, data_source_options, most_processed_data_source, qc_matrix, select_matrix


CHOOSING_MODULES = [
    ("volcano", "/api/stats/volcano/run", {}),
    ("anova", "/api/stats/anova/run", {"source": "anova"}),
    ("anova cluster", "/api/stats/anova/run", {"source": "anova_cluster", "nClusters": 3}),
    ("ora", "/api/stats/ora/run", {"source": "volcano", "direction": "up"}),
    ("simulation", "/api/stats/simulation/run", {}),
]


# --- one vocabulary ----------------------------------------------------------


def _source_literals():
    """Every module-level Literal in the schemas and services naming a matrix, by binding."""
    import app.schemas as schemas_package
    import app.services as services_package

    for package in (schemas_package, services_package):
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{info.name}")
            for name, value in vars(module).items():
                if get_origin(value) is Literal and {"filtered", "imputed"} & set(get_args(value)):
                    yield f"{module.__name__}.{name}", name, value


def test_the_vocabulary_is_defined_once() -> None:
    """Four copies of these Literals is how they drifted apart.

    Read from the imported modules: only the three names exist, and every
    module that binds one of them binds the same type -- a second definition
    with other members would be a second object here.
    """
    found = list(_source_literals())
    # PhosprotAggregationSource is a different question entirely -- which
    # phosphosite matrix a collapse was built from -- and merely shares a word.
    found = [entry for entry in found if entry[1] != "PhosprotAggregationSource"]
    names = {name for _, name, _ in found}
    assert names <= {"DataSource", "ResolvedSource", "ChosenSource"}, sorted(where for where, _, _ in found)
    for name in names:
        values = {id(value) for _, bound, value in found if bound == name}
        assert len(values) == 1, f"{name} is bound to {len(values)} different types: " + ", ".join(
            sorted(f"{where}={get_args(value)}" for where, bound, value in found if bound == name)
        )


def test_the_request_vocabulary_is_exactly_three_names() -> None:
    from typing import get_args

    assert DATA_SOURCES == ("data", "filtered", "imputed")
    assert set(get_args(DataSource)) == set(DATA_SOURCES)
    assert "auto" not in get_args(ResolvedSource), "auto was the ambiguity"


def test_there_is_one_resolver() -> None:
    """The two that disagreed are gone, not deprecated in place."""
    for retired in ("analysis_data_source", "_visualization_data_source",
                    "resolve_data_source_choice", "DATA_SOURCE_CHOICES"):
        assert not hasattr(functions, retired), f"{retired} is still importable"
    assert callable(select_matrix)


@pytest.mark.parametrize("source", DATA_SOURCES)
def test_a_request_names_one_matrix_or_raises(client, source: str) -> None:
    available = data_source_options("protein")["availableDataSources"]
    if source in available:
        used, frame, _ = select_matrix("protein", source)
        assert used == source
        assert not frame.empty
    else:
        with pytest.raises(ValueError, match="not available"):
            select_matrix("protein", source)


def test_data_is_the_annotated_matrix_not_the_filtered_one(client) -> None:
    """The single change that makes the vocabulary unambiguous."""
    _, unfiltered, _ = select_matrix("protein", "data")
    _, filtered, _ = select_matrix("protein", "filtered")
    assert len(unfiltered) > len(filtered), "the example project filters something out"


# --- QC has no say -----------------------------------------------------------


QC_ENDPOINTS = [
    "/api/plots/qc/{kind}/coverage-table",
    "/api/plots/qc/{kind}/boxplot-table",
    "/api/plots/qc/{kind}/cv-table",
    "/api/data-tools/completeness/{kind}/tables",
    "/api/plots/comparison/{kind}/options",
]


@pytest.mark.parametrize("endpoint", QC_ENDPOINTS)
def test_no_qc_endpoint_accepts_a_data_source(client, endpoint: str) -> None:
    """A QC surface that could be pointed elsewhere is not describing the data.

    FastAPI ignores unknown query parameters, so this checks the signature
    rather than the response: the parameter must not exist to be honoured.
    """
    spec = app.openapi()["paths"].get(endpoint)
    assert spec is not None, f"no route registered at {endpoint}"
    for method, operation in spec.items():
        names = {p["name"] for p in operation.get("parameters", [])}
        assert "dataSource" not in names, (
            f"{method.upper()} {endpoint} offers a choice QC should not have"
        )


def test_qc_and_comparison_read_the_same_matrix(client) -> None:
    """Pearson and the correlation heatmap have to be comparable."""
    from app.services import comparison_tools

    frame, _ = qc_matrix("protein")
    comparison_frame, _, _ = comparison_tools._analysis_context("protein")
    assert len(comparison_frame) == len(frame)


def test_the_coverage_table_counts_the_matrix_as_loaded(client) -> None:
    """The discrepancy that started this: 7,410 in one place, 7,404 in another.

    The other place was GET /api/qc/summary, which summarised the filtered
    matrix. No page called it and it was removed on 2026-10-02; the coverage
    table still has to count the data as loaded.
    """
    import pandas as pd

    from app.services.data_tools import _get_sample_columns

    for kind in ("protein", "phospho"):
        rows = pd.DataFrame(client.get(f"/api/plots/qc/{kind}/coverage-table").json()["rows"])
        per_sample = rows[~rows["Sample"].isin(["All samples", "Identified, not quantified"])]
        counted = sorted(int(value) for value in per_sample["Number"])
        frame, _ = qc_matrix(kind)
        numeric = frame[_get_sample_columns(kind, frame)].apply(pd.to_numeric, errors="coerce")
        measured = sorted(int(value) for value in numeric.notna().sum())
        assert counted == measured, f"{kind}: coverage-table says {counted[:3]}..., the loaded matrix has {measured[:3]}..."
        total = int(rows.loc[rows["Sample"] == "All samples", "Number"].iloc[0])
        assert total == int(numeric.notna().any(axis=1).sum())


def test_qc_reads_through_the_one_resolver(client) -> None:
    """So QC cannot drift away from what "data" means elsewhere."""
    frame, metadata = qc_matrix("protein")
    used, direct, direct_meta = select_matrix("protein", "data")
    assert used == "data"
    assert frame.equals(direct)
    assert metadata.equals(direct_meta)


# --- the modules that choose -------------------------------------------------


@pytest.mark.parametrize("name,endpoint,extra", CHOOSING_MODULES, ids=[c[0] for c in CHOOSING_MODULES])
def test_every_statistics_module_honours_its_own_selection(
    client, name: str, endpoint: str, extra: dict
) -> None:
    """ORA included: it carries its own slider rather than inheriting one."""
    seen = {}
    for source in ("data", "filtered"):
        response = client.post(endpoint, json={
            "kind": "protein", "condition1": "WT", "condition2": "GRK",
            "testType": "unpaired_welch", "dataSource": source, **extra,
        })
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert body["sourceUsed"] == source, f"{name} ignored dataSource={source}"
        seen[source] = body.get("totalRows") or body.get("backgroundSize")
    assert seen["data"] != seen["filtered"], (
        f"{name} reports the same size for both matrices, so the selection did nothing"
    )


def test_the_pca_is_the_one_qc_plot_that_chooses(client) -> None:
    for source in data_source_options("protein")["availableDataSources"]:
        response = client.get(
            "/api/plots/qc/protein/pca-features", params={"dataSource": source}
        )
        assert response.status_code == 200, response.text[:200]


# --- the ladder --------------------------------------------------------------


def test_the_default_is_the_most_processed_matrix_available(client) -> None:
    options = data_source_options("protein")
    assert options["defaultDataSource"] == most_processed_data_source("protein")
    assert options["defaultDataSource"] == options["availableDataSources"][-1], (
        "availableDataSources is in ladder order, so the default is its last entry"
    )


@pytest.mark.parametrize("kind", ["protein", "phospho", "phosprot"])
def test_every_selector_endpoint_serves_the_same_ladder(client, kind) -> None:
    """One payload shape, so no page has to work the ladder out itself."""
    payloads = [
        client.get(f"/api/plots/qc/{kind}/options").json(),
        client.get(f"/api/stats/options/{kind}").json(),
        client.get(f"/api/plots/single-protein/{kind}/options").json(),
    ]
    if kind == "phospho":
        payloads.append(client.get("/api/plots/phospho/options").json())
    for payload in payloads:
        assert payload["availableDataSources"] == payloads[0]["availableDataSources"]
        assert payload["defaultDataSource"] == payloads[0]["defaultDataSource"]
