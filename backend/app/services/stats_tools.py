from __future__ import annotations

from app.services.functions import comparison_contrast, entity_labels_for_kind

from app.services.reference_db import reference_db_candidates
from app.services.plot_export import (
    MAX_AUTO_FIT_CM,
    MAX_AUTO_FIT_PIXELS,
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
    fit_figure_to_labels as _fit_figure_to_labels,
)

import logging

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.spatial.distance import pdist
from scipy.stats import hypergeom

from app.schemas.annotation import AnnotationKind, DataSource, ResolvedSource
from app.schemas.stats import (
    AnovaRequest,
    AnovaResultResponse,
    EnrichmentRequest,
    EnrichmentResultResponse,
    EnrichmentTerm,
    OraDirection,
    HeatmapValueType,
    IdentifierOption,
    ListEnrichmentRequest,
    ListEnrichmentResultResponse,
    PathwayOptionsResponse,
    SimulationRequest,
    SimulationResultResponse,
    StatisticalOptionsResponse,
    StatsIdentifier,
    VolcanoControlRequest,
    VolcanoRequest,
    VolcanoResultResponse,
)
from app.services.clustering_tools import (
    CompletenessReport,
    heatmap_notice,
    completeness_message,
    drop_incomplete_features,
    row_zscore,
)
from app.services.functions import (
    _significance_pval_column,
    constant_within_group,
    constant_differences,
    without_variation,
    imputed_value_counts,
    _phosprot_values_are_centred,
    intensity_unit_label,
    anova_posthoc_data,
    data_source_options,
    select_matrix,
    extract_sample_id as _extract_id_or_number,
    imputed_data_available,
    paired_sample_columns,
    paired_t_test,
    effective_test_type,
    resolve_test_type,
)
from app.services.plot_styling import (
    advanced_alpha,
    advanced_color_text,
    advanced_condition_colors,
    advanced_element_number,
    advanced_label,
    advanced_number,
    advanced_optional_number,
    advanced_plotly_layout,
    advanced_size,
    advanced_text,
    apply_advanced_axes,
    advanced_color_map,
    marker_area,
    resolve_marker_shape,
    resolve_reference_line,
)
from app.services.runtime_cache import apply_cached_wrappers
from app.services.plotting_common import get_plt as _get_plt, get_plotly_go as _get_plotly, plotly_html as _plotly_html
from app.services.stats_core import (
    bh_adjust as _bh_adjust,
    pooled_se_df,
    satterthwaite as _satterthwaite,
    two_sided_t_pvalues,
)

# A downloaded table is read without the UI that produced it, so every column
# means one thing: `pval` is the raw p-value, `adj_pval` always the
# Benjamini-Hochberg adjusted one, and `selected_pval` the one significance was
# called on (raw when "use uncorrected p-values" is on, otherwise adjusted), with
# `neg_log10_selected_pval` the plotted -log10 of it. `correction` states which.
CORRECTION_BENJAMINI_HOCHBERG = "Benjamini-Hochberg"
CORRECTION_NONE = "none (uncorrected)"


def _correction_label(use_uncorrected: bool) -> str:
    return CORRECTION_NONE if use_uncorrected else CORRECTION_BENJAMINI_HOCHBERG


