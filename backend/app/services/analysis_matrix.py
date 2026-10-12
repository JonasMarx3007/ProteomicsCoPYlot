"""The live matrices an analysis reads, and which of them a session holds.

`functions.py` holds the pure transforms (what the notebooks and the pip
package reproduce); this module is where an analysis asks the session for the
matrix those transforms run on. Everything that reads the annotation store or
the session's localization cutoff lives here, so `functions` imports neither.
The stores are reached through their modules, not bound names, so a test that
replaces `annotation_store.get_annotation` is seen here too.
"""
from __future__ import annotations

import pandas as pd

from app.services import annotation_store, phospho_localization
from app.services.functions import LOCALIZATION_COLUMN, filter_localization


# One vocabulary, in ladder order: least processed first.
#
# "data" is the complete annotated log2 matrix, "filtered" the matrix the filter
# kept, "imputed" the filled matrix. There is deliberately no "auto" and no
# "log2" alias: those were two names for one matrix and one name that meant a
# different matrix on each of the two former resolvers, so the same request
# returned 11,580 rows through one path and 11,916 through the other.
DATA_SOURCES: tuple[str, ...] = ("data", "filtered", "imputed")

_EMPTY_FILTER_MESSAGE = (
    "No features passed the selected filter. Adjust the filter in "
    "Data > Annotation and generate annotation again to continue. "
    "Unfiltered data has not been substituted."
)

def data_source_availability(kind) -> dict[str, bool]:
    """Which of the three matrices this level actually holds.

    A completed empty filter is still a processing stage. Keep it selectable
    so analysis reports the empty result instead of substituting unfiltered rows.
    """
    annotation = annotation_store.get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        return {source: False for source in DATA_SOURCES}
    log2 = getattr(annotation, "log2_data", None)
    filtered = getattr(annotation, "filtered_data", None)
    return {
        "data": isinstance(log2, pd.DataFrame) and not log2.empty,
        "filtered": isinstance(filtered, pd.DataFrame) and len(filtered.columns) > 0,
        "imputed": imputed_data_available(kind),
    }

def most_processed_data_source(kind) -> str:
    """imputed > filtered > data -- what a fresh panel opens on.

    The default is the most processed matrix that exists, because that is the
    one the user built by configuring the pipeline. It is a *default*, not a
    coercion: a panel restoring a saved choice keeps that choice.
    """
    available = data_source_availability(kind)
    for source in reversed(DATA_SOURCES):
        if available[source]:
            return source
    return "data"

def data_source_options(kind) -> dict[str, object]:
    """What a selector should offer, and what it should open on.

    One payload for every panel that offers a choice, so the UI never has to
    work out the ladder itself and cannot get it different on two pages.
    """
    available = data_source_availability(kind)
    return {
        "availableDataSources": [s for s in DATA_SOURCES if available[s]],
        "defaultDataSource": most_processed_data_source(kind),
    }

def select_matrix(kind, data_source="data") -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """The matrix an analysis runs on. The only way to get one.

    Phosphosite matrices are narrowed to the sites that pass this session's
    localization probability cutoff (see services/phospho_localization.py), so
    every module that reads through here analyses the same sites.
    """
    source, frame, metadata = _select_matrix_all_rows(kind, data_source)
    if kind == "phospho":
        cutoff = phospho_localization.get_localization_cutoff()
        if cutoff > 0 and LOCALIZATION_COLUMN in frame.columns:
            kept = filter_localization(frame, cutoff)
            if kept.empty and not frame.empty:
                raise ValueError(
                    f"No phosphosite has a localization probability of at least {cutoff:.2f}. "
                    "Lower the localization probability cutoff."
                )
            frame = kept
        elif cutoff > 0:
            raise ValueError(
                f"A localization probability cutoff of {cutoff:.2f} is set, but this phosphosite "
                f"table has no '{LOCALIZATION_COLUMN}' column. Set the cutoff to 0."
            )
    return source, frame, metadata

