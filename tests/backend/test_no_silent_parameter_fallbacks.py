from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.routes_plots import _table_rows
from app.main import app
from app.services.viewer_bootstrap import load_viewer_state

API = ROOT / "backend" / "app" / "api"
ROUTE_FILES = sorted(API.glob("routes_*.py"))


def test_table_rows_serializes_missing_categorical_values() -> None:
    frame = pd.DataFrame({"group": pd.Categorical(["A", None])})

    assert _table_rows(frame) == {"rows": [{"group": "A"}, {"group": ""}]}


ENUM_PROBES = [
    ("/api/plots/qc/protein/pca.png", "plotDim", "9D", "3D", {}),
    ("/api/plots/qc/protein/pca.png", "colorBy", "NOT_A_FIELD", "Condition", {}),
    ("/api/plots/qc/protein/pca.png", "method", "NOT_A_METHOD", "PCA", {}),
    ("/api/plots/qc/protein/pca.png", "clusterMethod", "NOT_A_CLUSTER", "None", {}),
    ("/api/plots/qc/protein/pca.png", "dataSource", "NOT_A_SOURCE", "log2", {}),
    ("/api/plots/qc/protein/pca.png", "scaling", "NOT_A_SCALING", "auto", {}),
    ("/api/plots/qc/protein/boxplot.png", "mode", "NOT_A_MODE", "Single", {}),
    ("/api/plots/qc/protein/correlation.png", "method", "NOT_A_METHOD", "Matrix", {}),
    ("/api/plots/imputation/protein/overall-fit.png", "method", "NOT_A_METHOD", "quantile", {}),
    ("/api/plots/single-protein/protein/options", "tab", "NOT_A_TAB", "lineplot", {}),
    ("/api/plots/single-protein/protein/options", "identifier", "NOT_AN_ID", "genes", {}),
    ("/api/plots/phospho/coverage-table", "mode", "NOT_A_MODE", "Summary", {}),
]

REJECTION_ONLY_PROBES = [
    ("/api/plots/comparison/protein/pearson.png", "mode", "NOT_A_MODE"),
    ("/api/plots/comparison/protein/venn.png", "mode", "NOT_A_MODE"),
    ("/api/plots/single-protein/protein/heatmap-table", "valueType", "NOT_A_TYPE"),
    ("/api/plots/stats/protein/pathway-heatmap.png", "valueType", "NOT_A_TYPE"),
    ("/api/plots/peptide/rt.png", "method", "NOT_A_METHOD"),
    ("/api/plots/phospho/phosprot-regulation-table", "testType", "NOT_A_TEST"),
    ("/api/plots/phospho/ksea-table", "testType", "NOT_A_TEST"),
    ("/api/plots/stats/protein/ora/up.png", "backgroundMode", "NOT_A_MODE"),
]

ENUMERATED_PARAMETER_NAMES = {
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


@pytest.fixture(scope="module")
def client():
    load_viewer_state(ROOT / "viewer_config.json")
    with TestClient(app) as test_client:
        yield test_client


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
    REJECTION_ONLY_PROBES,
    ids=[f"{p.rsplit('/', 1)[-1]}:{n}" for p, n, _ in REJECTION_ONLY_PROBES],
)
def test_an_unrecognised_enum_value_is_rejected_without_full_context(
    client, path: str, parameter: str, invalid: str
) -> None:
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


def _route_parameters() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for route_file in ROUTE_FILES:
        found.extend(_parameters_in(route_file))
    return found


def _parameters_in(route_file) -> list[tuple[str, str, str]]:
    tree = ast.parse(route_file.read_text(encoding="utf-8"))
    source = route_file.read_text(encoding="utf-8").splitlines()
    found: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        path = None
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and decorator.args:
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    path = first.value
        if path is None:
            continue
        for arg in node.args.args:
            if arg.annotation is None:
                continue
            text = ast.get_source_segment("\n".join(source), arg.annotation) or ""
            found.append((path, arg.arg, text.strip()))
    return found