def _variance_and_count(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    counts = np.sum(np.isfinite(values), axis=1).astype(float)
    variances = np.nanvar(values, axis=1, ddof=1)
    return variances, counts


def _safe_neg_log10(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(float), 1e-300, 1.0)
    return -np.log10(clipped)


def _stats_source(
    kind: AnnotationKind,
    *,
    data_source: DataSource = "data",
) -> tuple[ResolvedSource, pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    source_used, frame, metadata = select_matrix(
        kind,
        data_source=data_source,
    )
    return source_used, frame, metadata, warnings


def _imputed_available(kind: AnnotationKind) -> bool:
    return imputed_data_available(kind)


def _imputation_mask(
    kind: AnnotationKind,
    source_used: str,
    frame: pd.DataFrame,
    sample_columns: list[str],
) -> pd.DataFrame | None:
    """Which cells of `frame` hold imputed values, when that can be known.

    Protein and phosphosite data: the imputed matrix against the matrix it was
    imputed from (filtered, else log2 -- the same choice `run_imputation`
    makes). Phosphoproteins: from their per-sample site-contribution counts, which also
    covers a phosphoprotein table aggregated from imputed sites. None when the
    matrix carries no imputed values or they cannot be located.
    """
    from app.services.annotation_store import get_annotation
    from app.services.functions import imputed_cell_mask, site_observed_imputed_mask

    samples = [sample for sample in sample_columns if sample in frame.columns]
    if not samples:
        return None
    if kind == "phosprot":
        return site_observed_imputed_mask(frame, samples)
    if source_used != "imputed":
        return None
    annotation = get_annotation(kind)
    if annotation is None:
        return None
    before = None
    for candidate in (getattr(annotation, "filtered_data", None), getattr(annotation, "log2_data", None)):
        if isinstance(candidate, pd.DataFrame) and len(candidate.columns) and not candidate.empty:
            before = candidate
            break
    if before is None or not frame.index.isin(before.index).all():
        return None
    if not all(sample in before.columns for sample in samples):
        return None
    return imputed_cell_mask(frame[samples], before[samples])


def _first_available_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _workflow_label_candidates(kind: AnnotationKind) -> list[str]:
    if kind == "protein":
        return ["ProteinNames"]
    if kind == "phospho":
        return ["PTM_Collapse_key", "UPD_seq"]
    return ["Phosphoprotein", "ProteinNames", "PTM_Collapse_key"]


def _gene_label_candidates(kind: AnnotationKind) -> list[str]:
    if kind == "phosprot":
        return ["Gene_group", "GeneNames"]
    return ["GeneNames", "Gene_group"]


def _identifier_options(kind: AnnotationKind, frame: pd.DataFrame) -> list[IdentifierOption]:
    options: list[IdentifierOption] = []
    workflow_column = _first_available_column(frame, _workflow_label_candidates(kind))
    if workflow_column:
        workflow_label_map = {
            "ProteinNames": "Protein Names",
            "PTM_Collapse_key": "Phosphosite Names",
            "UPD_seq": "Phosphosite Sequence",
            "Phosphoprotein": "Phosphoprotein Names",
        }
        options.append(
            IdentifierOption(
                key="workflow",
                label=workflow_label_map.get(workflow_column, "Workflow Names"),
            )
        )

    genes_column = _first_available_column(frame, _gene_label_candidates(kind))
    if genes_column:
        options.append(
            IdentifierOption(
                key="genes",
                label="Gene Group" if genes_column == "Gene_group" else "Gene Names",
            )
        )
    return options


def _resolve_label_column(kind: AnnotationKind, identifier: StatsIdentifier, frame: pd.DataFrame) -> str:
    candidates = _workflow_label_candidates(kind) if identifier == "workflow" else _gene_label_candidates(kind)
    resolved = _first_available_column(frame, candidates)
    if resolved:
        return resolved
    raise ValueError(
        "The selected identifier is not available for the current dataset: none of the columns "
        f"{', '.join(candidates)} is present. Name the identifier column accordingly in the file "
        "(for example rename a 'Protein' column to 'ProteinNames')."
    )


def statistical_options(kind: AnnotationKind) -> StatisticalOptionsResponse:
    source_used, frame, metadata, warnings = _stats_source(kind, data_source="data")
    # In the order the metadata lists them, as every plot draws them.
    conditions = metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
    samples_by_condition = {
        condition: metadata.loc[
            metadata["condition"].astype(str) == condition, "sample"
        ].astype(str).tolist()
        for condition in conditions
    }
    pair_ids_by_sample = {}
    if "pair_id" in metadata.columns:
        pair_ids_by_sample = {
            str(sample): str(pair_id).strip()
            for sample, pair_id in metadata[["sample", "pair_id"]].itertuples(
                index=False, name=None
            )
            if pd.notna(pair_id) and str(pair_id).strip()
        }
    identifiers = _identifier_options(kind, frame)
    if not identifiers:
        raise ValueError("No valid identifier columns are available for statistical analysis.")
    return StatisticalOptionsResponse(
        **data_source_options(kind),
        kind=kind,
        sourceUsed=source_used,
        imputedAvailable=_imputed_available(kind),
        availableConditions=conditions,
        samplesByCondition=samples_by_condition,
        pairIdsBySample=pair_ids_by_sample,
        availableIdentifiers=identifiers,
        warnings=warnings,
    )


def _clean_feature_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return ""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(";")[0].strip()


def _gene_tokens(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return []
    text = str(value or "").strip()
    if not text:
        return []
    return [token.strip() for token in text.split(";") if token.strip()]


def _normalize_highlight_token(value: object) -> str:
    token = str(value or "").strip().lower()
    if token.endswith("_human"):
        token = token[: -len("_human")]
    return token.strip()


def _volcano_untested_rows(
    df: pd.DataFrame,
    groups: dict[str, list[str]],
    valid_mask: np.ndarray,
    pair_counts: np.ndarray | None = None,
) -> pd.DataFrame:
    """The rows the t-test cannot use, with their value counts and means per condition.

    A row needs at least two values in every compared condition. The values are
    the ones before any control correction, so the means are the condition's own.
    """
    samples = {column for columns in groups.values() for column in columns}
    identifiers = [column for column in df.columns
                   if column not in samples and not str(column).startswith(("n_imputed__", "n_measured__", "n_fully_imputed__", "n_partially_imputed__"))
                   and column != "imputed_values"]
    rows = df.loc[~np.asarray(valid_mask, dtype=bool)]
    out = rows[identifiers].reset_index(drop=True)
    short: list[list[str]] = [[] for _ in range(len(rows))]
    for condition, columns in groups.items():
        values = rows[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(values)
        counts = finite.sum(axis=1)
        sums = np.where(finite, values, 0.0).sum(axis=1)
        out[f"n_{condition}"] = counts.astype(int)
        out[f"mean_{condition}"] = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
        for index in np.flatnonzero(counts < 2):
            short[index].append(str(condition))
    reasons = ["fewer than 2 values in " + ", ".join(names) if names else "" for names in short]
    if pair_counts is not None:
        out["n_pairs"] = pair_counts[~np.asarray(valid_mask, dtype=bool)]
        reasons = ["; ".join(filter(None, [reason, "fewer than 2 complete pairs" if count < 2 else ""]))
                   for reason, count in zip(reasons, out["n_pairs"])]
    out["reason"] = reasons
    return out


def _volcano_dataframe(
    *,
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    identifier: StatsIdentifier,
    p_value_threshold: float,
    log2fc_threshold: float,
    test_type: str,
    use_uncorrected: bool,
    data_source: DataSource = "data",
    condition1_control: str | None = None,
    condition2_control: str | None = None,
    frame_override: pd.DataFrame | None = None,
    metadata_override: pd.DataFrame | None = None,
    untested_out: list | None = None,
) -> tuple[ResolvedSource, str, pd.DataFrame, list[str]]:
    if condition1 == condition2:
        raise ValueError("Please select two different conditions.")
    if frame_override is None and metadata_override is None:
        source_used, frame, metadata, warnings = _stats_source(
            kind, data_source=data_source
        )
    elif frame_override is not None and metadata_override is not None:
        # The caller chose the matrix; report the source it asked for rather
        # than stamping every override "filtered".
        source_used = data_source
        frame = frame_override.copy()
        metadata = metadata_override.copy()
        warnings = []
    else:
        raise ValueError("Volcano frame and metadata overrides must be provided together.")
    label_column = _resolve_label_column(kind, identifier, frame)

    cols1 = metadata.loc[metadata["condition"] == condition1, "sample"].astype(str).tolist()
    cols2 = metadata.loc[metadata["condition"] == condition2, "sample"].astype(str).tolist()
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")
    test_type = effective_test_type(
        test_type, with_controls=bool(condition1_control) and bool(condition2_control)
    )
    paired, variance = resolve_test_type(test_type)
    if paired:
        cols1, cols2 = paired_sample_columns(metadata, condition1, condition2)

    selected_columns = [label_column, *cols1, *cols2]
    has_control1 = bool(condition1_control)
    has_control2 = bool(condition2_control)
    if has_control1 != has_control2:
        raise ValueError("Control-corrected volcano analysis requires both control conditions.")
    if has_control1 and has_control2:
        control_conditions = [
            str(condition1).strip(),
            str(condition1_control).strip(),
            str(condition2).strip(),
            str(condition2_control).strip(),
        ]
        if len(set(control_conditions)) != len(control_conditions):
            raise ValueError(
                "Control-corrected volcano analysis requires four distinct conditions; "
                "an experimental condition cannot be used as its own control."
            )
        ctrl1_cols = metadata.loc[metadata["condition"] == condition1_control, "sample"].astype(str).tolist()
        ctrl2_cols = metadata.loc[metadata["condition"] == condition2_control, "sample"].astype(str).tolist()
        if not ctrl1_cols or not ctrl2_cols:
            raise ValueError("Selected control conditions do not have any annotated samples.")
        selected_columns.extend([*ctrl1_cols, *ctrl2_cols])
    else:
        ctrl1_cols = []
        ctrl2_cols = []

    for extra in (
        "GeneNames",
        "Gene_group",
        "ProteinNames",
        "PTM_Collapse_key",
        "UPD_seq",
        "Protein_group",
        "Phosphoprotein",
        "site_num",
        "PTM_Collapse_keys",
    ):
        if extra in frame.columns and extra not in selected_columns:
            selected_columns.append(extra)

    df = frame[[col for col in selected_columns if col in frame.columns]].copy()
    count_groups = {condition1: cols1, condition2: cols2}
    if ctrl1_cols and ctrl2_cols:
        count_groups[str(condition1_control)] = ctrl1_cols
        count_groups[str(condition2_control)] = ctrl2_cols
    # The full frame, not df: phosphoprotein tables keep site_observed__ there.
    mask = _imputation_mask(kind, source_used, frame.loc[df.index], [c for cols in count_groups.values() for c in cols])
    imputed_columns: list[str] = []
    if mask is not None:
        counts = imputed_value_counts(mask, count_groups)
        imputed_columns = counts.columns.tolist()
        for column in imputed_columns:
            df[column] = counts[column].to_numpy()
    arr_x = df[cols1].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    arr_y = df[cols2].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)

    control_arrays: list[np.ndarray] = []
    if ctrl1_cols and ctrl2_cols:
        arr_ctrl1 = df[ctrl1_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        arr_ctrl2 = df[ctrl2_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        arr_x = arr_x - np.nanmean(arr_ctrl1, axis=1)[:, None]
        arr_y = arr_y - np.nanmean(arr_ctrl2, axis=1)[:, None]
        control_arrays = [arr_ctrl1, arr_ctrl2]

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    for control in control_arrays:
        # A control variance cannot be estimated from a single value, and it is
        # now part of the test statistic, so controls need replicates too.
        valid_mask &= np.sum(np.isfinite(control), axis=1) >= 2
    pair_counts = np.sum(np.isfinite(arr_x) & np.isfinite(arr_y), axis=1) if paired else None
    if pair_counts is not None:
        valid_mask &= pair_counts >= 2
    untested = int((~valid_mask).sum())
    if untested:
        # These rows leave the test silently otherwise, and they are often the
        # on/off cases a user is looking for, so they are counted and kept.
        reason = "fewer than 2 complete pairs" if paired else "fewer than 2 values in a compared condition"
        if control_arrays:
            reason += " or fewer than 2 values in a control condition"
        warnings.append(f"{untested:,} of {len(valid_mask):,} rows were not tested: {reason}.")
    if untested_out is not None:
        untested_out.append(_volcano_untested_rows(df, count_groups, valid_mask, pair_counts))
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for the selected comparison.")

    df = df.loc[valid_mask].reset_index(drop=True)
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    control_arrays = [control[valid_mask] for control in control_arrays]
    n1 = n1_real[valid_mask].astype(float)
    n2 = n2_real[valid_mask].astype(float)

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    # The first selected condition is the minuend everywhere in CoPYlot: the
    # title reads "condition1 vs condition2" and the axis reads
    # "condition1 - condition2", so the number under them must agree.
    log2fc = mean1 - mean2

    if paired:
        diffs = arr_x - arr_y
        mean_diff, n_diff, pvals = paired_t_test(diffs)
        log2fc = mean_diff
        if control_arrays:
            # Subtracting the control means shifts each row by a constant, so the
            # within-pair spread that paired_t_test sees is unchanged and the
            # uncertainty of the two control means is missing from it entirely.
            # Propagate it explicitly.
            components = [(np.nanvar(diffs, axis=1, ddof=1), n_diff)]
            components.extend(_variance_and_count(control) for control in control_arrays)
            se, dof = _satterthwaite(components)
            pvals = two_sided_t_pvalues(log2fc, se, dof)
    else:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        if variance == "welch":
            # Unequal variances: no pooling, Welch-Satterthwaite degrees of
            # freedom. Controls simply add two more independent components.
            components = [(var1, n1), (var2, n2)]
            components.extend(_variance_and_count(control) for control in control_arrays)
            se, dof = _satterthwaite(components)
        else:
            # Controls always take the Welch branch above: effective_test_type
            # turned "unpaired" into "unpaired_welch", because a pooled two-group
            # standard error would omit the control means' uncertainty.
            se, dof = pooled_se_df(var1, n1, var2, n2)
        pvals = two_sided_t_pvalues(log2fc, se, dof)

    no_variation = without_variation(
        [np.round(diffs, 9), *control_arrays] if paired else [arr_x, arr_y, *control_arrays]
    )
    if no_variation.any():
        pvals = np.where(no_variation, np.nan, pvals)
        warnings.append(
            f"{int(no_variation.sum()):,} rows have no variation in any compared group"
            + (" (identical paired differences)" if paired else "")
            + ", so no p-value can be computed; they are shown as Unavailable."
        )

    adj_pvals = _bh_adjust(pvals)
    selected_pvals = pvals if use_uncorrected else adj_pvals

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    significance[(selected_pvals < p_value_threshold) & (log2fc > log2fc_threshold)] = "Upregulated"
    significance[(selected_pvals < p_value_threshold) & (log2fc < -log2fc_threshold)] = "Downregulated"

    result = df.copy()
    result["log2FC"] = log2fc
    result["pval"] = pvals
    result["adj_pval"] = adj_pvals
    result["selected_pval"] = selected_pvals
    result["correction"] = _correction_label(use_uncorrected)
    result["neg_log10_selected_pval"] = _safe_neg_log10(selected_pvals)
    result["significance"] = significance
    # A variance warning is independent of whether the test has a finite p-value.
    # For a paired test the variation that matters is that of the differences.
    result["zero_variance"] = (constant_differences(diffs) if paired
                               else constant_within_group(arr_x) | constant_within_group(arr_y))
    if paired:
        result["n_pairs"] = n_diff.astype(int)
    # Imputation counts go last, after the statistics they qualify.
    result = result[[c for c in result.columns if c not in imputed_columns] + imputed_columns]
    return source_used, label_column, result, warnings


def _volcano_response(
    kind: AnnotationKind,
    source_used: ResolvedSource,
    label_column: str,
    df: pd.DataFrame,
    warnings: list[str],
    untested: pd.DataFrame | None = None,
) -> VolcanoResultResponse:
    return VolcanoResultResponse(
        kind=kind,
        sourceUsed=source_used,
        labelColumn=label_column,
        totalRows=int(len(df)),
        upregulatedCount=int((df["significance"] == "Upregulated").sum()),
        downregulatedCount=int((df["significance"] == "Downregulated").sum()),
        notSignificantCount=int((df["significance"] == "Not significant").sum()),
        unavailableCount=int((df["significance"] == "Unavailable").sum()),
        rows=df.astype(object).where(pd.notna(df), None).to_dict(orient="records"),
        warnings=warnings,
        untestedRows=([] if untested is None else
                      untested.astype(object).where(pd.notna(untested), None).to_dict(orient="records")),
    )


def run_volcano(payload: VolcanoRequest) -> VolcanoResultResponse:
    untested: list[pd.DataFrame] = []
    source_used, label_column, df, warnings = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
        data_source=payload.dataSource,
        untested_out=untested,
    )
    return _volcano_response(payload.kind, source_used, label_column, df, warnings,
                             untested[0] if untested else None)


def run_volcano_control(payload: VolcanoControlRequest) -> VolcanoResultResponse:
    untested: list[pd.DataFrame] = []
    source_used, label_column, df, warnings = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
        data_source=payload.dataSource,
        condition1_control=payload.condition1Control,
        condition2_control=payload.condition2Control,
        untested_out=untested,
    )
    return _volcano_response(payload.kind, source_used, label_column, df, warnings,
                             untested[0] if untested else None)


# The interactive palette. Screen-first: saturated enough to pick a point out of
# a cloud of thousands while hovering.
VOLCANO_COLORS = {
    "Downregulated": "#2563eb",
    "Not significant": "#94a3b8",
    "Upregulated": "#dc2626",
}

# The static palette. The same three meanings in the muted tones a journal
# figure wants, where the reader is looking at ink on paper rather than hunting
# a tooltip: ColorBrewer RdBu endpoints against a neutral grey.
VOLCANO_PRINT_COLORS = {
    "Downregulated": "#2166ac",
    "Not significant": "#bdbdbd",
    "Upregulated": "#b2182b",
}

_VOLCANO_ADVANCED_KEYS = {
    "Upregulated": ("volcanoUpSize", "volcanoUpAlpha", "volcanoUpColor"),
    "Downregulated": ("volcanoDownSize", "volcanoDownAlpha", "volcanoDownColor"),
    "Not significant": ("volcanoNsSize", "volcanoNsAlpha", "volcanoNsColor"),
}

# Non-significant points are the majority of any volcano, so they are drawn
# smaller and fainter by default: they are the backdrop the eye needs in order to
# judge the two tails, not the subject of the figure.
_VOLCANO_DEFAULTS = {
    "Upregulated": (6.0, 0.85),
    "Downregulated": (6.0, 0.85),
    "Not significant": (5.0, 0.55),
}


def _volcano_condition_texts(
    condition1: str,
    condition2: str,
    condition1_control: str | None,
    condition2_control: str | None,
    advanced: dict | None,
) -> tuple[str, str]:
    """The volcano's title and x-axis label, under the panel's condition names.

    A condition renamed in the plot appearance panel used to reach nothing on
    this figure: both texts were built from the raw names, so the reader saw one
    name in the panel and a different one on the plot. Only the names change --
    `comparison_contrast` still states condition 1 minus condition 2.
    """
    name1 = advanced_label(str(condition1), advanced, "conditionLabels")
    name2 = advanced_label(str(condition2), advanced, "conditionLabels")
    control1 = (
        advanced_label(str(condition1_control), advanced, "conditionLabels")
        if condition1_control
        else condition1_control
    )
    control2 = (
        advanced_label(str(condition2_control), advanced, "conditionLabels")
        if condition2_control
        else condition2_control
    )
    title = (
        f"{name1} vs {name2} (controls: {control1} vs {control2})"
        if condition1_control and condition2_control
        else f"{name1} vs {name2}"
    )
    axis_label = f"log2 fold change ({comparison_contrast(name1, name2, control1, control2)})"
    return title, axis_label


def _volcano_marker_style(
    advanced: dict | None, *, palette: dict[str, str]
) -> dict[str, dict[str, float | str]]:
    """Size, opacity and colour per significance class.

    One dict serves both renderers, so a size set in the advanced panel means
    the same dot in the interactive plot and in the figure that goes in the
    paper. Sizes are diameters in points (see `marker_area`).
    """
    style: dict[str, dict[str, float | str]] = {}
    for significance, (size_key, alpha_key, color_key) in _VOLCANO_ADVANCED_KEYS.items():
        default_size, default_alpha = _VOLCANO_DEFAULTS[significance]
        # This class's own setting, then the general one, then the class default.
        # Setting the general size in the panel clears the three class values, so
        # they all move together and can then be pulled apart again one by one.
        general_size = advanced_optional_number(advanced, "markerSize")
        general_alpha = advanced_optional_number(advanced, "markerAlpha")
        style[significance] = {
            "size": advanced_size(
                advanced,
                size_key,
                general_size if general_size is not None else default_size,
            ),
            "alpha": advanced_alpha(
                advanced,
                alpha_key,
                general_alpha if general_alpha is not None else default_alpha,
            ),
            "color": advanced_text(advanced, color_key) or palette[significance],
            "shape": resolve_marker_shape(advanced_text(advanced, "markerShape")),
        }
    style["_highlight"] = {
        "size": advanced_size(advanced, "volcanoHighlightSize", 10.0),
        "color": advanced_text(advanced, "volcanoHighlightColor") or "#22c55e",
    }
    return style


def _volcano_top_hits(
    volcano_df: pd.DataFrame,
    *,
    label_column: str,
    up: int,
    down: int,
) -> pd.DataFrame:
    """The most significant hits in each direction, for on-figure labelling.

    Ranked by the p-value the plot is drawn against -- `neg_log10_selected_pval` is
    what the y-axis shows, so the labelled points are the highest ones, which is
    what a reader expects "top hits" to mean. Ties are broken by |log2FC| so the
    choice is deterministic rather than dependent on row order.
    """
    if volcano_df.empty or label_column not in volcano_df.columns:
        return volcano_df.head(0)
    wanted = []
    for significance, count in (("Upregulated", up), ("Downregulated", down)):
        if count <= 0:
            continue
        subset = volcano_df[volcano_df["significance"] == significance].copy()
        if subset.empty:
            continue
        subset["_abs_fc"] = subset["log2FC"].abs()
        subset = subset.sort_values(
            ["neg_log10_selected_pval", "_abs_fc"], ascending=False, kind="mergesort"
        )
        wanted.append(subset.head(int(count)))
    if not wanted:
        return volcano_df.head(0)
    return pd.concat(wanted, ignore_index=True)


def _volcano_figure(
    volcano_df: pd.DataFrame,
    *,
    label_column: str,
    condition1: str,
    condition2: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    use_uncorrected: bool,
    highlight_terms: list[str],
    condition1_control: str | None = None,
    condition2_control: str | None = None,
    advanced: dict | None = None,
):
    go = _get_plotly()
    style = _volcano_marker_style(advanced, palette=VOLCANO_COLORS)
    color_mapping = {
        significance: str(style[significance]["color"]) for significance in VOLCANO_COLORS
    }
    normalized_highlights = {_normalize_highlight_token(term) for term in highlight_terms if _normalize_highlight_token(term)}

    def is_highlighted(value: object) -> bool:
        if not normalized_highlights:
            return False
        return any(_normalize_highlight_token(token) in normalized_highlights for token in _gene_tokens(value))

    def truncate_ptm_text(value: object, max_chars: int = 100) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]} ..."

    def build_hover_text(row: pd.Series) -> str:
        raw_label = row.get(label_column, "")
        label_text = "" if pd.isna(raw_label) else str(raw_label)
        parts = [label_text] if label_text else []
        phosphoprotein_value = row.get("Phosphoprotein")
        has_phospho_context = pd.notna(row.get("site_num")) or pd.notna(row.get("PTM_Collapse_keys")) or pd.notna(phosphoprotein_value)
        if has_phospho_context:
            phosphoprotein_text = "" if pd.isna(phosphoprotein_value) else str(phosphoprotein_value)
            site_value = row.get("site_num")
            site_text = ""
            if pd.notna(site_value):
                try:
                    site_text = str(int(float(site_value)))
                except Exception:
                    site_text = str(site_value)

            if label_column == "Phosphoprotein":
                if parts:
                    if site_text:
                        parts[0] = f"{parts[0]} ({site_text} sites)"
                elif phosphoprotein_text:
                    parts = [f"{phosphoprotein_text} ({site_text} sites)" if site_text else phosphoprotein_text]
            else:
                if phosphoprotein_text:
                    phospho_line = f"Phosphoprotein: {phosphoprotein_text}"
                    if site_text:
                        phospho_line = f"{phospho_line} ({site_text} sites)"
                    parts.append(phospho_line)
                elif site_text:
                    parts.append(f"Sites: {site_text}")

            ptm_value = row.get("PTM_Collapse_keys")
            ptm_text = truncate_ptm_text(ptm_value)
            if ptm_text:
                parts.append(ptm_text)

        if not parts:
            return ""
        return "<br>".join(parts)

    fig = go.Figure()
    for significance, color in color_mapping.items():
        subset = volcano_df[volcano_df["significance"] == significance].copy()
        if subset.empty:
            continue
        subset["_hover"] = subset.apply(build_hover_text, axis=1)
        subset["highlighted"] = subset[label_column].apply(is_highlighted)
        for highlighted, suffix in ((False, ""), (True, " (highlighted)")):
            part = subset[subset["highlighted"] == highlighted]
            if part.empty:
                continue
            size = style["_highlight"]["size"] if highlighted else style[significance]["size"]
            marker = {
                "color": color,
                "size": size,
                "opacity": style[significance]["alpha"],
                "symbol": resolve_marker_shape(
                    advanced_text(advanced, "markerShape"), "plotly"
                ),
            }
            if highlighted:
                marker["line"] = {"color": style["_highlight"]["color"], "width": 2}
                # A highlighted point is one the user went looking for, so it is
                # drawn at full strength whatever its class opacity is.
                marker["opacity"] = 1.0
            fig.add_trace(
                go.Scatter(
                    x=part["log2FC"],
                    y=part["neg_log10_selected_pval"],
                    mode="markers",
                    marker=marker,
                    name=f"{significance}{suffix}",
                    text=part["_hover"],
                    hovertemplate="%{text}<br>log2FC=%{x:.3f}<br>-log10 p=%{y:.3f}<extra></extra>",
                )
            )

    y_line = float(-np.log10(max(p_value_threshold, 1e-300)))
    max_y = max(y_line, float(volcano_df["neg_log10_selected_pval"].max()) if not volcano_df.empty else y_line)
    # The static twin of this plot has honoured the panel's reference-line colour
    # for a while and this one did not, so the same volcano changed appearance
    # when you switched renderer. Both read the same settings now.
    threshold_line = resolve_reference_line(advanced, color="black")
    if threshold_line.visible:
        for x_value in (log2fc_threshold, -log2fc_threshold):
            fig.add_shape(
                type="line", x0=x_value, x1=x_value, y0=0, y1=max_y,
                line=threshold_line.plotly(),
            )
        fig.add_shape(
            type="line",
            x0=float(volcano_df["log2FC"].min()) if not volcano_df.empty else -log2fc_threshold,
            x1=float(volcano_df["log2FC"].max()) if not volcano_df.empty else log2fc_threshold,
            y0=y_line,
            y1=y_line,
            line=threshold_line.plotly(),
        )
    volcano_title, volcano_axis_label = _volcano_condition_texts(
        condition1, condition2, condition1_control, condition2_control, advanced
    )
    fig.update_layout(
        title=volcano_title,
        xaxis_title=volcano_axis_label,
        yaxis_title="-log10 adj. p-value" if not use_uncorrected else "-log10 p-value",
        hovermode="closest",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


# Where a label may sit relative to its point, in points, best first. The top of
# a volcano is crowded in exactly one direction -- upward, towards the apex -- so
# the near offsets are tried diagonally outward before anything is pushed far.
_LABEL_OFFSETS = (
    (5, 5), (5, -7), (-5, 5), (-5, -7),
    (10, 13), (10, -15), (-10, 13), (-10, -15),
    (0, 17), (0, -19), (20, 0), (-20, 0),
    (16, 26), (-16, 26), (16, -28), (-16, -28),
    (0, 34), (0, -36), (30, 14), (-30, 14),
    (0, 50), (0, -52), (44, 22), (-44, 22),
)
# Beyond this distance the connection between label and point stops being
# obvious, so a leader line is drawn.
_LABEL_LEADER_AFTER = 20.0


def _place_volcano_labels(
    fig,
    ax,
    hits: pd.DataFrame,
    *,
    label_column: str,
    fontsize: float,
    color: str = "#111827",
) -> int:
    """Label the named points without letting the labels land on each other.

    Annotating at a fixed offset is what every first attempt does, and on a real
    volcano the top hits are metres apart in data space and millimetres apart on
    the page -- so the labels stack into an unreadable smear exactly where the
    reader is looking.

    So each label is measured after it is drawn and kept only if its box misses
    every box already placed; otherwise it is moved to the next candidate
    position. Labels are placed most-significant first, so the hit that matters
    most gets the position closest to its point and the crowding is pushed
    outward onto the less important ones. A label that ends up far from home
    gets a leader line. One that cannot be placed at all is dropped rather than
    drawn on top of something -- returning the count so the caller can say so.
    """
    if hits.empty or label_column not in hits.columns:
        return 0

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    placed: list[Any] = []
    drawn = 0

    ordered = hits.sort_values("neg_log10_selected_pval", ascending=False, kind="mergesort")
    for row in ordered.itertuples():
        text = str(getattr(row, label_column, "") or "").strip()
        if not text:
            continue
        point = (float(row.log2FC), float(row.neg_log10_selected_pval))
        annotation = None
        for x_offset, y_offset in _LABEL_OFFSETS:
            distance = (x_offset**2 + y_offset**2) ** 0.5
            annotation = ax.annotate(
                text,
                point,
                textcoords="offset points",
                xytext=(x_offset, y_offset),
                fontsize=fontsize,
                color=color,
                ha="left" if x_offset >= 0 else "right",
                va="bottom" if y_offset >= 0 else "top",
                zorder=5,
                arrowprops=(
                    {"arrowstyle": "-", "color": "#9ca3af", "linewidth": 0.5,
                     "shrinkA": 1.0, "shrinkB": 2.0}
                    if distance > _LABEL_LEADER_AFTER
                    else None
                ),
            )
            box = annotation.get_window_extent(renderer=renderer)
            inside = box.x0 >= 0 and box.y0 >= 0 and box.x1 <= fig.bbox.x1 and box.y1 <= fig.bbox.y1
            # Cushioned, and more so vertically: two labels whose boxes merely
            # touch still read as one run of text at this size.
            cushioned = box.expanded(1.04, 1.35)
            clear = all(not cushioned.overlaps(other) for other in placed)
            if inside and clear:
                placed.append(cushioned)
                drawn += 1
                break
            annotation.remove()
            annotation = None
    return drawn


def _volcano_png_figure(
    volcano_df: pd.DataFrame,
    *,
    label_column: str,
    condition1: str,
    condition2: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    use_uncorrected: bool,
    highlight_terms: list[str],
    condition1_control: str | None = None,
    condition2_control: str | None = None,
    advanced: dict | None = None,
    width_cm: float = 18.0,
    height_cm: float = 14.0,
    dpi: int = 300,
    label_top_up: int = 0,
    label_top_down: int = 0,
):
    """The volcano as a figure for a paper rather than for a mouse.

    The interactive plot earns its gridlines and its full frame: they help you
    read a value off a tooltip. On paper they are ink that carries no
    information, so this version drops them, keeps only the two spines the data
    is measured against, mutes the palette, and moves the legend out of the
    plotting area where it cannot sit on top of a point.

    Nothing is labelled unless asked. A volcano of 8,000 features has no
    readable set of labels, and a figure that picks some for you is a figure
    that made an editorial decision you did not see -- so `label_top_up` and
    `label_top_down` default to zero and the caller says how many it wants.
    """
    plt = _get_plt()
    style = _volcano_marker_style(advanced, palette=VOLCANO_PRINT_COLORS)
    fig, ax = plt.subplots(
        figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi))
    )

    normalized_highlights = {
        _normalize_highlight_token(term) for term in highlight_terms if _normalize_highlight_token(term)
    }

    def is_highlighted(value: object) -> bool:
        if not normalized_highlights:
            return False
        return any(
            _normalize_highlight_token(token) in normalized_highlights
            for token in _gene_tokens(value)
        )

    # Drawn least-interesting first so the significant tails end up on top of the
    # grey cloud rather than buried in it.
    for significance in ("Not significant", "Downregulated", "Upregulated"):
        subset = volcano_df[volcano_df["significance"] == significance]
        if subset.empty:
            continue
        settings = style[significance]
        ax.scatter(
            subset["log2FC"],
            subset["neg_log10_selected_pval"],
            s=marker_area(float(settings["size"])),
            c=str(settings["color"]),
            alpha=float(settings["alpha"]),
            marker=str(settings["shape"]),
            linewidths=0.0,
            edgecolors="none",
            label=significance,
            rasterized=True,
        )

    if normalized_highlights and label_column in volcano_df.columns:
        picked = volcano_df[volcano_df[label_column].apply(is_highlighted)]
        if not picked.empty:
            ax.scatter(
                picked["log2FC"],
                picked["neg_log10_selected_pval"],
                s=marker_area(float(style["_highlight"]["size"])),
                facecolors="none",
                edgecolors=str(style["_highlight"]["color"]),
                linewidths=1.2,
                label="Highlighted",
                zorder=4,
            )

    y_line = float(-np.log10(max(p_value_threshold, 1e-300)))
    threshold_line = resolve_reference_line(advanced, color="#9ca3af", width=0.8)
    if threshold_line.visible:
        for x_value in (log2fc_threshold, -log2fc_threshold):
            if x_value:
                ax.axvline(x_value, zorder=1, **threshold_line.matplotlib())
        ax.axhline(y_line, zorder=1, **threshold_line.matplotlib())

    volcano_title, volcano_axis_label = _volcano_condition_texts(
        condition1, condition2, condition1_control, condition2_control, advanced
    )
    ax.set_xlabel(volcano_axis_label, fontsize=11)
    ax.set_ylabel("-log10 p-value" if use_uncorrected else "-log10 adj. p-value", fontsize=11)
    ax.set_title(volcano_title, fontsize=12)
    ax.tick_params(labelsize=9)
    # The journal defaults. `apply_advanced_axes` runs afterwards, so anyone who
    # wants the frame or the grid back can still ask for it.
    ax.grid(False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    # An empty comparison has no classes to list, and asking for a legend then
    # only produces a warning.
    legend = (
        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.01, 1.0),
            frameon=False,
            fontsize=9,
            markerscale=1.6,
            borderaxespad=0.0,
        )
        if ax.get_legend_handles_labels()[0]
        else None
    )
    if legend is not None:
        legend.set_zorder(6)
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()

    # Labelled last, and after the layout has settled. Placement is measured in
    # display coordinates, and `tight_layout` moves the axes -- so labels chosen
    # before it are checked against positions the figure does not end up having,
    # and land on each other anyway.
    if label_top_up > 0 or label_top_down > 0:
        hits = _volcano_top_hits(
            volcano_df, label_column=label_column, up=label_top_up, down=label_top_down
        )
        _place_volcano_labels(
            fig,
            ax,
            hits,
            label_column=label_column,
            fontsize=max(4.0, advanced_number(advanced, "volcanoLabelSize", 7.0)),
        )
    return fig, plt


