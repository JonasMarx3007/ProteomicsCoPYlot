"""Write the backend's OpenAPI schema for the frontend's generated types.

    python tools/export_openapi.py          # rewrite frontend/src/lib/generated/{openapi,plotLimits}.json
    npm --prefix frontend run generate:api  # both steps: this, then the TypeScript types

The frontend's request and response types are checked against the generated
`api.d.ts` at compile time (frontend/src/lib/apiContract.ts), so a backend
field or enum the frontend does not know about fails `npm run build` instead of
a regex over source files. tests/contracts/test_generated_api_is_current.py
fails when this file is stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "frontend" / "src" / "lib" / "generated"
OUTPUT = GENERATED / "openapi.json"
LIMITS_OUTPUT = GENERATED / "plotLimits.json"
LIMIT_NAMES = (
    "MIN_PLOT_WIDTH_CM", "MAX_PLOT_WIDTH_CM", "MIN_PLOT_HEIGHT_CM", "MAX_PLOT_HEIGHT_CM",
    "MIN_PLOT_DPI", "MAX_PLOT_DPI", "MAX_PLOT_PIXELS", "HTML_LAYOUT_DPI",
)


def schema() -> dict:
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    from app.main import app
    from app.schemas.plot_settings import AdvancedPlotSettings

    document = app.openapi()
    # The `advanced` query parameter is a JSON string to FastAPI, so its shape
    # is added here for the frontend's types and the panel's tests.
    settings = AdvancedPlotSettings.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(settings.pop("$defs", {}))
    schemas["AdvancedPlotSettings"] = settings
    return document


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_limits() -> str:
    """The plot size limits the backend enforces, for the frontend to clamp to.

    frontend/src/lib/plotLimits.ts reads its constants from this file, so the
    panel cannot offer a size the request would then be refused for.
    """
    sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
    from app.services import plot_limits

    return json.dumps({name: getattr(plot_limits, name) for name in LIMIT_NAMES}, indent=2) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    LIMITS_OUTPUT.write_text(render_limits(), encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} and {LIMITS_OUTPUT.relative_to(ROOT)}")
