from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.functions import inverse_log2_transform_data


def _extract_id_or_number(sample: str) -> str:
    match = re.search(r"\d+|[A-Za-z]+", str(sample))
    return match.group(0) if match else str(sample)


def _metadata_for_kind(kind: AnnotationKind, frame: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        meta = meta[meta["sample"].isin(sample_columns)]
        if not meta.empty:
            meta = meta.drop_duplicates(subset=["sample"])
            meta = meta.set_index("sample").reindex(sample_columns).reset_index()
            meta["condition"] = meta["condition"].fillna("sample").astype(str)
            return meta
    return pd.DataFrame({"sample": sample_columns, "condition": ["sample"] * len(sample_columns)})


def _coverage_frame(kind: AnnotationKind) -> pd.DataFrame:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.source_data.empty:
        return annotation.source_data.copy()
    return raw


def _log2_qc_frame(kind: AnnotationKind) -> pd.DataFrame:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.log2_data.empty:
        return annotation.log2_data.copy()
    if annotation is not None and not annotation.filtered_data.empty:
        return annotation.filtered_data.copy()
    return raw


def _verification_frame(kind: AnnotationKind) -> pd.DataFrame:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is None:
        return raw
    sample_columns = [c for c in annotation.metadata["sample"].tolist() if c in annotation.log2_data.columns]
    if not sample_columns:
        return raw
    if annotation.is_log2_transformed:
        return inverse_log2_transform_data(annotation.log2_data, sample_columns)
    return annotation.source_data.copy()


def prepare_coverage_df(data: pd.DataFrame, meta: pd.DataFrame, name: bool = False) -> pd.DataFrame:
    data = data.replace(0, np.nan).copy()
    meta = meta.copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["new_sample"] = meta.groupby("condition").cumcount() + 1
    meta["new_sample"] = meta.apply(lambda row: f"{row['condition']}_{row['new_sample']}", axis=1)

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data_filtered = data.rename(columns=rename_dict)
    annotated_columns = [c for c in meta["new_sample"].tolist() if c in data_filtered.columns]
    if not annotated_columns:
        return pd.DataFrame(columns=["Sample", "Number"])

    data_filtered = data_filtered[annotated_columns].notna().astype(int)
    data_long = data_filtered.reset_index(drop=True).melt(var_name="Sample", value_name="Number")

    if name:
        data_annotated = data_long.merge(
            meta[["sample", "new_sample"]],
            left_on="Sample",
            right_on="new_sample",
            how="left",
        )
        summary = (
            data_annotated.groupby(["Sample", "sample"], as_index=False)["Number"]
            .sum()
            .rename(columns={"sample": "Original_Name"})
        )
        summary = summary[["Sample", "Number", "Original_Name"]]
    else:
        summary = data_long.groupby("Sample", as_index=False)["Number"].sum()

    summary["Sample"] = pd.Categorical(summary["Sample"], categories=annotated_columns, ordered=True)
    summary = summary.sort_values(["Sample"])

    if "ProteinNames" in data.columns:
        total_value = int(len(data["ProteinNames"]))
    elif "PTM_Collapse_key" in data.columns:
        total_value = int(len(data["PTM_Collapse_key"]))
    elif "Phosphoprotein" in data.columns:
        total_value = int(len(data["Phosphoprotein"]))
    else:
        total_value = int(data_filtered.shape[0])

    all_samples_row: dict[str, object] = {"Sample": "All samples", "Number": total_value}
    if name:
        all_samples_row["Original_Name"] = ""
    summary = pd.concat([summary, pd.DataFrame([all_samples_row])], ignore_index=True)
    return summary


def prepare_coverage_summary_df(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    data = data.replace(0, np.nan).copy()
    meta = meta.copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    condition_order = meta["condition"].dropna().unique().tolist()
    meta["id"] = meta["sample"].apply(_extract_id_or_number)
    meta["new_sample"] = meta.groupby("condition").cumcount() + 1
    meta["new_sample"] = meta.apply(
        lambda row: f"{row['condition']}_{row['new_sample']}\n({row['id']})",
        axis=1,
    )

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data_filtered = data.rename(columns=rename_dict)
    annotated_cols = [c for c in meta["new_sample"].tolist() if c in data_filtered.columns]
    if not annotated_cols:
        return pd.DataFrame(columns=["condition", "mean", "min", "max", "sd"])

    data_binary = data_filtered[annotated_cols].notna().astype(int)
    melted = data_binary.melt(var_name="Sample", value_name="Value")
    data_annotated = melted.merge(meta[["new_sample", "condition"]], left_on="Sample", right_on="new_sample")

    sample_summary = (
        data_annotated.groupby("Sample", sort=False)
        .agg(Value=("Value", "sum"), condition=("condition", "first"))
        .reset_index()
    )
    condition_summary = (
        sample_summary.groupby("condition", sort=False)
        .agg(mean=("Value", "mean"), min=("Value", "min"), max=("Value", "max"), sd=("Value", "std"))
        .reset_index()
    )

    numeric_cols = ["mean", "min", "max", "sd"]
    condition_summary[numeric_cols] = condition_summary[numeric_cols].round(2)
    if condition_order:
        condition_summary["condition"] = pd.Categorical(
            condition_summary["condition"],
            categories=condition_order,
            ordered=True,
        )
        condition_summary = condition_summary.sort_values("condition").reset_index(drop=True)
        condition_summary["condition"] = condition_summary["condition"].astype(str)
    return condition_summary


def prepare_boxplot_df(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    conditions_order = meta["condition"].unique()
    summary_list: list[dict[str, object]] = []
    for condition in conditions_order:
        columns = meta.loc[meta["condition"] == condition, "sample"].tolist()
        values = data[columns].mean(axis=1, skipna=True).values
        values = values[np.isfinite(values)]
        if len(values) == 0:
            continue

        q1 = float(np.percentile(values, 25))
        median = float(np.median(values))
        q3 = float(np.percentile(values, 75))
        iqr = q3 - q1
        lower_whisker = float(max(np.min(values), q1 - 1.5 * iqr))
        upper_whisker = float(min(np.max(values), q3 + 1.5 * iqr))
        mean = float(np.mean(values))

        summary_list.append(
            {
                "Condition": str(condition),
                "mean": round(mean, 2),
                "median": round(median, 2),
                "Q1": round(q1, 2),
                "Q3": round(q3, 2),
                "lower_whisker": round(lower_whisker, 2),
                "upper_whisker": round(upper_whisker, 2),
            }
        )

    summary_df = pd.DataFrame(summary_list)
    if summary_df.empty:
        return summary_df
    return summary_df.reset_index(drop=True)


def prepare_boxplot_single_df(data: pd.DataFrame, meta: pd.DataFrame, name: bool = False) -> pd.DataFrame:
    meta = meta.copy()
    meta["id"] = meta["sample"].apply(_extract_id_or_number)
    meta["new_sample"] = meta.groupby("condition").cumcount() + 1
    meta["new_sample"] = meta.apply(lambda row: f"{row['condition']}_{row['new_sample']}", axis=1)

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data_renamed = data.rename(columns=rename_dict)
    samples = [s for s in meta["new_sample"].tolist() if s in data_renamed.columns]

    summary_list: list[dict[str, object]] = []
    for sample in samples:
        values = data_renamed[sample].values
        values = values[np.isfinite(values)]
        if len(values) == 0:
            continue

        q1 = float(np.percentile(values, 25))
        median = float(np.median(values))
        q3 = float(np.percentile(values, 75))
        iqr = q3 - q1
        lower_whisker = float(max(np.min(values), q1 - 1.5 * iqr))
        upper_whisker = float(min(np.max(values), q3 + 1.5 * iqr))
        mean = float(np.mean(values))

        row_dict: dict[str, object] = {
            "Sample": sample,
            "mean": round(mean, 2),
            "median": round(median, 2),
            "Q1": round(q1, 2),
            "Q3": round(q3, 2),
            "lower_whisker": round(lower_whisker, 2),
            "upper_whisker": round(upper_whisker, 2),
        }
        if name:
            original_name = meta.loc[meta["new_sample"] == sample, "sample"].values[0]
            row_dict["Original_Name"] = str(original_name)
        summary_list.append(row_dict)

    summary_df = pd.DataFrame(summary_list)
    if summary_df.empty:
        return summary_df
    return summary_df.reset_index(drop=True)


def prepare_cov_df(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    conditions = meta["condition"].unique()
    summary_list: list[dict[str, object]] = []
    for cond in conditions:
        cols = meta.loc[meta["condition"] == cond, "sample"].tolist()
        if len(cols) < 2:
            continue
        subset = data[cols]
        means = subset.mean(axis=1, skipna=True)
        sds = subset.std(axis=1, skipna=True)
        cv = (sds / means) * 100
        cv = cv[np.isfinite(cv)]
        if len(cv) == 0:
            continue

        q1 = float(np.percentile(cv, 25))
        median = float(np.median(cv))
        q3 = float(np.percentile(cv, 75))
        iqr = q3 - q1
        lower_whisker = float(max(np.min(cv), q1 - 1.5 * iqr))
        upper_whisker = float(min(np.max(cv), q3 + 1.5 * iqr))
        mean_cv = float(np.mean(cv))

        summary_list.append(
            {
                "Condition": str(cond),
                "mean": round(mean_cv, 2),
                "median": round(median, 2),
                "Q1": round(q1, 2),
                "Q3": round(q3, 2),
                "lower_whisker": round(lower_whisker, 2),
                "upper_whisker": round(upper_whisker, 2),
            }
        )

    summary_df = pd.DataFrame(summary_list)
    if summary_df.empty:
        return summary_df
    return summary_df.reset_index(drop=True)


def qc_coverage_table(kind: AnnotationKind, summary: bool = False) -> pd.DataFrame:
    frame = _coverage_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    meta = _metadata_for_kind(kind, frame, sample_columns)
    if summary:
        return prepare_coverage_summary_df(frame, meta)
    return prepare_coverage_df(frame, meta)


def qc_boxplot_table(kind: AnnotationKind, mode: str = "Mean") -> pd.DataFrame:
    frame = _log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    if str(mode).lower() == "single":
        return prepare_boxplot_single_df(numeric, meta)
    return prepare_boxplot_df(numeric, meta)


def qc_cv_table(kind: AnnotationKind) -> pd.DataFrame:
    frame = _verification_frame(kind).replace(0, np.nan)
    sample_columns = _get_sample_columns(kind, frame)
    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    return prepare_cov_df(numeric, meta)
