"""The S/T/Y plot says what it counts.

One bar counts rows of the phosphosite matrix: one row is one site identifier.
A doubly phosphorylated peptide is two rows and is counted twice, so calling
the figure "peptide counts" overstated how many peptides were seen and
understated nothing -- a reader comparing it with the peptide-level numbers
elsewhere in the tool got two different answers to what looked like one
question.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services import phospho_tools
from app.services.runtime_cache import invalidate_runtime_cache


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


OLD_WORDING = ("s/t/y peptide count",)


def test_the_exported_notebook_does_not_call_it_a_peptide_count(example_project) -> None:
    """The notebook export of the S/T/Y plot is text the user reads and reruns.

    The plot is rendered through the same capture the app's export button uses,
    the archive is built, and every file in it is read: the notebook, the
    function source it ships and the manifest. The figure it reproduces has to
    carry the site wording too.
    """
    import io
    import json
    from zipfile import ZipFile

    from app.services.notebook_archive import build_notebook_archive
    from app.services.notebook_phospho import render_sty
    from app.services.notebook_snapshots import snapshots
    from app.services.session_context import get_session_id

    invalidate_runtime_cache("test")
    _, token = render_sty()
    assert token, "the S/T/Y plot was not captured for the notebook export"
    _, payload = build_notebook_archive(snapshots.get(get_session_id(), token))
    offenders = []
    with ZipFile(io.BytesIO(payload)) as archive:
        texts = {
            name: archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith((".py", ".ipynb", ".json", ".md", ".txt"))
        }
    for name, text in texts.items():
        if any(old in text.lower() for old in OLD_WORDING):
            offenders.append(name)
    assert not offenders, "the exported S/T/Y notebook still says peptide count in: " + ", ".join(offenders)
    notebook = next(json.loads(text) for name, text in texts.items() if name.endswith(".ipynb"))
    assert notebook["cells"], "the export has no notebook cells"
    assert "Modified S/T/Y site counts" in texts["functions.py"]
