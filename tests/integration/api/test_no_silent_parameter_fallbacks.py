from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.api.plot_responses import table_rows
from app.main import app

def test_table_rows_serializes_missing_categorical_values() -> None:
    frame = pd.DataFrame({"group": pd.Categorical(["A", None])})

    assert table_rows(frame) == {"rows": [{"group": "A"}, {"group": ""}]}


ENUM_PROBES = [
    ("/api/plots/qc/protein/pca.png", "plotDim", "9D", "3D", {}),
    ("/api/plots/qc/protein/pca.png", "colorBy", "NOT_A_FIELD", "Condition", {}),
    ("/api/plots/qc/protein/pca.png", "method", "NOT_A_METHOD", "PCA", {}),
    ("/api/plots/qc/protein/pca.png", "clusterMethod", "NOT_A_CLUSTER", "None", {}),
    ("/api/plots/qc/protein/pca-features", "clusterMethod", "NOT_A_CLUSTER", "None", {}),
    ("/api/plots/qc/protein/pca-features", "plotDim", "9D", "3D", {}),
    ("/api/plots/qc/protein/pca-features", "colorBy", "NOT_A_FIELD", "Condition", {}),
    ("/api/plots/qc/protein/pca-features", "scaling", "NOT_A_SCALING", "auto", {}),
    ("/api/plots/qc/protein/pca.png", "dataSource", "NOT_A_SOURCE", "data", {}),
    ("/api/plots/qc/protein/pca.png", "scaling", "NOT_A_SCALING", "auto", {}),
    ("/api/plots/qc/protein/boxplot.png", "mode", "NOT_A_MODE", "Single", {}),
    ("/api/plots/qc/protein/correlation.png", "method", "NOT_A_METHOD", "Matrix", {}),
    ("/api/plots/imputation/protein/overall-fit.png", "method", "NOT_A_METHOD", "quantile", {}),
    ("/api/plots/single-protein/protein/options", "tab", "NOT_A_TAB", "lineplot", {}),
    ("/api/plots/single-protein/protein/options", "identifier", "NOT_AN_ID", "genes", {}),
    ("/api/plots/phospho/coverage-table", "mode", "NOT_A_MODE", "Summary", {}),
]

# Companions come from the bundled viewer_config.json the fixture loads, so a
# probe that needs real conditions, samples or a pathway can still be paired with
# test_every_valid_value_still_works. Without that pairing an "is it rejected?"
# probe passes on any non-200 -- including the 422 for a missing companion -- and
# so cannot tell a rejected enum from an incomplete request.
WT, GRK = "WT", "GRK"
SAMPLE_1 = "[6] 20240822_nElute_tims1_JM_HEK293_WP_WT_1_Slot1-61_1_8064.d.PG.Log2Quantity"
SAMPLE_2 = "[7] 20240822_nElute_tims1_JM_HEK293_WP_WT_2_Slot1-62_1_8065.d.PG.Log2Quantity"
A_PATHWAY = "mitochondrial genome maintenance"

ENUM_PROBES += [
    ("/api/plots/comparison/protein/pearson.png", "mode", "NOT_A_MODE", "Single",
     {"sample1": SAMPLE_1, "sample2": SAMPLE_2}),
    ("/api/plots/comparison/protein/venn.png", "mode", "NOT_A_MODE", "Single",
     {"first": SAMPLE_1, "second": SAMPLE_2}),
    ("/api/plots/single-protein/phospho/heatmap-table", "valueType", "NOT_A_TYPE", "log2",
     {"protein": "AAAS", "identifier": "genes"}),
    ("/api/plots/stats/protein/pathway-heatmap.png", "valueType", "NOT_A_TYPE", "z",
     {"pathway": A_PATHWAY}),
    ("/api/plots/phospho/phosprot-regulation-table", "testType", "NOT_A_TEST", "unpaired",
     {"condition1": WT, "condition2": GRK}),
    ("/api/plots/phospho/ksea-table", "testType", "NOT_A_TEST", "unpaired",
     {"condition1": WT, "condition2": GRK}),
    ("/api/plots/stats/protein/ora/up.png", "backgroundMode", "NOT_A_MODE", "experiment",
     {"condition1": WT, "condition2": GRK}),
]

# The bundled state sets "peptide_file": "none", so every value of this parameter
# -- valid or not -- returns the same 400 for the missing dataset and no probe
# here can tell them apart. Listed separately rather than left among the paired
# probes so the file does not claim coverage it has not got.
UNDISCRIMINATED_WITHOUT_A_PEPTIDE_DATASET = [
    ("/api/plots/peptide/rt.png", "method", "NOT_A_METHOD"),
]

ENUMERATED_PARAMETER_NAMES = {
    "direction",
    "plotDim",
    "colorBy",
    "clusterMethod",
    "valueType",
    "tab",
    "identifier",
    "dataSource",
    "scaling",
    "backgroundMode",
    "testType",
}

OPEN_VALUED_PARAMETERS = {
    "method",
    "mode",
    "condition",
    "protease",
    "source",
}


