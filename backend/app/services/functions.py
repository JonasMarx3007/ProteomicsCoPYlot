from __future__ import annotations

import re
import json
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

import numpy as np
import pandas as pd
import scipy.stats as stats


def parse_selection_list(raw: str, *, accept_semicolons: bool = False) -> list[str]:
    """A JSON array, or a comma-separated list.

    `accept_semicolons` is for lists a language model wrote: asked for several
    names it returns "A; B" about as often as "A, B", and that is a live habit
    rather than an old file format.
    """
    text = str(raw or "").strip()
    if text.startswith("["):
        values = json.loads(text)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Selections must be an array of strings.")
        return values
    if accept_semicolons:
        text = text.replace(";", ",")
    return [value.strip() for value in text.split(",") if value.strip()]


FilterMode = Literal["per_group", "in_at_least_one_group", "overall"]
# What `choose_best_source` reports. Narrower than the schema's
# ResolvedSource because this helper only ever sees these three.
ChosenSource = Literal["filtered", "log2", "raw"]

AUTO_SAMPLE_PATTERN = re.compile(r"20\d{6}")
# Match the trailing measurement field, not words inside the acquisition name.
_AUTO_QUANTITY_PATTERN = re.compile(r"(?:quantity|intensity|abundance|area|lfq)\s*$", re.IGNORECASE)
_AUTO_STATISTIC_PATTERN = re.compile(
    r"(?:^|[._\s-])(?:q[._ -]?value|p[._ -]?value|nrof\w*|"
    r"[a-z]*counts?|identified|[a-z]*score|pep)\s*$",
    re.IGNORECASE,
)


def _auto_sample_columns(columns) -> list[str]:
    """Dated columns that hold sample quantities, for annotation without conditions."""
    dated = [
        str(column) for column in columns
        if AUTO_SAMPLE_PATTERN.search(str(column)) and not _AUTO_STATISTIC_PATTERN.search(str(column))
    ]
    quantities = [column for column in dated if _AUTO_QUANTITY_PATTERN.search(column)]
    return quantities or dated


# <shared-core> proteomicscopylot/_core.py, one copy for the app and the pip
# package. Notebook exports inline these definitions here (notebook_source.module_source).
from app.services.copylot_core import (  # re-exported: `name as name`
    _SAMPLE_DOTTED_SUFFIX as _SAMPLE_DOTTED_SUFFIX,
    _SAMPLE_TEXT_SUFFIX as _SAMPLE_TEXT_SUFFIX,
    _SAMPLE_ACQUISITION_SUFFIX as _SAMPLE_ACQUISITION_SUFFIX,
    _SAMPLE_NUMBER as _SAMPLE_NUMBER,
    strip_sample_measurement_suffix as strip_sample_measurement_suffix,
    extract_sample_id as extract_sample_id,
    _significance_pval_column as _significance_pval_column,
    constant_within_group as constant_within_group,
    condition_mean as condition_mean,
    resolve_feature_scaling as resolve_feature_scaling,
    _auto_label_col as _auto_label_col,
)
# </shared-core>


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


# What a row of each dataset level actually is. Reports and explanations should
# say "1,204 phosphosites", never "1,204 features": the noun is the difference
# between a sentence a reader can check and one they cannot.
ENTITY_LABELS_BY_KIND: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phospho": ("phosphosite", "phosphosites"),
    "phosprot": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
    "precursor": ("precursor", "precursors"),
}


def entity_labels_for_kind(kind) -> tuple[str, str]:
    """(singular, plural) name for one row of a dataset level."""
    key = str(kind).strip().lower()
    return ENTITY_LABELS_BY_KIND.get(key, ENTITY_LABELS_BY_KIND["protein"])


def condition_sample_labels(frame: pd.DataFrame) -> pd.Series:
    """``condition_N`` per row: N is the sample's 1-based place inside its condition.

    Every plot renames its sample columns this way. The expression was written
    out in six places, including inside `sample_label_frame`, whose whole job is
    to be the one copy the report's sample-mapping table can be trusted against.
    """
    return frame["condition"].astype(str) + "_" + (frame.groupby("condition").cumcount() + 1).astype(str)


