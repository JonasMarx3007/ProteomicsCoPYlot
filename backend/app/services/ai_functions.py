from __future__ import annotations

from typing import Any

import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services import plot_images as _plot_images
from app.services import table_functions as _table_functions
from app.services.data_tools import get_condition_palette_config
from app.services.peptide_tools import _extract_id_or_number as _extract_peptide_id
from app.services.peptide_tools import get_peptide_frame

_GENERAL_PROTEOMICS_CONTEXT_TEXT = (
    "This application analyzes proteomics data. "
    "Treat this as mass-spectrometry proteomics analysis, not RNA-seq or transcriptomics. "
    "Focus on data analysis and statistical interpretation. "
    "Be workflow-sensitive: use protein terms for protein workflows, phosphosite terms for phosphosite workflows, "
    "phosphoprotein terms for phosphoprotein workflows, and peptide terms for peptide workflows. "
    "Unless explicitly stated otherwise, assume quantitative values are already collapsed to protein-level values. "
    "Do not discuss instrumentation or acquisition settings unless the user explicitly asks for them."
)

_WORKFLOW_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phosphosite": ("phosphosite", "phosphosites"),
    "phosphoprotein": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
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


def _workflow_kind(workflow: str) -> AnnotationKind:
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    return "protein"


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


def _condition_palette_for_workflow(workflow: str) -> dict[str, str]:
    kind = _workflow_kind(workflow)
    if workflow == "peptide":
        kind = "protein"
    try:
        response = get_condition_palette_config(kind)
        return {str(key): str(value) for key, value in response.palette.items()}
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


def general_proteomics_context() -> dict[str, Any]:
    return _text_payload("general_proteomics_context", _GENERAL_PROTEOMICS_CONTEXT_TEXT)


def qc_coverage_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    try:
        if workflow_key == "peptide":
            rows, total_features = _coverage_rows_from_peptide()
        else:
            rows, total_features = _coverage_rows_from_wide(_workflow_kind(workflow_key))
        palette = _condition_palette_for_workflow(workflow_key)
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


__all__ = ["general_proteomics_context", "qc_coverage_plot"]
