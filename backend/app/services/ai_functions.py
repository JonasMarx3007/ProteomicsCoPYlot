from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from functools import wraps
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import ImputationRunRequest
from app.schemas.stats import VolcanoRequest
from app.services import functions as _functions
from app.services import table_functions as _table_functions
from app.services.comparison_tools import pearson_correlation_table, venn_table
from app.services.completeness_tools import completeness_tables
from app.services.data_tools import distribution_summary, run_imputation, verification_summary
from app.services.data_tools import _get_sample_columns
from app.services.peptide_tools import get_peptide_frame
from app.services.phospho_tools import (
    phospho_coverage_table,
    phospho_distribution_table,
    phospho_sty_table,
    phosphosite_plot_table,
)
from app.services.qc_tools import qc_summary
from app.services.single_protein_tools import (
    single_protein_boxplot_table,
    single_protein_heatmap_table,
    single_protein_lineplot_table,
)
from app.services.stats_tools import run_volcano, statistical_options

_MAX_DF_ROWS = 20_000
_MAX_SEQUENCE_ITEMS = 50_000
_MAX_NDARRAY_ITEMS = 50_000


def _replace_nan(value: Any) -> Any:
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, np.floating):
        item = float(value)
        return item if np.isfinite(item) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _numeric_column_stats(frame: pd.DataFrame, max_columns: int = 40) -> dict[str, dict[str, Any]]:
    numeric = frame.select_dtypes(include=[np.number])
    if numeric.empty:
        return {}
    stats: dict[str, dict[str, Any]] = {}
    for col in list(numeric.columns.astype(str))[:max_columns]:
        series = pd.to_numeric(numeric[col], errors="coerce")
        clean = series.replace([np.inf, -np.inf], np.nan).dropna()
        if clean.empty:
            stats[col] = {"count": 0, "min": None, "max": None, "mean": None, "median": None, "std": None}
            continue
        stats[col] = {
            "count": int(clean.size),
            "min": float(clean.min()),
            "max": float(clean.max()),
            "mean": float(clean.mean()),
            "median": float(clean.median()),
            "std": float(clean.std(ddof=1)) if clean.size > 1 else 0.0,
        }
    return stats


def _serialize_dataframe(frame: pd.DataFrame, *, max_rows: int = _MAX_DF_ROWS) -> dict[str, Any]:
    safe = frame.copy()
    row_count = int(len(safe))
    truncated = row_count > max_rows
    preview = safe.head(max_rows).where(pd.notna(safe.head(max_rows)), None).to_dict(orient="records")
    return {
        "type": "table",
        "rows": row_count,
        "columns": [str(col) for col in safe.columns.tolist()],
        "records": [{k: _replace_nan(v) for k, v in row.items()} for row in preview],
        "truncated": truncated,
        "numericSummary": _numeric_column_stats(safe),
    }


def _serialize_ndarray(array: np.ndarray) -> dict[str, Any]:
    arr = np.asarray(array)
    flat = arr.reshape(-1)
    finite = flat[np.isfinite(flat)] if np.issubdtype(arr.dtype, np.number) else np.array([])
    if flat.size <= _MAX_NDARRAY_ITEMS:
        values = [_replace_nan(item.item() if hasattr(item, "item") else item) for item in flat]
    else:
        values = [_replace_nan(item.item() if hasattr(item, "item") else item) for item in flat[:_MAX_NDARRAY_ITEMS]]
    payload: dict[str, Any] = {
        "type": "ndarray",
        "shape": [int(v) for v in arr.shape],
        "dtype": str(arr.dtype),
        "values": values,
        "truncated": int(flat.size) > _MAX_NDARRAY_ITEMS,
    }
    if finite.size > 0:
        payload["stats"] = {
            "count": int(finite.size),
            "min": float(np.min(finite)),
            "max": float(np.max(finite)),
            "mean": float(np.mean(finite)),
            "median": float(np.median(finite)),
            "std": float(np.std(finite)),
        }
    return payload