def _volcano_inputs(payload: VolcanoRequest | VolcanoControlRequest) -> tuple[pd.DataFrame, dict]:
    """The rows behind a volcano, and the arguments both renderers draw from.

    A volcano varies along two axes: plain or control-corrected (two more
    conditions, carried by the payload), and figure or interactive page (a
    different renderer). That used to be four functions repeating one argument
    list, which is four places for a new setting to reach three of them.
    """
    controls = {}
    if isinstance(payload, VolcanoControlRequest):
        controls = {
            "condition1_control": payload.condition1Control,
            "condition2_control": payload.condition2Control,
        }
    _, label_column, df, _ = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
        data_source=payload.dataSource,
        **controls,
    )
    figure_arguments = {
        "label_column": label_column,
        "condition1": payload.condition1,
        "condition2": payload.condition2,
        "p_value_threshold": payload.pValueThreshold,
        "log2fc_threshold": payload.log2fcThreshold,
        "use_uncorrected": payload.useUncorrected,
        "highlight_terms": payload.highlightTerms,
        **controls,
    }
    return df, figure_arguments


def volcano_png(
    payload: VolcanoRequest | VolcanoControlRequest,
    advanced: dict | None = None,
    *,
    width_cm: float = 18.0,
    height_cm: float = 14.0,
    dpi: int = 300,
    label_top_up: int = 0,
    label_top_down: int = 0,
) -> bytes:
    """The volcano as a figure for print; a control request draws the control volcano."""
    df, figure_arguments = _volcano_inputs(payload)
    fig, plt = _volcano_png_figure(
        df,
        **figure_arguments,
        advanced=advanced,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        label_top_up=label_top_up,
        label_top_down=label_top_down,
    )
    return _to_png_bytes(fig, plt, dpi=dpi)


def volcano_html(
    payload: VolcanoRequest | VolcanoControlRequest, advanced: dict | None = None
) -> str:
    """The same volcano as the interactive page."""
    df, figure_arguments = _volcano_inputs(payload)
    fig = _volcano_figure(df, **figure_arguments, advanced=advanced)
    fig.update_layout(**advanced_plotly_layout(advanced))
    return _plotly_html(fig)


