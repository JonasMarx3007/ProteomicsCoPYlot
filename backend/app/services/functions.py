from __future__ import annotations

"""FastAPI-facing CoPYlot service helpers.

Server/runtime code must stay self-contained in this module.
"""

import re
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.cluster.hierarchy import leaves_list, linkage

from app.schemas.annotation import AnnotationKind
from app.schemas.completeness import CompletenessTablesResponse
from app.services.runtime_cache import apply_cached_wrappers

try:
    from statsmodels.stats.multitest import multipletests
except ModuleNotFoundError:

    def multipletests(pvals, alpha=0.05, method="fdr_bh"):
        if method != "fdr_bh":
            raise ModuleNotFoundError(
                "statsmodels is required for multipletests methods other than 'fdr_bh'."
            )
        pvals = np.asarray(pvals, dtype=float)
        n = len(pvals)
        order = np.argsort(pvals)
        ranked = pvals[order]
        adjusted_ranked = ranked * n / np.arange(1, n + 1)
        adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
        adjusted = np.empty_like(adjusted_ranked)
        adjusted[order] = np.clip(adjusted_ranked, 0, 1)
        reject = adjusted <= alpha
        return reject, adjusted, None, None

FilterMode = Literal["per_group", "in_at_least_one_group"]
DataSource = Literal["filtered", "log2", "raw"]

AUTO_SAMPLE_PATTERN = re.compile(r"20\d{6}")


@dataclass
class MetadataBuildResult:
    metadata: pd.DataFrame
    auto_detected: bool


@dataclass
class ImputationDiagnostics:
    imputed_data: pd.DataFrame
    missing_before: int
    missing_after: int
    mean: float
    std: float
    quantile: float
    before_without_missing: np.ndarray
    before_with_missing: np.ndarray
    overall_observed: np.ndarray
    after_non_imputed: np.ndarray
    after_imputed: np.ndarray


# Data Pipeline
def build_metadata_from_conditions(
    data: pd.DataFrame,
    conditions: list[dict[str, object]],
) -> MetadataBuildResult:
    rows: list[dict[str, str]] = []
    used_samples: set[str] = set()

    for condition in conditions:
        name = str(condition.get("name", "")).strip()
        columns = condition.get("columns", [])
        if not name or not isinstance(columns, list):
            continue
        for col in columns:
            sample = str(col)
            if sample in used_samples or sample not in data.columns:
                continue
            rows.append({"sample": sample, "condition": name})
            used_samples.add(sample)

    if rows:
        return MetadataBuildResult(metadata=pd.DataFrame(rows), auto_detected=False)

    auto_columns = [str(col) for col in data.columns if AUTO_SAMPLE_PATTERN.search(str(col))]
    if not auto_columns:
        raise ValueError(
            "No valid condition assignments were provided and no auto-detectable sample "
            "columns were found (expected names like 20240131)."
        )
    auto_rows = [{"sample": col, "condition": "sample"} for col in auto_columns]
    return MetadataBuildResult(metadata=pd.DataFrame(auto_rows), auto_detected=True)


def log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    selected.replace(0, np.nan, inplace=True)
    log2_data = np.log2(selected)
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([log2_data, data[remaining]], axis=1)


def use_existing_log2_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([selected, data[remaining]], axis=1)


def inverse_log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    original = 2 ** selected
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([original, data[remaining]], axis=1)


def filter_data(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    min_present: int,
    mode: FilterMode,
) -> pd.DataFrame:
    sample_columns = metadata["sample"].tolist()
    data_selected = data[sample_columns].copy()
    conditions = metadata["condition"].unique()

    mask = pd.DataFrame(False, index=data_selected.index, columns=conditions)
    for condition in conditions:
        cols = metadata.loc[metadata["condition"] == condition, "sample"].tolist()
        mask[condition] = data_selected[cols].notna().sum(axis=1) >= min_present

    rows_to_keep = mask.all(axis=1) if mode == "per_group" else mask.any(axis=1)
    return data.loc[rows_to_keep].reset_index(drop=True)


def choose_best_source(
    filtered_df: pd.DataFrame | None,
    log2_df: pd.DataFrame | None,
    raw_df: pd.DataFrame,
) -> tuple[DataSource, pd.DataFrame]:
    if filtered_df is not None and not filtered_df.empty:
        return "filtered", filtered_df.copy()
    if log2_df is not None and not log2_df.empty:
        return "log2", log2_df.copy()
    return "raw", raw_df.copy()


