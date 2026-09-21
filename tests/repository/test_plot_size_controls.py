"""Width, height and DPI are one system, not eight copies of one.

Every plot in the tool is sized the same way: the same three controls in the
same order, with the same labels, the same limits, and the same behaviour when
a saved value is unusable. That only stays true if there is exactly one place
each of those decisions is made.

The failures these tests are here to catch have all happened at least once:

* a second `SizeRow` grown on one page, rendering DPI before width, so the same
  three fields sat in a different order depending on which plot you opened;
* a call site re-clamping with its own floor (`Math.max(5, value)`), so one page
  refused a 3 cm figure the backend would have drawn;
* a size restored with a bare `Number(...)`, turning a missing or malformed
  saved value into `0`, which reaches the backend as a 0 cm figure;
* the UI limits drifting away from the ones the backend enforces, so the panel
  happily offers a size the request then rejects.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

SRC = ROOT / "frontend" / "src"
PLOT_FIELDS = SRC / "components" / "PlotFields.tsx"
PLOT_LIMITS = SRC / "lib" / "plotLimits.ts"

# Files that hold a plot's width/height/DPI state.
SIZED_PAGES = sorted(
    path
    for path in (SRC / "features").rglob("*.tsx")
    if "widthCm" in path.read_text(encoding="utf-8")
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_pages_that_size_plots_are_the_ones_this_file_checks() -> None:
    """A new sized page must join the sweep below, not slip past it."""
    assert SIZED_PAGES, "no page holds plot size state -- the search is broken"
    names = {path.name for path in SIZED_PAGES}
    assert "QCPipelinePage.tsx" in names, names


def test_only_one_size_row_is_implemented() -> None:
    definitions = [
        path
        for path in SRC.rglob("*.tsx")
        if re.search(r"^(export )?function SizeRow\(", _read(path), re.MULTILINE)
    ]
    assert definitions == [PLOT_FIELDS], (
        "SizeRow must live in components/PlotFields.tsx alone; a second copy is "
        f"how the field order drifted last time: {[p.name for p in definitions]}"
    )


def test_the_other_entry_point_re_exports_rather_than_re_implements() -> None:
    """QC pages import from QcFields; that name must be the same component."""
    qc_fields = _read(SRC / "components" / "QcFields.tsx")
    assert 'export { SizeRow } from "./PlotFields";' in qc_fields


def test_every_sized_page_uses_the_shared_row() -> None:
    for path in SIZED_PAGES:
        source = _read(path)
        assert "<SizeRow" in source, f"{path.name} sizes a plot without the shared row"
        assert re.search(r"import \{[^}]*\bSizeRow\b", source), (
            f"{path.name} renders SizeRow without importing it"
        )


def test_no_page_clamps_a_size_at_the_call_site() -> None:
    """SizeRow clamps. A second clamp on top of it is a second set of limits."""
    offenders: list[str] = []
    pattern = re.compile(r"\b(widthCm|heightCm|dpi)\s*:\s*Math\.")
    for path in [*SIZED_PAGES, PLOT_FIELDS]:
        for number, line in enumerate(_read(path).splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "these call sites impose their own limits instead of the shared ones:\n"
        + "\n".join(offenders)
    )


def test_every_saved_size_is_restored_through_the_shared_helpers() -> None:
    """`Number(saved ?? 20)` turns `null` into `0`, a 0 cm figure."""
    offenders: list[str] = []
    bare = re.compile(r"Number\(\s*persisted\w*\.(widthCm|heightCm|dpi)")
    for path in SIZED_PAGES:
        source = _read(path)
        for number, line in enumerate(source.splitlines(), start=1):
            if bare.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
        if "widthCm:" in source:
            assert "restorePlotDimensionCm(" in source, (
                f"{path.name} restores a width without the shared guard"
            )
        if "dpi:" in source and "dpi={" in source:
            assert "restorePlotDpi(" in source, (
                f"{path.name} restores a DPI without the shared guard"
            )
    assert not offenders, "unguarded size restores:\n" + "\n".join(offenders)


def test_the_row_asks_for_width_then_height_then_dpi() -> None:
    source = _read(PLOT_FIELDS)
    body = source[source.index("export function SizeRow(") :]
    body = body[: body.index("\n}\n")]
    width = body.index('label="Width (cm)"')
    height = body.index('label="Height (cm)"')
    dpi = body.index('label="DPI"')
    assert width < height < dpi, "the shared row changed the order every page shows"
    assert body.count("clampPlotDimensionCm(") == 2, "width and height clamp alike"
    assert body.count("clampPlotDpi(") == 1


def test_the_ui_limits_are_the_limits_the_backend_enforces() -> None:
    from app.services import plot_limits as backend

    source = _read(PLOT_LIMITS)

    def constant(name: str) -> float:
        match = re.search(rf"export const {name} = ([0-9_.]+);", source)
        assert match, f"{name} is gone from plotLimits.ts"
        return float(match.group(1).replace("_", ""))

    assert constant("MIN_PLOT_DIMENSION_CM") == backend.MIN_PLOT_WIDTH_CM
    assert constant("MAX_PLOT_DIMENSION_CM") == backend.MAX_PLOT_WIDTH_CM
    assert constant("MIN_PLOT_DIMENSION_CM") == backend.MIN_PLOT_HEIGHT_CM
    assert constant("MAX_PLOT_DIMENSION_CM") == backend.MAX_PLOT_HEIGHT_CM
    assert constant("MIN_PLOT_DPI") == backend.MIN_PLOT_DPI
    assert constant("MAX_PLOT_DPI") == backend.MAX_PLOT_DPI
    assert constant("MAX_PLOT_PIXELS") == backend.MAX_PLOT_PIXELS
    assert constant("HTML_LAYOUT_DPI") == backend.HTML_LAYOUT_DPI


def test_the_restore_helpers_refuse_what_the_backend_would_refuse() -> None:
    """Read the guards' behaviour off the source: fallback, then clamp."""
    source = _read(PLOT_LIMITS)
    for helper in ("restorePlotDimensionCm", "restorePlotDpi"):
        body = source[source.index(f"export function {helper}(") :]
        body = body[: body.index("\n}\n")]
        assert "Number.isFinite(parsed)" in body, f"{helper} accepts a non-number"
        assert "null" in body and "undefined" in body, (
            f"{helper} must fall back rather than turn a missing value into 0"
        )
        clamp = "clampPlotDimensionCm(" if helper.endswith("Cm") else "clampPlotDpi("
        assert body.count(clamp) == 2, (
            f"{helper} must clamp both the fallback and the saved value"
        )