def _serialize_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _serialize_value(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _serialize_value(asdict(value))
    if isinstance(value, pd.DataFrame):
        return _serialize_dataframe(value)
    if isinstance(value, pd.Series):
        return _serialize_dataframe(value.to_frame(name=value.name or "value"))
    if isinstance(value, np.ndarray):
        return _serialize_ndarray(value)
    if isinstance(value, (bytes, bytearray)):
        return {
            "type": "binary",
            "byteLength": int(len(value)),
            "description": "Binary visual output suppressed in ai_functions.",
        }
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        truncated = len(seq) > _MAX_SEQUENCE_ITEMS
        seq = seq[:_MAX_SEQUENCE_ITEMS]
        payload = [_serialize_value(item) for item in seq]
        if truncated:
            return {
                "type": "sequence",
                "length": len(value),
                "items": payload,
                "truncated": True,
            }
        return payload
    return _replace_nan(value)


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if not np.isfinite(number):
        return None
    return number


def _build_payload(function_name: str, payload: Any, summary: str | None = None) -> dict[str, Any]:
    return {
        "function": function_name,
        "format": "ai_text",
        "summary": summary or f"Structured output for {function_name}.",
        "data": _serialize_value(payload),
    }


def stats_volcano_targets(
    kind: AnnotationKind = "protein",
    data_source: str = "imputed",
    condition1: str = "",
    condition2: str = "",
    identifier: str = "workflow",
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    top_n: int = 15,
) -> dict[str, Any]:
    options = statistical_options(kind)
    conditions = [str(item).strip() for item in options.availableConditions if str(item).strip()]
    selected_condition1 = str(condition1).strip() or (conditions[0] if len(conditions) > 0 else "")
    selected_condition2 = str(condition2).strip()
    if not selected_condition2:
        selected_condition2 = next(
            (item for item in conditions if item != selected_condition1),
            (conditions[1] if len(conditions) > 1 else selected_condition1),
        )
    if not selected_condition1 or not selected_condition2 or selected_condition1 == selected_condition2:
        raise ValueError("At least two distinct conditions are required for volcano target summarization.")

    identifier_key = str(identifier).strip().lower()
    if identifier_key not in {"workflow", "genes"}:
        identifier_key = "workflow"
    available_ids = {str(item.key).strip().lower() for item in options.availableIdentifiers}
    if identifier_key not in available_ids:
        identifier_key = "workflow" if "workflow" in available_ids else (next(iter(available_ids), "workflow"))

    source_key = str(data_source).strip().lower()
    if source_key not in {"data", "imputed"}:
        source_key = "imputed"
    if source_key == "imputed" and not bool(options.imputedAvailable):
        source_key = "data"

    volcano = run_volcano(
        VolcanoRequest(
            kind=kind,
            dataSource=source_key,  # type: ignore[arg-type]
            condition1=selected_condition1,
            condition2=selected_condition2,
            identifier=identifier_key,  # type: ignore[arg-type]
            pValueThreshold=float(p_value_threshold),
            log2fcThreshold=float(log2fc_threshold),
            testType="paired" if str(test_type).strip().lower() == "paired" else "unpaired",
            useUncorrected=bool(use_uncorrected),
        )
    )
    frame = pd.DataFrame(volcano.rows)
    label_column = str(volcano.labelColumn or "label")
    if frame.empty:
        payload = {
            "kind": kind,
            "comparison": {"condition1": selected_condition1, "condition2": selected_condition2},
            "identifier": identifier_key,
            "sourceUsed": volcano.sourceUsed,
            "thresholds": {
                "pValueThreshold": float(p_value_threshold),
                "log2fcThreshold": float(log2fc_threshold),
                "testType": "paired" if str(test_type).strip().lower() == "paired" else "unpaired",
                "useUncorrected": bool(use_uncorrected),
            },
            "counts": {
                "totalRows": int(volcano.totalRows),
                "upregulatedCount": int(volcano.upregulatedCount),
                "downregulatedCount": int(volcano.downregulatedCount),
                "notSignificantCount": int(volcano.notSignificantCount),
            },
            "topTargets": {"combinedTop": [], "upregulatedTop": [], "downregulatedTop": [], "mostSignificantTop": []},
            "highlight": {
                "strongestUpregulated": None,
                "strongestDownregulated": None,
                "mostSignificant": None,
                "bestCombinedCandidate": None,
            },
            "warnings": volcano.warnings,
        }
        return _build_payload("stats_volcano_targets", payload, "Volcano summary available but result rows are empty.")

    def _extract_target_rows(subset: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for _, row in subset.head(limit).iterrows():
            label_value = str(row.get(label_column, "")).strip()
            gene_value = str(row.get("GeneNames", "")).strip()
            significance = str(row.get("significance", "")).strip()
            log2fc_value = _to_float(row.get("log2FC"))
            neg_log_value = _to_float(row.get("neg_log10_adj_pval"))
            adj_p_value = _to_float(row.get("adj_pval"))
            p_value = _to_float(row.get("pval"))
            records.append(
                {
                    "label": label_value or None,
                    "gene": gene_value or None,
                    "significance": significance or None,
                    "log2FC": log2fc_value,
                    "negLog10AdjP": neg_log_value,
                    "adjPValue": adj_p_value,
                    "pValue": p_value,
                }
            )
        return records

    frame = frame.copy()
    frame["log2FC_num"] = pd.to_numeric(frame.get("log2FC"), errors="coerce")
    frame["negLog_num"] = pd.to_numeric(frame.get("neg_log10_adj_pval"), errors="coerce")
    frame["absLog2FC_num"] = frame["log2FC_num"].abs()
    frame["targetScore"] = frame["absLog2FC_num"] * frame["negLog_num"]
    frame = frame.replace([np.inf, -np.inf], np.nan)

    significant = frame[frame["significance"].astype(str) != "Not significant"].copy()
    significant = significant.dropna(subset=["log2FC_num", "negLog_num"])
    upregulated = significant[significant["log2FC_num"] > 0].copy()
    downregulated = significant[significant["log2FC_num"] < 0].copy()

    top_limit = max(1, min(int(top_n), 50))
    combined_top = significant.sort_values(["targetScore", "absLog2FC_num", "negLog_num"], ascending=[False, False, False])
    up_top = upregulated.sort_values(["log2FC_num", "negLog_num"], ascending=[False, False])
    down_top = downregulated.sort_values(["log2FC_num", "negLog_num"], ascending=[True, False])
    sig_top = significant.sort_values(["negLog_num", "absLog2FC_num"], ascending=[False, False])

    combined_targets = _extract_target_rows(combined_top, top_limit)
    up_targets = _extract_target_rows(up_top, top_limit)
    down_targets = _extract_target_rows(down_top, top_limit)
    sig_targets = _extract_target_rows(sig_top, top_limit)

    strongest_up = up_targets[0] if up_targets else None
    strongest_down = down_targets[0] if down_targets else None
    most_significant = sig_targets[0] if sig_targets else None
    best_combined = combined_targets[0] if combined_targets else None

    payload = {
        "kind": kind,
        "comparison": {"condition1": selected_condition1, "condition2": selected_condition2},
        "identifier": identifier_key,
        "labelColumn": label_column,
        "sourceUsed": volcano.sourceUsed,
        "thresholds": {
            "pValueThreshold": float(p_value_threshold),
            "log2fcThreshold": float(log2fc_threshold),
            "testType": "paired" if str(test_type).strip().lower() == "paired" else "unpaired",
            "useUncorrected": bool(use_uncorrected),
        },
        "counts": {
            "totalRows": int(volcano.totalRows),
            "upregulatedCount": int(volcano.upregulatedCount),
            "downregulatedCount": int(volcano.downregulatedCount),
            "notSignificantCount": int(volcano.notSignificantCount),
        },
        "topTargets": {
            "combinedTop": combined_targets,
            "upregulatedTop": up_targets,
            "downregulatedTop": down_targets,
            "mostSignificantTop": sig_targets,
        },
        "highlight": {
            "strongestUpregulated": strongest_up,
            "strongestDownregulated": strongest_down,
            "mostSignificant": most_significant,
            "bestCombinedCandidate": best_combined,
        },
        "warnings": volcano.warnings,
    }
    summary_parts = [
        f"Volcano target summary for {selected_condition1} vs {selected_condition2}: "
        f"{volcano.upregulatedCount} upregulated, {volcano.downregulatedCount} downregulated "
        f"(thresholds p<={p_value_threshold}, |log2FC|>={log2fc_threshold})."
    ]
    if best_combined is not None:
        label = str(best_combined.get("label") or best_combined.get("gene") or "unknown")
        direction = str(best_combined.get("significance") or "significant")
        summary_parts.append(
            "Best combined candidate: "
            f"{label} ({direction}, log2FC={best_combined.get('log2FC')}, "
            f"-log10 adj p={best_combined.get('negLog10AdjP')})."
        )
    if strongest_up is not None:
        label = str(strongest_up.get("label") or strongest_up.get("gene") or "unknown")
        summary_parts.append(
            f"Strongest upregulated: {label} (log2FC={strongest_up.get('log2FC')}, "
            f"-log10 adj p={strongest_up.get('negLog10AdjP')})."
        )
    if strongest_down is not None:
        label = str(strongest_down.get("label") or strongest_down.get("gene") or "unknown")
        summary_parts.append(
            f"Strongest downregulated: {label} (log2FC={strongest_down.get('log2FC')}, "
            f"-log10 adj p={strongest_down.get('negLog10AdjP')})."
        )
    summary = " ".join(summary_parts)
    return _build_payload("stats_volcano_targets", payload, summary)


def _bind_arguments(source_func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    bound = inspect.signature(source_func).bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def _missing_profile_from_matrix(matrix: pd.DataFrame, bin_count: int = 0) -> dict[str, Any]:
    if matrix.empty or matrix.shape[1] == 0:
        return {"sampleCount": 0, "featureCount": 0, "profile": [], "allMissingFeatures": 0}
    sample_count = int(matrix.shape[1])
    na_count = matrix.isna().sum(axis=1)
    transformed = (
        na_count.apply(lambda x: f">{bin_count}" if x > bin_count else str(int(x)))
        if int(bin_count) > 0
        else na_count.astype(int).astype(str)
    )
    if int(bin_count) > 0:
        levels = [str(i) for i in range(int(bin_count) + 1)] + [f">{int(bin_count)}"]
    else:
        levels = [str(i) for i in range(int(na_count.max()) + 1)]
    freq = transformed.value_counts().reindex(levels, fill_value=0)
    # Keep behavior aligned with plot code: drop the explicit "all missing" bucket when that label exists.
    all_missing_key = str(sample_count)
    if all_missing_key in freq.index:
        freq = freq.drop(index=all_missing_key)
    return {
        "sampleCount": sample_count,
        "featureCount": int(matrix.shape[0]),
        "allMissingFeatures": int((na_count == sample_count).sum()),
        "profile": [
            {"missingValues": str(level), "frequency": int(count)}
            for level, count in freq.items()
            if int(count) > 0
        ],
    }


def _imputation_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    payload = ImputationRunRequest(
        kind=bound["kind"],
        qValue=float(bound["q_value"]),
        adjustStd=float(bound["adjust_std"]),
        seed=int(bound["seed"]),
        sampleWise=bool(bound["sample_wise"]),
    )
    result = run_imputation(payload).model_dump(mode="json")
    summary = (
        f"Imputation diagnostics for {payload.kind}: "
        f"missing {result['missingBefore']} -> {result['missingAfter']}."
    )
    return result, summary


def _distribution_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    result = distribution_summary(bound["kind"]).model_dump(mode="json")
    summary = (
        f"Distribution summary for {bound['kind']} using {result['sourceUsed']} data with "
        f"{len(result['sampleColumns'])} sample columns."
    )
    return result, summary


def _verification_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    result = verification_summary(bound["kind"]).model_dump(mode="json")
    summary = f"Verification summary for {bound['kind']} with {result['numericValueCount']} numeric values."
    return result, summary


def _completeness_missing_plot_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import completeness_tools as _completeness_tools

    bound = _bind_arguments(source_func, args, kwargs)
    frame, meta = _completeness_tools._frame_and_meta(bound["kind"])
    matrix, _ = _completeness_tools._filtered_data(frame, meta, include_id=False)
    profile = _missing_profile_from_matrix(matrix, int(bound["bin_count"]))
    payload = {
        "kind": bound["kind"],
        "level": _completeness_tools._feature_label(frame),
        "missingValueDistribution": profile,
    }
    summary = (
        f"Missing-value distribution at {payload['level']} level across "
        f"{profile['sampleCount']} samples."
    )
    return payload, summary


def _completeness_missing_plot_peptide_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import completeness_tools as _completeness_tools

    bound = _bind_arguments(source_func, args, kwargs)
    frame = get_peptide_frame()
    file_col = _completeness_tools._peptide_file_column(frame)
    seq_col = _completeness_tools._peptide_sequence_column(frame)
    quantity_col = _completeness_tools._peptide_quantity_column(frame)
    pivot = frame.pivot_table(index=seq_col, columns=file_col, values=quantity_col, aggfunc="max")
    sample_cols = [value for value in _completeness_tools._peptide_sample_columns(frame) if value in pivot.columns]
    if not sample_cols:
        sample_cols = list(pivot.columns.astype(str))
    matrix = pivot[sample_cols].copy() if sample_cols else pd.DataFrame()
    profile = _missing_profile_from_matrix(matrix, int(bound["bin_count"]))
    payload = {
        "level": "Peptide",
        "missingValueDistribution": profile,
        "sampleColumns": [str(value) for value in sample_cols],
    }
    summary = f"Peptide missing-value distribution across {profile['sampleCount']} samples."
    return payload, summary


def _completeness_missing_plot_precursor_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import completeness_tools as _completeness_tools

    bound = _bind_arguments(source_func, args, kwargs)
    frame = get_peptide_frame()
    file_col = _completeness_tools._peptide_file_column(frame)
    precursor_col = _completeness_tools._peptide_precursor_column(frame)
    quantity_col = _completeness_tools._peptide_quantity_column(frame)
    pivot = frame.pivot_table(index=precursor_col, columns=file_col, values=quantity_col, aggfunc="max")
    sample_cols = [value for value in _completeness_tools._peptide_sample_columns(frame) if value in pivot.columns]
    if not sample_cols:
        sample_cols = list(pivot.columns.astype(str))
    matrix = pivot[sample_cols].copy() if sample_cols else pd.DataFrame()
    profile = _missing_profile_from_matrix(matrix, int(bound["bin_count"]))
    payload = {
        "level": "Precursor",
        "missingValueDistribution": profile,
        "sampleColumns": [str(value) for value in sample_cols],
    }
    summary = f"Precursor missing-value distribution across {profile['sampleCount']} samples."
    return payload, summary


def _completeness_heatmap_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import completeness_tools as _completeness_tools

    bound = _bind_arguments(source_func, args, kwargs)
    frame, meta = _completeness_tools._frame_and_meta(bound["kind"])
    matrix, renamed_meta = _completeness_tools._filtered_data(
        frame,
        meta,
        include_id=bool(bound["include_id"]),
    )
    tables = completeness_tables(
        bound["kind"],
        outlier_threshold=50.0,
        include_id=bool(bound["include_id"]),
    ).model_dump(mode="json")
    payload = {
        "kind": bound["kind"],
        "heatmapMatrix": _serialize_dataframe(matrix),
        "sampleMetadata": _serialize_dataframe(renamed_meta[["sample", "condition", "new_sample"]]),
        "completenessTables": tables,
    }
    summary = (
        f"Completeness heatmap matrix for {bound['kind']} with "
        f"{matrix.shape[0]} features x {matrix.shape[1]} samples."
    )
    return payload, summary


def _qc_coverage_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    per_sample = _table_functions.qc_coverage_table(bound["kind"], summary=False).copy()
    per_condition = _table_functions.qc_coverage_table(bound["kind"], summary=True).copy()

    def _extract_condition(sample_name: str) -> str | None:
        text = str(sample_name or "").strip()
        if not text:
            return None
        if text.lower().startswith("all sample"):
            return None
        if "_" in text:
            return text.split("_", 1)[0].strip() or None
        return None

    sample_table = per_sample.copy()
    sample_table["Sample"] = sample_table.get("Sample", "").astype(str)
    sample_table["DetectedFeatures"] = pd.to_numeric(sample_table.get("Number"), errors="coerce")
    total_features: int | None = None
    all_mask = sample_table["Sample"].str.lower().str.startswith("all sample")
    if all_mask.any():
        total_val = sample_table.loc[all_mask, "DetectedFeatures"].dropna()
        if not total_val.empty:
            total_features = int(total_val.iloc[0])
    sample_table = sample_table.loc[~all_mask].copy()
    sample_table["Condition"] = sample_table["Sample"].map(_extract_condition)
    sample_table = sample_table.dropna(subset=["DetectedFeatures"])
    sample_table = sample_table[sample_table["Condition"].notna()].copy()

    condition_stats: list[dict[str, Any]] = []
    if not sample_table.empty:
        for condition, subset in sample_table.groupby("Condition", sort=True):
            values = pd.to_numeric(subset["DetectedFeatures"], errors="coerce").dropna()
            if values.empty:
                continue
            condition_stats.append(
                {
                    "condition": str(condition),
                    "sampleCount": int(values.size),
                    "minDetectedFeatures": int(values.min()),
                    "maxDetectedFeatures": int(values.max()),
                    "medianDetectedFeatures": float(values.median()),
                    "meanDetectedFeatures": float(values.mean()),
                    "stdDetectedFeatures": float(values.std(ddof=1)) if int(values.size) > 1 else 0.0,
                }
            )

    comparisons: list[dict[str, Any]] = []
    for i in range(len(condition_stats)):
        left = condition_stats[i]
        for j in range(i + 1, len(condition_stats)):
            right = condition_stats[j]
            left_median = float(left["medianDetectedFeatures"])
            right_median = float(right["medianDetectedFeatures"])
            if left_median > right_median:
                higher = str(left["condition"])
                lower = str(right["condition"])
                diff = left_median - right_median
            elif right_median > left_median:
                higher = str(right["condition"])
                lower = str(left["condition"])
                diff = right_median - left_median
            else:
                higher = "equal"
                lower = "equal"
                diff = 0.0
            comparisons.append(
                {
                    "conditionA": str(left["condition"]),
                    "conditionB": str(right["condition"]),
                    "medianA": left_median,
                    "medianB": right_median,
                    "higherMedianCondition": higher,
                    "lowerMedianCondition": lower,
                    "medianDifference": diff,
                    "interpretation": (
                        "Higher detected-feature values indicate better data completeness."
                    ),
                }
            )

    condition_snippets = [
        (
            f"{item['condition']}[min={item['minDetectedFeatures']},max={item['maxDetectedFeatures']},"
            f"median={item['medianDetectedFeatures']:.2f}]"
        )
        for item in condition_stats[:8]
    ]
    best_pair_text = ""
    if comparisons:
        primary = sorted(comparisons, key=lambda row: float(row["medianDifference"]), reverse=True)[0]
        if str(primary["higherMedianCondition"]) != "equal":
            best_pair_text = (
                f" Median comparison: {primary['higherMedianCondition']} > {primary['lowerMedianCondition']} "
                f"(delta={float(primary['medianDifference']):.2f}); higher is better."
            )
        else:
            best_pair_text = " Median comparison: conditions are equal; higher would indicate better completeness."

    summary = (
        f"Coverage completeness for {bound['kind']}: detected features per sample are computed as "
        f"total features minus missing values (NA). "
        f"Total features={total_features if total_features is not None else 'unknown'}."
    )
    if condition_snippets:
        summary += f" Condition stats: {'; '.join(condition_snippets)}."
    summary += best_pair_text

    payload = {
        "kind": bound["kind"],
        "requestedMode": "summary" if bool(bound["summary"]) else "per_sample",
        "coverageDefinition": {
            "missingValuesPerSample": "Count NA values per sample column.",
            "totalFeatures": "Total number of dataframe rows (e.g., proteins/phosphosites).",
            "detectedFeaturesFormula": "Detected Features = Total Features - Missing Values per Sample.",
            "higherIsBetter": True,
            "higherIsBetterReason": "Higher detected-feature counts indicate better data completeness.",
        },
        "totalFeatures": total_features,
        "perSampleDetectedFeatures": sample_table[["Sample", "Condition", "DetectedFeatures"]],
        "perConditionSummaryTable": per_condition,
        "conditionStats": condition_stats,
        "conditionComparisons": comparisons,
    }
    return payload, summary


def _qc_peptide_coverage_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import plot_images as _plot_images
    from app.services.peptide_tools import _extract_id_or_number as _extract_peptide_id

    bound = _bind_arguments(source_func, args, kwargs)
    frame = get_peptide_frame()
    file_col = _plot_images._peptide_file_column(frame)
    seq_col = _plot_images._peptide_sequence_column(frame)
    quantity_col = _plot_images._peptide_quantity_column(frame)
    meta = _plot_images._peptide_coverage_metadata(frame, include_id=bool(bound["include_id"]))
    pivot = frame.pivot_table(index=seq_col, columns=file_col, values=quantity_col, aggfunc="max")
    if pivot.empty:
        return {"sampleCount": 0, "peptidesTotal": 0, "perSample": []}, "No peptide entries available."

    pivot = pivot.copy()
    pivot.columns = [_extract_peptide_id(column) for column in pivot.columns]
    labels = meta["label"].astype(str).tolist()
    rename_map = dict(zip(meta["id"].astype(str), labels))
    pivot = pivot.rename(columns=rename_map)
    selected = [label for label in labels if label in pivot.columns]
    if not selected:
        return {"sampleCount": 0, "peptidesTotal": int(pivot.shape[0]), "perSample": []}, "No peptide metadata/sample match."

    data_filtered = pivot[selected].copy()
    summary_df = data_filtered.notna().sum(axis=0).reset_index()
    summary_df.columns = ["Sample", "Value"]
    sample_to_condition = dict(zip(meta["label"].astype(str), meta["condition"].astype(str)))
    summary_df["Condition"] = summary_df["Sample"].astype(str).map(sample_to_condition).fillna("")
    payload = {
        "sampleCount": int(len(selected)),
        "peptidesTotal": int(pivot.shape[0]),
        "perSample": _serialize_dataframe(summary_df),
    }
    summary = f"Peptide coverage summary across {len(selected)} samples."
    return payload, summary


def _qc_histogram_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    summary_resp = qc_summary(bound["kind"]).model_dump(mode="json")
    payload = {
        "kind": bound["kind"],
        "sourceUsed": summary_resp["sourceUsed"],
        "sampleColumns": summary_resp["sampleColumns"],
        "intensityHistogram": summary_resp["intensityHistogram"],
        "warnings": summary_resp.get("warnings", []),
    }
    summary = f"Intensity histogram summary for {bound['kind']}."
    return payload, summary


def _qc_boxplot_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = _table_functions.qc_boxplot_table(bound["kind"], mode=str(bound["mode"]))
    summary = f"QC boxplot summary table for {bound['kind']} in mode '{bound['mode']}'."
    return table, summary


def _qc_cv_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = _table_functions.qc_cv_table(bound["kind"])
    summary = f"QC coefficient-of-variation summary table for {bound['kind']}."
    return table, summary


def _qc_pca_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import plot_images as _plot_images

    bound = _bind_arguments(source_func, args, kwargs)
    method = str(bound["method"])
    plot_dim = str(bound["plot_dim"])
    scores, explained, axis_prefix = _plot_images._pca_projection(
        bound["kind"],
        plot_dim=plot_dim,
        method=method,
        umap_n_neighbors=int(bound["umap_n_neighbors"]),
        umap_min_dist=float(bound["umap_min_dist"]),
        tsne_perplexity=float(bound["tsne_perplexity"]),
        tsne_learning_rate=float(bound["tsne_learning_rate"]),
        random_state=int(bound["random_state"]),
    )
    n_components = 3 if plot_dim.upper() == "3D" else 2
    component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]
    labels = _plot_images._compute_cluster_labels(
        scores[component_cols].to_numpy(dtype=float),
        cluster_method=str(bound["cluster_method"]),
        cluster_count=int(bound["cluster_count"]),
        dbscan_eps=float(bound["dbscan_eps"]),
        dbscan_min_samples=int(bound["dbscan_min_samples"]),
        random_state=int(bound["random_state"]),
    )
    if labels is not None:
        scores = scores.copy()
        scores["cluster"] = [_plot_images._cluster_display_label(value) for value in labels]
    color_by_key = str(bound["color_by"]).strip().lower()
    group_col = "cluster" if color_by_key == "cluster" and labels is not None else "condition"
    payload = {
        "kind": bound["kind"],
        "method": method,
        "plotDim": plot_dim,
        "axisPrefix": axis_prefix,
        "components": component_cols,
        "explainedVariancePercent": (
            [float(value) for value in np.asarray(explained).reshape(-1).tolist()]
            if explained is not None
            else None
        ),
        "groupBy": group_col,
        "groupCounts": {
            str(group): int(count)
            for group, count in scores[group_col].astype(str).value_counts().items()
        },
        "points": _serialize_dataframe(scores),
    }
    summary = f"{method} projection for {bound['kind']} ({plot_dim}) with {len(scores)} sample points."
    return payload, summary


def _qc_abundance_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import plot_images as _plot_images

    bound = _bind_arguments(source_func, args, kwargs)
    condition = str(bound["condition"])
    long_intensities, unique_conditions, workflow = _plot_images._abundance_rank_frame(bound["kind"])
    if condition != "All Conditions":
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        long_intensities = long_intensities[long_intensities["Condition"] == condition].copy()
    long_intensities = long_intensities.sort_values(["Condition", "Rank"], ascending=[True, True])
    top = (
        long_intensities.groupby("Condition", as_index=False, sort=False)
        .head(20)
        .reset_index(drop=True)
    )
    payload = {
        "kind": bound["kind"],
        "workflow": workflow,
        "condition": condition,
        "conditionsAvailable": unique_conditions,
        "pointCount": int(len(long_intensities)),
        "allPoints": _serialize_dataframe(long_intensities),
        "topRankedPerCondition": _serialize_dataframe(top),
    }
    summary = (
        f"Abundance rank summary for {workflow} ({bound['kind']}) "
        f"with {len(long_intensities)} ranked points."
    )
    return payload, summary


def _qc_correlation_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    from app.services import plot_images as _plot_images

    bound = _bind_arguments(source_func, args, kwargs)
    frame = _plot_images._verification_frame(bound["kind"])
    sample_columns = _get_sample_columns(bound["kind"], frame)
    if len(sample_columns) < 2:
        fallback_cols = (
            frame.apply(pd.to_numeric, errors="coerce")
            .dropna(axis=1, how="all")
            .columns.astype(str)
            .tolist()
        )
        sample_columns = [col for col in fallback_cols if col in frame.columns]
    if len(sample_columns) < 2:
        raise ValueError("At least two sample columns are required for correlation output.")

    meta = _plot_images._metadata_for_kind(bound["kind"], frame, sample_columns).copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].astype(str).apply(_plot_images._extract_id_or_number)
    meta["new_sample"] = meta.groupby("condition").cumcount() + 1
    if bool(bound["include_id"]):
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})",
            axis=1,
        )
    else:
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}",
            axis=1,
        )

    rename_map = dict(zip(meta["sample"], meta["new_sample"]))
    annotated_columns = meta["new_sample"].tolist()
    data_filtered = (
        frame[sample_columns]
        .rename(columns=rename_map)
        .reindex(columns=annotated_columns)
        .apply(pd.to_numeric, errors="coerce")
    )
    data_filtered = data_filtered.dropna(axis=1, how="all")
    if data_filtered.shape[1] < 2:
        raise ValueError("At least two non-empty sample columns are required for correlation output.")

    corr = data_filtered.corr(method="pearson").fillna(0.0)
    pairs: list[dict[str, Any]] = []
    cols = corr.columns.tolist()
    for i, left in enumerate(cols):
        for j in range(i + 1, len(cols)):
            right = cols[j]
            value = float(corr.loc[left, right])
            pairs.append(
                {
                    "left": str(left),
                    "right": str(right),
                    "pearsonR": value,
                    "absPearsonR": abs(value),
                }
            )
    strongest = sorted(pairs, key=lambda row: row["absPearsonR"], reverse=True)[:200]
    payload = {
        "kind": bound["kind"],
        "method": bound["method"],
        "fullRange": bool(bound["full_range"]),
        "samples": cols,
        "correlationMatrix": _serialize_dataframe(corr.reset_index().rename(columns={"index": "Sample"})),
        "strongestPairsTop200": strongest,
    }
    summary = f"Correlation summary for {bound['kind']} with {len(cols)} samples."
    return payload, summary


