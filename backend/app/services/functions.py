from __future__ import annotations

import re
import json
import warnings
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.special import digamma, polygamma

from app.schemas.annotation import AnnotationKind
from app.schemas.completeness import CompletenessTablesResponse
from app.services.clustering_tools import require_complete_clustering_matrix
from app.services.runtime_cache import apply_cached_wrappers


def parse_selection_list(raw: str, *, legacy_semicolons: bool = False) -> list[str]:
    text = str(raw or "").strip()
    if text.startswith("["):
        values = json.loads(text)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Selections must be an array of strings.")
        return values
    if legacy_semicolons:
        text = text.replace(";", ",")
    return [value.strip() for value in text.split(",") if value.strip()]

try:
    from statsmodels.stats.multitest import multipletests
except ModuleNotFoundError:

    def multipletests(pvals, alpha=0.05, method="fdr_bh"):
        if method != "fdr_bh":
            raise ModuleNotFoundError(
                "statsmodels is required for multipletests methods other than 'fdr_bh'."
            )
        pvals = np.asarray(pvals, dtype=float)
        n = len(pvals)
        order = np.argsort(pvals)
        ranked = pvals[order]
        adjusted_ranked = ranked * n / np.arange(1, n + 1)
        adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
        adjusted = np.empty_like(adjusted_ranked)
        adjusted[order] = np.clip(adjusted_ranked, 0, 1)
        reject = adjusted <= alpha
        return reject, adjusted, None, None

FilterMode = Literal["per_group", "in_at_least_one_group", "overall"]
DataSource = Literal["filtered", "log2", "raw"]

AUTO_SAMPLE_PATTERN = re.compile(r"20\d{6}")
_SAMPLE_DOTTED_SUFFIX = re.compile(
    r"(?:(?:\.(?:PG|GG|EG|FG|PEP|PR|Precursor|Protein|Peptide))?\."
    r"(?:(?:Avg|Average)?Log[._\s-]*2(?:Normal(?:i[sz]ed|isation|ization))?"
    r"(?:Quantity|Intensity|Abundance)|Normal(?:i[sz]ed|isation|ization)"
    r"(?:Quantity|Intensity|Abundance)?|Max[._\s-]*LFQ(?:Quantity|Intensity|Abundance)?|"
    r"TotalQuantity|Quantity|Intensity|Abundance))$",
    re.IGNORECASE,
)
_SAMPLE_TEXT_SUFFIX = re.compile(
    r"[\s._-]+(?:(?:Max[\s._-]*LFQ[\s._-]+)?"
    r"(?:Unique[\s._-]+|Total[\s._-]+|Razor[\s._-]+)?Intensity|"
    r"(?:Unique[\s._-]+|Total[\s._-]+|Razor[\s._-]+)?Spectral[\s._-]+Count|"
    r"PSMs?|Percent[\s._-]+PSMs?|LFQ[\s._-]+Intensity|iBAQ|"
    r"MS\s*/\s*MS[\s._-]+Count|MS[12][\s._-]+(?:Intensity|Count)|"
    r"Razor\s*\+\s*Unique[\s._-]+Peptides|Unique[\s._-]+Peptides|Peptides|"
    r"Sequence[\s._-]+Coverage(?:[\s._-]*\[%\])?|"
    r"Log[._\s-]*2[\s._-]*(?:Quantity|Intensity|Abundance|Ratio)|"
    r"(?:Quantity|Abundance|Ratio))$",
    re.IGNORECASE,
)
_SAMPLE_ACQUISITION_SUFFIX = re.compile(r"\.(?:d|htrms|raw|wiff2?|mzml|mzxml)$", re.IGNORECASE)
_SAMPLE_NUMBER = re.compile(r"\d+")


@dataclass
class MetadataBuildResult:
    metadata: pd.DataFrame
    auto_detected: bool


@dataclass
class ImputationDiagnostics:
    imputed_data: pd.DataFrame
    missing_before: int
    missing_after: int
    mean: float
    std: float
    quantile: float
    before_without_missing: np.ndarray
    before_with_missing: np.ndarray
    overall_observed: np.ndarray
    after_non_imputed: np.ndarray
    after_imputed: np.ndarray
    draw_components: list[tuple[float, float, int]]
    skipped_samples: list[str]


def strip_sample_measurement_suffix(value):
    sample = re.split(r"[\\/]", str(value).strip())[-1]
    previous = None
    while sample != previous:
        previous = sample
        sample = _SAMPLE_DOTTED_SUFFIX.sub("", sample).rstrip()
        sample = _SAMPLE_TEXT_SUFFIX.sub("", sample).rstrip()
    return _SAMPLE_ACQUISITION_SUFFIX.sub("", sample).rstrip()


def extract_sample_id(value):
    original = str(value).strip()
    numbers = _SAMPLE_NUMBER.findall(strip_sample_measurement_suffix(original))
    return numbers[-1] if numbers else original


def sample_id_map(names) -> dict[str, str]:
    """Map extracted id -> name, refusing to guess when two names share an id.

    The id is only the *last* number in a name, so a run set following the common
    date_cellline_condition_replicate convention collapses every condition onto
    the same handful of ids -- 20240110_HeLa_ctrl_01.raw and
    20240110_HeLa_treat_01.raw are both "01". Resolving that by first-wins drops
    one whole condition, and renaming data columns to the id produces duplicate
    column labels that later select silently as the wrong sample.

    This fallback exists for the case where metadata and run names differ
    cosmetically; it is only sound when the ids are unique. When they are not,
    say so instead of picking one.
    """
    mapping: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for name in names:
        text = str(name)
        sample_id = extract_sample_id(text)
        if sample_id in mapping and mapping[sample_id] != text:
            collisions.setdefault(sample_id, [mapping[sample_id]]).append(text)
            continue
        mapping[sample_id] = text
    if collisions:
        detail = "; ".join(
            f"{' and '.join(repr(name) for name in sorted(names))} both reduce to '{key}'"
            for key, names in sorted(collisions.items())
        )
        raise ValueError(
            "Sample names cannot be matched by number because they are ambiguous: "
            f"{detail}. Sample matching falls back to the last number in a name, so "
            "names that differ only before that number are indistinguishable. Either "
            "use sample names in the annotation that match the run names exactly, or "
            "rename the runs so the trailing number is unique."
        )
    return mapping


def paired_sample_columns(
    metadata: pd.DataFrame,
    condition1: str,
    condition2: str,
) -> tuple[list[str], list[str]]:
    if str(condition1) == str(condition2):
        raise ValueError("Paired tests require two different conditions.")
    if "pair_id" not in metadata.columns:
        raise ValueError(
            "Paired tests require a 'pair_id' metadata column with one stable subject "
            "identifier per sample."
        )
    duplicate_samples = (
        metadata.loc[
            metadata["sample"].astype(str).duplicated(keep=False),
            "sample",
        ]
        .astype(str)
        .drop_duplicates()
        .tolist()
    )
    if duplicate_samples:
        raise ValueError(
            "Paired tests require each sample to appear once in metadata. "
            f"Duplicates: {', '.join(duplicate_samples)}."
        )

    def samples_by_id(condition: str) -> dict[str, str]:
        rows = metadata.loc[
            metadata["condition"].astype(str) == str(condition),
            ["sample", "pair_id"],
        ].copy()
        if rows.empty:
            raise ValueError(f"Condition '{condition}' does not have any annotated samples.")

        rows["sample"] = rows["sample"].astype(str)
        rows["pair_id"] = rows["pair_id"].where(rows["pair_id"].notna(), "").astype(str).str.strip()
        rows = rows.loc[rows["pair_id"] != ""]

        grouped: dict[str, list[str]] = {}
        for sample, pair_id in rows.itertuples(index=False, name=None):
            grouped.setdefault(pair_id, []).append(sample)

        duplicates = {key: values for key, values in grouped.items() if len(values) > 1}
        if duplicates:
            details = "; ".join(
                f"{key}: {', '.join(values)}" for key, values in sorted(duplicates.items())
            )
            raise ValueError(
                f"Paired tests require unique pair IDs within condition '{condition}'. "
                f"Duplicates: {details}."
            )
        return {key: values[0] for key, values in grouped.items()}

    left = samples_by_id(condition1)
    right = samples_by_id(condition2)
    pair_ids = [pair_id for pair_id in left if pair_id in right]
    if len(pair_ids) < 2:
        raise ValueError("Paired tests require at least two matched pair IDs.")
    return [left[key] for key in pair_ids], [right[key] for key in pair_ids]


# Design (paired or not) and variance model are separate choices, but the API has
# always carried a single `testType` string, so they are encoded as a flat enum.
# "unpaired" and "paired" keep their original meaning, so stored requests and
# saved reports continue to resolve to exactly the test they always did.
_TEST_TYPES: dict[str, tuple[bool, str]] = {
    "unpaired": (False, "pooled"),
    "unpaired_welch": (False, "welch"),
    "paired": (True, "pooled"),
}


