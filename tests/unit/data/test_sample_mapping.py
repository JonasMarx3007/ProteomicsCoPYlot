"""The report's sample-mapping table must agree with the plots' axis labels.

The table exists to tell a reader which run is behind `WT_1`. That is only true
while it uses the same numbering rule the plots use, and the plot paths compute
their labels inline. These tests pin the two together.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services.functions import sample_label_frame
from app.services.report_function import _sample_mapping_html, _sample_mapping_rows_html


LONG_NAMES = [
    "[6] 20240822_nElute_tims1_JM_HEK293_WP_WT_1_Slot1-61_1_8064.d.PG.Log2Quantity",
    "[7] 20240822_nElute_tims1_JM_HEK293_WP_WT_2_Slot1-62_1_8065.d.PG.Log2Quantity",
    "[8] 20240822_nElute_tims1_JM_HEK293_WP_KO_1_Slot1-63_1_8066.d.PG.Log2Quantity",
    "[9] 20240822_nElute_tims1_JM_HEK293_WP_KO_2_Slot1-64_1_8067.d.PG.Log2Quantity",
]


def _metadata(pair_ids: list[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {"sample": LONG_NAMES, "condition": ["WT", "WT", "KO", "KO"]}
    )
    if pair_ids is not None:
        frame["pair_id"] = pair_ids
    return frame


def _text(markup: str) -> str:
    import html as html_module

    return html_module.unescape(re.sub(r"<[^>]+>", " ", markup))


def test_labels_number_samples_within_their_own_condition() -> None:
    mapping = sample_label_frame(_metadata())
    assert mapping["label"].tolist() == ["WT_1", "WT_2", "KO_1", "KO_2"]
    assert mapping["sample"].tolist() == LONG_NAMES


def test_labels_match_the_rule_the_plot_paths_apply() -> None:
    """`plot_images` and `peptide_tools` both number with groupby/cumcount.

    A sorted-by-condition frame and an interleaved one must give a sample the
    same number, because the protein/phospho path sorts by condition before
    numbering and the peptide path does not.
    """
    interleaved = pd.DataFrame(
        {
            "sample": ["a", "b", "c", "d"],
            "condition": ["WT", "KO", "WT", "KO"],
        }
    )
    plot_rule = interleaved.copy()
    plot_rule["index"] = plot_rule.groupby("condition").cumcount() + 1
    expected = (plot_rule["condition"] + "_" + plot_rule["index"].astype(str)).tolist()

    assert sample_label_frame(interleaved)["label"].tolist() == expected

    grouped = interleaved.sort_values("condition", kind="stable").reset_index(drop=True)
    by_sample = dict(
        zip(
            sample_label_frame(grouped)["sample"],
            sample_label_frame(grouped)["label"],
        )
    )
    assert by_sample == dict(zip(interleaved["sample"], expected))


def test_original_names_are_never_shortened() -> None:
    markup = _sample_mapping_rows_html(sample_label_frame(_metadata()), show_pairs=False)
    for name in LONG_NAMES:
        assert name in _text(markup), f"{name} was altered or truncated"
    assert "…" not in markup and "..." not in markup


def test_table_scrolls_instead_of_growing_the_page() -> None:
    """A 200-sample run must not produce a 200-row-tall block."""
    many = pd.DataFrame(
        {
            "sample": [f"run_{i:03d}" for i in range(200)],
            "condition": ["WT" if i % 2 else "KO" for i in range(200)],
        }
    )
    markup = _sample_mapping_rows_html(sample_label_frame(many), show_pairs=False)
    assert "class='map-scroll'" in markup
    assert markup.count("<tr>") == 201  # 200 samples plus the header row


def test_pair_column_appears_only_when_pairing_is_set() -> None:
    without = _sample_mapping_rows_html(
        sample_label_frame(_metadata()), show_pairs=False
    )
    assert "<th>Pair</th>" not in without

    paired = sample_label_frame(_metadata(["p1", "p2", "p1", "p2"]))
    assert paired["pair_id"].tolist() == ["p1", "p2", "p1", "p2"]
    assert "<th>Pair</th>" in _sample_mapping_rows_html(paired, show_pairs=True)


def test_identical_levels_are_named_together_rather_than_repeated() -> None:
    """Peptide plots reuse the protein annotation when protein data is loaded."""
    warnings: list[str] = []
    markup = _sample_mapping_html(
        levels=[
            ("Peptide Level", _metadata()),
            ("Protein Level", _metadata()),
        ],
        warnings=warnings,
    )
    assert markup.count("class='map-scroll'") == 1
    assert "Peptide Level and Protein Level" in _text(markup)
    assert not warnings


def test_levels_with_different_runs_each_get_a_table() -> None:
    phospho = pd.DataFrame(
        {
            "sample": [name.replace("_WP_", "_PP_") for name in LONG_NAMES],
            "condition": ["WT", "WT", "KO", "KO"],
        }
    )
    markup = _sample_mapping_html(
        levels=[("Protein Level", _metadata()), ("Phosphosite Level", phospho)],
        warnings=[],
    )
    assert markup.count("class='map-scroll'") == 2
    text = _text(markup)
    assert "Protein Level" in text and "Phosphosite Level" in text


@pytest.mark.parametrize(
    "metadata",
    [
        pd.DataFrame(columns=["sample", "condition"]),
        pd.DataFrame({"sample": ["  ", ""], "condition": ["WT", "KO"]}),
        pd.DataFrame({"missing": [1]}),
        None,
    ],
)
def test_unusable_metadata_yields_no_rows_rather_than_raising(metadata) -> None:
    assert sample_label_frame(metadata).empty


def test_section_states_that_no_samples_are_available() -> None:
    markup = _sample_mapping_html(levels=[("Protein Level", None)], warnings=[])
    assert "No annotated samples available." in _text(markup)
