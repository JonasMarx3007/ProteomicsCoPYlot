"""Human-readable headers for the columns a user sees in tables.

The DataFrames behind the report tables, the GUI tables and the CSV downloads
carry code identifiers as column names (``adj_pval``, ``lower_whisker``,
``n_MissingProteinValues``). Those names are a contract: the API, the CSV
files, the notebook exports and the assistant evidence all read them. What a
person reads in a rendered table is a different matter, so the *display*
label is looked up here and the data keys stay as they are.

``frontend/src/lib/columnLabels.ts`` holds the same dictionary for the GUI;
``tests/repo/test_column_labels_in_sync.py`` keeps the two identical.
"""
from __future__ import annotations

import re

# Exact names. Keep this dictionary and the TypeScript copy identical.
COLUMN_LABELS: dict[str, str] = {
    # QC summary tables
    "mean": "Mean",
    "median": "Median",
    "min": "Min",
    "max": "Max",
    "sd": "SD",
    "Q1": "Q1 (25th percentile)",
    "Q3": "Q3 (75th percentile)",
    "lower_whisker": "Lower whisker",
    "upper_whisker": "Upper whisker",
    "condition": "Condition",
    "sample": "Sample",
    "Number": "Identified features (n)",
    # Statistics tables
    "log2FC": "log2 fold change",
    "pval": "p-value",
    "adj_pval": "Adjusted p-value (BH)",
    "selected_pval": "p-value used for the threshold",
    "neg_log10_selected_pval": "-log10(p-value used)",
    "correction": "p-value correction",
    "significance": "Result",
    "zero_variance": "No variation",
    "n_pairs": "Complete pairs (n)",
    "reason": "Reason not tested",
    "f_statistic": "F statistic",
    "cluster": "Cluster",
    "test_type": "Test",
    "observed_n_condition1": "Observed n (condition 1)",
    "observed_n_condition2": "Observed n (condition 2)",
    "effective_n_condition1": "Projected n (condition 1)",
    "effective_n_condition2": "Projected n (condition 2)",
    "imputed_values": "Imputed values (n)",
    # Tukey post hoc
    "comparison": "Comparison",
    "group1": "Group 1",
    "group2": "Group 2",
    "n_group1": "n (group 1)",
    "n_group2": "n (group 2)",
    "q_statistic": "Tukey q",
    "tukey_pval": "Tukey p-value",
    "anova_adj_pval": "One-way ANOVA adjusted p-value",
    # Identifiers
    "ProteinNames": "Protein",
    "GeneNames": "Gene",
    "Protein_group": "Protein group",
    "Gene_group": "Gene",
    "PTM_Collapse_key": "Phosphosite",
    "PTM_Collapse_keys": "Phosphosites",
    "PTM_localization": "Localization probability",
    "UPD_seq": "Modified peptide",
    "Phosphoprotein": "Phosphoprotein",
    "site_num": "Sites (n)",
    "site_num_eligible": "Eligible sites (n)",
    "window_source": "Window source",
    # Phosphoprotein regulation
    "Downregulated_sites": "Down-regulated sites",
    "Upregulated_sites": "Up-regulated sites",
    "Downregulated_site_effects": "Down-regulated site effects",
    "Upregulated_site_effects": "Up-regulated site effects",
    "Downregulated_count": "Down-regulated sites (n)",
    "Upregulated_count": "Up-regulated sites (n)",
    "Downregulated_log2FC_sum": "|Sum of down-regulated log2FC|",
    "Upregulated_log2FC_sum": "Sum of up-regulated log2FC",
    # Completeness
    "Counts": "Missing values (n)",
    "%_missing_values": "Missing values (%)",
    "n_MissingProteinValues": "Missing values per feature",
    # Phospho coverage, per condition
    "classIMean": "Class I (mean)",
    "classISd": "Class I (SD)",
    "notClassIMean": "Not Class I (mean)",
    "notClassISd": "Not Class I (SD)",
    "unclassifiedMean": "Unclassified (mean)",
    "unclassifiedSd": "Unclassified (SD)",
    "totalMean": "Total (mean)",
    "totalSd": "Total (SD)",
    "SiteCount": "Sites per protein",
    "Frequency": "Proteins (n)",
    # Single-feature tables
    "SampleCount": "Samples (n)",
    "SourceFeatureCount": "Source features (n)",
    "SourceFeatures": "Source features",
    "Aggregation": "Aggregation",
    "Warning": "Note",
    # Comparison
    "Left": "First selection",
    "Right": "Second selection",
    "Points": "Paired values (n)",
    "PearsonR": "Pearson r",
}

# Columns that only carry a plot's coordinates; they stay in the data (the
# plot and the CSV use them) but are not shown as table columns.
HIDDEN_TABLE_COLUMNS: tuple[str, ...] = ("x", "y", "color_val")

# Prefixed names: one label per family, the suffix (a condition or sample
# name) shown in brackets.
_PREFIX_LABELS: tuple[tuple[str, str], ...] = (
    ("n_imputed__", "Imputed values"),
    ("n_measured__", "Measured values"),
    ("n_fully_imputed__", "Fully imputed values"),
    ("n_partially_imputed__", "Partially imputed values"),
    ("site_observed__", "Sites observed"),
    ("site_coverage__", "Site coverage"),
    ("site_supplied__", "Sites supplied"),
    ("site_measured__", "Sites measured"),
)
_MEAN_OF = re.compile(r"^mean_(.+)$")
_N_OF = re.compile(r"^n_(.+)$")


def display_label(column: str) -> str:
    """The header a person reads for a data column; unknown names pass through."""
    name = str(column)
    if name in COLUMN_LABELS:
        return COLUMN_LABELS[name]
    for prefix, label in _PREFIX_LABELS:
        if name.startswith(prefix) and len(name) > len(prefix):
            return f"{label} ({name[len(prefix):]})"
    match = _MEAN_OF.match(name)
    if match:
        return f"Mean ({match.group(1)})"
    match = _N_OF.match(name)
    if match and "__" not in name:
        return f"n ({match.group(1)})"
    return name


def display_labels(columns) -> dict[str, str]:
    """A rename map for ``DataFrame.rename(columns=...)``."""
    return {str(column): display_label(column) for column in columns}