def sample_label_frame(metadata: pd.DataFrame) -> pd.DataFrame:
    """Original sample name -> the generic ``condition_N`` label used in plots.

    Every plot renames its sample columns to ``{condition}_{n}``, where ``n`` is
    the sample's 1-based position among the samples of its own condition, in
    metadata order. The plot paths each compute that inline as
    ``groupby("condition").cumcount() + 1``; this is the same rule in one place,
    so the report's sample-mapping table cannot drift from the axis labels it
    claims to explain.

    Ordering note: the protein/phospho plot paths sort by condition before
    numbering, the peptide path does not. The sort is stable and grouping by
    condition preserves each condition's internal order either way, so the
    number a sample receives is identical. `tests/unit/data/test_sample_mapping.py`
    holds the two to that.

    Returns the columns ``sample``, ``condition``, ``label`` and ``pair_id``
    (empty strings when the annotation carries no pairing), in metadata order.
    """
    columns = ["sample", "condition", "label", "pair_id"]
    if metadata is None or metadata.empty:
        return pd.DataFrame(columns=columns)
    if "sample" not in metadata.columns or "condition" not in metadata.columns:
        return pd.DataFrame(columns=columns)

    frame = metadata.copy()
    frame["sample"] = frame["sample"].astype(str).str.strip()
    frame["condition"] = frame["condition"].astype(str).str.strip()
    frame = frame[(frame["sample"] != "") & (frame["condition"] != "")]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = frame.reset_index(drop=True)

    frame["label"] = condition_sample_labels(frame)
    if "pair_id" in frame.columns:
        frame["pair_id"] = frame["pair_id"].fillna("").astype(str).str.strip()
    else:
        frame["pair_id"] = ""
    return frame[columns].reset_index(drop=True)


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


def unpaired_samples_note(metadata: pd.DataFrame, condition1: str, condition2: str) -> str | None:
    """One sentence naming the samples a paired test leaves out, or None.

    `paired_sample_columns` keeps only the pair IDs both conditions share and
    says nothing about the rest, so a sample whose partner is missing -- a gap in
    the uploaded metadata, or a pair ID changed for another comparison -- was
    dropped silently. Call after
    `paired_sample_columns` has accepted the metadata.
    """
    if "pair_id" not in metadata.columns:
        return None
    left_samples, right_samples = paired_sample_columns(metadata, condition1, condition2)
    used = set(left_samples) | set(right_samples)
    left_out: list[str] = []
    for condition in (condition1, condition2):
        rows = metadata.loc[metadata["condition"].astype(str) == str(condition), "sample"].astype(str)
        left_out.extend(sample for sample in rows if sample not in used)
    if not left_out:
        return None
    return (
        f"Paired test: {len(left_out)} sample(s) without a partner left out: "
        + ", ".join(left_out)
        + "."
    )


# Design (paired or not) and variance model are separate choices, but the API has
# always carried a single `testType` string, so they are encoded as a flat enum.
# "unpaired" and "paired" keep their original meaning, so stored requests and
# saved reports continue to resolve to exactly the test they always did.
_TEST_TYPES: dict[str, tuple[bool, str]] = {
    "unpaired": (False, "pooled"),
    "unpaired_welch": (False, "welch"),
    "paired": (True, "pooled"),
    # limma empirical-Bayes moderation (R only; see r_limma.py). "robust"
    # fits the variance prior robustly, so outlying rows do not set it.
    "moderated": (False, "moderated"),
    "moderated_robust": (False, "moderated_robust"),
    "moderated_paired": (True, "moderated"),
    "moderated_robust_paired": (True, "moderated_robust"),
}
MODERATED_VARIANCE_MODELS = ("moderated", "moderated_robust")


def is_moderated_test_type(value) -> bool:
    """Whether a testType runs in R limma rather than in the tool's own arithmetic."""
    try:
        return resolve_test_type(value)[1] in MODERATED_VARIANCE_MODELS
    except ValueError:
        return False