def resolve_test_type(value) -> tuple[bool, str]:
    """Return (is_paired, variance_model) for a testType string."""
    mode = str(value).strip().lower()
    if mode not in _TEST_TYPES:
        raise ValueError(
            "test_type must be one of: " + ", ".join(sorted(_TEST_TYPES)) + "."
        )
    return _TEST_TYPES[mode]


def comparison_contrast(condition1, condition2, condition1_control=None, condition2_control=None) -> str:
    if condition1_control and condition2_control:
        return f"({condition2} - {condition2_control}) - ({condition1} - {condition1_control})"
    return f"{condition2} - {condition1}"


def paired_test_enabled(value) -> bool:
    return resolve_test_type(value)[0]


def variance_model(value) -> str:
    return resolve_test_type(value)[1]




def paired_t_test(differences: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    differences = np.asarray(differences, dtype=float)
    finite = np.isfinite(differences)
    n_pairs = finite.sum(axis=1).astype(float)
    clean = np.where(finite, differences, np.nan)
    mean_diff = np.nanmean(clean, axis=1)
    variance = np.nanvar(clean, axis=1, ddof=1)
    se = np.sqrt(variance / n_pairs)
    with np.errstate(divide="ignore", invalid="ignore"):
        pvalues = 2.0 * stats.t.sf(np.abs(mean_diff / se), n_pairs - 1.0)
    return mean_diff, n_pairs, np.asarray(pvalues, dtype=float)


# Data Pipeline
def build_metadata_from_conditions(
    data: pd.DataFrame,
    conditions: list[dict[str, object]],
) -> MetadataBuildResult:
    rows: list[dict[str, str]] = []
    used_samples: set[str] = set()

    # Resolve a requested column to a real one. An exact match always wins, so a
    # column whose name genuinely carries spaces still works; otherwise the name
    # is matched with surrounding whitespace ignored. Copying a header out of
    # Excel picks up a trailing space very easily, and without this the column is
    # dropped and a 5-vs-5 design quietly becomes 4-vs-5. The uploaded-metadata
    # path has always tolerated this; the two must not disagree.
    exact = {str(column) for column in data.columns}
    by_stripped: dict[str, str] = {}
    for column in data.columns:
        by_stripped.setdefault(str(column).strip(), str(column))

    for condition in conditions:
        name = str(condition.get("name", "")).strip()
        columns = condition.get("columns", [])
        if not name or not isinstance(columns, list):
            continue
        for col in columns:
            requested = str(col)
            sample = requested if requested in exact else by_stripped.get(requested.strip(), "")
            if not sample:
                continue
            if sample in used_samples:
                raise ValueError(f"Sample '{sample}' is assigned more than once. Assign each sample to exactly one condition.")
            rows.append({"sample": sample, "condition": name})
            used_samples.add(sample)

    if rows:
        return MetadataBuildResult(metadata=pd.DataFrame(rows), auto_detected=False)

    if conditions:
        raise ValueError("No valid condition assignments were provided. Select samples and name their conditions.")
    auto_columns = [str(col) for col in data.columns if AUTO_SAMPLE_PATTERN.search(str(col))]
    if not auto_columns:
        raise ValueError(
            "No valid condition assignments were provided and no auto-detectable sample "
            "columns were found (expected names like 20240131)."
        )
    auto_rows = [{"sample": col, "condition": "sample"} for col in auto_columns]
    return MetadataBuildResult(metadata=pd.DataFrame(auto_rows), auto_detected=True)


def raw_zero_to_nan(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    """Apply the raw-intensity missing-value convention to measurement columns.

    A zero in imported linear intensity data means "not detected".  This
    conversion belongs at the raw-data boundary only: zero is a valid value on
    log2 and other transformed scales (``2 ** 0 == 1``).  Restricting the
    conversion to declared sample columns also protects numeric annotations.
    """
    out = data.copy()
    present = [column for column in sample_columns if column in out.columns]
    if present:
        out[present] = (
            out[present]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf, 0], np.nan)
        )
    return out


def log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = raw_zero_to_nan(data[sample_columns], sample_columns)[sample_columns]
    log2_data = np.log2(selected)
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([log2_data, data[remaining]], axis=1)


