"""Every PNG/HTML plot route must accept the request fields it builds a model from.

FastAPI silently drops query parameters a route does not declare, so a field the
frontend sends but the route omits falls back to the model default without any
error. That is how `/stats/{kind}/ora/{direction}.png` came to draw an ANOVA
cluster with `average` linkage while the table beside it used the linkage the
user chose. This test derives the contract from the code: for each route in
`plots_*.py` (the `routes_plots` modules) that constructs a request model, every field of that model
that a client can set must be a parameter of the route, unless it is listed here
as deliberately fixed.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ROUTES = sorted((ROOT / "backend" / "app" / "api").glob("plots_*.py"))  # one module per URL prefix

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
    for path in ROUTES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") in {"get", "post"} for d in node.decorator_list
            ):
                yield node


def test_every_plot_route_declares_the_request_fields_it_builds() -> None:
    models = _request_models()
    problems: list[str] = []
    checked: set[str] = set()
    for route in _route_functions():
        params = {a.arg for a in route.args.args + route.args.kwonlyargs}
        for call in ast.walk(route):
            if not isinstance(call, ast.Call):
                continue
            constructor = call.func
            if (isinstance(constructor, ast.Attribute) and constructor.attr == "model_validate"
                    and len(call.args) == 1 and isinstance(call.args[0], ast.Call)
                    and isinstance(call.args[0].func, ast.Name) and call.args[0].func.id == "dict"):
                constructor, call = constructor.value, call.args[0]
            if not (isinstance(constructor, ast.Name) and constructor.id in models):
                continue
            # Only routes that build the model from individual parameters are
            # checked; a route taking the model as its body already gets every field.
            if any(isinstance(k.value, ast.Name) and k.value.id in params and k.arg is None for k in call.keywords):
                continue
            checked.add(route.name)
            fields = set(models[constructor.id].model_fields)
            passed = {k.arg for k in call.keywords if k.arg}
            missing = fields - passed - FIXED_FIELDS.get(route.name, set())
            if missing:
                problems.append(f"{route.name} builds {constructor.id} without {sorted(missing)}")
    assert {"stats_anova_route", "stats_ora_route", "stats_simulation_route"} <= checked
    assert not problems, "\n".join(problems)
