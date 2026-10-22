"""Fail closed for new operations while preserving the reviewed API surface."""
import json
from pathlib import Path

import pytest

from app.services.viewer_policy import VIEWER_ALLOWED_OPERATIONS, auth_route, viewer_request_allowed

BLOCKED = frozenset({
    ('POST', '/api/annotations/generate'),
    ('DELETE', '/api/annotations/metadata/current/{kind}'),
    ('POST', '/api/annotations/metadata/upload'),
    ('POST', '/api/annotations/normalize'),
    ('PUT', '/api/annotations/pairing'),
    ('POST', '/api/annotations/phosprot/aggregate'),
    ('POST', '/api/annotations/phosprot/upload'),
    ('POST', '/api/chat/models/install'),
    ('POST', '/api/chat/models/remove'),
    ('POST', '/api/data-tools/condition-colors/{kind}'),
    ('POST', '/api/data-tools/id-translation/download'),
    ('POST', '/api/data-tools/id-translation/run'),
    ('POST', '/api/data-tools/imputation/download'),
    ('POST', '/api/data-tools/imputation/run'),
    ('POST', '/api/datasets/metadata/profiles/create'),
    ('DELETE', '/api/datasets/metadata/profiles/delete'),
    ('POST', '/api/datasets/metadata/profiles/rename'),
    ('POST', '/api/datasets/packages/create'),
    ('POST', '/api/datasets/packages/rename'),
    ('POST', '/api/datasets/peptide-file'),
    ('POST', '/api/datasets/peptide-path'),
    ('POST', '/api/datasets/table-path'),
    ('POST', '/api/datasets/upload'),
    ('POST', '/api/external/peptide-collapse/upload'),
    ('DELETE', '/api/peptide/metadata/current'),
    ('POST', '/api/peptide/metadata/generate'),
    ('GET', '/api/plots/notebooks/{token}.zip'),
    ('POST', '/api/restore/export'),
    ('POST', '/api/restore/import'),
})


def test_every_current_operation_has_an_explicit_decision():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "frontend/src/lib/generated/openapi.json").read_text())
    served = {(method.upper(), path) for path, operations in schema["paths"].items()
              for method in operations if method in {"get", "post", "put", "patch", "delete", "head", "options"}}
    assert VIEWER_ALLOWED_OPERATIONS.isdisjoint(BLOCKED)
    assert served == VIEWER_ALLOWED_OPERATIONS | BLOCKED


@pytest.mark.parametrize("method,path", sorted(VIEWER_ALLOWED_OPERATIONS))
def test_allowed_operations_and_redirects(method, path):
    path = path.replace("{kind}", "protein").replace("{provider}", "openai").replace("{direction}", "up").replace("{version}", "3.0.0").replace("{progress_id}", "abc123")
    assert viewer_request_allowed(method, path)
    assert viewer_request_allowed(method, path + "/")


@pytest.mark.parametrize("method,path", sorted(BLOCKED))
def test_blocked_operations(method, path):
    assert not viewer_request_allowed(method, path)
    assert not viewer_request_allowed(method, path + "/")


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/new-route"), ("POST", "/api/new-route"),
    ("GET", "/api/plots/qc/protein/new-plot.png"),
    ("POST", "/api/chat/new-action"), ("GET", "/api/viewer/auth/new-action"),
    ("POST", "/api/health"), ("DELETE", "/api/datasets/current"),
    ("POST", "/api/chat/cloud-consent/openai/grant/extra"),
    ("POST", "/api/chat/cloud-consent/openai/extra/grant"),
    ("GET", "/api/runtime/plotly-3.0.0.js/extra"),
])
def test_unreviewed_operations_are_denied(method, path):
    assert not viewer_request_allowed(method, path)


def test_auth_exceptions_are_exact():
    assert auth_route("/api/viewer/auth/login/")
    assert not auth_route("/api/viewer/auth/new-action")
    assert not auth_route("/api/tool/auth/login/extra")
