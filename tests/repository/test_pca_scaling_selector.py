"""The feature-scaling selector names the scaling, and offers each one once.

There are two scalings. Centred weights a feature by its variance; unit variance
gives every feature equal weight. They answer different questions, which is why
the control exists at all.

The selector used to offer three entries: "Method default (centred)", "Centred
only" and "Unit variance". For PCA the first two are the same scaling under two
names, and for UMAP and t-SNE the duplicate pair is the first and the third
instead -- so whichever method was selected, one of the three options was a
synonym of another, and picking between them looked like a decision.

`auto` still exists in the API and in saved states. It just is not a thing a
person can choose, because it is not a third scaling.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

PAGE = ROOT / "frontend" / "src" / "features" / "qc" / "QCPipelinePage.tsx"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_selector_offers_exactly_the_two_scalings() -> None:
    source = _source()
    assert 'const SCALING_LABELS = ["Centred", "Unit variance"] as const;' in source
    assert "options={[...SCALING_LABELS]}" in source


def test_method_default_is_no_longer_an_option() -> None:
    source = _source()
    assert "Method default" not in source, (
        "for every method it equals one of the other two entries, so it put the "
        "same scaling in the list twice"
    )
    assert "Centred only" not in source, "the 'only' distinguished it from 'method default'"


def test_switching_method_moves_the_scaling_to_that_method_s_default() -> None:
    """The label names a scaling now, so it cannot quietly mean something else.

    PCA is conventionally run centred and UMAP/t-SNE on unit variance. With
    "Method default" in the list, switching method changed what that entry meant
    and the label followed. Naming the scaling means the *selection* has to move
    instead, or a UMAP would silently run on PCA's convention.
    """
    source = _source()
    assert "scaling: methodDefaultScaling(nextMethod)," in source
    assert re.search(
        r'function methodDefaultScaling\(method: string\): string \{\s*'
        r'return pcaMethodLabel\(method\) === "PCA" \? "centered" : "unit_variance";',
        source,
    ), "the frontend default must match resolve_feature_scaling on the backend"


def test_the_frontend_and_the_backend_agree_on_each_method_s_default() -> None:
    """Two implementations of one convention; they have to give one answer."""
    from app.services.functions import resolve_feature_scaling

    assert resolve_feature_scaling("auto", method="PCA") == "centered"
    assert resolve_feature_scaling("auto", method="UMAP") == "unit_variance"
    assert resolve_feature_scaling("auto", method="t-SNE") == "unit_variance"


def test_auto_is_still_accepted_so_a_saved_state_keeps_working() -> None:
    """Nothing writes it any more; states written before this change hold it."""
    from app.services.functions import resolve_feature_scaling

    assert resolve_feature_scaling("auto") == "centered"
    source = _source()
    assert 'key === "centered" || key === "centred"' in source, (
        "scalingLabel has to map a stored value, including the resolved form of "
        "auto, back onto one of the two labels"
    )