def _anova_dataframe(
    payload: AnovaRequest,
) -> tuple[ResolvedSource, str, pd.DataFrame, list[str]]:
    source_used, frame, metadata, warnings = _stats_source(payload.kind, data_source=payload.dataSource)
    label_column = _resolve_label_column(payload.kind, payload.identifier, frame)

    metadata = metadata.copy()
    metadata["sample"] = metadata["sample"].astype(str)
    metadata["condition"] = metadata["condition"].astype(str)
    conditions = metadata["condition"].dropna().drop_duplicates().tolist()
    if len(conditions) < 2:
        raise ValueError("ANOVA needs at least two conditions.")

    condition_cols = {
        condition: [
            sample
            for sample in metadata.loc[metadata["condition"] == condition, "sample"].tolist()
            if sample in frame.columns
        ]
        for condition in conditions
    }
    too_few = [condition for condition, cols in condition_cols.items() if len(cols) < 2]
    if too_few:
        raise ValueError(
            "Each ANOVA condition needs at least two sample columns. Missing: "
            + ", ".join(map(str, too_few))
        )

    sample_cols = [col for cols in condition_cols.values() for col in cols]
    selected_columns = [label_column, *sample_cols]
    for extra in (
        "GeneNames",
        "Gene_group",
        "ProteinNames",
        "PTM_Collapse_key",
        "Phosphoprotein",
        "site_num",
        "PTM_Collapse_keys",
    ):
        if extra in frame.columns and extra not in selected_columns:
            selected_columns.append(extra)

    df = frame[[col for col in selected_columns if col in frame.columns]].copy()
    df[sample_cols] = df[sample_cols].apply(pd.to_numeric, errors="coerce")
    mask = _imputation_mask(payload.kind, source_used, frame.loc[df.index], sample_cols)
    imputed_columns: list[str] = []
    if mask is not None:
        counts = imputed_value_counts(mask, condition_cols)
        imputed_columns = counts.columns.tolist()
        for column in imputed_columns:
            df[column] = counts[column].to_numpy()

    valid = np.ones(len(df), dtype=bool)
    groups: list[np.ndarray] = []
    for cols in condition_cols.values():
        group = df[cols].to_numpy(dtype=float)
        valid &= np.sum(~np.isnan(group), axis=1) >= 2
        groups.append(group)
    if not np.any(valid):
        raise ValueError("No rows have enough replicate values for ANOVA.")
    untested = int((~valid).sum())
    if untested:
        warnings = [*warnings, (
            f"{untested:,} of {len(valid):,} rows were not tested: fewer than 2 values in at least "
            "one condition."
        )]

    df = df.loc[valid].reset_index(drop=True)
    groups = [group[valid] for group in groups]

    try:
        from scipy import stats

        f_stat, pvals = stats.f_oneway(*groups, axis=1, nan_policy="omit")
    except TypeError:
        from scipy import stats

        f_stat = np.empty(len(df), dtype=float)
        pvals = np.empty(len(df), dtype=float)
        for i in range(len(df)):
            row_groups = [group[i][~np.isnan(group[i])] for group in groups]
            f_stat[i], pvals[i] = stats.f_oneway(*row_groups)

    # Do not coerce NaN to 1.0 here: f_oneway returns NaN when the whole row is
    # constant, and coercing first would make the isfinite filter below a no-op,
    # keeping untestable rows in the BH pool. A row that is constant within every
    # condition but differs between them is different: F is infinite (or, with
    # floating-point noise, enormous). It stays in the table, flagged as
    # zero_variance below, but gets no p-value -- the same rule the volcano
    # applies to rows without variation.
    finite = np.isfinite(pvals)
    if not finite.all():
        warnings = [*warnings, (
            f"{int((~finite).sum()):,} rows were not tested: their values are identical in every "
            "condition, so no F statistic exists."
        )]
    df = df.loc[finite].reset_index(drop=True)
    groups = [group[finite] for group in groups]
    f_stat = np.asarray(f_stat, dtype=float)[finite]
    pvals = pvals[finite]

    means = pd.DataFrame(
        {
            condition: np.nanmean(group, axis=1)
            for condition, group in zip(condition_cols.keys(), groups)
        },
        index=df.index,
    )

    # No variation within any condition: an infinite (or, with floating-point
    # noise, enormous) F says nothing about the size of the difference, only that
    # the variance is absent. As in the volcano, such rows get no p-value, stay
    # out of the BH family and are shown as Unavailable; the flag names them.
    zero_variance = np.logical_and.reduce([constant_within_group(group) for group in groups])
    if zero_variance.any():
        pvals = np.where(zero_variance, np.nan, pvals)
        warnings = [*warnings, (
            f"{int(zero_variance.sum()):,} rows have no variation within any condition, so no "
            "p-value can be computed; they are shown as Unavailable and marked in the "
            "zero_variance column."
        )]

    adj_pvals = _bh_adjust(pvals)
    selected_pvals = pvals if payload.useUncorrected else adj_pvals
    result = df.copy()
    result["f_statistic"] = f_stat
    result["pval"] = pvals
    result["adj_pval"] = adj_pvals
    result["selected_pval"] = selected_pvals
    result["correction"] = _correction_label(payload.useUncorrected)
    significance = np.where(
        selected_pvals < payload.pValueThreshold,
        "Significant",
        "Not significant",
    ).astype(object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    result["significance"] = significance
    result["neg_log10_selected_pval"] = _safe_neg_log10(selected_pvals)
    result["zero_variance"] = zero_variance
    for condition in means.columns:
        result[f"mean_{condition}"] = means[condition].to_numpy()
    result = result[[c for c in result.columns if c not in imputed_columns] + imputed_columns]

    # Benjamini-Hochberg ties many features to the same adjusted p; raw p then
    # the label keeps the order identical to both shipped packages.
    sort_keys = ["selected_pval", "pval"]
    if label_column in result.columns:
        sort_keys.append(label_column)
    return (
        source_used,
        label_column,
        result.sort_values(sort_keys, kind="mergesort").reset_index(drop=True),
        warnings,
    )


def _anova_cluster_dataframe(
    anova_df: pd.DataFrame, metadata: pd.DataFrame, payload: AnovaRequest
) -> tuple[pd.DataFrame, CompletenessReport | None]:
    sample_cols = [
        sample
        for sample in metadata["sample"].astype(str).tolist()
        if sample in anova_df.columns
    ]
    if not sample_cols:
        raise ValueError("No sample columns from metadata were found in the ANOVA table.")

    cluster_df = anova_df[anova_df[_significance_pval_column(anova_df)] < payload.pValueThreshold].copy()
    if cluster_df.empty:
        cluster_df.insert(1, "cluster", pd.Series(index=cluster_df.index, dtype="int64"))
        return cluster_df.reset_index(drop=True), None

    matrix = cluster_df[sample_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    # Features missing in any sample cannot be clustered, so they are dropped
    # here rather than refusing the whole request. The caller reports how many.
    completeness: CompletenessReport | None = None
    if matrix.shape[0] > 1:
        matrix, completeness = drop_incomplete_features(matrix, context="ANOVA clustering")
        cluster_df = cluster_df.loc[completeness.kept].reset_index(drop=True)
    matrix = row_zscore(matrix)

    if matrix.shape[0] <= 1:
        cluster_df.insert(1, "cluster", 1)
        return cluster_df.reset_index(drop=True), completeness

    row_linkage = linkage(matrix, method=payload.clusterMethod, metric="euclidean")
    row_order = leaves_list(row_linkage)
    raw_clusters = fcluster(row_linkage, t=payload.nClusters, criterion="maxclust")
    ordered_clusters = raw_clusters[row_order]

    cluster_map: dict[int, int] = {}
    relabeled: list[int] = []
    for cluster_id in ordered_clusters:
        cluster_key = int(cluster_id)
        if cluster_key not in cluster_map:
            cluster_map[cluster_key] = len(cluster_map) + 1
        relabeled.append(cluster_map[cluster_key])

    out = cluster_df.iloc[row_order].copy()
    if "cluster" in out.columns:
        out = out.drop(columns=["cluster"])
    out.insert(1, "cluster", relabeled)
    return out.reset_index(drop=True), completeness


def _condition_columns(metadata: pd.DataFrame, frame: pd.DataFrame) -> dict[str, list[str]]:
    metadata = metadata.copy()
    metadata["sample"] = metadata["sample"].astype(str)
    metadata["condition"] = metadata["condition"].astype(str)
    conditions = metadata["condition"].dropna().drop_duplicates().tolist()
    return {
        condition: [
            sample
            for sample in metadata.loc[metadata["condition"] == condition, "sample"].tolist()
            if sample in frame.columns
        ]
        for condition in conditions
    }


def run_anova(payload: AnovaRequest) -> AnovaResultResponse:
    source_used, label_column, anova_df, warnings = _anova_dataframe(payload)
    cluster_df = pd.DataFrame()
    cluster_count: int | None = None
    post_hoc_df = pd.DataFrame()
    metadata: pd.DataFrame | None = None

    if payload.source == "anova_cluster" or payload.postHoc == "tukey":
        _, _, metadata, _ = _stats_source(payload.kind, data_source=payload.dataSource)

    completeness_notice: str | None = None
    if payload.source == "anova_cluster":
        cluster_df, completeness = _anova_cluster_dataframe(anova_df, metadata, payload)
        # Reported separately from `warnings` so the interface can put it
        # directly beneath the plot it changed, rather than in a general list.
        completeness_notice = completeness_message(
            completeness,
            noun=entity_labels_for_kind(payload.kind)[1],
            purpose="clustering",
        ) if completeness is not None else None
        cluster_count = int(cluster_df["cluster"].nunique()) if "cluster" in cluster_df.columns else 0
        if cluster_df.empty:
            warnings = [*warnings, "No rows passed the ANOVA threshold; clustering was not run."]

    post_hoc_comparison: str | None = None
    if payload.postHoc == "tukey":
        condition_cols = _condition_columns(metadata, anova_df)
        # One pair costs one studentized-range integral per significant feature,
        # and that integral is the whole cost of the request, so asking for the
        # pair you are looking at is three times cheaper here than asking for
        # all of them. The numbers are the same either way: k and the pooled
        # MSE come from the entire design.
        # "" / "none" / "null" mean absent here, as they do throughout these
        # configs: the assistant reaches this endpoint through a text mode
        # string, where an unset field arrives as the word rather than as null.
        def _named(value: object) -> str:
            text = str(value or "").strip()
            return "" if text.lower() in {"", "none", "null"} else text

        first, second = _named(payload.postHocCondition1), _named(payload.postHocCondition2)
        requested_pair = (first, second) if first and second else None
        post_hoc_df = anova_posthoc_data(
            anova_df,
            metadata,
            in_pval=payload.pValueThreshold,
            label_col=label_column,
            pair=requested_pair,
        )
        if requested_pair is not None and len(condition_cols) >= 3:
            post_hoc_comparison = f"{requested_pair[0]} vs {requested_pair[1]}"
        if len(condition_cols) < 3:
            warnings = [
                *warnings,
                "Tukey HSD was not run: with two conditions the ANOVA and the single "
                "pairwise comparison test the same thing.",
            ]
        elif post_hoc_df.empty:
            if (anova_df[_significance_pval_column(anova_df)] < payload.pValueThreshold).any():
                warnings = [*warnings, "Rows passed the ANOVA threshold, but no usable Tukey HSD comparisons could be calculated."]
            else:
                warnings = [*warnings, "No rows passed the ANOVA threshold, so Tukey HSD was not run."]

    return AnovaResultResponse(
        kind=payload.kind,
        source=payload.source,
        sourceUsed=source_used,
        labelColumn=label_column,
        totalRows=int(len(anova_df)),
        significantCount=int((anova_df[_significance_pval_column(anova_df)] < payload.pValueThreshold).sum()),
        clusterCount=cluster_count,
        completenessNotice=completeness_notice,
        rows=anova_df.astype(object).where(pd.notna(anova_df), None).to_dict(orient="records"),
        clusterRows=cluster_df.astype(object).where(pd.notna(cluster_df), None).to_dict(orient="records") if not cluster_df.empty else [],
        postHocMethod="Tukey HSD" if payload.postHoc == "tukey" else None,
        postHocRows=post_hoc_df.astype(object).where(pd.notna(post_hoc_df), None).to_dict(orient="records")
        if not post_hoc_df.empty
        else [],
        postHocComparison=post_hoc_comparison,
        postHocSignificantCount=int((post_hoc_df["significance"] == "Significant").sum())
        if not post_hoc_df.empty
        else 0,
        warnings=warnings,
    )


def _prepare_anova_plot_frame(
    payload: AnovaRequest,
    selected_cluster: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    _, label_column, anova_df, _ = _anova_dataframe(payload)
    _, _, metadata, _ = _stats_source(payload.kind, data_source=payload.dataSource)
    if payload.source == "anova_cluster":
        anova_df, completeness = _anova_cluster_dataframe(anova_df, metadata, payload)
        if selected_cluster is not None:
            anova_df = anova_df[anova_df["cluster"] == selected_cluster].copy()
            if anova_df.empty:
                raise ValueError(f"Cluster {selected_cluster} was not found in the ANOVA cluster result.")
        if completeness is not None:
            if selected_cluster is None:
                anova_df.attrs["heatmap_total"] = completeness.total
            elif completeness.any_dropped:
                anova_df.attrs["heatmap_upstream_notice"] = (
                    f"Before cluster selection, {completeness.dropped:,} of {completeness.total:,} "
                    "features were excluded from clustering because of missing values."
                )
    return anova_df, metadata, label_column


def _anova_heatmap_figure(
    plot_df: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    kind: AnnotationKind,
    advanced: dict | None,
    label_column: str,
    p_value_threshold: float,
    clustered: bool,
    show_dendrograms: bool,
    show_legend: bool,
    selected_cluster: int | None = None,
    row_labels: bool = False,
):
    plt = _get_plt()
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Patch

    metadata = metadata.copy()
    metadata["sample"] = metadata["sample"].astype(str)
    metadata["condition"] = metadata["condition"].astype(str)
    metadata["plot_sample"] = (
        metadata["new_sample"].astype(str)
        if "new_sample" in metadata.columns
        else metadata["condition"] + "_" + (metadata.groupby("condition").cumcount() + 1).astype(str)
    )

    sample_cols = [sample for sample in metadata["sample"].tolist() if sample in plot_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from metadata were found in the ANOVA table.")

    if not clustered:
        plot_df = plot_df[plot_df[_significance_pval_column(plot_df)] < p_value_threshold].copy()

    if plot_df.empty:
        fig, ax = plt.subplots(figsize=(12, 8), dpi=150)
        ax.set_axis_off()
        ax.set_title("ANOVA heatmap")
        ax.text(0.5, 0.5, "No rows passed the ANOVA threshold.", ha="center", va="center")
        return fig, plt

    total_features = plot_df.attrs.get("heatmap_total", len(plot_df))
    raw_matrix = plot_df[sample_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    # The heatmap renders missing values as gaps perfectly well; only the
    # dendrograms need complete rows, so only they force a drop.
    if (not clustered and raw_matrix.shape[0] > 1) or raw_matrix.shape[1] > 1:
        _, heatmap_completeness = drop_incomplete_features(
            raw_matrix, context="ANOVA heatmap"
        )
        plot_df = plot_df.loc[heatmap_completeness.kept]
        raw_matrix = (
            plot_df[sample_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        )
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    matrix = row_zscore(matrix)
    display_matrix = np.ma.array(matrix, mask=missing_mask | ~np.isfinite(matrix))
    cluster_matrix = matrix.copy()
    row_linkage = None
    col_linkage = None

    if not clustered and matrix.shape[0] > 1:
        row_linkage = linkage(cluster_matrix, method="average", metric="euclidean")
        row_order = leaves_list(row_linkage)
        display_matrix = display_matrix[row_order]
        cluster_matrix = cluster_matrix[row_order]
        plot_df = plot_df.iloc[row_order]

    if matrix.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method="average", metric="euclidean")
        col_order = leaves_list(col_linkage)
        display_matrix = display_matrix[:, col_order]
        sample_cols = [sample_cols[i] for i in col_order]

    sample_to_condition = dict(zip(metadata["sample"], metadata["condition"]))
    sample_to_label = dict(zip(metadata["sample"], metadata["plot_sample"]))
    conditions = [sample_to_condition.get(sample, "") for sample in sample_cols]
    x_labels = [sample_to_label.get(sample, sample) for sample in sample_cols]

    meta_condition_order = metadata["condition"].dropna().drop_duplicates().tolist()
    unique_conditions = [
        condition
        for condition in meta_condition_order
        if condition in set(conditions)
    ]
    unique_conditions.extend(
        condition
        for condition in conditions
        if condition not in unique_conditions
    )
    # The same condition colours every other plot uses, including whatever the
    # user set on the Colors page and any per-plot override. This heatmap used to
    # generate its own tab20 palette, so a condition was one colour here and a
    # different one in the volcano, PCA and boxplots beside it.
    condition_hex = advanced_condition_colors(kind, plt, unique_conditions, advanced)
    condition_colors = {
        condition: to_rgba(condition_hex.get(condition, "#808080"))
        for condition in unique_conditions
    }
    condition_strip = np.array([[condition_colors[condition] for condition in conditions]])

    cluster_values = plot_df["cluster"].tolist() if clustered and "cluster" in plot_df.columns else []
    unique_clusters = list(dict.fromkeys(cluster_values))
    cluster_colors = {}
    cluster_strip = None
    if clustered:
        cluster_palette = plt.cm.tab20b(np.linspace(0, 1, max(len(unique_clusters), 1)))
        cluster_colors = {
            cluster: cluster_palette[i % len(cluster_palette)]
            for i, cluster in enumerate(unique_clusters)
        }
        cluster_strip = np.array([[cluster_colors[cluster]] for cluster in cluster_values])

    fig = plt.figure(figsize=(13.6, 9.2), dpi=150)
    fig._copylot_notice = heatmap_notice(total_features, len(plot_df))
    if plot_df.attrs.get("heatmap_upstream_notice"):
        fig._copylot_notice += ". " + plot_df.attrs["heatmap_upstream_notice"]
    left_width = 0.03 if clustered else (0.12 if show_dendrograms and row_linkage is not None else 0.01)
    top_height = 0.16 if show_dendrograms and col_linkage is not None else 0.08

    # Row labels are for the cluster heatmaps only, where a cluster is small
    # enough to read. They go to the right of the heatmap -- the left edge holds
    # the cluster strip -- in a column of their own, sized to the longest label,
    # so they never run into the colour bar.
    row_label_texts: list[str] = []
    row_label_size = 0.0
    row_label_width = 0.0
    if clustered and row_labels:
        if label_column in plot_df.columns:
            row_label_texts = [str(value) for value in plot_df[label_column].tolist()]
        else:
            row_label_texts = [str(value) for value in plot_df.index.tolist()]
        heatmap_height_pt = 9.2 * 72 * 0.62
        auto_size = min(7.0, max(2.0, 0.8 * heatmap_height_pt / max(len(row_label_texts), 1)))
        row_label_size = advanced_number(advanced, "rowLabelSize", 0.0) or auto_size
        longest = max((len(text) for text in row_label_texts), default=0)
        row_label_width = min(0.6, max(0.04, longest * row_label_size * 0.6 / 72 / 9.0))

    label_columns = [row_label_width] if row_label_texts else []
    width_ratios = [left_width, 1.0, *label_columns, 0.035]
    if show_legend:
        width_ratios += [0.105, 0.105]
    cbar_column = 2 + len(label_columns)
    grid = fig.add_gridspec(
        3,
        len(width_ratios),
        height_ratios=[top_height, 0.025, 1.0],
        width_ratios=width_ratios,
        hspace=0.02,
        wspace=0.08,
    )
    ax_top = fig.add_subplot(grid[0, 1])
    ax_strip = fig.add_subplot(grid[1, 1])
    ax_cluster = fig.add_subplot(grid[2, 0])
    ax = fig.add_subplot(grid[2, 1])
    cax = fig.add_subplot(grid[2, cbar_column])
    ax_cluster_legend = fig.add_subplot(grid[:, cbar_column + 1]) if show_legend else None
    ax_condition_legend = fig.add_subplot(grid[:, cbar_column + 2]) if show_legend else None
    if ax_cluster_legend is not None:
        ax_cluster_legend.set_axis_off()
    if ax_condition_legend is not None:
        ax_condition_legend.set_axis_off()
    if show_dendrograms and col_linkage is not None:
        from scipy.cluster.hierarchy import dendrogram

        dendrogram(
            col_linkage,
            ax=ax_top,
            no_labels=True,
            color_threshold=0,
            above_threshold_color="black",
            link_color_func=lambda _: "black",
        )
    ax_top.set_axis_off()

    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()

    if clustered and cluster_strip is not None:
        ax_cluster.imshow(cluster_strip, aspect="auto", interpolation="nearest")
    elif show_dendrograms and row_linkage is not None:
        from scipy.cluster.hierarchy import dendrogram

        dendrogram(
            row_linkage,
            ax=ax_cluster,
            orientation="left",
            no_labels=True,
            color_threshold=0,
            above_threshold_color="black",
            link_color_func=lambda _: "black",
        )
        # scipy draws leaf 0 at the bottom of a left-oriented dendrogram while
        # imshow draws row 0 at the top; flip the axis so branches meet their rows.
        ax_cluster.invert_yaxis()
    ax_cluster.set_axis_off()

    cmap = plt.get_cmap("RdBu_r").with_extremes(bad="#d8d8d8")
    image = ax.imshow(display_matrix, aspect="auto", interpolation="nearest", cmap=cmap, vmin=-2.5, vmax=2.5)
    ax.set_xlabel("samples")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(sample_cols)))
    ax.set_xticklabels(x_labels, rotation=90, fontsize=5)
    if row_label_texts:
        ax.yaxis.tick_right()
        ax.set_yticks(np.arange(len(row_label_texts)))
        ax.set_yticklabels(
            row_label_texts,
            fontsize=row_label_size,
            color=advanced_color_text(advanced, "rowLabelColor") or "black",
        )
        ax.tick_params(axis="y", length=0, pad=2)
    else:
        ax.set_yticks([])
    colorbar = fig.colorbar(image, cax=cax)
    colorbar.set_label("row z-score", labelpad=12)

    condition_handles = [
        Patch(
            facecolor=condition_colors[condition],
            # The advanced panel offers a condition rename on this plot; the
            # legend read the original name regardless.
            label=advanced_label(str(condition), advanced, "conditionLabels"),
        )
        for condition in unique_conditions
    ]
    cluster_handles = []
    if clustered:
        cluster_handles = [
            Patch(facecolor=cluster_colors[cluster], label=f"cluster {cluster}")
            for cluster in unique_clusters[:12]
        ]
    if show_legend and cluster_handles and ax_cluster_legend is not None:
        ax_cluster_legend.legend(
            handles=cluster_handles,
            title="Clusters",
            loc="upper left",
            frameon=False,
            fontsize=7,
            title_fontsize=8,
            borderaxespad=0,
            labelspacing=0.55,
            handlelength=1.1,
        )
    if show_legend and condition_handles and ax_condition_legend is not None:
        ax_condition_legend.legend(
            handles=condition_handles,
            title="Conditions",
            loc="upper left",
            frameon=False,
            fontsize=7,
            title_fontsize=8,
            borderaxespad=0,
            labelspacing=0.55,
            handlelength=1.1,
        )

    if clustered and selected_cluster is not None:
        title = f"ANOVA cluster {selected_cluster} heatmap"
    else:
        title = "ANOVA cluster heatmap" if clustered else "ANOVA heatmap"
    fig.suptitle(f"{title} ({len(plot_df)} rows)", y=0.985, fontsize=14)
    fig.subplots_adjust(left=0.04, right=0.97, top=0.93, bottom=0.18)
    return fig, plt


def anova_png(payload: AnovaRequest, selected_cluster: int | None = None, advanced: dict | None = None) -> bytes:
    plot_df, metadata, label_column = _prepare_anova_plot_frame(payload, selected_cluster=selected_cluster)
    fig, plt = _anova_heatmap_figure(
        plot_df,
        metadata,
        kind=payload.kind,
        advanced=advanced,
        label_column=label_column,
        p_value_threshold=payload.pValueThreshold,
        clustered=payload.source == "anova_cluster",
        show_dendrograms=payload.showDendrograms,
        show_legend=payload.showLegend,
        selected_cluster=selected_cluster,
        row_labels=payload.showRowLabels,
    )
    for ax in fig.axes:
        apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt, dpi=150)


def _go_db_candidates() -> list[Path]:
    return reference_db_candidates("all_go_terms_genes.csv")


@lru_cache(maxsize=1)
def load_go_db() -> pd.DataFrame:
    for path in _go_db_candidates():
        if path.exists():
            frame = pd.read_csv(path)
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            frame.attrs["database_sha256"] = digest.hexdigest()
            return frame
    searched = ", ".join(str(path) for path in _go_db_candidates())
    LOGGER.error("Gene Ontology database not found. Searched: %s", searched)
    raise ValueError(
        "Could not find the bundled Gene Ontology database (all_go_terms_genes.csv). "
        "The searched locations are recorded in the server log."
    )


def _go_database_sha256() -> str:
    db = load_go_db()
    loaded_digest = str(db.attrs.get("database_sha256", "")).strip()
    if loaded_digest:
        return loaded_digest
    canonical_csv = db.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(canonical_csv).hexdigest()


LOGGER = logging.getLogger(__name__)

GO_DATABASE_ORGANISM = "Homo sapiens"

# The organism keys the API accepts, and the database each one names. One entry
# today; a second organism is a row here plus its table, not a new code path.
GO_DATABASES: dict[str, str] = {"human": GO_DATABASE_ORGANISM}


def resolve_enrichment_organism(organism: str = "human") -> str:
    """The display name of the GO database for this organism key.

    Refuses anything it does not have rather than falling back to human: the
    numbers would be real and the species wrong, which is the one failure an
    enrichment result cannot survive.
    """
    # Blank means "not specified", not "an organism named nothing", so it takes
    # the default the same way a missing field does.
    key = (str(organism).strip().lower() or "human")
    if key not in GO_DATABASES:
        offered = ", ".join(sorted(GO_DATABASES))
        raise ValueError(
            f"No Gene Ontology database is bundled for '{organism}'. Available: {offered}."
        )
    return GO_DATABASES[key]


@lru_cache(maxsize=1)
def _annotated_gene_universe() -> frozenset[str]:
    db = load_go_db()
    universe: set[str] = set()
    for genes_text in db["genes"]:
        universe.update(
            gene.strip() for gene in str(genes_text or "").split(";") if gene.strip()
        )
    return frozenset(universe)


def _species_overlap_warning(genes: list[str]) -> str | None:
    """Warn when the supplied gene symbols barely overlap the bundled GO universe.

    The bundled Gene Ontology table is Homo sapiens only. Symbols from another
    species still produce a syntactically valid result - almost everything simply
    fails to map - so a low overlap is the practical signal that the wrong
    organism was loaded.
    """
    cleaned = {str(gene).strip() for gene in genes if str(gene or "").strip()}
    if len(cleaned) < 50:
        return None
    matched = len(cleaned & _annotated_gene_universe())
    fraction = matched / len(cleaned)
    if fraction >= 0.2:
        return None
    return (
        f"Only {matched} of {len(cleaned)} gene symbols ({fraction:.0%}) are present in the "
        f"bundled {GO_DATABASE_ORGANISM} Gene Ontology database. Enrichment assumes "
        f"{GO_DATABASE_ORGANISM} symbols; if this data is from another organism the result "
        "is not interpretable."
    )


def pathway_options() -> PathwayOptionsResponse:
    db = load_go_db()
    pathways = sorted(db["description"].dropna().astype(str).drop_duplicates().tolist())
    return PathwayOptionsResponse(pathways=pathways)


def _different_genes(
    payload: EnrichmentRequest,
) -> tuple[ResolvedSource, list[str], list[str], list[str], list[str]]:
    """Select ORA genes from the exact public Volcano result path.

    Keeping ORA on ``run_volcano_control`` is intentional: changes to the
    control correction, variance calculation, or significance classification
    are then shared by the Control Volcano tab and ORA instead of being copied.
    """
    common = dict(
        kind=payload.kind,
        dataSource=payload.dataSource,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier="genes",
        pValueThreshold=payload.pValueThreshold,
        log2fcThreshold=payload.log2fcThreshold,
        testType=payload.testType,
        useUncorrected=payload.useUncorrected,
    )
    if payload.source == "volcano_control":
        if not payload.condition1Control or not payload.condition2Control:
            raise ValueError("Volcano control source requires both control conditions.")
        volcano_result = run_volcano_control(
            VolcanoControlRequest(
                **common,
                condition1Control=payload.condition1Control,
                condition2Control=payload.condition2Control,
            )
        )
    else:
        volcano_result = run_volcano(VolcanoRequest(**common))

    source_used = volcano_result.sourceUsed
    gene_column = volcano_result.labelColumn
    df = pd.DataFrame(volcano_result.rows)
    warnings = volcano_result.warnings
    if gene_column not in df.columns:
        raise ValueError("A gene label column is required for enrichment analysis.")

    split_groups = payload.kind == "phosprot" or gene_column == "Gene_group"
    up_genes = _genes_from_values(
        df.loc[df["significance"] == "Upregulated", gene_column].tolist(),
        split_groups=split_groups,
    )
    down_genes = _genes_from_values(
        df.loc[df["significance"] == "Downregulated", gene_column].tolist(),
        split_groups=split_groups,
    )
    tested_genes = _genes_from_values(df[gene_column].tolist(), split_groups=split_groups)
    return source_used, up_genes, down_genes, tested_genes, warnings


def _anova_cluster_genes(
    payload: EnrichmentRequest,
) -> tuple[ResolvedSource, list[str], list[str], list[str]]:
    if payload.selectedCluster is None:
        raise ValueError("Select an ANOVA protein cluster to run ORA.")

    anova_payload = AnovaRequest(
        kind=payload.kind,
        source="anova_cluster",
        dataSource=payload.dataSource,
        identifier="genes",
        pValueThreshold=payload.pValueThreshold,
        useUncorrected=payload.useUncorrected,
        nClusters=payload.nClusters,
        # Must match the page the cluster was selected from: a different linkage
        # produces a different partition, so cluster 2 here would not be the
        # cluster 2 the user picked.
        clusterMethod=payload.clusterMethod,
    )
    source_used, gene_column, anova_df, warnings = _anova_dataframe(anova_payload)
    _, _, metadata, _ = _stats_source(payload.kind, data_source=payload.dataSource)
    cluster_df, _ = _anova_cluster_dataframe(anova_df, metadata, anova_payload)
    if cluster_df.empty:
        raise ValueError("No significant ANOVA rows are available for clustering or ORA.")
    if "cluster" not in cluster_df.columns:
        raise ValueError("ANOVA clustering did not produce any protein clusters.")

    available_clusters = sorted({int(value) for value in cluster_df["cluster"].dropna().tolist()})
    selected_df = cluster_df.loc[cluster_df["cluster"] == payload.selectedCluster]
    if selected_df.empty:
        available_text = ", ".join(str(value) for value in available_clusters) or "none"
        raise ValueError(
            f"ANOVA cluster {payload.selectedCluster} was not found. "
            f"Available clusters: {available_text}."
        )
    if gene_column not in selected_df.columns:
        raise ValueError("A gene label column is required for enrichment analysis.")

    split_groups = payload.kind == "phosprot" or gene_column == "Gene_group"
    genes = _genes_from_values(
        selected_df[gene_column].tolist(),
        split_groups=split_groups,
    )
    tested_genes = _genes_from_values(
        anova_df[gene_column].tolist(),
        split_groups=split_groups,
    )
    return source_used, genes, tested_genes, warnings


def _validate_enrichment_kind(kind: AnnotationKind) -> None:
    if kind == "phospho":
        raise ValueError(
            "ORA only supports Protein and Phosphoproteome levels. "
            "Phospho (site-level) is not supported."
        )


def _genes_from_values(values: list[object], *, split_groups: bool) -> list[str]:
    if split_groups:
        return sorted(
            {
                gene
                for value in values
                for gene in _gene_tokens(value)
                if gene
            }
        )
    return sorted(
        {
            gene
            for value in values
            if (gene := _clean_feature_name(value))
        }
    )


def _prepare_ora_universe(
    background_genes: list[str] | None,
    min_term_size: int,
    max_term_size: int,
) -> tuple[set[str], list[tuple[str, str, str, set[str]]]]:
    records: list[tuple[str, str, str, set[str]]] = []
    annotated_genes: set[str] = set()
    db = load_go_db()
    for ontology, term_id, description, genes_text in db[
        ["ontology", "term", "description", "genes"]
    ].itertuples(index=False, name=None):
        term_genes = {
            gene.strip()
            for gene in str(genes_text or "").split(";")
            if gene.strip()
        }
        annotated_genes.update(term_genes)
        records.append(
            (
                str(ontology or ""),
                str(term_id or ""),
                str(description or ""),
                term_genes,
            )
        )

    if background_genes is None:
        background = annotated_genes
    else:
        background = annotated_genes.intersection(
            {
                gene.strip()
                for gene in background_genes
                if gene and gene.strip()
            }
        )
    if not background:
        return set(), []

    eligible_terms: list[tuple[str, str, str, set[str]]] = []
    for ontology, term_id, description, term_genes in records:
        effective_term_genes = background.intersection(term_genes)
        if min_term_size <= len(effective_term_genes) <= max_term_size:
            eligible_terms.append(
                (ontology, term_id, description, effective_term_genes)
            )
    return background, eligible_terms


def _enrichment_terms(
    gene_list: list[str],
    top_n: int,
    adj_p_value_cutoff: float | None,
    background: set[str],
    eligible_terms: list[tuple[str, str, str, set[str]]],
    counts: dict[str, int] | None = None,
) -> list[EnrichmentTerm]:
    if counts is not None:
        counts.update(searchSpace=len(eligible_terms), overlapTested=0, passingCutoff=0, displayed=0)
    genes = {
        gene.strip()
        for gene in gene_list
        if gene and gene.strip()
    }
    query = genes.intersection(background)
    if not query or not eligible_terms:
        return []

    population_size = len(background)
    sample_size = len(query)
    # Only terms sharing at least one gene with the query are tested. A term with
    # no overlap has p = 1 by construction and is never reported, so counting it
    # in the BH denominator would penalise every reported term for a test that
    # never ran. clusterProfiler draws the line in the same place.
    tested = [
        (term, overlap)
        for term, overlap in (
            (term, sorted(query.intersection(term[3]))) for term in eligible_terms
        )
        if overlap
    ]
    if not tested:
        return []
    if counts is not None:
        counts["overlapTested"] = len(tested)

    term_sizes = np.asarray([len(term[3]) for term, _ in tested], dtype=int)
    overlap_sizes = np.asarray([len(overlap) for _, overlap in tested], dtype=int)
    pvalues = np.asarray(
        hypergeom.sf(
            overlap_sizes - 1,
            population_size,
            term_sizes,
            sample_size,
        ),
        dtype=float,
    )
    adj = _bh_adjust(pvalues)
    terms: list[EnrichmentTerm] = []
    for idx, ((ontology, term_id, description, term_genes), overlap) in enumerate(tested):
        p_value = float(pvalues[idx])
        adj_p_value = float(adj[idx])
        if adj_p_value_cutoff is not None and adj_p_value > float(adj_p_value_cutoff):
            continue
        terms.append(
            EnrichmentTerm(
                source=ontology,
                termId=term_id,
                name=description,
                termSize=len(term_genes),
                intersectionSize=len(overlap),
                querySize=sample_size,
                geneRatio=len(overlap) / max(1, sample_size),
                hitPercent=(len(overlap) / max(1, len(term_genes))) * 100.0,
                pValue=float(p_value),
                adjPValue=adj_p_value,
                intersectingGenes=overlap,
            )
        )

    terms.sort(key=lambda term: (term.adjPValue, term.pValue, -term.intersectionSize))
    if counts is not None:
        counts.update(passingCutoff=len(terms), displayed=len(terms[:top_n]))
    return terms[:top_n]


def _background_for_mode(mode: str, tested_genes: list[str]) -> list[str] | None:
    if mode == "global":
        return None
    if not tested_genes:
        raise ValueError("No tested genes are available for the experiment-specific ORA background.")
    return tested_genes


def run_enrichment(payload: EnrichmentRequest) -> EnrichmentResultResponse:
    _validate_enrichment_kind(payload.kind)
    if payload.minTermSize > payload.maxTermSize:
        raise ValueError("Minimum term size cannot be larger than maximum term size.")

    source_mode = str(payload.source).strip().lower()
    term_counts: dict[str, dict[str, int]] = {}
    if source_mode == "anova":
        source_used, cluster_genes, tested_genes, warnings = _anova_cluster_genes(payload)
        background = _background_for_mode(payload.backgroundMode, tested_genes)
        effective_background, eligible_terms = _prepare_ora_universe(
            background,
            payload.minTermSize,
            payload.maxTermSize,
        )
        cluster_terms = _enrichment_terms(
            cluster_genes,
            payload.topN,
            payload.adjPValueCutoff,
            effective_background,
            eligible_terms,
            term_counts.setdefault("cluster", {}),
        )
        species_warning = _species_overlap_warning(tested_genes)
        if species_warning:
            warnings = [*warnings, species_warning]
        return EnrichmentResultResponse(
            kind=payload.kind,
            sourceUsed=source_used,
            selectedCluster=payload.selectedCluster,
            clusterGenes=cluster_genes,
            clusterTerms=cluster_terms,
            backgroundMode=payload.backgroundMode,
            backgroundGenes=background or [],
            backgroundSize=len(background) if background is not None else len(effective_background),
            annotatedBackgroundSize=len(effective_background),
            organism=resolve_enrichment_organism(payload.organism),
            databaseSha256=_go_database_sha256(),
            testedTermCount=len(eligible_terms),
            termCounts=term_counts,
            upstreamCorrectionMethod=_correction_label(payload.useUncorrected),
            warnings=warnings,
        )

    use_control = source_mode == "volcano_control"
    if use_control:
        if not payload.condition1Control or not payload.condition2Control:
            raise ValueError("Volcano control source requires both control conditions.")
        unique_conditions = {
            str(payload.condition1).strip(),
            str(payload.condition2).strip(),
            str(payload.condition1Control).strip(),
            str(payload.condition2Control).strip(),
        }
        if len([value for value in unique_conditions if value]) < 4:
            raise ValueError("Volcano control source requires four different conditions.")

    source_used, up_genes, down_genes, tested_genes, warnings = _different_genes(payload)
    background = _background_for_mode(payload.backgroundMode, tested_genes)
    effective_background, eligible_terms = _prepare_ora_universe(
        background,
        payload.minTermSize,
        payload.maxTermSize,
    )
    up_terms = _enrichment_terms(
        up_genes,
        payload.topN,
        payload.adjPValueCutoff,
        effective_background,
        eligible_terms,
        term_counts.setdefault("up", {}),
    )
    down_terms = _enrichment_terms(
        down_genes,
        payload.topN,
        payload.adjPValueCutoff,
        effective_background,
        eligible_terms,
        term_counts.setdefault("down", {}),
    )
    species_warning = _species_overlap_warning(tested_genes)
    if species_warning:
        warnings = [*warnings, species_warning]
    return EnrichmentResultResponse(
        kind=payload.kind,
        sourceUsed=source_used,
        upGenes=up_genes,
        downGenes=down_genes,
        upTerms=up_terms,
        downTerms=down_terms,
        backgroundMode=payload.backgroundMode,
        backgroundGenes=background or [],
        backgroundSize=len(background) if background is not None else len(effective_background),
        annotatedBackgroundSize=len(effective_background),
        organism=resolve_enrichment_organism(payload.organism),
        upstreamCorrectionMethod=_correction_label(payload.useUncorrected),
        databaseSha256=_go_database_sha256(),
        testedTermCount=len(eligible_terms),
        termCounts=term_counts,
        warnings=warnings,
    )


def run_enrichment_from_list(payload: ListEnrichmentRequest) -> ListEnrichmentResultResponse:
    term_counts: dict[str, dict[str, int]] = {"query": {}}
    if payload.minTermSize > payload.maxTermSize:
        raise ValueError("Minimum term size cannot be larger than maximum term size.")

    cleaned_genes = sorted({_clean_feature_name(gene) for gene in payload.genes if _clean_feature_name(gene)})
    cleaned_background = sorted(
        {
            _clean_feature_name(gene)
            for gene in payload.backgroundGenes
            if _clean_feature_name(gene)
        }
    )
    if payload.backgroundMode == "experiment" and not cleaned_background:
        raise ValueError(
            "Provide the tested-gene background for experiment-specific ORA, "
            "or select all annotated genes (global)."
        )
    background = cleaned_background if payload.backgroundMode == "experiment" else None
    if background is not None:
        missing = sorted(set(cleaned_genes).difference(background))
        if missing:
            preview = ", ".join(missing[:10])
            suffix = "" if len(missing) <= 10 else f" and {len(missing) - 10} more"
            raise ValueError(
                "Every query gene must be included in the experiment background. "
                f"Missing: {preview}{suffix}."
            )
    effective_background, eligible_terms = _prepare_ora_universe(
        background,
        payload.minTermSize,
        payload.maxTermSize,
    )
    terms = _enrichment_terms(
        cleaned_genes,
        payload.topN,
        payload.adjPValueCutoff,
        effective_background,
        eligible_terms,
        term_counts["query"],
    )

    warnings: list[str] = []
    if not cleaned_genes:
        warnings.append("No valid genes were provided in the input list.")
    elif not terms:
        warnings.append("No enrichment terms found for the provided gene list and parameters.")
    species_warning = _species_overlap_warning(cleaned_background or cleaned_genes)
    if species_warning:
        warnings.append(species_warning)

    return ListEnrichmentResultResponse(
        genes=cleaned_genes,
        terms=terms,
        backgroundMode=payload.backgroundMode,
        backgroundGenes=background or [],
        backgroundSize=len(background) if background is not None else len(effective_background),
        annotatedBackgroundSize=len(effective_background),
        organism=resolve_enrichment_organism(payload.organism),
        databaseSha256=_go_database_sha256(),
        testedTermCount=len(eligible_terms),
        termCounts=term_counts,
        warnings=warnings,
    )


def _ora_direction_texts(
    payload: EnrichmentRequest,
    result: EnrichmentResultResponse,
    direction: OraDirection,
    advanced: dict | None,
) -> tuple[str, str]:
    """The heading over an ORA figure, and the word its error message uses.

    The heading names the condition the direction belongs to, and only that
    one. A volcano here is ``condition1 - condition2``, so a term in the up set
    is over-represented among the features higher in *condition 1*; stating the
    mirror image as well ("and lower in condition 2") is the same fact twice and
    is what makes a reader stop and work out which way round the figure is.
    The name follows the plot appearance panel, so a condition renamed there is
    renamed here too.
    """
    if payload.source == "anova":
        if direction != "cluster":
            raise ValueError("ANOVA ORA plots require the cluster direction.")
        cluster = result.selectedCluster
        return f"ANOVA Cluster {cluster}", f"ANOVA cluster {cluster}"
    if direction == "cluster":
        raise ValueError("Volcano ORA plots require the up or down direction.")
    word = "Upregulated" if direction == "up" else "Downregulated"
    name = advanced_label(str(payload.condition1), advanced, "conditionLabels").strip()
    return (f"{word} in {name}" if name else word), word.lower()


def _rc_font_points(plt, key: str, default: float) -> float:
    """A matplotlib font size in points, whatever form rcParams holds it in.

    ``ytick.labelsize`` is "medium" out of the box, which is a multiplier on
    ``font.size`` rather than a measurement, so it has to be resolved before it
    can be used to work out how much room a label needs.
    """
    from matplotlib.font_manager import font_scalings

    value = plt.rcParams.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        base = plt.rcParams.get("font.size", 10.0)
        try:
            base = float(base)
        except (TypeError, ValueError):
            base = default
        return base * float(font_scalings.get(str(value), 1.0))


# How a term's bubble is sized, in points squared. Area is proportional to the
# number of genes the term and the query share, which is how a reader compares
# two bubbles; the scale factor only decides how big the largest one is. It is
# capped at the historic 30 so a small result set looks as it always did, and
# falls below it once a term is large enough that the old scale would have
# drawn a disc over its neighbours.
_ORA_BUBBLE_SCALE_CAP = 30.0
_ORA_MAX_BUBBLE_AREA = 520.0
_ORA_MIN_BUBBLE_AREA = 45.0
# The width the bubble scale was chosen against, in centimetres.
_ORA_REFERENCE_WIDTH_CM = 20.0
# A point is 1/72 inch; a centimetre is 1/2.54 inch.
_POINTS_TO_CM = 2.54 / 72.0


def _ora_height_needed_cm(label_lines: int, rows: int, font_points: float) -> float:
    """The shortest canvas that still gives every term label its own room.

    ``fit_figure_to_labels`` grows a figure whose labels spill off the canvas,
    but tick labels that merely collide with each other stay inside it: ten
    three-line GO descriptions on a 6 inch axis overlap into an unreadable band
    without ever overflowing. That cannot be measured after the fact, so it is
    computed before the figure is made -- one line of room per line of label,
    plus a gap per term.
    """
    text_cm = label_lines * font_points * 1.35 * _POINTS_TO_CM
    gaps_cm = rows * 0.22
    # The axes are about three quarters of the canvas; the title, the x axis and
    # its label are the rest.
    return (text_cm + gaps_cm) / 0.75 + 3.0


def _ora_height_ceiling_cm(width_cm: float, dpi: int) -> float:
    """The tallest canvas this figure may grow to.

    The same physical and pixel ceilings the HTTP layer enforces, so a hundred
    terms cannot produce an image the browser refuses to decode.
    """
    resolved_dpi = float(max(72, int(dpi)))
    pixel_ceiling = (
        MAX_AUTO_FIT_PIXELS * 2.54 * 2.54 / (max(1.0, float(width_cm)) * resolved_dpi * resolved_dpi)
    )
    return max(6.0, min(MAX_AUTO_FIT_CM, pixel_ceiling))


# No tick label is drawn smaller than this, whatever it costs in room.
_ORA_MIN_TICK_POINTS = 4.0


def _ora_label_layout(
    names: list[str], *, width_cm: float, height_cm: float, dpi: int, tick_points: float
) -> tuple[list[str], float, float]:
    """Wrap the term names, then pick the canvas height and tick size that hold them.

    Three quantities decide each other here, so they are settled together: how
    many lines a name wraps to depends on the font, the height needed depends on
    the lines, and whether that height is available depends on the ceiling. The
    height grows first, because a taller figure costs the reader nothing. Only
    when the tallest allowed canvas still cannot hold the labels -- thirty terms
    at twenty points, say -- does the font give way, and it gives way by exactly
    as much as is missing. That is the last step before an error, and a figure
    whose labels are a point or two smaller than asked for is a better answer
    than no figure at all.

    Returns the wrapped labels, the height in centimetres, and the tick size in
    points the figure must actually be drawn at.
    """
    ceiling = _ora_height_ceiling_cm(width_cm, dpi)
    labels = [str(name) for name in names]
    target = max(6.0, float(height_cm))
    for _ in range(5):
        labels = [
            _wrap_to_width(str(name), width_cm=width_cm, font_points=tick_points, share=0.34)
            for name in names
        ]
        lines = sum(label.count("\n") + 1 for label in labels)
        needed = _ora_height_needed_cm(lines, len(labels), tick_points)
        target = max(float(height_cm), min(needed, ceiling))
        if needed <= target + 0.01 or tick_points <= _ORA_MIN_TICK_POINTS:
            break
        # Shrink by the shortfall, with a little extra so the next pass is not
        # left a hair short and forced round again.
        tick_points = max(_ORA_MIN_TICK_POINTS, tick_points * (target / needed) * 0.97)
    return labels, min(target, ceiling), tick_points


def ora_plot_png(
    payload: EnrichmentRequest,
    direction: OraDirection,
    advanced: dict | None = None,
    *,
    width_cm: float = 26.0,
    height_cm: float = 12.0,
    dpi: int = 300,
) -> bytes:
    plt = _get_plt()
    from matplotlib.colors import Normalize

    result = run_enrichment(payload)
    heading, missing_word = _ora_direction_texts(payload, result, direction, advanced)
    if payload.source == "anova":
        terms = result.clusterTerms
    else:
        terms = result.upTerms if direction == "up" else result.downTerms
    if not terms:
        raise ValueError(f"No {missing_word} enrichment terms found for the selected parameters.")

    frame = pd.DataFrame(
        {
            # BP, CC and MF terms share one plot and one BH correction, so each
            # label names its ontology.
            "name": [f"{term.name} ({term.source})" if term.source else term.name for term in terms],
            # GeneRatio (overlap / query size), the x axis every ORA dot plot
            # from clusterProfiler onwards uses; term coverage stays in the table.
            "geneRatio": [term.geneRatio for term in terms],
            "intersectionSize": [term.intersectionSize for term in terms],
            "score": [_safe_neg_log10(np.asarray([term.adjPValue]))[0] for term in terms],
        }
    )
    frame = frame.sort_values(by="score", ascending=False, kind="mergesort").reset_index(drop=True)
    y_positions = np.arange(len(frame))

    # The tick size the figure will actually be drawn at, because the labels are
    # wrapped and the canvas sized before `apply_advanced_axes` runs.
    tick_points = (
        advanced_number(advanced, "yTickLabelSize", 0.0)
        # rcParams gives "medium" as often as a number, and "medium" is a
        # relative size, not a measurement.
        or _rc_font_points(plt, "ytick.labelsize", 10.0)
    )
    title_points = advanced_element_number(advanced, "titleElement", "size") or 12.0

    # A GO description runs to 187 characters. Left on one line it either spills
    # off the canvas or forces a figure half a metre wide; broken to a share of
    # the width it stays beside the plot it belongs to.
    labels, height_cm, tick_points = _ora_label_layout(
        [str(name) for name in frame["name"]],
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        tick_points=tick_points,
    )

    counts = frame["intersectionSize"].astype(float).to_numpy()
    largest = float(np.nanmax(counts)) if counts.size else 1.0
    # A marker is measured in points, so the same bubble on a wider canvas reads
    # smaller. Scale with the canvas so a figure asked for at twice the width
    # keeps the proportions the default one had.
    canvas = max(0.5, float(width_cm) / _ORA_REFERENCE_WIDTH_CM) ** 2
    bubble_scale = canvas * min(
        _ORA_BUBBLE_SCALE_CAP, _ORA_MAX_BUBBLE_AREA / max(1.0, largest)
    )
    areas = np.clip(counts * bubble_scale, _ORA_MIN_BUBBLE_AREA * canvas, None)

    score_min, score_max = float(frame["score"].min()), float(frame["score"].max())
    if score_min == score_max:
        padding = max(0.1, score_max * 0.05)
        score_min, score_max = max(0.0, score_min - padding), score_max + padding
    score_norm = Normalize(vmin=score_min, vmax=score_max)
    fig, ax = plt.subplots(
        figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi))
    )
    scatter = ax.scatter(
        frame["geneRatio"],
        y_positions,
        s=areas,
        c=frame["score"],
        cmap=advanced_color_map(advanced, "YlOrRd"),
        norm=score_norm,
        edgecolors="#334155",
        linewidths=0.6,
        zorder=3,
    )
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    # Room at the edges: without it the first and last bubble are cut in half by
    # the frame, and the widest one touches the right spine.
    ax.set_ylim(len(frame) - 0.5, -0.5)
    ax.margins(x=0.14)
    ax.set_xlabel("GeneRatio (overlap / query genes)")
    background_label = (
        "tested-gene background"
        if result.backgroundMode == "experiment"
        else "global annotated background"
    )
    ax.set_title(
        _wrap_to_width(heading, width_cm=width_cm, font_points=title_points)
        + "\n"
        + _wrap_to_width(
            f"GO Enrichment (ORA), {background_label}",
            width_cm=width_cm,
            font_points=title_points,
        )
    )

    # No size key. Bubble area still carries the size of the overlap, but a key
    # for it was read as three more terms with missing labels: it sits on the
    # category axis, in line with the data, and nothing about a legend inside a
    # plot frame says "this row is not a result". The count is in the table, in
    # the `intersectionSize` column, where it can be read exactly rather than
    # estimated off a circle.

    # `ax=` rather than a second subplot with `cax=`: attaching a colour bar to
    # an axes of its own marks that axes as one `tight_layout` will not arrange,
    # and matplotlib then silently declines to lay out the whole figure -- which
    # leaves the fit to answer overhanging tick labels by widening the canvas,
    # pass after pass, until it runs out of passes.
    cbar = fig.colorbar(scatter, ax=ax, pad=0.02, shrink=0.82, aspect=30)
    cbar.set_label("-log10 adjusted p-value")
    apply_advanced_axes(ax, advanced)
    # After the panel, not before: the labels were wrapped to this size and the
    # canvas was sized for it, so the drawn size has to be the one that was
    # measured. It is never larger than the size that was asked for.
    ax.tick_params(axis="y", labelsize=tick_points)
    fig.tight_layout()
    # The requested size is a floor, not a ceiling. A GO term name is as long as
    # it is, and an error where a figure should be is the worst of the available
    # answers -- grow the canvas until the labels are inside it, then render.
    #
    # More passes than the default three: the colour bar sits at a fraction of
    # the width while its label sticks out by a fixed number of points, so the
    # last fraction of an inch of overhang comes off a little at a time. The
    # axes-pulling that closes this gap on other figures cannot help here,
    # because a colour bar is not a subplot and `subplots_adjust` leaves it
    # exactly where it was.
    _fit_figure_to_labels(fig, plt, dpi=dpi, max_passes=8)
    return _to_png_bytes(fig, plt, dpi=dpi)