def _single_protein_boxplot_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = single_protein_boxplot_table(
        kind=bound["kind"],
        protein=str(bound["protein"]),
        conditions=list(bound["conditions"]),
        identifier=str(bound["identifier"]),
    )
    summary = f"Single-protein boxplot table for {bound['protein']} ({bound['kind']})."
    return table, summary


def _single_protein_lineplot_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = single_protein_lineplot_table(
        kind=bound["kind"],
        proteins=list(bound["proteins"]),
        conditions=list(bound["conditions"]),
        include_id=bool(bound["include_id"]),
        identifier=str(bound["identifier"]),
    )
    summary = f"Single-protein lineplot table for {len(bound['proteins'])} features ({bound['kind']})."
    return table, summary


def _single_protein_heatmap_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = single_protein_heatmap_table(
        kind=bound["kind"],
        protein=str(bound["protein"]),
        conditions=list(bound["conditions"]),
        identifier=str(bound["identifier"]),
        include_id=bool(bound["include_id"]),
        filter_m1=bool(bound["filter_m1"]),
        cluster_rows=bool(bound["cluster_rows"]),
        cluster_cols=bool(bound["cluster_cols"]),
        value_type=str(bound["value_type"]),
    )
    summary = f"Single-protein heatmap table for {bound['protein']} ({bound['kind']})."
    return table, summary