def use_existing_log2_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    """Take an upload that is already on the log2 scale, as measurement columns.

    Non-finite values are missing, not observed. An upload can carry -inf: log2 of
    a zero, which is what the deprecated collapse variants write for a Spectronaut
    non-detection. `filter_data` counts with `notna()`, so an -inf survives the
    completeness filter as though it were a measurement and then yields an
    infinite fold change. The notebook package has always coerced these; the web
    app did not, so a file this application produced could corrupt an analysis
    without the user ever leaving it.
    """
    selected = (
        data[sample_columns]
        .copy()
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([selected, data[remaining]], axis=1)


def inverse_log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    original = 2 ** selected
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([original, data[remaining]], axis=1)


def _median_center(values: pd.DataFrame) -> pd.DataFrame:
    """Shift each sample so all samples share a common median.

    Operates on log2 values, where a multiplicative loading difference is an
    additive offset. Samples are re-centred on the grand median rather than on
    zero so the result stays on a recognisable intensity scale; that choice is a
    constant shift and does not affect any fold change.
    """
    medians = values.median(axis=0, skipna=True)
    grand_median = float(np.nanmedian(medians.to_numpy(dtype=float)))
    return values.sub(medians, axis=1).add(grand_median)


def _quantile_normalize(values: pd.DataFrame) -> pd.DataFrame:
    """Force every sample onto a common intensity distribution.

    Missing values are neither imputed nor allowed to shift a sample's ranks:
    each sample's observed values are mapped onto their own quantile positions,
    and the shared reference distribution is read off at those positions. This
    interpolates rather than dropping incomplete rows, so a feature missing in
    one sample still contributes everywhere it was measured.
    """
    from scipy.stats import rankdata

    numeric = values.apply(pd.to_numeric, errors="coerce")
    row_count = int(numeric.shape[0])
    if row_count == 0:
        return numeric

    # Grid spans the full row count so columns with different numbers of
    # observed values still land on a common reference curve.
    grid = np.linspace(0.0, 1.0, row_count)
    curves = []
    for column in numeric.columns:
        observed = np.sort(numeric[column].dropna().to_numpy(dtype=float))
        if observed.size == 0:
            continue
        positions = np.linspace(0.0, 1.0, observed.size) if observed.size > 1 else np.zeros(1)
        curves.append(np.interp(grid, positions, observed))
    if not curves:
        return numeric
    reference = np.mean(np.vstack(curves), axis=0)

    out = numeric.copy()
    for column in numeric.columns:
        mask = numeric[column].notna().to_numpy()
        observed = numeric[column].to_numpy(dtype=float)[mask]
        if observed.size == 0:
            continue
        # Average ranks, matching R's rank(), so ties map to one reference value.
        ranks = rankdata(observed, method="average")
        positions = (ranks - 1.0) / max(observed.size - 1, 1)
        out.loc[mask, column] = np.interp(positions, grid, reference)
    return out


def _normalization_sample_columns(
    data: pd.DataFrame,
    meta: "pd.DataFrame | pd.Series | list[str]",
) -> list[str]:
    """Resolve the columns to normalize from a metadata frame or a column list.

    The notebook package takes a metadata frame as the second argument in every
    other public function, so `normalize_data(data, meta, ...)` is the call people
    write. That used to resolve to no columns and return the input unchanged,
    which is indistinguishable from a successful normalization.
    """
    if isinstance(meta, pd.DataFrame):
        if "sample" not in meta.columns:
            raise ValueError(
                "Metadata must contain a 'sample' column naming the columns to normalize."
            )
        requested = [str(value) for value in meta["sample"].tolist()]
    elif isinstance(meta, pd.Series):
        requested = [str(value) for value in meta.tolist()]
    else:
        requested = [str(value) for value in meta]

    columns = {str(column) for column in data.columns}
    present = [column for column in requested if column in columns]
    missing = [column for column in requested if column not in columns]
    if not present:
        raise ValueError(
            "None of the requested sample columns are in the data, so nothing would "
            f"be normalized. Requested: {', '.join(requested[:6]) or '(nothing)'}."
        )
    if missing:
        raise ValueError(
            f"{len(missing)} requested sample column(s) are not in the data: "
            f"{', '.join(missing[:6])}. Normalizing only the rest would silently "
            "change the reference distribution."
        )
    return present


def normalize_data(
    data: pd.DataFrame,
    meta: "pd.DataFrame | pd.Series | list[str]",
    method: str = "none",
    linear_source: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Apply a global normalization to the sample columns of a log2 matrix.

    Always global. Normalising within conditions would remove exactly the
    differences the downstream tests are looking for.

    `linear_source` matters only for VSN, which models linear intensities.
    Reconstructing them as 2**log2 perturbs the input at machine epsilon
    (~6e-16), and VSN's fit is unstable enough on real data that this shifts the
    result by ~0.34 log2 units -- R disagrees with itself by the same amount on
    round-tripped input. Passing the untransformed upload keeps the result
    reproducible against a direct vsn2() call on the same file.

    References: quantile normalization follows the method of Bolstad et al. 2003, doi:10.1093/bioinformatics/19.2.185;
    VSN is delegated to the Bioconductor vsn package
    (Huber et al. 2002, doi:10.1093/bioinformatics/18.suppl_1.S96).
    """
    resolved = str(method or "none").strip().lower()
    if resolved in {"", "none"}:
        return data
    present = _normalization_sample_columns(data, meta)

    numeric = data[present].apply(pd.to_numeric, errors="coerce")
    if resolved == "median":
        normalized = _median_center(numeric)
    elif resolved == "quantile":
        normalized = _quantile_normalize(numeric)
    elif resolved == "vsn":
        # Delegated to Bioconductor vsn rather than reimplemented; see r_vsn.py
        # for why. Only reachable when Rscript and the package are present.
        from app.services.r_vsn import vsn_normalize_linear

        if linear_source is not None:
            linear = linear_source[present].apply(pd.to_numeric, errors="coerce")
            linear = linear.mask(linear == 0)
        else:
            linear = pd.DataFrame(
                np.power(2.0, numeric.to_numpy(dtype=float)),
                index=numeric.index,
                columns=numeric.columns,
            )
        normalized = vsn_normalize_linear(linear).where(linear.notna())
    else:
        raise ValueError("Normalization must be 'none', 'median', 'quantile', or 'vsn'.")

    out = data.copy()
    out[present] = normalized
    return out


def _validate_filter_thresholds(
    min_present: int,
    method: str,
    min_percentage: float,
) -> None:
    """Reject a threshold that is not a meaningful quantity.

    A filter that keeps nothing is a legitimate answer to a strict request, so
    only impossible values are refused: a percentage outside 0-100, or a negative
    count. Those cannot describe any completeness requirement.
    """
    if method == "percentage":
        try:
            value = float(min_percentage)
        except (TypeError, ValueError):
            raise ValueError(
                f"Minimum completeness percentage must be a number, got {min_percentage!r}."
            ) from None
        if not 0.0 <= value <= 100.0:
            raise ValueError(
                f"Minimum completeness percentage must be between 0 and 100, got {value:g}."
            )
        return

    try:
        value = int(min_present)
    except (TypeError, ValueError):
        raise ValueError(
            f"Minimum valid values must be a whole number, got {min_present!r}."
        ) from None
    if value < 0:
        raise ValueError(f"Minimum valid values must be zero or greater, got {value}.")


def _validate_meta_samples(metadata: pd.DataFrame) -> None:
    """Refuse metadata that names a sample more than once.

    A sample listed twice is counted twice by every group-wise mean and variance,
    which roughly halves the standard error while leaving the fold change
    untouched -- so nothing looks wrong and only the p-values move, downward. The
    upload path already rejects this, but restore and direct service calls reach
    here without passing through it, and the notebook packages have refused it
    since they gained the same guard.
    """
    if not isinstance(metadata, pd.DataFrame) or "sample" not in metadata.columns:
        return
    samples = metadata["sample"].astype(str).str.strip()
    repeated = samples[samples.duplicated(keep=False)].drop_duplicates().tolist()
    if repeated:
        raise ValueError(
            f"Metadata lists {len(repeated)} sample(s) more than once: "
            f"{', '.join(repeated[:10])}"
            f"{', and more' if len(repeated) > 10 else ''}. "
            "Each sample must appear exactly once; a repeated sample is counted "
            "twice and deflates every p-value."
        )


def filter_data(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    min_present: int,
    mode: FilterMode,
    method="at_least_n",
    min_percentage=70.0,
) -> pd.DataFrame:
    _validate_meta_samples(metadata)
    sample_columns = metadata["sample"].tolist()
    data_selected = data[sample_columns].copy()
    method = str(method or "at_least_n").strip().lower()
    if method not in {"at_least_n", "percentage"}:
        raise ValueError("Filter method must be 'at_least_n' or 'percentage'.")
    # The notebook package accepts "per group" and "per_group" alike; accepting only
    # one spelling here meant the same call worked in a notebook and failed in the
    # web app. Normalise, then validate.
    mode = str(mode or "").strip().lower().replace(" ", "_")
    if mode not in {"per_group", "in_at_least_one_group", "overall"}:
        raise ValueError("Filter mode must be 'per_group', 'in_at_least_one_group', or 'overall'.")
    _validate_filter_thresholds(min_present, method, min_percentage)

    if mode == "overall":
        valid = data_selected[sample_columns].notna().sum(axis=1)
        if method == "percentage":
            rows_to_keep = valid / len(sample_columns) >= min_percentage / 100
        else:
            rows_to_keep = valid >= min_present
    else:
        conditions = metadata["condition"].unique()
        mask = pd.DataFrame(False, index=data_selected.index, columns=conditions)
        for condition in conditions:
            cols = metadata.loc[metadata["condition"] == condition, "sample"].tolist()
            valid = data_selected[cols].notna().sum(axis=1)
            if method == "percentage":
                mask[condition] = valid / len(cols) >= min_percentage / 100
            else:
                mask[condition] = valid >= min_present
        rows_to_keep = mask.all(axis=1) if mode == "per_group" else mask.any(axis=1)
    return data.loc[rows_to_keep].reset_index(drop=True)


def choose_best_source(
    filtered_df: pd.DataFrame | None,
    log2_df: pd.DataFrame | None,
    raw_df: pd.DataFrame,
) -> tuple[DataSource, pd.DataFrame]:
    # Filtering preserves columns even when no rows pass. Only None or the
    # legacy schema-less placeholder means that no filtered matrix exists.
    if filtered_df is not None and len(filtered_df.columns) > 0:
        if filtered_df.empty:
            raise ValueError(
                "No features passed the selected filter. Adjust the filter in "
                "Data > Annotation and generate annotation again to continue. "
                "Unfiltered data has not been substituted."
            )
        return "filtered", filtered_df.copy()
    if log2_df is not None and not log2_df.empty:
        return "log2", log2_df.copy()
    return "raw", raw_df.copy()


def impute_values_with_diagnostics(
    data: pd.DataFrame,
    sample_columns: list[str],
    q: float = 0.01,
    adj_std: float = 0.3,
    seed: int = 1337,
    sample_wise: bool = True,
    method="quantile",
    down_shift=1.8,
    width=0.3,
) -> ImputationDiagnostics:
    method = str(method or "quantile").strip().lower()
    if method == "normal":
        method = "quantile"
    if method not in {"quantile", "numerical"}:
        raise ValueError("Imputation method must be 'quantile' or 'numerical'.")
    if down_shift < 0:
        raise ValueError("Numerical downshift must be zero or greater.")
    if width < 0:
        raise ValueError("Numerical width must be zero or greater.")
    # A request-local generator keeps seeded imputation reproducible without
    # mutating NumPy's process-global RNG or interfering with another session.
    rng = np.random.default_rng(seed)
    # This function receives an analysis-scale matrix.  Missing raw zeros have
    # already been converted while constructing that matrix; a transformed zero
    # is observed data and must not be imputed.
    numeric = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    missing_mask = numeric.isna()
    row_has_missing = missing_mask.any(axis=1)

    all_values = numeric.values.flatten()
    observed = all_values[~np.isnan(all_values)]

    before_without = numeric.loc[~row_has_missing].values.flatten()
    before_with = numeric.loc[row_has_missing].values.flatten()
    before_without = before_without[~np.isnan(before_without)]
    before_with = before_with[~np.isnan(before_with)]

    mean_val = float(np.mean(observed)) if observed.size else np.nan
    std_val = float(np.std(observed, ddof=1)) if observed.size > 1 else np.nan
    quantile_val = float(np.quantile(observed, q)) if observed.size else np.nan
    if not sample_wise and (observed.size < 2 or not np.isfinite(std_val) or std_val <= 0 or np.ptp(observed) == 0):
        raise ValueError("Global imputation requires at least two observed values with nonzero spread.")

    imputed_numeric = numeric.copy()
    missing_before = int(imputed_numeric.isna().sum().sum())
    draw_components = []
    skipped_samples = []

    if sample_wise:
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            col_observed = col_values.dropna().values
            if col_observed.size < 2 or np.ptp(col_observed) == 0:
                skipped_samples.append(str(col))
                continue
            col_sd = float(np.std(col_observed, ddof=1))
            if not np.isfinite(col_sd) or col_sd <= 0:
                skipped_samples.append(str(col))
                continue
            if method == "numerical":
                draw_center = float(np.mean(col_observed)) - down_shift * col_sd
                draw_std = col_sd * width
            else:
                draw_center = float(np.quantile(col_observed, q))
                draw_std = col_sd * adj_std
            draws = rng.normal(draw_center, draw_std, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws
            draw_components.append((draw_center, draw_std, missing_count))
    else:
        if method == "numerical":
            draw_center = mean_val - down_shift * std_val
            draw_std = std_val * width
        else:
            draw_center = quantile_val
            draw_std = std_val * adj_std
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            draws = rng.normal(draw_center, draw_std, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws
        if missing_before > 0:
            draw_components.append((draw_center, draw_std, missing_before))

    result = data.copy()
    result[sample_columns] = imputed_numeric
    missing_after = int(result[sample_columns].isna().sum().sum())

    after_imputed = imputed_numeric[missing_mask].values.flatten()
    after_non_imputed = imputed_numeric[~missing_mask].values.flatten()
    after_imputed = after_imputed[~np.isnan(after_imputed)]
    after_non_imputed = after_non_imputed[~np.isnan(after_non_imputed)]

    return ImputationDiagnostics(
        imputed_data=result,
        missing_before=missing_before,
        missing_after=missing_after,
        mean=mean_val,
        std=std_val,
        quantile=quantile_val,
        before_without_missing=before_without,
        before_with_missing=before_with,
        overall_observed=observed,
        after_non_imputed=after_non_imputed,
        after_imputed=after_imputed,
        draw_components=draw_components,
        skipped_samples=skipped_samples,
    )


DATA_SOURCE_CHOICES = ("auto", "log2", "filtered", "imputed")


def resolve_data_source_choice(data_source, default):
    """Canonical name for a requested matrix, shared by every pipeline.

    ``auto`` takes the first available of filtered, log2, raw. ``log2`` is the
    complete annotated matrix before filtering. ``filtered`` and ``imputed``
    name their materialized outputs.

    ``data`` is the historical spelling. It meant ``auto`` on the analysis path
    and ``log2`` on the visualization path, which is why it is resolved against
    a per-path default rather than to a fixed matrix.
    """
    requested = str(data_source or "data").strip().lower()
    if requested == "data":
        requested = str(default).strip().lower()
    if requested not in DATA_SOURCE_CHOICES:
        raise ValueError(
            "Unsupported data source. Choose 'auto', 'log2', 'filtered', or 'imputed'."
        )
    return requested


def _visualization_data_source(kind, data_source="log2"):
    """Select an explicit visualization matrix without silently substituting one.

    Defaults to ``log2``: the complete annotated matrix before filtering.
    ``filtered`` and ``imputed`` are only accepted when their materialized
    outputs exist; ``auto`` resolves the way the analysis path does.
    """
    from app.services.annotation_store import get_annotation
    from app.services.data_tools import _get_current_frame

    source_alias = str(data_source or "data").strip().lower()
    requested_source = resolve_data_source_choice(data_source, default="log2")

    _get_current_frame(kind)  # Preserve the existing loaded-dataset requirement.
    annotation = get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        raise ValueError(f"No annotation metadata available for {kind}. Generate annotation first.")

    if requested_source == "auto":
        source_used, frame, metadata, _ = analysis_data_source(kind, data_source="auto")
        return source_used, frame, metadata

    if requested_source == "log2":
        log2_data = getattr(annotation, "log2_data", None)
        if not isinstance(log2_data, pd.DataFrame) or log2_data.empty:
            raise ValueError(
                f"Log2 {kind} data is not available. Generate annotation first."
            )
        # The web UI's historical/public label is "data" even though its exact
        # matrix contract is the complete annotated log2 matrix.
        source_used = "data" if source_alias == "data" else "log2"
        return source_used, log2_data.copy(), annotation.metadata.copy()

    if requested_source == "filtered":
        filtered = getattr(annotation, "filtered_data", None)
        if not isinstance(filtered, pd.DataFrame) or filtered.empty:
            raise ValueError(
                f"Filtered {kind} data is not available. Generate annotation/filtering first."
            )
        return "filtered", filtered.copy(), annotation.metadata.copy()

    if not imputed_data_available(kind):
        raise ValueError(
            f"Imputed {kind} data is not available. Run imputation successfully first."
        )
    imputed = getattr(annotation, "imputed_data", None)
    return "imputed", imputed.copy(), annotation.metadata.copy()


def _visualization_data_source_availability(kind) -> dict[str, bool]:
    from app.services.annotation_store import get_annotation

    annotation = get_annotation(kind)
    filtered = getattr(annotation, "filtered_data", None) if annotation is not None else None
    return {
        "filteredAvailable": isinstance(filtered, pd.DataFrame) and not filtered.empty,
        "imputedAvailable": imputed_data_available(kind),
    }


def _phosprot_values_are_centred(kind) -> bool:
    """True when the stored frame holds ratios to each site's median, not abundances."""
    from app.services.annotation_store import get_annotation

    if kind != "phosprot":
        return False
    annotation = get_annotation(kind)
    aggregation = getattr(annotation, "phosprot_aggregation", None) if annotation else None
    return str(aggregation or "").strip().lower() == "robust_site_median"


def analysis_data_source(kind, data_source="auto"):
    """Select the matrix an analysis runs on.

    Defaults to ``auto``: filtered if filtering has run, else log2, else raw.
    ``log2``, ``filtered`` and ``imputed`` name one matrix each and raise when it
    does not exist.
    """
    from app.services.annotation_store import get_annotation
    from app.services.data_tools import _get_current_frame

    requested_source = resolve_data_source_choice(data_source, default="auto")

    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        raise ValueError(f"No annotation metadata available for {kind}. Generate annotation first.")

    if requested_source == "imputed":
        imputation = getattr(annotation, "imputation", None)
        imputation_mode = str(getattr(imputation, "mode", "none")).strip().lower()
        imputed_data = getattr(annotation, "imputed_data", None)
        if (
            imputation is None
            or imputation_mode == "none"
            or not isinstance(imputed_data, pd.DataFrame)
            or imputed_data.empty
        ):
            raise ValueError(
                f"Imputed {kind} data is not available. Run imputation successfully first."
            )
        sample_columns = annotation.metadata["sample"].astype(str).tolist()
        missing_samples = [sample for sample in sample_columns if sample not in imputed_data.columns]
        if missing_samples:
            raise ValueError(
                f"Stored imputed {kind} data is invalid because sample columns are missing: "
                f"{missing_samples}. Run imputation again."
            )
        return "imputed", imputed_data.copy(), annotation.metadata.copy(), []

    if requested_source == "log2":
        log2_data = getattr(annotation, "log2_data", None)
        if not isinstance(log2_data, pd.DataFrame) or log2_data.empty:
            raise ValueError(f"Log2 {kind} data is not available. Generate annotation first.")
        return "log2", log2_data.copy(), annotation.metadata.copy(), []

    if requested_source == "filtered":
        filtered = getattr(annotation, "filtered_data", None)
        if not isinstance(filtered, pd.DataFrame) or len(filtered.columns) == 0:
            raise ValueError(
                f"Filtered {kind} data is not available. Generate annotation/filtering first."
            )
        source_used, frame = choose_best_source(filtered, None, raw)
        return source_used, frame, annotation.metadata.copy(), []

    source_used, base_frame = choose_best_source(
        annotation.filtered_data,
        annotation.log2_data,
        raw,
    )
    warnings: list[str] = []
    if source_used == "raw":
        sample_columns = [
            sample
            for sample in annotation.metadata["sample"].astype(str).tolist()
            if sample in base_frame.columns
        ]
        if not bool(getattr(annotation, "is_log2_transformed", False)):
            base_frame = raw_zero_to_nan(base_frame, sample_columns)
        warnings.append("Using raw data because filtered/log2 annotated data is unavailable.")

    return source_used, base_frame, annotation.metadata.copy(), warnings


def imputed_data_available(kind):
    from app.services.annotation_store import get_annotation

    annotation = get_annotation(kind)
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


def anova_data_f(data, meta, conditions=None, in_pval=0.05, workflow="Protein", uncorrected=False):
    if workflow == "Protein":
        label_col = "ProteinNames"
    elif workflow == "Phosphosite":
        label_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        label_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    if conditions is None:
        conditions = meta["condition"].dropna().unique().tolist()
    if len(conditions) < 2:
        raise ValueError("ANOVA needs at least two conditions.")

    condition_cols = {
        condition: [col for col in meta.loc[meta["condition"] == condition, "sample"].tolist() if col in data.columns]
        for condition in conditions
    }
    too_few = [condition for condition, cols in condition_cols.items() if len(cols) < 2]
    if too_few:
        raise ValueError("Each ANOVA condition needs at least two sample columns. Missing: " + ", ".join(map(str, too_few)))

    sample_cols = [col for cols in condition_cols.values() for col in cols]
    cols_to_use = [label_col] + sample_cols

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].copy()
    df[sample_cols] = df[sample_cols].apply(pd.to_numeric, errors="coerce")

    valid = np.ones(len(df), dtype=bool)
    groups = []
    for cols in condition_cols.values():
        group = df[cols].to_numpy(dtype=float)
        valid &= np.sum(~np.isnan(group), axis=1) >= 2
        groups.append(group)

    df = df.loc[valid].copy()
    groups = [group[valid] for group in groups]
    if df.empty:
        return df.reset_index(drop=True)

    try:
        f_stat, pvals = stats.f_oneway(*groups, axis=1, nan_policy="omit")
    except TypeError:
        f_stat = np.empty(len(df), dtype=float)
        pvals = np.empty(len(df), dtype=float)
        for i in range(len(df)):
            row_groups = [group[i][~np.isnan(group[i])] for group in groups]
            f_stat[i], pvals[i] = stats.f_oneway(*row_groups)

    finite = np.isfinite(pvals)
    df = df.loc[finite].copy()
    groups = [group[finite] for group in groups]
    f_stat = f_stat[finite]
    pvals = pvals[finite]

    means = pd.DataFrame({
        condition: np.nanmean(group, axis=1)
        for condition, group in zip(condition_cols.keys(), groups)
    }, index=df.index)

    out = df[cols_to_use].copy()
    out["f_statistic"] = f_stat
    out["pval"] = pvals
    out["adj_pval"] = pvals if uncorrected else multipletests(pvals, method="fdr_bh")[1]
    out["significance"] = np.where(out["adj_pval"] < in_pval, "Significant", "Not significant")
    out["neg_log10_adj_pval"] = -np.log10(np.clip(out["adj_pval"], np.finfo(float).tiny, None))

    for condition in means.columns:
        out[f"mean_{condition}"] = means[condition].to_numpy()

    return out.sort_values("adj_pval").reset_index(drop=True)


def anova_cluster_data(anova_df, meta, n_clusters=4, in_pval=0.05, z_score=True, only_significant=True, cluster_method="average", cluster_metric="euclidean", cluster_col="cluster"):
    from scipy.cluster.hierarchy import fcluster

    if n_clusters < 1:
        raise ValueError("n_clusters must be at least 1.")

    sample_cols = [col for col in meta["sample"].astype(str).tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    if only_significant and "adj_pval" in anova_df.columns:
        cluster_df = anova_df[anova_df["adj_pval"] < in_pval].copy()
    else:
        cluster_df = anova_df.copy()

    if cluster_df.empty:
        cluster_df.insert(1, cluster_col, pd.Series(index=cluster_df.index, dtype="int64"))
        return cluster_df.reset_index(drop=True)

    matrix = cluster_df[sample_cols].to_numpy(dtype=float)
    if matrix.shape[0] > 1:
        require_complete_clustering_matrix(matrix, context="ANOVA")
    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd

    if matrix.shape[0] <= 1:
        cluster_df[cluster_col] = 1
        return cluster_df.reset_index(drop=True)

    row_linkage = linkage(matrix, method=cluster_method, metric=cluster_metric)
    row_order = leaves_list(row_linkage)
    raw_clusters = fcluster(row_linkage, t=n_clusters, criterion="maxclust")
    ordered_clusters = raw_clusters[row_order]

    cluster_map = {}
    relabeled_clusters = []
    for cluster_id in ordered_clusters:
        if cluster_id not in cluster_map:
            cluster_map[cluster_id] = len(cluster_map) + 1
        relabeled_clusters.append(cluster_map[cluster_id])

    cluster_df = cluster_df.iloc[row_order].copy()
    if cluster_col in cluster_df.columns:
        cluster_df = cluster_df.drop(columns=[cluster_col])
    cluster_df.insert(1, cluster_col, relabeled_clusters)
    return cluster_df.reset_index(drop=True)



def constant_within_group(values):
    """True per row where every observed replicate in the group holds one value.

    Such a row has no measured within-group variation, so the standard error
    collapses and the t-statistic explodes: a fold change of 0.05 can reach
    p = 2e-54 and outrank every genuine effect at the top of a volcano. The
    p-value itself is correct and matches `scipy.stats.ttest_ind`; what the flag
    marks is that the significance comes from absent variation rather than
    effect size. Values reported at a detection floor, rounded exports and
    imputation filling one value across replicates all produce it.

    Tested with min == max rather than variance == 0, which is exact regardless
    of floating-point representation: 14.05 repeated three times has a variance
    of 4.7e-30, not 0, so a zero test would miss it.
    """
    numeric = np.asarray(values, dtype=float)
    observed = np.isfinite(numeric)
    counts = observed.sum(axis=1)
    masked = np.where(observed, numeric, np.nan)
    with warnings.catch_warnings():
        # A row with nothing observed is an all-NaN slice; numpy warns and
        # returns NaN, and the count check below already excludes it.
        warnings.simplefilter("ignore", RuntimeWarning)
        low = np.nanmin(masked, axis=1)
        high = np.nanmax(masked, axis=1)
    return (counts > 0) & (low == high)


def condition_mean(data, columns, min_present=1):
    """Mean across a condition's replicates, blanked where too few were observed.

    `mean(axis=1)` skips missing values silently, so a condition mean resting on
    one replicate is plotted and correlated at the same weight as a fully
    observed one. Measured on 2000 features with 30% poor coverage, the
    single-replicate means were off by 0.28 log2 on average and 1.21 at worst
    against the same features' fully observed means.

    `min_present` is the smallest number of observations a mean may rest on. The
    default of 1 reports every mean, which is the long-standing behaviour and keeps
    previously generated results reproducible. Pass 2 or more to require that a
    mean rest on enough replicates to carry spread information.

    Returns (means, counts) so the caller can report how many features were
    excluded rather than dropping them silently.
    """
    numeric = data[list(columns)].apply(pd.to_numeric, errors="coerce")
    counts = numeric.notna().sum(axis=1)
    means = numeric.mean(axis=1)
    return means.where(counts >= int(min_present)), counts


def anova_posthoc_data(anova_df, meta, in_pval=0.05, only_significant=True, label_col=None):
    """Tukey HSD for every condition pair, following a one-way ANOVA.

    A significant omnibus F says only that some condition differs; this supplies the
    pairwise comparisons. Gated on the ANOVA result the way Perseus does it: the BH
    adjustment on the ANOVA controls error across features, and Tukey controls the
    family-wise rate across the condition pairs within each feature.

    Tukey-Kramer is used throughout, so unequal group sizes arising from missing
    values are handled correctly. Returns one row per feature and condition pair;
    an empty frame when fewer than three conditions are present, because with two
    the omnibus F and the single pairwise comparison test the same hypothesis.
    """
    if label_col is None:
        label_col = _auto_label_col(anova_df)

    conditions = meta["condition"].dropna().astype(str).unique().tolist()
    condition_cols = {}
    for condition in conditions:
        cols = [
            col
            for col in meta.loc[meta["condition"].astype(str) == condition, "sample"].astype(str).tolist()
            if col in anova_df.columns
        ]
        if cols:
            condition_cols[condition] = cols
    if len(condition_cols) < 3:
        return pd.DataFrame()

    if only_significant and "adj_pval" in anova_df.columns:
        posthoc_df = anova_df[anova_df["adj_pval"] < in_pval].copy()
    else:
        posthoc_df = anova_df.copy()
    if posthoc_df.empty:
        return pd.DataFrame()

    groups = {
        condition: posthoc_df[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        for condition, cols in condition_cols.items()
    }
    counts = {condition: np.sum(~np.isnan(group), axis=1).astype(float) for condition, group in groups.items()}
    means = {condition: np.nanmean(group, axis=1) for condition, group in groups.items()}

    # Pooled within-group variance across every condition, as the ANOVA itself uses.
    sum_squares = np.zeros(len(posthoc_df), dtype=float)
    for condition, group in groups.items():
        variance = np.nanvar(group, axis=1, ddof=1)
        sum_squares += np.where(counts[condition] > 1, (counts[condition] - 1) * np.nan_to_num(variance), 0.0)
    total_n = np.sum([counts[condition] for condition in condition_cols], axis=0)
    df_resid = total_n - len(condition_cols)
    with np.errstate(divide="ignore", invalid="ignore"):
        mse = np.where(df_resid > 0, sum_squares / df_resid, np.nan)

    labels = posthoc_df[label_col].astype(str).to_numpy()
    anova_adj = (
        posthoc_df["adj_pval"].to_numpy(dtype=float)
        if "adj_pval" in posthoc_df.columns
        else np.full(len(posthoc_df), np.nan)
    )
    names = list(condition_cols.keys())
    frames = []
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            left, right = names[first], names[second]
            n_left, n_right = counts[left], counts[right]
            with np.errstate(divide="ignore", invalid="ignore"):
                standard_error = np.sqrt(mse / 2.0 * (1.0 / n_left + 1.0 / n_right))
                difference = means[right] - means[left]
                q_statistic = np.abs(difference) / standard_error
            pvals = stats.studentized_range.sf(q_statistic, len(names), df_resid)
            pvals = np.where(np.isfinite(q_statistic) & (df_resid > 0), pvals, np.nan)
            usable = np.isfinite(pvals) & (n_left >= 2) & (n_right >= 2)
            if not np.any(usable):
                continue
            frames.append(pd.DataFrame({
                label_col: labels[usable],
                "comparison": f"{right} vs {left}",
                "group1": left,
                "group2": right,
                "log2FC": difference[usable],
                "n_group1": n_left[usable].astype(int),
                "n_group2": n_right[usable].astype(int),
                "q_statistic": q_statistic[usable],
                "tukey_pval": pvals[usable],
                "significance": np.where(pvals[usable] < in_pval, "Significant", "Not significant"),
                "anova_adj_pval": anova_adj[usable],
            }))

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["tukey_pval", label_col, "comparison"]).reset_index(drop=True)

def resolve_feature_scaling(scaling="auto", method="PCA"):
    """How features are weighted before a projection.

    ``centered`` subtracts each feature's mean across samples and stops there,
    so a feature contributes in proportion to its variance. ``unit_variance``
    also divides by the standard deviation, giving every feature equal weight.

    ``auto`` keeps each method's established default: PCA on the centred matrix,
    UMAP and t-SNE on unit-variance features because both read distances and are
    sensitive to feature scale. The two answer different questions, so a run that
    mixes them without saying which was used is not reproducible.
    """
    requested = str(scaling or "auto").strip().lower()
    if requested in {"centered", "centred"}:
        return "centered"
    if requested in {"unit_variance", "scaled"}:
        return "unit_variance"
    if requested != "auto":
        raise ValueError(
            "Unsupported scaling. Choose 'auto', 'centered', or 'unit_variance'."
        )
    return "centered" if str(method or "PCA").strip().lower() == "pca" else "unit_variance"


def intensity_unit_label(centered=False, scale="log2", workflow=""):
    unit = "Ratio to Site Median" if centered else "Intensity"
    return " ".join(part for part in (scale, workflow, unit) if part)


def abundance_axis_label(workflow, centered=False):
    """Y-axis label for the abundance plot.

    ``robust_site_median`` phosphoprotein aggregation centres every site on its
    own across-sample median, so those values carry a ratio to that median
    rather than an intensity. Every other phosprot mode, and both other
    workflows, hold real abundances.
    """
    return intensity_unit_label(centered, scale="log10", workflow=workflow)


def _auto_label_col(frame: pd.DataFrame) -> str:
    if "Phosphoprotein" in frame.columns:
        return "Phosphoprotein"
    if "ProteinNames" in frame.columns:
        return "ProteinNames"
    if "PTM_Collapse_key" in frame.columns:
        return "PTM_Collapse_key"
    if "Gene_group" in frame.columns:
        return "Gene_group"
    if "GeneNames" in frame.columns:
        return "GeneNames"
    raise ValueError("No supported label column was found.")


def anova_plot(
    anova_df,
    meta,
    in_pval=0.05,
    z_score=True,
    cluster_rows=True,
    cluster_samples=True,
    cluster_method="average",
    cluster_metric="euclidean",
    show_gene_names=False,
    show_condition_legend=False,
    show_dendrograms=True,
    width=12,
    height=10,
    dpi=150,
):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage

    if anova_df.empty:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.set_axis_off()
        ax.set_title("ANOVA heatmap")
        return fig

    label_col = _auto_label_col(anova_df)
    meta_plot = meta.copy()
    meta_plot["sample"] = meta_plot["sample"].astype(str)
    meta_plot["condition"] = meta_plot["condition"].astype(str)
    if "new_sample" in meta_plot.columns:
        meta_plot["plot_sample"] = meta_plot["new_sample"].astype(str)
    else:
        meta_plot["plot_sample"] = meta_plot["condition"] + "_" + (meta_plot.groupby("condition").cumcount() + 1).astype(str)

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    plot_df = anova_df[anova_df["adj_pval"] < in_pval].copy() if "adj_pval" in anova_df.columns else anova_df.copy()
    if plot_df.empty:
        plot_df = anova_df.copy()

    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    if (cluster_rows and raw_matrix.shape[0] > 1) or (
        cluster_samples and raw_matrix.shape[1] > 1
    ):
        require_complete_clustering_matrix(raw_matrix, context="ANOVA heatmap")
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd
        cmap = "RdBu_r"
        color_label = "row z-score"
        vmin, vmax = -2.5, 2.5
    else:
        cmap = "viridis"
        color_label = "intensity"
        vmin = vmax = None

    display_mask = missing_mask | ~np.isfinite(matrix)
    display_matrix = np.ma.array(matrix, mask=display_mask)
    cluster_matrix = matrix.copy()
    row_linkage = None
    col_linkage = None

    if cluster_rows and matrix.shape[0] > 1:
        row_linkage = linkage(cluster_matrix, method=cluster_method, metric=cluster_metric)
        row_order = leaves_list(row_linkage)
        display_matrix = display_matrix[row_order]
        cluster_matrix = cluster_matrix[row_order]
        labels = [labels[i] for i in row_order]
        plot_df = plot_df.iloc[row_order]

    if cluster_samples and matrix.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method=cluster_method, metric=cluster_metric)
        col_order = leaves_list(col_linkage)
        display_matrix = display_matrix[:, col_order]
        sample_cols = [sample_cols[i] for i in col_order]

    sample_to_condition = dict(zip(meta_plot["sample"], meta_plot["condition"]))
    sample_to_label = dict(zip(meta_plot["sample"], meta_plot["plot_sample"]))
    conditions = [sample_to_condition.get(sample, "") for sample in sample_cols]
    x_labels = [sample_to_label.get(sample, sample) for sample in sample_cols]

    unique_conditions = list(dict.fromkeys(conditions))
    palette = plt.cm.tab20(np.linspace(0, 1, max(len(unique_conditions), 1)))
    condition_colors = {condition: palette[i % len(palette)] for i, condition in enumerate(unique_conditions)}
    condition_strip = np.array([[condition_colors[condition] for condition in conditions]])

    fig = plt.figure(figsize=(width, height), dpi=dpi)
    grid = fig.add_gridspec(3, 3, height_ratios=[0.16, 0.025, 1.0], width_ratios=[0.10, 1.0, 0.035], hspace=0.02, wspace=0.03)
    ax_corner = fig.add_subplot(grid[0, 0])
    ax_col_dendrogram = fig.add_subplot(grid[0, 1])
    ax_top_blank = fig.add_subplot(grid[0, 2])
    ax_strip_left = fig.add_subplot(grid[1, 0])
    ax_strip = fig.add_subplot(grid[1, 1])
    ax_strip_right = fig.add_subplot(grid[1, 2])
    ax_row_dendrogram = fig.add_subplot(grid[2, 0])
    ax = fig.add_subplot(grid[2, 1])
    cax = fig.add_subplot(grid[2, 2])

    for blank_ax in [ax_corner, ax_top_blank, ax_strip_left, ax_strip_right]:
        blank_ax.set_axis_off()

    if show_dendrograms and col_linkage is not None:
        dendrogram(col_linkage, ax=ax_col_dendrogram, no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_col_dendrogram.set_axis_off()

    if show_dendrograms and row_linkage is not None:
        dendrogram(row_linkage, ax=ax_row_dendrogram, orientation="left", no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_row_dendrogram.set_axis_off()

    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()

    plot_cmap = plt.get_cmap(cmap).copy()
    plot_cmap.set_bad("#d8d8d8")
    image = ax.imshow(display_matrix, aspect="auto", interpolation="nearest", cmap=plot_cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel("samples")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(sample_cols)))
    ax.set_xticklabels(x_labels, rotation=90, fontsize=5)
    if show_gene_names:
        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=5)
    else:
        ax.set_yticks([])

    colorbar = fig.colorbar(image, cax=cax)
    colorbar.set_label(color_label)

    legend_handles = [Patch(facecolor=condition_colors[condition], label=condition) for condition in unique_conditions]
    if show_condition_legend and legend_handles:
        ax_top_blank.legend(handles=legend_handles, loc="upper left", frameon=False, fontsize=7, borderaxespad=0)

    fig.suptitle(f"ANOVA heatmap ({len(plot_df)} rows)", y=0.965)
    fig.subplots_adjust(left=0.04, right=0.90, top=0.91, bottom=0.16)
    return fig


def anova_plot_cluster(
    anova_cluster_df,
    meta,
    cluster_col="cluster",
    z_score=True,
    cluster_samples=True,
    cluster_method="average",
    cluster_metric="euclidean",
    show_gene_names=False,
    show_condition_legend=False,
    show_cluster_legend=True,
    max_cluster_legend=12,
    show_dendrogram=True,
    width=12,
    height=10,
    dpi=150,
):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from scipy.cluster.hierarchy import dendrogram, leaves_list, linkage

    if cluster_col not in anova_cluster_df.columns:
        raise ValueError(f"anova_cluster_df must contain a '{cluster_col}' column from anova_cluster_data().")
    if anova_cluster_df.empty:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.set_axis_off()
        ax.set_title("ANOVA cluster heatmap")
        return fig

    label_col = _auto_label_col(anova_cluster_df)
    meta_plot = meta.copy()
    meta_plot["sample"] = meta_plot["sample"].astype(str)
    meta_plot["condition"] = meta_plot["condition"].astype(str)
    if "new_sample" in meta_plot.columns:
        meta_plot["plot_sample"] = meta_plot["new_sample"].astype(str)
    else:
        meta_plot["plot_sample"] = meta_plot["condition"] + "_" + (meta_plot.groupby("condition").cumcount() + 1).astype(str)

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_cluster_df.columns]
    if not sample_cols:
        raise ValueError("anova_cluster_df must contain the original sample columns from anova_data_f().")

    plot_df = anova_cluster_df.copy()
    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    if cluster_samples and raw_matrix.shape[1] > 1:
        require_complete_clustering_matrix(raw_matrix, context="ANOVA cluster heatmap")
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        row_mean = np.nanmean(matrix, axis=1, keepdims=True)
        row_sd = np.nanstd(matrix, axis=1, keepdims=True)
        row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1
        matrix = (matrix - row_mean) / row_sd
        cmap = "RdBu_r"
        color_label = "row z-score"
        vmin, vmax = -2.5, 2.5
    else:
        cmap = "viridis"
        color_label = "intensity"
        vmin = vmax = None

    display_matrix = np.ma.array(matrix, mask=missing_mask | ~np.isfinite(matrix))
    cluster_matrix = matrix.copy()
    col_linkage = None
    if cluster_samples and matrix.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method=cluster_method, metric=cluster_metric)
        col_order = leaves_list(col_linkage)
        display_matrix = display_matrix[:, col_order]
        sample_cols = [sample_cols[i] for i in col_order]

    sample_to_condition = dict(zip(meta_plot["sample"], meta_plot["condition"]))
    sample_to_label = dict(zip(meta_plot["sample"], meta_plot["plot_sample"]))
    conditions = [sample_to_condition.get(sample, "") for sample in sample_cols]
    x_labels = [sample_to_label.get(sample, sample) for sample in sample_cols]

    unique_conditions = list(dict.fromkeys(conditions))
    condition_palette = plt.cm.tab20(np.linspace(0, 1, max(len(unique_conditions), 1)))
    condition_colors = {condition: condition_palette[i % len(condition_palette)] for i, condition in enumerate(unique_conditions)}
    condition_strip = np.array([[condition_colors[condition] for condition in conditions]])

    cluster_values = plot_df[cluster_col].tolist()
    unique_clusters = list(dict.fromkeys(cluster_values))
    cluster_palette = plt.cm.tab20b(np.linspace(0, 1, max(len(unique_clusters), 1)))
    cluster_colors = {cluster: cluster_palette[i % len(cluster_palette)] for i, cluster in enumerate(unique_clusters)}
    cluster_strip = np.array([[cluster_colors[cluster]] for cluster in cluster_values])

    fig = plt.figure(figsize=(width, height), dpi=dpi)
    grid = fig.add_gridspec(3, 4, height_ratios=[0.16, 0.025, 1.0], width_ratios=[0.025, 1.0, 0.035, 0.12], hspace=0.02, wspace=0.04)
    ax_col_dendrogram = fig.add_subplot(grid[0, 1])
    ax_strip = fig.add_subplot(grid[1, 1])
    ax_cluster = fig.add_subplot(grid[2, 0])
    ax = fig.add_subplot(grid[2, 1])
    cax = fig.add_subplot(grid[2, 2])
    ax_legend = fig.add_subplot(grid[:, 3])
    ax_legend.set_axis_off()

    if show_dendrogram and col_linkage is not None:
        dendrogram(col_linkage, ax=ax_col_dendrogram, no_labels=True, color_threshold=0, above_threshold_color="black", link_color_func=lambda _: "black")
    ax_col_dendrogram.set_axis_off()
    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()
    ax_cluster.imshow(cluster_strip, aspect="auto", interpolation="nearest")
    ax_cluster.set_axis_off()

    plot_cmap = plt.get_cmap(cmap).copy()
    plot_cmap.set_bad("#d8d8d8")
    image = ax.imshow(display_matrix, aspect="auto", interpolation="nearest", cmap=plot_cmap, vmin=vmin, vmax=vmax)
    ax.set_xlabel("samples")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(sample_cols)))
    ax.set_xticklabels(x_labels, rotation=90, fontsize=5)
    if show_gene_names:
        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=5)
    else:
        ax.set_yticks([])

    colorbar = fig.colorbar(image, cax=cax)
    colorbar.set_label(color_label)

    legend_handles = []
    if show_cluster_legend:
        legend_handles.extend([Patch(facecolor=cluster_colors[cluster], label=f"cluster {cluster}") for cluster in unique_clusters[:max_cluster_legend]])
    if show_condition_legend:
        legend_handles.extend([Patch(facecolor=condition_colors[condition], label=condition) for condition in unique_conditions])
    if legend_handles:
        ax_legend.legend(handles=legend_handles, loc="upper left", frameon=False, fontsize=7, borderaxespad=0)

    fig.suptitle(f"ANOVA cluster heatmap ({len(plot_df)} rows)", y=0.965)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.91, bottom=0.16)
    return fig