def _aggregate_pathway_gene_values(
    frame: pd.DataFrame,
    *,
    gene_column: str,
    sample_columns: list[str],
    pathway_genes: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """Collapse mapped features to one row per pathway gene by sample median."""
    value_frame = (
        frame.loc[:, sample_columns]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )

    gene_positions: dict[str, list[int]] = {}
    for position, gene_value in enumerate(frame[gene_column].tolist()):
        # A repeated token within one annotation still represents one source
        # feature and must not increase its contribution count.
        row_tokens = {token.casefold() for token in _gene_tokens(gene_value)}
        for token in row_tokens:
            gene_positions.setdefault(token, []).append(position)

    ordered_genes: list[str] = []
    seen_genes: set[str] = set()
    for gene_value in pathway_genes:
        gene = str(gene_value).strip()
        gene_key = gene.casefold()
        if not gene or gene_key in seen_genes:
            continue
        seen_genes.add(gene_key)
        ordered_genes.append(gene)

    matrix_rows: list[pd.Series] = []
    source_counts: list[int] = []
    for gene in ordered_genes:
        positions = gene_positions.get(gene.casefold(), [])
        source_counts.append(len(positions))
        if not positions:
            matrix_rows.append(pd.Series(np.nan, index=sample_columns, dtype=float))
            continue
        matrix_rows.append(value_frame.iloc[positions].median(axis=0, skipna=True))

    heatmap_data = pd.DataFrame(matrix_rows, index=ordered_genes, columns=sample_columns)
    feature_counts = pd.Series(
        source_counts,
        index=ordered_genes,
        dtype="int64",
        name="source_feature_count",
    )
    return heatmap_data, feature_counts


def _wrap_to_width(
    text: str,
    *,
    width_cm: float,
    font_points: float = 12.0,
    share: float = 1.0,
    minimum: int = 12,
) -> str:
    """Break one line of text to the character budget a width in centimetres holds.

    Matplotlib wraps neither a title nor a tick label, and a Gene Ontology
    description is one long line -- the longest in the bundled table is 187
    characters, wider than any canvas these pages would sensibly be given.
    Enlarging the figure until it fits is the wrong answer to that; breaking the
    line is the right one.

    The character budget is deliberately crude: at roughly half the point size
    per character for a proportional face, a centimetre holds about
    ``28.35 / (0.5 * font_points)`` characters. It does not need to be exact,
    only to keep the line inside the canvas so that the fit check that follows
    has something it can satisfy. ``share`` is how much of the width the text is
    allowed -- a title may have all of it, a y tick label only the strip beside
    the plot.
    """
    import textwrap

    per_cm = 28.35 / max(1.0, 0.5 * font_points)
    budget = max(minimum, int(width_cm * max(0.05, share) * per_cm))
    if len(text) <= budget:
        return text
    return "\n".join(textwrap.wrap(text, budget, break_long_words=False, break_on_hyphens=False))


def _wrapped_title(text: str, *, width_cm: float, font_points: float = 12.0) -> str:
    """A title broken to the width of the figure it sits on."""
    return _wrap_to_width(text, width_cm=width_cm, font_points=font_points, minimum=20)


def pathway_heatmap_png(
    *,
    kind: AnnotationKind,
    pathway: str,
    conditions: list[str],
    value_type: HeatmapValueType,
    include_id: bool,
    header: bool,
    remove_empty: bool,
    cluster_rows: bool,
    cluster_cols: bool,
    width_cm: float,
    height_cm: float,
    dpi: int,
    data_source: str = "data",
    show_source_count: bool = False,
    advanced: dict | None = None,
) -> bytes:
    plt = _get_plt()
    _, frame, metadata, _ = _stats_source(kind, data_source=data_source)
    gene_column = _first_available_column(frame, _gene_label_candidates(kind))
    if gene_column is None:
        raise ValueError("A gene label column is required for pathway heatmaps.")

    db = load_go_db()
    pathway_row = db.loc[db["description"].astype(str).str.lower() == pathway.strip().lower()]
    if pathway_row.empty:
        raise ValueError(f"No pathway found matching '{pathway}'.")
    pathway_genes = [gene.strip() for gene in str(pathway_row.iloc[0]["genes"]).split(";") if gene.strip()]
    if not pathway_genes:
        raise ValueError("The selected pathway does not contain any genes.")

    meta_filtered = metadata.copy()
    if conditions:
        meta_filtered = meta_filtered[meta_filtered["condition"].isin(conditions)]
    if meta_filtered.empty:
        raise ValueError("No samples match the selected conditions.")

    sample_columns = meta_filtered["sample"].astype(str).tolist()
    heatmap_data, source_feature_counts = _aggregate_pathway_gene_values(
        frame,
        gene_column=gene_column,
        sample_columns=sample_columns,
        pathway_genes=pathway_genes,
    )
    total_genes = len(heatmap_data)
    if remove_empty:
        heatmap_data = heatmap_data.dropna(how="all")
        source_feature_counts = source_feature_counts.loc[heatmap_data.index]
    if heatmap_data.empty:
        raise ValueError("No matching pathway genes were found in the current dataset.")

    if value_type == "z":
        heatmap_data = pd.DataFrame(
            row_zscore(heatmap_data), index=heatmap_data.index, columns=heatmap_data.columns
        )
        color_label = "Z-score"
    else:
        color_label = intensity_unit_label(_phosprot_values_are_centred(kind))

    heatmap_data = heatmap_data.replace([np.inf, -np.inf], np.nan)
    if value_type == "z":
        heatmap_data = heatmap_data.dropna(how="all")
    if heatmap_data.empty:
        raise ValueError("No informative pathway rows remain after heatmap transformation.")

    if show_source_count:
        # How many dataset rows collapsed onto each gene. Off by default: on a
        # pathway of forty genes it is forty parentheticals down the side of the
        # figure, and for most of them the answer is 1.
        heatmap_data.index = [
            f"{gene} (n={int(source_feature_counts.loc[gene])})"
            for gene in heatmap_data.index
        ]

    meta_filtered = meta_filtered.reset_index(drop=True)
    # Keep pathway heatmap sample labels aligned with the app-wide convention:
    # condition + running number, with optional original sample id.
    meta_filtered["condition"] = meta_filtered["condition"].astype(str)
    meta_filtered["sample_index"] = meta_filtered.groupby("condition").cumcount() + 1
    if include_id:
        meta_filtered["display"] = meta_filtered.apply(
            lambda row: (
                f"{row['condition']}_{int(row['sample_index'])}\n"
                f"({_extract_id_or_number(row['sample'])})"
            ),
            axis=1,
        )
    else:
        meta_filtered["display"] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{int(row['sample_index'])}",
            axis=1,
        )
    label_map = dict(zip(meta_filtered["sample"].astype(str), meta_filtered["display"]))
    heatmap_data = heatmap_data.rename(columns=label_map)

    cluster_matrix = None
    if (cluster_rows and heatmap_data.shape[0] > 1) or (cluster_cols and heatmap_data.shape[1] > 1):
        cluster_matrix, pathway_completeness = drop_incomplete_features(
            heatmap_data, context="pathway heatmap"
        )
        heatmap_data = heatmap_data.loc[pathway_completeness.kept]
    if cluster_rows and heatmap_data.shape[0] > 1:
        row_order = leaves_list(linkage(pdist(cluster_matrix), method="average"))
        heatmap_data = heatmap_data.iloc[row_order]
        cluster_matrix = cluster_matrix[row_order]
    if cluster_cols and heatmap_data.shape[1] > 1:
        col_order = leaves_list(linkage(pdist(cluster_matrix.T), method="average"))
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi)))
    matrix = np.ma.masked_invalid(heatmap_data.to_numpy(dtype=float))
    fig._copylot_notice = heatmap_notice(total_genes, len(heatmap_data), noun="genes")
    # A z-score is a diverging quantity: draw it on the same diverging map and
    # symmetric limits as the ANOVA heatmaps, so equal colours mean equal z.
    image = ax.imshow(
        matrix,
        aspect="auto",
        cmap=advanced_color_map(advanced, "RdBu_r" if value_type == "z" else "plasma"),
        **({"vmin": -2.5, "vmax": 2.5} if value_type == "z" else {}),
    )
    ax.set_xticks(np.arange(heatmap_data.shape[1]))
    ax.set_xticklabels(
        [advanced_label(str(column), advanced, "conditionLabels") for column in heatmap_data.columns],
        rotation=90,
    )
    ax.set_yticks(np.arange(heatmap_data.shape[0]))
    ax.set_yticklabels(list(heatmap_data.index) if header else [""] * heatmap_data.shape[0])
    # A GO description runs to 187 characters at the long end, which is wider
    # than any canvas this page will ever be given. Growing the figure cannot
    # fix a title that is one unbreakable line, so it is wrapped to the width
    # the figure actually has before anything is measured.
    title_text = (
        f"{pathway} ({'Z-transformed' if value_type == 'z' else color_label}; "
        "median across mapped features)"
    )
    ax.set_title(_wrapped_title(title_text, width_cm=width_cm))
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label(color_label)
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    # Re-wrap to the axes the title sits over: the gene labels take the left
    # strip and the colour bar the right one, so a title as wide as the whole
    # figure overhung the labels to the left edge.
    axes_width_cm = float(ax.get_position().width) * float(fig.get_figwidth()) * 2.54
    ax.title.set_text(_wrapped_title(ax.get_title(), width_cm=axes_width_cm))
    fig.tight_layout()
    # The requested width/height is a floor, not a ceiling: a normal GO term has
    # more gene labels than the default 20 x 12 cm canvas can hold, and the page
    # would otherwise be unusable at its own defaults. Grow to fit, then render.
    _fit_figure_to_labels(fig, plt, dpi=dpi)
    return _to_png_bytes(fig, plt, dpi=dpi)