def _phosphosite_plot_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = phosphosite_plot_table(cutoff=float(bound["cutoff"]))
    summary = f"Phosphosite summary table using cutoff={bound['cutoff']}."
    return table, summary


def _phospho_coverage_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = phospho_coverage_table(
        include_id=bool(bound["include_id"]),
        conditions=list(bound["conditions"]) if bound["conditions"] is not None else None,
        mode=str(bound["mode"]),
    )
    summary = f"Phospho coverage table in mode '{bound['mode']}'."
    return table, summary


def _phospho_distribution_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = phospho_distribution_table(cutoff=float(bound["cutoff"]))
    summary = f"Phospho distribution table using cutoff={bound['cutoff']}."
    return table, summary


def _phospho_sty_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    table = phospho_sty_table()
    summary = "STY distribution table."
    return table, summary


def _comparison_pearson_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = pearson_correlation_table(
        kind=bound["kind"],
        mode=str(bound["mode"]),
        sample1=str(bound["sample1"]),
        sample2=str(bound["sample2"]),
        condition1=str(bound["condition1"]),
        condition2=str(bound["condition2"]),
        alias1=str(bound["alias1"]),
        alias2=str(bound["alias2"]),
    )
    summary = "Pearson correlation summary table."
    return table, summary


def _comparison_venn_text(*args: Any, source_func: Callable[..., Any], **kwargs: Any) -> tuple[Any, str]:
    bound = _bind_arguments(source_func, args, kwargs)
    table = venn_table(
        kind=bound["kind"],
        mode=str(bound["mode"]),
        first=str(bound["first"]),
        second=str(bound["second"]),
        third=str(bound["third"]),
        alias1=str(bound["alias1"]),
        alias2=str(bound["alias2"]),
        alias3=str(bound["alias3"]),
    )
    summary = "Venn-region count summary table."
    return table, summary


