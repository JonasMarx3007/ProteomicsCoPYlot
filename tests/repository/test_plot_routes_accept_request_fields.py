"""Every PNG/HTML plot route must accept the request fields it builds a model from.

FastAPI silently drops query parameters a route does not declare, so a field the
frontend sends but the route omits falls back to the model default without any
error. That is how `/stats/{kind}/ora/{direction}.png` came to draw an ANOVA
cluster with `average` linkage while the table beside it used the linkage the
user chose. This test derives the contract from the code: for each route in
`routes_plots.py` that constructs a request model, every field of that model
that a client can set must be a parameter of the route, unless it is listed here
as deliberately fixed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

ROUTES = ROOT / "backend" / "app" / "api" / "routes_plots.py"

# Fields a plot route may legitimately not expose, with the reason.
FIXED_FIELDS: dict[str, set[str]] = {
    # A heatmap has no post-hoc comparison to draw.
    "stats_anova_route": {"postHoc", "postHocCondition1", "postHocCondition2"},
}


def _request_models() -> dict[str, type]:
    from app.schemas import analysis, completeness, data_tools, peptide, qc, stats

    models: dict[str, type] = {}
    for module in (analysis, completeness, data_tools, peptide, qc, stats):
        for name in dir(module):
            candidate = getattr(module, name)
            if isinstance(candidate, type) and hasattr(candidate, "model_fields") and name.endswith("Request"):
                models[name] = candidate
    return models


def _route_functions():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") in {"get", "post"} for d in node.decorator_list
        ):
            yield node


def test_every_plot_route_declares_the_request_fields_it_builds() -> None:
    models = _request_models()
    problems: list[str] = []
    for route in _route_functions():
        params = {a.arg for a in route.args.args + route.args.kwonlyargs}
        for call in ast.walk(route):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in models):
                continue
            # Only routes that build the model from individual parameters are
            # checked; a route taking the model as its body already gets every field.
            if any(isinstance(k.value, ast.Name) and k.value.id in params and k.arg is None for k in call.keywords):
                continue
            fields = set(models[call.func.id].model_fields)
            passed = {k.arg for k in call.keywords if k.arg}
            missing = fields - passed - FIXED_FIELDS.get(route.name, set())
            if missing:
                problems.append(f"{route.name} builds {call.func.id} without {sorted(missing)}")
    assert not problems, "\n".join(problems)