# Enumerated parameters still typed as bare `str`, where the service layer rather
# than the schema rejects a bad value. Each was probed directly: every one returns
# 400 or 422 for an unrecognised value, so none of them silently falls back to a
# default. They are listed per (route, parameter) rather than by name, because a
# probe on one route proves nothing about another. Typing them with the matching
# Literal alias would move rejection to the schema and let them be deleted here.
SERVICE_VALIDATED = {
    ("/stats/{kind}/volcano.html", "dataSource"),
    ("/stats/{kind}/volcano-control.html", "dataSource"),
    ("/stats/{kind}/anova.png", "dataSource"),
    ("/stats/{kind}/ora/{direction}.png", "dataSource"),
    ("/stats/{kind}/ora/{direction}.png", "backgroundMode"),
    ("/stats/{kind}/pathway-heatmap.png", "dataSource"),
    ("/stats/{kind}/pathway-heatmap.png", "valueType"),
    ("/stats/{kind}/simulation.html", "dataSource"),
    ("/qc/{kind}/pca-features", "dataSource"),
    ("/qc/{kind}/pca.png", "dataSource"),
    ("/qc/{kind}/pca.png", "clusterMethod"),
    ("/qc/{kind}/pca-interactive.html", "dataSource"),
    ("/qc/{kind}/pca-interactive.html", "clusterMethod"),
    ("/single-protein/{kind}/heatmap.png", "valueType"),
    ("/single-protein/{kind}/heatmap-table", "valueType"),
    ("/phospho/ksea.png", "dataSource"),
    ("/phospho/ksea.png", "testType"),
    ("/phospho/ksea-table", "dataSource"),
    ("/phospho/ksea-table", "testType"),
    ("/phospho/phosprot-regulation.png", "testType"),
    ("/phospho/phosprot-regulation.html", "testType"),
    ("/phospho/phosprot-regulation-table", "testType"),
}


def test_enumerated_route_parameters_are_typed_or_probed() -> None:
    probed = {(path, name) for path, name, _, _, _ in ENUM_PROBES}
    probed |= {(path, name) for path, name, _ in REJECTION_ONLY_PROBES}

    offenders = [
        (path, name)
        for path, name, annotation in _route_parameters()
        if name in ENUMERATED_PARAMETER_NAMES
        and name not in OPEN_VALUED_PARAMETERS
        and annotation == "str"
        and (path, name) not in probed
        and (path, name) not in SERVICE_VALIDATED
    ]
    assert not offenders, (
        "these enumerated route parameters are typed as bare `str` and no probe "
        "proves the service rejects a bad value, so an unexpected value will "
        "silently produce the default:\n  "
        + "\n  ".join(f"{path}  ->  {name}" for path, name in offenders)
    )


@pytest.mark.parametrize(
    "path,parameter,companions",
    [
        ("/api/plots/stats/protein/volcano.html", "dataSource", {"condition1": "A", "condition2": "B"}),
        ("/api/plots/stats/protein/ora/up.png", "backgroundMode", {"condition1": "A", "condition2": "B"}),
        ("/api/plots/qc/protein/pca.png", "clusterMethod", {}),
        ("/api/plots/phospho/ksea.png", "testType", {"condition1": "A", "condition2": "B"}),
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
    parameters = _route_parameters()
    assert len(parameters) > 100, f"only {len(parameters)} route parameters parsed"
    assert any(name == "plotDim" for _, name, _ in parameters)


ACCEPTED_KIND_ANNOTATIONS = {
    "AnnotationKind",
    "CompletenessDatasetKind",
    "MetadataAnnotationKind",
    "DatasetKind",
}


def _kind_annotations() -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in sorted(API.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(isinstance(d, ast.Call) and d.args for d in node.decorator_list):
                continue
            for arg in node.args.args:
                if arg.arg == "kind" and arg.annotation is not None:
                    annotation = (ast.get_source_segment(source, arg.annotation) or "").strip()
                    found.append((path.name, node.name, annotation))
    return found


def test_every_route_types_kind_from_the_shared_alias() -> None:
    offenders = [
        (f, fn, ann)
        for f, fn, ann in _kind_annotations()
        if ann not in ACCEPTED_KIND_ANNOTATIONS
    ]
    assert not offenders, (
        "these routes do not type `kind` from the shared alias, so the valid set is "
        "either unvalidated or duplicated and free to drift:\n  "
        + "\n  ".join(f"{f}:{fn}  ->  {ann}" for f, fn, ann in offenders)
    )


def test_the_kind_scanner_finds_the_expected_routes() -> None:
    annotations = _kind_annotations()
    assert len(annotations) > 40, f"only {len(annotations)} kind parameters parsed"


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