def resolve_test_type(value) -> tuple[bool, str]:
    """Return (is_paired, variance_model) for a testType string."""
    mode = str(value).strip().lower()
    if mode not in _TEST_TYPES:
        raise ValueError(
            "test_type must be one of: " + ", ".join(sorted(_TEST_TYPES)) + "."
        )
    return _TEST_TYPES[mode]


def effective_test_type(test_type, *, with_controls: bool) -> str:
    """The test a control-corrected volcano actually runs.

    With controls, the "unpaired" (pooled Student's t) choice is computed as a
    Welch-type test: the four groups' variances are propagated separately with
    Satterthwaite degrees of freedom, because a pooled two-group standard error
    would omit the controls' uncertainty. The page sends "unpaired_welch" for
    that case already; this makes any other caller record the same name, so the
    notebook settings and the assistant evidence state the test that ran.
    """
    mode = str(test_type).strip().lower()
    if with_controls and mode == "unpaired":
        return "unpaired_welch"
    return mode


def comparison_contrast(condition1, condition2, condition1_control=None, condition2_control=None) -> str:
    if condition1_control and condition2_control:
        return f"({condition1} - {condition1_control}) - ({condition2} - {condition2_control})"
    return f"{condition1} - {condition2}"


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
    auto_columns = _auto_sample_columns(data.columns)
    if not auto_columns:
        raise ValueError(
            "No valid condition assignments were provided and no auto-detectable sample "
            "columns were found (expected names like 20240131)."
        )
    auto_rows = [{"sample": col, "condition": "sample"} for col in auto_columns]
    return MetadataBuildResult(metadata=pd.DataFrame(auto_rows), auto_detected=True)


