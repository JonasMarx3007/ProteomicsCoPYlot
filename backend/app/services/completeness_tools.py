from __future__ import annotations

from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
)

import re

import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.completeness import CompletenessTablesResponse
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_sample_columns
from app.services.dataset_store import get_current_dataset
from app.services.functions import extract_sample_id as _extract_id_or_number
from app.services.functions import raw_zero_to_nan
from app.services.plot_images import (
    _peptide_file_column,
    _peptide_quantity_column,
    _peptide_sequence_column,
)
from app.services.plot_styling import (
    advanced_label,
    apply_advanced_axes,
    advanced_color,
    advanced_label_size,
)
from app.services.runtime_cache import apply_cached_wrappers
from app.services.plotting_common import get_plt as _get_plt, get_sns as _get_sns


def _feature_label(frame: pd.DataFrame) -> str:
    if "Phosphoprotein" in frame.columns:
        return "Phosphoprotein"
    if "PTM_Collapse_key" in frame.columns:
        return "Phosphosite"
    if "ProteinNames" in frame.columns:
        return "Protein"
    return "Feature"


def _peptide_precursor_column(frame: pd.DataFrame) -> str:
    if "Precursor.Id" in frame.columns:
        return "Precursor.Id"
    for column in frame.columns:
        normalized = re.sub(r"[^a-z0-9]+", "", str(column).strip().lower())
        if "precursor" in normalized and "id" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a precursor-id column.")


def _peptide_sample_columns(frame: pd.DataFrame) -> list[str]:
    from app.services.peptide_tools import _prepare_metadata, _sample_rename_map

    file_col = _peptide_file_column(frame)
    file_names = [
        str(value)
        for value in frame[file_col].dropna().astype(str).tolist()
        if str(value).strip()
    ]
    ordered_files = list(dict.fromkeys(file_names))
    if not ordered_files:
        raise ValueError("Peptide dataset does not contain any sample entries in the file-name column.")

    meta = _prepare_metadata(frame, include_id=False)
    matched = _sample_rename_map(ordered_files, meta, key_column=file_col)
    if not matched:
        raise ValueError("Peptide metadata does not match peptide sample columns.")
    return list(matched)


def _missing_value_plot_from_matrix(
    matrix: pd.DataFrame,
    *,
    title_label: str,
    bin_count: int,
    header: bool,
    text: bool,
    text_size: int,
    color: str,
    width_cm: float,
    height_cm: float,
    dpi: int,
    advanced: dict | None = None,
) -> bytes:
    plt = _get_plt()
    if matrix.empty or matrix.shape[1] == 0:
        raise ValueError("No data columns are available to calculate missing values.")

    # Exclude never-identified features before bucketing. Doing it afterwards by
    # string comparison silently stopped working whenever binning was on: an
    # all-missing row becomes ">N" rather than the sample count, so it was folded
    # into the top bucket instead and the same dataset reported different totals
    # depending on the bin setting.
    na_count = matrix.isna().sum(axis=1)
    na_count = na_count[na_count != matrix.shape[1]]

    if bin_count > 0:
        na_count = na_count.apply(lambda x: f">{bin_count}" if x > bin_count else str(int(x)))
        levels_vec = [str(i) for i in range(bin_count + 1)] + [f">{bin_count}"]
    else:
        na_count = na_count.astype(int).astype(str)
        max_count = int(na_count.astype(int).max()) if len(na_count) else 0
        levels_vec = [str(i) for i in range(max_count + 1)]

    miss_vals = na_count.value_counts().reset_index()
    miss_vals.columns = ["na_count", "Freq"]
    miss_vals["na_count"] = pd.Categorical(
        miss_vals["na_count"],
        categories=levels_vec,
        ordered=True,
    )
    miss_vals = miss_vals.sort_values("na_count")

    fig, ax = plt.subplots(
        figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)),
        dpi=max(72, int(dpi)),
    )
    ax.bar(
        miss_vals["na_count"].astype(str),
        miss_vals["Freq"],
        color=advanced_color(advanced, "barColor", color),
    )
    ax.set_xlabel("Number of Missing Values")
    ax.set_ylabel("Frequency")

    if text and not miss_vals.empty:
        offset = float(max(miss_vals["Freq"])) * 0.01
        for _, row in miss_vals.iterrows():
            ax.text(
                str(row["na_count"]),
                float(row["Freq"]) + offset,
                str(int(row["Freq"])),
                ha="center",
                fontsize=advanced_label_size(advanced, text_size),
            )

    if header:
        ax.set_title(f"Missing Value Plot - {title_label} Level")

    ax.tick_params(axis="x", rotation=0)
    ax.grid(axis="y", linestyle="--", alpha=0.7)
    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _frame_and_meta(kind: AnnotationKind) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = get_current_dataset(kind)
    if current is None or not hasattr(current, "frame"):
        raise ValueError(f"No {kind} dataset is currently loaded.")
    frame = current.frame.copy()

    annotation = get_annotation(kind)
    if annotation is not None and not annotation.source_data.empty:
        frame = annotation.source_data.copy()

    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")
    if annotation is None or not bool(getattr(annotation, "is_log2_transformed", False)):
        frame = raw_zero_to_nan(frame, sample_columns)

    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        meta = meta[meta["sample"].isin(sample_columns)]
        if not meta.empty:
            meta = meta.drop_duplicates(subset=["sample"])
            meta = meta.set_index("sample").reindex(sample_columns).reset_index()
            meta["condition"] = meta["condition"].fillna("sample").astype(str)
            return frame, meta

    meta = pd.DataFrame({"sample": sample_columns, "condition": ["sample"] * len(sample_columns)})
    return frame, meta