def impute_values_with_diagnostics(
    data: pd.DataFrame,
    sample_columns: list[str],
    q: float = 0.01,
    adj_std: float = 1.0,
    seed: int = 1337,
    sample_wise: bool = False,
) -> ImputationDiagnostics:
    np.random.seed(seed)
    numeric = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    missing_mask = numeric.isna()
    row_has_missing = missing_mask.any(axis=1)

    all_values = numeric.values.flatten()
    observed = all_values[~np.isnan(all_values)]
    if observed.size == 0:
        raise ValueError("No numeric values available for imputation.")

    before_without = numeric.loc[~row_has_missing].values.flatten()
    before_with = numeric.loc[row_has_missing].values.flatten()
    before_without = before_without[~np.isnan(before_without)]
    before_with = before_with[~np.isnan(before_with)]

    mean_val = float(np.nanmean(observed))
    std_val = float(np.nanstd(observed))
    quantile_val = float(np.nanquantile(observed, q))

    imputed_numeric = numeric.copy()
    missing_before = int(imputed_numeric.isna().sum().sum())

    if sample_wise:
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            col_observed = col_values.dropna().values
            if col_observed.size == 0:
                draws = np.random.normal(quantile_val, std_val * adj_std, missing_count)
            else:
                col_q = float(np.nanquantile(col_observed, q))
                col_sd = float(np.nanstd(col_observed))
                draw_sd = col_sd if col_sd > 0 else std_val
                draws = np.random.normal(col_q, draw_sd, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws
    else:
        draw_sd = std_val * adj_std
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            draws = np.random.normal(quantile_val, draw_sd, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws

    result = data.copy()
    result[sample_columns] = imputed_numeric
    missing_after = int(result[sample_columns].isna().sum().sum())

    after_imputed = imputed_numeric[missing_mask].values.flatten()
    after_non_imputed = imputed_numeric[~missing_mask].values.flatten()
    after_imputed = after_imputed[~np.isnan(after_imputed)]
    after_non_imputed = after_non_imputed[~np.isnan(after_non_imputed)]

    return ImputationDiagnostics(
        imputed_data=result,
        missing_before=missing_before,
        missing_after=missing_after,
        mean=mean_val,
        std=std_val,
        quantile=quantile_val,
        before_without_missing=before_without,
        before_with_missing=before_with,
        overall_observed=observed,
        after_non_imputed=after_non_imputed,
        after_imputed=after_imputed,
    )


def anova_data_f(data, meta, conditions=None, in_pval=0.05, workflow="Protein", uncorrected=False):
    if workflow == "Protein":
        label_col = "ProteinNames"
    elif workflow == "Phosphosite":
        label_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        label_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    if conditions is None:
        conditions = meta["condition"].dropna().unique().tolist()
    if len(conditions) < 2:
        raise ValueError("ANOVA needs at least two conditions.")

    condition_cols = {
        condition: [col for col in meta.loc[meta["condition"] == condition, "sample"].tolist() if col in data.columns]
        for condition in conditions
    }
    too_few = [condition for condition, cols in condition_cols.items() if len(cols) < 2]
    if too_few:
        raise ValueError("Each ANOVA condition needs at least two sample columns. Missing: " + ", ".join(map(str, too_few)))

    sample_cols = [col for cols in condition_cols.values() for col in cols]
    cols_to_use = [label_col] + sample_cols

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].replace(0, np.nan).copy()
    df[sample_cols] = df[sample_cols].apply(pd.to_numeric, errors="coerce")

    valid = np.ones(len(df), dtype=bool)
    groups = []
    for cols in condition_cols.values():
        group = df[cols].to_numpy(dtype=float)
        valid &= np.sum(~np.isnan(group), axis=1) >= 2
        groups.append(group)

    df = df.loc[valid].copy()
    groups = [group[valid] for group in groups]
    if df.empty:
        return df.reset_index(drop=True)

    try:
        f_stat, pvals = stats.f_oneway(*groups, axis=1, nan_policy="omit")
    except TypeError:
        f_stat = np.empty(len(df), dtype=float)
        pvals = np.empty(len(df), dtype=float)
        for i in range(len(df)):
            row_groups = [group[i][~np.isnan(group[i])] for group in groups]
            f_stat[i], pvals[i] = stats.f_oneway(*row_groups)

    finite = np.isfinite(pvals)
    df = df.loc[finite].copy()
    groups = [group[finite] for group in groups]
    f_stat = f_stat[finite]
    pvals = pvals[finite]

    means = pd.DataFrame({
        condition: np.nanmean(group, axis=1)
        for condition, group in zip(condition_cols.keys(), groups)
    }, index=df.index)

    out = df[cols_to_use].copy()
    out["f_statistic"] = f_stat
    out["pval"] = pvals
    out["adj_pval"] = pvals if uncorrected else multipletests(pvals, method="fdr_bh")[1]
    out["significance"] = np.where(out["adj_pval"] < in_pval, "Significant", "Not significant")
    out["neg_log10_adj_pval"] = -np.log10(np.clip(out["adj_pval"], np.finfo(float).tiny, None))

    for condition in means.columns:
        out[f"mean_{condition}"] = means[condition].to_numpy()

    return out.sort_values("adj_pval").reset_index(drop=True)


def anova_cluster_data(anova_df, meta, n_clusters=4, in_pval=0.05, z_score=True, only_significant=True, cluster_method="average", cluster_metric="euclidean", cluster_col="cluster", min_cluster_fraction=0.05):
    from scipy.cluster.hierarchy import fcluster

    if n_clusters < 1:
        raise ValueError("n_clusters must be at least 1.")

    sample_cols = [col for col in meta["sample"].astype(str).tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    if only_significant and "adj_pval" in anova_df.columns:
        cluster_df = anova_df[anova_df["adj_pval"] < in_pval].copy()
        if cluster_df.empty:
            cluster_df = anova_df.copy()
    else:
        cluster_df = anova_df.copy()

    matrix = cluster_df[sample_cols].to_numpy(dtype=float)
    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)

    if matrix.shape[0] <= 1:
        cluster_df[cluster_col] = 1
        return cluster_df.reset_index(drop=True)

    row_linkage = linkage(matrix, method=cluster_method, metric=cluster_metric)
    row_order = leaves_list(row_linkage)
    raw_clusters = fcluster(row_linkage, t=n_clusters, criterion="maxclust")
    ordered_clusters = raw_clusters[row_order]

    cluster_map = {}
    relabeled_clusters = []
    for cluster_id in ordered_clusters:
        if cluster_id not in cluster_map:
            cluster_map[cluster_id] = len(cluster_map) + 1
        relabeled_clusters.append(cluster_map[cluster_id])

    relabeled_clusters = np.asarray(relabeled_clusters, dtype=int)
    if min_cluster_fraction and min_cluster_fraction > 0:
        min_cluster_size = int(np.ceil(len(relabeled_clusters) * min_cluster_fraction))
        cluster_ids, cluster_counts = np.unique(relabeled_clusters, return_counts=True)
        count_map = dict(zip(cluster_ids, cluster_counts))
        large_clusters = [cluster_id for cluster_id in cluster_ids if count_map[cluster_id] >= min_cluster_size]
        if len(large_clusters) == 0:
            large_clusters = [max(cluster_ids, key=lambda cluster_id: count_map[cluster_id])]
        merged_clusters = relabeled_clusters.copy()
        for cluster_id in cluster_ids:
            if count_map[cluster_id] >= min_cluster_size:
                continue
            target_cluster = min(large_clusters, key=lambda target: (abs(target - cluster_id), target < cluster_id))
            merged_clusters[relabeled_clusters == cluster_id] = target_cluster
        cluster_map = {}
        relabeled_clusters = []
        for cluster_id in merged_clusters:
            if cluster_id not in cluster_map:
                cluster_map[cluster_id] = len(cluster_map) + 1
            relabeled_clusters.append(cluster_map[cluster_id])

    cluster_df = cluster_df.iloc[row_order].copy()
    if cluster_col in cluster_df.columns:
        cluster_df = cluster_df.drop(columns=[cluster_col])
    cluster_df.insert(1, cluster_col, relabeled_clusters)
    return cluster_df.reset_index(drop=True)


def _auto_label_col(frame: pd.DataFrame) -> str:
    if "Phosphoprotein" in frame.columns:
        return "Phosphoprotein"
    if "ProteinNames" in frame.columns:
        return "ProteinNames"
    if "PTM_Collapse_key" in frame.columns:
        return "PTM_Collapse_key"
    if "Gene_group" in frame.columns:
        return "Gene_group"
    if "GeneNames" in frame.columns:
        return "GeneNames"
    raise ValueError("No supported label column was found.")


def anova_plot(
    anova_df,
    meta,
    in_pval=0.05,
    z_score=True,
    cluster_rows=True,
    cluster_samples=True,
    cluster_method="average",
    cluster_metric="euclidean",
    show_gene_names=False,
    show_condition_legend=False,
    show_dendrograms=True,
    width=12,
    height=10,
    dpi=150,
):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage

    if anova_df.empty:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.set_axis_off()
        ax.set_title("ANOVA heatmap")
        return fig

    label_col = _auto_label_col(anova_df)
    meta_plot = meta.copy()
    meta_plot["sample"] = meta_plot["sample"].astype(str)
    meta_plot["condition"] = meta_plot["condition"].astype(str)
    if "new_sample" in meta_plot.columns:
        meta_plot["plot_sample"] = meta_plot["new_sample"].astype(str)
    else:
        meta_plot["plot_sample"] = meta_plot["condition"] + "_" + (meta_plot.groupby("condition").cumcount() + 1).astype(str)

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    plot_df = anova_df[anova_df["adj_pval"] < in_pval].copy() if "adj_pval" in anova_df.columns else anova_df.copy()
    if plot_df.empty:
        plot_df = anova_df.copy()

    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd
        cmap = "RdBu_r"
        color_label = "row z-score"
        vmin, vmax = -2.5, 2.5
    else:
        cmap = "viridis"
        color_label = "intensity"
        vmin = vmax = None

    display_mask = missing_mask | ~np.isfinite(matrix)
    display_matrix = np.ma.array(matrix, mask=display_mask)
    cluster_matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    row_linkage = None
    col_linkage = None

    if cluster_rows and matrix.shape[0] > 1:
        row_linkage = linkage(cluster_matrix, method=cluster_method, metric=cluster_metric)
        row_order = leaves_list(row_linkage)
        display_matrix = display_matrix[row_order]
        cluster_matrix = cluster_matrix[row_order]
        labels = [labels[i] for i in row_order]
        plot_df = plot_df.iloc[row_order]

    if cluster_samples and matrix.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method=cluster_method, metric=cluster_metric)
        col_order = leaves_list(col_linkage)
        display_matrix = display_matrix[:, col_order]
        sample_cols = [sample_cols[i] for i in col_order]

    sample_to_condition = dict(zip(meta_plot["sample"], meta_plot["condition"]))
    sample_to_label = dict(zip(meta_plot["sample"], meta_plot["plot_sample"]))
    conditions = [sample_to_condition.get(sample, "") for sample in sample_cols]
    x_labels = [sample_to_label.get(sample, sample) for sample in sample_cols]

    unique_conditions = list(dict.fromkeys(conditions))
    palette = plt.cm.tab20(np.linspace(0, 1, max(len(unique_conditions), 1)))
    condition_colors = {condition: palette[i % len(palette)] for i, condition in enumerate(unique_conditions)}
    condition_strip = np.array([[condition_colors[condition] for condition in conditions]])

    fig = plt.figure(figsize=(width, height), dpi=dpi)
    grid = fig.add_gridspec(3, 3, height_ratios=[0.16, 0.025, 1.0], width_ratios=[0.10, 1.0, 0.035], hspace=0.02, wspace=0.03)
    ax_corner = fig.add_subplot(grid[0, 0])
    ax_col_dendrogram = fig.add_subplot(grid[0, 1])
    ax_top_blank = fig.add_subplot(grid[0, 2])
    ax_strip_left = fig.add_subplot(grid[1, 0])
    ax_strip = fig.add_subplot(grid[1, 1])
    ax_strip_right = fig.add_subplot(grid[1, 2])
    ax_row_dendrogram = fig.add_subplot(grid[2, 0])
    ax = fig.add_subplot(grid[2, 1])
    cax = fig.add_subplot(grid[2, 2])

    for blank_ax in [ax_corner, ax_top_blank, ax_strip_left, ax_strip_right]:
        blank_ax.set_axis_off()

    if show_dendrograms and col_linkage is not None:
        dendrogram(col_linkage, ax=ax_col_dendrogram, no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_col_dendrogram.set_axis_off()

    if show_dendrograms and row_linkage is not None:
        dendrogram(row_linkage, ax=ax_row_dendrogram, orientation="left", no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_row_dendrogram.set_axis_off()

    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()

    plot_cmap = plt.get_cmap(cmap).copy()
    plot_cmap.set_bad("#d8d8d8")
    image = ax.imshow(display_matrix, aspect="auto", interpolation="nearest", cmap=plot_cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel("samples")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(sample_cols)))
    ax.set_xticklabels(x_labels, rotation=90, fontsize=5)
    if show_gene_names:
        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=5)
    else:
        ax.set_yticks([])

    colorbar = fig.colorbar(image, cax=cax)
    colorbar.set_label(color_label)

    legend_handles = [Patch(facecolor=condition_colors[condition], label=condition) for condition in unique_conditions]
    if show_condition_legend and legend_handles:
        ax_top_blank.legend(handles=legend_handles, loc="upper left", frameon=False, fontsize=7, borderaxespad=0)

    fig.suptitle(f"ANOVA heatmap ({len(plot_df)} rows)", y=0.965)
    fig.subplots_adjust(left=0.04, right=0.90, top=0.91, bottom=0.16)
    return fig