def _simulation_dataframe(
    payload: SimulationRequest,
) -> tuple[ResolvedSource, str, pd.DataFrame, list[str]]:
    source_used, frame, metadata, warnings = _stats_source(
        payload.kind,
        data_source=payload.dataSource,
    )
    label_column = _resolve_label_column(payload.kind, payload.identifier, frame)

    cols1 = metadata.loc[metadata["condition"] == payload.condition1, "sample"].astype(str).tolist()
    cols2 = metadata.loc[metadata["condition"] == payload.condition2, "sample"].astype(str).tolist()
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")

    selected_columns = [label_column, *cols1, *cols2]
    for extra in (
        "GeneNames",
        "Gene_group",
        "ProteinNames",
        "PTM_Collapse_key",
        "Phosphoprotein",
        "site_num",
        "PTM_Collapse_keys",
    ):
        if extra in frame.columns and extra not in selected_columns:
            selected_columns.append(extra)

    data_filtered = frame[
        [column for column in selected_columns if column in frame.columns]
    ].copy()
    arr_x = data_filtered[cols1].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    arr_y = data_filtered[cols2].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for the selected simulation.")

    data_filtered = data_filtered.loc[valid_mask].reset_index(drop=True)
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1_real = n1_real[valid_mask].astype(float)
    n2_real = n2_real[valid_mask].astype(float)
    # Same orientation as the volcano: first selected condition minus second.
    log2fc = np.nanmean(arr_x, axis=1) - np.nanmean(arr_y, axis=1)

    simulated_n1 = (
        n1_real
        if payload.sampleSizeOverride == 0
        else np.full(len(n1_real), float(payload.sampleSizeOverride))
    )
    simulated_n2 = (
        n2_real
        if payload.sampleSizeOverride == 0
        else np.full(len(n2_real), float(payload.sampleSizeOverride))
    )
    var1 = np.nanvar(arr_x, axis=1, ddof=1) * payload.varianceMultiplier
    var2 = np.nanvar(arr_y, axis=1, ddof=1) * payload.varianceMultiplier
    if payload.testType == "unpaired_welch":
        se, degrees_freedom = _satterthwaite(
            [(var1, simulated_n1), (var2, simulated_n2)]
        )
    else:
        se, degrees_freedom = pooled_se_df(var1, simulated_n1, var2, simulated_n2)

    pvals = two_sided_t_pvalues(log2fc, se, degrees_freedom)
    # Rows without variation in either group have a standard error of zero at
    # every projected n: the projection keeps the plain t-test arithmetic, but
    # follows the volcano's rule for these rows -- no p-value, out of the BH
    # family -- so that at the observed n it reproduces the volcano table.
    no_variation = without_variation([arr_x, arr_y])
    if no_variation.any():
        pvals = np.where(no_variation, np.nan, pvals)
        warnings = [*warnings, (
            f"{int(no_variation.sum()):,} rows have no variation in either compared group, so no "
            "p-value can be projected; they are shown as Unavailable, as in the volcano plot."
        )]
    selected_pvals = pvals if payload.useUncorrected else _bh_adjust(pvals)

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    significance[
        (selected_pvals < payload.pValueThreshold)
        & (log2fc > payload.log2fcThreshold)
    ] = "Upregulated"
    significance[
        (selected_pvals < payload.pValueThreshold)
        & (log2fc < -payload.log2fcThreshold)
    ] = "Downregulated"

    result = data_filtered.copy()
    result["log2FC"] = log2fc
    result["pval"] = pvals
    result["adj_pval"] = _bh_adjust(pvals)
    result["selected_pval"] = selected_pvals
    result["correction"] = _correction_label(payload.useUncorrected)
    result["test_type"] = payload.testType
    result["observed_n_condition1"] = n1_real.astype(int)
    result["observed_n_condition2"] = n2_real.astype(int)
    result["effective_n_condition1"] = simulated_n1.astype(int)
    result["effective_n_condition2"] = simulated_n2.astype(int)
    result["neg_log10_selected_pval"] = _safe_neg_log10(selected_pvals)
    result["significance"] = significance
    return source_used, label_column, result, warnings


