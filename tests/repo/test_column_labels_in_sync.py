"""The report and the GUI show the same header for the same data column.

`backend/app/services/column_labels.py` labels the report's tables,
`frontend/src/lib/columnLabels.ts` labels the GUI's. One dictionary in two
languages; this keeps them identical, and checks the labelling itself on the
names that used to reach the reader as code identifiers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from app.services import column_labels

ROOT = Path(__file__).resolve().parents[2]


def _typescript_labels() -> dict[str, str]:
    text = (ROOT / "frontend" / "src" / "lib" / "columnLabels.ts").read_text(encoding="utf-8")
    block = text.split("// COLUMN_LABELS_START", 1)[1].split("// COLUMN_LABELS_END", 1)[0]
    body = block[block.index("{"):block.rindex("}") + 1]
    body = re.sub(r",\s*}", "}", body)  # trailing comma is TypeScript, not JSON
    return json.loads(body)


def test_the_two_dictionaries_are_identical() -> None:
    assert _typescript_labels() == column_labels.COLUMN_LABELS


def test_the_hidden_columns_agree() -> None:
    text = (ROOT / "frontend" / "src" / "lib" / "columnLabels.ts").read_text(encoding="utf-8")
    match = re.search(r"HIDDEN_TABLE_COLUMNS: readonly string\[\] = \[(.*?)\]", text)
    assert match is not None
    assert tuple(json.loads(f"[{match.group(1)}]")) == column_labels.HIDDEN_TABLE_COLUMNS


def test_identifiers_that_reached_the_reader_now_have_labels() -> None:
    labels = {name: column_labels.display_label(name) for name in (
        "lower_whisker", "upper_whisker", "Q1", "Number", "adj_pval", "neg_log10_selected_pval",
        "zero_variance", "f_statistic", "n_pairs", "q_statistic", "tukey_pval", "PTM_Collapse_key",
        "n_MissingProteinValues", "%_missing_values", "classIMean", "Downregulated_log2FC_sum",
    )}
    assert all(label != name for name, label in labels.items()), labels
    assert not any(re.search(r"[a-z]_[a-z]", label) for label in labels.values()), labels


def test_prefixed_and_patterned_names() -> None:
    assert column_labels.display_label("mean_WT") == "Mean (WT)"
    assert column_labels.display_label("n_GRK") == "n (GRK)"
    assert column_labels.display_label("n_imputed__GRK") == "Imputed values (GRK)"
    assert column_labels.display_label("site_coverage__WT_1") == "Site coverage (WT_1)"
    assert column_labels.display_label("n_pairs") == "Complete pairs (n)"  # exact name wins over the pattern
    assert column_labels.display_label("Something_else") == "Something_else"  # unknown names pass through


def test_the_report_table_shows_labels_and_two_decimals() -> None:
    from app.services.report_function import _table_to_html

    frame = pd.DataFrame({"Condition": ["A"], "mean": [8.1934], "lower_whisker": [2.9], "x": [1.0]})
    html = _table_to_html("Boxplot Summary Table", frame)
    assert "<th>Mean</th>" in html and "<th>Lower whisker</th>" in html
    assert "lower_whisker" not in html and "<th>x</th>" not in html
    assert "8.19" in html and "2.90" in html
