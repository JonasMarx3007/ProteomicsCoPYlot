from __future__ import annotations

from typing import Any

import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import EnrichmentRequest
from app.services.annotation_store import get_annotation
from app.services.condition_palette_store import build_condition_color_map
from app.services.completeness_tools import completeness_tables as _completeness_tables
from app.services import plot_images as _plot_images
from app.services import stats_tools as _stats_tools
from app.services import single_protein_tools as _single_protein_tools
from app.services import comparison_tools as _comparison_tools
from app.services import phospho_tools as _phospho_tools
from app.services import table_functions as _table_functions
from app.services.peptide_tools import _extract_id_or_number as _extract_peptide_id
from app.services.peptide_tools import get_peptide_frame

_GENERAL_PROTEOMICS_CONTEXT_PREFIX = (
    "This application analyzes proteomics data. "
    "Treat this as mass-spectrometry proteomics analysis, not RNA-seq or transcriptomics. "
    "Focus on data analysis and statistical interpretation. "
    "Do not discuss instrumentation or acquisition settings unless the user explicitly asks for them. "
    "Do not mention plotting options, display toggles, or UI controls unless the user explicitly asks for those controls. "
    "Do not mention colors, palettes, or visual encoding details unless the user explicitly asks for color/visual mapping information. "
    "If color information is explicitly requested, prefer color names rather than hex values. "
    "Avoid unnecessary parenthetical examples like '(e.g., ...)'; use examples only when needed to disambiguate or when explicitly requested. "
    "Avoid ambiguous claims; be explicit and precise. "
    "Use code-backed calculations for requested math, and do not run extra mathematical operations unless the user explicitly asks for them. "
    "General quality-assessment rule: if no explicit thresholds or cutoffs are defined, do not make dataset quality assessments. "
    "In that case, give only general, non-data-specific guidance and state that strict cutoff-based interpretation is not available. "
    "Hard claim gate: only make data-specific findings when explicit numeric evidence and explicit cutoff/rule definitions are provided. "
    "If evidence or cutoffs/rules are missing, do not claim findings for the current dataset; provide checklist-style interpretation guidance only. "
)

_WORKFLOW_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phosphosite": ("phosphosite", "phosphosites"),
    "phosphoprotein": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
}

_HEX_COLOR_NAME_OVERRIDES: dict[str, str] = {
    "#1F77B4": "blue",
    "#FF7F0E": "orange",
    "#2CA02C": "green",
    "#D62728": "red",
    "#9467BD": "purple",
    "#8C564B": "brown",
    "#E377C2": "pink",
    "#7F7F7F": "gray",
    "#BCBD22": "olive",
    "#17BECF": "cyan",
    "#AEC7E8": "light blue",
    "#FFBB78": "light orange",
    "#98DF8A": "light green",
    "#FF9896": "light red",
    "#C5B0D5": "lavender",
    "#C49C94": "tan",
    "#F7B6D2": "light pink",
    "#C7C7C7": "light gray",
    "#DBDB8D": "pale olive",
    "#9EDAE5": "light cyan",
}

_COMPLETENESS_KIND_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phospho": ("phosphosite", "phosphosites"),
    "phosprot": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
    "precursor": ("precursor", "precursors"),
}


def _empty_payload(function_name: str) -> dict[str, Any]:
    return {
        "function": function_name,
        "format": "ai_text",
        "summary": "",
        "data": {"text": ""},
    }


def _text_payload(function_name: str, text: str) -> dict[str, Any]:
    return {
        "function": function_name,
        "format": "ai_text",
        "summary": text,
        "data": {"text": text},
    }


def _normalize_coverage_workflow(workflow: str) -> str:
    key = str(workflow or "").strip().lower()
    if key in {"peptide", "phosphosite", "phosphoprotein", "protein"}:
        return key
    if "peptide" in key:
        return "peptide"
    if "phosphosite" in key or key == "phospho":
        return "phosphosite"
    if "phosprot" in key or "phosphoprotein" in key:
        return "phosphoprotein"
    return "protein"


def _workflow_entity_labels(workflow: str) -> tuple[str, str]:
    return _WORKFLOW_ENTITY_LABELS.get(workflow, _WORKFLOW_ENTITY_LABELS["protein"])


def _workflow_kind(workflow: str) -> AnnotationKind:
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    return "protein"


def _normalize_boxplot_mode(mode: str) -> str:
    key = str(mode or "").strip().lower()
    if key == "single":
        return "Single"
    return "Mean"


def _extract_condition_from_sample(sample_name: str) -> str:
    text = str(sample_name or "").strip()
    if not text:
        return "sample"
    if "_" in text:
        head = text.split("_", 1)[0].strip()
        return head or text
    return text


def _fmt_value(value: float | int) -> str:
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.2f}"


def _color_name(color_value: str) -> str:
    value = str(color_value or "").strip().upper()
    if not value:
        return "unassigned"
    mapped = _HEX_COLOR_NAME_OVERRIDES.get(value)
    if mapped:
        return mapped
    if value.startswith("#"):
        return "custom color"
    return value.lower()


def _coverage_rows_from_wide(kind: AnnotationKind) -> tuple[pd.DataFrame, int | None]:
    table = _table_functions.qc_coverage_table(kind, summary=False).copy()
    if table.empty or "Sample" not in table.columns or "Number" not in table.columns:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), None

    frame = table.copy()
    frame["Sample"] = frame["Sample"].astype(str)
    frame["Count"] = pd.to_numeric(frame["Number"], errors="coerce")

    total_features: int | None = None
    all_mask = frame["Sample"].str.lower().str.startswith("all sample")
    if all_mask.any():
        total_values = frame.loc[all_mask, "Count"].dropna()
        if not total_values.empty:
            total_features = int(total_values.iloc[0])

    frame = frame.loc[~all_mask].copy()
    frame = frame.dropna(subset=["Count"])
    if frame.empty:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), total_features

    frame["Condition"] = frame["Sample"].map(_extract_condition_from_sample)
    return frame[["Sample", "Condition", "Count"]].reset_index(drop=True), total_features


def _coverage_rows_from_peptide() -> tuple[pd.DataFrame, int | None]:
    frame = get_peptide_frame()
    file_col = _plot_images._peptide_file_column(frame)
    seq_col = _plot_images._peptide_sequence_column(frame)
    quantity_col = _plot_images._peptide_quantity_column(frame)
    meta = _plot_images._peptide_coverage_metadata(frame, include_id=False)

    pivot = frame.pivot_table(index=seq_col, columns=file_col, values=quantity_col, aggfunc="max")
    if pivot.empty:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), 0

    pivot = pivot.copy()
    pivot.columns = [_extract_peptide_id(column) for column in pivot.columns]
    labels = meta["label"].astype(str).tolist()
    rename_map = dict(zip(meta["id"].astype(str), labels))
    pivot = pivot.rename(columns=rename_map)
    selected = [label for label in labels if label in pivot.columns]
    if not selected:
        selected = list(pivot.columns.astype(str))
    if not selected:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), int(pivot.shape[0])

    filtered = pivot[selected].copy()
    summary_df = filtered.notna().sum(axis=0).reset_index()
    summary_df.columns = ["Sample", "Count"]
    sample_to_condition = dict(zip(meta["label"].astype(str), meta["condition"].astype(str)))
    summary_df["Condition"] = summary_df["Sample"].astype(str).map(sample_to_condition).fillna(
        summary_df["Sample"].astype(str)
    )
    summary_df["Count"] = pd.to_numeric(summary_df["Count"], errors="coerce")
    summary_df = summary_df.dropna(subset=["Count"]).reset_index(drop=True)
    return summary_df[["Sample", "Condition", "Count"]], int(pivot.shape[0])


