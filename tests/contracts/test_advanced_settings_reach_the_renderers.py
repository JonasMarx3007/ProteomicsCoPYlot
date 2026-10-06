"""Every advanced plot setting is read by a renderer, and no other setting is.

The advanced panel writes its settings into one JSON query parameter and the
renderers read them out of a plain dict, so neither side's spelling is checked
by FastAPI. A key the panel writes and no renderer reads is a card that does
nothing when used; a key a renderer reads and nobody declares is a setting
nobody can set. Both were once found only by reading the source with regular
expressions.

`AdvancedPlotSettings` (backend/app/schemas/plot_settings.py) is the declared
vocabulary. The frontend is held to it at compile time and by the panel sweep in
frontend/tests/component/advanced-panel-keys.test.tsx. This is the renderer
side: the plot routes draw the example project with every declared key set, and
every key they look up is recorded.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from typing import Any, get_args, get_origin

import pytest
from pydantic import BaseModel

from app.api import routes_plots
from app.services.notebook_provenance import NotebookProvenanceError
from app.services.runtime_cache import invalidate_runtime_cache
from app.schemas.plot_settings import ADVANCED_PLOT_SETTING_KEYS, AdvancedPlotSettings

C1, C2 = "WT", "GRK"
CONDITIONS = json.dumps([C1, C2])


class RecordingSettings(dict):
    """The parsed settings, noting every key a renderer asks for."""

    read: set[str] = set()

    def get(self, key: Any, default: Any = None) -> Any:
        RecordingSettings.read.add(key)
        return super().get(key, default)

    def __getitem__(self, key: Any) -> Any:
        RecordingSettings.read.add(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        RecordingSettings.read.add(key)  # type: ignore[arg-type]
        return super().__contains__(key)


def _sample_value(name: str, annotation: Any) -> Any:
    """A value of the declared type that differs from every plot's default."""
    options = [a for a in get_args(annotation) if a is not type(None)] or [annotation]
    kind = options[0]
    if get_origin(kind) is not None and str(get_origin(kind)).endswith("Literal"):
        return get_args(kind)[-1]
    if get_origin(kind) is dict:
        # Keyed by a group no plot has: the map is looked up, and every group
        # still falls through to the general setting, which is then read too.
        return {"no-such-group": _sample_value(name, get_args(kind)[1])}
    if isinstance(kind, type) and issubclass(kind, BaseModel):
        # Offset too: a nudged title or axis label once made every interactive
        # plot and the missing-value heatmap refuse to draw.
        return {"text": "Styled", "size": 11, "xOffset": 2, "yOffset": 2, "bold": True, "italic": True,
                "color": "#123456"}
    if kind is bool:
        return True
    if kind is float:
        if "Alpha" in name:
            return 0.7
        # The value-label offsets are in data units; one bar's width moves a
        # label off the canvas.
        return 0.1 if name.startswith("text") else 3.0
    if "Color" in name:
        return "#123456"
    if name == "correlationColorMap":
        return "viridis"
    return "Styled"


def _every_setting() -> dict[str, Any]:
    return {
        name: _sample_value(name, field.annotation)
        for name, field in AdvancedPlotSettings.model_fields.items()
    }


# (route, query parameters). Each draws a different renderer, with the options
# on that make it draw the parts the styling applies to: value labels, row
# names, the per-condition point groups, the labelled volcano hits.
ROUTES: list[tuple[str, dict[str, Any]]] = [
    ("/stats/protein/volcano.html", {"condition1": C1, "condition2": C2}),
    ("/stats/protein/volcano.png", {"condition1": C1, "condition2": C2, "labelTopUp": 3, "labelTopDown": 3}),
    ("/stats/protein/anova.png", {"source": "anova_cluster", "showRowLabels": True, "nClusters": 2, "pValueThreshold": 0.001}),
    ("/stats/protein/ora/up.png", {"condition1": C1, "condition2": C2}),
    ("/stats/protein/simulation.html", {"condition1": C1, "condition2": C2}),
    ("/imputation/protein/before-missing.png", {}),
    ("/imputation/protein/overall-fit.png", {}),
    ("/imputation/protein/after-imputation.png", {}),
    ("/distribution/protein/qqnorm.png", {}),
    ("/completeness/protein/missing-value.png", {}),
    ("/completeness/protein/missing-heatmap.png", {}),
    ("/qc/protein/coverage.png", {"text": True, "summary": True}),
    ("/qc/protein/intensity-histogram.png", {}),
    ("/qc/protein/boxplot.png", {"outliers": True}),
    ("/qc/protein/cv.png", {}),
    ("/qc/protein/pca.png", {}),
    ("/qc/protein/pca-interactive.html", {}),
    ("/qc/protein/abundance.png", {}),
    ("/qc/protein/abundance-interactive.html", {}),
    ("/qc/protein/correlation.png", {}),
    ("/phospho/phosphosite-plot.png", {}),
    ("/phospho/coverage.png", {}),
    ("/phospho/distribution.png", {}),
    ("/phospho/phosprot-regulation.html", {"condition1": C1, "condition2": C2}),
    ("/phospho/sty.png", {}),
    ("/comparison/protein/pearson.png", {"mode": "Condition", "condition1": C1, "condition2": C2}),
    ("/comparison/protein/pearson.html", {"mode": "Condition", "condition1": C1, "condition2": C2}),
    ("/comparison/protein/venn.png", {"mode": "Condition", "first": C1, "second": C2}),
]