def _renamed_meta(meta: pd.DataFrame, include_id: bool = True) -> pd.DataFrame:
    renamed = meta.copy()
    renamed["sample"] = renamed["sample"].astype(str)
    renamed["id"] = renamed["sample"].apply(_extract_id_or_number)
    renamed["new_sample"] = renamed.groupby("condition").cumcount() + 1
    if include_id:
        renamed["new_sample"] = renamed.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})",
            axis=1,
        )
    else:
        renamed["new_sample"] = renamed.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}",
            axis=1,
        )
    return renamed


def _selected_matrix(
    frame: pd.DataFrame, meta: pd.DataFrame, include_id: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """The annotated sample columns, without features missing in all of them.

    A row with no value in any selected sample says nothing about the
    completeness of those samples (it was identified elsewhere, or never
    quantified), so it is excluded once here for the missing-value plot, the
    heatmap and the summary tables alike -- the same rule the coverage plots
    apply to their reference line. The number of excluded rows is returned so
    the page and the report can state it.
    """
    renamed_meta = _renamed_meta(meta, include_id=include_id)
    rename_map = dict(zip(renamed_meta["sample"], renamed_meta["new_sample"]))
    filtered = frame.rename(columns=rename_map)
    columns = [c for c in renamed_meta["new_sample"].tolist() if c in filtered.columns]
    if not columns:
        raise ValueError("No metadata sample columns are present in the dataset.")
    matrix = filtered[columns]
    present = matrix.notna().any(axis=1)
    excluded = int((~present).sum())
    return matrix[present], renamed_meta, excluded


def _filtered_data(frame: pd.DataFrame, meta: pd.DataFrame, include_id: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix, renamed_meta, _excluded = _selected_matrix(frame, meta, include_id=include_id)
    return matrix, renamed_meta


def completeness_excluded_feature_count(kind: AnnotationKind, include_id: bool = True) -> int:
    """Features with no value in any selected sample (excluded from the page)."""
    frame, meta = _frame_and_meta(kind)
    return _selected_matrix(frame, meta, include_id=include_id)[2]


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
    frame, meta = _frame_and_meta(kind)
    data_filtered, _ = _filtered_data(frame, meta, include_id=False)
    return _missing_value_plot_from_matrix(
        data_filtered,
        title_label=_feature_label(frame),
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
    *,
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
    quantity_column: str | None = None,
) -> bytes:
    from app.services.peptide_tools import get_peptide_frame

    frame = get_peptide_frame()
    file_col = _peptide_file_column(frame)
    seq_col = _peptide_sequence_column(frame)
    quantity_col = _peptide_quantity_column(frame, requested=quantity_column)
    pivot = frame.pivot_table(
        index=seq_col,
        columns=file_col,
        values=quantity_col,
        aggfunc="max",
    )
    sample_cols = [value for value in _peptide_sample_columns(frame) if value in pivot.columns]
    if not sample_cols:
        raise ValueError("Selected peptide samples have no usable quantity values.")
    matrix = raw_zero_to_nan(pivot[sample_cols], sample_cols)
    return _missing_value_plot_from_matrix(
        matrix,
        title_label="Peptide",
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
    *,
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
    quantity_column: str | None = None,
) -> bytes:
    from app.services.peptide_tools import get_peptide_frame

    frame = get_peptide_frame()
    file_col = _peptide_file_column(frame)
    precursor_col = _peptide_precursor_column(frame)
    quantity_col = _peptide_quantity_column(frame, requested=quantity_column)
    pivot = frame.pivot_table(
        index=precursor_col,
        columns=file_col,
        values=quantity_col,
        # "max" matches the peptide pivot above. "first" was order-dependent, so
        # two exports of the same search gave different precursor completeness.
        aggfunc="max",
    )
    sample_cols = [value for value in _peptide_sample_columns(frame) if value in pivot.columns]
    if not sample_cols:
        raise ValueError("Selected peptide samples have no usable quantity values.")
    matrix = raw_zero_to_nan(pivot[sample_cols], sample_cols)
    return _missing_value_plot_from_matrix(
        matrix,
        title_label="Precursor",
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
    plt = _get_plt()
    sns = _get_sns()
    frame, meta = _frame_and_meta(kind)
    data_filtered, renamed_meta = _filtered_data(frame, meta, include_id=include_id)
    original_by_label = {
        str(row["new_sample"]): str(row["sample"])
        for _, row in renamed_meta.iterrows()
    }

    fig, ax = plt.subplots(
        figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)),
        dpi=max(72, int(dpi)),
    )

    # Keep seaborn heatmap rendering aligned with the legacy CoPYlot look.
    sns.heatmap(data_filtered.isna(), cbar=False, cmap="viridis", ax=ax)

    if header:
        ax.set_title("Missing Values Heatmap")
    ax.set_xlabel("Sample")
    ax.set_ylabel(f"{_feature_label(frame)}s")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    ax.set_xticklabels(
        [
            advanced_label(
                label.get_text(),
                advanced,
                "sampleLabels",
                original_by_label.get(label.get_text()),
            )
            for label in ax.get_xticklabels()
        ],
        rotation=90,
    )
    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=True)