def _condition_palette_for_workflow(workflow: str, conditions: list[str]) -> dict[str, str]:
    kind = _workflow_kind(workflow)
    if workflow == "peptide":
        kind = "protein"
    try:
        ordered_conditions: list[str] = []
        seen: set[str] = set()
        for condition in conditions:
            name = str(condition or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            ordered_conditions.append(name)
        return build_condition_color_map(kind, ordered_conditions)
    except Exception:
        return {}


def _condition_order(rows: pd.DataFrame) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for value in rows["Condition"].astype(str).tolist():
        if value in seen:
            continue
        seen.add(value)
        order.append(value)
    return order


def _conditions_for_workflow(workflow: str) -> list[str]:
    kind = _workflow_kind(workflow)
    try:
        annotation = get_annotation(kind)
    except Exception:
        annotation = None

    if annotation is not None and not annotation.metadata.empty and "condition" in annotation.metadata.columns:
        values = annotation.metadata["condition"].astype(str).str.strip()
        values = values[values != ""]
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values.tolist():
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        if ordered:
            return ordered

    try:
        summary = _table_functions.qc_boxplot_table(kind, mode="Mean").copy()
    except Exception:
        summary = pd.DataFrame()
    if not summary.empty and "Condition" in summary.columns:
        return _condition_order(summary[["Condition"]].astype(str))
    return []


def _safe_context_text(value: Any) -> str:
    text = str(value or "").replace("|", "/").replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return "unknown"
    return text


def _primary_term_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    first = text.split(";", 1)[0].strip()
    return _safe_context_text(first or text)


def _preview_items(values: list[str], limit: int) -> tuple[list[str], bool]:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return [], False
    max_items = max(1, int(limit))
    trimmed = cleaned[:max_items]
    return trimmed, len(cleaned) > len(trimmed)


def _parse_mode_pairs(mode: str | None) -> dict[str, str]:
    text = str(mode or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    for part in text.split("|"):
        token = str(part or "").strip()
        if not token or "=" not in token:
            continue
        key, value = token.split("=", 1)
        key_norm = str(key or "").strip().lower()
        value_norm = str(value or "").strip()
        if not key_norm or not value_norm:
            continue
        parsed[key_norm] = value_norm
    return parsed


def _normalize_completeness_kind(workflow: str, mode: str | None = None) -> str:
    mode_pairs = _parse_mode_pairs(mode)
    requested = str(
        mode_pairs.get("kind")
        or mode_pairs.get("level")
        or mode_pairs.get("dataset")
        or ""
    ).strip().lower()
    if requested in _COMPLETENESS_KIND_LABELS:
        return requested
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    if workflow == "peptide":
        return "peptide"
    return "protein"


def _bool_from_mode(mode_pairs: dict[str, str], *keys: str, default: bool) -> bool:
    for key in keys:
        if key not in mode_pairs:
            continue
        value = str(mode_pairs.get(key, "")).strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return default


def _float_from_mode(
    mode_pairs: dict[str, str],
    *keys: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value_num = default
    for key in keys:
        if key not in mode_pairs:
            continue
        try:
            value_num = float(str(mode_pairs.get(key, "")).strip())
            break
        except Exception:
            continue
    if minimum is not None and value_num < minimum:
        value_num = minimum
    if maximum is not None and value_num > maximum:
        value_num = maximum
    return value_num


def _split_mode_list(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    items: list[str] = []
    for token in raw.replace(";", ",").split(","):
        normalized = str(token).strip()
        if normalized:
            items.append(normalized)
    return items


def _completeness_feature_rows(
    kind: str,
) -> tuple[float | None, int, list[tuple[int, int, float | None]], str | None]:
    if kind not in {"protein", "phospho", "phosprot"}:
        return None, 0, [], f"tables_not_available_for_level={kind}"
    try:
        payload = _completeness_tables(kind=kind, outlier_threshold=50.0, include_id=True)
    except Exception as exc:
        return None, 0, [], _safe_context_text(exc)

    overall_missing = float(payload.overallMissingPercent)
    sample_count = int(len(payload.sampleSummary))
    rows: list[tuple[int, int, float | None]] = []
    for item in payload.featureSummary:
        missing_value_raw = item.get("n_MissingProteinValues")
        count_raw = item.get("Counts")
        percent_raw = item.get("%_missing_values")
        try:
            missing_value = int(float(missing_value_raw))
            count_value = int(float(count_raw))
        except Exception:
            continue
        percent_value: float | None
        try:
            percent_value = float(percent_raw)
        except Exception:
            percent_value = None
        rows.append((missing_value, count_value, percent_value))
    rows.sort(key=lambda value: value[0])
    return overall_missing, sample_count, rows, None


def _completeness_tables_payload(
    kind: str,
    *,
    outlier_threshold: float,
    include_id: bool,
) -> tuple[float | None, int, list[dict[str, Any]], list[dict[str, Any]], list[str], str | None]:
    if kind not in {"protein", "phospho", "phosprot"}:
        return None, 0, [], [], [], f"tables_not_available_for_level={kind}"
    try:
        payload = _completeness_tables(
            kind=kind,
            outlier_threshold=float(outlier_threshold),
            include_id=bool(include_id),
        )
    except Exception as exc:
        return None, 0, [], [], [], _safe_context_text(exc)

    overall_missing = float(payload.overallMissingPercent)
    sample_rows = list(payload.sampleSummary)
    feature_rows = list(payload.featureSummary)
    outliers = [str(value) for value in payload.outliers]
    sample_count = len(sample_rows)
    return overall_missing, sample_count, sample_rows, feature_rows, outliers, None


def _normalize_stats_kind(workflow: str, mode: str | None = None) -> str:
    mode_pairs = _parse_mode_pairs(mode)
    requested = str(
        mode_pairs.get("kind")
        or mode_pairs.get("dataset")
        or mode_pairs.get("level")
        or ""
    ).strip().lower()
    if requested in {"protein", "phospho", "phosprot"}:
        return requested
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    return "protein"


def _entity_labels_from_stats_kind(kind: str) -> tuple[str, str]:
    if kind == "phospho":
        return _WORKFLOW_ENTITY_LABELS["phosphosite"]
    if kind == "phosprot":
        return _WORKFLOW_ENTITY_LABELS["phosphoprotein"]
    return _WORKFLOW_ENTITY_LABELS["protein"]


def _volcano_ranked_rows(
    frame: pd.DataFrame,
    *,
    label_column: str,
    group: str,
    limit: int,
    strategy: str = "balanced",
) -> tuple[pd.DataFrame, bool]:
    if frame.empty:
        return frame, False
    subset = frame.copy()
    subset[label_column] = subset[label_column].astype(str)
    subset["abs_log2FC"] = pd.to_numeric(subset["log2FC"], errors="coerce").fillna(0.0).astype(float).abs()
    subset["abs_neg_log10_adj_pval"] = (
        pd.to_numeric(subset["neg_log10_adj_pval"], errors="coerce").fillna(0.0).astype(float).abs()
    )
    if strategy == "fold_change_priority":
        subset["rank_score"] = subset["abs_log2FC"]
    else:
        subset["rank_score"] = subset["abs_log2FC"] * subset["abs_neg_log10_adj_pval"]

    if group == "up":
        subset = subset[subset["log2FC"] > 0].copy()
        if strategy == "fold_change_priority":
            subset = subset.sort_values(
                ["abs_log2FC", "log2FC", "abs_neg_log10_adj_pval", "adj_pval"],
                ascending=[False, False, False, True],
            )
        else:
            subset = subset.sort_values(
                ["rank_score", "abs_neg_log10_adj_pval", "log2FC"],
                ascending=[False, False, False],
            )
    else:
        subset = subset[subset["log2FC"] < 0].copy()
        if strategy == "fold_change_priority":
            subset = subset.sort_values(
                ["abs_log2FC", "log2FC", "abs_neg_log10_adj_pval", "adj_pval"],
                ascending=[False, True, False, True],
            )
        else:
            subset = subset.sort_values(
                ["rank_score", "abs_neg_log10_adj_pval", "log2FC"],
                ascending=[False, False, True],
            )
    if subset.empty:
        return subset, False
    total = int(subset.shape[0])
    trimmed = subset.head(max(1, int(limit))).copy()
    return trimmed, total > int(trimmed.shape[0])


def _parse_pca_mode(mode: str | None) -> tuple[str, str]:
    method = "PCA"
    plot_dim = "2D"
    raw = str(mode or "").strip()
    if not raw:
        return method, plot_dim
    for part in raw.split("|"):
        token = str(part or "").strip()
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key_norm = str(key or "").strip().lower()
        value_norm = str(value or "").strip()
        if not value_norm:
            continue
        if key_norm in {"method"}:
            method = value_norm
        if key_norm in {"plotdim", "plot_dim"}:
            value_up = value_norm.upper()
            if value_up in {"2D", "3D"}:
                plot_dim = value_up
    return method, plot_dim


def _pca_variance_lines(workflow: str, *, method: str = "PCA", plot_dim: str = "2D") -> list[str]:
    kind = _workflow_kind(workflow)
    lines: list[str] = []
    method_key = str(method or "PCA").strip().lower()
    target_dim = "3D" if str(plot_dim or "").strip().upper() == "3D" else "2D"

    if method_key != "pca":
        lines.append(
            f"pca_data|status=available|projection={target_dim}|method={_safe_context_text(method)}"
        )
        lines.append(
            f"pca_variance|status=not_applicable|reason=explained_pc_variance_is_defined_for_pca_only|method={_safe_context_text(method)}"
        )
        return lines

    pca_scores: pd.DataFrame | None = None
    explained = None
    axis_prefix = ""
    used_dim = target_dim
    projection_error: Exception | None = None

    try:
        pca_scores, explained, axis_prefix = _plot_images._pca_projection(
            kind,
            plot_dim=target_dim,
            method="PCA",
        )
    except Exception as exc:
        projection_error = exc

    if projection_error is not None or pca_scores is None:
        lines.append(
            f"pca_variance|status=unavailable|reason={_safe_context_text(projection_error)}"
        )
        return lines

    sample_count = int(pca_scores["sample"].astype(str).nunique()) if "sample" in pca_scores.columns else 0
    condition_count = (
        int(pca_scores["condition"].astype(str).nunique()) if "condition" in pca_scores.columns else 0
    )
    lines.append(
        f"pca_data|status=available|projection={used_dim}|sample_points={sample_count}|conditions={condition_count}"
    )

    if explained is None or axis_prefix != "PC":
        lines.append("pca_variance|status=unavailable|reason=explained_variance_not_computed")
        return lines

    explained_values = [float(value) for value in explained.tolist() if pd.notna(value)]
    if len(explained_values) < 2:
        lines.append("pca_variance|status=unavailable|reason=insufficient_components")
        return lines

    pc1 = explained_values[0]
    pc2 = explained_values[1]
    lines.append(
        f"pca_variance|PC1={pc1:.2f}|PC2={pc2:.2f}|PC1_PC2_total={(pc1 + pc2):.2f}|unit=percent_sample_variance"
    )

    if target_dim == "3D" and len(explained_values) >= 3:
        pc3 = explained_values[2]
        lines.append(
            f"pca_variance|PC3={pc3:.2f}|PC1_PC2_PC3_total={(pc1 + pc2 + pc3):.2f}|unit=percent_sample_variance"
        )

    return lines


def _coverage_text_from_rows(
    rows: pd.DataFrame,
    *,
    workflow: str,
    total_features: int | None,
    palette: dict[str, str],
) -> str:
    _, entity_plural = _WORKFLOW_ENTITY_LABELS.get(workflow, _WORKFLOW_ENTITY_LABELS["protein"])
    if rows.empty:
        return (
            f"coverage|workflow={workflow}|entity={entity_plural}|status=empty"
        )

    data = rows.copy()
    data["Sample"] = data["Sample"].astype(str)
    data["Condition"] = data["Condition"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).reset_index(drop=True)
    if data.empty:
        return (
            f"coverage|workflow={workflow}|entity={entity_plural}|status=no_numeric_values"
        )

    sample_count = int(data["Sample"].nunique())
    conditions = _condition_order(data)
    condition_count = len(conditions)

    lines: list[str] = []
    lines.append(
        f"coverage_overview|workflow={workflow}|entity={entity_plural}|samples={sample_count}|conditions={condition_count}|total_features={total_features if total_features is not None else 'unknown'}"
    )
    lines.append(
        "coverage_formula|detected_features=total_features-missing_values_per_sample"
    )
    lines.append(
        "coverage_visual|bars=detected_features_per_sample|bar_color=condition"
    )
    lines.append(
        "coverage_reference_line|color=red|value="
        f"{total_features if total_features is not None else 'unknown'}|"
        f"description=total_unique_{entity_plural}_over_all_samples"
    )

    for condition in conditions:
        subset = data[data["Condition"] == condition].copy()
        subset = subset.sort_values("Sample")
        sample_names = subset["Sample"].astype(str).tolist()
        sample_names_text = ",".join(sample_names)
        sample_values = ";".join(
            [f"{row['Sample']}={_fmt_value(float(row['Count']))}" for _, row in subset.iterrows()]
        )
        values = subset["Count"].astype(float)
        color = palette.get(condition, "")
        lines.append(
            f"condition|name={condition}|sample_count={len(sample_names)}|sample_names={sample_names_text}"
        )
        lines.append(
            f"sample_values|condition={condition}|values={sample_values}"
        )
        lines.append(
            f"condition_stats|name={condition}|mean={_fmt_value(values.mean())}|median={_fmt_value(values.median())}|min={_fmt_value(values.min())}|max={_fmt_value(values.max())}|color={color if color else 'unassigned'}"
        )

    return "\n".join(lines)


def general_proteomics_context(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)
    text = (
        f"{_GENERAL_PROTEOMICS_CONTEXT_PREFIX}"
        f"Current workflow scope is '{workflow_key}'. "
        f"Use {entity_plural} terminology for this context. "
        "Do not use generic terms like 'features'; always use the concrete workflow entity name "
        f"({entity_singular}/{entity_plural}). "
        "Do not mix proteins, phosphosites, phosphoproteins, and peptides unless the user explicitly asks for cross-level interpretation. "
        "If workflow scope is unclear from context, ask one focused follow-up question before making level-specific claims."
    )
    return _text_payload("general_proteomics_context", text)


def qc_coverage_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    try:
        if workflow_key == "peptide":
            rows, total_features = _coverage_rows_from_peptide()
        else:
            rows, total_features = _coverage_rows_from_wide(_workflow_kind(workflow_key))
        conditions = rows["Condition"].astype(str).tolist() if "Condition" in rows.columns else []
        palette = _condition_palette_for_workflow(workflow_key, conditions)
        text = _coverage_text_from_rows(
            rows,
            workflow=workflow_key,
            total_features=total_features,
            palette=palette,
        )
    except Exception as exc:
        _, entity_plural = _WORKFLOW_ENTITY_LABELS.get(workflow_key, _WORKFLOW_ENTITY_LABELS["protein"])
        text = (
            f"The bars of the plot show the number of {entity_plural} per sample colored by condition. "
            f"Coverage text generation is currently unavailable: {exc}"
        )
    return _text_payload("qc_coverage_plot", text)


def qc_histogram_intensity(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)
    text = (
        "Intensity values are evaluated on a per-condition basis: "
        f"for each {entity_singular}, the mean value across all replicates within each condition is calculated row-wise. "
        "The resulting condition-specific vectors are then used for visualization. "
        "Each condition is displayed as a separate histogram, distinguished by color. "
        "These histograms provide an overview of the data distribution and allow assessment of whether values approximate a normal distribution or deviate from it. "
        "For high-quality data, each condition should be approximately normally distributed, and overall distribution shapes should be similar across conditions. "
        f"Use workflow-appropriate terminology ({entity_plural}) in explanations. "
        "Important limitation for this context: this is guidance-only and not data-aware. "
        "Do not claim observed properties of the current dataset (for example normality, skewness, outliers, or condition differences) unless explicit computed statistics are provided in context. "
        "Only provide what to look for and how to interpret it, and clearly label such statements as checks rather than findings."
    )
    return _text_payload("qc_histogram_intensity", text)


def qc_boxplot_intensity(workflow: str = "protein", mode: str = "Mean") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_key = _normalize_boxplot_mode(mode)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)

    try:
        table = _table_functions.qc_boxplot_table(_workflow_kind(workflow_key), mode=mode_key).copy()
    except Exception as exc:
        return _text_payload(
            "qc_boxplot_intensity",
            (
                f"boxplot_overview|workflow={workflow_key}|entity={entity_plural}|mode={mode_key}|status=error\n"
                f"boxplot_error|detail={str(exc).replace('|', '/').replace(chr(10), ' ')}"
            ),
        )

    lines: list[str] = []
    lines.append(
        f"boxplot_overview|workflow={workflow_key}|entity={entity_plural}|mode={mode_key}|rows={int(table.shape[0])}"
    )
    lines.append(
        "boxplot_general|per_condition_processing=for_each_entity_extract_condition_values_from_replicates"
    )
    lines.append(
        "boxplot_general|quality_interpretation=compare_conditions_detect_shifts_outliers_symmetry_spread_skewness"
    )
    lines.append(
        "boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=beyond_whiskers"
    )
    lines.append(
        "boxplot_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "boxplot_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )

    if mode_key == "Single":
        lines.append(
            "boxplot_visual|mode=Single|boxes=sample_wise|color=condition|description=one_boxplot_per_sample_colored_by_condition"
        )
    else:
        lines.append(
            "boxplot_visual|mode=Mean|boxes=condition_wise|description=one_boxplot_per_condition_using_rowwise_condition_means"
        )

    if table.empty:
        lines.append("boxplot_data|status=empty")
        return _text_payload("qc_boxplot_intensity", "\n".join(lines))

    data = table.copy()
    numeric_columns = ["mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in numeric_columns:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    if mode_key == "Mean":
        if "Condition" not in data.columns:
            lines.append("boxplot_data|status=missing_condition_column")
            return _text_payload("qc_boxplot_intensity", "\n".join(lines))

        data["Condition"] = data["Condition"].astype(str)
        conditions = data["Condition"].tolist()
        palette = _condition_palette_for_workflow(workflow_key, conditions)
        for _, row in data.iterrows():
            condition = str(row.get("Condition", "")).strip() or "unknown"
            color = palette.get(condition, "")
            lines.append(
                "boxplot_condition|"
                f"name={condition}|mean={_fmt_value(row.get('mean', 0.0))}|median={_fmt_value(row.get('median', 0.0))}|"
                f"Q1={_fmt_value(row.get('Q1', 0.0))}|Q3={_fmt_value(row.get('Q3', 0.0))}|"
                f"lower_whisker={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker={_fmt_value(row.get('upper_whisker', 0.0))}|"
                f"color={color if color else 'unassigned'}"
            )
    else:
        if "Sample" not in data.columns:
            lines.append("boxplot_data|status=missing_sample_column")
            return _text_payload("qc_boxplot_intensity", "\n".join(lines))

        data["Sample"] = data["Sample"].astype(str)
        data["Condition"] = data["Sample"].map(_extract_condition_from_sample)
        conditions = data["Condition"].tolist()
        palette = _condition_palette_for_workflow(workflow_key, conditions)

        condition_order = _condition_order(data[["Condition"]].copy())
        lines.append(
            f"boxplot_samples|sample_count={int(data['Sample'].nunique())}|condition_count={len(condition_order)}"
        )
        for condition in condition_order:
            subset = data[data["Condition"] == condition].copy()
            sample_names = subset["Sample"].astype(str).tolist()
            color = palette.get(condition, "")
            median_values = pd.to_numeric(subset["median"], errors="coerce").dropna()
            lines.append(
                f"boxplot_condition_samples|name={condition}|sample_count={len(sample_names)}|sample_names={','.join(sample_names)}|color={color if color else 'unassigned'}"
            )
            if not median_values.empty:
                lines.append(
                    "boxplot_condition_median_stats|"
                    f"name={condition}|median_mean={_fmt_value(float(median_values.mean()))}|"
                    f"median_min={_fmt_value(float(median_values.min()))}|median_max={_fmt_value(float(median_values.max()))}"
                )

        for _, row in data.iterrows():
            sample = str(row.get("Sample", "")).strip() or "unknown"
            condition = str(row.get("Condition", "")).strip() or "unknown"
            lines.append(
                "boxplot_sample|"
                f"condition={condition}|sample={sample}|mean={_fmt_value(row.get('mean', 0.0))}|"
                f"median={_fmt_value(row.get('median', 0.0))}|Q1={_fmt_value(row.get('Q1', 0.0))}|Q3={_fmt_value(row.get('Q3', 0.0))}|"
                f"lower_whisker={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker={_fmt_value(row.get('upper_whisker', 0.0))}"
            )

    lines.append(
        "boxplot_quality_guidance|general_check=consistent_shapes_similar_replicate_medians_reasonable_symmetry_after_log2"
    )
    lines.append(
        "boxplot_quality_guidance|general_warning_signals=asymmetry_many_outliers_or_large_shifts_can_reflect_technical_issues_or_biological_variation"
    )

    return _text_payload("qc_boxplot_intensity", "\n".join(lines))


def qc_cov_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)

    try:
        table = _table_functions.qc_cv_table(_workflow_kind(workflow_key)).copy()
    except Exception as exc:
        return _text_payload(
            "qc_cov_plot",
            (
                f"cov_overview|workflow={workflow_key}|entity={entity_plural}|status=error\n"
                f"cov_error|detail={str(exc).replace('|', '/').replace(chr(10), ' ')}"
            ),
        )

    lines: list[str] = []
    lines.append(
        f"cov_overview|workflow={workflow_key}|entity={entity_plural}|rows={int(table.shape[0])}"
    )
    lines.append(
        "cov_general|description=condition_wise_coefficient_of_variation_distributions_visualized_as_boxplots"
    )
    lines.append(
        "cov_general|purpose=assess_replicate_consistency_within_each_condition_using_relative_variability"
    )
    lines.append(
        "cov_processing|minimum_replicates_per_condition=2"
    )
    lines.append(
        "cov_processing|steps=extract_condition_samples_compute_featurewise_mean_and_sd_compute_cv_remove_undefined_values_build_condition_distribution"
    )
    lines.append(
        "cov_formula|CV=(SD/mean)*100"
    )
    lines.append(
        "cov_boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=beyond_whiskers"
    )
    lines.append(
        "cov_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "cov_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )

    if table.empty:
        lines.append("cov_data|status=empty")
        return _text_payload("qc_cov_plot", "\n".join(lines))

    data = table.copy()
    required_columns = ["Condition", "mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in required_columns:
        if column not in data.columns:
            lines.append(f"cov_data|status=missing_column|column={column}")
            return _text_payload("qc_cov_plot", "\n".join(lines))

    data["Condition"] = data["Condition"].astype(str)
    numeric_columns = ["mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    condition_count = int(data["Condition"].nunique())
    lines.append(f"cov_conditions|count={condition_count}")

    for _, row in data.iterrows():
        condition = str(row.get("Condition", "")).strip() or "unknown"
        lines.append(
            "cov_condition|"
            f"name={condition}|mean_cv={_fmt_value(row.get('mean', 0.0))}|median_cv={_fmt_value(row.get('median', 0.0))}|"
            f"Q1_cv={_fmt_value(row.get('Q1', 0.0))}|Q3_cv={_fmt_value(row.get('Q3', 0.0))}|"
            f"lower_whisker_cv={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker_cv={_fmt_value(row.get('upper_whisker', 0.0))}"
        )

    lines.append(
        "cov_quality_guidance|general_check=similar_box_shapes_comparable_IQR_and_medians_support_replicate_consistency"
    )
    lines.append(
        "cov_quality_guidance|general_warning_signals=wide_boxes_high_medians_or_many_outliers_can_indicate_higher_variability_or_reproducibility_issues"
    )

    return _text_payload("qc_cov_plot", "\n".join(lines))


def qc_pca_plot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)
    method, plot_dim = _parse_pca_mode(mode)
    method_clean = _safe_context_text(method)

    lines: list[str] = []
    lines.append(
        f"pca_overview|workflow={workflow_key}|entity={entity_plural}|plot_types=static_and_interactive|dimensions=2D_or_3D"
    )
    lines.append(f"pca_active_view|method={method_clean}|plot_dim={plot_dim}")
    lines.append(
        "pca_description|goal=reduce_dimensionality_and_visualize_relationships_between_samples_based_on_measured_entities"
    )
    lines.append(
        "pca_points|each_point_represents=one_sample"
    )
    lines.append(
        "pca_components|principal_components=linear_combinations_of_all_measured_entities_using_variance_and_covariance_structure"
    )
    lines.append(
        "pca_component_order|PC1=max_variance|PC2=next_variance_orthogonal_to_PC1|PCn=remaining_orthogonal_variance"
    )
    lines.append(
        "pca_projection|benefit=condense_high_dimensional_information_into_few_axes_to_reveal_sample_patterns_clusters_and_trends"
    )
    lines.append(
        "pca_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "pca_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_within_condition_replicate_compactness"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_between_condition_separation_and_overlap_patterns"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_for_possible_outlier_samples"
    )
    lines.append(
        "pca_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "pca_usage|supports=identify_outliers_assess_condition_separation_evaluate_overall_dataset_structure"
    )
    lines.append("pca_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping")
    lines.extend(_pca_variance_lines(workflow_key, method=method, plot_dim=plot_dim))

    conditions = _conditions_for_workflow(workflow_key)
    lines.append(f"pca_conditions|count={len(conditions)}")

    return _text_payload("qc_pca_plot", "\n".join(lines))


def qc_abundance_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)

    lines: list[str] = []
    lines.append(
        f"abundance_overview|workflow={workflow_key}|entity={entity_plural}"
    )
    lines.append(
        "abundance_scope|purpose=inspect_global_intensity_patterns_and_explore_specific_entities_of_interest"
    )
    lines.append(
        "abundance_processing|step=group_samples_by_condition_and_compute_featurewise_mean_across_replicates"
    )
    lines.append(
        "abundance_transform|formula=log10(mean_intensity_across_replicates+1)|reason=avoid_undefined_values_at_zero"
    )
    lines.append(
        "abundance_ranking|x_axis=feature_rank_within_condition_sorted_by_transformed_intensity_descending"
    )
    lines.append(
        "abundance_axes|x=rank_high_to_low_intensity|y=log10_transformed_mean_intensity"
    )
    lines.append(
        "abundance_points|each_point_represents=one_entity_mean_within_one_condition"
    )
    lines.append(
        f"abundance_focus|supports=highlight_or_prioritize_selected_{entity_plural}_during_interpretation"
    )
    lines.append(
        "abundance_interpretation|rank_order_view_supports=assess_dynamic_range_compare_conditions_and_inspect_overall_intensity_distribution_shape"
    )
    lines.append(
        "abundance_special_case|phosphoprotein_context=optional_truncation_of_extended_ptm_text_for_readability"
    )
    lines.append(
        "abundance_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "abundance_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_curve_smoothness_and_gradual_intensity_decay"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_pattern_consistency_across_conditions_or_replicates"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_for_sharp_deviations_or_possible_outlier_entities"
    )
    lines.append(
        "abundance_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "abundance_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("qc_abundance_plot", "\n".join(lines))


def qc_correlation_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)

    lines: list[str] = []
    lines.append(
        f"correlation_overview|workflow={workflow_key}|entity={entity_plural}|modes=matrix_and_ellipse"
    )
    lines.append(
        "correlation_scope|purpose=visualize_pairwise_sample_similarity_assess_replicate_consistency_and_flag_possible_anomalies"
    )
    lines.append(
        "correlation_input|vectors=log_transformed_sample_intensity_vectors"
    )
    lines.append(
        "correlation_formula|pearson_r=cov(x_i,x_j)/(sigma_x_i*sigma_x_j)"
    )
    lines.append(
        "correlation_distance|d_ij=1-r_ij"
    )
    lines.append(
        "correlation_clustering|step=apply_hierarchical_clustering_on_distance_matrix_then_reorder_by_dendrogram"
    )
    lines.append(
        "correlation_structure|effect=reordered_map_groups_similar_samples_and_reveals_block_patterns"
    )
    lines.append(
        "correlation_matrix_mode|representation=reordered_correlation_matrix_with_diverging_scale"
    )
    lines.append(
        "correlation_matrix_mode|interpretation=one_end_high_positive_other_end_weak_or_negative_center_near_zero"
    )
    lines.append(
        "correlation_ellipse_mode|encoding=ellipse_shape_and_orientation_represent_magnitude_and_sign_of_correlation"
    )
    lines.append(
        "correlation_ellipse_mode|magnitude_rule=abs_r_toward_1_narrower_abs_r_toward_0_more_circular"
    )
    lines.append(
        "correlation_ellipse_mode|sign_rule=orientation_differs_for_positive_vs_negative_correlation"
    )
    lines.append(
        "correlation_usage|supports=global_sample_relationship_review_and_detection_of_possible_batch_or_labeling_issues"
    )
    lines.append(
        "correlation_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "correlation_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_within_group_similarity_patterns"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_clustering_smoothness_and_block_consistency"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_for_weak_or_asymmetric_sample_relationships"
    )
    lines.append(
        "correlation_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "correlation_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("qc_correlation_plot", "\n".join(lines))


def completeness_missing_value_plot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    kind = _normalize_completeness_kind(workflow_key, mode)
    entity_singular, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])

    lines: list[str] = []
    lines.append(
        f"missing_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        "missing_functions|wide_format=missing_value_plot|long_format=missing_value_plot_prec_and_missing_value_plot_pep"
    )
    lines.append(
        "missing_format_logic|protein_and_phosphosite_levels=wide_format|full_report_precursor_and_peptide_levels=long_format"
    )
    lines.append(
        "missing_calculation|step1=count_missing_values_per_feature_row"
    )
    lines.append(
        "missing_calculation|step2=aggregate_feature_counts_by_missing_value_count"
    )
    lines.append(
        "missing_plot_encoding|x_axis=number_of_missing_values_per_feature|y_axis=number_of_features_with_that_missing_value_count"
    )
    lines.append(
        "missing_interpretation_example|zero_missing_values_means_feature_detected_in_all_samples"
    )
    lines.append(
        "missing_interpretation_example|one_missing_value_means_feature_detected_in_total_samples_minus_one"
    )
    lines.append(
        "missing_interpretation_example|high_missing_value_counts_mean_feature_detected_in_few_samples"
    )
    lines.append(
        "missing_usage|supports=quick_overview_of_data_completeness_and_missingness_pattern_detection"
    )

    overall_missing, sample_count, feature_rows, error = _completeness_feature_rows(kind)
    if error is not None:
        lines.append(f"missing_tables|status=unavailable|detail={error}")
    else:
        lines.append(
            f"missing_tables_overall|overall_missing_values_percent={_fmt_value(overall_missing if overall_missing is not None else 0.0)}"
        )
        lines.append(f"missing_tables_samples|count={sample_count}")
        lines.append(f"missing_tables_feature_distribution|rows={len(feature_rows)}")
        for missing_count, feature_count, percent_value in feature_rows:
            detected_count = max(0, sample_count - int(missing_count))
            percent_text = "unknown" if percent_value is None else _fmt_value(percent_value)
            lines.append(
                "missing_feature_bin|"
                f"missing_values={missing_count}|feature_count={feature_count}|feature_percent={percent_text}|"
                f"detected_samples_per_feature={detected_count}"
            )

    lines.append(
        "missing_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "missing_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )
    lines.append(
        "missing_quality_guidance|type=checklist_only_not_findings|check=inspect_where_mass_of_distribution_sits_across_missing_value_bins"
    )
    lines.append(
        "missing_quality_guidance|type=checklist_only_not_findings|check=inspect_for_large_tails_at_high_missing_value_counts"
    )
    lines.append(
        "missing_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "missing_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("completeness_missing_value_plot", "\n".join(lines))


def completeness_missing_value_heatmap(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    kind = _normalize_completeness_kind(workflow_key, mode)
    _, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])

    lines: list[str] = []
    lines.append(
        f"missing_heatmap_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        "missing_heatmap_relation|similar_to_missing_value_plot=true|difference=preserves_structural_pattern_of_missingness"
    )
    lines.append(
        "missing_heatmap_encoding|missing_and_present_values_are_shown_with_distinct_visual_classes"
    )
    lines.append(
        "missing_heatmap_structure|rows=features|columns=samples|pattern_preservation=enabled"
    )
    lines.append(
        "missing_heatmap_pattern_example|vertical_missing_band=sample_with_many_missing_values"
    )
    lines.append(
        "missing_heatmap_pattern_example|horizontal_missing_band=feature_missing_across_multiple_samples"
    )
    lines.append(
        "missing_heatmap_usage|supports=quick_detection_of_systematic_missingness_and_missing-data_trends"
    )
    lines.append(
        "missing_heatmap_scope|general_information_only_not_data_specific_findings"
    )
    lines.append(
        "missing_heatmap_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "missing_heatmap_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )
    lines.append(
        "missing_heatmap_quality_guidance|type=checklist_only_not_findings|check=inspect_for_column_wise_missingness_patterns"
    )
    lines.append(
        "missing_heatmap_quality_guidance|type=checklist_only_not_findings|check=inspect_for_row_wise_missingness_patterns"
    )
    lines.append(
        "missing_heatmap_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "missing_heatmap_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("completeness_missing_value_heatmap", "\n".join(lines))


def completeness_missing_value_tables(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_completeness_kind(workflow_key, mode)
    _, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])
    outlier_threshold = _float_from_mode(
        mode_pairs,
        "outlierthreshold",
        "outlier_threshold",
        "threshold",
        default=50.0,
        minimum=0.0,
        maximum=100.0,
    )
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=True)

    lines: list[str] = []
    lines.append(
        f"missing_tables_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        f"missing_tables_outlier_criterion|rule=sample_missing_percent_greater_than_threshold|threshold_percent={_fmt_value(outlier_threshold)}"
    )
    lines.append(
        f"missing_tables_parameters|include_id={str(include_id).lower()}"
    )

    overall_missing, sample_count, sample_rows, feature_rows, outliers, error = _completeness_tables_payload(
        kind,
        outlier_threshold=outlier_threshold,
        include_id=include_id,
    )

    if error is not None:
        lines.append(f"missing_tables|status=unavailable|detail={error}")
    else:
        lines.append(
            f"missing_tables_overall|overall_missing_values_percent={_fmt_value(overall_missing if overall_missing is not None else 0.0)}"
        )
        lines.append(f"missing_tables_samples|count={sample_count}|rows={len(sample_rows)}")
        for row in sample_rows:
            sample_name = str(row.get("Sample", "")).strip() or "unknown"
            condition = _extract_condition_from_sample(sample_name)
            missing_count = row.get("Counts")
            missing_percent = row.get("%_missing_values")
            lines.append(
                "missing_sample_row|"
                f"sample={sample_name}|condition={condition}|missing_count={_safe_context_text(missing_count)}|"
                f"missing_percent={_safe_context_text(missing_percent)}"
            )

        lines.append(f"missing_tables_feature_distribution|rows={len(feature_rows)}")
        for row in feature_rows:
            missing_values = row.get("n_MissingProteinValues")
            feature_count = row.get("Counts")
            feature_percent = row.get("%_missing_values")
            lines.append(
                "missing_feature_row|"
                f"missing_values_per_feature={_safe_context_text(missing_values)}|feature_count={_safe_context_text(feature_count)}|"
                f"feature_percent={_safe_context_text(feature_percent)}"
            )

        lines.append(f"missing_outliers|count={len(outliers)}")
        if outliers:
            sample_percent_map: dict[str, Any] = {}
            for row in sample_rows:
                sample_name = str(row.get("Sample", "")).strip()
                if not sample_name:
                    continue
                sample_percent_map[sample_name] = row.get("%_missing_values")
            for sample_name in outliers:
                condition = _extract_condition_from_sample(sample_name)
                missing_percent = sample_percent_map.get(sample_name)
                lines.append(
                    "missing_outlier|"
                    f"sample={sample_name}|condition={condition}|missing_percent={_safe_context_text(missing_percent)}|"
                    f"defined_by_threshold_percent_gt={_fmt_value(outlier_threshold)}"
                )

    lines.append(
        "missing_tables_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "missing_tables_quality_guidance|hard_claim_gate=do_not_state_unqualified_quality_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )
    lines.append(
        "missing_tables_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("completeness_missing_value_tables", "\n".join(lines))


def stats_volcano_plot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)

    source = str(mode_pairs.get("source", "volcano")).strip().lower()
    if source not in {"volcano", "volcano_control"}:
        source = "volcano"
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    condition1_control = str(mode_pairs.get("condition1control", "")).strip()
    condition2_control = str(mode_pairs.get("condition2control", "")).strip()
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    test_type = str(mode_pairs.get("testtype", "unpaired")).strip().lower()
    if test_type not in {"paired", "unpaired"}:
        test_type = "unpaired"
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "imputed"}:
        data_source = "data"
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        "alpha",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        "fc",
        default=1.0,
        minimum=0.0,
    )
    max_ranked_per_group = int(
        _float_from_mode(
            mode_pairs,
            "maxranked",
            "max_ranked",
            "ranklimit",
            default=100.0,
            minimum=10.0,
            maximum=500.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"volcano_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|source={source}"
    )
    lines.append(
        "volcano_functions|data_function=volcano_data_f|plot_functions=volcano_plot_and_volcano_plot_h"
    )
    lines.append(
        "volcano_functions|control_variant=volcano_control_uses_same_output_table_structure"
    )
    lines.append(
        "volcano_formula|log2FC=mean_condition2-mean_condition1"
    )
    lines.append(
        "volcano_testing|supported_tests=unpaired_t_test_or_paired_t_test"
    )
    lines.append(
        "volcano_multiple_testing|method=benjamini_hochberg_fdr_control"
    )
    lines.append(
        "volcano_classification_rule|upregulated=(adj_p_or_selected_p<alpha_and_log2FC>tau)|downregulated=(adj_p_or_selected_p<alpha_and_log2FC<-tau)|not_significant=otherwise"
    )
    lines.append(
        "volcano_axes|x=log2FC|y=negative_log10_of_selected_p_metric"
    )
    lines.append(
        "volcano_presentation_rule|do_not_quote_internal_group_keys_or_context_field_names_in_user_facing_answers"
    )

    lines.append(
        f"volcano_parameters|source={source}|identifier={identifier}|test_type={test_type}|data_source={data_source}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|use_uncorrected={'true' if use_uncorrected else 'false'}"
    )
    lines.append(
        f"volcano_selected_p_metric|for_significance={'pval' if use_uncorrected else 'adj_pval'}|for_y_axis={'neg_log10_pval' if use_uncorrected else 'neg_log10_adj_pval'}"
    )
    lines.append(
        f"volcano_comparison|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}"
    )
    if source == "volcano_control":
        lines.append(
            f"volcano_control_comparison|condition1_control={_safe_context_text(condition1_control)}|condition2_control={_safe_context_text(condition2_control)}"
        )

    missing_required = not condition1 or not condition2 or (source == "volcano_control" and (not condition1_control or not condition2_control))
    if missing_required:
        lines.append("volcano_data|status=incomplete_parameters")
        return _text_payload("stats_volcano_plot", "\n".join(lines))

    try:
        source_used, label_column, df, warnings = _stats_tools._volcano_dataframe(
            kind=kind,  # type: ignore[arg-type]
            condition1=condition1,
            condition2=condition2,
            identifier=identifier,  # type: ignore[arg-type]
            p_value_threshold=float(p_value_threshold),
            log2fc_threshold=float(log2fc_threshold),
            test_type=test_type,
            use_uncorrected=bool(use_uncorrected),
            data_source=data_source,  # type: ignore[arg-type]
            condition1_control=condition1_control if source == "volcano_control" else None,
            condition2_control=condition2_control if source == "volcano_control" else None,
        )
    except Exception as exc:
        lines.append(f"volcano_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_volcano_plot", "\n".join(lines))

    frame = df.copy()
    frame["significance"] = frame["significance"].astype(str)
    frame["log2FC"] = pd.to_numeric(frame["log2FC"], errors="coerce")
    frame["pval"] = pd.to_numeric(frame["pval"], errors="coerce")
    frame["adj_pval"] = pd.to_numeric(frame["adj_pval"], errors="coerce")
    frame["neg_log10_adj_pval"] = pd.to_numeric(frame["neg_log10_adj_pval"], errors="coerce")

    total = int(frame.shape[0])
    up_count = int((frame["significance"] == "Upregulated").sum())
    down_count = int((frame["significance"] == "Downregulated").sum())
    not_significant_count = int((frame["significance"] == "Not significant").sum())
    denom = float(max(total, 1))
    lines.append(
        f"volcano_tested|total_{entity_plural}_tested={total}|label_column={label_column}|source_used={source_used}"
    )
    lines.append(
        f"volcano_counts|upregulated={up_count}|downregulated={down_count}|not_significant={not_significant_count}"
    )
    lines.append(
        f"volcano_fractions|upregulated_fraction={up_count/denom:.4f}|downregulated_fraction={down_count/denom:.4f}|not_significant_fraction={not_significant_count/denom:.4f}"
    )
    if warnings:
        lines.append(f"volcano_warnings|count={len(warnings)}|messages={_safe_context_text(' || '.join(warnings))}")

    significant_frame = frame[frame["significance"].isin(["Upregulated", "Downregulated"])].copy()
    has_significant = not significant_frame.empty
    lines.append(f"volcano_significant|count={int(significant_frame.shape[0])}|present={'true' if has_significant else 'false'}")

    if has_significant:
        up_ranked, up_truncated = _volcano_ranked_rows(
            significant_frame[significant_frame["significance"] == "Upregulated"].copy(),
            label_column=label_column,
            group="up",
            limit=max_ranked_per_group,
            strategy="balanced",
        )
        down_ranked, down_truncated = _volcano_ranked_rows(
            significant_frame[significant_frame["significance"] == "Downregulated"].copy(),
            label_column=label_column,
            group="down",
            limit=max_ranked_per_group,
            strategy="balanced",
        )
        lines.append(
            f"volcano_ranked_terms|type=significant|max_per_group={max_ranked_per_group}|rank_method=balanced_effect_and_significance|up_rows={int(up_ranked.shape[0])}|down_rows={int(down_ranked.shape[0])}|up_truncated={'true' if up_truncated else 'false'}|down_truncated={'true' if down_truncated else 'false'}"
        )
        for rank, (_, row) in enumerate(up_ranked.iterrows(), start=1):
            lines.append(
                "volcano_term|"
                f"group=upregulated|rank={rank}|term={_primary_term_label(row.get(label_column, ''))}|"
                f"log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
                f"pval={_fmt_value(float(row.get('pval', 1.0)))}|adj_pval={_fmt_value(float(row.get('adj_pval', 1.0)))}|"
                f"neg_log10_adj_pval={_fmt_value(float(row.get('neg_log10_adj_pval', 0.0)))}|rank_score={_fmt_value(float(row.get('rank_score', 0.0)))}"
            )
        for rank, (_, row) in enumerate(down_ranked.iterrows(), start=1):
            lines.append(
                "volcano_term|"
                f"group=downregulated|rank={rank}|term={_primary_term_label(row.get(label_column, ''))}|"
                f"log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
                f"pval={_fmt_value(float(row.get('pval', 1.0)))}|adj_pval={_fmt_value(float(row.get('adj_pval', 1.0)))}|"
                f"neg_log10_adj_pval={_fmt_value(float(row.get('neg_log10_adj_pval', 0.0)))}|rank_score={_fmt_value(float(row.get('rank_score', 0.0)))}"
            )
    else:
        lines.append(
            "volcano_disclaimer|message=no_features_passed_the_significance_and_fold_change_thresholds_the_following_terms_are_ranked_as_most_interesting_but_not_significant"
        )
        up_top, _ = _volcano_ranked_rows(
            frame.copy(),
            label_column=label_column,
            group="up",
            limit=10,
            strategy="fold_change_priority",
        )
        down_top, _ = _volcano_ranked_rows(
            frame.copy(),
            label_column=label_column,
            group="down",
            limit=10,
            strategy="fold_change_priority",
        )
        lines.append(
            f"volcano_ranked_terms|type=not_significant_fallback|rank_method=fold_change_priority_pvalue_tiebreak|up_rows={int(up_top.shape[0])}|down_rows={int(down_top.shape[0])}"
        )
        for rank, (_, row) in enumerate(up_top.iterrows(), start=1):
            lines.append(
                "volcano_term|"
                f"group=upregulated_candidate_not_significant|rank={rank}|term={_primary_term_label(row.get(label_column, ''))}|"
                f"log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
                f"pval={_fmt_value(float(row.get('pval', 1.0)))}|adj_pval={_fmt_value(float(row.get('adj_pval', 1.0)))}|"
                f"neg_log10_adj_pval={_fmt_value(float(row.get('neg_log10_adj_pval', 0.0)))}|rank_score={_fmt_value(float(row.get('rank_score', 0.0)))}"
            )
        for rank, (_, row) in enumerate(down_top.iterrows(), start=1):
            lines.append(
                "volcano_term|"
                f"group=downregulated_candidate_not_significant|rank={rank}|term={_primary_term_label(row.get(label_column, ''))}|"
                f"log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
                f"pval={_fmt_value(float(row.get('pval', 1.0)))}|adj_pval={_fmt_value(float(row.get('adj_pval', 1.0)))}|"
                f"neg_log10_adj_pval={_fmt_value(float(row.get('neg_log10_adj_pval', 0.0)))}|rank_score={_fmt_value(float(row.get('rank_score', 0.0)))}"
            )

    lines.append(
        "volcano_quality_rule|scope=data_driven_with_explicit_thresholds|claims_allowed_only_when_reporting_the_explicit_metrics_and_thresholds_used"
    )
    lines.append(
        "volcano_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )
    return _text_payload("stats_volcano_plot", "\n".join(lines))


def stats_gsea_plot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    source = str(mode_pairs.get("source", "volcano")).strip().lower()
    if source not in {"volcano", "volcano_control"}:
        source = "volcano"
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    condition1_control = str(mode_pairs.get("condition1control", "")).strip()
    condition2_control = str(mode_pairs.get("condition2control", "")).strip()
    test_type = str(mode_pairs.get("testtype", "unpaired")).strip().lower()
    if test_type not in {"paired", "unpaired"}:
        test_type = "unpaired"
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        "alpha",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        "fc",
        default=1.0,
        minimum=0.0,
    )
    top_n = int(
        _float_from_mode(
            mode_pairs,
            "topn",
            "top_terms",
            "topterms",
            default=10.0,
            minimum=1.0,
            maximum=100.0,
        )
    )
    min_term_size = int(
        _float_from_mode(
            mode_pairs,
            "mintermsize",
            "min_term_size",
            default=20.0,
            minimum=1.0,
        )
    )
    max_term_size = int(
        _float_from_mode(
            mode_pairs,
            "maxtermsize",
            "max_term_size",
            default=300.0,
            minimum=1.0,
        )
    )
    if min_term_size > max_term_size:
        min_term_size, max_term_size = max_term_size, min_term_size

    max_gene_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxgenepreview",
            "max_gene_preview",
            default=200.0,
            minimum=20.0,
            maximum=1000.0,
        )
    )
    max_intersection_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxintersectionpreview",
            "max_intersection_preview",
            default=40.0,
            minimum=5.0,
            maximum=200.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"gsea_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|source={source}"
    )
    lines.append(
        "gsea_method|basis=volcano_t_test_differential_analysis_with_user_defined_thresholds"
    )
    lines.append(
        "gsea_method|volcano_dependency=upregulated_and_downregulated_gene_clusters_are_derived_from_t_test_and_multiple_testing_settings"
    )
    lines.append(
        "gsea_flow|upregulated_cluster=upregulated_genes_to_enriched_pathways"
    )
    lines.append(
        "gsea_flow|downregulated_cluster=downregulated_genes_to_enriched_pathways"
    )
    lines.append(
        f"gsea_parameters|source={source}|test_type={test_type}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|use_uncorrected={'true' if use_uncorrected else 'false'}"
    )
    lines.append(
        f"gsea_comparison|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}"
    )
    if source == "volcano_control":
        lines.append(
            f"gsea_control_comparison|condition1_control={_safe_context_text(condition1_control)}|condition2_control={_safe_context_text(condition2_control)}"
        )
    lines.append(
        f"gsea_term_filters|top_terms={top_n}|min_term_size={min_term_size}|max_term_size={max_term_size}"
    )

    missing_required = not condition1 or not condition2 or (source == "volcano_control" and (not condition1_control or not condition2_control))
    if missing_required:
        lines.append("gsea_data|status=incomplete_parameters")
        return _text_payload("stats_gsea_plot", "\n".join(lines))

    try:
        payload = EnrichmentRequest(
            kind=kind,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            condition1=condition1,
            condition2=condition2,
            condition1Control=condition1_control if source == "volcano_control" else None,
            condition2Control=condition2_control if source == "volcano_control" else None,
            pValueThreshold=float(p_value_threshold),
            log2fcThreshold=float(log2fc_threshold),
            testType=test_type,  # type: ignore[arg-type]
            useUncorrected=bool(use_uncorrected),
            topN=int(top_n),
            minTermSize=int(min_term_size),
            maxTermSize=int(max_term_size),
        )
        result = _stats_tools.run_enrichment(payload)
    except Exception as exc:
        lines.append(f"gsea_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_gsea_plot", "\n".join(lines))

    up_genes = [str(value) for value in result.upGenes]
    down_genes = [str(value) for value in result.downGenes]
    up_gene_preview, up_gene_truncated = _preview_items(up_genes, max_gene_preview)
    down_gene_preview, down_gene_truncated = _preview_items(down_genes, max_gene_preview)

    lines.append(
        f"gsea_data|status=available|source_used={result.sourceUsed}"
    )
    lines.append(
        f"gsea_gene_clusters|upregulated_genes={len(up_genes)}|downregulated_genes={len(down_genes)}"
    )
    lines.append(
        f"gsea_cluster_genes|cluster=upregulated|count={len(up_genes)}|preview_count={len(up_gene_preview)}|preview_truncated={'true' if up_gene_truncated else 'false'}|genes={_safe_context_text(';'.join(up_gene_preview))}"
    )
    lines.append(
        f"gsea_cluster_genes|cluster=downregulated|count={len(down_genes)}|preview_count={len(down_gene_preview)}|preview_truncated={'true' if down_gene_truncated else 'false'}|genes={_safe_context_text(';'.join(down_gene_preview))}"
    )

    up_terms = list(result.upTerms)
    down_terms = list(result.downTerms)
    lines.append(f"gsea_terms|cluster=upregulated|count={len(up_terms)}")
    lines.append(f"gsea_terms|cluster=downregulated|count={len(down_terms)}")

    if not up_terms:
        lines.append("gsea_terms_status|cluster=upregulated|status=no_terms_for_current_filters")
    if not down_terms:
        lines.append("gsea_terms_status|cluster=downregulated|status=no_terms_for_current_filters")

    for index, term in enumerate(up_terms, start=1):
        genes_preview, preview_truncated = _preview_items([str(value) for value in term.intersectingGenes], max_intersection_preview)
        lines.append(
            "gsea_term|"
            f"cluster=upregulated|rank={index}|source={_safe_context_text(term.source)}|term_id={_safe_context_text(term.termId)}|"
            f"name={_safe_context_text(term.name)}|term_size={term.termSize}|intersection_size={term.intersectionSize}|"
            f"hit_percent={_fmt_value(term.hitPercent)}|p_value={_fmt_value(term.pValue)}|adj_p_value={_fmt_value(term.adjPValue)}|"
            f"intersection_genes_count={len(term.intersectingGenes)}|intersection_genes_preview={_safe_context_text(';'.join(genes_preview))}|"
            f"intersection_preview_truncated={'true' if preview_truncated else 'false'}"
        )

    for index, term in enumerate(down_terms, start=1):
        genes_preview, preview_truncated = _preview_items([str(value) for value in term.intersectingGenes], max_intersection_preview)
        lines.append(
            "gsea_term|"
            f"cluster=downregulated|rank={index}|source={_safe_context_text(term.source)}|term_id={_safe_context_text(term.termId)}|"
            f"name={_safe_context_text(term.name)}|term_size={term.termSize}|intersection_size={term.intersectionSize}|"
            f"hit_percent={_fmt_value(term.hitPercent)}|p_value={_fmt_value(term.pValue)}|adj_p_value={_fmt_value(term.adjPValue)}|"
            f"intersection_genes_count={len(term.intersectingGenes)}|intersection_genes_preview={_safe_context_text(';'.join(genes_preview))}|"
            f"intersection_preview_truncated={'true' if preview_truncated else 'false'}"
        )

    if result.warnings:
        lines.append(
            f"gsea_warnings|count={len(result.warnings)}|messages={_safe_context_text(' || '.join(result.warnings))}"
        )

    lines.append(
        "gsea_quality_rule|scope=data_driven_with_explicit_thresholds|claims_allowed_only_when_reporting_the_explicit_metrics_and_filters_used"
    )
    lines.append(
        "gsea_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("stats_gsea_plot", "\n".join(lines))


def stats_pathway_heatmap_plot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    pathway = str(mode_pairs.get("pathway", "")).strip()
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    value_type = str(mode_pairs.get("valuetype", mode_pairs.get("value_type", "z"))).strip().lower()
    if value_type not in {"log2", "z"}:
        value_type = "z"
    remove_empty = _bool_from_mode(mode_pairs, "removeempty", "remove_empty", default=True)
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    cluster_rows = _bool_from_mode(mode_pairs, "clusterrows", "cluster_rows", default=False)
    cluster_cols = _bool_from_mode(mode_pairs, "clustercols", "cluster_cols", default=False)
    max_gene_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxgenepreview",
            "max_gene_preview",
            default=350.0,
            minimum=20.0,
            maximum=2000.0,
        )
    )
    max_condition_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxconditionpreview",
            "max_condition_preview",
            default=80.0,
            minimum=10.0,
            maximum=500.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"pathway_heatmap_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        f"pathway_heatmap_selection|pathway={_safe_context_text(pathway)}|value_type={'z_score' if value_type == 'z' else 'log2'}|remove_empty={'true' if remove_empty else 'false'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|cluster_rows={'true' if cluster_rows else 'false'}|cluster_cols={'true' if cluster_cols else 'false'}"
    )
    if selected_conditions:
        condition_preview, condition_truncated = _preview_items(selected_conditions, max_condition_preview)
        lines.append(
            f"pathway_heatmap_conditions|selection=custom|selected_count={len(selected_conditions)}|preview_count={len(condition_preview)}|preview_truncated={'true' if condition_truncated else 'false'}|conditions={_safe_context_text(';'.join(condition_preview))}"
        )
    else:
        lines.append("pathway_heatmap_conditions|selection=all_available")
    lines.append(
        "pathway_heatmap_value_mode|log2=log2_intensities|z_score=row_wise_standardization_per_gene_across_selected_samples"
    )

    if not pathway:
        lines.append("pathway_heatmap_data|status=incomplete_parameters|detail=pathway_not_selected")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    try:
        source_used, frame, metadata, warnings = _stats_tools._stats_source(kind)  # type: ignore[attr-defined]
    except Exception as exc:
        lines.append(f"pathway_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    gene_candidates = ["Gene_group", "GeneNames"] if kind == "phosprot" else ["GeneNames", "Gene_group"]
    gene_column = next((column for column in gene_candidates if column in frame.columns), None)
    if gene_column is None:
        lines.append("pathway_heatmap_data|status=error|detail=gene_label_column_not_available")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    try:
        db = _stats_tools.load_go_db()
        pathway_row = db.loc[db["description"].astype(str).str.lower() == pathway.strip().lower()]
        if pathway_row.empty:
            raise ValueError(f"No pathway found matching '{pathway}'.")
        pathway_genes = [
            gene.strip()
            for gene in str(pathway_row.iloc[0]["genes"]).split(";")
            if str(gene).strip()
        ]
        if not pathway_genes:
            raise ValueError("The selected pathway does not contain any genes.")

        meta_filtered = metadata.copy()
        if selected_conditions:
            selected_set = {value.strip() for value in selected_conditions if value.strip()}
            meta_filtered = meta_filtered[meta_filtered["condition"].astype(str).isin(selected_set)]
        if meta_filtered.empty:
            raise ValueError("No samples match the selected conditions.")

        sample_columns = [
            sample
            for sample in meta_filtered["sample"].astype(str).tolist()
            if sample in frame.columns
        ]
        if not sample_columns:
            raise ValueError("No selected samples are available in the current dataset.")

        value_frame = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
        gene_to_row: dict[str, pd.Series] = {}
        for idx, gene_value in frame[gene_column].items():
            tokens = [token.strip() for token in str(gene_value or "").split(";") if token.strip()]
            for token in tokens:
                key = token.lower()
                if key not in gene_to_row and idx in value_frame.index:
                    gene_to_row[key] = value_frame.loc[idx]

        matrix_rows: list[pd.Series] = []
        matrix_index: list[str] = []
        all_missing_rows = 0
        matched_genes_in_dataset = 0
        for gene in pathway_genes:
            key = gene.lower()
            row = gene_to_row.get(key)
            if row is None:
                matrix_rows.append(pd.Series([pd.NA] * len(sample_columns), index=sample_columns))
                matrix_index.append(gene)
                continue
            matched_genes_in_dataset += 1
            if bool(row.isna().all()):
                all_missing_rows += 1
            matrix_rows.append(row)
            matrix_index.append(gene)

        heatmap_data = pd.DataFrame(matrix_rows, index=matrix_index, columns=sample_columns)
        if remove_empty:
            heatmap_data = heatmap_data.dropna(how="all")
        shown_genes = [str(gene) for gene in heatmap_data.index.tolist()]

        missing_in_dataset = max(0, len(pathway_genes) - matched_genes_in_dataset)
        removed_due_empty = max(0, all_missing_rows) if remove_empty else 0

        pathway_gene_preview, pathway_gene_preview_truncated = _preview_items(pathway_genes, max_gene_preview)
        shown_gene_preview, shown_gene_preview_truncated = _preview_items(shown_genes, max_gene_preview)

        lines.append(
            f"pathway_heatmap_data|status=available|source_used={source_used}|gene_column={_safe_context_text(gene_column)}|pathway_gene_count={len(pathway_genes)}|shown_gene_count={len(shown_genes)}|matched_gene_count={matched_genes_in_dataset}|missing_in_dataset_count={missing_in_dataset}|removed_due_all_missing_count={removed_due_empty}|sample_count={len(sample_columns)}"
        )
        lines.append(
            f"pathway_heatmap_pathway_genes|count={len(pathway_genes)}|preview_count={len(pathway_gene_preview)}|preview_truncated={'true' if pathway_gene_preview_truncated else 'false'}|genes={_safe_context_text(';'.join(pathway_gene_preview))}"
        )
        lines.append(
            f"pathway_heatmap_shown_genes|count={len(shown_genes)}|preview_count={len(shown_gene_preview)}|preview_truncated={'true' if shown_gene_preview_truncated else 'false'}|genes={_safe_context_text(';'.join(shown_gene_preview))}"
        )
    except Exception as exc:
        lines.append(f"pathway_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    if warnings:
        lines.append(
            f"pathway_heatmap_warnings|count={len(warnings)}|messages={_safe_context_text(' || '.join(warnings))}"
        )
    lines.append(
        "pathway_heatmap_quality_rule|scope=data_driven_with_explicit_selection_and_counts|claims_allowed_only_when_reporting_explicit_values_from_context"
    )
    lines.append(
        "pathway_heatmap_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )
    return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))


def comparison_pearson_correlation(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    mode_raw = str(mode_pairs.get("mode", "Single")).strip().lower()
    if mode_raw in {"condition", "mean"}:
        selected_mode = "Mean"
        api_mode = "Condition"
    else:
        selected_mode = "Single"
        api_mode = "Single"

    sample1 = str(mode_pairs.get("sample1", "")).strip()
    sample2 = str(mode_pairs.get("sample2", "")).strip()
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    alias1 = str(mode_pairs.get("alias1", "")).strip()
    alias2 = str(mode_pairs.get("alias2", "")).strip()

    if api_mode == "Single":
        left_fallback = sample1
        right_fallback = sample2
    else:
        left_fallback = condition1
        right_fallback = condition2
    left_input = alias1 or left_fallback
    right_input = alias2 or right_fallback

    lines: list[str] = []
    lines.append(
        f"comparison_pearson_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        "comparison_pearson_scope|purpose=interactive_view_of_linear_relationships_for_reproducibility_outlier_screening_and_sample_or_condition_comparison"
    )
    lines.append(
        "comparison_pearson_functions|single_mode_function=correlation_xy_intensity_single|mean_mode_function=correlation_xy_intensity"
    )
    lines.append(
        "comparison_pearson_workflow|steps=extract_values_remove_missing_compute_pearson_and_p_value_scatter_plot_with_regression_line"
    )
    lines.append(
        "comparison_pearson_rule|alias_priority=true|when_alias_is_provided_use_alias_labels_instead_of_raw_sample_or_condition_names"
    )
    if selected_mode == "Single":
        lines.append(
            "comparison_pearson_mode|selected=Single|comparison_level=sample_vs_sample|point_definition=one_entity_value_in_sample1_compared_with_sample2"
        )
        lines.append(
            f"comparison_pearson_selection|left={_safe_context_text(left_input)}|right={_safe_context_text(right_input)}"
        )
    else:
        lines.append(
            "comparison_pearson_mode|selected=Mean|comparison_level=condition_mean_vs_condition_mean|point_definition=one_entity_mean_across_replicates_in_condition1_compared_with_condition2"
        )
        lines.append(
            "comparison_pearson_mean_definition|per_entity_condition_value=mean_across_all_available_replicates_within_each_condition"
        )
        lines.append(
            f"comparison_pearson_selection|left={_safe_context_text(left_input)}|right={_safe_context_text(right_input)}"
        )

    incomplete = (api_mode == "Single" and (not sample1 or not sample2)) or (
        api_mode == "Condition" and (not condition1 or not condition2)
    )
    if incomplete:
        lines.append("comparison_pearson_data|status=incomplete_parameters")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    try:
        table = _comparison_tools.pearson_correlation_table(
            kind,  # type: ignore[arg-type]
            mode=api_mode,
            sample1=sample1,
            sample2=sample2,
            condition1=condition1,
            condition2=condition2,
            alias1=alias1,
            alias2=alias2,
        ).copy()
    except Exception as exc:
        lines.append(f"comparison_pearson_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    lines.append(
        f"comparison_pearson_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("comparison_pearson_table|status=empty")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))
    if "Metric" not in table.columns or "Value" not in table.columns:
        lines.append("comparison_pearson_table|status=error|detail=missing_columns:Metric,Value")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    metric_values: dict[str, Any] = {}
    for _, row in table.iterrows():
        metric = str(row.get("Metric", "")).strip()
        if not metric:
            continue
        value = row.get("Value")
        metric_values[metric] = value

    left_label = str(metric_values.get("Left", left_input) or left_input).strip() or "unknown"
    right_label = str(metric_values.get("Right", right_input) or right_input).strip() or "unknown"
    lines.append(
        f"comparison_pearson_labels|left={_safe_context_text(left_label)}|right={_safe_context_text(right_label)}"
    )

    for metric in ["Left", "Right", "Points", "PearsonR"]:
        if metric not in metric_values:
            continue
        value = metric_values.get(metric)
        value_text = _safe_context_text(value)
        if metric == "Points":
            try:
                value_text = str(int(round(float(value))))
            except Exception:
                value_text = _safe_context_text(value)
        elif metric == "PearsonR":
            try:
                value_num = float(value)
                value_text = _fmt_value(value_num)
            except Exception:
                value_text = _safe_context_text(value)
        lines.append(
            f"comparison_pearson_table_metric|metric={metric}|value={value_text}"
        )

    lines.append(
        "comparison_pearson_reference|pearson_r_source=summary_table_metric_PearsonR"
    )
    lines.append(
        "comparison_pearson_quality_rule|scope=data_descriptive_only|do_not_make_quality_or_outlier_claims_without_explicit_thresholds_or_cutoffs"
    )
    lines.append(
        "comparison_pearson_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("comparison_pearson_correlation", "\n".join(lines))


def comparison_venn_diagram(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    mode_raw = str(mode_pairs.get("mode", "Single")).strip().lower()
    if mode_raw in {"condition", "mean"}:
        selected_mode = "Mean"
        api_mode = "Condition"
        level_text = "condition"
    else:
        selected_mode = "Single"
        api_mode = "Single"
        level_text = "sample"

    first = str(mode_pairs.get("first", "")).strip()
    second = str(mode_pairs.get("second", "")).strip()
    third = str(mode_pairs.get("third", "")).strip()
    alias1 = str(mode_pairs.get("alias1", "")).strip()
    alias2 = str(mode_pairs.get("alias2", "")).strip()
    alias3 = str(mode_pairs.get("alias3", "")).strip()
    color1 = str(mode_pairs.get("color1", "#1f77b4")).strip() or "#1f77b4"
    color2 = str(mode_pairs.get("color2", "#ff7f0e")).strip() or "#ff7f0e"
    color3 = str(mode_pairs.get("color3", "#2ca02c")).strip() or "#2ca02c"

    label1 = alias1 or first
    label2 = alias2 or second
    label3 = alias3 or third
    has_third = bool(third)
    set_count = 3 if has_third else 2

    lines: list[str] = []
    lines.append(
        f"comparison_venn_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|set_count={set_count}"
    )
    lines.append(
        "comparison_venn_scope|purpose=visualize_shared_and_unique_entities_across_samples_or_conditions"
    )
    lines.append(
        "comparison_venn_functions|single_mode_function=overlap_plot_single|mean_mode_function=overlap_plot_condition"
    )
    lines.append(
        "comparison_venn_processing|step1=extract_non_missing_and_non_zero_entities|step2=convert_to_sets|step3=render_venn2_or_venn3"
    )
    lines.append(
        "comparison_venn_rule|alias_priority=true|when_alias_is_provided_use_alias_labels_instead_of_raw_sample_or_condition_names"
    )
    if selected_mode == "Single":
        lines.append(
            "comparison_venn_mode|selected=Single|comparison_level=sample_vs_sample_or_sample_triplet|presence_rule=entity_is_present_if_non_missing_and_non_zero_in_each_selected_sample"
        )
    else:
        lines.append(
            "comparison_venn_mode|selected=Mean|comparison_level=condition_vs_condition_or_condition_triplet|presence_rule=entity_is_present_if_detected_in_at_least_one_replicate_within_each_selected_condition"
        )
    lines.append(
        f"comparison_venn_selection|level={level_text}|first={_safe_context_text(label1)}|second={_safe_context_text(label2)}|third={_safe_context_text(label3 if has_third else 'not_selected')}"
    )
    lines.append(
        f"comparison_venn_colors|first={_safe_context_text(_color_name(color1))}|second={_safe_context_text(_color_name(color2))}|third={_safe_context_text(_color_name(color3) if has_third else 'not_used')}"
    )

    if not first or not second:
        lines.append("comparison_venn_data|status=incomplete_parameters")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    try:
        table = _comparison_tools.venn_table(
            kind,  # type: ignore[arg-type]
            mode=api_mode,
            first=first,
            second=second,
            third=third,
            alias1=alias1,
            alias2=alias2,
            alias3=alias3,
        ).copy()
    except Exception as exc:
        lines.append(f"comparison_venn_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    lines.append(
        f"comparison_venn_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("comparison_venn_table|status=empty")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))
    if "Region" not in table.columns or "Count" not in table.columns:
        lines.append("comparison_venn_table|status=error|detail=missing_columns:Region,Count")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    data = table.copy()
    data["Region"] = data["Region"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).copy()

    if data.empty:
        lines.append("comparison_venn_table|status=empty_after_numeric_filter")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    for _, row in data.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_table_row|region={_safe_context_text(region)}|count={count}"
        )

    total_rows = data[data["Region"].str.startswith("Total ")].copy()
    for _, row in total_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        label = region[6:].strip() if region.startswith("Total ") else region
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_group_size|group={_safe_context_text(label)}|count={count}"
        )

    unique_rows = data[data["Region"].str.endswith(" only")].copy()
    for _, row in unique_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_unique|region={_safe_context_text(region)}|count={count}"
        )

    overlap_rows = data[
        data["Region"].str.contains(" & ", regex=False)
        & ~data["Region"].str.startswith("Total ")
    ].copy()
    for _, row in overlap_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_overlap|region={_safe_context_text(region)}|count={count}"
        )

    lines.append(
        "comparison_venn_interpretation_scope|supports=identify_shared_entities_unique_entities_and_coverage_differences_across_selected_sets"
    )
    lines.append(
        "comparison_venn_quality_rule|scope=data_descriptive_only|do_not_make_reproducibility_or_quality_claims_without_explicit_thresholds_or_cutoffs"
    )
    lines.append(
        "comparison_venn_color_rule|color_information_included_for_selected_sets"
    )

    return _text_payload("comparison_venn_diagram", "\n".join(lines))


def phospho_phosphosite_plot(workflow: str = "phosphosite", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    cutoff = _float_from_mode(
        mode_pairs,
        "cutoff",
        default=0.0,
        minimum=0.0,
    )

    lines: list[str] = []
    lines.append(
        f"phosphosite_summary_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites"
    )
    lines.append(
        f"phosphosite_summary_cutoff|ptm_localization_probability_min={_fmt_value(cutoff)}"
    )
    lines.append(
        "phosphosite_summary_cutoff_rule|filter=retain_rows_where_PTM_localization_is_greater_than_or_equal_to_cutoff"
    )
    lines.append(
        "phosphosite_summary_entities|phosphoproteins=distinct_protein_groups_with_at_least_one_site_passing_cutoff|phosphopeptides=unique_modified_peptide_sequences|phosphosites=unique_PTM_collapse_keys"
    )
    lines.append(
        "phosphosite_summary_visual|plot=horizontal_bar_chart|ordering=descending_by_count|labels=exact_count_shown_at_bar_end"
    )
    lines.append(
        "phosphosite_summary_general|expected_hierarchy=phosphopeptides_and_phosphosites_often_exceed_phosphoproteins_due_to_modification_hierarchy"
    )
    lines.append(
        "phosphosite_summary_general|cutoff_interpretation=sharp_count_drop_with_higher_cutoff_can_indicate_many_low_confidence_localizations_while_stable_counts_can_indicate_robust_localization"
    )

    try:
        table = _phospho_tools.phosphosite_plot_table(cutoff=float(cutoff)).copy()
    except Exception as exc:
        lines.append(f"phosphosite_summary_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    lines.append(
        f"phosphosite_summary_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phosphosite_summary_table|status=empty")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))
    if "Term" not in table.columns or "Count" not in table.columns:
        lines.append("phosphosite_summary_table|status=error|detail=missing_columns:Term,Count")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    data = table.copy()
    data["Term"] = data["Term"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).copy()

    if data.empty:
        lines.append("phosphosite_summary_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    phosphosites_count: int | None = None
    phosphopeptides_count: int | None = None
    phosphoproteins_count: int | None = None

    for _, row in data.iterrows():
        term = str(row.get("Term", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"phosphosite_summary_table_row|term={_safe_context_text(term)}|count={count}"
        )
        term_norm = term.lower().replace(" ", "")
        if "phosphosite" in term_norm:
            phosphosites_count = count
        elif "phosphopeptide" in term_norm:
            phosphopeptides_count = count
        elif "phosphoprotein" in term_norm:
            phosphoproteins_count = count

    lines.append(
        f"phosphosite_summary_under_cutoff|cutoff={_fmt_value(cutoff)}|phosphosites={phosphosites_count if phosphosites_count is not None else 'unknown'}|phosphopeptides={phosphopeptides_count if phosphopeptides_count is not None else 'unknown'}|phosphoproteins={phosphoproteins_count if phosphoproteins_count is not None else 'unknown'}"
    )
    lines.append(
        "phosphosite_summary_quality_rule|data_specific_counts_at_selected_cutoff_are_allowed|broader_quality_claims_require_explicit_comparison_rules_or_additional_thresholds"
    )
    lines.append(
        "phosphosite_summary_color_rule|never_report_colors_unless_user_explicitly_requests_color_mapping"
    )

    return _text_payload("phospho_phosphosite_plot", "\n".join(lines))


def phospho_phosphosite_coverage_plot(workflow: str = "phosphosite", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    mode_raw = str(mode_pairs.get("mode", "Normal")).strip().lower()
    plot_mode = "Summary" if mode_raw == "summary" else "Normal"
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))

    lines: list[str] = []
    lines.append(
        f"phospho_coverage_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites|mode={plot_mode}"
    )
    lines.append(
        "phospho_coverage_functions|per_sample_view=phossite_coverage_plot|summary_view=phossite_coverage_plot_summary"
    )
    lines.append(
        "phospho_coverage_class_rule|class_i=PTM_localization_greater_than_or_equal_to_0.75|not_class_i=PTM_localization_less_than_0.75"
    )
    lines.append(
        "phospho_coverage_calculation|per_sample_detected_sites=total_sites_minus_missing_values|computed_separately_for_class_i_and_not_class_i"
    )
    lines.append(
        "phospho_coverage_visual_encoding|color_mapping=class_i_vs_not_class_i|not_colored_by_condition"
    )
    lines.append(
        "phospho_coverage_normal_view|bars=stacked_per_sample|stack_order=class_i_bottom_then_not_class_i_top"
    )
    lines.append(
        "phospho_coverage_summary_view|bars=condition_level_mean_for_class_i_and_not_class_i|points=replicate_values|error_bars=standard_deviation"
    )
    lines.append(
        f"phospho_coverage_parameters|include_id={'true' if include_id else 'false'}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}"
    )

    conditions_arg = selected_conditions if selected_conditions else None
    try:
        table = _phospho_tools.phospho_coverage_table(
            include_id=include_id,
            conditions=conditions_arg,
            mode=plot_mode,
        ).copy()
    except Exception as exc:
        lines.append(f"phospho_coverage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

    lines.append(
        f"phospho_coverage_table|status=available|mode={plot_mode}|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_coverage_table|status=empty")
        return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

    if plot_mode == "Normal":
        required_columns = ["Sample", "Class I", "Not Class I", "Condition", "Total"]
        missing_columns = [column for column in required_columns if column not in table.columns]
        if missing_columns:
            lines.append(
                f"phospho_coverage_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
            )
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        data = table.copy()
        data["Sample"] = data["Sample"].astype(str)
        data["Condition"] = data["Condition"].astype(str)
        data["Class I"] = pd.to_numeric(data["Class I"], errors="coerce")
        data["Not Class I"] = pd.to_numeric(data["Not Class I"], errors="coerce")
        data["Total"] = pd.to_numeric(data["Total"], errors="coerce")
        data = data.dropna(subset=["Class I", "Not Class I", "Total"])
        if data.empty:
            lines.append("phospho_coverage_table|status=empty_after_numeric_filter")
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        sample_count = int(data["Sample"].nunique())
        condition_order = _condition_order(data[["Condition"]].copy())
        lines.append(
            f"phospho_coverage_counts|sample_count={sample_count}|condition_count={len(condition_order)}"
        )
        for _, row in data.iterrows():
            lines.append(
                "phospho_coverage_sample|"
                f"condition={_safe_context_text(row['Condition'])}|sample={_safe_context_text(row['Sample'])}|"
                f"class_i={_fmt_value(float(row['Class I']))}|not_class_i={_fmt_value(float(row['Not Class I']))}|total={_fmt_value(float(row['Total']))}"
            )

        for condition in condition_order:
            subset = data[data["Condition"] == condition].copy()
            if subset.empty:
                continue
            sample_names = subset["Sample"].astype(str).tolist()
            class_vals = subset["Class I"].astype(float)
            not_vals = subset["Not Class I"].astype(float)
            total_vals = subset["Total"].astype(float)
            lines.append(
                "phospho_coverage_condition|"
                f"name={_safe_context_text(condition)}|sample_count={len(sample_names)}|samples={_safe_context_text(','.join(sample_names))}|"
                f"class_i_mean={_fmt_value(class_vals.mean())}|class_i_median={_fmt_value(class_vals.median())}|class_i_min={_fmt_value(class_vals.min())}|class_i_max={_fmt_value(class_vals.max())}|"
                f"not_class_i_mean={_fmt_value(not_vals.mean())}|not_class_i_median={_fmt_value(not_vals.median())}|not_class_i_min={_fmt_value(not_vals.min())}|not_class_i_max={_fmt_value(not_vals.max())}|"
                f"total_mean={_fmt_value(total_vals.mean())}|total_median={_fmt_value(total_vals.median())}|total_min={_fmt_value(total_vals.min())}|total_max={_fmt_value(total_vals.max())}"
            )
    else:
        required_columns = ["Condition", "classIMean", "classISd", "notClassIMean", "notClassISd"]
        missing_columns = [column for column in required_columns if column not in table.columns]
        if missing_columns:
            lines.append(
                f"phospho_coverage_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
            )
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        data = table.copy()
        data["Condition"] = data["Condition"].astype(str)
        data["classIMean"] = pd.to_numeric(data["classIMean"], errors="coerce")
        data["classISd"] = pd.to_numeric(data["classISd"], errors="coerce")
        data["notClassIMean"] = pd.to_numeric(data["notClassIMean"], errors="coerce")
        data["notClassISd"] = pd.to_numeric(data["notClassISd"], errors="coerce")
        data = data.dropna(subset=["classIMean", "classISd", "notClassIMean", "notClassISd"])
        if data.empty:
            lines.append("phospho_coverage_table|status=empty_after_numeric_filter")
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        lines.append(
            f"phospho_coverage_summary_counts|condition_count={int(data['Condition'].nunique())}"
        )
        for _, row in data.iterrows():
            lines.append(
                "phospho_coverage_condition_summary|"
                f"condition={_safe_context_text(row['Condition'])}|"
                f"class_i_mean={_fmt_value(float(row['classIMean']))}|class_i_sd={_fmt_value(float(row['classISd']))}|"
                f"not_class_i_mean={_fmt_value(float(row['notClassIMean']))}|not_class_i_sd={_fmt_value(float(row['notClassISd']))}"
            )

        try:
            replicate_table = _phospho_tools.phospho_coverage_table(
                include_id=include_id,
                conditions=conditions_arg,
                mode="Normal",
            ).copy()
        except Exception:
            replicate_table = pd.DataFrame()
        if not replicate_table.empty and all(
            column in replicate_table.columns for column in ["Condition", "Sample", "Class I", "Not Class I", "Total"]
        ):
            rep = replicate_table.copy()
            rep["Condition"] = rep["Condition"].astype(str)
            rep["Sample"] = rep["Sample"].astype(str)
            rep["Class I"] = pd.to_numeric(rep["Class I"], errors="coerce")
            rep["Not Class I"] = pd.to_numeric(rep["Not Class I"], errors="coerce")
            rep["Total"] = pd.to_numeric(rep["Total"], errors="coerce")
            rep = rep.dropna(subset=["Class I", "Not Class I", "Total"])
            for condition in _condition_order(rep[["Condition"]].copy()):
                subset = rep[rep["Condition"] == condition].copy()
                if subset.empty:
                    continue
                sample_values = ";".join(
                    [
                        f"{_safe_context_text(row['Sample'])}:class_i={_fmt_value(float(row['Class I']))},not_class_i={_fmt_value(float(row['Not Class I']))},total={_fmt_value(float(row['Total']))}"
                        for _, row in subset.iterrows()
                    ]
                )
                lines.append(
                    "phospho_coverage_summary_points|"
                    f"condition={_safe_context_text(condition)}|n_replicates={int(subset.shape[0])}|values={sample_values}"
                )

    lines.append(
        "phospho_coverage_quality_rule|scope=data_descriptive_with_explicit_class_definition|broader_quality_claims_require_explicit_cutoff_rules_or_multi_cutoff_comparison"
    )
    lines.append(
        "phospho_coverage_color_rule|do_not_report_specific_color_values_unless_user_explicitly_requests_color_mapping"
    )
    return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))


def phospho_phosphosite_distribution_plot(workflow: str = "phosphosite", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    cutoff = _float_from_mode(
        mode_pairs,
        "cutoff",
        default=0.0,
        minimum=0.0,
        maximum=1.0,
    )

    lines: list[str] = []
    lines.append(
        f"phospho_distribution_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphoproteins_and_phosphosites"
    )
    lines.append(
        "phospho_distribution_scope|purpose=show_how_many_phosphosites_are_detected_per_phosphoprotein"
    )
    lines.append(
        "phospho_distribution_function|plot_function=phossite_dist"
    )
    lines.append(
        "phospho_distribution_required_columns|primary=Phosphoprotein_and_site_num|fallback=Protein_group_or_Phosphoprotein_with_PTM_Collapse_key"
    )
    lines.append(
        "phospho_distribution_computation|x_axis=number_of_phosphosites_per_phosphoprotein|y_axis=frequency_number_of_phosphoproteins_with_that_site_count"
    )
    lines.append(
        f"phospho_distribution_cutoff|value={_fmt_value(cutoff)}|type=upper_quantile_filter_on_site_count_distribution"
    )
    if cutoff > 0:
        lines.append(
            "phospho_distribution_cutoff_effect|rule=remove_phosphoproteins_with_site_counts_above_quantile_threshold_q_equal_1_minus_cutoff"
        )
    else:
        lines.append(
            "phospho_distribution_cutoff_effect|rule=no_quantile_filter_applied_full_distribution_retained"
        )

    try:
        table = _phospho_tools.phospho_distribution_table(cutoff=float(cutoff)).copy()
    except Exception as exc:
        lines.append(f"phospho_distribution_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    lines.append(
        f"phospho_distribution_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_distribution_table|status=empty")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))
    if "SiteCount" not in table.columns or "Frequency" not in table.columns:
        lines.append("phospho_distribution_table|status=error|detail=missing_columns:SiteCount,Frequency")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    data = table.copy()
    data["SiteCount"] = pd.to_numeric(data["SiteCount"], errors="coerce")
    data["Frequency"] = pd.to_numeric(data["Frequency"], errors="coerce")
    data = data.dropna(subset=["SiteCount", "Frequency"]).copy()
    if data.empty:
        lines.append("phospho_distribution_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    data["SiteCount"] = data["SiteCount"].astype(int)
    data["Frequency"] = data["Frequency"].astype(int)
    data = data.sort_values("SiteCount").reset_index(drop=True)

    total_phosphoproteins = int(data["Frequency"].sum())
    min_site_count = int(data["SiteCount"].min())
    max_site_count = int(data["SiteCount"].max())
    lines.append(
        f"phospho_distribution_summary|total_phosphoproteins_represented={total_phosphoproteins}|min_site_count={min_site_count}|max_site_count={max_site_count}"
    )

    for _, row in data.iterrows():
        lines.append(
            "phospho_distribution_bin|"
            f"site_count={int(row['SiteCount'])}|frequency={int(row['Frequency'])}"
        )

    lines.append(
        "phospho_distribution_general_pattern|often_right_skewed_with_many_proteins_having_few_sites_and_fewer_proteins_having_many_sites"
    )
    lines.append(
        "phospho_distribution_general_pattern|broad_or_multimodal_patterns_can_reflect_complex_signaling_or_dataset_specific_characteristics"
    )
    lines.append(
        "phospho_distribution_quality_rule|data_specific_frequency_reporting_is_allowed|broader_quality_or_bias_claims_require_explicit_cutoffs_or_comparison_rules"
    )
    lines.append(
        "phospho_distribution_color_rule|do_not_report_color_information_unless_user_explicitly_requests_color_mapping"
    )
    return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))


