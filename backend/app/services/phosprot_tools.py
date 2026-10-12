from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

import numpy as np
import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    PhosprotAggregationMode,
    PhosprotAggregationSource,
    phosprot_filter_config,
)
from app.services.annotation_store import StoredAnnotation, clear_annotation, get_annotation, store_prepared_annotation
from app.services.annotation_processor import resolve_log2_state
from app.services.dataset_store import save_table_dataset
from app.services.phospho_localization import localization_cutoff_description, validate_localization_cutoff
from app.services.functions import (
    filter_localization,
    choose_best_source,
    filter_data,
    inverse_log2_transform_data,
    log2_transform_data,
    raw_zero_to_nan,
    use_existing_log2_data,
)
from app.services.analysis_matrix import _select_matrix_all_rows

_REQUIRED_PHOSPHO_COLUMNS = [
    "UPD_seq",
    "PTM_localization",
    "Protein_group",
    "Gene_group",
    "PTM_Collapse_key",
]

ROBUST_SITE_MIN_FRACTION = 0.5


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
    return float(values.sum(min_count=1))


def _mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce")
    return float(values.mean())


def _clean_numeric_sample_columns(
    data: pd.DataFrame,
    sample_columns: list[str],
) -> pd.DataFrame:
    """Copy a phosphosite frame and retain only finite numeric sample values.

    Annotation columns and measured zeroes are preserved. Non-numeric values,
    positive/negative infinity, and existing missing values become ``NaN``.
    Keeping this boundary shared prevents aggregation and coverage diagnostics
    from silently using different definitions of an observed phosphosite.
    """
    cleaned = data.copy()
    cleaned[sample_columns] = (
        cleaned[sample_columns]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    return cleaned


def _site_diagnostics(
    data: pd.DataFrame,
    sample_columns: list[str],
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame]:
    """Return fixed eligible sites plus explicit per-sample coverage diagnostics."""
    numeric = _clean_numeric_sample_columns(data, sample_columns)[sample_columns]
    eligible_mask = numeric.notna().any(axis=1)
    eligible = data.loc[eligible_mask].copy()
    groups = data["Protein_group"].astype(str)
    group_order = groups.drop_duplicates().tolist()

    total = groups.value_counts(sort=False).reindex(group_order, fill_value=0).astype(int)
    eligible_groups = groups.loc[eligible_mask]
    eligible_count = (
        eligible_groups.value_counts(sort=False).reindex(group_order, fill_value=0).astype(int)
    )
    observed = (
        numeric.loc[eligible_mask]
        .notna()
        .astype(int)
        .assign(Protein_group=eligible_groups.to_numpy())
        .groupby("Protein_group", sort=False)[sample_columns]
        .sum()
        .reindex(group_order, fill_value=0)
        .astype(int)
    )

    diagnostics = pd.DataFrame(
        {
            "Protein_group": group_order,
            "site_num": total.to_numpy(),
            "site_num_eligible": eligible_count.to_numpy(),
        }
    )
    denominator = eligible_count.replace(0, np.nan).astype(float)
    fractions = observed.div(denominator, axis=0)
    diagnostics["site_observed_min"] = observed.min(axis=1).to_numpy(dtype=int)
    diagnostics["site_observed_mean"] = observed.mean(axis=1).to_numpy(dtype=float)
    diagnostics["site_coverage_min"] = fractions.min(axis=1).to_numpy(dtype=float)
    diagnostics["site_coverage_mean"] = fractions.mean(axis=1).to_numpy(dtype=float)
    complete = observed.eq(eligible_count, axis=0)
    complete.loc[eligible_count == 0, :] = False
    diagnostics["site_complete_samples"] = complete.sum(axis=1).to_numpy(dtype=int)
    for sample in sample_columns:
        diagnostics[f"site_observed__{sample}"] = observed[sample].to_numpy(dtype=int)
        diagnostics[f"site_coverage__{sample}"] = fractions[sample].to_numpy(dtype=float)
    return diagnostics, eligible_count, eligible, observed


def transform_phosprot(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    mode: PhosprotAggregationMode = "robust_site_median",
    data_scale: Literal["linear", "log2"] = "linear",
    coverage_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Collapse phosphosites to one phosphoprotein value per sample.

    ``robust_site_median`` centres every site across samples on log2 scale and
    takes the within-protein median when at least half of the fixed eligible
    site set has finite supplied values (including imputed values).
    The other modes aggregate original-scale values.
    ``data_scale`` states the supplied measurement scale so callers never rely
    on magnitude-based scale guessing. ``coverage_data`` may supply the aligned
    pre-imputation matrix so diagnostics describe real observations rather than
    filled values. It fixes site eligibility, not per-sample value availability.
    ``site_observed__`` retains overall coverage; ``site_measured__`` and
    ``site_supplied__`` count only the sites used by the selected collapse.
    """
    missing = [column for column in _REQUIRED_PHOSPHO_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in phospho dataset: {missing}")

    if not {"condition", "sample"}.issubset(metadata.columns):
        raise ValueError("Phospho metadata must contain 'sample' and 'condition' columns.")

    sample_columns = [str(value) for value in metadata["sample"].tolist()]
    if not sample_columns:
        raise ValueError("Phospho metadata must contain at least one sample.")
    duplicate_samples = sorted(
        {sample for sample in sample_columns if sample_columns.count(sample) > 1}
    )
    if duplicate_samples:
        raise ValueError(f"Phospho metadata contains duplicate samples: {duplicate_samples}")
    missing_samples = [sample for sample in sample_columns if sample not in data.columns]
    if missing_samples:
        raise ValueError(
            f"Phospho metadata contains sample columns not present in phospho data: {missing_samples}"
        )

    resolved_scale = str(data_scale).strip().lower()
    if resolved_scale not in {"linear", "log2"}:
        raise ValueError("data_scale must be 'linear' or 'log2'.")

    data = data.copy()
    data["Protein_group"] = data["Protein_group"].astype(str)
    if coverage_data is not None:
        coverage_data = coverage_data.copy()
        if not coverage_data.index.equals(data.index):
            raise ValueError("coverage_data must have exactly the same row index as data.")
        missing_coverage = [
            column
            for column in ["Protein_group", *sample_columns]
            if column not in coverage_data.columns
        ]
        if missing_coverage:
            raise ValueError(f"coverage_data is missing required columns: {missing_coverage}")
        coverage_data["Protein_group"] = coverage_data["Protein_group"].astype(str)
        if not coverage_data["Protein_group"].equals(data["Protein_group"]):
            raise ValueError("coverage_data Protein_group values must align exactly with data.")

    gene_map = data.groupby("Protein_group")["Gene_group"].nunique(dropna=True)
    invalid = gene_map[gene_map > 1]
    if not invalid.empty:
        raise ValueError(
            "Each Protein_group must map to exactly one Gene_group. "
            f"Violations: {list(invalid.index)}"
        )

    if resolved_scale == "log2":
        log2_source = _clean_numeric_sample_columns(
            use_existing_log2_data(data, sample_columns),
            sample_columns,
        )
        linear_source = _clean_numeric_sample_columns(
            inverse_log2_transform_data(log2_source, sample_columns),
            sample_columns,
        )
    else:
        linear_source = _clean_numeric_sample_columns(
            raw_zero_to_nan(data, sample_columns),
            sample_columns,
        )
        log2_source = _clean_numeric_sample_columns(
            log2_transform_data(linear_source, sample_columns),
            sample_columns,
        )

    if coverage_data is None:
        diagnostic_source = log2_source
    elif resolved_scale == "log2":
        diagnostic_source = use_existing_log2_data(coverage_data, sample_columns)
    else:
        diagnostic_source = log2_transform_data(
            raw_zero_to_nan(coverage_data, sample_columns),
            sample_columns,
        )
    diagnostic_source = _clean_numeric_sample_columns(diagnostic_source, sample_columns)
    diagnostics, eligible_count, eligible_coverage, observed = _site_diagnostics(
        diagnostic_source,
        sample_columns,
    )
    eligible_index = eligible_coverage.index
    eligible_log2 = log2_source.loc[eligible_index].copy()

    annotation_aggregation = {
        "Gene_group": "first",
        "PTM_Collapse_key": _collapse_strings,
        "PTM_localization": _concat_strings,
        "UPD_seq": _collapse_strings,
    }
    annotations = data.groupby("Protein_group", as_index=False).agg(annotation_aggregation)

    non_positive_aggregates = 0
    if mode == "robust_site_median":
        numeric = eligible_log2[sample_columns].apply(pd.to_numeric, errors="coerce")
        site_centres = numeric.median(axis=1, skipna=True)
        centred = numeric.sub(site_centres, axis=0)
        centred["Protein_group"] = eligible_log2["Protein_group"].astype(str).to_numpy()
        values = (
            centred.groupby("Protein_group", sort=False)[sample_columns]
            .median()
            .reindex(diagnostics["Protein_group"].astype(str).tolist())
        )
        available = numeric.notna().assign(
            Protein_group=eligible_log2["Protein_group"].to_numpy()
        ).groupby("Protein_group")[sample_columns].sum().reindex(values.index, fill_value=0)
        required = eligible_count.reindex(values.index, fill_value=0).apply(
            lambda count: max(1, int(math.ceil(float(count) * ROBUST_SITE_MIN_FRACTION)))
        )
        for sample in sample_columns:
            values.loc[available[sample] < required, sample] = np.nan
        values = values.reset_index()
    else:
        source = linear_source.loc[eligible_index].copy()
        if mode == "sum_propagate_na":
            summarizer = _sum_propagate_nan
        elif mode == "sum_ignore_na":
            summarizer = _sum_ignore_nan
        elif mode == "mean":
            summarizer = _mean
        else:
            raise ValueError(
                "mode must be one of: robust_site_median, sum_propagate_na, "
                "sum_ignore_na, mean."
            )
        if mode in ("mean", "sum_ignore_na"):
            # Only sites quantified in every sample: each sample's value then comes
            # from the same sites, so a change in which sites were observed cannot
            # flip a fold change. Summing over whatever happened to be observed
            # used to turn a +1 log2 site change into -0.37 when the other condition
            # had more detected sites. Proteins without such a site stay missing.
            source = source.loc[source[sample_columns].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)]
        values = source.groupby("Protein_group", as_index=False).agg(
            {column: summarizer for column in sample_columns}
        )
        # These modes aggregate original-scale intensities while
        # robust_site_median returns log2. Transforming here means every mode
        # leaves this function on one scale, so the stored frame, the exported
        # table and the notebook packages all agree; downstream no longer has to
        # remember which mode produced the values it was handed.
        aggregated = values[sample_columns].apply(pd.to_numeric, errors="coerce")
        non_positive_aggregates = int((aggregated <= 0).sum().sum())
        if non_positive_aggregates:
            aggregated = aggregated.mask(aggregated <= 0)
        values[sample_columns] = np.log2(aggregated)

    supplied_source = eligible_log2 if mode == "robust_site_median" else source
    supplied = supplied_source[sample_columns].notna().assign(
        Protein_group=supplied_source['Protein_group'].to_numpy()
    ).groupby('Protein_group')[sample_columns].sum().reindex(diagnostics['Protein_group'], fill_value=0)
    measured = (supplied_source[sample_columns].notna()
                & diagnostic_source.loc[supplied_source.index, sample_columns].notna()).assign(
        Protein_group=supplied_source['Protein_group'].to_numpy()
    ).groupby('Protein_group')[sample_columns].sum().reindex(diagnostics['Protein_group'], fill_value=0)
    for sample in sample_columns:
        diagnostics[f"site_supplied__{sample}"] = supplied[sample].to_numpy(dtype=int)
        diagnostics[f"site_measured__{sample}"] = measured[sample].to_numpy(dtype=int)
    phosprot = annotations.merge(values, on="Protein_group", how="left")
    phosprot = phosprot.merge(diagnostics, on="Protein_group", how="left")
    phosprot = phosprot.rename(
        columns={
            "PTM_Collapse_key": "PTM_Collapse_keys",
            "Protein_group": "Phosphoprotein",
        }
    )

    diagnostic_columns = [
        column
        for column in phosprot.columns
        if column.startswith("site_") and column not in {"site_num", "site_num_eligible"}
    ]
    phosprot.attrs["non_positive_aggregates"] = non_positive_aggregates
    ordered = [
        "Phosphoprotein",
        "Gene_group",
        "site_num",
        "site_num_eligible",
        "PTM_Collapse_keys",
        "PTM_localization",
        "UPD_seq",
        *sample_columns,
        *diagnostic_columns,
    ]
    return phosprot[[column for column in ordered if column in phosprot.columns]]


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
    filename: str,
    is_log2_transformed: bool | None,
    warning_prefix: str,
    upstream_normalization: str | None = None,
    aggregation: str | None = None,
    lineage=None,
) -> object:
    phospho_annotation = _shared_phospho_annotation()
    metadata = phospho_annotation.metadata.copy()
    sample_columns = [sample for sample in metadata["sample"].astype(str).tolist() if sample in frame.columns]
    if not sample_columns:
        raise ValueError(
            "Shared phospho metadata does not match sample columns in phosphoprotein dataset."
        )
    metadata = metadata[metadata["sample"].astype(str).isin(sample_columns)].copy()

    resolved_log2, log2_auto_detected, log2_warning = resolve_log2_state(
        frame,
        sample_columns,
        is_log2_transformed,
    )

    inherited_filter_config = _shared_filter_config(phospho_annotation)
    # Phosphoprotein values are either collapsed from an already-normalized
    # phosphosite matrix or uploaded on their intended analysis scale. Never
    # normalize them again after collapse.
    filter_config = phosprot_filter_config(inherited_filter_config)
    if resolved_log2:
        log2_data = use_existing_log2_data(frame, sample_columns)
    else:
        log2_data = log2_transform_data(frame, sample_columns)

    filtered_data = filter_data(
        log2_data,
        metadata,
        min_present=filter_config.minPresent,
        mode=filter_config.mode,
        method=filter_config.method,
        min_percentage=filter_config.minPercentage,
    )

    warnings: list[str] = [
        f"{warning_prefix} Metadata and filter settings were inherited from phospho annotation."
    ]
    if log2_warning:
        warnings.append(log2_warning)
    if upstream_normalization is None:
        warnings.append(
            "No phosphoprotein-level normalization was applied. The uploaded "
            "phosphoprotein values were retained on their supplied normalization scale."
        )
    else:
        normalization = str(upstream_normalization or "none").strip().lower()
        warnings.append(
            f"Phosphosite-level normalization was '{normalization}' before collapse. "
            "No phosphoprotein-level normalization was applied after collapse."
        )
    stored = StoredAnnotation(
        kind="phosprot",
        source_data=frame.copy(),
        metadata=metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=resolved_log2,
        metadata_source="shared_phospho",
        filter_config=filter_config,
        auto_detected=False,
        warnings=warnings,
        log2_auto_detected=log2_auto_detected,
        phosprot_aggregation=aggregation,
        phosprot_lineage=lineage.model_copy(deep=True) if lineage else None,
        imputation=None,
        imputed_data=pd.DataFrame(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_table_dataset(filename=filename, kind="phosprot", frame=frame, phosprot_aggregation=aggregation,
                       phosprot_lineage=lineage)
    clear_annotation("phosprot", clear_all_profiles=True)
    return store_prepared_annotation(stored)


def aggregate_from_phospho(
    mode: PhosprotAggregationMode,
    source: PhosprotAggregationSource = "non_imputed",
    localization_cutoff: float = 0.0,
) -> object:
    from app.schemas.annotation import PhosprotLineage
    from app.app_version import APP_VERSION
    phospho_annotation = _shared_phospho_annotation()
    sample_columns = phospho_annotation.metadata["sample"].astype(str).tolist()
    filtered_source = getattr(phospho_annotation, "filtered_data", None)
    # Validate the observed source before looking up imputed values: filtering
    # must also remain authoritative for the site's coverage diagnostics.
    selected_source, log2_source = choose_best_source(
        filtered_source, phospho_annotation.log2_data, phospho_annotation.log2_data,
    )
    if selected_source == "raw":
        raise ValueError("Phosphoprotein aggregation needs annotated phospho data. Generate the phospho annotation first.")
    if selected_source == "filtered":
        source_label = "normalized, filtered, non-imputed phospho data"
    else:
        source_label = "normalized, non-imputed phospho data"
    missing_samples = [sample for sample in sample_columns if sample not in log2_source.columns]
    if missing_samples:
        raise ValueError(
            "Normalized phospho annotation is missing sample columns required for "
            f"phosphoprotein aggregation: {missing_samples}"
        )
    upstream_normalization = _shared_filter_config(phospho_annotation).normalization

    coverage_source = log2_source.copy()
    if source == "imputed":
        # All sites here; the collapse applies its own localization cutoff below.
        _, log2_source, _ = _select_matrix_all_rows("phospho", "imputed")
        source_label = "stored, verified imputed phospho data"

    # Only sites at or above the collapse's own localization cutoff are collapsed.
    # It is chosen with the collapse and recorded in the lineage, because the
    # phosphoprotein table outlives any later change of the session-wide cutoff.
    localization_cutoff = validate_localization_cutoff(localization_cutoff)
    if localization_cutoff > 0:
        log2_source = filter_localization(log2_source, localization_cutoff)
        coverage_source = coverage_source.loc[coverage_source.index.isin(log2_source.index)]
        if log2_source.empty:
            raise ValueError(
                f"No phosphosite has a localization probability of at least {localization_cutoff:.2f}; "
                "nothing to collapse."
            )

    phosprot = transform_phosprot(
        log2_source,
        phospho_annotation.metadata,
        mode=mode,
        data_scale="log2",
        coverage_data=coverage_source,
    )
    # transform_phosprot now returns log2 for every mode, so the frame stored
    # here, the table exported from it and the notebook packages are all on the
    # same scale.
    result_is_log2 = True

    # A non-positive aggregate cannot be log2 transformed, so transform_phosprot
    # masks it before taking the log and reports how many it lost. Counting it
    # here would be wrong now: the values are already log2, where a negative is
    # an ordinary measurement rather than a problem.
    non_positive = int(phosprot.attrs.get("non_positive_aggregates", 0))
    non_positive_warning = ""
    if non_positive:
        non_positive_warning = (
            f" {non_positive} aggregated value(s) were not positive and were set to"
            " missing because they cannot be log2 transformed. This points at a scale or"
            " imputation problem in the phosphosite input rather than at the aggregation."
        )

    method_note = ""
    if mode == "robust_site_median":
        method_note = (
            " Sites were centred by their across-sample median on log2 scale, then"
            " collapsed by the within-protein median. A sample value requires at least"
            f" {ROBUST_SITE_MIN_FRACTION:.0%} of the fixed eligible site set."
        )
    elif mode == "mean":
        method_note = (
            " Each protein value is the mean over the sites quantified in every sample;"
            " proteins without such a site are missing."
        )
    elif mode == "sum_ignore_na":
        method_note = (
            " Each protein value is the linear-scale sum over the sites quantified in"
            " every sample, so every sample sums the same sites; proteins without such"
            " a site are missing."
        )
    elif mode == "sum_propagate_na":
        method_note = (
            " A fixed eligible site set was used; a sample value is missing whenever any"
            " eligible site is missing. Per-sample observed-site coverage is included in"
            " the output."
        )
    return _store_phosprot_annotation(
        frame=phosprot,
        filename=f"phosprot_aggregated_{source}_{mode}.csv",
        is_log2_transformed=result_is_log2,
        warning_prefix=(
            "Phosphoprotein dataset was aggregated from "
            f"{source_label} using aggregation mode '{mode}'."
            f" {localization_cutoff_description(localization_cutoff)}"
            f"{non_positive_warning}{method_note}"
        ),
        upstream_normalization=upstream_normalization,
        aggregation=str(mode),
        lineage=PhosprotLineage(
            toolVersion=APP_VERSION, aggregation=mode,
            source="imputed" if source == "imputed" else selected_source,
            coverageSource=selected_source, filter=phospho_annotation.filter_config.model_copy(deep=True),
            imputation=phospho_annotation.imputation.model_copy(deep=True)
                if source == "imputed" and phospho_annotation.imputation else None,
            siteCount=len(log2_source), sampleCount=len(sample_columns),
            robustMinFraction=ROBUST_SITE_MIN_FRACTION if mode == "robust_site_median" else None,
            localizationCutoff=localization_cutoff,
        ),
    )


def upload_phosprot(
    frame: pd.DataFrame,
    filename: str,
    is_log2_transformed: bool | None = None,
) -> object:
    """Store a phosphoprotein matrix made earlier as the current phosphoprotein data.

    The alternative to `aggregate_from_phospho`: instead of collapsing the
    session's phosphosite data, a user brings back a phosphoprotein matrix they
    collapsed before (for example in an earlier session or another tool), so an
    analysis can be reproduced on exactly that matrix. Deliberately kept
    (design decision D17). It needs the phospho annotation, whose sample sheet
    the phosphoprotein level shares; the matrix is recorded with aggregation
    "uploaded" and no collapse lineage. `is_log2_transformed=None` detects the
    scale from the values.
    """
    _shared_phospho_annotation()
    warning_prefix = (
        "Phosphoprotein dataset was uploaded manually. "
        "Log2 state was auto-detected from the uploaded dataset."
        if is_log2_transformed is None
        else "Phosphoprotein dataset was uploaded manually."
    )
    return _store_phosprot_annotation(
        frame=frame,
        filename=filename,
        is_log2_transformed=is_log2_transformed,
        warning_prefix=warning_prefix,
        aggregation="uploaded",
    )
