"""Explanatory boxes and provenance fields that were removed on purpose.

Every one of these was on screen because somebody thought the user needed
telling. They were taken out deliberately, each after being looked at: the text
was either saying something the control already says, or recording a fact
(a database hash, a correction-scope paragraph) that belongs in a report rather
than in front of someone reading a figure.

A removal has no code behind it, so nothing stops it drifting back in the next
time the same thought occurs. That is what this file is: one place naming what
was removed and why, so putting it back is a decision rather than an accident.

Each test names the file and the exact string, because a removal checked by a
vague pattern passes on a reworded version of the same box.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"

RESTORE = SRC / "features" / "data" / "RestorePage.tsx"
STATS = SRC / "features" / "stats"  # the page, its panels and their shared helpers
CANVAS = SRC / "features" / "analysis" / "AnalysisPage.tsx"
PHOSPHO = SRC / "features" / "phospho" / "PhosphoSpecificPage.tsx"
PANEL = SRC / "components" / "plots" / "AdvancedPlotOptions.tsx"


def _read(path: Path) -> str:
    if path.is_dir():
        return "\n".join(_read(child) for child in sorted(path.glob("*.ts*")))
    return path.read_text(encoding="utf-8")


def test_the_restore_page_has_no_standing_amber_explanations() -> None:
    """Two paragraphs of prose in front of five buttons nobody had misused.

    The amber boxes that remain on this page are conditional -- Missing Files,
    and the warnings a restore actually returned. Those are answers to something
    that just happened; the removed ones were there whatever the user did.
    """
    source = _read(RESTORE)
    assert "Leaving or refreshing starts a new analysis" not in source
    assert "Save states are compatibility snapshots. Older files remain usable" not in source
    # The conditional ones stay; this test is about standing prose, not about
    # taking the page's warnings away.
    assert "Missing Files" in source
    assert "warnings.length > 0" in source or "warnings.map" in source


def test_there_is_no_ora_provenance_card() -> None:
    """A card of five facts and a SHA-256, above the result the user came for."""
    source = _read(STATS)
    assert "OraProvenanceSection" not in source
    assert "ORA Provenance" not in source
    assert "GO database SHA-256" not in source
    # Organism, correction and search-space size are still stated -- they moved
    # into the summary row beside the result, which is where the rest of the
    # run's parameters already were.
    assert '{ label: "Organism", value: result.organism }' in source


def test_the_canvas_ora_tile_does_not_print_the_database_hash() -> None:
    source = _read(CANVAS)
    assert "GO database SHA-256" not in source
    assert "OraTermCounts" not in source


def test_the_correction_scope_paragraph_is_gone_from_the_codebase() -> None:
    """It was one 300-character sentence, rendered on two pages and exported
    as a column on every row of every ORA CSV."""
    matches = [
        path
        for path in SRC.rglob("*.ts*")
        if "ORA_CORRECTION_SCOPE" in path.read_text(encoding="utf-8")
    ]
    assert not matches, f"still referenced in: {[str(p.relative_to(SRC)) for p in matches]}"
    assert not (SRC / "components" / "OraTermCounts.tsx").exists()


def test_the_ora_export_rows_carry_neither_the_hash_nor_the_scope() -> None:
    """Two columns repeated on every row, identical in all of them."""
    for path in (STATS, CANVAS):
        source = _read(path)
        assert "databaseSha256: result.databaseSha256" not in source, path.name
        assert "correctionScope:" not in source, path.name


def test_the_simulation_sample_size_field_explains_itself_in_its_label() -> None:
    """The grey paragraph under it said what the label now says."""
    source = _read(STATS)
    assert "Use 0 for each row&apos;s observed replicate counts" not in source
    # 2026-09-24: the panel became "Replicate & Variance Projection" and the
    # field says what it sets; the meaning of 0 stays in the label.
    assert 'label="Replicates per group (0 = observed, 2-100 fixed)"' in source


def test_the_phosprot_regulation_options_have_no_score_explanation_box() -> None:
    source = _read(PHOSPHO)
    assert "scoreExplanation" not in source
    assert "coordinates sum the log2 fold changes" not in source


def test_the_advanced_panel_has_no_grey_hint_line_under_any_input() -> None:
    """Sixteen small grey lines, one under each numeric box, mostly repeating a
    number the field already shows when it is empty.

    `Reference: 6` under a box whose value *is* 6 until you change it says
    nothing. The three that did say something -- that 0 draws no outline, that a
    size applies to the static plot only, that a dot size is in points -- now say
    it in the field's own label, where it is read rather than skimmed past.

    The grey class itself is still used in this file for row labels and for two
    explanatory paragraphs inside cards. What this test forbids is the
    `mt-1 block` variant, which is the one that renders *under* a control.
    """
    source = _read(PANEL)
    assert "mt-1 block text-[11px] text-slate-500" not in source
    for gone in ("Reference: ", "Ref: ", "Diameter in points", "0 draws no outline",
                 "Static plot only", "0 to 1. Reference"):
        assert gone not in source, gone
    # What the removed lines said, where it went.
    assert "Dot size (pt)" in source
    assert "Dot outline width (0 = none)" in source
    assert "Hit label size (static plot)" in source