def run_simulation(payload: SimulationRequest) -> SimulationResultResponse:
    source_used, label_column, frame, warnings = _simulation_dataframe(payload)
    effective_n1 = frame["effective_n_condition1"].astype(int)
    effective_n2 = frame["effective_n_condition2"].astype(int)
    return SimulationResultResponse(
        kind=payload.kind,
        sourceUsed=source_used,
        testType=payload.testType,
        condition1=payload.condition1,
        condition2=payload.condition2,
        sampleSizeMode="observed" if payload.sampleSizeOverride == 0 else "override",
        sampleSizeOverride=payload.sampleSizeOverride,
        effectiveSampleSizeCondition1Min=int(effective_n1.min()),
        effectiveSampleSizeCondition1Max=int(effective_n1.max()),
        effectiveSampleSizeCondition2Min=int(effective_n2.min()),
        effectiveSampleSizeCondition2Max=int(effective_n2.max()),
        labelColumn=label_column,
        totalRows=int(len(frame)),
        upregulatedCount=int((frame["significance"] == "Upregulated").sum()),
        downregulatedCount=int((frame["significance"] == "Downregulated").sum()),
        notSignificantCount=int((frame["significance"] == "Not significant").sum()),
        unavailableCount=int((frame["significance"] == "Unavailable").sum()),
        rows=frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records"),
        warnings=warnings,
    )