def condition_cvs(values: pd.DataFrame, meta: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    """Per-condition coefficient of variation in percent: 100 * SD / mean of each
    row's observed linear values (sample SD, ddof = 1). Conditions with fewer than
    two samples are skipped and non-finite CVs are dropped. The CV plot and its
    table both use this."""
    result: list[tuple[str, pd.Series]] = []
    conditions = meta["condition"].astype(str)
    for condition in conditions.dropna().unique().tolist():
        cols = meta.loc[conditions == condition, "sample"].tolist()
        if len(cols) < 2:
            continue
        subset = values[cols]
        cv = subset.std(axis=1, skipna=True) / subset.mean(axis=1, skipna=True) * 100.0
        cv = cv[np.isfinite(cv)]
        if len(cv):
            result.append((condition, cv))
    return result


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


def _median_center(values: pd.DataFrame, fit_rows: pd.Index | None = None) -> pd.DataFrame:
    """Shift each sample so all samples share a common median.

    Operates on log2 values, where a multiplicative loading difference is an
    additive offset. Samples are re-centred on the grand median rather than on
    zero so the result stays on a recognisable intensity scale; that choice is a
    constant shift and does not affect any fold change.

    The medians are taken over `fit_rows` (the filtered rows) when given and the
    shift is applied to every row, so rows the filter removed never set the
    reference but still land on the same scale.
    """
    reference = values if fit_rows is None else values.loc[fit_rows]
    medians = reference.median(axis=0, skipna=True)
    grand_median = float(np.nanmedian(medians.to_numpy(dtype=float)))
    return values.sub(medians, axis=1).add(grand_median)


def _quantile_normalize(values: pd.DataFrame, fit_rows: pd.Index | None = None) -> pd.DataFrame:
    """Force every sample onto a common intensity distribution.

    Missing values are neither imputed nor allowed to shift a sample's ranks:
    each sample's observed values are mapped onto their own quantile positions,
    and the shared reference distribution is read off at those positions. This
    interpolates rather than dropping incomplete rows, so a feature missing in
    one sample still contributes everywhere it was measured.

    With `fit_rows`, the reference distribution and each sample's quantile
    mapping are learned from those rows only; every other row is then placed by
    interpolating its value into its sample's learned mapping, so the filtered
    rows decide the transformation and the rest follow it.
    """
    from scipy.stats import rankdata

    numeric = values.apply(pd.to_numeric, errors="coerce")
    reference_frame = numeric if fit_rows is None else numeric.loc[fit_rows]
    row_count = int(reference_frame.shape[0])
    if row_count == 0:
        return numeric

    # Grid spans the full row count so columns with different numbers of
    # observed values still land on a common reference curve.
    grid = np.linspace(0.0, 1.0, row_count)
    curves = []
    for column in numeric.columns:
        observed = np.sort(reference_frame[column].dropna().to_numpy(dtype=float))
        if observed.size == 0:
            continue
        positions = np.linspace(0.0, 1.0, observed.size) if observed.size > 1 else np.zeros(1)
        curves.append(np.interp(grid, positions, observed))
    if not curves:
        return numeric
    reference = np.mean(np.vstack(curves), axis=0)

    out = numeric.copy()
    for column in numeric.columns:
        fit_values = reference_frame[column].dropna().to_numpy(dtype=float)
        if fit_values.size == 0:
            continue
        # Average ranks, matching R's rank(), so ties map to one reference value.
        ranks = rankdata(fit_values, method="average")
        positions = (ranks - 1.0) / max(fit_values.size - 1, 1)
        mapped = np.interp(positions, grid, reference)
        if fit_rows is None:
            mask = numeric[column].notna().to_numpy()
            out.loc[mask, column] = mapped
            continue
        # The learned monotone mapping value -> normalized value for this sample,
        # applied to every observed value in the column (the fit rows reproduce
        # their own mapping exactly; other rows interpolate into it).
        order = np.argsort(fit_values, kind="stable")
        xs, ys = fit_values[order], mapped[order]
        xs_unique, first = np.unique(xs, return_index=True)
        ys_unique = ys[first]
        mask = numeric[column].notna().to_numpy()
        column_values = numeric[column].to_numpy(dtype=float)[mask]
        out.loc[mask, column] = np.interp(column_values, xs_unique, ys_unique)
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


def anchor_vsn_level(glog_values: pd.DataFrame, log2_values: pd.DataFrame) -> pd.DataFrame:
    """Pin VSN's output to the level of the plain log2 data.

    vsn's model is glog(a*x + b) and its profile likelihood is flat on real
    data, so two fits of nearly identical input -- the same file with one
    rounding digit changed, or 2**log2 of a log2 upload -- reach solutions that
    differ by a constant added to every value (1.22 log2 on the HEK293 example,
    with a residual of 3e-4 once that constant is removed). The constant carries
    no information: every fold change, variance, correlation and p-value is the
    same under it. Subtracting it makes the output reproducible and leaves it on
    a log2-like scale a reader recognises. One global shift, never per sample,
    so the between-sample calibration vsn fitted is untouched.
    """
    glog = glog_values.to_numpy(dtype=float)
    plain = log2_values.to_numpy(dtype=float)
    both = np.isfinite(glog) & np.isfinite(plain)
    if not both.any():
        return glog_values
    offset = float(np.nanmedian(glog[both]) - np.nanmedian(plain[both]))
    return glog_values - offset


def normalize_data(
    data: pd.DataFrame,
    meta: "pd.DataFrame | pd.Series | list[str]",
    method: str = "none",
    linear_source: pd.DataFrame | None = None,
    fit_rows: "pd.Index | None" = None,
) -> pd.DataFrame:
    """Apply a global normalization to the sample columns of a log2 matrix.

    Always global. Normalising within conditions would remove exactly the
    differences the downstream tests are looking for.

    `fit_rows` names the rows the normalization is learned from -- the rows the
    valid-value filter kept -- while the learned transformation is applied to
    every row. Rows with many missing values are mostly low-abundance features
    that are missing more in one group than the other; letting them set the
    reference pulled unchanged proteins apart by up to 0.5 log2 units. Fitting on the filtered rows removes that, and
    applying to all rows keeps the unfiltered "data" matrix on the same scale
    as the filtered one. Without `fit_rows` every row is used, as before.

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
    if fit_rows is not None:
        fit_rows = numeric.index.intersection(pd.Index(fit_rows))
        if len(fit_rows) == len(numeric.index):
            fit_rows = None  # every row kept: identical to the plain fit
    if resolved == "median":
        normalized = _median_center(numeric, fit_rows)
    elif resolved == "quantile":
        normalized = _quantile_normalize(numeric, fit_rows)
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
        normalized = vsn_normalize_linear(linear, fit_rows=fit_rows).where(linear.notna())
        normalized = anchor_vsn_level(normalized, numeric)
    else:
        raise ValueError("Normalization must be 'none', 'median', 'quantile', or 'vsn'.")

    out = data.copy()
    out[present] = normalized
    return out


MISSINGNESS_GAP = 0.10
MISSINGNESS_MIN_COMPLETE = 20
_MISSINGNESS_METHOD_LABELS = {"median": "Median centering", "quantile": "Quantile normalization", "vsn": "VSN"}


def missingness_imbalance(
    data: pd.DataFrame,
    meta: "pd.DataFrame | pd.Series | list[str]",
    min_gap: float = MISSINGNESS_GAP,
    min_complete: int = MISSINGNESS_MIN_COMPLETE,
) -> pd.DataFrame:
    """Per-sample missingness, and how far each sample sits on the complete features.

    Median and quantile normalization use every observed value of a sample.
    Missing values are mostly low-abundance, so a sample with many more of them
    has a higher observed median and is shifted down. A sample is flagged when
    its share of missing values is at least `min_gap` above the most complete
    sample. `complete_offset` is the sample's median distance from the row
    median over the features measured in every sample: after normalization it
    shows the shift those features carry. It is NaN when fewer than
    `min_complete` features are complete. Pass the normalized matrix to see the
    shift the normalization left; missing positions are the same before and after.
    """
    present = _normalization_sample_columns(data, meta)
    numeric = data[present].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.where(np.isfinite(numeric))
    missing = numeric.isna().mean(axis=0) if len(numeric) else pd.Series(0.0, index=present)
    reference = float(missing.min()) if len(missing) else 0.0
    complete = numeric.dropna(axis=0, how="any")
    if len(complete) >= int(min_complete):
        offsets = complete.sub(complete.median(axis=1), axis=0).median(axis=0)
    else:
        offsets = pd.Series(np.nan, index=present)
    conditions = pd.Series(np.nan, index=present, dtype=object)
    if isinstance(meta, pd.DataFrame) and "condition" in meta.columns:
        lookup = dict(zip(meta["sample"].astype(str), meta["condition"]))
        conditions = pd.Series([lookup.get(str(sample)) for sample in present], index=present, dtype=object)
    return pd.DataFrame({
        "sample": present,
        "condition": conditions.to_numpy(),
        "missing_fraction": missing.reindex(present).to_numpy(dtype=float),
        "reference_missing_fraction": reference,
        "flagged": (missing.reindex(present).to_numpy(dtype=float) - reference) >= float(min_gap) - 1e-12,
        "complete_features": int(len(complete)),
        "complete_offset": offsets.reindex(present).to_numpy(dtype=float),
    })


def missingness_imbalance_warning(
    table: pd.DataFrame,
    method: str,
    min_gap: float = MISSINGNESS_GAP,
) -> str | None:
    """The warning for `missingness_imbalance`, or None when there is nothing to say.

    Median centering, quantile normalization and VSN are concerned: all are
    fitted on each sample's observed values.
    """
    label = _MISSINGNESS_METHOD_LABELS.get(str(method or "none").strip().lower())
    if label is None or table.empty or not bool(table["flagged"].any()):
        return None
    flagged = table[table["flagged"]].sort_values("missing_fraction", ascending=False, kind="mergesort")
    others = table[~table["flagged"]]
    listed = [f"{sample} ({fraction * 100:.0f}%)"
              for sample, fraction in zip(flagged["sample"].head(6), flagged["missing_fraction"].head(6))]
    if len(flagged) > 6:
        listed.append(f"and {len(flagged) - 6} more")
    message = (
        f"Missing values differ strongly between samples: {len(flagged)} of {len(table)} samples have at "
        f"least {min_gap * 100:.0f} percentage points more missing values than the most complete sample "
        f"({float(table['reference_missing_fraction'].iloc[0]) * 100:.0f}%): {', '.join(listed)}. "
        f"{label} uses each sample's observed values, and missing values are mostly low-abundance, "
        "so these samples can be shifted down."
    )
    if flagged["complete_offset"].notna().all() and len(others) and others["complete_offset"].notna().all():
        shift = float(flagged["complete_offset"].mean() - others["complete_offset"].mean())
        message += (
            f" On the {int(table['complete_features'].iloc[0]):,} features measured in every sample, they sit "
            f"{abs(shift):.2f} log2 {'below' if shift < 0 else 'above'} the other samples after normalization."
        )
    conditions = flagged["condition"].dropna().astype(str).unique().tolist()
    if len(conditions) == 1 and flagged["condition"].notna().all():
        message += (
            f" All of them are in condition {conditions[0]}, so fold changes involving "
            f"{conditions[0]} may carry this shift."
        )
    return message + " Check these samples before interpreting fold changes."


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
    rows_to_keep = filter_mask(data, metadata, min_present, mode, method, min_percentage)
    return data.loc[rows_to_keep].reset_index(drop=True)


def filter_mask(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    min_present: int,
    mode: FilterMode,
    method="at_least_n",
    min_percentage=70.0,
) -> pd.Series:
    """Which rows of `data` the valid-value filter keeps, on `data`'s own index.

    `filter_data` returns the kept rows re-indexed from 0; the normalization fit
    needs them by their original labels, so the decision lives here.
    """
    _validate_meta_samples(metadata)
    sample_columns = metadata["sample"].tolist()
    data_selected = data[sample_columns].copy()
    method = str(method or "at_least_n").strip().lower()
    if method not in {"at_least_n", "percentage"}:
        raise ValueError("Filter method must be 'at_least_n' or 'percentage'.")
    # All three implementations spell it `per_group` and still read the older
    # "per group"; accepting only one spelling here once meant the same call
    # worked in a notebook and failed in the web app. Normalise, then validate.
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
    return rows_to_keep


def choose_best_source(
    filtered_df: pd.DataFrame | None,
    log2_df: pd.DataFrame | None,
    raw_df: pd.DataFrame,
) -> tuple[ChosenSource, pd.DataFrame]:
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


LOCALIZATION_COLUMN = "PTM_localization"


def filter_localization(frame, cutoff=0.0, column=LOCALIZATION_COLUMN):
    """Rows whose localization probability is at least `cutoff`.

    A cutoff of 0 keeps every row, including rows without a probability. Above
    0 a row without a probability (missing, non-numeric or outside 0..1) is
    dropped: it cannot be shown to pass. A table without the column cannot be
    filtered, so a positive cutoff on it is an error rather than a silent no-op.
    Mirrored by `filter_localization` in the pip package and the R helpers.
    """
    cutoff = float(cutoff)
    if not 0.0 <= cutoff <= 1.0:
        raise ValueError("The localization probability cutoff must be between 0 and 1.")
    if cutoff <= 0.0:
        return frame.copy()
    if column not in frame.columns:
        raise ValueError(
            f"A localization probability cutoff of {cutoff:.2f} needs a '{column}' column, "
            "which this phosphosite table does not have."
        )
    probability = pd.to_numeric(frame[column], errors="coerce")
    probability = probability.where(probability.between(0.0, 1.0))
    return frame.loc[probability >= cutoff].copy()


IMPUTED_COUNT_PREFIX = "n_imputed__"
IMPUTED_TOTAL_COLUMN = "imputed_values"


def imputed_cell_mask(values, observed=None):
    """Classify cells: -1 missing, 0 measured, 1 fully imputed, 2 partially imputed.

    Ordinary intensities are measured or fully imputed. Collapsed values use
    site_observed_imputed_mask to distinguish mixed contributions. None means
    provenance is unavailable, not that nothing was imputed.
    """
    present = values.apply(pd.to_numeric, errors="coerce").notna()
    if observed is not None:
        before = observed.reindex(index=values.index, columns=values.columns)
        before = before.apply(pd.to_numeric, errors="coerce")
        # -1: missing, 0: measured, 1: fully imputed, 2: partially imputed.
        return before.isna().astype(int).where(present, -1)
    return None


def site_observed_imputed_mask(frame, sample_columns):
    """Classify direct per-sample site contributions, not cross-sample centering effects.

    Measured contributors and supplied site counts are required. Without them provenance
    is unknown, not evidence of no imputation. Missing/unknown cells are -1.
    Older tables only carry site_observed__ counts; new collapses keep coverage
    there and record actual measured contributors separately in site_measured__.
    """
    prefix = "site_measured__" if any(str(c).startswith("site_measured__") for c in frame.columns) else "site_observed__"
    columns = [f"{prefix}{sample}" for sample in sample_columns]
    supplied_columns = [f"site_supplied__{sample}" for sample in sample_columns]
    if not all(column in frame.columns for column in columns + supplied_columns):
        return None
    present = frame[sample_columns].apply(pd.to_numeric, errors="coerce").notna()
    measured = frame[columns].apply(pd.to_numeric, errors="coerce").to_numpy()
    supplied = frame[supplied_columns].apply(pd.to_numeric, errors="coerce").to_numpy()
    known = np.isfinite(measured) & np.isfinite(supplied) & (supplied > 0) & (measured >= 0) & (measured <= supplied)
    states = np.where(measured == 0, 1, np.where(measured < supplied, 2, 0))
    return pd.DataFrame(states, index=frame.index, columns=sample_columns).where(present & known, -1)


def imputed_value_counts(mask, groups):
    """Count measured, fully imputed and partially imputed values per condition.

    n_imputed__<group> and imputed_values include both imputed categories.
    Missing/unknown cells are not counted as measured. Statistical calculations
    are unchanged; imputed values still enter tests as observations.
    """
    counts = pd.DataFrame(index=mask.index)
    total = np.zeros(len(mask), dtype=int)
    for group, columns in groups.items():
        values = mask[list(columns)]
        for state, name in ((0, "measured"), (1, "fully_imputed"), (2, "partially_imputed")):
            counts[f"n_{name}__{group}"] = values.eq(state).sum(axis=1).astype(int).to_numpy()
        column_count = values.isin([1, 2]).sum(axis=1).astype(int).to_numpy()
        counts[f"{IMPUTED_COUNT_PREFIX}{group}"] = column_count
        total = total + column_count
    counts[IMPUTED_TOTAL_COLUMN] = total
    return counts


def constant_differences(differences):
    """`constant_within_group` for paired differences, ignoring float subtraction noise.

    14.05 - 12.0 and 15.05 - 13.0 differ in the last bits, so the differences
    are compared at nine decimals, far below any measured log2 difference.
    """
    return constant_within_group(np.round(np.asarray(differences, dtype=float), 9))


def without_variation(groups):
    """Rows where every variance component is constant: the standard error is zero.

    The t statistic is then undefined, not infinite, so these rows get no
    p-value (shown as "Unavailable") instead of p = 0 ranking them first.
    """
    return np.logical_and.reduce([constant_within_group(group) for group in groups])


def anova_posthoc_data(anova_df, meta, in_pval=0.05, only_significant=True, label_col=None, pair=None):
    """Tukey HSD for every condition pair, following a one-way ANOVA.

    A significant omnibus F says only that some condition differs; this supplies the
    pairwise comparisons. Gated on the ANOVA result the way Perseus does it: the BH
    adjustment on the ANOVA controls error across features, and Tukey controls the
    family-wise rate across the condition pairs within each feature.

    Tukey-Kramer is used throughout, so unequal group sizes arising from missing
    values are handled correctly. Returns one row per feature and condition pair;
    an empty frame when fewer than three conditions are present, because with two
    the omnibus F and the single pairwise comparison test the same hypothesis.

    `pair` restricts which comparison is *reported*, not how it is computed: the
    studentized range still takes k from every condition in the design and the
    MSE is still pooled across all of them, so a pair computed alone is
    numerically identical to the same pair computed alongside the others. It is
    there because each comparison costs a studentized-range integral per feature,
    which dominates the request.
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

    if only_significant and _significance_pval_column(anova_df):
        posthoc_df = anova_df[anova_df[_significance_pval_column(anova_df)] < in_pval].copy()
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
    # `names` stays the whole design: it sets k for the studentized range, and
    # the MSE above is already pooled across all of it.
    names = list(condition_cols.keys())
    if pair is None:
        comparisons = [
            (names[first], names[second])
            for first in range(len(names))
            for second in range(first + 1, len(names))
        ]
    else:
        left_wanted, right_wanted = (str(value) for value in pair)
        missing = [name for name in (left_wanted, right_wanted) if name not in condition_cols]
        if missing:
            raise ValueError(
                f"Post-hoc conditions not present in this dataset: {', '.join(missing)}."
            )
        if left_wanted == right_wanted:
            raise ValueError("Post-hoc comparison needs two different conditions.")
        # In the order asked for, so the sign follows the same rule as every
        # other comparison in the tool: the condition named first is the
        # minuend. The Tukey p-value itself is symmetric -- q uses |difference|.
        comparisons = [(left_wanted, right_wanted)]

    frames = []
    for left, right in comparisons:
        n_left, n_right = counts[left], counts[right]
        with np.errstate(divide="ignore", invalid="ignore"):
            standard_error = np.sqrt(mse / 2.0 * (1.0 / n_left + 1.0 / n_right))
            # group1 minus group2, matching the volcano convention: the
            # condition named first in `comparison` is the minuend.
            difference = means[left] - means[right]
            q_statistic = np.abs(difference) / standard_error
        pvals = stats.studentized_range.sf(q_statistic, len(names), df_resid)
        pvals = np.where(np.isfinite(q_statistic) & (df_resid > 0), pvals, np.nan)
        usable = np.isfinite(pvals) & (n_left >= 2) & (n_right >= 2)
        if not np.any(usable):
            continue
        frames.append(pd.DataFrame({
            label_col: labels[usable],
            "comparison": f"{left} vs {right}",
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


QQ_MAX_POINTS = 100_000
"""Above this many observations the Q-Q plot draws a random sample.

One number, used by the PNG, by the JSON summary and as the default below, so
the plot the user sees and the sentence that describes it cannot disagree.
"""


def qqnorm_plot_data(
    values: np.ndarray,
    max_points: int = QQ_MAX_POINTS,
    seed: int = 187,
) -> dict[str, list[tuple[float, float]]]:
    """Sample quantiles against normal quantiles, on whatever scale is passed.

    Every value is kept. This used to drop everything at or below zero, which
    is indefensible on the log2 matrix this plot is fed: a log2 intensity is
    negative wherever the linear intensity is below 1, and a `robust_site_median`
    phosphoprotein matrix holds ratios centred on zero, so roughly half of it
    was discarded before the question "are these values normal?" was asked --
    and discarding the lower half is exactly what makes a distribution look
    normal. Neither `notebook_functions.py` nor `notebook_functions.R` filtered,
    so the backend also disagreed with both packages on the same data.
    """
    clean = np.asarray(values, dtype=float)
    # Non-finite rather than merely non-NaN: an infinity has no quantile and
    # would poison the least-squares fit line for every other point.
    clean = clean[np.isfinite(clean)]
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


# The section markers that used to head the render facade are gone with it:
# each pipeline's renderers live in their own module (plot_images,
# completeness_tools, single_protein_tools, phospho_tools, comparison_tools)
# and are imported from there. What stays here is the analysis core the three
# pipelines share.
