from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from app.schemas.annotation import ConditionAssignment, FilterMode
# One reading of the sample column for uploads and annotation (2026-10-02).
from app.services.metadata_upload_store import MAX_MANUAL_METADATA_PROFILES, _resolve_sample_column
from app.services.functions import (
    build_metadata_from_conditions,
    filter_data,
    log2_transform_data,
    missingness_imbalance,
    missingness_imbalance_warning,
    normalize_data,
    use_existing_log2_data,
)

@dataclass
class AnnotationComputationResult:
    metadata: pd.DataFrame
    log2_data: pd.DataFrame
    filtered_data: pd.DataFrame
    is_log2_transformed: bool
    log2_auto_detected: bool
    auto_detected: bool
    warnings: list[str]


@dataclass(frozen=True)
class Log2ScaleDetection:
    is_log2_transformed: bool | None
    reason: str
    # True when the negative-value test and the magnitude test disagree: the
    # call is still made, but the user is told to check it.
    conflict: bool = False


def _range_votes(usable: list[np.ndarray]) -> tuple[int, int]:
    """Per-column votes from the value range: log2 intensities sit roughly in
    0-60, linear intensities far above."""
    log2_votes = 0
    linear_votes = 0
    for finite in usable:
        q50, q95, column_q99 = np.nanquantile(finite, [0.50, 0.95, 0.99])
        if q95 > 50 or column_q99 > 100:
            linear_votes += 1
        elif q50 <= 35 and q95 <= 45 and column_q99 <= 60:
            log2_votes += 1
    return log2_votes, linear_votes


# "log2" as a token, so a run dated `log2024` is not read as a scale marker.
_LOG2_NAME = re.compile(r"(?<![a-z0-9])log2(?![0-9])", re.IGNORECASE)