def simulation_html(payload: SimulationRequest, advanced: dict | None = None) -> str:
    _, label_column, frame, _ = _simulation_dataframe(payload)
    fig = _volcano_figure(
        frame,
        label_column=label_column,
        condition1=payload.condition1,
        condition2=payload.condition2,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        use_uncorrected=payload.useUncorrected,
        highlight_terms=[],
    )
    effective_n1 = frame["effective_n_condition1"].astype(int)
    effective_n2 = frame["effective_n_condition2"].astype(int)

    def _range_label(values: pd.Series) -> str:
        minimum = int(values.min())
        maximum = int(values.max())
        return str(minimum) if minimum == maximum else f"{minimum}-{maximum}"

    mode_label = "observed" if payload.sampleSizeOverride == 0 else "fixed override"
    effective_n_label = (
        f"Simulation effective n: {payload.condition1}={_range_label(effective_n1)}, "
        f"{payload.condition2}={_range_label(effective_n2)} ({mode_label})"
    )
    fig.add_annotation(
        text=effective_n_label,
        x=0.5,
        y=1.08,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 12},
    )
    fig.update_layout(margin={"l": 40, "r": 20, "t": 80, "b": 40})
    fig.update_layout(**advanced_plotly_layout(advanced))
    return _plotly_html(fig)


apply_cached_wrappers(
    globals(),
    [
        "statistical_options",
        "run_volcano",
        "run_volcano_control",
        "run_anova",
        "anova_png",
        "volcano_html",
        "volcano_control_html",
        "volcano_png",
        "volcano_control_png",
        "pathway_options",
        "run_enrichment",
        "run_enrichment_from_list",
        "ora_plot_png",
        "pathway_heatmap_png",
        "run_simulation",
        "simulation_html",
    ],
)