def completeness_sample_summary_table(
    kind: AnnotationKind,
    include_id: bool = True,
) -> pd.DataFrame:
    frame, meta = _frame_and_meta(kind)
    data_filtered, _ = _filtered_data(frame, meta, include_id=include_id)

    na_counts = data_filtered.isna().sum(axis=0)
    summary = na_counts.reset_index()
    summary.columns = ["Sample", "Counts"]
    total_rows = max(1, data_filtered.shape[0])
    summary["%_missing_values"] = (summary["Counts"] / total_rows) * 100.0
    summary["%_missing_values"] = summary["%_missing_values"].round(2)
    return summary


def completeness_feature_summary_table(
    kind: AnnotationKind,
    include_id: bool = True,
) -> pd.DataFrame:
    frame, meta = _frame_and_meta(kind)
    data_filtered, _ = _filtered_data(frame, meta, include_id=include_id)

    na_counts = data_filtered.isna().sum(axis=1)
    summary = na_counts.value_counts().reset_index()
    summary.columns = ["n_MissingProteinValues", "Counts"]
    summary = summary.sort_values("n_MissingProteinValues").reset_index(drop=True)
    total_counts = max(1, int(summary["Counts"].sum()))
    summary["%_missing_values"] = ((summary["Counts"] / total_counts) * 100.0).round(2)
    return summary


def completeness_tables(
    kind: AnnotationKind,
    outlier_threshold: float = 50.0,
    include_id: bool = True,
) -> CompletenessTablesResponse:
    sample_summary = completeness_sample_summary_table(kind, include_id=include_id)
    feature_summary = completeness_feature_summary_table(kind, include_id=include_id)

    frame, meta = _frame_and_meta(kind)
    data_filtered, _, excluded = _selected_matrix(frame, meta, include_id=include_id)
    total_values = max(1, int(data_filtered.size))
    missing_values = int(data_filtered.isna().sum().sum())
    overall_missing = round((missing_values / total_values) * 100.0, 2)
    outliers = sample_summary[sample_summary["%_missing_values"] > float(outlier_threshold)][
        "Sample"
    ].astype(str).tolist()

    return CompletenessTablesResponse(
        kind=kind,
        overallMissingPercent=overall_missing,
        outlierThreshold=float(outlier_threshold),
        outliers=outliers,
        excludedAllMissingCount=excluded,
        sampleSummary=sample_summary.where(pd.notna(sample_summary), None).to_dict(orient="records"),
        featureSummary=feature_summary.where(pd.notna(feature_summary), None).to_dict(orient="records"),
    )

# Each module caches its own renderers, the way table_functions and
# single_protein_tools already did. These were cached one layer up, by a facade
# in functions.py that forwarded to them; the facade is gone and the cache
# stays where the work is.
apply_cached_wrappers(
    globals(),
    [
        "completeness_missing_value_plot",
        "completeness_missing_value_plot_peptide",
        "completeness_missing_value_plot_precursor",
        "completeness_missing_value_heatmap",
        "completeness_tables",
    ],
)
