/**
 * Human-readable headers for the columns a user sees in tables.
 *
 * Table rows keep their data keys (`adj_pval`, `lower_whisker`, ...): the
 * API, the CSV downloads and the notebook exports read them. The header a
 * person reads is looked up here. `backend/app/services/column_labels.py`
 * holds the same dictionary for the report; `tests/repo/test_column_labels_in_sync.py`
 * keeps the two identical, so edit both.
 */

// COLUMN_LABELS_START
export const COLUMN_LABELS: Record<string, string> = {
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
  "comparison": "Comparison",
  "group1": "Group 1",
  "group2": "Group 2",
  "n_group1": "n (group 1)",
  "n_group2": "n (group 2)",
  "q_statistic": "Tukey q",
  "tukey_pval": "Tukey p-value",
  "anova_adj_pval": "ANOVA adjusted p-value",
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
  "Downregulated_sites": "Down-regulated sites",
  "Upregulated_sites": "Up-regulated sites",
  "Downregulated_site_effects": "Down-regulated site effects",
  "Upregulated_site_effects": "Up-regulated site effects",
  "Downregulated_count": "Down-regulated sites (n)",
  "Upregulated_count": "Up-regulated sites (n)",
  "Downregulated_log2FC_sum": "|Sum of down-regulated log2FC|",
  "Upregulated_log2FC_sum": "Sum of up-regulated log2FC",
  "Counts": "Missing values (n)",
  "%_missing_values": "Missing values (%)",
  "n_MissingProteinValues": "Missing values per feature",
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
  "SampleCount": "Samples (n)",
  "SourceFeatureCount": "Source features (n)",
  "SourceFeatures": "Source features",
  "Aggregation": "Aggregation",
  "Warning": "Note",
  "Left": "First selection",
  "Right": "Second selection",
  "Points": "Paired values (n)",
  "PearsonR": "Pearson r",
};
// COLUMN_LABELS_END

/** Plot coordinates carried in table rows; shown in the plot and the CSV, not as columns. */
export const HIDDEN_TABLE_COLUMNS: readonly string[] = ["x", "y", "color_val"];

const PREFIX_LABELS: ReadonlyArray<readonly [string, string]> = [
  ["n_imputed__", "Imputed values"],
  ["n_measured__", "Measured values"],
  ["n_fully_imputed__", "Fully imputed values"],
  ["n_partially_imputed__", "Partially imputed values"],
  ["site_observed__", "Sites observed"],
  ["site_coverage__", "Site coverage"],
  ["site_supplied__", "Sites supplied"],
  ["site_measured__", "Sites measured"],
];

/** The header a person reads for a data column; unknown names pass through. */
export function displayLabel(column: string, overrides?: Record<string, string>): string {
  if (overrides && Object.hasOwn(overrides, column)) return overrides[column];
  if (Object.hasOwn(COLUMN_LABELS, column)) return COLUMN_LABELS[column];
  for (const [prefix, label] of PREFIX_LABELS) {
    if (column.startsWith(prefix) && column.length > prefix.length) return `${label} (${column.slice(prefix.length)})`;
  }
  const mean = /^mean_(.+)$/.exec(column);
  if (mean) return `Mean (${mean[1]})`;
  const n = /^n_(.+)$/.exec(column);
  if (n && !column.includes("__")) return `n (${n[1]})`;
  return column;
}

/** Hide coordinates only for plot summaries, never for arbitrary data matrices. */
export function visibleColumns(columns: string[], plotSummary = false): string[] {
  return plotSummary ? columns.filter((column) => !HIDDEN_TABLE_COLUMNS.includes(column)) : columns;
}