def _select_matrix_all_rows(kind, data_source="data") -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """The matrix an analysis runs on, before the phosphosite cutoff.

    Returns the resolved name, the frame and the metadata. Every unavailable or
    unrecognised request raises with a message naming what to do about it --
    nothing is silently substituted, because a substituted matrix produces real
    numbers under the wrong label, which is worse than an error.
    """
    requested = str(data_source or "data").strip().lower()
    if requested not in DATA_SOURCES:
        raise ValueError(
            "Unsupported data source "
            f"{str(data_source)!r}. Choose one of: {', '.join(DATA_SOURCES)}."
        )

    annotation = annotation_store.get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        raise ValueError(
            f"No annotation metadata available for {kind}. Generate annotation first."
        )
    metadata = annotation.metadata.copy()

    if requested == "data":
        log2_data = getattr(annotation, "log2_data", None)
        if not isinstance(log2_data, pd.DataFrame) or log2_data.empty:
            raise ValueError(
                f"{kind.capitalize()} data is not available. Generate annotation first."
            )
        return "data", log2_data.copy(), metadata

    if requested == "filtered":
        filtered = getattr(annotation, "filtered_data", None)
        if not isinstance(filtered, pd.DataFrame) or len(filtered.columns) == 0:
            raise ValueError(
                f"Filtered {kind} data is not available. Generate annotation/filtering first."
            )
        if filtered.empty:
            raise ValueError(_EMPTY_FILTER_MESSAGE)
        return "filtered", filtered.copy(), metadata

    imputation = getattr(annotation, "imputation", None)
    imputed_data = getattr(annotation, "imputed_data", None)
    if (
        imputation is None
        or str(getattr(imputation, "mode", "none")).strip().lower() == "none"
        or not isinstance(imputed_data, pd.DataFrame)
        or imputed_data.empty
    ):
        raise ValueError(
            f"Imputed {kind} data is not available. Run imputation successfully first."
        )
    missing_samples = [
        sample
        for sample in metadata["sample"].astype(str).tolist()
        if sample not in imputed_data.columns
    ]
    if missing_samples:
        raise ValueError(
            f"Stored imputed {kind} data is invalid because sample columns are missing: "
            f"{missing_samples}. Run imputation again."
        )
    return "imputed", imputed_data.copy(), metadata

def qc_matrix(kind) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The data as loaded, with its metadata. What QC describes.

    QC has no data-source choice by design: it exists to show what the
    instrument produced, *before* any decision about filtering or imputation, so
    offering to describe the filtered subset would defeat the purpose. Every QC
    surface therefore reads this one matrix, and PCA is the single deliberate
    exception -- it cannot use incomplete features, so choosing its input is a
    real scientific decision and it keeps the selector.

    This is `select_matrix(kind, "data")`, not a parallel accessor, so QC cannot
    drift away from what "data" means everywhere else. The helpers this replaced
    fell back to the filtered matrix when log2 was missing and said nothing, so a
    QC plot could quietly describe the filtered subset.

    CV and the abundance plot read the same data back-transformed to the linear
    scale, which is the scale those statistics are defined on -- a scale choice,
    not a matrix choice.
    """
    _, frame, metadata = select_matrix(kind, "data")
    return frame, metadata

def phosprot_values_are_centred(kind) -> bool:
    """True when the stored frame holds ratios to each site's median, not abundances."""
    if kind != "phosprot":
        return False
    annotation = annotation_store.get_annotation(kind)
    aggregation = getattr(annotation, "phosprot_aggregation", None) if annotation else None
    return str(aggregation or "").strip().lower() == "robust_site_median"

def imputed_data_available(kind):
    annotation = annotation_store.get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        return False
    imputation = getattr(annotation, "imputation", None)
    if imputation is None:
        return False
    if (
        str(getattr(imputation, "mode", "none")).strip().lower() == "none"
        or not bool(getattr(imputation, "applied", False))
    ):
        return False
    frame = getattr(annotation, "imputed_data", None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return False
    sample_columns = [
        sample
        for sample in annotation.metadata["sample"].astype(str).tolist()
        if sample in frame.columns
    ]
    return len(sample_columns) == len(annotation.metadata)