def histogram(values: np.ndarray, bins: int = 30) -> list[tuple[float, float, int]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    counts, edges = np.histogram(clean, bins=bins)
    return [(float(edges[i]), float(edges[i + 1]), int(counts[i])) for i in range(len(counts))]


def comparative_histogram(
    left_values: np.ndarray,
    right_values: np.ndarray,
    bins: int = 30,
) -> list[tuple[float, float, int, int]]:
    left_clean = left_values[~np.isnan(left_values)]
    right_clean = right_values[~np.isnan(right_values)]
    combined = np.concatenate([left_clean, right_clean]) if left_clean.size or right_clean.size else np.array([])
    if combined.size == 0:
        return []
    _, edges = np.histogram(combined, bins=bins)
    left_counts, _ = np.histogram(left_clean, bins=edges)
    right_counts, _ = np.histogram(right_clean, bins=edges)
    return [
        (float(edges[i]), float(edges[i + 1]), int(left_counts[i]), int(right_counts[i]))
        for i in range(len(edges) - 1)
    ]


def normal_fit_curve(values: np.ndarray, points: int = 200, ddof: int = 0) -> list[tuple[float, float]]:
    clean = values[~np.isnan(values)]
    if clean.size <= ddof:
        return []
    std_val = float(np.std(clean, ddof=ddof))
    if std_val <= 0:
        return []
    mean_val = float(np.mean(clean))
    x = np.linspace(np.min(clean), np.max(clean), points)
    y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
    return [(float(px), float(py)) for px, py in zip(x, y)]


def qqnorm_plot_data(
    values: np.ndarray,
    max_points: int = 100_000,
    seed: int = 187,
) -> dict[str, list[tuple[float, float]]]:
    clean = values[~np.isnan(values)]
    clean = clean[clean > 0]
    if clean.size == 0:
        return {"points": [], "fitLine": []}

    if clean.size > max_points:
        rng = np.random.default_rng(seed)
        clean = rng.choice(clean, max_points, replace=False)

    clean = np.sort(clean)
    n = clean.size
    normal = NormalDist()

    theoretical = np.array([normal.inv_cdf((i - 0.5) / n) for i in range(1, n + 1)])
    sample = clean.astype(float)

    if n < 2:
        return {
            "points": [(float(theoretical[0]), float(sample[0]))],
            "fitLine": [],
        }

    slope, intercept = np.polyfit(theoretical, sample, 1)
    x0, x1 = float(np.min(theoretical)), float(np.max(theoretical))
    y0, y1 = float(slope * x0 + intercept), float(slope * x1 + intercept)

    return {
        "points": [(float(tx), float(sy)) for tx, sy in zip(theoretical, sample)],
        "fitLine": [(x0, y0), (x1, y1)],
    }


# Imputation Pipeline
def imputation_before_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_before_plot as _impl

    return _impl(
        kind,
        q_value,
        adjust_std,
        seed,
        sample_wise,
        method=method,
        down_shift=down_shift,
        width=width,
        advanced=advanced,
    )


def imputation_overall_fit_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    show_imputation_draw: bool = True,
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_overall_fit_plot as _impl

    return _impl(
        kind,
        q_value,
        adjust_std,
        seed,
        sample_wise,
        show_imputation_draw,
        method=method,
        down_shift=down_shift,
        width=width,
        advanced=advanced,
    )


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    normalization: str = "separate",
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import imputation_after_plot as _impl

    return _impl(
        kind,
        q_value,
        adjust_std,
        seed,
        sample_wise,
        normalization,
        method=method,
        down_shift=down_shift,
        width=width,
        advanced=advanced,
    )


# Distribution Pipeline
def distribution_qqnorm_plot(
    kind: AnnotationKind,
    random_seed: int = 187,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import distribution_qqnorm_plot as _impl

    return _impl(kind, random_seed=random_seed, advanced=advanced)


# Completeness Pipeline
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
    from app.services.completeness_tools import completeness_missing_value_plot as _impl

    return _impl(
        kind=kind,
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
    from app.services.completeness_tools import completeness_missing_value_plot_peptide as _impl

    return _impl(
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        quantity_column=quantity_column,
    )


def completeness_missing_value_plot_precursor(
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
    from app.services.completeness_tools import completeness_missing_value_plot_precursor as _impl

    return _impl(
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        quantity_column=quantity_column,
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
    from app.services.completeness_tools import completeness_missing_value_heatmap as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def completeness_tables(
    kind: AnnotationKind,
    outlier_threshold: float = 50.0,
    include_id: bool = True,
) -> CompletenessTablesResponse:
    from app.services.completeness_tools import completeness_tables as _impl

    return _impl(
        kind=kind,
        outlier_threshold=outlier_threshold,
        include_id=include_id,
    )


# QC Pipeline
def qc_coverage_plot(
    kind: AnnotationKind,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    text_size: int = 9,
    random_seed: int = 187,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_coverage_plot as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        legend=legend,
        summary=summary,
        text=text,
        text_size=text_size,
        random_seed=random_seed,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_peptide_coverage_plot(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
    quantity_column: str | None = None,
    level: str = "peptide",
) -> bytes:
    from app.services.plot_images import qc_peptide_coverage_plot as _impl

    return _impl(
        include_id=include_id,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        quantity_column=quantity_column,
        level=level,
    )


def qc_intensity_histogram_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_intensity_histogram_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_boxplot_plot(
    kind: AnnotationKind,
    mode: str = "Mean",
    outliers: bool = False,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_boxplot_plot as _impl

    return _impl(
        kind=kind,
        mode=mode,
        outliers=outliers,
        include_id=include_id,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_cv_plot(
    kind: AnnotationKind,
    outliers: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_cv_plot as _impl

    return _impl(
        kind=kind,
        outliers=outliers,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_pca_plot(
    kind: AnnotationKind,
    data_source: str = "data",
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 5,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    scaling: str = "auto",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_pca_plot as _impl

    return _impl(
        kind=kind,
        data_source=data_source,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        method=method,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        color_by=color_by,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        dbscan_eps=dbscan_eps,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
        scaling=scaling,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_pca_interactive_html(
    kind: AnnotationKind,
    data_source: str = "data",
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 8,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    scaling: str = "auto",
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict | None = None,
) -> str:
    from app.services.plot_images import qc_pca_interactive_html as _impl

    return _impl(
        kind=kind,
        data_source=data_source,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        method=method,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        color_by=color_by,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        dbscan_eps=dbscan_eps,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
        scaling=scaling,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
    )


def qc_abundance_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_abundance_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        condition=condition,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def qc_abundance_interactive_html(
    kind: AnnotationKind,
    condition: str = "All Conditions",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict | None = None,
) -> str:
    from app.services.plot_images import qc_abundance_interactive_html as _impl

    return _impl(
        kind=kind,
        condition=condition,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
    )


def qc_correlation_plot(
    kind: AnnotationKind,
    method: str = "Matrix",
    include_id: bool = False,
    full_range: bool = False,
    width_cm: float = 20,
    height_cm: float = 16,
    dpi: int = 400,
    advanced: dict | None = None,
) -> bytes:
    from app.services.plot_images import qc_correlation_plot as _impl

    return _impl(
        kind=kind,
        method=method,
        include_id=include_id,
        full_range=full_range,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


# Single Protein Pipeline
def single_protein_boxplot_plot(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    outliers: bool = False,
    dots: bool = False,
    random_seed: int = 69,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
    data_source: str = "data",
    sample_n: bool = True,
) -> bytes:
    from app.services.single_protein_tools import single_protein_boxplot_plot as _impl

    return _impl(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
        outliers=outliers,
        dots=dots,
        random_seed=random_seed,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        data_source=data_source,
        sample_n=sample_n,
    )


def single_protein_lineplot_plot(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    include_id: bool = False,
    identifier: str = "workflow",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict | None = None,
    data_source: str = "data",
) -> bytes:
    from app.services.single_protein_tools import single_protein_lineplot_plot as _impl

    return _impl(
        kind=kind,
        proteins=proteins,
        conditions=conditions,
        include_id=include_id,
        identifier=identifier,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        data_source=data_source,
    )


def single_protein_heatmap_plot(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    include_id: bool = False,
    header: bool = True,
    filter_m1: bool = True,
    cluster_rows: bool = False,
    cluster_cols: bool = False,
    value_type: str = "log2",
    cmap_name: str = "plasma",
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
    data_source: str = "data",
) -> bytes:
    from app.services.single_protein_tools import single_protein_heatmap_plot as _impl

    return _impl(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
        include_id=include_id,
        header=header,
        filter_m1=filter_m1,
        cluster_rows=cluster_rows,
        cluster_cols=cluster_cols,
        value_type=value_type,
        cmap_name=cmap_name,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        data_source=data_source,
    )


# Phospho-specific Pipeline
def phosphosite_plot_png(
    cutoff: float = 0.0,
    color: str = "#87CEEB",
    width_cm: float = 15,
    height_cm: float = 10,
    dpi: int = 100,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phosphosite_plot_png as _impl

    return _impl(
        cutoff=cutoff,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def phospho_coverage_png(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: str = "Normal",
    color_class_i: str = "#2563eb",
    color_not_class_i: str = "#f59e0b",
    random_seed: int = 69,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    conditions: list[str] | None = None,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_coverage_png as _impl

    return _impl(
        include_id=include_id,
        header=header,
        legend=legend,
        mode=mode,
        color_class_i=color_class_i,
        color_not_class_i=color_not_class_i,
        random_seed=random_seed,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        conditions=conditions,
        advanced=advanced,
    )


def phospho_distribution_png(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    width_cm: float = 20,
    height_cm: float = 15,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_distribution_png as _impl

    return _impl(
        cutoff=cutoff,
        header=header,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


def phospho_sty_png(
    header: bool = True,
    width_cm: float = 17.78,
    height_cm: float = 11.43,
    dpi: int = 140,
    advanced: dict | None = None,
) -> bytes:
    from app.services.phospho_tools import phospho_sty_png as _impl

    return _impl(
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
    )


# Comparison Pipeline
def comparison_pearson_png(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 60,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
    data_source: str = "data",
) -> bytes:
    from app.services.comparison_tools import pearson_correlation_png as _impl

    return _impl(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
        alias1=alias1,
        alias2=alias2,
        color=color,
        dot_size=dot_size,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        data_source=data_source,
    )


def comparison_pearson_html(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 8,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    advanced: dict | None = None,
    data_source: str = "data",
) -> str:
    from app.services.comparison_tools import pearson_correlation_html as _impl

    return _impl(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
        alias1=alias1,
        alias2=alias2,
        color=color,
        dot_size=dot_size,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        advanced=advanced,
        data_source=data_source,
    )


def comparison_venn_png(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
    color1: str = "#1f77b4",
    color2: str = "#ff7f0e",
    color3: str = "#2ca02c",
    header: bool = True,
    width_cm: float = 15,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
    data_source: str = "data",
) -> bytes:
    from app.services.comparison_tools import venn_png as _impl

    return _impl(
        kind=kind,
        mode=mode,
        first=first,
        second=second,
        third=third,
        alias1=alias1,
        alias2=alias2,
        alias3=alias3,
        color1=color1,
        color2=color2,
        color3=color3,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
        advanced=advanced,
        data_source=data_source,
    )


apply_cached_wrappers(
    globals(),
    [
        "imputation_before_plot",
        "imputation_overall_fit_plot",
        "imputation_after_plot",
        "distribution_qqnorm_plot",
        "completeness_missing_value_plot",
        "completeness_missing_value_plot_peptide",
        "completeness_missing_value_plot_precursor",
        "completeness_missing_value_heatmap",
        "completeness_tables",
        "qc_coverage_plot",
        "qc_peptide_coverage_plot",
        "qc_intensity_histogram_plot",
        "qc_boxplot_plot",
        "qc_cv_plot",
        "qc_pca_plot",
        "qc_pca_interactive_html",
        "qc_abundance_plot",
        "qc_abundance_interactive_html",
        "qc_correlation_plot",
        "single_protein_boxplot_plot",
        "single_protein_lineplot_plot",
        "single_protein_heatmap_plot",
        "phosphosite_plot_png",
        "phospho_coverage_png",
        "phospho_distribution_png",
        "phospho_sty_png",
        "comparison_pearson_png",
        "comparison_pearson_html",
        "comparison_venn_png",
    ],
)
