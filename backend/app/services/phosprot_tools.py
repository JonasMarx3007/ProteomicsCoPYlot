from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    PhosprotAggregationMode,
    PhosprotAggregationSource,
)
from app.services.annotation_store import get_annotation, save_annotation
from app.services.dataset_store import save_table_dataset
from app.services.functions import (
    filter_data,
    impute_values_with_diagnostics,
    inverse_log2_transform_data,
    log2_transform_data,
    use_existing_log2_data,
)

_REQUIRED_PHOSPHO_COLUMNS = [
    "UPD_seq",
    "PTM_localization",
    "Protein_group",
    "Gene_group",
    "PTM_Collapse_key",
]


def _collapse_strings(series: pd.Series) -> str:
    return ";".join(sorted(set(series.dropna().astype(str))))


def _concat_strings(series: pd.Series) -> str:
    return ";".join(series.dropna().astype(str))


def _sum_propagate_nan(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any():
        return float("nan")
    return float(values.sum())


def _sum_ignore_nan(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce")
    return float(values.fillna(0).sum())


def _mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce")
    return float(values.mean())


def transform_phosprot(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    mode: PhosprotAggregationMode = "sum_mean_impute",
) -> pd.DataFrame:
    missing = [column for column in _REQUIRED_PHOSPHO_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in phospho dataset: {missing}")

    if not {"condition", "sample"}.issubset(metadata.columns):
        raise ValueError("Phospho metadata must contain 'sample' and 'condition' columns.")

    sample_columns = [str(value) for value in metadata["sample"].tolist()]
    missing_samples = [sample for sample in sample_columns if sample not in data.columns]
    if missing_samples:
        raise ValueError(
            f"Phospho metadata contains sample columns not present in phospho data: {missing_samples}"
        )

    gene_map = data.groupby("Protein_group")["Gene_group"].nunique(dropna=True)
    invalid = gene_map[gene_map > 1]
    if not invalid.empty:
        raise ValueError(
            "Each Protein_group must map to exactly one Gene_group. "
            f"Violations: {list(invalid.index)}"
        )

    if mode == "sum_mean_impute":
        frame = data.copy()
        for condition in metadata["condition"].dropna().astype(str).unique().tolist():
            condition_samples = metadata.loc[
                metadata["condition"].astype(str) == condition, "sample"
            ].astype(str).tolist()
            condition_samples = [sample for sample in condition_samples if sample in sample_columns]
            if not condition_samples:
                continue
            means = frame[condition_samples].apply(pd.to_numeric, errors="coerce").mean()
            frame[condition_samples] = frame[condition_samples].apply(
                pd.to_numeric, errors="coerce"
            ).fillna(means)
        source = frame
        summarizer = lambda values: pd.to_numeric(values, errors="coerce").sum()
    elif mode == "sum_propagate_na":
        source = data
        summarizer = _sum_propagate_nan
    elif mode == "sum_ignore_na":
        source = data
        summarizer = _sum_ignore_nan
    elif mode == "mean":
        source = data
        summarizer = _mean
    else:
        raise ValueError(
            "mode must be one of: sum_mean_impute, sum_propagate_na, sum_ignore_na, mean."
        )

    aggregation = {
        "Gene_group": "first",
        "PTM_Collapse_key": _collapse_strings,
        "PTM_localization": _concat_strings,
        "UPD_seq": _collapse_strings,
        **{column: summarizer for column in sample_columns},
    }
    phosprot = source.groupby("Protein_group", as_index=False).agg(aggregation)

    site_counts = source.groupby("Protein_group").size().reset_index(name="site_num")
    phosprot = phosprot.merge(site_counts, on="Protein_group", how="left")
    phosprot = phosprot.rename(
        columns={
            "PTM_Collapse_key": "PTM_Collapse_keys",
            "Protein_group": "Phosphoprotein",
        }
    )

    columns = phosprot.columns.tolist()
    columns.remove("site_num")
    insert_position = columns.index("Gene_group") + 1
    columns.insert(insert_position, "site_num")
    return phosprot[columns]


def _shared_phospho_annotation():
    phospho_annotation = get_annotation("phospho")
    if phospho_annotation is None or phospho_annotation.metadata.empty:
        raise ValueError(
            "Phospho annotation is required first. Generate phospho annotation to share metadata with phosphoprotein."
        )
    return phospho_annotation


def _shared_filter_config(phospho_annotation) -> AnnotationFilterConfig:
    return phospho_annotation.filter_config or AnnotationFilterConfig()


def _store_phosprot_annotation(
    frame: pd.DataFrame,
    is_log2_transformed: bool,
    warning_prefix: str,
) -> object:
    phospho_annotation = _shared_phospho_annotation()
    metadata = phospho_annotation.metadata.copy()
    sample_columns = [sample for sample in metadata["sample"].astype(str).tolist() if sample in frame.columns]
    if not sample_columns:
        raise ValueError(
            "Shared phospho metadata does not match sample columns in phosphoprotein dataset."
        )
    metadata = metadata[metadata["sample"].astype(str).isin(sample_columns)].copy()

    if is_log2_transformed:
        log2_data = use_existing_log2_data(frame, sample_columns)
    else:
        log2_data = log2_transform_data(frame, sample_columns)

    filter_config = _shared_filter_config(phospho_annotation)
    filtered_data = filter_data(
        log2_data,
        metadata,
        min_present=filter_config.minPresent,
        mode=filter_config.mode,
    )

    warnings: list[str] = [
        f"{warning_prefix} Metadata and filter settings were inherited from phospho annotation."
    ]
    return save_annotation(
        kind="phosprot",
        source_data=frame,
        metadata=metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=is_log2_transformed,
        metadata_source="shared_phospho",
        filter_config=filter_config,
        auto_detected=False,
        warnings=warnings,
    )


def _impute_phospho_source(
    source: pd.DataFrame,
    *,
    sample_columns: list[str],
    phospho_annotation,
) -> tuple[pd.DataFrame, str]:
    imputation = getattr(phospho_annotation, "imputation", None)
    q_value = 0.01
    adjust_std = 1.0
    seed = 1337
    sample_wise = False
    config_label = "default settings"
    if imputation is not None and str(getattr(imputation, "mode", "none")) != "none":
        q_value = (
            float(imputation.qValue)
            if getattr(imputation, "qValue", None) is not None
            else q_value
        )
        adjust_std = (
            float(imputation.adjustStd)
            if getattr(imputation, "adjustStd", None) is not None
            else adjust_std
        )
        seed = (
            int(imputation.seed)
            if getattr(imputation, "seed", None) is not None
            else seed
        )
        sample_wise = (
            bool(imputation.sampleWise)
            if getattr(imputation, "sampleWise", None) is not None
            else sample_wise
        )
        config_label = (
            f"stored imputation settings (q={q_value}, adjustStd={adjust_std}, "
            f"seed={seed}, sampleWise={sample_wise})"
        )

    diagnostics = impute_values_with_diagnostics(
        data=source,
        sample_columns=sample_columns,
        q=q_value,
        adj_std=adjust_std,
        seed=seed,
        sample_wise=sample_wise,
    )
    return diagnostics.imputed_data, config_label


def aggregate_from_phospho(
    mode: PhosprotAggregationMode,
    source: PhosprotAggregationSource = "non_imputed",
) -> object:
    phospho_annotation = _shared_phospho_annotation()
    source_data = phospho_annotation.source_data.copy()
    sample_columns = phospho_annotation.metadata["sample"].astype(str).tolist()

    if phospho_annotation.is_log2_transformed:
        source_data = inverse_log2_transform_data(source_data, sample_columns)

    source_label = "non-imputed phospho data"
    if source == "imputed":
        source_data, imputation_label = _impute_phospho_source(
            source_data,
            sample_columns=sample_columns,
            phospho_annotation=phospho_annotation,
        )
        source_label = f"imputed phospho data ({imputation_label})"

    phosprot = transform_phosprot(source_data, phospho_annotation.metadata, mode=mode)
    save_table_dataset(
        filename=f"phosprot_aggregated_{source}_{mode}.csv",
        kind="phosprot",
        frame=phosprot,
    )
    return _store_phosprot_annotation(
        frame=phosprot,
        is_log2_transformed=False,
        warning_prefix=(
            "Phosphoprotein dataset was aggregated from "
            f"{source_label} using aggregation mode '{mode}'."
        ),
    )


def upload_phosprot(frame: pd.DataFrame, filename: str, is_log2_transformed: bool) -> object:
    _shared_phospho_annotation()
    save_table_dataset(filename=filename, kind="phosprot", frame=frame)
    return _store_phosprot_annotation(
        frame=frame,
        is_log2_transformed=is_log2_transformed,
        warning_prefix="Phosphoprotein dataset was uploaded manually.",
    )