def anova_plot_cluster(
    anova_cluster_df,
    meta,
    cluster_col="cluster",
    z_score=True,
    cluster_samples=True,
    cluster_method="average",
    cluster_metric="euclidean",
    show_gene_names=False,
    show_condition_legend=False,
    show_cluster_legend=True,
    max_cluster_legend=12,
    show_dendrogram=True,
    width=12,
    height=10,
    dpi=150,
):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage

    if cluster_col not in anova_cluster_df.columns:
        raise ValueError(f"anova_cluster_df must contain a '{cluster_col}' column from anova_cluster_data().")
    if anova_cluster_df.empty:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.set_axis_off()
        ax.set_title("ANOVA cluster heatmap")
        return fig

    label_col = _auto_label_col(anova_cluster_df)
    meta_plot = meta.copy()
    meta_plot["sample"] = meta_plot["sample"].astype(str)
    meta_plot["condition"] = meta_plot["condition"].astype(str)
    if "new_sample" in meta_plot.columns:
        meta_plot["plot_sample"] = meta_plot["new_sample"].astype(str)
    else:
        meta_plot["plot_sample"] = meta_plot["condition"] + "_" + (meta_plot.groupby("condition").cumcount() + 1).astype(str)

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_cluster_df.columns]
    if not sample_cols:
        raise ValueError("anova_cluster_df must contain the original sample columns from anova_data_f().")

    plot_df = anova_cluster_df.copy()
    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd
        cmap = "RdBu_r"
        color_label = "row z-score"
        vmin, vmax = -2.5, 2.5
    else:
        cmap = "viridis"
        color_label = "intensity"
        vmin = vmax = None

    display_matrix = np.ma.array(matrix, mask=missing_mask | ~np.isfinite(matrix))
    cluster_matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    col_linkage = None
    if cluster_samples and matrix.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method=cluster_method, metric=cluster_metric)
        col_order = leaves_list(col_linkage)
        display_matrix = display_matrix[:, col_order]
        sample_cols = [sample_cols[i] for i in col_order]

    sample_to_condition = dict(zip(meta_plot["sample"], meta_plot["condition"]))
    sample_to_label = dict(zip(meta_plot["sample"], meta_plot["plot_sample"]))
    conditions = [sample_to_condition.get(sample, "") for sample in sample_cols]
    x_labels = [sample_to_label.get(sample, sample) for sample in sample_cols]

    unique_conditions = list(dict.fromkeys(conditions))
    condition_palette = plt.cm.tab20(np.linspace(0, 1, max(len(unique_conditions), 1)))
    condition_colors = {condition: condition_palette[i % len(condition_palette)] for i, condition in enumerate(unique_conditions)}
    condition_strip = np.array([[condition_colors[condition] for condition in conditions]])

    cluster_values = plot_df[cluster_col].tolist()
    unique_clusters = list(dict.fromkeys(cluster_values))
    cluster_palette = plt.cm.tab20b(np.linspace(0, 1, max(len(unique_clusters), 1)))
    cluster_colors = {cluster: cluster_palette[i % len(cluster_palette)] for i, cluster in enumerate(unique_clusters)}
    cluster_strip = np.array([[cluster_colors[cluster]] for cluster in cluster_values])

    fig = plt.figure(figsize=(width, height), dpi=dpi)
    grid = fig.add_gridspec(3, 4, height_ratios=[0.16, 0.025, 1.0], width_ratios=[0.025, 1.0, 0.035, 0.12], hspace=0.02, wspace=0.04)
    ax_col_dendrogram = fig.add_subplot(grid[0, 1])
    ax_strip = fig.add_subplot(grid[1, 1])
    ax_cluster = fig.add_subplot(grid[2, 0])
    ax = fig.add_subplot(grid[2, 1])
    cax = fig.add_subplot(grid[2, 2])
    ax_legend = fig.add_subplot(grid[:, 3])
    ax_legend.set_axis_off()

    if show_dendrogram and col_linkage is not None:
        dendrogram(col_linkage, ax=ax_col_dendrogram, no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_col_dendrogram.set_axis_off()
    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()
    ax_cluster.imshow(cluster_strip, aspect="auto", interpolation="nearest")
    ax_cluster.set_axis_off()

    plot_cmap = plt.get_cmap(cmap).copy()
    plot_cmap.set_bad("#d8d8d8")
    image = ax.imshow(display_matrix, aspect="auto", interpolation="nearest", cmap=plot_cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel("samples")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(sample_cols)))
    ax.set_xticklabels(x_labels, rotation=90, fontsize=5)
    if show_gene_names:
        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=5)
    else:
        ax.set_yticks([])

    colorbar = fig.colorbar(image, cax=cax)
    colorbar.set_label(color_label)

    legend_handles = []
    if show_cluster_legend:
        legend_handles.extend([Patch(facecolor=cluster_colors[cluster], label=f"cluster {cluster}") for cluster in unique_clusters[:max_cluster_legend]])
    if show_condition_legend:
        legend_handles.extend([Patch(facecolor=condition_colors[condition], label=condition) for condition in unique_conditions])
    if legend_handles:
        ax_legend.legend(handles=legend_handles, loc="upper left", frameon=False, fontsize=7, borderaxespad=0)

    fig.suptitle(f"ANOVA cluster heatmap ({len(plot_df)} rows)", y=0.965)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.91, bottom=0.16)
    return fig

