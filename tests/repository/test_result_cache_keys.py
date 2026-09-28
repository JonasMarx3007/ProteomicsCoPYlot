"""A cached analysis result is keyed by the whole request that produced it.

Every analysis panel keeps one result and a key, and shows the result only when
the key matches the request it is currently displaying. That is the right shape:
a result computed for other settings simply does not match, so a stale figure is
impossible.

It only works if the key describes the *whole* request. When the key and the
request are written out as two separate object literals they can drift, and the
drift is invisible: the ANOVA panel's request gained `postHocCondition1` and
`postHocCondition2` and its key did not, so a Tukey result could never equal the
key it had just been stored under. `result` stayed null, the derived `running`
flag stayed true, and the panel showed "Running the ANOVA and the Tukey HSD
post-hoc... it can take a minute" for as long as the user was willing to wait,
over a response that had already arrived. The wording made the hang look like
the slowness it warns about.

Two rules, both checked here:

* the key a panel stores is the same expression it compares against; and
* every field in a request appears in that request's key.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "frontend" / "src" / "features"
ANOVA_PANEL = FEATURES / "stats" / "AnovaPanel.tsx"
ORA_PANEL = FEATURES / "stats" / "OraPanel.tsx"

KEYED = sorted(
    path
    for path in FEATURES.rglob("*.tsx")
    if "setResultState({" in path.read_text(encoding="utf-8")
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _field_names(block: str) -> set[str]:
    """Object keys in a literal: `name,` or `name: value`, comments removed."""
    lines = [line for line in block.splitlines() if not line.strip().startswith("//")]
    text = "\n".join(lines)
    return set(re.findall(r"^\s*([A-Za-z_]\w*)\s*[,:]", text, re.M))


def test_there_are_panels_to_check() -> None:
    assert KEYED, "no panel stores a keyed result -- the search is broken"


@pytest.mark.parametrize("path", KEYED, ids=lambda path: path.name)
def test_every_stored_key_is_the_key_the_panel_compares_against(path: Path) -> None:
    source = _source(path)
    stored = [
        expression.strip()
        for expression in re.findall(
            r"setResultState\(\{\s*key:\s*(.+?),\s*data:", source, re.S
        )
    ]
    assert stored, f"{path.name} matched the search but stores no key"
    compared = set(re.findall(r"resultState\?\.key === (\w+)", source))
    allowed = compared | {
        "JSON.stringify({ revision, ...debouncedRequestPayload })",
        "JSON.stringify({ revision, ...requestPayload })",
    }
    unexpected = [expression for expression in stored if expression not in allowed]
    assert not unexpected, (
        f"{path.name} stores a key built some other way: {unexpected}. It has to "
        "be the expression the panel compares against, or the request spread."
    )


# (name, where the request literal starts, where it ends, where the key block is)
STATS_PANELS = [
    (
        "ANOVA",
        ANOVA_PANEL,
        "const requestPayload = useMemo<AnovaRequest | null>",
        "const currentResultKey = requestPayload",
        "const currentResultKey = requestPayload",
    ),
    (
        "ORA",
        ORA_PANEL,
        "runEnrichmentAnalysis({",
        "} satisfies EnrichmentRequest",
        "const currentResultKey = JSON.stringify({",
    ),
]


@pytest.mark.parametrize(
    "name,panel,start,end,key_anchor", STATS_PANELS, ids=lambda value: str(value)[:12]
)
def test_every_request_field_is_in_that_request_key(
    name: str, panel: Path, start: str, end: str, key_anchor: str
) -> None:
    source = _source(panel)
    request = source[source.index(start) : source.index(end, source.index(start))]
    fields = _field_names(request) - {"revision"}
    key_start = source.index(key_anchor)
    if "...requestPayload" in source[key_start : key_start + 200]:
        return  # derived from the request; it cannot omit a field
    key = source[key_start : source.index("});", key_start)]
    key_fields = _field_names(key)
    # `source: sourceMode` in the request is `sourceMode` in the key; both name
    # the same state, so accept either spelling.
    aliases = {"source": "sourceMode", "sourceMode": "source"}
    missing = {
        field
        for field in fields
        if field not in key_fields and aliases.get(field) not in key_fields
    }
    assert not missing, (
        f"{name}: these are sent in the request and absent from its cache key, "
        f"so a result computed with them can never be displayed: {sorted(missing)}"
    )


def test_the_anova_key_is_derived_from_its_request() -> None:
    """The specific regression, pinned by shape rather than by field list."""
    source = _source(ANOVA_PANEL)
    start = source.index("const requestPayload = useMemo<AnovaRequest | null>")
    request = source[start : source.index("const currentResultKey", start)]
    assert "postHocCondition1" in request and "postHocCondition2" in request
    key_block = source[
        source.index("const currentResultKey", start) : source.index("const result =", start)
    ]
    assert "...requestPayload" in key_block, (
        "the ANOVA key must spread the request, so the post-hoc pair is in it"
    )


def test_the_running_message_is_derived_from_the_same_result() -> None:
    """`running` says 'still working'; it must mean it."""
    source = _source(ANOVA_PANEL)
    assert "const running = Boolean(requestPayload) && !result && !error;" in source, (
        "if `running` stops being derived from `result`, the panel can claim to "
        "be working while holding the answer, or the reverse"
    )