def log2_scale_hint(data: pd.DataFrame, sample_columns: list[str]) -> str | None:
    """A note for the scale checkbox when the values look unusual for log2 intensities.

    The auto-detection cannot tell log2 from log10, natural-log or count data:
    all of them sit in a narrow positive range. Two patterns are worth a word:
    mostly whole numbers (count data such as spectral counts), and a median
    below 12 with no negative values (log2 intensities from mass spectrometry
    usually lie around 15-30; log10 or ln intensities lie lower). Centred data
    and log2 ratios have negative values and are left alone, and so are columns
    whose names all say log2. The checkbox itself is not changed.
    """
    columns = [str(column) for column in sample_columns if str(column) in data.columns]
    if not columns:
        return None
    numbers = data[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float).ravel()
    finite = numbers[np.isfinite(numbers)]
    if finite.size < 30:
        return None
    negative_fraction = float(np.mean(finite < 0))
    if negative_fraction >= 0.001:
        # Negative values make the detector say log2. When the magnitude says
        # linear instead (background-subtracted intensities with a few negative
        # cells), say so here, where the box is -- the detector's reason alone
        # is only shown after the annotation was generated.
        numeric = data[columns].apply(pd.to_numeric, errors="coerce")
        usable = [numeric[column].to_numpy(dtype=float) for column in columns]
        usable = [values[np.isfinite(values)] for values in usable]
        usable = [values for values in usable if values.size >= 3]
        log2_votes, linear_votes = _range_votes(usable)
        if usable and linear_votes >= max(1, (len(usable) + 1) // 2) and linear_votes > log2_votes:
            return (
                f"{negative_fraction:.1%} of the values are negative, which suggests transformed data, "
                f"but the values are large (median {float(np.median(finite)):.3g}), which looks like "
                "linear intensities -- for example background-subtracted ones. The box is ticked because "
                "of the negative values; untick it if these are linear values."
            )
    whole = float(np.mean(np.isclose(finite, np.round(finite), rtol=0, atol=1e-9)))
    if whole >= 0.95 and float(finite.min()) >= 0:
        return (
            f"{whole:.0%} of the values are whole numbers, which looks like count data (for example "
            "spectral counts) rather than log2 values. If so, untick the box so the counts are log2-transformed."
        )
    if all(_LOG2_NAME.search(column) for column in columns):
        return None
    median = float(np.median(finite))
    # A heuristic only: location and spread cannot identify a logarithm's base.
    quartile_1, quartile_3 = np.percentile(finite, [25, 75])
    spread = float(quartile_3 - quartile_1)
    if float(np.mean(finite < 0)) < 0.001 and 0 < median < 12 and spread < 1.8:
        return (
            f"The values have a median of {median:.1f} and an interquartile range of {spread:.2f}; "
            "These summaries cannot determine the data scale. If these are log10 or natural-log "
            "values, convert them to log2 before uploading "
            "(log2 = log10 x 3.32, or ln x 1.44)."
        )
    return None


def detect_log2_transformed(
    data: pd.DataFrame,
    sample_columns: list[str],
) -> Log2ScaleDetection:
    """Classify scale using only confirmed measurement/sample columns.

    A column name is weak evidence: it is trusted only when *every* selected
    column carries the marker, and never over a clear contradiction from the
    values themselves. One oddly named column used to decide for the whole
    dataset, which skipped the log2 transform and turned a two-fold change into
    a fold change of several hundred thousand.
    """
    selected_columns = [str(column) for column in sample_columns if str(column) in data.columns]
    if not selected_columns:
        return Log2ScaleDetection(None, "no matching sample columns were available")

    named_log2 = [column for column in selected_columns if _LOG2_NAME.search(column)]
    names_agree = len(named_log2) == len(selected_columns)

    value_detection = _value_scale_detection(data, selected_columns)
    if names_agree:
        if value_detection.is_log2_transformed is False:
            return Log2ScaleDetection(
                None,
                "every selected sample column is named as log2 but the values are on a "
                f"linear-intensity scale ({value_detection.reason}); state the scale explicitly",
            )
        return Log2ScaleDetection(
            True,
            f"all {len(named_log2)} selected sample column names indicate log2 values",
        )
    return value_detection


def _value_scale_detection(
    data: pd.DataFrame,
    selected_columns: list[str],
) -> Log2ScaleDetection:
    numeric = data[selected_columns].apply(pd.to_numeric, errors="coerce")
    usable: list[np.ndarray] = []
    for column in selected_columns:
        values = numeric[column].to_numpy(dtype=float, copy=False)
        finite = values[np.isfinite(values)]
        if finite.size >= 3:
            usable.append(finite)

    if not usable:
        return Log2ScaleDetection(None, "the selected sample columns contain no usable numeric values")

    combined = np.concatenate(usable)
    negative_fraction = float(np.mean(combined < 0))
    log2_votes, linear_votes = _range_votes(usable)
    required_votes = max(1, (len(usable) + 1) // 2)
    if negative_fraction >= 0.001:
        # Negative values favour log2 in this heuristic. The magnitude test
        # still runs: when it says linear (a
        # background-subtracted linear matrix with a few negative cells, say),
        # the call stands, but the reason says that the two tests disagree, so
        # the page can warn instead of staying silent.
        if linear_votes >= required_votes and linear_votes > log2_votes:
            return Log2ScaleDetection(
                True,
                f"{negative_fraction:.1%} of the selected sample values are negative, which suggests "
                "transformed data, but their magnitude (median "
                f"{float(np.nanmedian(combined)):.3g}) looks like linear intensities; the negative "
                "values decided. Check the scale and set it explicitly if these are linear values",
                conflict=True,
            )
        return Log2ScaleDetection(
            True,
            "selected sample values include a reproducible negative-value signal",
        )

    q01, q99 = np.nanquantile(combined, [0.01, 0.99])
    if q01 >= 0 and q99 <= 2:
        return Log2ScaleDetection(
            None,
            "non-negative values are confined to 0-2, which can represent either ratios or transformed data",
        )

    if log2_votes >= required_votes and log2_votes > linear_votes:
        return Log2ScaleDetection(
            True,
            f"{log2_votes} of {len(usable)} selected sample columns have a log2-like value range",
        )
    if linear_votes >= required_votes and linear_votes > log2_votes:
        return Log2ScaleDetection(
            False,
            f"{linear_votes} of {len(usable)} selected sample columns have a linear-intensity value range",
        )
    return Log2ScaleDetection(
        None,
        "the selected sample columns do not provide a consistent scale signal",
    )


_NORMALIZATION_LABELS = {
    "none": "No normalization was applied.",
    "median": (
        "Median centering was applied globally to the log2 values before filtering: each "
        "sample was shifted onto a common median."
    ),
    "quantile": (
        "Quantile normalization was applied globally to the log2 values before filtering: "
        "every sample was mapped onto a common intensity distribution."
    ),
}


def _vsn_label() -> str:
    """Name the reference implementation and its version, for the Methods section."""
    try:
        from app.services.r_vsn import vsn_reference_version

        version = vsn_reference_version()
    except Exception:  # noqa: BLE001 - reporting only
        version = None
    suffix = f" version {version}" if version else ""
    return (
        "VSN was applied globally, replacing the plain log2 transform. It is computed by the "
        f"Bioconductor 'vsn' package{suffix} rather than a reimplementation. Note that the vsn "
        "fit can be sensitive to tiny changes in the input on some datasets, so re-running it "
        "on data exported and re-imported through a text format may not reproduce it exactly. "
        "The CV and abundance plots use the unnormalized data, because VSN output is not on a "
        "linear intensity scale."
    )


def _normalization_warning(normalization: str) -> str:
    """State the normalization in the annotation output so the report records it."""
    key = str(normalization or "none").strip().lower()
    if key == "vsn":
        return _vsn_label()
    message = _NORMALIZATION_LABELS.get(key, f"Normalization '{key}' was applied.")
    if key == "none":
        message += (
            " Sample loading and instrument drift are therefore uncorrected unless the upload "
            "was already normalized upstream (for example MaxLFQ or PG.Normalised)."
        )
    return message


def _missingness_warning(log2_data: pd.DataFrame, metadata: pd.DataFrame, normalization: str) -> str | None:
    """Warn when median, quantile or VSN normalization met very uneven missingness."""
    if str(normalization or "none").strip().lower() not in {"median", "quantile", "vsn"}:
        return None
    return missingness_imbalance_warning(missingness_imbalance(log2_data, metadata), normalization)


ZERO_SHARE_LIMIT = 0.005
ZERO_GAP_LOG2 = 5.0


def _log2_zero_warning(data: pd.DataFrame, sample_columns: list[str], is_log2_transformed: bool) -> str | None:
    """Warn when a log2 upload holds many exact zeros far below its other values.

    In a log2 matrix 0 is kept as a measurement (an intensity of 1), which is
    right for data that really reaches 0. Some exports write 0 for "not
    measured" instead; in a matrix whose values sit around 20, each such zero is
    an extreme low value and turns into a fold change of 20 or more. The warning
    fires when more than 0.5 % of the values are exactly 0 and the lowest 1 % of
    the other values start at least 5 log2 units (32-fold) above it. Nothing is
    changed: only the person who exported the file knows what the zeros mean.
    """
    if not is_log2_transformed or not sample_columns:
        return None
    values = data[sample_columns].apply(pd.to_numeric, errors="coerce")
    numbers = values.to_numpy(dtype=float)
    finite = numbers[np.isfinite(numbers)]
    zeros = int((finite == 0).sum())
    if not finite.size or zeros / finite.size <= ZERO_SHARE_LIMIT:
        return None
    nonzero = finite[finite != 0]
    if not nonzero.size:
        return None
    lowest = float(np.percentile(nonzero, 1))
    if lowest < ZERO_GAP_LOG2:
        return None
    rows = int((values == 0).any(axis=1).sum())
    return (
        f"{zeros:,} values ({zeros / finite.size:.1%}) in {rows:,} rows are exactly 0, while the lowest 1% of "
        f"the other values start at {lowest:.1f} log2. In a log2 matrix a 0 is kept as a measurement (an "
        "intensity of 1), so if these zeros mean 'not measured' they act as extreme low values and produce "
        "very large fold changes. If so, remove them or export them as empty cells and upload again."
    )


def prepare_normalized_log2_data(
    data: pd.DataFrame,
    sample_columns: list[str],
    is_log2_transformed: bool,
    normalization: str,
) -> pd.DataFrame:
    """Create the one canonical analysis matrix used by every annotation path.

    VSN models linear intensities and is sensitive to machine-epsilon changes in
    its input, so observed linear intensities are preserved exactly as its source.
    Raw-zero non-detections are masked by the normalization boundary.
    For already-log2 uploads there is no original linear matrix to preserve.
    """
    if is_log2_transformed:
        log2_data = use_existing_log2_data(data, sample_columns)
    else:
        log2_data = log2_transform_data(data, sample_columns)

    return normalize_data(
        log2_data,
        sample_columns,
        normalization,
        linear_source=None if is_log2_transformed else data,
    )


def resolve_log2_state(
    data: pd.DataFrame,
    sample_columns: list[str],
    requested_state: bool | None,
) -> tuple[bool, bool, str | None]:
    if requested_state is not None:
        return bool(requested_state), False, None

    detection = detect_log2_transformed(data, sample_columns)
    if detection.is_log2_transformed is None:
        raise ValueError(
            "Could not reliably auto-detect whether the selected sample columns are log2 "
            f"transformed: {detection.reason}. Choose an explicit log2 scale setting."
        )
    scale_label = "already log2 transformed" if detection.is_log2_transformed else "linear"
    warning = (
        f"Sample scale was auto-detected as {scale_label} from {len(sample_columns)} "
        f"selected sample column(s): {detection.reason}."
    )
    if detection.conflict:
        warning = "Check the data scale. " + warning
    return detection.is_log2_transformed, True, warning


# One of these has to exist for the statistics pages to label a row. The
# upload aliases the common export names (Spectronaut, DIA-NN, MaxQuant,
# FragPipe) onto them; anything else used to pass annotation and then fail on
# every statistics page with a 400 that did not say what was missing.
_IDENTIFIER_COLUMNS = ("ProteinNames", "GeneNames", "PTM_Collapse_key", "UPD_seq", "Phosphoprotein", "Gene_group")


def _identifier_warning(data: pd.DataFrame) -> str | None:
    columns = {str(column) for column in data.columns}
    if columns & set(_IDENTIFIER_COLUMNS):
        return None
    return (
        "No identifier column was recognised (none of " + ", ".join(_IDENTIFIER_COLUMNS) + "). "
        "QC plots work without one, but the statistics pages need a column to label each row: "
        "rename the protein or site identifier column in the file (for example 'Protein' to "
        "'ProteinNames') and upload it again."
    )


_RUN_COLUMNS = ("File.Name", "Run", "R.FileName")
_DECOY_PREFIXES = ("REV__", "CON__", "rev_", "con_")


def _table_shape_warnings(data: pd.DataFrame) -> list[str]:
    """Rows that will mislead a reader without being wrong for the arithmetic.

    Three things an upload used to accept in silence: a long-format precursor
    report taken for a protein table (one row per precursor and run, so the
    same protein repeats and a "sample" column holds every run's values), an
    identifier that occurs on several rows (both rows become identically
    labelled points), and MaxQuant decoy/contaminant rows (``REV__``/``CON__``
    identifiers, or a ``+`` in the Reverse / Potential contaminant columns).
    Nothing is removed; the warning says what is there.
    """
    warnings: list[str] = []
    columns = [str(column) for column in data.columns]
    label = next((column for column in _IDENTIFIER_COLUMNS if column in columns), None)
    labels = data[label].dropna().astype(str) if label is not None else None
    run_column = next((column for column in _RUN_COLUMNS if column in columns), None)
    if run_column is not None and labels is not None and labels.duplicated().any():
        warnings.append(
            f"This table has a run column ({run_column}) and the same {label} on several rows, which "
            "looks like a long-format precursor or peptide report (one row per precursor and run). "
            "Upload it on the Peptide page, or use the protein-group matrix export (one row per "
            "protein, one column per run) here."
        )
    elif labels is not None:
        duplicated = int(labels.duplicated().sum())
        if duplicated:
            warnings.append(
                f"{duplicated:,} rows repeat a {label} already used by another row; they are kept and "
                "will appear as identically labelled points. Check the export for isoform or "
                "duplicate entries."
            )
    flagged = np.zeros(len(data), dtype=bool)
    if label is not None:
        flagged |= data[label].fillna("").astype(str).str.startswith(_DECOY_PREFIXES).to_numpy(dtype=bool)
    for column in ("Reverse", "Potential contaminant", "Only identified by site"):
        if column in columns:
            flagged |= data[column].astype(str).str.strip().eq("+").to_numpy(dtype=bool)
    decoys = int(flagged.sum())
    if decoys:
        warnings.append(
            f"{decoys:,} rows look like decoy or contaminant entries (REV__/CON__ identifiers or a '+' in "
            "Reverse / Potential contaminant / Only identified by site); they are kept. Remove them from "
            "the export if they should not enter the analysis."
        )
    return warnings


def _unparseable_sample_columns(
    data: pd.DataFrame,
    sample_columns: list[str],
) -> list[tuple[str, int, int]]:
    """Sample columns where text that looks like data does not parse as a number.

    `pd.to_numeric(errors="coerce")` turns anything unparseable into NaN, and
    every later stage reads NaN as "not detected". A blank or a documented
    placeholder really is missing, so those are ignored; a value carrying digits
    that still fails to parse is a measurement being lost. A column exported with
    a European decimal comma loses every value this way, and the sample then
    looks fully undetected rather than unreadable.

    Returns (column, lost, total non-blank) for every column losing anything at
    all. A partial loss is worth reporting rather than tolerating: a spreadsheet
    that writes 3,115,462.6 mangles only the largest values, so what it deletes
    is a biased sample of the measurements and shifts the comparison.
    """
    placeholders = {"", "na", "n/a", "nan", "-", "--", "null", "none", "filtered", "#div/0!", "#n/a"}
    findings: list[tuple[str, int, int]] = []
    for column in sample_columns:
        if column not in data.columns:
            continue
        raw = data[column]
        if raw.dtype.kind in "fiub":
            continue  # already numeric; nothing was parsed from text
        text = raw.astype(str).str.strip()
        considered = text[~text.str.lower().isin(placeholders)]
        if considered.empty:
            continue
        coerced = pd.to_numeric(considered, errors="coerce")
        # Only count entries that carried a digit: a stray label is not a
        # measurement, but "1234,5" or "1,234.5" is.
        lost = int((coerced.isna() & considered.str.contains(r"\d", regex=True)).sum())
        # Reported whenever anything is lost, not only past the threshold. The
        # threshold was set for the all-or-nothing case a decimal comma produces,
        # and a partial loss is the one worth telling someone about: a thousands
        # separator applied by a spreadsheet hits only the largest values, so the
        # measurements it deletes are a biased sample, not a random one.
        if lost:
            findings.append((str(column), lost, int(len(considered))))
    return findings


def _unmatched_metadata_samples(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    matched_samples: list[str],
) -> list[str]:
    """Metadata sample names that name no column in the loaded dataset."""
    column_map = {str(c).strip().lower(): str(c).strip() for c in metadata.columns}
    sample_col = _resolve_sample_column(column_map, metadata.columns)
    if sample_col is None:
        return []
    submitted = _clean_string_series(metadata[sample_col]).apply(
        lambda value: re.sub(r"\.0$", "", value)
    )
    matched = set(matched_samples)
    return sorted({name for name in submitted if name and name not in matched})


def normalize_uploaded_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    if metadata.empty:
        raise ValueError("Uploaded metadata is empty.")

    normalized = metadata.copy()
    normalized.columns = [str(c).strip() for c in normalized.columns]
    column_map = {str(c).strip().lower(): str(c).strip() for c in normalized.columns}

    sample_col = _resolve_sample_column(column_map, normalized.columns)
    if sample_col is None:
        raise ValueError(
            "Uploaded metadata must contain a sample column (e.g. 'sample' or 'data_column_name')."
        )
    sample_key = str(sample_col).strip().lower()
    non_sample_columns = [
        column for column in normalized.columns if str(column).strip().lower() != sample_key
    ]
    if not non_sample_columns:
        raise ValueError(
            "Uploaded metadata must contain at least one grouping column besides 'sample'."
        )

    condition_col = column_map.get("condition", non_sample_columns[0])
    selected = normalized[[sample_col, *non_sample_columns]].copy()

    alias_map: dict[str, str] = {}
    used_aliases: set[str] = {"sample"}
    for original in non_sample_columns:
        alias = _make_unique_column_alias(str(original), used_aliases)
        alias_map[str(original)] = alias
        used_aliases.add(alias)

    selected = selected.rename(columns={sample_col: "sample", **alias_map})
    condition_alias = alias_map[str(condition_col)]
    if condition_alias != "condition":
        selected.insert(1, "condition", selected[condition_alias])

    cleaned = selected.copy()
    cleaned["sample"] = _clean_string_series(cleaned["sample"]).apply(
        lambda value: re.sub(r"\.0$", "", value)
    )
    for column in cleaned.columns:
        if column == "sample":
            continue
        cleaned[column] = _clean_string_series(cleaned[column])

    cleaned = cleaned[(cleaned["sample"] != "") & (cleaned["condition"] != "")]

    data_columns = set(str(c) for c in data.columns)
    cleaned = cleaned[cleaned["sample"].isin(data_columns)]
    if "pair_id" in cleaned.columns and cleaned["sample"].duplicated(keep=False).any():
        duplicates = (
            cleaned.loc[cleaned["sample"].duplicated(keep=False), "sample"]
            .drop_duplicates()
            .tolist()
        )
        raise ValueError(
            "Metadata with pair_id must contain each sample exactly once. "
            f"Duplicates: {', '.join(duplicates)}."
        )
    # A sample repeated with the same values says the same thing twice and is
    # dropped. A sample repeated with *different* values is a contradiction: the
    # file states two incompatible facts, and keeping the first let row order
    # decide which condition a sample belongs to, and so which group it was
    # tested in. The pair_id branch above already refuses the same shape.
    conflicting: list[str] = []
    for sample, rows in cleaned.groupby("sample", sort=False):
        if len(rows) < 2:
            continue
        for column in rows.columns:
            if column == "sample":
                continue
            values = rows[column].astype(str).drop_duplicates().tolist()
            if len(values) > 1:
                conflicting.append(f"{sample} ({column}: {', '.join(values)})")
                break
    if conflicting:
        raise ValueError(
            "Metadata assigns a sample to more than one value. Each sample must "
            "appear exactly once. Conflicts: "
            f"{'; '.join(conflicting[:10])}."
        )

    # An identically repeated row used to be dropped silently. It says the same
    # thing twice, so the annotation is unaffected -- but a metadata file that
    # repeats a sample was assembled wrong, and the same slip made against a
    # hand-built frame in the notebook packages doubles that sample's weight and
    # roughly halves the standard error. Reporting it here keeps the three
    # implementations to one rule: a sample appears once, or you hear about it.
    repeated = (
        cleaned.loc[cleaned["sample"].duplicated(keep=False), "sample"]
        .drop_duplicates()
        .tolist()
    )
    if repeated:
        raise ValueError(
            f"Metadata lists {len(repeated)} sample(s) more than once: "
            f"{', '.join(repeated[:10])}"
            f"{', and more' if len(repeated) > 10 else ''}. "
            "Each sample must appear exactly once; remove the duplicate rows."
        )

    cleaned = cleaned.reset_index(drop=True)
    if cleaned.empty:
        raise ValueError(
            "Uploaded metadata does not match any sample columns in the current dataset."
        )
    return cleaned


def _clean_string_series(series: pd.Series) -> pd.Series:
    return series.where(pd.notna(series), "").astype(str).str.strip()


def _make_unique_column_alias(raw_name: str, used_aliases: set[str]) -> str:
    alias = re.sub(r"\s+", "_", raw_name.strip())
    alias = re.sub(r"[^A-Za-z0-9_\-]", "", alias)
    alias = alias.strip("_-")
    if not alias:
        alias = "Metadata"

    candidate = alias
    index = 2
    lowered = {value.lower() for value in used_aliases}
    while candidate.lower() in lowered:
        candidate = f"{alias}_{index}"
        index += 1
    return candidate


def split_uploaded_metadata_profiles(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
) -> list[tuple[str, pd.DataFrame]]:
    """Turn each uploaded grouping column into one normalized source profile.

    ``sample`` identifies dataset columns and ``pair_id`` carries pairing
    structure. Every other column is categorical grouping information. Combined
    profiles are built later by the bounded metadata-profile store, so this path
    must not create subset columns itself.
    """
    if metadata.empty:
        raise ValueError("Uploaded metadata is empty.")

    source = metadata.copy()
    source.columns = [str(column).strip() for column in source.columns]
    column_map = {
        str(column).strip().lower(): str(column).strip()
        for column in source.columns
    }
    sample_col = _resolve_sample_column(column_map, source.columns)
    if sample_col is None:
        raise ValueError(
            "Uploaded metadata must contain a sample column "
            "(e.g. 'sample' or 'data_column_name')."
        )

    sample_key = str(sample_col).strip().lower()
    pair_col = column_map.get("pair_id")
    pair_key = str(pair_col).strip().lower() if pair_col is not None else None
    grouping_columns = [
        column
        for column in source.columns
        if str(column).strip().lower() not in {sample_key, pair_key}
    ]
    if not grouping_columns:
        raise ValueError(
            "Uploaded metadata must contain at least one grouping column besides "
            "'sample' and optional 'pair_id'."
        )
    if len(grouping_columns) > MAX_MANUAL_METADATA_PROFILES:
        raise ValueError(
            f"Uploaded metadata contains {len(grouping_columns)} grouping columns. "
            f"At most {MAX_MANUAL_METADATA_PROFILES} can be split into metadata profiles."
        )

    used_aliases: set[str] = {"sample"}
    profiles: list[tuple[str, pd.DataFrame]] = []
    for grouping_column in grouping_columns:
        profile_name = _make_unique_column_alias(str(grouping_column), used_aliases)
        used_aliases.add(profile_name)
        selected_columns = [sample_col, grouping_column]
        if pair_col is not None and pair_col not in selected_columns:
            selected_columns.append(pair_col)
        profile_input = source[selected_columns].copy()
        rename_map = {
            sample_col: "sample",
            grouping_column: "condition",
        }
        if pair_col is not None:
            rename_map[pair_col] = "pair_id"
        profile_input = profile_input.rename(columns=rename_map)
        normalized = normalize_uploaded_metadata(data=data, metadata=profile_input)
        output_columns = ["sample", "condition"]
        if "pair_id" in normalized.columns:
            output_columns.append("pair_id")
        profiles.append((profile_name, normalized[output_columns].copy()))
    return profiles


def _refuse_unreadable_samples(
    data: pd.DataFrame, sample_columns: list[str], unparseable: list[tuple[str, int, int]]
) -> None:
    """Refuse a matrix in which no sample value could be read as a number.

    A European export with decimal commas parses to a matrix of missing values.
    Auto-detection then asked for an explicit scale, and with one the annotation
    "succeeded" with zero rows. Neither helps; the locale is the problem.
    """
    numeric = data[[c for c in sample_columns if c in data.columns]].apply(pd.to_numeric, errors="coerce")
    if numeric.size and numeric.notna().any().any():
        return
    if unparseable:
        raise ValueError(
            "No sample value could be read as a number. " + _unparseable_warning(unparseable)
            + " Export the file with a decimal point and upload it again."
        )
    raise ValueError("The selected sample columns contain no numeric values.")


def _unparseable_warning(unparseable: list[tuple[str, int, int]]) -> str:
    detail = ", ".join(
        f"{column} ({lost} of {total})" for column, lost, total in unparseable[:6]
    )
    if len(unparseable) > 6:
        detail += f", and {len(unparseable) - 6} more"
    return (
        "Values that look like measurements could not be read as numbers and were "
        f"treated as missing in: {detail}. A decimal comma or a thousands separator "
        "does this to a whole column; check the export locale before interpreting "
        "these samples as undetected."
    )


def _dropped_samples_warning(dropped: list[str], annotated: int, source: str) -> str:
    preview = ", ".join(dropped[:10])
    if len(dropped) > 10:
        preview += f", and {len(dropped) - 10} more"
    return (
        f"{len(dropped)} {source} name a sample that is not a column in this dataset "
        f"and were ignored: {preview}. {annotated} sample(s) were annotated."
    )


def compute_annotation(
    data: pd.DataFrame,
    conditions: list[ConditionAssignment],
    is_log2_transformed: bool | None,
    min_present: int,
    filter_mode: FilterMode,
    filter_method="at_least_n",
    min_percentage=70.0,
    normalization: str = "none",
) -> AnnotationComputationResult:
    metadata_result = build_metadata_from_conditions(
        data,
        [{"name": c.name, "columns": c.columns} for c in conditions],
    )
    metadata = metadata_result.metadata
    auto_detected = metadata_result.auto_detected
    sample_columns = metadata["sample"].tolist()

    if not sample_columns:
        raise ValueError("No sample columns could be determined for metadata.")

    # Both annotation paths must report the same data-quality problems. Wiring
    # these into only one caller is how a locale-mangled column reached a volcano
    # plot with an empty warning list. Checked before the scale: a file whose
    # numbers could not be read has no scale to detect, and the error has to
    # say so rather than ask for an explicit scale setting.
    unparseable_columns = _unparseable_sample_columns(data, sample_columns)
    _refuse_unreadable_samples(data, sample_columns, unparseable_columns)
    resolved_log2, log2_auto_detected, log2_warning = resolve_log2_state(
        data,
        sample_columns,
        is_log2_transformed,
    )

    # Normalize before filtering so the log2 frame and the filtered frame that
    # derives from it both carry it. Modules differ in which one they read
    # (statistics uses filtered, comparison and single-protein use log2), so
    # normalizing only one would leave the app internally inconsistent.
    log2_data = prepare_normalized_log2_data(
        data,
        sample_columns,
        resolved_log2,
        normalization,
    )

    filtered_data = filter_data(
        log2_data,
        metadata,
        min_present=min_present,
        mode=filter_mode,
        method=filter_method,
        min_percentage=min_percentage,
    )

    annotated = {str(sample) for sample in sample_columns}
    # A name that only differed by surrounding whitespace was matched, not lost,
    # so it must not be reported as dropped.
    annotated_stripped = {sample.strip() for sample in annotated}
    dropped_columns = [
        str(column)
        for condition in conditions
        for column in condition.columns
        if str(column) not in annotated and str(column).strip() not in annotated_stripped
    ]

    warnings: list[str] = []
    if unparseable_columns:
        warnings.append(_unparseable_warning(unparseable_columns))
    identifier_warning = _identifier_warning(data)
    if identifier_warning:
        warnings.append(identifier_warning)
    warnings.extend(_table_shape_warnings(data))
    if dropped_columns:
        warnings.append(
            _dropped_samples_warning(
                dropped_columns, len(sample_columns), "assigned column(s)"
            )
        )
    if log2_warning:
        warnings.append(log2_warning)
    zero_warning = _log2_zero_warning(data, sample_columns, resolved_log2)
    if zero_warning:
        warnings.append(zero_warning)
    if auto_detected:
        warnings.append("Metadata was auto-generated from date-like column names.")
    warnings.append(_normalization_warning(normalization))
    missingness_warning = _missingness_warning(log2_data, metadata, normalization)
    if missingness_warning:
        warnings.append(missingness_warning)

    return AnnotationComputationResult(
        metadata=metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=resolved_log2,
        log2_auto_detected=log2_auto_detected,
        auto_detected=auto_detected,
        warnings=warnings,
    )


def compute_annotation_from_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    is_log2_transformed: bool | None,
    min_present: int,
    filter_mode: FilterMode,
    filter_method="at_least_n",
    min_percentage=70.0,
    normalization: str = "none",
) -> AnnotationComputationResult:
    normalized_metadata = normalize_uploaded_metadata(data=data, metadata=metadata)
    sample_columns = normalized_metadata["sample"].tolist()
    if not sample_columns:
        raise ValueError("No valid sample columns found in uploaded metadata.")

    # Rows naming a sample the dataset does not have are dropped rather than
    # rejected, because a shared metadata file legitimately covers more runs than
    # are loaded. Dropping them silently is the problem: three mistyped names turn
    # a balanced 6-vs-6 design into 6-vs-3, and every test result changes.
    unmatched_metadata_samples = _unmatched_metadata_samples(data, metadata, sample_columns)
    unparseable_columns = _unparseable_sample_columns(data, sample_columns)
    _refuse_unreadable_samples(data, sample_columns, unparseable_columns)

    resolved_log2, log2_auto_detected, log2_warning = resolve_log2_state(
        data,
        sample_columns,
        is_log2_transformed,
    )

    log2_data = prepare_normalized_log2_data(
        data,
        sample_columns,
        resolved_log2,
        normalization,
    )

    filtered_data = filter_data(
        log2_data,
        normalized_metadata,
        min_present=min_present,
        mode=filter_mode,
        method=filter_method,
        min_percentage=min_percentage,
    )

    warnings = ["Using uploaded metadata table for annotation."]
    if unparseable_columns:
        warnings.append(_unparseable_warning(unparseable_columns))
    identifier_warning = _identifier_warning(data)
    if identifier_warning:
        warnings.append(identifier_warning)
    warnings.extend(_table_shape_warnings(data))
    if unmatched_metadata_samples:
        warnings.append(
            _dropped_samples_warning(
                unmatched_metadata_samples,
                len(sample_columns),
                "uploaded metadata row(s)",
            )
        )
    if log2_warning:
        warnings.append(log2_warning)
    zero_warning = _log2_zero_warning(data, sample_columns, resolved_log2)
    if zero_warning:
        warnings.append(zero_warning)
    warnings.append(_normalization_warning(normalization))
    missingness_warning = _missingness_warning(log2_data, normalized_metadata, normalization)
    if missingness_warning:
        warnings.append(missingness_warning)

    return AnnotationComputationResult(
        metadata=normalized_metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=resolved_log2,
        log2_auto_detected=log2_auto_detected,
        auto_detected=False,
        warnings=warnings,
    )