def _notebook_modules() -> list[Any]:
    import app.services as services

    return [
        importlib.import_module(f"app.services.{info.name}")
        for info in pkgutil.iter_modules(services.__path__)
        if info.name.startswith("notebook_") and info.name != "notebook_provenance"
    ]


def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
    raise NotebookProvenanceError("forced by the settings sweep")


@pytest.fixture(scope="module")
def recorded(client) -> dict[str, Any]:
    original = routes_plots.parse_advanced_plot_settings
    patch = pytest.MonkeyPatch()
    patch.setattr(
        routes_plots, "parse_advanced_plot_settings", lambda raw: RecordingSettings(original(raw))
    )
    RecordingSettings.read = set()
    advanced = json.dumps(_every_setting())
    failures: dict[str, str] = {}
    try:
        protein = client.get("/api/plots/single-protein/protein/options").json()["proteins"][0]
        phospho_protein = client.get(
            "/api/plots/single-protein/phospho/options", params={"tab": "heatmap"}
        ).json()["proteins"][0]
        contrast = {"condition1": C1, "condition2": C2}
        token = client.get("/api/plots/stats/protein/ora/up.png", params=contrast).headers["x-copylot-notebook"]
        terms = client.get(
            "/api/plots/stats/protein/ora/up/tables", params={**contrast, "snapshot": token}
        ).json()["upTerms"]
        pathway = str(terms[0]["name"])
        samples = client.get("/api/plots/comparison/protein/options").json()["samples"]
        routes = [
            *ROUTES,
            ("/comparison/protein/venn.png",
             {"mode": "Single", "first": samples[0], "second": samples[1], "third": samples[2]}),
            ("/single-protein/protein/boxplot.png",
             {"protein": protein, "conditions": CONDITIONS, "dots": True, "outliers": True, "sampleN": True}),
            ("/single-protein/protein/lineplot.png", {"proteins": json.dumps([protein]), "conditions": CONDITIONS}),
            ("/single-protein/phospho/heatmap.png", {"protein": phospho_protein, "conditions": CONDITIONS}),
            ("/stats/protein/pathway-heatmap.png", {"pathway": pathway, "conditions": CONDITIONS}),
        ]
        for path, params in routes:
            response = client.get(f"/api/plots{path}", params={**params, "advanced": advanced})
            if response.status_code != 200:
                failures[path] = response.text[:300]
        # Most figures are drawn by an exported notebook built from the same
        # renderer source, and the settings reach it as a plain dict. Drawing
        # each again on the direct path, which every such route falls back to,
        # lets the recorder see those renderers too.
        for module in _notebook_modules():
            for name in dir(module):
                if name.startswith("render_"):
                    patch.setattr(module, name, _unavailable)
        # The first pass's figures are cached under the same arguments.
        invalidate_runtime_cache("settings-sweep", all_sessions=True)
        for path, params in routes:
            client.get(f"/api/plots{path}", params={**params, "advanced": advanced})
    finally:
        patch.undo()
    return {"read": set(RecordingSettings.read), "failures": failures}


def test_every_route_drew_its_plot(recorded) -> None:
    """A route that failed read nothing, and would hide a key from the checks below."""
    assert not recorded["failures"], json.dumps(recorded["failures"], indent=1)


def test_the_renderers_read_only_declared_settings(recorded) -> None:
    undeclared = sorted(key for key in recorded["read"] if key not in ADVANCED_PLOT_SETTING_KEYS)
    assert not undeclared, (
        "renderers read settings AdvancedPlotSettings does not declare, so nothing "
        f"can set them: {undeclared}"
    )


def test_every_declared_setting_is_read_by_a_renderer(recorded) -> None:
    unread = sorted(ADVANCED_PLOT_SETTING_KEYS - recorded["read"])
    assert not unread, (
        f"no renderer read these settings, so setting them changes nothing: {unread}"
    )