@pytest.mark.parametrize(
    ("path", "parameter", "invalid", "valid", "companions"),
    ENUM_PROBES,
    ids=[f"{p.rsplit('/', 1)[-1]}:{n}" for p, n, _, _, _ in ENUM_PROBES],
)
def test_an_unrecognised_enum_value_is_rejected(
    client, path: str, parameter: str, invalid: str, valid: str, companions: dict
) -> None:
    response = client.get(path, params={**companions, parameter: invalid})
    assert response.status_code != 200, (
        f"{path} accepted {parameter}={invalid!r} and returned a result. The value "
        "was not recognised, so the response shows a default rather than what was "
        "requested, with no error."
    )


@pytest.mark.parametrize(
    ("path", "parameter", "invalid"),
    UNDISCRIMINATED_WITHOUT_A_PEPTIDE_DATASET,
    ids=[f"{p.rsplit('/', 1)[-1]}:{n}" for p, n, _ in UNDISCRIMINATED_WITHOUT_A_PEPTIDE_DATASET],
)
def test_a_route_without_its_dataset_still_refuses_rather_than_defaulting(
    client, path: str, parameter: str, invalid: str
) -> None:
    """Weak by construction: it cannot separate a rejected enum from a missing dataset.

    Kept because a 200 here would be a real defect, but it is not evidence that
    the enum is validated. Loading a peptide dataset into the fixture is what
    would turn this into a paired probe.
    """
    response = client.get(path, params={parameter: invalid})
    assert response.status_code != 200, (
        f"{path} accepted {parameter}={invalid!r} and returned a result."
    )


@pytest.mark.parametrize(
    ("path", "parameter", "invalid", "valid", "companions"),
    ENUM_PROBES,
    ids=[f"{p.rsplit('/', 1)[-1]}:{n}" for p, n, _, _, _ in ENUM_PROBES],
)
def test_every_valid_value_still_works(
    client, path: str, parameter: str, invalid: str, valid: str, companions: dict
) -> None:
    response = client.get(path, params={**companions, parameter: valid})
    assert response.status_code == 200, (
        f"{path} rejected the valid value {parameter}={valid!r}: "
        f"{response.status_code} {response.text[:160]}"
    )


def _openapi_parameters() -> list[tuple[str, str, dict]]:
    """Every (path template, parameter name, schema) the API publishes.

    Read from the OpenAPI document FastAPI generates from the routes' type
    annotations, which is the same contract the request validator enforces: a
    parameter typed with a Literal alias carries an `enum`, one typed as a bare
    `str` is a plain string with no enum.
    """
    found: list[tuple[str, str, dict]] = []
    for path, operations in app.openapi()["paths"].items():
        for operation in operations.values():
            for parameter in operation.get("parameters", []):
                found.append((path, parameter["name"], parameter.get("schema", {})))
    return found


def _is_bare_string(schema: dict) -> bool:
    # `str | None` is published as anyOf and was never counted as bare here.
    return schema.get("type") == "string" and "enum" not in schema


def _template_matches(template: str, concrete: str) -> bool:
    pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template))
    return re.fullmatch(pattern, concrete) is not None


# Enumerated parameters still typed as bare `str`, where the service layer rather
# than the schema rejects a bad value. Each was probed directly: every one returns
# 400 or 422 for an unrecognised value, so none of them silently falls back to a
# default. They are listed per (route, parameter) rather than by name, because a
# probe on one route proves nothing about another. Typing them with the matching
# Literal alias would move rejection to the schema and let them be deleted here.
SERVICE_VALIDATED = {
    ("/api/plots/stats/{kind}/volcano.html", "dataSource"),
    ("/api/plots/stats/{kind}/volcano-control.html", "dataSource"),
    ("/api/plots/stats/{kind}/anova.png", "dataSource"),
    ("/api/plots/stats/{kind}/ora/{direction}.png", "dataSource"),
    ("/api/plots/stats/{kind}/ora/{direction}.png", "backgroundMode"),
    ("/api/plots/stats/{kind}/pathway-heatmap.png", "dataSource"),
    ("/api/plots/stats/{kind}/pathway-heatmap.png", "valueType"),
    ("/api/plots/stats/{kind}/simulation.html", "dataSource"),
    ("/api/plots/qc/{kind}/pca-features", "dataSource"),
    ("/api/plots/qc/{kind}/pca-features", "clusterMethod"),
    ("/api/plots/qc/{kind}/pca.png", "dataSource"),
    ("/api/plots/qc/{kind}/pca.png", "clusterMethod"),
    ("/api/plots/qc/{kind}/pca-interactive.html", "dataSource"),
    ("/api/plots/qc/{kind}/pca-interactive.html", "clusterMethod"),
    ("/api/plots/single-protein/{kind}/heatmap.png", "valueType"),
    ("/api/plots/single-protein/{kind}/heatmap-table", "valueType"),
    ("/api/plots/phospho/ksea-table", "dataSource"),
    ("/api/plots/phospho/ksea-table", "testType"),
    ("/api/plots/phospho/phosprot-regulation.html", "testType"),
    ("/api/plots/phospho/phosprot-regulation-table", "testType"),
}