def histogram(values: np.ndarray, bins: int = 30) -> list[tuple[float, float, int]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    counts, edges = np.histogram(clean, bins=bins)
    return [(float(edges[i]), float(edges[i + 1]), int(counts[i])) for i in range(len(counts))]


def comparative_histogram(
    left_values: np.ndarray,
    right_values: np.ndarray,
    bins: int = 30,
) -> list[tuple[float, float, int, int]]:
    left_clean = left_values[~np.isnan(left_values)]
    right_clean = right_values[~np.isnan(right_values)]
    combined = np.concatenate([left_clean, right_clean]) if left_clean.size or right_clean.size else np.array([])
    if combined.size == 0:
        return []
    _, edges = np.histogram(combined, bins=bins)
    left_counts, _ = np.histogram(left_clean, bins=edges)
    right_counts, _ = np.histogram(right_clean, bins=edges)
    return [
        (float(edges[i]), float(edges[i + 1]), int(left_counts[i]), int(right_counts[i]))
        for i in range(len(edges) - 1)
    ]


def normal_fit_curve(values: np.ndarray, points: int = 200) -> list[tuple[float, float]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    std_val = float(np.std(clean))
    if std_val <= 0:
        return []
    mean_val = float(np.mean(clean))
    x = np.linspace(np.min(clean), np.max(clean), points)
    y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
    return [(float(px), float(py)) for px, py in zip(x, y)]


def qqnorm_plot_data(values: np.ndarray, max_points: int = 100_000) -> dict[str, list[tuple[float, float]]]:
    clean = values[~np.isnan(values)]
    clean = clean[clean > 0]
    if clean.size == 0:
        return {"points": [], "fitLine": []}

    if clean.size > max_points:
        np.random.seed(187)
        clean = np.random.choice(clean, max_points, replace=False)

    clean = np.sort(clean)
    n = clean.size
    normal = NormalDist()

    theoretical = np.array([normal.inv_cdf((i - 0.5) / n) for i in range(1, n + 1)])
    sample = clean.astype(float)

    if n < 2:
        return {
            "points": [(float(theoretical[0]), float(sample[0]))],
            "fitLine": [],
        }

    slope, intercept = np.polyfit(theoretical, sample, 1)
    x0, x1 = float(np.min(theoretical)), float(np.max(theoretical))
    y0, y1 = float(slope * x0 + intercept), float(slope * x1 + intercept)

    return {
        "points": [(float(tx), float(sy)) for tx, sy in zip(theoretical, sample)],
        "fitLine": [(x0, y0), (x1, y1)],
    }


# Imputation Pipeline
def imputation_before_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_before_plot as _impl

    return _impl(kind, q_value, adjust_std, seed, sample_wise, advanced=advanced)


def imputation_overall_fit_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    show_imputation_draw: bool = True,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_overall_fit_plot as _impl

    return _impl(
        kind,
        q_value,
        adjust_std,
        seed,
        sample_wise,
        show_imputation_draw,
        advanced=advanced,
    )


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    normalization: str = "separate",
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_after_plot as _impl

    return _impl(
        kind,
        q_value,
        adjust_std,
        seed,
        sample_wise,
        normalization,
        advanced=advanced,
    )


# Distribution Pipeline
def distribution_qqnorm_plot(kind: AnnotationKind, advanced: dict | None = None) -> bytes:
    from app.services.plot_images import distribution_qqnorm_plot as _impl

    return _impl(kind, advanced=advanced)


# Completeness Pipeline
def completeness_missing_value_plot(
    kind: AnnotationKind,
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_plot as _impl

    return _impl(
        kind=kind,
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def completeness_missing_value_plot_peptide(
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_plot_peptide as _impl

    return _impl(
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def completeness_missing_value_plot_precursor(
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_plot_precursor as _impl

    return _impl(
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def completeness_missing_value_heatmap(
    kind: AnnotationKind,
    include_id: bool = True,
    header: bool = True,
    width_cm: float = 10,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_heatmap as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def completeness_tables(
    kind: AnnotationKind,
    outlier_threshold: float = 50.0,
    include_id: bool = True,
) -> CompletenessTablesResponse:
    from app.services.completeness_tools import completeness_tables as _impl

    return _impl(
        kind=kind,
        outlier_threshold=outlier_threshold,
        include_id=include_id,
    )


# QC Pipeline
def qc_coverage_plot(
    kind: AnnotationKind,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_coverage_plot as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        legend=legend,
        summary=summary,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_peptide_coverage_plot(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_peptide_coverage_plot as _impl

    return _impl(
        include_id=include_id,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_intensity_histogram_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_intensity_histogram_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_boxplot_plot(
    kind: AnnotationKind,
    mode: str = "Mean",
    outliers: bool = False,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_boxplot_plot as _impl

    return _impl(
        kind=kind,
        mode=mode,
        outliers=outliers,
        include_id=include_id,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_cv_plot(
    kind: AnnotationKind,
    outliers: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_cv_plot as _impl

    return _impl(
        kind=kind,
        outliers=outliers,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_pca_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 5,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_pca_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        method=method,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        color_by=color_by,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        dbscan_eps=dbscan_eps,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_pca_interactive_html(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 8,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict | None = None,
) -> str:
    from app.services.plot_images import qc_pca_interactive_html as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        method=method,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        color_by=color_by,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        dbscan_eps=dbscan_eps,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
    )


def qc_abundance_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_abundance_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        condition=condition,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_abundance_interactive_html(
    kind: AnnotationKind,
    condition: str = "All Conditions",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict | None = None,
) -> str:
    from app.services.plot_images import qc_abundance_interactive_html as _impl

    return _impl(
        kind=kind,
        condition=condition,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
    )


def qc_correlation_plot(
    kind: AnnotationKind,
    method: str = "Matrix",
    include_id: bool = False,
    full_range: bool = False,
    width_cm: float = 20,
    height_cm: float = 16,
    dpi: int = 400,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_correlation_plot as _impl

    return _impl(
        kind=kind,
        method=method,
        include_id=include_id,
        full_range=full_range,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


# Single Protein Pipeline
def single_protein_boxplot_plot(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    outliers: bool = False,
    dots: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.single_protein_tools import single_protein_boxplot_plot as _impl

    return _impl(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
        outliers=outliers,
        dots=dots,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def single_protein_lineplot_plot(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    include_id: bool = False,
    identifier: str = "workflow",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.single_protein_tools import single_protein_lineplot_plot as _impl

    return _impl(
        kind=kind,
        proteins=proteins,
        conditions=conditions,
        include_id=include_id,
        identifier=identifier,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def single_protein_heatmap_plot(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    include_id: bool = False,
    header: bool = True,
    filter_m1: bool = True,
    cluster_rows: bool = False,
    cluster_cols: bool = False,
    value_type: str = "log2",
    cmap_name: str = "plasma",
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.single_protein_tools import single_protein_heatmap_plot as _impl

    return _impl(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
        include_id=include_id,
        header=header,
        filter_m1=filter_m1,
        cluster_rows=cluster_rows,
        cluster_cols=cluster_cols,
        value_type=value_type,
        cmap_name=cmap_name,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


# Phospho-specific Pipeline
def phosphosite_plot_png(
    cutoff: float = 0.0,
    color: str = "#87CEEB",
    width_cm: float = 15,
    height_cm: float = 10,
    dpi: int = 100,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phosphosite_plot_png as _impl

    return _impl(
        cutoff=cutoff,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def phospho_coverage_png(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: str = "Normal",
    color_class_i: str = "#2563eb",
    color_not_class_i: str = "#f59e0b",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    conditions: list[str] | None = None,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_coverage_png as _impl

    return _impl(
        include_id=include_id,
        header=header,
        legend=legend,
        mode=mode,
        color_class_i=color_class_i,
        color_not_class_i=color_not_class_i,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        conditions=conditions,
        advanced=advanced,
    )


def phospho_distribution_png(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    width_cm: float = 20,
    height_cm: float = 15,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_distribution_png as _impl

    return _impl(
        cutoff=cutoff,
        header=header,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def phospho_sty_png(
    header: bool = True,
    width_cm: float = 17.78,
    height_cm: float = 11.43,
    dpi: int = 140,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_sty_png as _impl

    return _impl(
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


# Comparison Pipeline
def comparison_pearson_png(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 60,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.comparison_tools import pearson_correlation_png as _impl

    return _impl(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
        alias1=alias1,
        alias2=alias2,
        color=color,
        dot_size=dot_size,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def comparison_pearson_html(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 8,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    advanced: dict | None = None,
) -> str:
    from app.services.comparison_tools import pearson_correlation_html as _impl

    return _impl(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
        alias1=alias1,
        alias2=alias2,
        color=color,
        dot_size=dot_size,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
    )


def comparison_venn_png(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
    color1: str = "#1f77b4",
    color2: str = "#ff7f0e",
    color3: str = "#2ca02c",
    header: bool = True,
    width_cm: float = 15,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.comparison_tools import venn_png as _impl

    return _impl(
        kind=kind,
        mode=mode,
        first=first,
        second=second,
        third=third,
        alias1=alias1,
        alias2=alias2,
        alias3=alias3,
        color1=color1,
        color2=color2,
        color3=color3,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


apply_cached_wrappers(
    globals(),
    [
        "imputation_before_plot",
        "imputation_overall_fit_plot",
        "imputation_after_plot",
        "distribution_qqnorm_plot",
        "completeness_missing_value_plot",
        "completeness_missing_value_plot_peptide",
        "completeness_missing_value_plot_precursor",
        "completeness_missing_value_heatmap",
        "completeness_tables",
        "qc_coverage_plot",
        "qc_peptide_coverage_plot",
        "qc_intensity_histogram_plot",
        "qc_boxplot_plot",
        "qc_cv_plot",
        "qc_pca_plot",
        "qc_pca_interactive_html",
        "qc_abundance_plot",
        "qc_abundance_interactive_html",
        "qc_correlation_plot",
        "single_protein_boxplot_plot",
        "single_protein_lineplot_plot",
        "single_protein_heatmap_plot",
        "phosphosite_plot_png",
        "phospho_coverage_png",
        "phospho_distribution_png",
        "phospho_sty_png",
        "comparison_pearson_png",
        "comparison_pearson_html",
        "comparison_venn_png",
    ],
)