_SPECIAL_HANDLERS: dict[str, Callable[..., tuple[Any, str]]] = {
    "imputation_before_plot": _imputation_text,
    "imputation_overall_fit_plot": _imputation_text,
    "imputation_after_plot": _imputation_text,
    "distribution_qqnorm_plot": _distribution_text,
    "verification_first_digit_plot": _verification_text,
    "verification_duplicate_pattern_plot": _verification_text,
    "completeness_missing_value_plot": _completeness_missing_plot_text,
    "completeness_missing_value_plot_peptide": _completeness_missing_plot_peptide_text,
    "completeness_missing_value_plot_precursor": _completeness_missing_plot_precursor_text,
    "completeness_missing_value_heatmap": _completeness_heatmap_text,
    "qc_coverage_plot": _qc_coverage_text,
    "qc_peptide_coverage_plot": _qc_peptide_coverage_text,
    "qc_intensity_histogram_plot": _qc_histogram_text,
    "qc_boxplot_plot": _qc_boxplot_text,
    "qc_cv_plot": _qc_cv_text,
    "qc_pca_plot": _qc_pca_text,
    "qc_pca_interactive_html": _qc_pca_text,
    "qc_abundance_plot": _qc_abundance_text,
    "qc_abundance_interactive_html": _qc_abundance_text,
    "qc_correlation_plot": _qc_correlation_text,
    "single_protein_boxplot_plot": _single_protein_boxplot_text,
    "single_protein_lineplot_plot": _single_protein_lineplot_text,
    "single_protein_heatmap_plot": _single_protein_heatmap_text,
    "phosphosite_plot_png": _phosphosite_plot_text,
    "phospho_coverage_png": _phospho_coverage_text,
    "phospho_distribution_png": _phospho_distribution_text,
    "phospho_sty_png": _phospho_sty_text,
    "comparison_pearson_png": _comparison_pearson_text,
    "comparison_venn_png": _comparison_venn_text,
}


def _make_ai_wrapper(name: str, source_func: Callable[..., Any]) -> Callable[..., dict[str, Any]]:
    special_handler = _SPECIAL_HANDLERS.get(name)

    @wraps(source_func)
    def _wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if special_handler is not None:
            payload, summary = special_handler(*args, source_func=source_func, **kwargs)
            return _build_payload(name, payload, summary)
        result = source_func(*args, **kwargs)
        return _build_payload(name, result)

    _wrapper.__signature__ = inspect.signature(source_func)  # type: ignore[attr-defined]
    return _wrapper


def _collect_source_functions() -> dict[str, Callable[..., Any]]:
    out: dict[str, Callable[..., Any]] = {}
    for module in (_functions, _table_functions):
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if func.__module__ != module.__name__:
                continue
            if name.startswith("_"):
                continue
            out[name] = func
    return out


_SOURCE_FUNCTIONS = _collect_source_functions()

for _name, _func in _SOURCE_FUNCTIONS.items():
    globals()[_name] = _make_ai_wrapper(_name, _func)

__all__ = sorted(_SOURCE_FUNCTIONS.keys())
