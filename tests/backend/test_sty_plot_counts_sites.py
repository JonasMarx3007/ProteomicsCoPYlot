"""The S/T/Y plot says what it counts.

One bar counts rows of the phosphosite matrix: one row is one site identifier.
A doubly phosphorylated peptide is two rows and is counted twice, so calling
the figure "peptide counts" overstated how many peptides were seen and
understated nothing -- a reader comparing it with the peptide-level numbers
elsewhere in the tool got two different answers to what looked like one
question.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import phospho_tools
from app.services.runtime_cache import invalidate_runtime_cache

FRONTEND = ROOT / "frontend" / "src"
SERVICES = ROOT / "backend" / "app" / "services"


def _title(monkeypatch: pytest.MonkeyPatch, keys: list[str], *, header: bool = True) -> str:
    captured: dict[str, str] = {}

    def capture(fig, *args, **kwargs) -> bytes:
        captured["title"] = fig.axes[0].get_title()
        fig.clear()
        return b"png"

    monkeypatch.setattr(
        phospho_tools, "_phospho_context", lambda: (pd.DataFrame({"PTM_Collapse_key": keys}), pd.DataFrame(), [])
    )
    monkeypatch.setattr(phospho_tools, "_to_png_bytes", capture)
    invalidate_runtime_cache("test")
    try:
        phospho_tools.phospho_sty_png(header=header)
    finally:
        invalidate_runtime_cache("test")
    return captured["title"]


# Two sites on one peptide: two rows, two bars' worth of count, one peptide.
TWO_SITES_ONE_PEPTIDE = ["PEP~GENE_S1_1", "PEP~GENE_T5_1"]


def test_the_title_says_sites_not_peptides(monkeypatch: pytest.MonkeyPatch) -> None:
    title = _title(monkeypatch, TWO_SITES_ONE_PEPTIDE)
    assert title == "Modified S/T/Y site counts"
    assert "peptide" not in title.lower()


def test_the_bars_really_count_rows_and_not_peptides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Why the old wording was wrong, stated as a number."""
    monkeypatch.setattr(
        phospho_tools,
        "_phospho_context",
        lambda: (pd.DataFrame({"PTM_Collapse_key": TWO_SITES_ONE_PEPTIDE}), pd.DataFrame(), []),
    )
    invalidate_runtime_cache("test")
    try:
        table = phospho_tools.phospho_sty_table()
    finally:
        invalidate_runtime_cache("test")
    counts = dict(zip(table["Residue"], table["Count"]))
    assert counts["S"] == 1 and counts["T"] == 1
    assert int(table["Count"].sum()) == 2, "two sites, one peptide"


def test_the_header_toggle_still_removes_the_title(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _title(monkeypatch, TWO_SITES_ONE_PEPTIDE, header=False) == ""


def test_the_old_wording_survives_nowhere_the_user_can_read_it() -> None:
    """The summary report and the frontend were checked for the same string."""
    offenders = []
    for path in list(SERVICES.glob("*.py")) + list(FRONTEND.rglob("*.ts")) + list(FRONTEND.rglob("*.tsx")):
        text = path.read_text(encoding="utf-8")
        if "S/T/Y peptide count" in text or "S/T/Y Peptide Count" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "the S/T/Y plot is still called a peptide count in: " + ", ".join(offenders)