def test_enumerated_route_parameters_are_typed_or_probed() -> None:
    probes = [(path, name) for path, name, _, _, _ in ENUM_PROBES]
    probes += [(path, name) for path, name, _ in UNDISCRIMINATED_WITHOUT_A_PEPTIDE_DATASET]

    def probed(template: str, name: str) -> bool:
        return any(
            probe_name == name and _template_matches(template, probe_path)
            for probe_path, probe_name in probes
        )

    offenders = [
        (path, name)
        for path, name, schema in _openapi_parameters()
        if name in ENUMERATED_PARAMETER_NAMES
        and name not in OPEN_VALUED_PARAMETERS
        and _is_bare_string(schema)
        and not probed(path, name)
        and (path, name) not in SERVICE_VALIDATED
    ]
    assert not offenders, (
        "these enumerated route parameters are typed as bare `str` and no probe "
        "proves the service rejects a bad value, so an unexpected value will "
        "silently produce the default:\n  "
        + "\n  ".join(f"{path}  ->  {name}" for path, name in offenders)
    )


def test_every_service_validated_entry_names_a_published_parameter() -> None:
    """An entry for a route or parameter that no longer exists excuses nothing."""
    published = {(path, name) for path, name, _ in _openapi_parameters()}
    stale = sorted(SERVICE_VALIDATED - published)
    assert not stale, f"SERVICE_VALIDATED names parameters the API does not publish: {stale}"


@pytest.mark.parametrize(
    "path,parameter,companions",
    [
        ("/api/plots/stats/protein/volcano.html", "dataSource", {"condition1": "A", "condition2": "B"}),
        ("/api/plots/stats/protein/ora/up.png", "backgroundMode", {"condition1": "A", "condition2": "B"}),
        ("/api/plots/qc/protein/pca.png", "clusterMethod", {}),
        ("/api/plots/phospho/ksea-table", "testType", {"condition1": "A", "condition2": "B"}),
        ("/api/plots/single-protein/protein/heatmap.png", "valueType", {"protein": "X"}),
    ],
)
def test_service_validated_parameters_really_do_reject(
    client, path: str, parameter: str, companions: dict[str, str]
) -> None:
    response = client.get(path, params={**companions, parameter: "NOT_A_REAL_VALUE"})
    assert response.status_code in (400, 422), (
        f"{path} accepted {parameter}='NOT_A_REAL_VALUE' with {response.status_code}; "
        f"SERVICE_VALIDATED claims the service rejects it, so either that claim is "
        f"stale or this parameter now silently falls back to a default"
    )


def test_the_route_scanner_actually_finds_parameters() -> None:
    parameters = _openapi_parameters()
    assert len(parameters) > 100, f"only {len(parameters)} route parameters published"
    assert any(name == "plotDim" for _, name, _ in parameters)


def _accepted_kind_value_sets() -> dict[str, tuple[str, ...]]:
    from app.schemas.annotation import AnnotationKind, MetadataAnnotationKind
    from app.schemas.dataset import CompletenessDatasetKind, DatasetKind

    return {
        "AnnotationKind": get_args(AnnotationKind),
        "CompletenessDatasetKind": get_args(CompletenessDatasetKind),
        "MetadataAnnotationKind": get_args(MetadataAnnotationKind),
        "DatasetKind": get_args(DatasetKind),
    }


def _kind_parameters() -> list[tuple[str, dict]]:
    return [(path, schema) for path, name, schema in _openapi_parameters() if name == "kind"]


def test_every_route_types_kind_from_the_shared_alias() -> None:
    """Every route's published `kind` is exactly one of the shared aliases' value sets.

    A route typing `kind` as a bare `str` publishes no enum, so its valid set is
    unvalidated; one typing it with its own copy of a Literal publishes a set
    that drifts from the alias as soon as the alias changes. Either shows up
    here as a published enum that matches no shared alias.
    """
    accepted = {tuple(sorted(values)) for values in _accepted_kind_value_sets().values()}
    offenders = [
        (path, schema.get("enum", "no enum: bare str"))
        for path, schema in _kind_parameters()
        if tuple(sorted(schema.get("enum", ()))) not in accepted
    ]
    assert not offenders, (
        "these routes do not type `kind` from the shared alias, so the valid set is "
        "either unvalidated or duplicated and free to drift:\n  "
        + "\n  ".join(f"{path}  ->  {enum}" for path, enum in offenders)
    )


def test_the_kind_scanner_finds_the_expected_routes() -> None:
    annotations = _kind_parameters()
    assert len(annotations) > 40, f"only {len(annotations)} kind parameters published"


@pytest.mark.parametrize(
    "path",
    [
        "/api/plots/qc/{kind}/coverage.png",
        "/api/plots/completeness/{kind}/missing-value.png",
        "/api/plots/qc/{kind}/pca.png",
    ],
)
def test_an_unknown_kind_is_rejected_at_the_schema(client, path: str) -> None:
    response = client.get(path.replace("{kind}", "NOT_A_KIND"))
    assert response.status_code == 422, (
        f"{path} answered {response.status_code} for an unknown kind; every route "
        "should reject it at the schema so the OpenAPI enum documents the valid set"
    )