def phospho_sty_plot(workflow: str = "phosphosite", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)

    lines: list[str] = []
    lines.append(
        f"phospho_sty_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites"
    )
    lines.append(
        "phospho_sty_scope|purpose=report_number_and_percentage_of_phosphosites_on_serine_S_threonine_T_and_tyrosine_Y"
    )
    lines.append(
        "phospho_sty_visual|plot=bar_chart_with_residue_categories_S_T_Y|y_axis=count|labels=percentage_annotations"
    )
    lines.append(
        "phospho_sty_table_definition|columns=Residue_Count_Percentage"
    )

    try:
        table = _phospho_tools.phospho_sty_table().copy()
    except Exception as exc:
        lines.append(f"phospho_sty_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    lines.append(
        f"phospho_sty_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_sty_table|status=empty")
        return _text_payload("phospho_sty_plot", "\n".join(lines))
    if not all(column in table.columns for column in ["Residue", "Count", "Percentage"]):
        lines.append("phospho_sty_table|status=error|detail=missing_columns:Residue,Count,Percentage")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    data = table.copy()
    data["Residue"] = data["Residue"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data["Percentage"] = pd.to_numeric(data["Percentage"], errors="coerce")
    data = data.dropna(subset=["Count", "Percentage"]).copy()
    if data.empty:
        lines.append("phospho_sty_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    data["Count"] = data["Count"].astype(int)
    total_count = int(data["Count"].sum())
    lines.append(f"phospho_sty_total|total_phosphosite_count={total_count}")

    for residue in ["S", "T", "Y"]:
        subset = data[data["Residue"].str.upper() == residue]
        if subset.empty:
            lines.append(f"phospho_sty_row|residue={residue}|count=0|percentage=0")
            continue
        row = subset.iloc[0]
        lines.append(
            "phospho_sty_row|"
            f"residue={residue}|count={int(row['Count'])}|percentage={_fmt_value(float(row['Percentage']))}"
        )

    for _, row in data.iterrows():
        lines.append(
            "phospho_sty_table_row|"
            f"residue={_safe_context_text(row['Residue'])}|count={int(row['Count'])}|percentage={_fmt_value(float(row['Percentage']))}"
        )

    lines.append(
        "phospho_sty_quality_rule|report_exact_counts_and_percentages_from_table|do_not_make_additional_quality_claims_without_explicit_threshold_rules"
    )
    lines.append(
        "phospho_sty_color_rule|do_not_report_color_mapping_unless_user_explicitly_requests_it"
    )
    return _text_payload("phospho_sty_plot", "\n".join(lines))


def phospho_phosprot_regulation_plot(workflow: str = "phosphoprotein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)

    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        default=1.0,
        minimum=0.0,
    )
    test_type = str(mode_pairs.get("testtype", "unpaired")).strip().lower()
    if test_type not in {"paired", "unpaired"}:
        test_type = "unpaired"
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    max_hover_sites = int(
        _float_from_mode(
            mode_pairs,
            "maxhoversites",
            "max_hover_sites",
            default=20.0,
            minimum=1.0,
        )
    )
    show_phosphosites = _bool_from_mode(mode_pairs, "showphosphosites", "show_phosphosites", default=True)

    lines: list[str] = []
    lines.append(
        f"phosprot_regulation_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphoproteins"
    )
    lines.append(
        "phosprot_regulation_scope|purpose=interactive_protein_level_view_of_differential_phosphorylation_aggregated_from_phosphosite_level_information"
    )
    lines.append(
        "phosprot_regulation_function|plot_function=phosprot_regulation"
    )
    lines.append(
        f"phosprot_regulation_parameters|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|test_type={test_type}|use_uncorrected={'true' if use_uncorrected else 'false'}|max_hover_sites={max_hover_sites}|show_phosphosites={'true' if show_phosphosites else 'false'}"
    )
    lines.append(
        "phosprot_regulation_core_steps|step1=compute_phosphosite_log2_fold_changes_between_selected_conditions|step2=perform_statistical_testing_per_site|step3=aggregate_up_and_down_site_contributions_to_protein_level_coordinates"
    )
    lines.append(
        "phosprot_regulation_coordinate_definition|x_axis=absolute_upregulated_sum_log2|y_axis=absolute_downregulated_sum_log2|point=one_protein"
    )
    lines.append(
        "phosprot_regulation_hover_definition|hover_can_include_up_and_down_site_counts_and_site_identifiers_with_optional_truncation"
    )
    lines.append(
        "phosprot_regulation_table_definition|columns=Protein_group_Upregulated_sites_Downregulated_sites_Upregulated_count_Downregulated_count_Upregulated_sum_Downregulated_sum_x_y_color_val"
    )
    lines.append(
        "phosprot_regulation_parameter_note|current_variant_does_not_apply_a_significance_cutoff_to_filter_plot_points_threshold_inputs_are_retained_as_parameters_for_the_underlying_computation_context"
    )
    lines.append(
        "phosprot_regulation_interpretation_scope|supports_identifying_proteins_with_strong_up_or_down_site_contributions_and_assessing_balance_between_up_and_down_signals"
    )
    lines.append(
        "phosprot_regulation_quality_rule|general_not_data_specific_for_this_context_do_not_make_dataset_specific_claims_without_explicit_numeric_output_context"
    )
    lines.append(
        "phosprot_regulation_color_rule|do_not_report_color_gradient_or_mapping_unless_user_explicitly_requests_color_details"
    )

    return _text_payload("phospho_phosprot_regulation_plot", "\n".join(lines))


def single_protein_boxplot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_protein = str(mode_pairs.get("protein", "")).strip()
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    outliers = _bool_from_mode(mode_pairs, "outliers", default=False)
    dots = _bool_from_mode(mode_pairs, "dots", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    legend = _bool_from_mode(mode_pairs, "legend", default=True)

    lines: list[str] = []
    lines.append(
        f"single_protein_boxplot_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|identifier={identifier}"
    )
    lines.append(
        f"single_protein_boxplot_selection|selected_input={_safe_context_text(selected_protein)}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|outliers={'true' if outliers else 'false'}|dots={'true' if dots else 'false'}|header={'true' if header else 'false'}|legend={'true' if legend else 'false'}"
    )
    lines.append(
        "single_protein_boxplot_general|description=distribution_of_log2_transformed_intensity_values_for_one_selected_entity_across_conditions"
    )
    lines.append(
        "single_protein_boxplot_general|per_condition_processing=for_selected_entity_extract_all_intensity_values_from_replicates_in_each_condition"
    )
    lines.append(
        "single_protein_boxplot_general|interpretation_scope=compare_conditions_detect_shifts_outliers_and_distribution_shape_symmetry_spread_skewness"
    )
    lines.append(
        "single_protein_boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=beyond_whiskers"
    )
    lines.append(
        f"single_protein_boxplot_labels|entity_terms={entity_singular}/{entity_plural}"
    )
    lines.append(
        "single_protein_boxplot_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "single_protein_boxplot_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )

    if not selected_protein:
        lines.append("single_protein_boxplot_data|status=incomplete_parameters|detail=protein_not_selected")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_boxplot_table(
            kind,  # type: ignore[arg-type]
            selected_protein,
            selected_conditions,
            identifier=identifier,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_boxplot_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    lines.append(
        f"single_protein_boxplot_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )

    if table.empty:
        lines.append("single_protein_boxplot_table|status=empty")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    data = table.copy()
    ordered_columns: list[str] = [
        column
        for column in ["Condition", "N", "Mean", "Median", "Q1", "Q3", "Min", "Max"]
        if column in data.columns
    ]
    for column in data.columns:
        if column not in ordered_columns:
            ordered_columns.append(str(column))

    lines.append(
        f"single_protein_boxplot_table_columns|values={_safe_context_text(','.join(ordered_columns))}"
    )

    numeric_hints = {"N", "Mean", "Median", "Q1", "Q3", "Min", "Max"}
    for rank, (_, row) in enumerate(data.iterrows(), start=1):
        row_parts = [f"rank={rank}"]
        for column in ordered_columns:
            raw_value = row.get(column)
            key = _safe_context_text(column).replace(" ", "_")
            if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
                row_parts.append(f"{key}=na")
                continue
            if column in numeric_hints:
                try:
                    value_num = float(raw_value)
                    if column == "N":
                        row_parts.append(f"{key}={int(round(value_num))}")
                    else:
                        row_parts.append(f"{key}={_fmt_value(value_num)}")
                    continue
                except Exception:
                    pass
            row_parts.append(f"{key}={_safe_context_text(raw_value)}")
        lines.append("single_protein_boxplot_table_row|" + "|".join(row_parts))

    return _text_payload("single_protein_boxplot", "\n".join(lines))


def single_protein_lineplot(workflow: str = "protein", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_proteins = _split_mode_list(mode_pairs.get("proteins", ""))
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    legend = _bool_from_mode(mode_pairs, "legend", default=True)
    max_item_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxitempreview",
            "max_item_preview",
            default=200.0,
            minimum=20.0,
            maximum=2000.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"single_protein_lineplot_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|identifier={identifier}"
    )
    lines.append(
        f"single_protein_lineplot_selection|proteins={_safe_context_text(','.join(selected_proteins)) if selected_proteins else 'none_selected'}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|legend={'true' if legend else 'false'}"
    )
    lines.append(
        "single_protein_lineplot_context_policy|data_volume_control=use_per_entity_min_max_mean_median_only_no_row_level_dump"
    )
    lines.append(
        "single_protein_lineplot_general|description=each_selected_entity_is_plotted_as_an_independent_trajectory_across_ordered_samples_and_conditions"
    )
    lines.append(
        "single_protein_lineplot_axes|x_axis=samples|y_axis=log2_intensity|conditions_define_sample_grouping_and_ordering"
    )
    lines.append(
        "single_protein_lineplot_general|sample_ordering=samples_follow_user_selected_condition_sequence_for_consistent_experimental_alignment"
    )
    lines.append(
        "single_protein_lineplot_general|missing_values=NA_markers_are_omitted_while_lines_remain_connected_across_missing_positions"
    )
    lines.append(
        "single_protein_lineplot_general|interpretation_scope=evaluate_condition_or_temporal_trends_replicate_variation_and_sample_level_shifts"
    )
    lines.append(
        f"single_protein_lineplot_labels|entity_terms={entity_singular}/{entity_plural}"
    )
    lines.append(
        "single_protein_lineplot_quality_rule|scope=general_not_data_specific|assessment_requires_defined_thresholds_or_cutoffs=true"
    )
    lines.append(
        "single_protein_lineplot_quality_rule|if_no_cutoffs_defined=do_not_make_quality_claims_for_current_dataset"
    )

    if not selected_proteins:
        lines.append("single_protein_lineplot_data|status=incomplete_parameters|detail=proteins_not_selected")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_lineplot_table(
            kind,  # type: ignore[arg-type]
            selected_proteins,
            selected_conditions,
            include_id=include_id,
            identifier=identifier,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_lineplot_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    lines.append(
        f"single_protein_lineplot_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("single_protein_lineplot_table|status=empty")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    data = table.copy()
    required_columns = ["Feature", "Sample", "Condition", "Value"]
    missing_columns = [column for column in required_columns if column not in data.columns]
    if missing_columns:
        lines.append(
            f"single_protein_lineplot_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
        )
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    data["Feature"] = data["Feature"].astype(str)
    data["Sample"] = data["Sample"].astype(str)
    data["Condition"] = data["Condition"].astype(str)
    data["Value"] = pd.to_numeric(data["Value"], errors="coerce")
    data = data.dropna(subset=["Value"]).copy()

    if data.empty:
        lines.append("single_protein_lineplot_table|status=empty_after_numeric_filter")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    lines.append(
        "single_protein_lineplot_table_representation|mode=aggregated_entity_statistics_only|source=single_protein_lineplot_table"
    )

    entity_count = int(data["Feature"].nunique())
    condition_count = int(data["Condition"].nunique())
    lines.append(
        f"single_protein_lineplot_counts|entity_count={entity_count}|condition_count={condition_count}"
    )

    feature_values = data["Feature"].drop_duplicates().tolist()
    feature_preview, feature_truncated = _preview_items(feature_values, max_item_preview)
    selected_preview, selected_truncated = _preview_items(selected_proteins, max_item_preview)
    lines.append(
        f"single_protein_lineplot_selected_entities|requested_count={len(selected_proteins)}|requested_preview_count={len(selected_preview)}|requested_preview_truncated={'true' if selected_truncated else 'false'}|requested_values={_safe_context_text(';'.join(selected_preview))}"
    )
    lines.append(
        f"single_protein_lineplot_entities|count={entity_count}|preview_count={len(feature_preview)}|preview_truncated={'true' if feature_truncated else 'false'}|values={_safe_context_text(';'.join(feature_preview))}"
    )
    lines.append(
        "single_protein_lineplot_focus|answer_entity_questions_using_only_per_entity_min_max_mean_median_and_plot_structure_explanation"
    )

    observed_conditions = data["Condition"].drop_duplicates().tolist()
    condition_preview, condition_truncated = _preview_items(observed_conditions, max_item_preview)
    lines.append(
        f"single_protein_lineplot_conditions|count={condition_count}|preview_count={len(condition_preview)}|preview_truncated={'true' if condition_truncated else 'false'}|values={_safe_context_text(';'.join(condition_preview))}"
    )

    for feature in feature_values:
        feature_data = data[data["Feature"] == feature].copy()
        if feature_data.empty:
            continue
        values_all = feature_data["Value"].astype(float)
        lines.append(
            "single_protein_lineplot_entity_summary|"
            f"entity={_safe_context_text(feature)}|n_values={int(values_all.shape[0])}|"
            f"mean={_fmt_value(values_all.mean())}|median={_fmt_value(values_all.median())}|"
            f"min={_fmt_value(values_all.min())}|max={_fmt_value(values_all.max())}"
        )
    lines.append(
        f"single_protein_lineplot_final_entities|values={_safe_context_text(';'.join(feature_values))}"
    )

    return _text_payload("single_protein_lineplot", "\n".join(lines))


def single_protein_phosphosite_heatmap(workflow: str = "phosphosite", mode: str | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _parse_mode_pairs(mode)
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_protein = str(mode_pairs.get("protein", "")).strip()
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    filter_m1 = _bool_from_mode(mode_pairs, "filterm1", "filter_m1", default=True)
    cluster_rows = _bool_from_mode(mode_pairs, "clusterrows", "cluster_rows", default=False)
    cluster_cols = _bool_from_mode(mode_pairs, "clustercols", "cluster_cols", default=False)
    value_type = str(mode_pairs.get("valuetype", mode_pairs.get("value_type", "log2"))).strip().lower()
    if value_type not in {"log2", "z"}:
        value_type = "log2"
    max_site_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxsitepreview",
            "max_site_preview",
            default=500.0,
            minimum=20.0,
            maximum=5000.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"single_protein_heatmap_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites|identifier={identifier}"
    )
    lines.append(
        f"single_protein_heatmap_selection|protein={_safe_context_text(selected_protein)}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|filter_m1={'true' if filter_m1 else 'false'}|cluster_rows={'true' if cluster_rows else 'false'}|cluster_cols={'true' if cluster_cols else 'false'}|value_type={value_type}"
    )
    lines.append(
        "single_protein_heatmap_visual|x_axis=samples|y_axis=phosphosites_for_selected_protein|cells=transformed_intensity_values"
    )
    lines.append(
        "single_protein_heatmap_general|description=heatmap_shows_selected_protein_with_site_rows_listed_in_context_across_samples"
    )
    lines.append(
        "single_protein_heatmap_response_rule|if_exact_site_names_are_available_use_them_directly_and_do_not_use_placeholder_patterns_like_S_xxx_T_xxx_Y_xxx"
    )
    lines.append(
        "single_protein_heatmap_quality_rule|scope=structure_only_not_data_specific|do_not_make_dataset_quality_claims_without_explicit_cutoffs"
    )

    if not selected_protein:
        lines.append("single_protein_heatmap_data|status=incomplete_parameters|detail=protein_not_selected")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_heatmap_table(
            "phospho",  # type: ignore[arg-type]
            selected_protein,
            selected_conditions,
            identifier=identifier,
            include_id=include_id,
            filter_m1=filter_m1,
            cluster_rows=cluster_rows,
            cluster_cols=cluster_cols,
            value_type=value_type,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    lines.append(
        f"single_protein_heatmap_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("single_protein_heatmap_table|status=empty")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    site_column = "Site" if "Site" in table.columns else str(table.columns[0])
    sample_columns = [str(column) for column in table.columns if str(column) != site_column]
    sites = table[site_column].astype(str).dropna().drop_duplicates().tolist()
    site_preview, site_truncated = _preview_items(sites, max_site_preview)

    lines.append(
        f"single_protein_heatmap_structure|selected_protein={_safe_context_text(selected_protein)}|site_column={_safe_context_text(site_column)}|site_count={len(sites)}|sample_count={len(sample_columns)}"
    )
    lines.append(
        f"single_protein_heatmap_sites|count={len(sites)}|preview_count={len(site_preview)}|preview_truncated={'true' if site_truncated else 'false'}|values={_safe_context_text(';'.join(site_preview))}"
    )
    if len(sites) == 1:
        lines.append(
            f"single_protein_heatmap_single_site|site={_safe_context_text(sites[0])}"
        )
    else:
        lines.append(
            f"single_protein_heatmap_exact_sites|values={_safe_context_text(';'.join(sites))}"
        )
    lines.append(
        f"single_protein_heatmap_samples|count={len(sample_columns)}|values={_safe_context_text(';'.join(sample_columns))}"
    )

    return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))


__all__ = [
    "general_proteomics_context",
    "completeness_missing_value_plot",
    "completeness_missing_value_heatmap",
    "completeness_missing_value_tables",
    "stats_volcano_plot",
    "stats_gsea_plot",
    "stats_pathway_heatmap_plot",
    "comparison_pearson_correlation",
    "comparison_venn_diagram",
    "phospho_phosphosite_plot",
    "phospho_phosphosite_coverage_plot",
    "phospho_phosphosite_distribution_plot",
    "phospho_sty_plot",
    "phospho_phosprot_regulation_plot",
    "single_protein_boxplot",
    "single_protein_lineplot",
    "single_protein_phosphosite_heatmap",
    "qc_coverage_plot",
    "qc_histogram_intensity",
    "qc_boxplot_intensity",
    "qc_cov_plot",
    "qc_pca_plot",
    "qc_abundance_plot",
    "qc_correlation_plot",
]
