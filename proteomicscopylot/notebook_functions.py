import gzip
import os
import warnings
import re
import sys
import math
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pyarrow.parquet as pq
import scipy.stats as stats
import seaborn as    sns
from matplotlib.patches import Ellipse
from matplotlib.patches import Rectangle
from matplotlib_venn import venn2, venn3
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from scipy.stats import gaussian_kde, pearsonr
from scipy.stats import t
from sklearn.decomposition import PCA

# <shared-core> proteomicscopylot/_core.py, one copy for the app and the pip
# package. Notebook exports inline these definitions here.
try:
    from ._core import (
        _SAMPLE_DOTTED_SUFFIX,
        _SAMPLE_TEXT_SUFFIX,
        _SAMPLE_ACQUISITION_SUFFIX,
        _SAMPLE_NUMBER,
        strip_sample_measurement_suffix,
        extract_sample_id,
        _significance_pval_column,
        constant_within_group,
        condition_mean,
        resolve_feature_scaling,
        _auto_label_col,
        bh_adjust,
    )
except ImportError:  # loaded from its file alone, outside the package
    import importlib.util as _importlib_util

    _core_spec = _importlib_util.spec_from_file_location("_copylot_core", Path(__file__).with_name("_core.py"))
    _core = _importlib_util.module_from_spec(_core_spec)
    _core_spec.loader.exec_module(_core)
    _SAMPLE_DOTTED_SUFFIX = _core._SAMPLE_DOTTED_SUFFIX
    _SAMPLE_TEXT_SUFFIX = _core._SAMPLE_TEXT_SUFFIX
    _SAMPLE_ACQUISITION_SUFFIX = _core._SAMPLE_ACQUISITION_SUFFIX
    _SAMPLE_NUMBER = _core._SAMPLE_NUMBER
    strip_sample_measurement_suffix = _core.strip_sample_measurement_suffix
    extract_sample_id = _core.extract_sample_id
    _significance_pval_column = _core._significance_pval_column
    constant_within_group = _core.constant_within_group
    condition_mean = _core.condition_mean
    resolve_feature_scaling = _core.resolve_feature_scaling
    _auto_label_col = _core._auto_label_col
    bh_adjust = _core.bh_adjust
# </shared-core>


def multipletests(pvals, alpha=0.05, method="fdr_bh"):
    """Benjamini-Hochberg adjustment, in the return shape of statsmodels' function.

    One implementation (`_core.bh_adjust`, shared with the application), so the
    adjusted p-values never depend on whether statsmodels happens to be
    installed; tests/reference compares it with statsmodels.
    """
    if method != "fdr_bh":
        raise ValueError("Only method='fdr_bh' (Benjamini-Hochberg) is available.")
    adjusted = bh_adjust(np.asarray(pvals, dtype=float))
    reject = adjusted <= alpha
    return reject, adjusted, None, None

try:
    from Bio import SeqIO
except ModuleNotFoundError:
    SeqIO = None


#BASIC AND DATA
def bool_to_str(value):
    if value is True:
        return "TRUE"
    elif value is False:
        return "FALSE"
    else:
        return ""


def format_value(val):
    if hasattr(val, 'name'):
        return val.name
    elif isinstance(val, bool) or val is None:
        return bool_to_str(val)
    elif isinstance(val, (int, float)):
        return number_to_str(val)
    else:
        return str(val)

def extract_number(s):
    nums = re.findall(r'\d+', s)
    return int(nums[0]) if nums else -1


def number_to_str(value):
    """Render a number the same way in every pipeline.

    Both packages used to delegate to the language's own conversion, and those
    disagree: R's `as.character` drops a trailing `.0` and switches to scientific
    notation past a width threshold, Python's `str` does neither, so `1.0` and
    `1000000.0` came out as different text from the two products. The contract is
    now explicit -- whole numbers carry no decimal point, and nothing below 1e15
    is rendered in scientific notation.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        return ""
    number = float(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Inf" if number > 0 else "-Inf"
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    return f"{number:.10g}"


def make_columns_unique(df):
    cols = pd.Series(df.columns)
    for dup in cols[cols.duplicated()].unique():
        dup_idx = cols[cols == dup].index.tolist()
        for i, idx in enumerate(dup_idx[1:], start=1):
            cols[idx] = f"{cols[idx]}_{i}"
    df.columns = cols
    return df


def sanitize_dataframe(df):
    df = df.copy()
    df = make_columns_unique(df)
    for col in df.columns:
        if isinstance(df[col], pd.Series):
            if not pd.api.types.is_numeric_dtype(df[col]):
                df[col] = df[col].astype(str)
        else:
            df[col] = df[col].astype(str)
    return df


def rename_cols(df):
    rename_map = {
        "Run": "File.Name",
        "PG.ProteinNames": "ProteinNames",
        "PG.ProteinGroups": "ProteinNames",
        "Protein.IDs": "ProteinNames",
        "PG.Genes": "GeneNames",
        "Protein.Names": "ProteinNames",
        "Protein IDs": "ProteinNames",
        "Genes": "GeneNames",
        "Gene names": "GeneNames",
        "PEP.StrippedSequence": "Stripped.Sequence",
        "Sequence": "Stripped.Sequence",
        "EG.ModifiedSequence": "Modified.Sequence",
        "R.FileName": "File.Name",
        "EG.iRTPredicted": "Predicted.RT",
        "EG.iRTEmpirical": "RT"
    }

    total_quantity_cols = [col for col in df.columns if re.match(r"EG\.TotalQuantity", col)]
    if total_quantity_cols:
        rename_map[total_quantity_cols[0]] = "Precursor.Quantity"

    df = df.rename(columns=rename_map)

    if {"GeneNames", "ProteinNames", "Raw file", "Intensity"}.issubset(df.columns):
        df['Intensity'] = pd.to_numeric(df['Intensity'], errors='coerce').fillna(0)
        agg_df = df.groupby(['GeneNames', 'ProteinNames', 'Raw file'], dropna=False)['Intensity'].sum().reset_index()
        df = agg_df.pivot(index=['GeneNames', 'ProteinNames'], columns='Raw file', values='Intensity').reset_index()
        df.columns.name = None

    if "Reverse" in df.columns:
        df = df[~df["Reverse"].str.contains(r"\+", na=False)]
    if "Only identified by site" in df.columns:
        df = df[~df["Only identified by site"].str.contains(r"\+", na=False)]

    return df

def info():
    print("Proteomics CoPYlot is a package/app to streamline the analysis of proteomics data. Have fun!")


# The bundled HEK293 example (WT vs GRK, five replicates each), by short name.
EXAMPLE_DATA_FILES = {
    "protein": "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv",
    "phospho": "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv",
    "phosphoprotein": "phosprot_filtered_data_full.csv",
    "protein_metadata": "protein_metadata_full.csv",
    "phospho_metadata": "phospho_metadata_full.csv",
}


def example_data_path(name):
    """Path of a bundled example file: one of the keys of EXAMPLE_DATA_FILES."""
    if name not in EXAMPLE_DATA_FILES:
        raise ValueError(f"Unknown example {name!r}; choose one of: {', '.join(EXAMPLE_DATA_FILES)}.")
    path = Path(__file__).resolve().parent / "example_data" / EXAMPLE_DATA_FILES[name]
    if not path.is_file():
        raise FileNotFoundError(f"The bundled example file is missing: {path}")
    return path


def load_example_data(name):
    """Read a bundled example file with `read_data`; see EXAMPLE_DATA_FILES for the names."""
    return read_data(example_data_path(name))


def read_data(file):
    if hasattr(file, 'name'):
        filename = file.name
    else:
        filename = file

    ext = os.path.splitext(filename)[1].lower().strip(".")

    if ext not in ["csv", "tsv", "txt", "xlsx", "parquet"]:
        raise ValueError("Invalid file type")

    if ext == "csv":
        df = pd.read_csv(file)
    elif ext == "tsv" or ext == "txt":
        df = pd.read_csv(file, sep="\t")
    elif ext == "xlsx":
        df = pd.read_excel(file)
    elif ext == "parquet":
        table = pq.read_table(file)
        df = table.to_pandas()
    else:
        raise ValueError("Unsupported file type")

    df = rename_cols(df)

    return df


def paired_sample_columns(meta, condition1, condition2):
    if str(condition1) == str(condition2):
        raise ValueError("Paired tests require two different conditions.")
    if "pair_id" not in meta.columns:
        raise ValueError(
            "Paired tests require a 'pair_id' metadata column with one stable subject "
            "identifier per sample."
        )
    duplicate_samples = (
        meta.loc[meta["sample"].astype(str).duplicated(keep=False), "sample"]
        .astype(str)
        .drop_duplicates()
        .tolist()
    )
    if duplicate_samples:
        raise ValueError(
            "Paired tests require each sample to appear once in metadata. "
            f"Duplicates: {', '.join(duplicate_samples)}."
        )

    def samples_by_id(condition):
        rows = meta.loc[
            meta["condition"].astype(str) == str(condition),
            ["sample", "pair_id"],
        ].copy()
        if rows.empty:
            raise ValueError(f"Condition '{condition}' does not have any annotated samples.")

        rows["sample"] = rows["sample"].astype(str)
        rows["pair_id"] = (
            rows["pair_id"].where(rows["pair_id"].notna(), "").astype(str).str.strip()
        )
        rows = rows.loc[rows["pair_id"] != ""]

        grouped = {}
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


def paired_test_enabled(value):
    mode = str(value).strip().lower()
    if mode not in {"paired", "unpaired"}:
        raise ValueError("paired must be 'Paired' or 'Unpaired'.")
    return mode == "paired"


# Which residues are cleaved after, and whether a following proline blocks it.
#   trypsin       K and R, both proline-blocked (K-P and R-P are not cut).
#   trypsin_lysc  K and R, but the Lys-C component is not proline-inhibited, so
#                 K-P is cleaved. R is cut by trypsin only, so R-P stays blocked.
_PROTEASE_PROLINE_BLOCKED = {
    "trypsin": {"K": True, "R": True},
    "trypsin_lysc": {"K": False, "R": True},
}

PROTEASE_LABELS = {
    "trypsin": "Trypsin",
    "trypsin_lysc": "Trypsin / Lys-C",
}


def normalize_protease(value="trypsin"):
    key = str(value or "trypsin").strip().lower().replace("-", "_").replace("/", "_")
    key = key.replace("__", "_")
    if key in {"trypsin_lysc", "trypsin_lys_c", "trypsinlysc"}:
        return "trypsin_lysc"
    if key == "trypsin":
        return "trypsin"
    raise ValueError("Protease must be 'trypsin' or 'trypsin_lysc'.")


def count_missed_cleavages(sequence, protease="trypsin"):
    """Count internal missed cleavage sites in a peptide sequence.

    A missed cleavage is a cleavable residue that is neither the C-terminal
    residue -- that one is the expected cut site, not a missed one -- nor
    blocked by a following proline. Proline blocking is protease dependent.
    """
    rules = _PROTEASE_PROLINE_BLOCKED[normalize_protease(protease)]

    def _count(value):
        residues = str(value or "").strip().upper()
        total = 0
        for index in range(len(residues) - 1):
            proline_blocked = rules.get(residues[index])
            if proline_blocked is None:
                continue
            if proline_blocked and residues[index + 1] == "P":
                continue
            total += 1
        return total

    # A column of sequences must give a count per sequence, as the R functions
    # does. Passing one used to stringify the whole container and count the
    # residues in its repr -- brackets and quotes included -- so a list of two
    # peptides returned a single meaningless number instead of two counts.
    if isinstance(sequence, (str, bytes)) or sequence is None:
        return _count(sequence)
    if hasattr(sequence, "__iter__"):
        return [_count(item) for item in sequence]
    return _count(sequence)


def _guarded_t_statistic(effect, standard_error):
    """Divide effect by SE without warnings while retaining zero-SE semantics."""
    effect_values, se_values = np.broadcast_arrays(
        np.asarray(effect, dtype=float),
        np.asarray(standard_error, dtype=float),
    )
    statistic = np.full(effect_values.shape, np.nan, dtype=float)
    nonzero_se = np.isfinite(se_values) & (se_values != 0)
    np.divide(effect_values, se_values, out=statistic, where=nonzero_se)

    zero_se = np.isfinite(se_values) & (se_values == 0) & np.isfinite(effect_values)
    statistic[zero_se & (effect_values > 0)] = np.inf
    statistic[zero_se & (effect_values < 0)] = -np.inf
    return statistic


def paired_t_test(differences):
    differences = np.asarray(differences, dtype=float)
    finite = np.isfinite(differences)
    n_pairs = finite.sum(axis=1).astype(float)
    clean = np.where(finite, differences, np.nan)
    mean_diff = np.nanmean(clean, axis=1)
    variance = np.nanvar(clean, axis=1, ddof=1)
    se = np.sqrt(variance / n_pairs)
    t_statistic = _guarded_t_statistic(mean_diff, se)
    pvalues = 2.0 * t.sf(np.abs(t_statistic), n_pairs - 1.0)
    return mean_diff, n_pairs, np.asarray(pvalues, dtype=float)


def negative_log10(values):
    with np.errstate(divide="ignore", invalid="ignore"):
        return -np.log10(values)


def extract_id_or_number(x):
    return extract_sample_id(x)


def _sample_meta(meta, id=True, newline=False, zero_based=False):
    """Sample labels `Condition_n`, with the sample's id appended when `id` is set.

    `n` counts each condition's samples in metadata order, from 1 (from 0 with
    `zero_based`). The id follows on its own line with `newline` -- for tick
    labels -- or after a space. Returns a copy with `sample` as text and `id` and
    `new_sample` added. The R functions' `.sample_meta` is the same rule.
    """
    meta = meta.copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].apply(extract_id_or_number)
    number = meta.groupby("condition").cumcount() + (0 if zero_based else 1)
    labels = meta["condition"].astype(str) + "_" + number.astype(str)
    if id:
        labels = labels + ("\n(" if newline else " (") + meta["id"].astype(str) + ")"
    meta["new_sample"] = labels
    return meta


def _rename_samples(data, meta):
    """`data` with its sample columns renamed to the labels `_sample_meta` built."""
    return data.rename(columns=dict(zip(meta["sample"], meta["new_sample"])))


def raw_zero_to_nan(data: pd.DataFrame, sample_columns) -> pd.DataFrame:
    """Read 0 (and +/-inf) in raw, linear intensities as not measured.

    Only the named sample columns change; annotation columns and values on a
    log2 scale, where 0 is a real measurement, are left alone. Same name and
    rule in the app and the R functions.
    """
    output = data.copy()
    present = [column for column in map(str, sample_columns) if column in output.columns]
    if present:
        output[present] = (
            output[present]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf, 0], np.nan)
        )
    return output


def _prepare_intensity_data(
    data: pd.DataFrame,
    sample_columns,
    data_scale: str = "log2",
) -> pd.DataFrame:
    """Apply the shared missingness contract to an intensity matrix.

    Zero is a valid measured value on the log2 scale (linear abundance 1), but
    represents a non-detection in linear/raw quantities. Non-numeric and
    non-finite sample values are missing under either scale. Annotation columns
    are copied unchanged.
    """
    scale = str(data_scale).strip().lower()
    if scale not in {"log2", "linear"}:
        raise ValueError("data_scale must be 'log2' or 'linear'.")

    output = data.copy()
    present = [column for column in map(str, sample_columns) if column in output.columns]
    if present:
        output[present] = (
            output[present]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        if scale == "linear":
            output[present] = output[present].replace(0, np.nan)
    return output


def log2_transform_data(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    annotated_columns = meta['sample'].tolist()
    data_filtered = raw_zero_to_nan(data[annotated_columns], annotated_columns)
    log2_data = np.log2(data_filtered)

    remaining_columns = [col for col in data.columns if col not in annotated_columns]
    combined_data = pd.concat([log2_data, data[remaining_columns]], axis=1)

    return combined_data


def inverse_log2_transform_data(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    annotated_columns = meta['sample'].tolist()
    log2_data = data[annotated_columns].copy()
    original_data = 2 ** log2_data

    remaining_columns = [col for col in data.columns if col not in annotated_columns]
    combined_data = pd.concat([original_data, data[remaining_columns]], axis=1)

    return combined_data


def _validate_filter_thresholds(num, method, percentage):
    """Reject a threshold that is not a meaningful quantity.

    A filter that keeps nothing is a legitimate answer to a strict request, so
    only impossible values are refused: a percentage outside 0-100, or a negative
    count. Those cannot describe any completeness requirement, and used to pass
    silently -- a negative count returned the whole matrix unfiltered.
    """
    if method == "percentage":
        try:
            value = float(percentage)
        except (TypeError, ValueError):
            raise ValueError(
                f"Minimum completeness percentage must be a number, got {percentage!r}."
            ) from None
        if not 0.0 <= value <= 100.0:
            raise ValueError(
                f"Minimum completeness percentage must be between 0 and 100, got {value:g}."
            )
        return

    try:
        value = int(num)
    except (TypeError, ValueError):
        raise ValueError(
            f"Minimum valid values must be a whole number, got {num!r}."
        ) from None
    if value < 0:
        raise ValueError(f"Minimum valid values must be zero or greater, got {value}.")


def _validate_meta_samples(meta):
    """Refuse metadata that names a sample more than once.

    A sample listed twice is counted twice by every group-wise mean and variance,
    which roughly halves the standard error while leaving the fold change
    untouched -- so nothing looks wrong and only the p-values move, downward. On
    the bundled example a single duplicated condition takes the median p-value to
    about a tenth of its correct value. The web app rejects this at upload; the
    notebook packages take a hand-built frame, which is exactly where the slip
    happens.
    """
    if not isinstance(meta, pd.DataFrame) or "sample" not in meta.columns:
        return meta
    samples = meta["sample"].astype(str).str.strip()
    repeated = samples[samples.duplicated(keep=False)].drop_duplicates().tolist()
    if repeated:
        raise ValueError(
            f"Metadata lists {len(repeated)} sample(s) more than once: "
            f"{', '.join(repeated[:10])}"
            f"{', and more' if len(repeated) > 10 else ''}. "
            "Each sample must appear exactly once; a repeated sample is counted "
            "twice and deflates every p-value."
        )
    return meta


_VALUE_PLACEHOLDERS = {
    "", "na", "n/a", "nan", "-", "--", "null", "none", "filtered", "#div/0!", "#n/a",
}


def _validate_sample_values(data, meta, threshold=0.2):
    """Refuse sample columns whose values do not parse as numbers.

    Every stage coerces with ``errors="coerce"``, which turns unparseable text
    into NaN, and NaN reads as "not detected" from then on. A column exported
    from a locale that writes 19,436 for 19.436 loses every value this way: the
    sample survives the completeness filter on the strength of the other
    replicates and the analysis quietly runs one replicate short.

    Blanks and documented placeholders really are missing, so they are ignored.
    Only entries carrying a digit count as a lost measurement -- a stray text
    label is not one. The web app catches this when annotations are applied; the
    notebook packages take a hand-built frame, which is where the slip happens.
    """
    if not isinstance(data, pd.DataFrame) or not isinstance(meta, pd.DataFrame):
        return data
    if "sample" not in meta.columns:
        return data

    findings = []
    for column in meta["sample"].astype(str).tolist():
        if column not in data.columns:
            continue
        raw = data[column]
        if raw.dtype.kind in "fiub":
            continue
        text = raw.astype(str).str.strip()
        considered = text[~text.str.lower().isin(_VALUE_PLACEHOLDERS)]
        if considered.empty:
            continue
        coerced = pd.to_numeric(considered, errors="coerce")
        unreadable = coerced.isna() & considered.str.contains("[0-9]", regex=True)
        lost = int(unreadable.sum())
        if not lost:
            continue
        example = str(considered[unreadable].iloc[0])
        if lost / len(considered) > threshold:
            findings.append((column, lost, int(len(considered)), example))
        else:
            # Below the threshold this is more likely a few odd cells than a
            # mangled export, so it is not worth refusing the frame -- but it is
            # still measurements turning into NaN, and saying nothing was the
            # same silence the threshold exists to break.
            warnings.warn(
                f"Sample column {column!r} lost {lost} of {len(considered)} values that "
                f"carry digits but do not parse as numbers (e.g. {example!r}). They "
                "become NaN and read as 'not detected' from here on.",
                stacklevel=3,
            )

    if findings:
        detail = "; ".join(
            f"{column} lost {lost} of {total} values (e.g. {example!r})"
            for column, lost, total, example in findings
        )
        raise ValueError(
            f"{len(findings)} sample column(s) carry values that do not parse as "
            f"numbers: {detail}. This usually means a decimal comma from a "
            "locale-specific export. Every unparseable value becomes NaN, so the "
            "sample would be treated as fully undetected rather than unreadable."
        )
    return data


def filter_data(data, meta, num, mode="per_group", method="at_least_n", percentage=70):
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    meta = meta.copy()
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns].copy()
    method = str(method).strip().lower()
    # One spelling everywhere since 2026-10-02 (`per_group`, as the app uses);
    # the older "per group" with a space is still read the same way.
    mode = str(mode).strip().lower().replace(" ", "_")
    if method not in {"at_least_n", "percentage"}:
        raise ValueError("Filter method must be 'at_least_n' or 'percentage'.")
    # An unrecognised mode used to fall through to the `any` branch, silently
    # applying the most permissive filter of the three: a misspelling retained
    # features present in only one condition, which is what `per_group` exists
    # to exclude.
    if mode not in {"per_group", "in_at_least_one_group", "overall"}:
        raise ValueError(
            "Filter mode must be 'per_group', 'in_at_least_one_group', or 'overall'."
        )
    _validate_filter_thresholds(num, method, percentage)

    if mode == "overall":
        valid = data_filtered.notna().sum(axis=1)
        if method == "percentage":
            rows_to_keep = valid / len(annotated_columns) >= percentage / 100
        else:
            rows_to_keep = valid >= num
    else:
        conditions = meta['condition'].unique()
        mask = pd.DataFrame(False, index=data_filtered.index, columns=conditions)
        for cond in conditions:
            cols = meta.loc[meta['condition'] == cond, 'sample']
            valid = data_filtered[cols].notna().sum(axis=1)
            if method == "percentage":
                mask[cond] = valid / len(cols) >= percentage / 100
            else:
                mask[cond] = valid >= num
        rows_to_keep = mask.all(axis=1) if mode == "per_group" else mask.any(axis=1)

    return data.loc[rows_to_keep]


LOCALIZATION_COLUMN = "PTM_localization"


def filter_localization(data, cutoff=0.0, column=LOCALIZATION_COLUMN):
    """Phosphosites whose localization probability is at least `cutoff`.

    0 keeps every row, including rows without a probability. Above 0 a row
    without a probability (missing, non-numeric or outside 0..1) is dropped,
    because it cannot be shown to pass. Use it on a phosphosite table before a
    generic function (volcano, QC, PCA, ...) to reproduce the application's
    localization probability cutoff; the phospho-specific functions take
    `localization_cutoff=` directly. Mirrors the backend and the R helper.
    """
    cutoff = float(cutoff)
    if not 0.0 <= cutoff <= 1.0:
        raise ValueError("The localization probability cutoff must be between 0 and 1.")
    if cutoff <= 0.0:
        return data.copy()
    if column not in data.columns:
        raise ValueError(
            f"A localization probability cutoff of {cutoff:.2f} needs a '{column}' column, "
            "which this phosphosite table does not have."
        )
    probability = pd.to_numeric(data[column], errors="coerce")
    probability = probability.where(probability.between(0.0, 1.0))
    return data.loc[probability >= cutoff].copy()


def transform_phosprot(
    data: pd.DataFrame,
    meta: pd.DataFrame,
    mode: str = "robust_site_median",
    data_scale: str = "linear",
    coverage_data: pd.DataFrame | None = None,
    localization_cutoff: float = 0.0,
):
    """Collapse phosphosites to one phosphoprotein value per sample.

    Only sites with a localization probability of at least
    ``localization_cutoff`` are collapsed (see `filter_localization`).

    ``robust_site_median`` works on log2 values after centring every site by its
    across-sample median and requires at least 50% of the fixed eligible sites.
    The other modes aggregate original-scale intensities and the result is log2
    transformed afterwards, so every mode returns log2 values and the fold
    changes computed from them are comparable. ``mean`` averages only the sites
    quantified in every sample, so all samples use the same sites; a protein
    without such a site is missing. ``data_scale`` describes the
    supplied sample columns and may be ``"linear"`` or ``"log2"``.
    Pass aligned pre-imputation ``coverage_data`` for observed-site diagnostics
    and eligibility. The 50% threshold counts finite supplied values, including
    imputed values. Without coverage_data, diagnostics describe the input only.
    """
    data = filter_localization(data, localization_cutoff)
    if coverage_data is not None:
        coverage_data = coverage_data.loc[coverage_data.index.isin(data.index)]
    required_cols = [
        "UPD_seq",
        "PTM_localization",
        "Protein_group",
        "Gene_group",
        "PTM_Collapse_key"
    ]

    missing = [c for c in required_cols if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in `data`: {missing}")

    if not {"condition", "sample"}.issubset(meta.columns):
        raise ValueError("`meta` must contain columns: 'condition', 'sample'")

    sample_cols = [str(value) for value in meta["sample"].tolist()]
    if not sample_cols:
        raise ValueError("`meta` must contain at least one sample")
    duplicate_samples = sorted({sample for sample in sample_cols if sample_cols.count(sample) > 1})
    if duplicate_samples:
        raise ValueError(f"`meta.sample` contains duplicate names: {duplicate_samples}")
    missing_samples = [s for s in sample_cols if s not in data.columns]
    if missing_samples:
        raise ValueError(f"`meta.sample` contains names not found in data: {missing_samples}")

    resolved_scale = str(data_scale).strip().lower()
    if resolved_scale not in {"linear", "log2"}:
        raise ValueError("data_scale must be 'linear' or 'log2'.")
    data = data.copy()
    data["Protein_group"] = data["Protein_group"].astype(str)

    gene_map = data.groupby("Protein_group")["Gene_group"].nunique()
    bad = gene_map[gene_map > 1]
    if not bad.empty:
        raise ValueError(
            "Each Protein_group must map to exactly one Gene_group.\n"
            f"Violations for Protein_groups: {list(bad.index)}"
        )

    collapse = lambda x: ";".join(sorted(set(x.dropna().astype(str))))

    def arrange_elements(series: pd.Series):
        return ";".join(series.dropna().astype(str))

    def sum_propagate_nan(series: pd.Series):
        vals = pd.to_numeric(series, errors="coerce")
        if vals.isna().any():
            return np.nan
        return vals.sum()

    def sum_ignore_nan(series: pd.Series):
        vals = pd.to_numeric(series, errors="coerce")
        return vals.sum(min_count=1)

    def mean(series: pd.Series):
        vals = pd.to_numeric(series, errors="coerce")
        return vals.mean()

    if resolved_scale == "log2":
        log2_source = data.copy()
        log2_source[sample_cols] = log2_source[sample_cols].apply(pd.to_numeric, errors="coerce")
        linear_source = inverse_log2_transform_data(log2_source, meta)
    else:
        linear_source = raw_zero_to_nan(data, sample_cols)
        log2_source = log2_transform_data(linear_source, meta)
    for source_frame in (log2_source, linear_source):
        source_frame[sample_cols] = (
            source_frame[sample_cols]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )

    diagnostic_source = log2_source
    if coverage_data is not None:
        if not coverage_data.index.equals(data.index):
            raise ValueError("coverage_data must have exactly the same row index as data.")
        if not {"Protein_group", *sample_cols}.issubset(coverage_data.columns):
            raise ValueError("coverage_data is missing required columns.")
        if not coverage_data["Protein_group"].astype(str).equals(data["Protein_group"]):
            raise ValueError("coverage_data Protein_group values must align exactly with data.")
        diagnostic_source = (coverage_data if resolved_scale == "log2" else
                             log2_transform_data(raw_zero_to_nan(coverage_data, sample_cols), meta))
    numeric = diagnostic_source[sample_cols].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    eligible_mask = numeric.notna().any(axis=1)
    eligible_log2 = log2_source.loc[eligible_mask].copy()
    groups = data["Protein_group"].astype(str)
    group_order = groups.drop_duplicates().tolist()
    total = groups.value_counts(sort=False).reindex(group_order, fill_value=0).astype(int)
    eligible_groups = groups.loc[eligible_mask]
    eligible_count = eligible_groups.value_counts(sort=False).reindex(group_order, fill_value=0).astype(int)
    observed = (
        numeric.loc[eligible_mask]
        .notna()
        .astype(int)
        .assign(Protein_group=eligible_groups.to_numpy())
        .groupby("Protein_group", sort=False)[sample_cols]
        .sum()
        .reindex(group_order, fill_value=0)
        .astype(int)
    )
    fractions = observed.div(eligible_count.replace(0, np.nan).astype(float), axis=0)

    annotation_agg = {
        "Gene_group": "first",
        "PTM_Collapse_key": collapse,
        "PTM_localization": arrange_elements,
        "UPD_seq": collapse,
    }
    annotations = data.groupby("Protein_group", as_index=False).agg(annotation_agg)

    if mode == "robust_site_median":
        eligible_numeric = eligible_log2[sample_cols].apply(pd.to_numeric, errors="coerce")
        centred = eligible_numeric.sub(eligible_numeric.median(axis=1, skipna=True), axis=0)
        centred["Protein_group"] = eligible_log2["Protein_group"].astype(str).to_numpy()
        values = centred.groupby("Protein_group", sort=False)[sample_cols].median().reindex(group_order)
        required = eligible_count.apply(lambda count: max(1, int(math.ceil(float(count) * 0.5))))
        available = eligible_numeric.notna().assign(
            Protein_group=eligible_log2["Protein_group"].to_numpy()
        ).groupby("Protein_group")[sample_cols].sum().reindex(group_order, fill_value=0)
        for sample in sample_cols:
            values.loc[available[sample] < required, sample] = np.nan
        values = values.reset_index()
    else:
        eligible_index = eligible_log2.index
        source = linear_source.loc[eligible_index].copy()
        if mode == "sum_propagate_na":
            summarizer = sum_propagate_nan
        elif mode == "sum_ignore_na":
            summarizer = sum_ignore_nan
        elif mode == "mean":
            summarizer = mean
        else:
            raise ValueError(
                "mode must be 'robust_site_median', 'sum_propagate_na', "
                "'sum_ignore_na', or 'mean'"
            )
        if mode in ("mean", "sum_ignore_na"):
            # Only sites quantified in every sample, so all samples use the same sites
            # and a change in coverage cannot flip a fold change.
            source = source.loc[source[sample_cols].apply(pd.to_numeric, errors="coerce").notna().all(axis=1)]
        values = source.groupby("Protein_group", as_index=False).agg(
            {column: summarizer for column in sample_cols}
        )
        # These modes aggregate original-scale intensities, so their result is
        # linear while robust_site_median returns log2. Everything downstream --
        # volcano_data_f above all -- labels its output "log2FC" unconditionally,
        # so a linear frame yields a "log2FC" that is really a difference of raw
        # intensities, in the thousands. Transform here so every mode returns the
        # same scale, matching what the web app does downstream.
        aggregated = values[sample_cols].apply(pd.to_numeric, errors="coerce")
        non_positive = int((aggregated <= 0).sum().sum())
        if non_positive:
            aggregated = aggregated.mask(aggregated <= 0)
            warnings.warn(
                f"{non_positive} aggregated value(s) were not positive and were set to "
                "missing because they cannot be log2 transformed. This points at a "
                "scale or imputation problem in the phosphosite input rather than at "
                "the aggregation.",
                stacklevel=2,
            )
        values[sample_cols] = np.log2(aggregated)

    diagnostics = pd.DataFrame({
        "Protein_group": group_order,
        "site_num": total.to_numpy(),
        "site_num_eligible": eligible_count.to_numpy(),
        "site_observed_min": observed.min(axis=1).to_numpy(dtype=int),
        "site_observed_mean": observed.mean(axis=1).to_numpy(dtype=float),
        "site_coverage_min": fractions.min(axis=1).to_numpy(dtype=float),
        "site_coverage_mean": fractions.mean(axis=1).to_numpy(dtype=float),
    })
    complete = observed.eq(eligible_count, axis=0)
    complete.loc[eligible_count == 0, :] = False
    diagnostics["site_complete_samples"] = complete.sum(axis=1).to_numpy(dtype=int)
    for sample in sample_cols:
        diagnostics[f"site_observed__{sample}"] = observed[sample].to_numpy(dtype=int)
        diagnostics[f"site_coverage__{sample}"] = fractions[sample].to_numpy(dtype=float)

    supplied_source = eligible_log2 if mode == "robust_site_median" else source
    supplied = supplied_source[sample_cols].notna().assign(
        Protein_group=supplied_source['Protein_group'].to_numpy()
    ).groupby('Protein_group')[sample_cols].sum().reindex(group_order, fill_value=0)
    measured = (supplied_source[sample_cols].notna()
                & numeric.loc[supplied_source.index, sample_cols].notna()).assign(
        Protein_group=supplied_source['Protein_group'].to_numpy()
    ).groupby('Protein_group')[sample_cols].sum().reindex(group_order, fill_value=0)
    for sample in sample_cols:
        diagnostics[f"site_supplied__{sample}"] = supplied[sample].to_numpy(dtype=int)
        diagnostics[f"site_measured__{sample}"] = measured[sample].to_numpy(dtype=int)
    data_phosprot = annotations.merge(values, on="Protein_group", how="left")
    data_phosprot = data_phosprot.merge(diagnostics, on="Protein_group", how="left")

    data_phosprot = data_phosprot.rename(columns={
        "PTM_Collapse_key": "PTM_Collapse_keys",
        "Protein_group": "Phosphoprotein"
    })

    diagnostic_cols = [
        column for column in data_phosprot.columns
        if column.startswith("site_") and column not in {"site_num", "site_num_eligible"}
    ]
    ordered = [
        "Phosphoprotein", "Gene_group", "site_num", "site_num_eligible",
        "PTM_Collapse_keys", "PTM_localization", "UPD_seq", *sample_cols,
        *diagnostic_cols,
    ]
    return data_phosprot[[column for column in ordered if column in data_phosprot.columns]]


def qqnorm_plot(data, meta, seed=187):
    sample_columns = meta['sample'].tolist()
    data_values = data[sample_columns].apply(pd.to_numeric, errors="coerce")

    values_vector = data_values.values.flatten()
    values_vector = values_vector[np.isfinite(values_vector)]

    if len(values_vector) > 100_000:
        rng = np.random.default_rng(seed)
        values_vector = rng.choice(values_vector, 100_000, replace=False)

    fig, ax = plt.subplots()
    stats.probplot(values_vector, plot=ax)
    ax.set_title("QQ Plot")
    ax.set_xlabel("Theoretical Quantiles")
    ax.set_ylabel("Sample Quantiles")
    return fig

def impute_values(data: pd.DataFrame, meta: pd.DataFrame, q=0.01, adj_std=0.3, ret=0, sample_wise=True, seed=1337, method="quantile", down_shift=1.8, width=0.3):
    """Impute missing values with a downshifted normal draw.

    Pass **log2 transformed** data. The model draws from a normal centred near
    the low quantile of the observed distribution, which is only sensible where
    intensities are roughly Gaussian. On linear intensities the draw width is
    set by the high-abundance tail and roughly half the draws come out negative,
    which then become NaN as soon as anything log2 transforms them.

    If you need linear values for another workflow, impute first and
    inverse-transform afterwards -- not the other way round.

    Uses sample SD (n-1). Sample-wise draws skip empty, singleton and constant
    columns with a warning. Explicit global draws require a usable pooled SD.

    For phosphoprotein workflows, impute phosphosites before transform_phosprot,
    never the collapsed phosphoprotein matrix. Keep the non-imputed site matrix
    for independent coverage checks, and aggregate with data_scale="log2".
    This generic helper cannot infer the
    biological dataset level from an arbitrary dataframe.

    Methods: "quantile" (default) draws around the q-quantile of the observed values
    with adj_std times their standard deviation, in the spirit of MinProb (Lazar et
    al. 2016, doi:10.1021/acs.jproteome.5b00981). "numerical" is the downshifted
    normal with Perseus defaults, mean - down_shift * SD and width * SD (Tyanova et
    al. 2016, doi:10.1038/nmeth.3901).
    """
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    method = str(method).strip().lower()
    if method == "normal":
        method = "quantile"
    if method not in {"quantile", "numerical"}:
        raise ValueError("Imputation method must be 'quantile' or 'numerical'.")
    if not float(adj_std if method == "quantile" else width) > 0:
        raise ValueError("Adjust standard deviation must be greater than 0.")
    rng = np.random.default_rng(seed)
    data = data.copy()
    annotated_columns = meta["sample"].tolist()
    data_filtered = data[annotated_columns].copy()
    combined_data = data_filtered.values.flatten()
    missing_value_mask = data_filtered.isna()
    data_without_na = data_filtered.loc[~data_filtered.isna().any(axis=1)]
    data_with_na = data_filtered.loc[data_filtered.isna().any(axis=1)]
    combined_data_without_na = data_without_na.values.flatten()
    combined_data_with_na = data_with_na.values.flatten()

    if ret in (1, 2, 3) and not np.isfinite(combined_data).any():
        raise ValueError("No observed values available to plot an imputation distribution.")

    if ret == 1:
        fig, ax = plt.subplots()
        ax.hist([combined_data_without_na, combined_data_with_na],
                bins=50, density=True, alpha=0.6, histtype='stepfilled',
                label=["Without Missing Values", "With Missing Values"])
        ax.legend()
        ax.set_title("Overall distribution of data with and without missing values")
        ax.set_xlabel("log2 Intensity")
        ax.set_ylabel("Density")
        return fig

    observed = combined_data[~np.isnan(combined_data)]
    mean_val = np.mean(observed) if observed.size else np.nan
    sd_val = np.std(observed, ddof=1) if observed.size > 1 else np.nan
    quantile_val = np.quantile(observed, q) if observed.size else np.nan
    if not sample_wise and (observed.size < 2 or not np.isfinite(sd_val) or sd_val <= 0 or np.ptp(observed) == 0):
        raise ValueError("Global imputation requires at least two observed values with nonzero spread.")

    if ret == 2:
        fig, ax = plt.subplots()
        ax.hist(combined_data[~np.isnan(combined_data)],
                bins=50, density=True, alpha=0.6, color="blue", histtype='stepfilled')
        x = np.linspace(np.nanmin(combined_data), np.nanmax(combined_data), 200)
        if np.isfinite(sd_val) and sd_val > 0:
            ax.plot(x, (1/(sd_val*np.sqrt(2*np.pi))) * np.exp(-0.5*((x-mean_val)/sd_val)**2),
                    color="red", label="Normal fit")
        ax.set_title("Overall data distribution and norm fit")
        ax.set_xlabel("log2 Intensity")
        ax.set_ylabel("Density")
        ax.legend()
        return fig

    skipped_samples = []
    if sample_wise:
        for col in annotated_columns:
            col_vals = data_filtered[col]
            num_na = col_vals.isna().sum()
            if num_na > 0:
                col_observed = col_vals.dropna().to_numpy()
                if col_observed.size < 2 or np.ptp(col_observed) == 0:
                    skipped_samples.append(str(col))
                    continue
                col_sd = np.std(col_observed, ddof=1)
                if not np.isfinite(col_sd) or col_sd <= 0:
                    skipped_samples.append(str(col))
                    continue
                if method == "numerical":
                    center = np.nanmean(col_vals) - down_shift * col_sd
                    draw_sd = col_sd * width
                else:
                    center = np.nanquantile(col_vals, q)
                    # adj_std must scale the draw here exactly as it does in the
                    # global branch below; without it the setting is inert in
                    # sample-wise mode and the spread is always the full SD.
                    draw_sd = col_sd * adj_std
                data_filtered.loc[col_vals.isna(), col] = rng.normal(center, draw_sd, num_na)
    else:
        if method == "numerical":
            center = mean_val - down_shift * sd_val
            draw_sd = sd_val * width
        else:
            center = quantile_val
            draw_sd = sd_val * adj_std
        for col in annotated_columns:
            col_vals = data_filtered[col]
            num_na = col_vals.isna().sum()
            if num_na > 0:
                data_filtered.loc[col_vals.isna(), col] = rng.normal(center, draw_sd, num_na)

    if skipped_samples:
        warnings.warn(
            "Missing values left unchanged: fewer than two observations or no usable spread in sample(s): "
            + ", ".join(skipped_samples), RuntimeWarning, stacklevel=2,
        )
    imputed_data = data_filtered[missing_value_mask]
    non_imputed_data = data_filtered[~missing_value_mask]
    imputed_combined = imputed_data.values.flatten()
    non_imputed_combined = non_imputed_data.values.flatten()

    if ret == 3:
        fig, ax = plt.subplots()
        ax.hist([non_imputed_combined, imputed_combined],
                bins=50, density=True, alpha=0.6, histtype='stepfilled',
                label=["Non-Imputed Values", "Imputed Values"])
        ax.legend()
        ax.set_title("Distribution of data after imputation")
        ax.set_xlabel("log2 Intensity")
        ax.set_ylabel("Density")
        return fig

    data_imputed = data.copy()
    data_imputed[annotated_columns] = data_filtered
    return data_imputed


#QC FUNCTIONS
def coverage_plot(data, meta, id=True, header=True, legend=True, plot_colors=None,
                  width=20, height=10, dpi=300, text=False, text_size=9,
                  data_scale="log2"):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    conditions = meta['condition'].unique()
    # `_sample_meta` works on a copy: this used to write `id` and
    # `new_sample` into the caller's own meta.
    meta = _sample_meta(meta, id=id, newline=True)
    data_filtered = _rename_samples(data, meta)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]

    if not annotated_columns:
        raise ValueError("None of the annotated columns exist in the data after renaming.")

    data_filtered = data_filtered[annotated_columns]
    data_filtered = data_filtered.notna().astype(int)

    data_long = data_filtered.reset_index().melt(
        id_vars=data_filtered.index.name or None,
        var_name='Sample',
        value_name='Value'
    )

    data_annotated = data_long.merge(meta[['new_sample', 'condition']],
                                     left_on='Sample', right_on='new_sample')

    summary = data_annotated.groupby(['Sample', 'condition'], as_index=False)['Value'].sum()
    summary['Sample'] = pd.Categorical(summary['Sample'], categories=annotated_columns, ordered=True)
    summary['condition'] = pd.Categorical(summary['condition'], categories=conditions, ordered=True)
    summary = summary.sort_values(['condition', 'Sample'])

    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54), dpi=dpi)

    colors = plot_colors if plot_colors is not None else plt.cm.tab10.colors
    color_map = {cond: colors[i % len(colors)] for i, cond in enumerate(conditions)}

    for cond in conditions:
        cond_data = summary[summary['condition'] == cond]
        bars = ax.bar(cond_data['Sample'], cond_data['Value'], label=cond, color=color_map[cond])

        if text:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        height * 0.02,
                        f"{int(np.ceil(height))}",
                        ha="center", va="bottom",
                        fontsize=text_size, fontweight="bold",
                        color="black", rotation=90
                    )

    ax.set_xlabel('Sample')

    redline = None

    if 'Phosphoprotein' in data.columns:
        ax.set_ylabel('Number of phosphoproteins')
        redline = int(data_filtered.any(axis=1).sum())
        if header: fig.suptitle('Phosphoproteins per sample', fontsize=14)

    elif 'ProteinNames' in data.columns:
        ax.set_ylabel('Number of proteins')
        redline = int(data_filtered.any(axis=1).sum())
        if header: fig.suptitle('Proteins per sample', fontsize=14)

    elif 'PTM_Collapse_key' in data.columns:
        ax.set_ylabel('Number of phosphosites')
        redline = int(data_filtered.any(axis=1).sum())
        if header: fig.suptitle('Phosphosites per sample', fontsize=14)

    else:
        ax.set_ylabel('Number')
        if header: fig.suptitle('')

    if redline is not None:
        ax.axhline(y=redline, color='red', linestyle='--')

    ax.tick_params(axis='x', rotation=90, labelsize=6)

    if legend:
        ax.legend(title='Condition', bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.subplots_adjust(right=0.75, top=0.88)
    else:
        if ax.legend_:
            ax.legend_.remove()
        plt.subplots_adjust(right=0.95, top=0.88)

    ymax = summary['Value'].max()
    if redline is not None:
        ymax = max(ymax, redline)
    ax.set_ylim(0, ymax * 1.1)

    plt.tight_layout()
    return fig


def coverage_plot_summary(data, meta, header=True, plot_colors=None, width=20, height=10, dpi=300, text=False,
                          text_size=9, seed=69, data_scale="log2"):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    meta = meta.copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].str.extract(r'(\d+|[A-Za-z]+)', expand=False)

    meta["new_sample"] = [
        f"{cond}_{i+1}\n({sid})"
        for cond in meta["condition"].unique()
        for i, sid in enumerate(meta.loc[meta["condition"] == cond, "id"])
    ]

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data = data.rename(columns=rename_dict)
    annotated_cols = meta["new_sample"].tolist()
    data_filtered = data[annotated_cols]
    data_binary = data_filtered.notna().astype(int)
    melted = data_binary.melt(var_name="Sample", value_name="Value")
    data_annotated = melted.merge(meta, left_on="Sample", right_on="new_sample")

    sample_summary = (
        data_annotated.groupby("Sample")
        .agg(Value=("Value", "sum"), condition=("condition", "first"))
        .reset_index()
    )

    condition_summary = (
        sample_summary.groupby("condition")
        .agg(mean_value=("Value", "mean"), sd_value=("Value", "std"))
        .reset_index()
    )

    conditions = condition_summary["condition"].tolist()
    if plot_colors is None:
        plot_colors = plt.cm.tab10.colors
    if len(plot_colors) < len(conditions):
        plot_colors = (plot_colors * (len(conditions) // len(plot_colors) + 1))[:len(conditions)]
    color_map = dict(zip(conditions, plot_colors))

    fig, ax = plt.subplots(figsize=(width/2.54, height/2.54), dpi=dpi)
    bar_positions = np.arange(len(conditions))
    bar_means = condition_summary["mean_value"].values
    bar_sds = condition_summary["sd_value"].values

    bars = ax.bar(
        bar_positions,
        bar_means,
        yerr=bar_sds,
        capsize=5,
        color=[color_map[c] for c in conditions],
        edgecolor="black"
    )

    rng = np.random.default_rng(seed)
    for i, cond in enumerate(conditions):
        cond_values = sample_summary.loc[sample_summary["condition"] == cond, "Value"].values
        jitter = rng.uniform(-0.2, 0.2, size=len(cond_values))
        ax.scatter(
            np.full(len(cond_values), bar_positions[i]) + jitter,
            cond_values,
            color="black",
            alpha=0.7,
            s=20,
            zorder=3
        )

    if text:
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height * 0.02,
                f"{int(np.ceil(height))}",
                ha="center",
                va="bottom",
                fontsize=text_size,
                fontweight="bold",
                rotation=90,
                color="black"
            )

    plot_title, y_label = "", "Number"
    red_line_value = None

    if "Phosphoprotein" in data.columns:
        plot_title = "Phosphoproteins per sample"
        y_label = "Number of phosphoproteins"
    elif "ProteinNames" in data.columns:
        plot_title = "Proteins per sample"
        y_label = "Number of proteins"
    elif "PTM_Collapse_key" in data.columns:
        plot_title = "Phosphosites per sample"
        y_label = "Number of phosphosites"

    if plot_title:
        red_line_value = int(data_binary.any(axis=1).sum())
        ax.axhline(red_line_value, linestyle="--", color="red")

    ax.set_title(plot_title if header else "")
    ax.set_ylabel(y_label)
    ax.set_xticks(bar_positions)
    ax.set_xticklabels(conditions, rotation=90, ha="center")

    ymax = max(
        max(bar_means + np.nan_to_num(bar_sds, nan=0)),
        red_line_value if red_line_value is not None else 0
    )
    ax.set_ylim(0, ymax * 1.1)

    plt.tight_layout()
    return fig


def _peptide_sample_map(columns, samples):
    columns = [str(column) for column in columns]
    samples = [str(sample) for sample in samples]
    mapping = {column: column for column in columns if column in samples}
    remaining_columns = [column for column in columns if column not in mapping]
    remaining_samples = [sample for sample in samples if sample not in columns]
    if remaining_columns and remaining_samples:
        by_id = sample_id_map(remaining_columns)
        sample_id_map(remaining_samples)
        for sample in remaining_samples:
            column = by_id.get(extract_sample_id(sample))
            if column is not None:
                mapping[column] = sample
    if samples and not mapping:
        raise ValueError("Peptide metadata does not match peptide sample columns.")
    return mapping


def coverage_plot_pep(data2_path, meta, id=True, header=True, legend=True,
                      plot_colors=None, width=10, height=6, dpi=100, quantity_column='Precursor.Quantity', level='peptide'):

    if level not in {"peptide", "precursor"}:
        raise ValueError("Coverage level must be peptide or precursor.")
    feature_column = 'Precursor.Id' if level == 'precursor' else 'Stripped.Sequence'

    if isinstance(data2_path, pd.DataFrame):
        data = data2_path.copy()
    else:
        data = sanitize_dataframe(read_data(data2_path)).copy()

    meta = meta.copy()
    meta['condition'] = meta['condition'].astype(str)
    meta = _sample_meta(meta.reset_index(drop=True), id=id, newline=True)

    ordered_new_samples = list(meta['new_sample'])
    sample_to_new = dict(zip(meta['sample'], meta['new_sample']))
    new_to_condition = dict(zip(meta['new_sample'], meta['condition']))

    if "File.Name" in data.columns:
        pivot = data.pivot_table(index=feature_column, columns='File.Name',
                                 values=quantity_column, aggfunc='max')
        rename_map = {column: sample_to_new[sample] for column, sample in
                      _peptide_sample_map(pivot.columns, meta['sample']).items()}
        pivot = pivot.rename(columns=rename_map)
        annotated_cols = [c for c in ordered_new_samples if c in pivot.columns]
        data_filtered = pivot[annotated_cols].reset_index()
    else:
        rename_map = {column: sample_to_new[sample] for column, sample in
                      _peptide_sample_map(data.columns.drop(feature_column, errors='ignore'), meta['sample']).items()}
        d2 = data.rename(columns=rename_map)
        annotated_cols = [c for c in ordered_new_samples if c in d2.columns]
        data_filtered = d2[annotated_cols].copy()
        if feature_column in data.columns:
            data_filtered = pd.concat([data[[feature_column]].reset_index(drop=True),
                                       data_filtered.reset_index(drop=True)], axis=1)
        else:
            data_filtered = data_filtered.reset_index().rename(columns={'index': feature_column})

    for c in data_filtered.columns:
        if c != feature_column:
            data_filtered[c] = pd.to_numeric(data_filtered[c], errors='coerce')
            data_filtered[c] = np.where(data_filtered[c].notna() & (data_filtered[c] != 0), 1, 0)

    # Reference line: features quantified in at least one annotated sample (the
    # union of the bars), as on coverage_plot; not the number of sequences in the file.
    peptides_count = int((data_filtered.drop(columns=[feature_column]).sum(axis=1) > 0).sum())

    plot_data = data_filtered.melt(id_vars=feature_column, var_name='Sample', value_name='Value')
    summary = plot_data.groupby('Sample')['Value'].sum().reset_index()
    summary['Sample'] = pd.Categorical(summary['Sample'], categories=ordered_new_samples, ordered=True)
    summary = summary.sort_values('Sample')

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    if plot_colors is None:
        colors = list(plt.rcParams['axes.prop_cycle'].by_key()['color'])
    else:
        colors = list(plot_colors)

    conditions = list(dict.fromkeys(meta['condition'].tolist()))
    color_map = {c: colors[i % len(colors)] for i, c in enumerate(conditions)}
    bar_colors = [color_map.get(new_to_condition.get(str(s), None), colors[0]) for s in summary['Sample'].astype(str)]

    ax.bar(range(len(summary)), summary['Value'].values, color=bar_colors)
    ax.axhline(y=peptides_count, color='red', linestyle='--')
    if header:
        ax.set_title(f"{level.capitalize()}s per sample")
    ax.set_ylabel(f"Number of {level}s")
    ax.set_xlabel("Sample")
    ax.set_xticks(range(len(summary)))
    ax.set_xticklabels([str(s) for s in summary['Sample'].astype(str)], rotation=90)

    if legend:
        handles = [Rectangle((0,0),1,1, color=color_map[c]) for c in conditions]
        ax.legend(handles, conditions, title="Condition", bbox_to_anchor=(1.05, 1), loc='upper left')

    plt.tight_layout()
    return fig


def histo_int(data, meta, plot_colors=None, header=True, legend=True,
              width=20, height=10, dpi=300):
    figsize_inches = (width / 2.54, height / 2.54)
    fig, ax = plt.subplots(figsize=figsize_inches, dpi=dpi)

    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns]

    mean_intensities = []
    for condition in meta['condition'].unique():
        columns = meta.loc[meta['condition'] == condition, 'sample'].tolist()
        mean_intensity = data_filtered[columns].mean(axis=1, skipna=True)
        mean_intensity = mean_intensity[np.isfinite(mean_intensity)]
        mean_intensities.append((condition, mean_intensity))

    n_conditions = len(mean_intensities)

    if plot_colors is None:
        colors = plt.cm.tab10.colors
        if n_conditions > len(colors):
            colors = plt.get_cmap('tab20').colors
    else:
        if len(plot_colors) < n_conditions:
            plot_colors = (plot_colors * (n_conditions // len(plot_colors) + 1))[:n_conditions]
        colors = plot_colors

    all_values = np.concatenate([vals for _, vals in mean_intensities])
    xmin, xmax = np.min(all_values), np.max(all_values)
    x_grid = np.linspace(xmin, xmax, 1000)

    for idx, (condition, vals) in enumerate(mean_intensities):
        kde = gaussian_kde(vals)
        density = kde(x_grid)
        ax.plot(x_grid, density, label=condition, color=colors[idx])

    ax.set_xlabel('log2 Intensity')
    ax.set_ylabel('Density')

    if header:
        ax.set_title('Distribution of mean intensity per condition (log2)')

    if legend:
        ax.legend(title='Condition', bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        leg = ax.get_legend()
        if leg is not None:
            leg.remove()
        plt.tight_layout()

    return fig


def boxplot_int(data, meta, outliers=False, header=True, plot_colors=None,
                width_cm=20, height_cm=10, dpi=100, text=False, text_size=9):
    n_conditions = meta['condition'].nunique()

    if plot_colors is not None:
        if len(plot_colors) < n_conditions:
            plot_colors = (plot_colors * (n_conditions // len(plot_colors) + 1))[:n_conditions]
    else:
        base_colors = plt.cm.tab10.colors
        if n_conditions > len(base_colors):
            base_colors = plt.get_cmap('tab20').colors
        plot_colors = base_colors[:n_conditions]

    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns]

    mean_intensities = []
    medians = []
    conditions_order = meta['condition'].unique()

    for condition in conditions_order:
        columns = meta.loc[meta['condition'] == condition, 'sample'].tolist()
        mean_intensity = data_filtered[columns].mean(axis=1, skipna=True)
        mean_intensity = mean_intensity[np.isfinite(mean_intensity)]
        mean_intensities.append(mean_intensity)
        if len(mean_intensity) > 0:
            medians.append(np.median(mean_intensity))
        else:
            medians.append(np.nan)

    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54), dpi=dpi)

    boxprops = dict(linewidth=1.5, color='black')
    whiskerprops = dict(linewidth=1.5, color='black')
    capprops = dict(linewidth=1.5, color='black')
    medianprops = dict(linewidth=2.5, color='firebrick')
    flierprops = dict(marker='o', markerfacecolor='red', markersize=5, linestyle='none') if outliers else dict(marker='')

    positions = np.arange(1, n_conditions + 1)
    bplot = ax.boxplot(
        mean_intensities,
        patch_artist=True,
        showfliers=outliers,
        boxprops=boxprops,
        whiskerprops=whiskerprops,
        capprops=capprops,
        medianprops=medianprops,
        flierprops=flierprops,
        positions=positions
    )

    for patch, color in zip(bplot['boxes'], plot_colors):
        patch.set_facecolor(color)

    if text:
        for pos, med in zip(positions, medians):
            if not np.isnan(med):
                ax.text(
                    # A fixed step above the line: a multiplicative offset sat on
                    # the line for medians near zero and below it for negative ones.
                    pos, med + 0.02 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
                    f"{med:.2f}",
                    ha='center', va='bottom', fontsize=text_size,
                    color='black', rotation=0, fontweight='bold'
                )

    ax.set_xticks(positions)
    ax.set_xticklabels(conditions_order)
    ax.set_xlabel("Condition")
    ax.set_ylabel("log2 Intensity")

    if header:
        ax.set_title("Mean intensity per condition (log2)")

    if ax.get_legend() is not None:
        ax.get_legend().remove()

    plt.tight_layout(rect=[0, 0, 0.85, 1])
    return fig


def boxplot_int_single(
    data, meta, outliers=False, id=True, header=True, legend=True, plot_colors=None,
    width_cm=20, height_cm=10, dpi=100, text=False, text_size=9
):
    meta = meta.copy()
    meta = _sample_meta(meta, id=id)
    data = _rename_samples(data, meta)

    intensities = data.melt(var_name="sample", value_name="intensity")
    intensities = intensities.merge(
        meta[["new_sample", "condition"]],
        left_on="sample", right_on="new_sample"
    )
    intensities = intensities.replace([np.inf, -np.inf], np.nan).dropna()

    samples = meta["new_sample"].tolist()

    grouped_data = [
        intensities.loc[intensities["sample"] == s, "intensity"].values
        for s in samples
    ]

    unique_conditions = meta["condition"].unique()
    if plot_colors is None:
        cmap = plt.get_cmap("tab10", len(unique_conditions))
        condition_colors = dict(zip(unique_conditions, [cmap(i) for i in range(len(unique_conditions))]))
    else:
        condition_colors = dict(zip(unique_conditions, plot_colors))

    sample_colors = [condition_colors[c] for c in meta["condition"]]

    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54), dpi=dpi)
    bp = ax.boxplot(grouped_data, patch_artist=True, showfliers=outliers)

    for patch, color in zip(bp["boxes"], sample_colors):
        patch.set_facecolor(color)

    if text:
        medians = [np.median(g) if len(g) > 0 else np.nan for g in grouped_data]
        for i, median in enumerate(medians):
            if not np.isnan(median):
                ax.text(
                    i + 1, median + 0.02 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
                    f"{median:.2f}",
                    ha="center", va="bottom",
                    fontsize=text_size, rotation=0, color="black", fontweight="bold"
                )

    ax.set_xticks(range(1, len(samples) + 1))
    ax.set_xticklabels(samples, rotation=90, ha="center")
    ax.set_ylabel("log2 Intensity")

    if header:
        ax.set_title("Measured protein intensity values (log2)")
    else:
        ax.set_title("")

    if legend:
        from matplotlib.patches import Patch
        legend_handles = [
            Patch(facecolor=condition_colors[c], edgecolor="black", label=c)
            for c in unique_conditions
        ]
        ax.legend(handles=legend_handles, title="Condition",
                  loc="center left", bbox_to_anchor=(1, 0.5))
        plt.subplots_adjust(right=0.8)
    else:
        if ax.get_legend() is not None:
            ax.get_legend().remove()
        plt.subplots_adjust(right=0.95)

    plt.tight_layout()
    return fig


def cov_plot(data, meta, outliers=False, header=True, legend=True, plot_colors=None,
             width_cm=20, height_cm=10, dpi=100, text=False, text_size=9,
             data_scale=None):
    """Plot per-condition coefficients of variation for linear intensities.

    ``CV = sd / mean`` is not defined on log2-transformed intensities.  Require
    callers to state the scale explicitly so a log2 matrix cannot silently
    produce a plausible-looking but scientifically invalid plot.
    """
    if data_scale is None:
        raise ValueError(
            "cov_plot requires data_scale='linear'; coefficient of variation "
            "is not meaningful on log2-transformed intensities."
        )
    normalized_scale = str(data_scale).strip().lower()
    if normalized_scale != "linear":
        if normalized_scale == "log2":
            raise ValueError(
                "cov_plot requires linear intensities; inverse-transform log2 "
                "data before plotting and pass data_scale='linear'."
            )
        raise ValueError("data_scale must be 'linear' for cov_plot.")

    data = _prepare_intensity_data(data, meta['sample'].tolist(), normalized_scale)
    conditions = meta['condition'].unique()
    valid_conditions = []
    cv_data = []

    for cond in conditions:
        cols = meta.loc[meta['condition'] == cond, 'sample'].tolist()
        if len(cols) >= 2:
            subset = data[cols]
            means = subset.mean(axis=1, skipna=True)
            sds = subset.std(axis=1, skipna=True)
            cv = (sds / means) * 100
            cv = cv[np.isfinite(cv)]
            if len(cv) > 0:
                valid_conditions.append(cond)
                cv_data.append(cv)

    n_conditions = len(valid_conditions)

    if plot_colors is not None:
        if len(plot_colors) < n_conditions:
            plot_colors = (plot_colors * (n_conditions // len(plot_colors) + 1))[:n_conditions]
    else:
        base_colors = plt.cm.tab10.colors
        if n_conditions > len(base_colors):
            base_colors = plt.get_cmap('tab20').colors
        plot_colors = base_colors[:n_conditions]

    fig, ax = plt.subplots(figsize=(width_cm / 2.54, height_cm / 2.54), dpi=dpi)

    boxprops = dict(linewidth=1.5, color='black')
    whiskerprops = dict(linewidth=1.5, color='black')
    capprops = dict(linewidth=1.5, color='black')
    medianprops = dict(linewidth=2.5, color='firebrick')
    flierprops = dict(marker='o', markerfacecolor='red', markersize=5, linestyle='none') if outliers else dict(marker='')

    positions = np.arange(1, n_conditions + 1)

    bplot = ax.boxplot(
        cv_data,
        patch_artist=True,
        showfliers=outliers,
        boxprops=boxprops,
        whiskerprops=whiskerprops,
        capprops=capprops,
        medianprops=medianprops,
        flierprops=flierprops,
        positions=positions
    )

    for patch, color in zip(bplot['boxes'], plot_colors):
        patch.set_facecolor(color)

    if text:
        for i, vals in enumerate(cv_data, start=1):
            med = np.median(vals)
            ax.text(i, med, f"{med:.2f}", ha="center", va="bottom",
                    fontsize=text_size, fontweight="bold", color="black")

    ax.set_xticks(positions)
    ax.set_xticklabels(valid_conditions)
    ax.set_xlabel("Condition")
    ax.set_ylabel("Coefficient of Variation (%)")

    if header:
        ax.set_title("Coefficient of Variation")

    if legend:
        from matplotlib.patches import Patch
        legend_handles = [Patch(facecolor=plot_colors[i], edgecolor='black', label=cond) for i, cond in enumerate(valid_conditions)]
        ax.legend(handles=legend_handles, title="Condition", loc='center left', bbox_to_anchor=(1, 0.5))
    else:
        if ax.get_legend() is not None:
            ax.get_legend().remove()

    plt.tight_layout()
    return fig


def minimum_enclosing_ellipse(points, tol=1e-3):
    N, d = points.shape
    Q = np.vstack([points.T, np.ones(N)])
    QT = Q.T
    u = np.ones(N) / N
    err = tol + 1
    for _ in range(10000):
        X = Q @ np.diag(u) @ QT
        M = np.diag(QT @ np.linalg.inv(X) @ Q)
        j = np.argmax(M)
        step_size = (M[j] - d - 1) / ((d + 1) * (M[j] - 1))
        new_u = (1 - step_size) * u
        new_u[j] += step_size
        err = np.linalg.norm(new_u - u)
        u = new_u
        if err <= tol:
            break
    else:
        raise ValueError("Enclosing ellipse did not converge.")
    center = points.T @ u
    A = np.linalg.inv(points.T @ np.diag(u) @ points - np.outer(center, center)) / d
    U, s, _ = np.linalg.svd(A)
    axes = 1. / np.sqrt(s)
    angle = np.degrees(np.arctan2(U[1, 0], U[0, 0]))
    return center, axes, angle


def fitted_group_ellipse(points):
    """Fit an enclosing ellipse only when the group reliably spans the plane.

    The points are copied row-major first, so the same values give the same
    ellipse whichever layout a pandas selection hands them over in.
    """
    array = np.ascontiguousarray(points, dtype=float)
    if array.ndim != 2 or array.shape[0] < 3 or array.shape[1] != 2 or not np.isfinite(array).all():
        return None
    try:
        origin = array.mean(axis=0)
        centered = array - origin
        scale = np.max(np.abs(centered))
        if not np.isfinite(scale) or scale == 0:
            return None
        normalized = centered / scale
        singular = np.linalg.svd(normalized, compute_uv=False)
        # The solver inverts a scatter matrix, squaring the coordinate condition number.
        if singular[-1] <= singular[0] * np.sqrt(np.finfo(float).eps):
            return None
        center, axes, angle = minimum_enclosing_ellipse(normalized)
        center, axes = origin + center * scale, axes * scale
    except (np.linalg.LinAlgError, ValueError, ZeroDivisionError, FloatingPointError):
        return None
    if not (np.isfinite(center).all() and np.isfinite(axes).all() and np.isfinite(angle)):
        return None
    if float(np.min(axes)) <= 0:
        return None
    return center, axes, angle


def ellipse_skip_message(groups):
    """What to say about the groups that got no ellipse."""
    names = [str(group) for group in groups if str(group).strip()]
    if not names:
        return ""
    listed = ", ".join(names)
    subject = "group" if len(names) == 1 else "groups"
    return (
        f"No ellipse was drawn for {subject} {listed}: {'its' if len(names) == 1 else 'their'} "
        "points have no spread in one direction -- they fall on a line, or two "
        "samples share the same position -- so there is no enclosing ellipse to fit. "
        "The points themselves are unaffected."
    )


def _prepare_pca_matrix(data, meta, *, plot_3d=False):
    annotated_columns = meta['sample'].astype(str).tolist()
    missing_columns = [column for column in annotated_columns if column not in data.columns]
    if missing_columns:
        raise ValueError(f"PCA sample columns are missing from data: {', '.join(missing_columns)}")

    n_components = 3 if plot_3d else 2
    numeric = data[annotated_columns].apply(pd.to_numeric, errors='coerce')
    numeric = numeric.replace([np.inf, -np.inf], np.nan)
    complete = numeric.dropna()
    if complete.shape[0] < n_components:
        raise ValueError(
            "PCA cannot be computed because only "
            f"{complete.shape[0]} of {numeric.shape[0]} features are complete across all samples; "
            "the missingness is too high. Impute the data before calling the PCA function."
        )

    transposed_expr = complete.T
    transposed_expr = transposed_expr.loc[:, transposed_expr.var(axis=0) > 0]
    if transposed_expr.shape[0] < n_components:
        raise ValueError(f"PCA needs at least {n_components} samples for this projection.")
    if transposed_expr.shape[1] < n_components:
        raise ValueError(
            f"PCA needs at least {n_components} complete, non-constant features; "
            f"only {transposed_expr.shape[1]} remain after filtering."
        )
    return transposed_expr, n_components


def pca_scores(data, meta, plot_3d=False, scaling="auto"):
    """The PCA coordinates `pca_plot` draws, as a table.

    One row per sample with PC1, PC2 (and PC3 with `plot_3d`), `sample` and
    `condition`. The explained variance of each component, in percent of the
    total, is in `.attrs["explained_variance"]`. Only features measured in every
    sample and not constant across them are used. `scaling="unit_variance"`
    divides each feature by its sample SD (n - 1), as R's `prcomp(scale. = TRUE)`.
    The sign of a component is arbitrary and may differ between implementations.
    """
    transposed_expr, n_components = _prepare_pca_matrix(data, meta, plot_3d=plot_3d)
    if resolve_feature_scaling(scaling, method="PCA") == "unit_variance":
        centred = transposed_expr - transposed_expr.mean(axis=0)
        deviation = centred.std(axis=0, ddof=1).replace(0.0, 1.0).fillna(1.0)
        transposed_expr = centred / deviation
    pca = PCA(n_components=n_components)
    pca_result = pca.fit_transform(transposed_expr)
    scores = pd.DataFrame(pca_result, columns=[f'PC{i+1}' for i in range(n_components)])
    scores['sample'] = transposed_expr.index
    conditions = dict(zip(meta['sample'].astype(str), meta['condition']))
    scores['condition'] = [conditions.get(str(sample)) for sample in scores['sample']]
    scores.attrs['explained_variance'] = [float(value) for value in pca.explained_variance_ratio_ * 100]
    return scores


def pca_plot(data, meta, header=True, legend=True, dot_size=3,
             width_cm=20, height_cm=10, dpi=100, plot_colors=None,
             plot_3d=False, add_ellipses=False, scaling="auto"):
    meta = meta.copy()  # the caller's metadata is left as it was
    meta['condition'] = pd.Categorical(meta['condition'], categories=meta['condition'].unique(), ordered=True)
    scores = pca_scores(data, meta, plot_3d=plot_3d, scaling=scaling)
    explained_variance = np.asarray(scores.attrs['explained_variance'])
    plot_scores = scores.drop(columns='condition').merge(meta, on='sample')
    plot_scores['condition'] = pd.Categorical(plot_scores['condition'], categories=meta['condition'].unique(), ordered=True)
    figsize = (width_cm / 2.54, height_cm / 2.54)
    if plot_3d:
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_subplot(111, projection='3d')
    else:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    colors = plot_colors if plot_colors is not None else plt.cm.tab10.colors
    conditions = plot_scores['condition'].unique()
    color_map = {cond: colors[i % len(colors)] for i, cond in enumerate(conditions)}
    skipped_ellipses = []
    for cond in conditions:
        subset = plot_scores[plot_scores['condition'] == cond]
        if plot_3d:
            ax.scatter(subset['PC1'], subset['PC2'], subset['PC3'],
                       label=cond, s=dot_size*10, alpha=0.7, color=color_map[cond])
        else:
            ax.scatter(subset['PC1'], subset['PC2'],
                       label=cond, s=dot_size*10, alpha=0.7, color=color_map[cond])
            if add_ellipses:
                fit = fitted_group_ellipse(subset[['PC1', 'PC2']].to_numpy())
                if fit is None:
                    skipped_ellipses.append(cond)
                else:
                    center, axes, angle = fit
                    ellipse = Ellipse(xy=center, width=2*axes[0], height=2*axes[1],
                                      angle=angle, facecolor=color_map[cond], alpha=0.15,
                                      edgecolor=color_map[cond], lw=1)
                    ax.add_patch(ellipse)
    # Said out loud, never drawn into the figure: a plot that leaves the tool
    # should carry no caption about how the tool drew it.
    if skipped_ellipses:
        warnings.warn(ellipse_skip_message(skipped_ellipses), stacklevel=2)
    if plot_3d:
        ax.set_xlabel(f"PC1 - {explained_variance[0]:.2f}%")
        ax.set_ylabel(f"PC2 - {explained_variance[1]:.2f}%")
        ax.set_zlabel(f"PC3 - {explained_variance[2]:.2f}%")
    else:
        ax.set_xlabel(f"PC1 - {explained_variance[0]:.2f}% variance")
        ax.set_ylabel(f"PC2 - {explained_variance[1]:.2f}% variance")
    if header:
        ax.set_title("PCA Plot" if not plot_3d else "3D PCA Plot")
    if legend:
        ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc='upper left')
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
    plt.tight_layout()
    return fig


def pca_plot_interactive(data, meta, plot_colors=None, header=True, legend=True,
                         dot_size=8, plot_3d=False, add_ellipses=False):
    import matplotlib.colors as mcolors
    import plotly.express as px
    import plotly.graph_objects as go
    if plot_colors is None:
        plot_colors = px.colors.qualitative.Plotly
    transposed_expr, n_components = _prepare_pca_matrix(data, meta, plot_3d=plot_3d)
    pca = PCA(n_components=n_components)
    pca_result = pca.fit_transform(transposed_expr)
    explained_variance = pca.explained_variance_ratio_ * 100
    pcs = [f"PC{i+1}" for i in range(n_components)]
    pca_scores = pd.DataFrame(pca_result, columns=pcs)
    pca_scores["sample"] = transposed_expr.index
    pca_scores = pca_scores.merge(meta, on="sample")
    if plot_3d:
        fig = px.scatter_3d(
            pca_scores, x="PC1", y="PC2", z="PC3",
            color="condition", color_discrete_sequence=plot_colors,
            hover_data={"sample": True, "condition": True}, opacity=0.8
        )
        fig.update_traces(marker=dict(size=dot_size))
        layout_kwargs = dict(
            scene=dict(
                xaxis=dict(title=f"PC1 - {explained_variance[0]:.2f}%"),
                yaxis=dict(title=f"PC2 - {explained_variance[1]:.2f}%"),
                zaxis=dict(title=f"PC3 - {explained_variance[2]:.2f}%"),
                aspectmode="cube",  # the same fixed box as the application (2026-10-09)
            ),
            showlegend=legend
        )
        if header:
            layout_kwargs["title"] = "3D PCA Plot"
    else:
        x_label = f"PC1 - {explained_variance[0]:.2f}% variance"
        y_label = f"PC2 - {explained_variance[1]:.2f}% variance"
        fig = px.scatter(
            pca_scores, x="PC1", y="PC2",
            color="condition", color_discrete_sequence=plot_colors,
            hover_data={"sample": True, "condition": True}, opacity=0.8
        )
        fig.update_traces(marker=dict(size=dot_size))
        layout_kwargs = dict(
            xaxis=dict(title=x_label, zeroline=False),
            yaxis=dict(title=y_label, zeroline=False),
            showlegend=legend
        )
        if header:
            layout_kwargs["title"] = "PCA Plot"
        if add_ellipses:
            skipped_ellipses = []
            for i, cond in enumerate(pca_scores["condition"].unique()):
                subset = pca_scores[pca_scores["condition"] == cond]
                fit = fitted_group_ellipse(subset[["PC1", "PC2"]].to_numpy())
                if fit is None:
                    skipped_ellipses.append(cond)
                else:
                    center, axes, angle = fit
                    t = np.linspace(0, 2*np.pi, 200)
                    ellipse = np.array([axes[0]*np.cos(t), axes[1]*np.sin(t)])
                    R = np.array([[np.cos(np.radians(angle)), -np.sin(np.radians(angle))],
                                  [np.sin(np.radians(angle)),  np.cos(np.radians(angle))]])
                    ellipse_rot = R @ ellipse
                    ellipse_x = ellipse_rot[0] + center[0]
                    ellipse_y = ellipse_rot[1] + center[1]
                    rgba = mcolors.to_rgba(plot_colors[i % len(plot_colors)], alpha=0.15)
                    fill_str = f'rgba({int(rgba[0]*255)},{int(rgba[1]*255)},{int(rgba[2]*255)},{rgba[3]})'
                    fig.add_trace(go.Scatter(
                        x=ellipse_x, y=ellipse_y,
                        mode="lines", fill="toself",
                        line=dict(color=plot_colors[i % len(plot_colors)], width=1),
                        fillcolor=fill_str,
                        showlegend=False
                    ))
            if skipped_ellipses:
                warnings.warn(ellipse_skip_message(skipped_ellipses), stacklevel=2)
    fig.update_layout(**layout_kwargs)
    return fig


def abundance_axis_label(workflow, centered=False):
    """Y-axis label for the abundance plot.

    ``robust_site_median`` phosphoprotein aggregation centres every site on its
    own across-sample median, so those values carry a ratio to that median
    rather than an intensity. Every other phosprot mode, and both other
    workflows, hold real abundances.
    """
    if centered:
        return f"log10 {workflow} Ratio to Site Median"
    return f"log10 {workflow} Intensity"


def abundance_plot(data, meta, workflow="Protein", plot_colors=None, width_cm=20, height_cm=10, dpi=300,
                   legend=True, header=True, data_scale="log2", centered=False):
    """Rank arithmetic mean linear intensities (or site-median ratios when centered)."""
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    if str(data_scale).strip().lower() == "log2":
        data[meta['sample']] = np.exp2(data[meta['sample']])
    unique_conditions = meta['condition'].unique()

    if plot_colors is not None:
        if len(plot_colors) < len(unique_conditions):
            reps = int(np.ceil(len(unique_conditions) / len(plot_colors)))
            plot_colors = (plot_colors * reps)[:len(unique_conditions)]
    else:
        plot_colors = plt.get_cmap('tab10').colors[:len(unique_conditions)]

    annotated_columns = meta['sample'].tolist()

    if workflow == "Protein":
        key_col = "ProteinNames"
    elif workflow == "Phosphosite":
        key_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        key_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    data_filtered = data[[key_col] + annotated_columns].copy()

    mean_intensities = pd.DataFrame()
    mean_intensities[key_col] = data_filtered[key_col]

    for condition in unique_conditions:
        columns = meta.loc[meta['condition'] == condition, 'sample'].tolist()
        condition_data = data_filtered[[key_col] + columns].copy()
        means = condition_data[columns].mean(axis=1, skipna=True)
        # log10 of the value, with no pseudocount: the axis names the quantity,
        # so `log10(x + 1)` would plot something else. Non-positive means have
        # no logarithm and drop out with the NaNs below.
        means_log = np.log10(means.where(means > 0))
        mean_intensities[condition] = means_log

    long_intensities = mean_intensities.melt(
        id_vars=[key_col], var_name="Condition", value_name="log10Intensity"
    ).dropna(subset=["log10Intensity"])
    long_intensities['Rank'] = long_intensities.groupby('Condition')['log10Intensity'] \
                                                .rank(ascending=False, method='first')
    long_intensities['Condition'] = pd.Categorical(
        long_intensities['Condition'], categories=unique_conditions, ordered=True
    )

    width_in = width_cm / 2.54
    height_in = height_cm / 2.54
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)

    for cond, color in zip(unique_conditions, plot_colors):
        subset = long_intensities[long_intensities['Condition'] == cond]
        ax.scatter(subset['Rank'], subset['log10Intensity'], label=cond, color=color, s=5)

    ax.set_xlabel(f"{workflow} Rank")
    ax.set_ylabel(abundance_axis_label(workflow, centered))

    if header:
        ax.set_title(f"Abundance plot - {workflow}")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc='upper left')
        fig.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        if ax.get_legend() is not None:
            ax.legend_.remove()
        fig.tight_layout()

    return fig


def interactive_abundance_plot(data, meta, condition, workflow="Protein", search=None, max_ptms=5,
                               data_scale="log2", centered=False):
    """Rank arithmetic mean linear intensities (or site-median ratios when centered)."""
    annotated_columns = meta.loc[meta["condition"] == condition, "sample"].tolist()
    data = _prepare_intensity_data(data, annotated_columns, data_scale)
    if str(data_scale).strip().lower() == "log2":
        data[annotated_columns] = np.exp2(data[annotated_columns])

    if workflow == "Protein":
        feature_col = "ProteinNames"
    elif workflow == "Phosphosite":
        feature_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        feature_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    columns_to_use = [feature_col] + annotated_columns
    data_filtered = data[columns_to_use].copy()
    condition_means = data_filtered[annotated_columns].mean(axis=1, skipna=True)
    # See `plot_abundance`: log10 of the value, no pseudocount.
    condition_means = np.log10(condition_means.where(condition_means > 0))

    mean_intensities = pd.DataFrame({
        "Feature": data_filtered[feature_col],
        "log10Intensity": condition_means
    }).dropna()

    mean_intensities["Feature"] = mean_intensities["Feature"].astype(str).str.split(";").str[0]

    if workflow == "Phosphoprotein":
        if "site_num" in data.columns:
            site_map = data.set_index("Phosphoprotein")["site_num"].to_dict()
        else:
            site_map = data.groupby("Phosphoprotein").size().to_dict()
        mean_intensities["site_num"] = mean_intensities["Feature"].map(site_map)

        if "PTM_Collapse_keys" in data.columns:
            ptm_map = data.set_index("Phosphoprotein")["PTM_Collapse_keys"].to_dict()
        else:
            ptm_map = data.groupby("Phosphoprotein")["PTM_Collapse_key"] \
                          .agg(lambda x: ";".join(sorted(set(x.dropna().astype(str))))).to_dict()
        mean_intensities["PTM_Collapse_keys"] = mean_intensities["Feature"].map(ptm_map)

        def truncate_ptms(ptm_str, max_items=max_ptms):
            ptms = str(ptm_str).split(";")
            return ";".join(ptms[:max_items]) + (";..." if len(ptms) > max_items else "")

        mean_intensities["HoverLabel"] = mean_intensities.apply(
            lambda row: f"{row['Feature']} ({row['site_num']} sites)\n{truncate_ptms(row['PTM_Collapse_keys'])}",
            axis=1
        )
    else:
        mean_intensities["HoverLabel"] = mean_intensities["Feature"]

    mean_intensities = mean_intensities.sort_values("log10Intensity", ascending=False).reset_index(drop=True)
    mean_intensities["Rank"] = mean_intensities.index + 1

    if search is None:
        search = []
    mean_intensities["Color"] = np.where(mean_intensities["Feature"].isin(search), "red", "blue")
    mean_intensities["TextLabel"] = np.where(mean_intensities["Feature"].isin(search),
                                             mean_intensities["Feature"], "")

    hover_cols = {"HoverLabel": True, "Rank": True, "log10Intensity": True, "Color": False, "TextLabel": False}

    fig = px.scatter(
        mean_intensities,
        x="Rank",
        y="log10Intensity",
        color="Color",
        text="TextLabel",
        hover_data=hover_cols,
        color_discrete_map={"red": "red", "blue": "blue"},
        title=f"Abundance plot - {condition} ({workflow})"
    )

    fig.update_traces(marker=dict(size=6), textposition="top center")
    fig.update_layout(
        xaxis_title=f"{workflow} Rank",
        yaxis_title=abundance_axis_label(workflow, centered),
        showlegend=False
    )

    return fig


def sample_correlation_matrix(data, meta, id=True, data_scale="log2"):
    """The Pearson correlations between samples that `corr_plot` colours.

    Rows and columns are the display names (`condition_n`, with the sample id
    when `id=True`), in metadata order -- `corr_plot` then reorders them by
    clustering. Each pair uses the features measured in both samples; a sample
    with no values at all is left out.
    """
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    meta = _sample_meta(meta.copy(), id=id)
    data = _rename_samples(data, meta)
    data_filtered = data[meta['new_sample'].tolist()].dropna(axis=1, how='all')
    if data_filtered.shape[1] < 2:
        raise ValueError("At least two non-empty sample columns are required for correlation plot.")
    return data_filtered.corr(method='pearson')



def correlation_matrix_mesh(ax, matrix, cmap, vmin, vmax):
    """The correlation matrix as one rectangle per cell, laid out as `matshow` lays it out.

    `matshow` draws the matrix as an image, so an SVG or PDF download held a
    bitmap: blurred when scaled, and not one shape per cell to edit. A mesh is
    vector in those formats and the same picture in a PNG. Row 0 is at the top,
    the cells are square and the column ticks are on top, as before.
    """
    values = np.ma.masked_invalid(np.asarray(matrix, dtype=float))
    rows, cols = values.shape
    mesh = ax.pcolormesh(
        np.arange(cols + 1) - 0.5,
        np.arange(rows + 1) - 0.5,
        values,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="flat",
        # Each cell's edge in its own colour: without it a vector viewer shows
        # hairline gaps between neighbouring cells.
        edgecolors="face",
        linewidth=0.0,
    )
    ax.set_xlim(-0.5, cols - 0.5)
    ax.set_ylim(rows - 0.5, -0.5)
    ax.set_aspect("equal")
    ax.xaxis.tick_top()
    return mesh

def corr_plot(data, meta, method="Matrix", id=True, full_range=False, width=10, height=8, dpi=100,
              data_scale="log2"):
    correlation_matrix = sample_correlation_matrix(data, meta, id=id, data_scale=data_scale)
    incomplete = not np.isfinite(correlation_matrix.to_numpy()).all()
    ordered_corr = correlation_matrix
    if not incomplete:
        distance_matrix = (1 - correlation_matrix).clip(lower=0, upper=2).to_numpy(copy=True)
        np.fill_diagonal(distance_matrix, 0)
        linkage_matrix = linkage(squareform(distance_matrix), method='complete')
        ordered_indices = leaves_list(linkage_matrix)
        ordered_corr = correlation_matrix.iloc[ordered_indices, ordered_indices]

    finite = ordered_corr.to_numpy()[np.isfinite(ordered_corr.to_numpy())]
    vmin, vmax = (-1, 1) if full_range or not finite.size else (finite.min(), finite.max())
    if np.isclose(vmin, vmax):
        vmin, vmax = -1, 1

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    if method == "Matrix":
        cmap = plt.get_cmap('coolwarm').with_extremes(bad='#eeeeee')
        cax = correlation_matrix_mesh(ax, ordered_corr, cmap, vmin, vmax)
        plt.xticks(range(len(ordered_corr.columns)), ordered_corr.columns, rotation=90, ha='center', va='bottom')
        plt.yticks(range(len(ordered_corr.index)), ordered_corr.index)
        fig.colorbar(cax)

    elif method == "Ellipse":
        n = len(ordered_corr)
        ax.set_xlim(0, n)
        ax.set_ylim(0, n)
        ax.set_xticks(np.arange(n) + 0.5)
        ax.set_yticks(np.arange(n) + 0.5)
        ax.set_xticklabels(ordered_corr.columns, rotation=90, ha='center', va='top')
        ax.set_yticklabels(ordered_corr.index)
        ax.invert_yaxis()

        for i in range(n):
            for j in range(n):
                r = ordered_corr.iloc[i, j]
                if not np.isfinite(r):
                    continue
                width_ellipse = 0.9
                height_ellipse = 0.9 * (1 - abs(r))
                angle = 45 if r > 0 else -45
                ellipse = Ellipse(
                    (j + 0.5, i + 0.5),
                    width=width_ellipse,
                    height=height_ellipse,
                    angle=angle,
                    facecolor="red" if r > 0 else "blue",
                    alpha=0.6
                )
                ax.add_patch(ellipse)

        sm = plt.cm.ScalarMappable(cmap="coolwarm", norm=plt.Normalize(vmin=-1, vmax=1))
        fig.colorbar(sm, ax=ax)

    else:
        raise ValueError("method must be 'matrix' or 'ellipse'")

    missing_rows, missing_cols = np.where(~np.isfinite(ordered_corr.to_numpy()))
    offset = 0.5 if method == "Ellipse" else 0
    for i, j in zip(missing_rows, missing_cols):
        ax.text(j + offset, i + offset, "NA", ha="center", va="center", fontsize=7, color='#666666')
    if incomplete:
        ax.set_xlabel("NA: correlation unavailable; clustering skipped (metadata order)")

    plt.tight_layout()
    return fig


#STATISTIC FUNCTIONS
def _variance_and_count(values):
    """Per-row variance and observed count for one independent group.

    A group with one observation has no defined variance; numpy warns and
    returns NaN, which propagates to a NaN standard error and then to p = 1.
    That is the safe direction, so the expected warning is silenced rather than
    surfaced to the notebook user.
    """
    counts = np.sum(np.isfinite(values), axis=1).astype(float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        variances = np.nanvar(values, axis=1, ddof=1)
    return variances, counts


def _satterthwaite(components):
    """Standard error and effective degrees of freedom for a sum of group means.

    Each component is (variance, n) for one independent group.
    """
    ratios = [variance / count for variance, count in components]
    se_squared = np.sum(ratios, axis=0)
    denominator = np.sum(
        [ratio**2 / np.maximum(count - 1.0, 1e-12) for ratio, (_, count) in zip(ratios, components)],
        axis=0,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        dof = se_squared**2 / denominator
    dof = np.where(se_squared == 0, 1.0, dof)
    return np.sqrt(se_squared), dof


def _resolve_volcano_label_column(data, workflow, label_column=None):
    """Resolve the displayed/tested feature without duplicating Volcano math."""
    if label_column is not None:
        label_column = str(label_column)
        if label_column not in data.columns:
            raise ValueError(f"label_column '{label_column}' was not found in data.")
        return label_column
    if workflow == "Protein":
        return "ProteinNames"
    if workflow == "Phosphosite":
        return "PTM_Collapse_key"
    if workflow == "Phosphoprotein":
        return "Phosphoprotein"
    raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")


def _adjust_finite_pvalues(pvalues):
    pvalues = np.asarray(pvalues, dtype=float)
    finite = np.isfinite(pvalues)
    adjusted = np.full(pvalues.shape, np.nan)
    if finite.any():
        adjusted[finite] = multipletests(pvalues[finite], method="fdr_bh")[1]
    return adjusted


def volcano_data_f(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                   workflow="Protein", paired="Unpaired", uncorrected=False,
                   test_type=None, label_column=None, observed=None):
    """Differential abundance between two conditions.

    `test_type` selects the design and variance model together: "unpaired",
    "unpaired_welch" or "paired". When
    it is omitted the older `paired` argument is used, so existing calls keep
    their behaviour.

    Pass `observed` (the matrix before `impute_values`) when `data` is imputed:
    the result then gains `n_imputed__<condition>` and `imputed_values`, the
    number of imputed values behind each row. Imputed values are tested as if
    measured. Phosphoprotein tables with site-contribution columns get the counts
    without it.
    """
    if condition1 == condition2:
        raise ValueError("Please select two different conditions.")
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    if test_type is None:
        is_paired = paired_test_enabled(paired)
        variance = "pooled"
    else:
        is_paired, variance = resolve_test_type(test_type)
    label_col = _resolve_volcano_label_column(data, workflow, label_column)

    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()
    if is_paired:
        annotated_columns1, annotated_columns2 = paired_sample_columns(
            meta, condition1, condition2
        )
    cols_to_use = [label_col] + annotated_columns1 + annotated_columns2

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].copy()
    imputed_counts = _imputed_counts_for(
        data, observed, {condition1: annotated_columns1, condition2: annotated_columns2}
    )
    arr_x = df[annotated_columns1].to_numpy(dtype=float)
    arr_y = df[annotated_columns2].to_numpy(dtype=float)

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)

    df = df.loc[valid_mask]
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask]
    n2 = n2_real[valid_mask]

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean1 - mean2

    if not is_paired:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        if variance == "welch":
            # Unequal variances: no pooling, Welch-Satterthwaite degrees of freedom.
            se, dfree = _satterthwaite([(var1, n1), (var2, n2)])
        else:
            pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
            se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
            dfree = n1 + n2 - 2
        t_stat = _guarded_t_statistic(log2fc, se)
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        diffs = arr_x - arr_y
        valid_paired = np.sum(np.isfinite(diffs), axis=1) >= 2
        if not np.any(valid_paired):
            raise ValueError("No rows have enough paired values for the selected comparison.")
        df = df.loc[valid_paired]
        arr_x = arr_x[valid_paired]
        arr_y = arr_y[valid_paired]
        diffs = diffs[valid_paired]
        mean_diff, n_diff, pvals = paired_t_test(diffs)
        log2fc = mean_diff

    no_variation = without_variation([np.round(diffs, 9)] if is_paired else [arr_x, arr_y])
    pvals = np.where(no_variation, np.nan, pvals)

    # `adj_pval` is always Benjamini-Hochberg; `selected_pval` is the one
    # significance is called on (raw when `uncorrected`), as in the web app.
    adj_pvals = _adjust_finite_pvalues(pvals)
    selected_pvals = pvals if uncorrected else adj_pvals

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    significance[(selected_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(selected_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    result = {
        label_col: df[label_col].values,
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "selected_pval": selected_pvals,
        "significance": significance,
        "neg_log10_selected_pval": negative_log10(selected_pvals),
        # Marks constant groups (paired: constant differences); rows where every
        # group is constant have no p-value at all.
        "zero_variance": (constant_differences(diffs) if is_paired
                          else constant_within_group(arr_x) | constant_within_group(arr_y)),
    }

    if workflow == "Phosphoprotein":
        if "site_num" in df.columns:
            result["site_num"] = df["site_num"].values
        if "PTM_Collapse_keys" in df.columns:
            result["PTM_Collapse_keys"] = df["PTM_Collapse_keys"].values
    if is_paired:
        result["n_pairs"] = n_diff.astype(int)

    result = pd.DataFrame(result)
    if imputed_counts is not None:
        for column in imputed_counts.columns:
            result[column] = imputed_counts.loc[df.index, column].to_numpy()
    return result


def volcano_data_f_control(data, meta, condition1, condition2, condition1_control, condition2_control,
    in_pval=0.05, in_log2fc=1, workflow="Protein", paired="Unpaired", uncorrected=False,
    test_type=None, label_column=None, observed=None):
    """Control-adjusted differential abundance using the web application's tests.

    `test_type` accepts the same five modes as :func:`volcano_data_f`. When it
    is omitted, the legacy `paired` argument remains authoritative. `observed`
    adds the imputed-value counts described there, for all four groups.

    The four conditions must be distinct, as in the web app. With one control
    shared by both sides the fold change reduces to condition1 - condition2, but
    the control's variance would enter the standard error twice: raw p < 0.05
    fell to 1.3 % of null rows instead of 5 %.
    """
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    named = [str(value).strip() for value in (condition1, condition1_control, condition2, condition2_control)]
    if len(set(named)) != len(named):
        raise ValueError(
            "Control-corrected volcano analysis requires four distinct conditions; "
            "an experimental condition cannot be used as its own control."
        )
    if test_type is None:
        is_paired = paired_test_enabled(paired)
        variance = "pooled"
    else:
        is_paired, variance = resolve_test_type(test_type)
    label_col = _resolve_volcano_label_column(data, workflow, label_column)

    c1_cols = meta.loc[meta["condition"] == condition1, "sample"].tolist()
    c2_cols = meta.loc[meta["condition"] == condition2, "sample"].tolist()
    c1_ctrl_cols = meta.loc[meta["condition"] == condition1_control, "sample"].tolist()
    c2_ctrl_cols = meta.loc[meta["condition"] == condition2_control, "sample"].tolist()

    if not c1_cols or not c2_cols:
        raise ValueError("No samples found for condition1 and/or condition2 in meta.")
    if not c1_ctrl_cols or not c2_ctrl_cols:
        raise ValueError("No samples found for condition1_control and/or condition2_control in meta.")
    if is_paired:
        c1_cols, c2_cols = paired_sample_columns(meta, condition1, condition2)

    # Deduplicated: using one condition as both controls (a common design) would
    # otherwise select the same columns twice, and df[c1_ctrl_cols] would then
    # return each control column twice -- halving the group's apparent variance
    # and doubling its n, both of which shrink the standard error.
    cols_to_use = list(dict.fromkeys(
        [label_col] + c1_cols + c2_cols + c1_ctrl_cols + c2_ctrl_cols
    ))

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].copy()
    imputed_counts = _imputed_counts_for(data, observed, {
        condition1: c1_cols, condition2: c2_cols,
        condition1_control: c1_ctrl_cols, condition2_control: c2_ctrl_cols,
    })
    arr_c1 = df[c1_cols].to_numpy(dtype=float)
    arr_c2 = df[c2_cols].to_numpy(dtype=float)
    arr_c1_ctrl = df[c1_ctrl_cols].to_numpy(dtype=float)
    arr_c2_ctrl = df[c2_ctrl_cols].to_numpy(dtype=float)

    c1_ctrl_mean = np.nanmean(arr_c1_ctrl, axis=1)
    c2_ctrl_mean = np.nanmean(arr_c2_ctrl, axis=1)

    arr_x = arr_c1 - c1_ctrl_mean[:, None]
    arr_y = arr_c2 - c2_ctrl_mean[:, None]

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    valid_mask &= np.sum(np.isfinite(arr_c1_ctrl), axis=1) >= 2
    valid_mask &= np.sum(np.isfinite(arr_c2_ctrl), axis=1) >= 2

    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for the selected comparison.")

    df = df.loc[valid_mask]
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask]
    n2 = n2_real[valid_mask]

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean1 - mean2

    # Subtracting each control mean shifts a row by a constant, which leaves the
    # test groups' own variance untouched -- so a two-group standard error omits
    # the uncertainty of the control means entirely and understates the true
    # uncertainty. On a complete null that produced a 12.75% false-positive rate
    # against a nominal 5%. The control groups are propagated as additional
    # independent components instead.
    control_arrays = [arr_c1_ctrl[valid_mask], arr_c2_ctrl[valid_mask]]

    if not is_paired:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        groups = [(var1, n1), (var2, n2)]
        groups.extend(_variance_and_count(control) for control in control_arrays)
        # With controls, pooled and Welch both propagate four independent
        # group means with a Satterthwaite approximation, matching the web.
        se, dfree = _satterthwaite(groups)
        t_stat = _guarded_t_statistic(log2fc, se)
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        diffs = arr_x - arr_y
        n_diff = np.sum(np.isfinite(diffs), axis=1)
        valid_paired = n_diff >= 2

        if not np.any(valid_paired):
            raise ValueError("No rows have enough paired values for the selected comparison.")
        df = df.loc[valid_paired]
        arr_x = arr_x[valid_paired]
        arr_y = arr_y[valid_paired]
        diffs = diffs[valid_paired]
        control_arrays = [control[valid_paired] for control in control_arrays]
        mean_diff, n_diff, _ = paired_t_test(diffs)
        log2fc = mean_diff
        # Same reasoning: the within-pair spread paired_t_test sees is unchanged
        # by the control subtraction, so propagate the control means explicitly.
        difference_variance = np.nanvar(diffs, axis=1, ddof=1)
        components = [(difference_variance, n_diff.astype(float))]
        components.extend(_variance_and_count(control) for control in control_arrays)
        se, dfree = _satterthwaite(components)
        t_stat = _guarded_t_statistic(log2fc, se)
        pvals = 2 * t.sf(np.abs(t_stat), dfree)

    no_variation = without_variation(
        [np.round(diffs, 9), *control_arrays] if is_paired else [arr_x, arr_y, *control_arrays]
    )
    pvals = np.where(no_variation, np.nan, pvals)

    # `adj_pval` is always Benjamini-Hochberg; `selected_pval` is the one
    # significance is called on (raw when `uncorrected`), as in the web app.
    adj_pvals = _adjust_finite_pvalues(pvals)
    selected_pvals = pvals if uncorrected else adj_pvals

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    significance[(selected_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(selected_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    result = {
        label_col: df[label_col].values,
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "selected_pval": selected_pvals,
        "significance": significance,
        "neg_log10_selected_pval": negative_log10(selected_pvals),
    }

    if workflow == "Phosphoprotein":
        if "site_num" in df.columns:
            result["site_num"] = df["site_num"].values
        if "PTM_Collapse_keys" in df.columns:
            result["PTM_Collapse_keys"] = df["PTM_Collapse_keys"].values
    if is_paired:
        result["n_pairs"] = n_diff.astype(int)

    result = pd.DataFrame(result)
    if imputed_counts is not None:
        for column in imputed_counts.columns:
            result[column] = imputed_counts.loc[df.index, column].to_numpy()
    return result


def _volcano_label_col(volcano_df):
    """The column that names a volcano's features."""
    if 'Phosphoprotein' in volcano_df.columns:
        return 'Phosphoprotein'
    if 'ProteinNames' in volcano_df.columns:
        return 'ProteinNames'
    return 'PTM_Collapse_key'


def _volcano_hover_text(volcano_df, label_col, max_chars=100):
    """Hover text: the feature name; for a phosphoprotein also its site count and
    its sites, the list cut at `max_chars`."""
    hover_text = volcano_df[label_col].astype(str)
    if label_col == 'Phosphoprotein':
        if 'site_num' in volcano_df.columns:
            hover_text += " (" + volcano_df['site_num'].astype(str) + " sites)"
        if 'PTM_Collapse_keys' in volcano_df.columns:
            hover_text += "<br>" + volcano_df['PTM_Collapse_keys'].astype(str).apply(
                lambda x: x if len(x) <= max_chars else x[:max_chars] + " ..."
            )
    return hover_text


def _volcano_plot_base(volcano_df, condition1, condition2, in_pval, in_log2fc, uncorrected,
                       highlight_terms=None, max_chars=100):
    """The interactive volcano `volcano_plot` and `volcano_plot_h` both draw.

    One trace per significance class, and a second, ringed one for the features
    named in `highlight_terms` (matched on the part of a name before `_`, case
    ignored). A class with no points gets no trace. The R functions'
    `.volcano_plot_base` draws the same figure.
    """
    if highlight_terms is not None and not isinstance(highlight_terms, list):
        highlight_terms = [highlight_terms]

    def normalize_name(name):
        return str(name).split('_')[0].lower()

    highlight_terms_norm = [normalize_name(t) for t in highlight_terms] if highlight_terms else []
    label_col = _volcano_label_col(volcano_df)

    color_mapping = {'Downregulated': 'blue', 'Not significant': 'gray', 'Upregulated': 'red'}
    y_hline = -np.log10(in_pval)
    max_y = max(y_hline, volcano_df['neg_log10_selected_pval'].max())

    shapes = [
        dict(type="line", x0=in_log2fc, x1=in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=-in_log2fc, x1=-in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=volcano_df['log2FC'].min(), x1=volcano_df['log2FC'].max(),
             y0=y_hline, y1=y_hline, line=dict(color="black", dash="dash"))
    ]

    fig = go.Figure()
    for sig, color in color_mapping.items():
        subset = volcano_df[volcano_df['significance'] == sig]
        if highlight_terms_norm:
            highlighted = subset[label_col].apply(
                lambda x: any(n in highlight_terms_norm for n in [normalize_name(y) for y in str(x).split(';')])
            ).astype(bool)
        else:
            highlighted = pd.Series(False, index=subset.index)

        for ringed in (False, True):
            points = subset[highlighted == ringed]
            if len(points) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=points['log2FC'],
                y=points['neg_log10_selected_pval'],
                mode='markers',
                marker=dict(color=color, size=8, line=dict(color='lime', width=3)) if ringed else dict(color=color, size=5),
                text=_volcano_hover_text(points, label_col, max_chars),
                name=f"{sig} (highlighted)" if ringed else sig,
                hoverinfo='text'
            ))

    fig.update_layout(
        title=f"{condition1} vs {condition2}",
        xaxis_title=f"log2 fold change ({condition1} - {condition2})",
        yaxis_title='-log10 adj. p-value' if not uncorrected else '-log10 p-value',
        shapes=shapes,
        hovermode='closest'
    )
    return fig


def volcano_plot(volcano_df, condition1, condition2, in_pval=0.05, in_log2fc=1, uncorrected=False, max_chars=100):
    return _volcano_plot_base(volcano_df, condition1, condition2, in_pval, in_log2fc, uncorrected,
                              max_chars=max_chars)


def volcano_plot_h(volcano_df, condition1, condition2,
                   in_pval=0.05, in_log2fc=1, uncorrected=False,
                   highlight_terms=None, max_chars=100):
    return _volcano_plot_base(volcano_df, condition1, condition2, in_pval, in_log2fc, uncorrected,
                              highlight_terms=highlight_terms, max_chars=max_chars)


def anova_data_f(data, meta, conditions=None, in_pval=0.05, workflow="Protein", uncorrected=False,
                 observed=None):
    """One-way ANOVA per row. `observed` adds imputed-value counts as in volcano_data_f."""
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
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
        extra_cols = [
            column
            for column in ("Gene_group", "GeneNames")
            if column in data.columns
        ][:1]
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].copy()
    df[sample_cols] = df[sample_cols].apply(pd.to_numeric, errors="coerce")
    imputed_counts = _imputed_counts_for(data, observed, condition_cols)

    valid = np.ones(len(df), dtype=bool)
    groups = []
    for cols in condition_cols.values():
        group = df[cols].to_numpy(dtype=float)
        valid &= np.sum(~np.isnan(group), axis=1) >= 2
        groups.append(group)

    df = df.loc[valid].copy()
    groups = [group[valid] for group in groups]
    if df.empty:
        raise ValueError("No rows have enough replicate values for ANOVA.")

    try:
        f_stat, pvals = stats.f_oneway(*groups, axis=1, nan_policy="omit")
    except TypeError:
        f_stat = np.empty(len(df), dtype=float)
        pvals = np.empty(len(df), dtype=float)
        for i in range(len(df)):
            row_groups = [group[i][~np.isnan(group[i])] for group in groups]
            f_stat[i], pvals[i] = stats.f_oneway(*row_groups)

    # f_oneway returns NaN only for a row that is constant throughout; those are
    # dropped. A row constant within every condition but different between them
    # gets an infinite (or enormous) F; it stays, flagged zero_variance, but gets
    # no p-value -- the same rule the volcano applies to rows without variation.
    finite = np.isfinite(pvals)
    df = df.loc[finite].copy()
    groups = [group[finite] for group in groups]
    f_stat = f_stat[finite]
    pvals = pvals[finite]

    means = pd.DataFrame({
        condition: np.nanmean(group, axis=1)
        for condition, group in zip(condition_cols.keys(), groups)
    }, index=df.index)

    # No variation within any condition: an infinite F says only that the
    # variance is absent, not that the difference is large. No p-value, out of
    # the BH family, shown as Unavailable.
    zero_variance = np.logical_and.reduce([constant_within_group(group) for group in groups])
    pvals = np.where(zero_variance, np.nan, pvals)

    out = df[cols_to_use].copy()
    out["f_statistic"] = f_stat
    out["pval"] = pvals
    out["adj_pval"] = _adjust_finite_pvalues(pvals)
    out["selected_pval"] = pvals if uncorrected else out["adj_pval"].to_numpy()
    significance = np.where(out["selected_pval"] < in_pval, "Significant", "Not significant").astype(object)
    significance[~np.isfinite(pvals)] = "Unavailable"
    out["significance"] = significance
    out["neg_log10_selected_pval"] = -np.log10(np.clip(out["selected_pval"], np.finfo(float).tiny, None))
    out["zero_variance"] = zero_variance

    for condition in means.columns:
        out[f"mean_{condition}"] = means[condition].to_numpy()
    if imputed_counts is not None:
        for column in imputed_counts.columns:
            out[column] = imputed_counts.loc[df.index, column].to_numpy()

    # Benjamini-Hochberg ties many features to the same adjusted p, so sorting on
    # it alone leaves the order within those groups to whichever sort the
    # language happens to use -- the R functions returned a different one. Raw p
    # then the label makes the order identical across all three pipelines.
    try:
        sort_keys = ["selected_pval", "pval", _auto_label_col(out)]
    except ValueError:
        sort_keys = ["selected_pval", "pval"]
    return out.sort_values(sort_keys, kind="mergesort").reset_index(drop=True)


def row_zscore(matrix):
    """Row-wise z-scores with the sample standard deviation (ddof=1).

    The one definition every heatmap in the package uses, and the same one
    the web application and the R functions use: ddof=1, a row with no spread
    (or a non-finite SD) centred and left at zero rather than made undefined.
    """
    values = np.asarray(matrix, dtype=float)
    row_mean = np.nanmean(values, axis=1, keepdims=True)
    row_sd = np.nanstd(values, axis=1, ddof=1, keepdims=True)
    row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1.0
    return (values - row_mean) / row_sd


def anova_cluster_data(anova_df, meta, n_clusters=4, in_pval=0.05, z_score=True, only_significant=True, cluster_method="average", cluster_metric="euclidean", cluster_col="cluster"):
    from scipy.cluster.hierarchy import fcluster

    if n_clusters < 1:
        raise ValueError("n_clusters must be at least 1.")

    sample_cols = [col for col in meta["sample"].astype(str).tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    if only_significant and _significance_pval_column(anova_df):
        cluster_df = anova_df[anova_df[_significance_pval_column(anova_df)] < in_pval].copy()
    else:
        cluster_df = anova_df.copy()

    if cluster_df.empty:
        cluster_df.insert(1, cluster_col, pd.Series(index=cluster_df.index, dtype="int64"))
        return cluster_df.reset_index(drop=True)

    matrix = cluster_df[sample_cols].to_numpy(dtype=float)
    if matrix.shape[0] > 1:
        matrix, kept, dropped, total = _drop_incomplete_features(
            matrix, context="ANOVA clustering"
        )
        cluster_df = cluster_df.loc[kept]
        _warn_dropped_features(dropped, total)
    if z_score:
        matrix = row_zscore(matrix)

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




_TEST_TYPES = {
    "unpaired": (False, "pooled"),
    "unpaired_welch": (False, "welch"),
    "paired": (True, "pooled"),
}


def resolve_test_type(value):
    """Return (is_paired, variance_model) for a test_type string."""
    mode = str(value).strip().lower()
    if mode not in _TEST_TYPES:
        raise ValueError("test_type must be one of: " + ", ".join(sorted(_TEST_TYPES)) + ".")
    return _TEST_TYPES[mode]


def variance_model(value):
    return resolve_test_type(value)[1]




def median_center(values):
    """Shift each sample so all samples share a common median.

    Operates on log2 values, where a multiplicative loading difference is an
    additive offset. Samples are re-centred on the grand median rather than on
    zero so the result stays on a recognisable intensity scale; that choice is a
    constant shift and does not affect any fold change.
    """
    medians = values.median(axis=0, skipna=True)
    grand_median = float(np.nanmedian(medians.to_numpy(dtype=float)))
    return values.sub(medians, axis=1).add(grand_median)


def quantile_normalize(values):
    """Force every sample onto a common intensity distribution.

    Missing values are neither imputed nor allowed to shift a sample's ranks:
    each sample's observed values are mapped onto their own quantile positions,
    and the shared reference distribution is read off at those positions. This
    interpolates rather than dropping incomplete rows, so a feature missing in
    one sample still contributes everywhere it was measured.
    """
    numeric = values.apply(pd.to_numeric, errors="coerce")
    row_count = int(numeric.shape[0])
    if row_count == 0:
        return numeric

    # Grid spans the full row count so columns with different
    # numbers of observed values still land on a common reference curve.
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
        ranks = stats.rankdata(observed, method="average")
        positions = (ranks - 1.0) / (observed.size - 1.0) if observed.size > 1 else np.zeros(1)
        out.loc[mask, column] = np.interp(positions, grid, reference)
    return out


def _normalization_sample_columns(data, meta):
    """Resolve the columns to normalize from a metadata frame or a column list.

    Every other public function here takes a metadata frame as its second
    argument, so `normalize_data(data, meta, ...)` is the call people actually
    write. That used to resolve to no columns and return the input unchanged,
    which is indistinguishable from a successful normalization: the caller gets a
    frame back and every downstream figure is computed on unnormalized data.
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
            f"be normalized. Requested: {', '.join(requested[:6]) or '(nothing)'}. "
            "Pass the metadata frame or the list of sample column names."
        )
    if missing:
        raise ValueError(
            f"{len(missing)} requested sample column(s) are not in the data: "
            f"{', '.join(missing[:6])}. Normalizing only the rest would silently "
            "change the reference distribution."
        )
    return present


MISSINGNESS_GAP = 0.10
MISSINGNESS_MIN_COMPLETE = 20
_MISSINGNESS_METHOD_LABELS = {"median": "Median centering", "quantile": "Quantile normalization", "vsn": "VSN"}


def missingness_imbalance(data, meta, min_gap=MISSINGNESS_GAP, min_complete=MISSINGNESS_MIN_COMPLETE):
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


def missingness_imbalance_warning(table, method, min_gap=MISSINGNESS_GAP):
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


def normalize_data(data, meta, method="none", linear_source=None):
    """Apply a global normalization to the sample columns of a log2 matrix.

    Always global. Normalising within conditions would remove exactly the
    differences the downstream tests are looking for.

    VSN is delegated to Bioconductor rather than reimplemented: a Python port
    matched the reference on well-conditioned data but diverged by up to 2.2 log2
    units on wide-dynamic-range input, because vsn's profile likelihood is flat
    and multimodal. It is available in the R functions and the web app; from this
    package, use one of those.

    References: quantile normalization follows the method of Bolstad et al. 2003, doi:10.1093/bioinformatics/19.2.185;
    VSN is delegated to the Bioconductor vsn package
    (Huber et al. 2002, doi:10.1093/bioinformatics/18.suppl_1.S96).

    For phosphoprotein workflows, normalize phosphosites before
    transform_phosprot, never the collapsed phosphoprotein matrix: the collapse
    carries the site-level normalization forward, and a second pass would
    normalize the same values twice. The app applies none at that level.
    """
    resolved = str(method or "none").strip().lower()
    if resolved in {"", "none"}:
        return data
    present = _normalization_sample_columns(data, meta)

    numeric = data[present].apply(pd.to_numeric, errors="coerce")
    if resolved == "median":
        normalized = median_center(numeric)
    elif resolved == "quantile":
        normalized = quantile_normalize(numeric)
    elif resolved == "vsn":
        raise ValueError(
            "VSN is not available in the notebook package because it delegates to "
            "Bioconductor vsn. Use the R functions or the web app, or choose "
            "'median' or 'quantile'."
        )
    else:
        raise ValueError("method must be one of: none, median, quantile, vsn.")

    out = data.copy()
    out[present] = normalized
    message = missingness_imbalance_warning(missingness_imbalance(out, meta), resolved)
    if message:
        warnings.warn(message, UserWarning, stacklevel=2)
    return out


def sample_id_map(names):
    """Map extracted id -> name, refusing to guess when two names share an id.

    The id is only the *last* number in a name, so a run set following the common
    date_cellline_condition_replicate convention collapses every condition onto
    the same handful of ids: 20240110_HeLa_ctrl_01.raw and
    20240110_HeLa_treat_01.raw are both "01". Resolving that by first-wins drops
    one whole condition, and renaming data columns to the id produces duplicate
    column labels that later select silently as the wrong sample.
    """
    mapping = {}
    collisions = {}
    for name in names:
        text = str(name)
        sample_id = extract_sample_id(text)
        if sample_id in mapping and mapping[sample_id] != text:
            collisions.setdefault(sample_id, [mapping[sample_id]]).append(text)
            continue
        mapping[sample_id] = text
    if collisions:
        detail = "; ".join(
            "{} both reduce to '{}'".format(
                " and ".join(repr(item) for item in sorted(items)), key
            )
            for key, items in sorted(collisions.items())
        )
        raise ValueError(
            "Sample names cannot be matched by number because they are ambiguous: "
            + detail
            + ". Sample matching falls back to the last number in a name, so names "
            "that differ only before that number are indistinguishable. Either use "
            "sample names in the annotation that match the run names exactly, or "
            "rename the runs so the trailing number is unique."
        )
    return mapping

IMPUTED_COUNT_PREFIX = "n_imputed__"
IMPUTED_TOTAL_COLUMN = "imputed_values"


def imputed_cell_mask(values, observed=None):
    """Classify cells: -1 missing, 0 measured, 1 fully imputed, 2 partially imputed.

    `observed` is the matrix before imputation (same rows and sample columns).
    Returns None without it. Mirrors app.services.functions.imputed_cell_mask.
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

    Measured contributors (site_measured__, or site_observed__ in older tables)
    and site_supplied__ counts are required. Without them provenance is unknown,
    not evidence of no imputation. Coverage counts remain separate in new tables.
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

    Imputed values enter every test as if measured -- they count towards n and
    the degrees of freedom -- so these columns tell a call carried by
    measurements from one carried by the imputation.
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


def _imputed_counts_for(data, observed, groups):
    """Counts for `groups` of `data`, or None when imputation cannot be located.

    `observed` is the pre-imputation matrix the caller passed (e.g. the filtered
    data that was given to `impute_values`); without it a phosphoprotein table's
    own site-contribution columns are used when present.
    """
    samples = list(dict.fromkeys(c for cols in groups.values() for c in cols))
    if observed is not None:
        missing_rows = ~data.index.isin(observed.index)
        missing_cols = [c for c in samples if c not in observed.columns]
        if missing_rows.any() or missing_cols:
            raise ValueError(
                "observed must be the pre-imputation matrix of this data: same row index and "
                f"sample columns ({int(missing_rows.sum())} rows, {len(missing_cols)} sample columns not found)."
            )
        mask = imputed_cell_mask(data[samples], observed[samples])
    else:
        mask = site_observed_imputed_mask(data, samples)
    return None if mask is None else imputed_value_counts(mask, groups)



def constant_differences(differences):
    """`constant_within_group` for paired differences, ignoring float subtraction noise."""
    return constant_within_group(np.round(np.asarray(differences, dtype=float), 9))


def without_variation(groups):
    """Rows where every variance component is constant: the standard error is zero.

    The t statistic is then undefined, so such rows get no p-value
    (significance "Unavailable") instead of p = 0.
    """
    return np.logical_and.reduce([constant_within_group(group) for group in groups])


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
    names = list(condition_cols.keys())
    frames = []
    for first in range(len(names)):
        for second in range(first + 1, len(names)):
            left, right = names[first], names[second]
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
        meta_plot["plot_sample"] = _sample_meta(meta_plot, id=False)["new_sample"]

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_df.columns]
    if not sample_cols:
        raise ValueError("No sample columns from meta were found in anova_df.")

    column = _significance_pval_column(anova_df)
    plot_df = anova_df[anova_df[column] < in_pval].copy() if column else anova_df.copy()
    if plot_df.empty:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.set_axis_off()
        ax.set_title("ANOVA heatmap")
        ax.text(0.5, 0.5, "No rows passed the ANOVA threshold.", ha="center", va="center")
        return fig

    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    if (cluster_rows and raw_matrix.shape[0] > 1) or (cluster_samples and raw_matrix.shape[1] > 1):
        _, kept, dropped, total = _drop_incomplete_features(
            raw_matrix, context="ANOVA heatmap"
        )
        plot_df = plot_df.loc[kept]
        raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
        _warn_dropped_features(dropped, total)
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        matrix = row_zscore(matrix)
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
        # scipy draws leaf 0 at the bottom of a left-oriented dendrogram while
        # imshow draws row 0 at the top; flip the axis so branches meet their rows.
        ax_row_dendrogram.invert_yaxis()
    ax_row_dendrogram.set_axis_off()

    ax_strip.imshow(condition_strip, aspect="auto", interpolation="nearest")
    ax_strip.set_axis_off()

    plot_cmap = plt.get_cmap(cmap).with_extremes(bad="#d8d8d8")
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
        meta_plot["plot_sample"] = _sample_meta(meta_plot, id=False)["new_sample"]

    sample_cols = [col for col in meta_plot["sample"].tolist() if col in anova_cluster_df.columns]
    if not sample_cols:
        raise ValueError("anova_cluster_df must contain the original sample columns from anova_data_f().")

    plot_df = anova_cluster_df.copy()
    raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
    if cluster_samples and raw_matrix.shape[1] > 1:
        _, kept, dropped, total = _drop_incomplete_features(
            raw_matrix, context="ANOVA cluster heatmap"
        )
        plot_df = plot_df.loc[kept]
        raw_matrix = plot_df[sample_cols].to_numpy(dtype=float)
        _warn_dropped_features(dropped, total)
    missing_mask = ~np.isfinite(raw_matrix)
    matrix = raw_matrix.copy()
    labels = plot_df[label_col].astype(str).tolist()

    if z_score:
        matrix = row_zscore(matrix)
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

    plot_cmap = plt.get_cmap(cmap).with_extremes(bad="#d8d8d8")
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


def _is_phosphoprotein_workflow(workflow):
    workflow_key = "".join(character for character in str(workflow).lower() if character.isalnum())
    return workflow_key in {"phosprot", "phosphoprotein", "phosphoproteome"}


def _different_genes_column(data, workflow):
    prefer_group = _is_phosphoprotein_workflow(workflow)
    candidates = ["Gene_group", "GeneNames"] if prefer_group else ["GeneNames"]
    for column in candidates:
        if column in data.columns:
            return column, prefer_group
    raise ValueError("different_genes requires GeneNames or Gene_group.")


def _different_gene_tokens(values, split_groups):
    genes = set()
    for value in values:
        if value is None or pd.isna(value):
            continue
        if isinstance(value, (float, np.floating)) and not np.isfinite(value):
            continue
        text = str(value).strip()
        tokens = text.split(";") if split_groups else text.split(";", 1)[:1]
        genes.update(token.strip() for token in tokens if token.strip())
    return sorted(genes)


def _different_genes_from_volcano(volcano_data, key_col, split_groups):
    """Format the exact Volcano classifications for ORA input."""
    required = {key_col, "significance"}
    missing = required.difference(volcano_data.columns)
    if missing:
        raise ValueError(
            "Volcano output is missing required ORA columns: " + ", ".join(sorted(missing))
        )
    return {
        "Upregulated": _different_gene_tokens(
            volcano_data.loc[volcano_data["significance"] == "Upregulated", key_col],
            split_groups,
        ),
        "Downregulated": _different_gene_tokens(
            volcano_data.loc[volcano_data["significance"] == "Downregulated", key_col],
            split_groups,
        ),
        "Background": _different_gene_tokens(volcano_data[key_col], split_groups),
    }


def different_genes(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                    workflow="Gene", paired="Unpaired", uncorrected=False, test_type=None):
    """Select normal-Volcano gene clusters and tested background for ORA.

    The statistics and significance labels come directly from
    :func:`volcano_data_f`. Omitting ``test_type`` preserves the legacy
    ``paired`` argument; otherwise all five public Volcano modes are supported.
    """
    key_col, split_groups = _different_genes_column(data, workflow)
    volcano_data = volcano_data_f(
        data,
        meta,
        condition1,
        condition2,
        in_pval=in_pval,
        in_log2fc=in_log2fc,
        workflow=workflow,
        paired=paired,
        uncorrected=uncorrected,
        test_type=test_type,
        label_column=key_col,
    )
    return _different_genes_from_volcano(volcano_data, key_col, split_groups)


def different_genes_control(
    data,
    meta,
    condition1,
    condition2,
    condition1_control,
    condition2_control,
    in_pval=0.05,
    in_log2fc=1,
    workflow="Gene",
    paired="Unpaired",
    uncorrected=False,
    test_type=None,
):
    """Select corrected Control-Volcano clusters and background for ORA."""
    key_col, split_groups = _different_genes_column(data, workflow)
    volcano_data = volcano_data_f_control(
        data,
        meta,
        condition1,
        condition2,
        condition1_control,
        condition2_control,
        in_pval=in_pval,
        in_log2fc=in_log2fc,
        workflow=workflow,
        paired=paired,
        uncorrected=uncorrected,
        test_type=test_type,
        label_column=key_col,
    )
    return _different_genes_from_volcano(volcano_data, key_col, split_groups)


ENRICHMENT_COLUMNS = [
    "source",
    "term_id",
    "term_name",
    "term_size",
    "intersection_size",
    "query_size",
    "gene_ratio",
    "p_value",
    "adj_p_value",
]


def _empty_enrichment_frame():
    """An empty enrichment table with the documented columns."""
    return pd.DataFrame({column: pd.Series(dtype="object") for column in ENRICHMENT_COLUMNS})


def enrichment_data(
    gene_list,
    top_n=10,
    min_num=20,
    max_num=300,
    background=None,
    background_mode="experiment",
    adj_p_value_cutoff=0.05,
    workflow="Protein",
    organism="human",
):
    """The over-representation table behind `enrichment_analysis`.

    Split out so the numbers can be read, exported and compared across the three
    pipelines. `enrichment_analysis` draws exactly this frame, so the figure and
    the table cannot drift apart.

    Returns an empty frame rather than None when nothing passes, so callers can
    treat the result as a table unconditionally.
    """
    split_groups = _is_phosphoprotein_workflow(workflow)
    genes = _different_gene_tokens(gene_list, split_groups)
    if not genes:
        return _empty_enrichment_frame()
    if background_mode not in {"experiment", "global"}:
        raise ValueError("background_mode must be 'experiment' or 'global'.")
    if min_num > max_num:
        raise ValueError("min_num cannot be larger than max_num.")

    db = load_go_db(organism).copy()
    db["gene_list"] = db["genes"].fillna("").astype(str).apply(
        lambda value: sorted({gene.strip() for gene in value.split(";") if gene.strip()})
    )
    annotated = {gene for term_genes in db["gene_list"] for gene in term_genes}
    if background_mode == "experiment":
        if background is None:
            raise ValueError(
                "Provide the tested-gene background, or set background_mode='global'."
            )
        submitted_background = set(_different_gene_tokens(background, split_groups))
        missing = sorted(set(genes).difference(submitted_background))
        if missing:
            raise ValueError(
                "Every query gene must be included in the experiment background. "
                f"Missing: {', '.join(missing[:10])}."
            )
        effective_background = submitted_background.intersection(annotated)
    else:
        effective_background = annotated
    if not effective_background:
        return _empty_enrichment_frame()

    query = set(genes).intersection(effective_background)
    if not query:
        return _empty_enrichment_frame()
    population_size = len(effective_background)
    sample_size = len(query)
    rows = []
    overlaps = []
    term_sizes = []
    for _, row in db.iterrows():
        term_genes = effective_background.intersection(row["gene_list"])
        term_size = len(term_genes)
        if term_size < min_num or term_size > max_num:
            continue
        overlap = sorted(query.intersection(term_genes))
        # A term sharing no gene with the query has p = 1 by construction and is
        # never reported, so it is not a test. Counting it in the Benjamini-
        # Hochberg denominator inflated every reported adjusted p -- by 3.4x on a
        # 4000-gene background -- and made the packages disagree with the web
        # app, which corrects over tested terms only.
        if not overlap:
            continue
        overlaps.append(len(overlap))
        term_sizes.append(term_size)
        rows.append(
            {
                "source": str(row.get("ontology", "")),
                "term_id": str(row.get("term", "")),
                "term_name": str(row.get("description", "")),
                "term_size": term_size,
                "intersection_size": len(overlap),
                "query_size": sample_size,
                "gene_ratio": len(overlap) / sample_size,
            }
        )
    if not rows:
        return _empty_enrichment_frame()

    p_values = np.asarray(
        stats.hypergeom.sf(
            np.asarray(overlaps) - 1,
            population_size,
            np.asarray(term_sizes),
            sample_size,
        ),
        dtype=float,
    )
    adjusted = multipletests(np.asarray(p_values), method="fdr_bh")[1]
    res = pd.DataFrame(rows)
    res["p_value"] = p_values
    res["adj_p_value"] = adjusted
    # `intersection_size > 0` holds for every row now; only the cutoff remains.
    res = res[res["adj_p_value"] <= adj_p_value_cutoff].copy()
    if res.empty:
        return _empty_enrichment_frame()
    res = res.sort_values(["adj_p_value", "p_value"]).head(top_n)
    return res.reset_index(drop=True)


def enrichment_analysis(
    gene_list,
    top_n=10,
    min_num=20,
    max_num=300,
    background=None,
    background_mode="experiment",
    adj_p_value_cutoff=0.05,
    workflow="Protein",
    organism="human",
):
    """Dot plot of the table returned by `enrichment_data`."""
    res = enrichment_data(
        gene_list,
        top_n=top_n,
        min_num=min_num,
        max_num=max_num,
        background=background,
        background_mode=background_mode,
        adj_p_value_cutoff=adj_p_value_cutoff,
        workflow=workflow,
        organism=organism,
    )
    if res.empty:
        return None
    background_label = (
        "Background: tested genes" if background_mode == "experiment" else "Background: whole genome"
    )

    fig, ax = plt.subplots(figsize=(8, 6))
    # GeneRatio (overlap / query genes), as in clusterProfiler's dot plot.
    # BP, CC and MF terms share one plot and one BH correction, so each label
    # names its ontology, as in the web app.
    labels = [f"{name} ({source})" if str(source) else str(name)
              for name, source in zip(res['term_name'], res['source'].fillna(''))]
    scatter = ax.scatter(
        x=res['gene_ratio'],
        y=labels,
        s=res['intersection_size']*10,
        c=-np.log10(res['adj_p_value'].clip(lower=np.finfo(float).tiny)),
        cmap='RdBu_r'
    )

    ax.set_xlabel('GeneRatio (overlap / query genes)')
    ax.set_ylabel('GO Term')
    background_label = (
        "tested-gene background"
        if background_mode == "experiment"
        else "global annotated background"
    )
    ax.set_title(f"GO Enrichment (ORA)\n{background_label}")

    cbar = fig.colorbar(scatter, ax=ax, pad=0.15)
    cbar.set_label('-log10 adjusted p-value')

    plt.tight_layout()
    return fig


# Organism key -> bundled Gene Ontology table (built by
# tools/build_reference_databases.py; see data/db/README.md). Nothing falls
# back to human: a wrong organism gives real numbers for the wrong species.
GO_DATABASES = {
    "human": "all_go_terms_genes.csv",
    "mouse": "all_go_terms_genes_mouse.csv",
}


def load_go_db(organism="human"):
    """The GO term-to-gene table for `organism` ("human" or "mouse").

    `COPYLOT_GO_DB` overrides the human table only; `COPYLOT_GO_DB_MOUSE` the
    mouse one.
    """
    key = str(organism).strip().lower() or "human"
    if key not in GO_DATABASES:
        raise ValueError(
            f"No Gene Ontology database is bundled for '{organism}'. "
            f"Available: {', '.join(sorted(GO_DATABASES))}."
        )
    filename = GO_DATABASES[key]
    candidates = []
    configured = os.getenv("COPYLOT_GO_DB" if key == "human" else f"COPYLOT_GO_DB_{key.upper()}", "").strip()
    if configured:
        candidates.append(configured)
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(sys._MEIPASS, "data", "db", filename))
    candidates.extend([
        os.path.join(os.path.dirname(__file__), "data", filename),
        os.path.join(os.path.abspath("."), "data", "db", filename),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "db", filename),
    ])
    for db_file in candidates:
        if os.path.isfile(db_file):
            return pd.read_csv(db_file)
    raise FileNotFoundError(
        f"Could not find {filename}. Checked: " + ", ".join(candidates)
    )


def _aggregate_pathway_gene_values(data, gene_column, sample_columns, pathway_genes):
    value_frame = (
        data.reindex(columns=sample_columns)
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    gene_positions = {}
    for position, gene_value in enumerate(data[gene_column].tolist()):
        if gene_value is None or pd.isna(gene_value):
            tokens = set()
        else:
            tokens = {
                token.strip().casefold()
                for token in str(gene_value).split(";")
                if token.strip()
            }
        for token in tokens:
            gene_positions.setdefault(token, []).append(position)

    ordered_genes = []
    seen_genes = set()
    for gene_value in pathway_genes:
        gene = str(gene_value).strip()
        gene_key = gene.casefold()
        if not gene or gene_key in seen_genes:
            continue
        seen_genes.add(gene_key)
        ordered_genes.append(gene)

    rows = []
    counts = []
    for gene in ordered_genes:
        positions = gene_positions.get(gene.casefold(), [])
        counts.append(len(positions))
        if positions:
            rows.append(value_frame.iloc[positions].median(axis=0, skipna=True))
        else:
            rows.append(pd.Series(np.nan, index=sample_columns, dtype=float))

    heatmap_data = pd.DataFrame(rows, index=ordered_genes, columns=sample_columns)
    source_counts = pd.Series(
        counts,
        index=ordered_genes,
        dtype="int64",
        name="source_feature_count",
    )
    return heatmap_data, source_counts


def proteins_in_pathway(
        data, meta, db, pathway, conditions=None,
        figsize=(12, 8), cmap_name='plasma',
        remove_empty=True,
        cluster_rows=False,
        cluster_cols=False,
        value_type="z",
        header=True,
        id=True,
        show_source_count=False,
        gene_column=None
):
    if gene_column is None:
        candidates = [name for name in ("GeneNames", "Gene_group") if name in data.columns]
        if len(candidates) != 1:
            raise ValueError("Specify gene_column when gene labels are missing or ambiguous.")
        gene_column = candidates[0]
    if gene_column not in data.columns:
        raise ValueError("Selected gene_column is missing.")
    pathway_row = db[db['description'].str.lower() == pathway.lower()]
    if pathway_row.empty:
        raise ValueError(f"No pathway found exactly matching '{pathway}' in db")

    genes_str = pathway_row['genes'].values[0]
    genes = [g.strip() for g in genes_str.split(';') if g.strip()]

    data = data.copy()

    if conditions is not None:
        meta_filtered = meta[meta['condition'].isin(conditions)].copy()
    else:
        meta_filtered = meta.copy()

    meta_filtered = _sample_meta(meta_filtered, id=id, newline=True)

    rename_dict = dict(zip(meta_filtered['sample'], meta_filtered['new_sample']))
    sample_cols = list(meta_filtered['sample'])

    heatmap_data, source_feature_counts = _aggregate_pathway_gene_values(
        data,
        gene_column=gene_column,
        sample_columns=sample_cols,
        pathway_genes=genes,
    )

    if remove_empty:
        heatmap_data = heatmap_data.dropna(how="all")
        source_feature_counts = source_feature_counts.loc[heatmap_data.index]

    if heatmap_data.empty:
        raise ValueError("No matching gene data available for the selected pathway.")

    value_type = value_type.lower()

    if value_type == "z":
        heatmap_data = pd.DataFrame(row_zscore(heatmap_data), index=heatmap_data.index, columns=heatmap_data.columns)
        cbar_label = "Z-score"
    elif value_type == "log2":
        cbar_label = "log2 Intensity"
    else:
        raise ValueError("value_type must be 'z' or 'log2'")

    heatmap_data = heatmap_data.replace([np.inf, -np.inf], np.nan)
    if value_type == "z":
        heatmap_data = heatmap_data.dropna(how="all")
        source_feature_counts = source_feature_counts.loc[heatmap_data.index]
    if heatmap_data.empty:
        raise ValueError("No informative pathway rows remain after heatmap transformation.")

    if show_source_count:
        # How many dataset rows collapsed onto each gene. Off by default: on a
        # pathway of forty genes it is forty parentheticals down the side of the
        # figure, and most of them read 1.
        heatmap_data.index = [
            f"{gene} (n={int(source_feature_counts.loc[gene])})"
            for gene in heatmap_data.index
        ]

    heatmap_data = heatmap_data.rename(columns=rename_dict)
    ordered_labels = list(meta_filtered['new_sample'])
    heatmap_data = heatmap_data[ordered_labels]

    cluster_matrix = None
    if (cluster_rows and heatmap_data.shape[0] > 1) or (cluster_cols and heatmap_data.shape[1] > 1):
        cluster_matrix, kept, dropped, total = _drop_incomplete_features(
            heatmap_data, context="pathway heatmap"
        )
        heatmap_data = heatmap_data.loc[kept]
        _warn_dropped_features(dropped, total)
    if cluster_rows and heatmap_data.shape[0] > 1:
        row_linkage = linkage(cluster_matrix, method='average', metric='euclidean')
        row_order = leaves_list(row_linkage)
        heatmap_data = heatmap_data.iloc[row_order]
        cluster_matrix = cluster_matrix[row_order]

    if cluster_cols and heatmap_data.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method='average', metric='euclidean')
        col_order = leaves_list(col_linkage)
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=figsize)
    # A z-score is diverging: the default map becomes RdBu_r with symmetric
    # limits in z mode, as on the ANOVA heatmaps; an explicit cmap_name is kept.
    z_mode = value_type == "z"
    sns.heatmap(
        heatmap_data,
        cmap=plt.get_cmap("RdBu_r" if z_mode and cmap_name == "plasma" else cmap_name),
        **({"vmin": -2.5, "vmax": 2.5} if z_mode else {}),
        cbar_kws={'label': cbar_label},
        linewidths=0.5,
        linecolor='gray',
        mask=heatmap_data.isna(),
        ax=ax
    )

    if header:
        ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    else:
        ax.set_yticklabels([])

    ax.set_xticklabels(ax.get_xticklabels(), rotation=90)
    title_suffix = "Z-transformed" if value_type == "z" else "log2 Intensities"
    ax.set_title(f"{pathway} ({title_suffix}; median across mapped features)", fontsize=14)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Protein / Gene" if header else "")
    fig.tight_layout()

    return fig


def volcano_plot_sim(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                     workflow="Protein", mod_var=1, mod_n=0):
    """A what-if projection of the volcano, not a power calculation.

    The observed mean fold changes are held fixed and the pooled t-test is
    recomputed with the variance multiplied by `mod_var` and, when `mod_n` > 1,
    `mod_n` replicates per group. Nothing is drawn at random. The observed fold
    changes include noise, so the projection is optimistic for effects that look
    large, and it does not estimate the probability of detecting a true effect.
    """
    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()
    label_col = "ProteinNames" if workflow == "Protein" else "PTM_Collapse_key"
    cols_to_use = [label_col] + annotated_columns1 + annotated_columns2
    data_filtered = data[cols_to_use].copy()
    threshold = len(annotated_columns1) + len(annotated_columns2) - 2
    mask = data_filtered.iloc[:, 1:].isna().sum(axis=1) < threshold
    data_filtered = data_filtered.loc[mask]
    x_data = data_filtered[annotated_columns1].astype(float)
    y_data = data_filtered[annotated_columns2].astype(float)
    n1_real = x_data.notna().sum(axis=1)
    n2_real = y_data.notna().sum(axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not valid_mask.any():
        raise ValueError("No rows have enough replicate values for the selected simulation.")
    x_data = x_data[valid_mask]
    y_data = y_data[valid_mask]
    data_filtered = data_filtered.loc[valid_mask]
    mean1 = x_data.mean(axis=1)
    mean2 = y_data.mean(axis=1)
    var1 = x_data.var(axis=1, ddof=1)
    var2 = y_data.var(axis=1, ddof=1)
    n1 = n1_real[valid_mask] if mod_n in (0, 1) else mod_n
    n2 = n2_real[valid_mask] if mod_n in (0, 1) else mod_n
    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    pooled_var *= mod_var
    se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
    t_stat = _guarded_t_statistic(mean1 - mean2, se)
    df = n1 + n2 - 2
    pvals = 2 * t.sf(np.abs(t_stat), df)
    # Rows without variation in either group: no p-value at any projected n,
    # out of the BH family -- the volcano's rule, so the projection at the
    # observed n reproduces the volcano table.
    pvals = np.where(without_variation([x_data.to_numpy(dtype=float), y_data.to_numpy(dtype=float)]), np.nan, pvals)
    adj_pvals = _adjust_finite_pvalues(pvals)
    log2fc = mean1 - mean2
    significance = np.where((adj_pvals < in_pval) & (log2fc > in_log2fc), "Upregulated",
                            np.where((adj_pvals < in_pval) & (log2fc < -in_log2fc), "Downregulated",
                                     "Not significant"))
    volcano_data = pd.DataFrame({
        'Feature': data_filtered[label_col],
        'log2FC': log2fc,
        'pval': pvals,
        'adj_pval': adj_pvals,
        'selected_pval': adj_pvals,
        'significance': significance
    })
    volcano_data.loc[~np.isfinite(pvals), 'significance'] = 'Unavailable'
    volcano_data['neg_log10_selected_pval'] = -np.log10(volcano_data['selected_pval'].clip(lower=1e-300))
    color_mapping = {"Downregulated": "blue", "Not significant": "gray", "Upregulated": "red", "Unavailable": "gray"}
    fig = px.scatter(
        volcano_data,
        x='log2FC',
        y='neg_log10_selected_pval',
        color='significance',
        hover_data=['Feature'],
        color_discrete_map=color_mapping,
        title=f"{condition1} vs. {condition2}",
    )
    vline_height = max(-np.log10(in_pval), volcano_data['neg_log10_selected_pval'].max())
    fig.add_shape(type="line", x0=in_log2fc, x1=in_log2fc, y0=0, y1=vline_height,
                  line=dict(dash='dash', color='black'))
    fig.add_shape(type="line", x0=-in_log2fc, x1=-in_log2fc, y0=0, y1=vline_height,
                  line=dict(dash='dash', color='black'))
    fig.add_shape(type="line", x0=volcano_data['log2FC'].min(), x1=volcano_data['log2FC'].max(),
                  y0=-np.log10(in_pval), y1=-np.log10(in_pval),
                  line=dict(dash='dash', color='black'))
    fig.update_layout(
        xaxis_title=f"log2 fold change ({condition1} - {condition2})",
        yaxis_title="-log10 adj. p-value",
        hovermode='closest'
    )
    return fig


def convert_to_centered(seq: str) -> str:
    if not isinstance(seq, str):
        return seq
    match = re.search(r"\*", seq)
    if not match:
        return seq
    star_index = match.start()
    if star_index == 0:
        return seq
    mod_residue = seq[star_index - 1].upper()
    clean_seq = seq[:star_index - 1] + mod_residue + seq[star_index + 1:]
    mod_pos = star_index - 1
    left = clean_seq[:mod_pos]
    right = clean_seq[mod_pos + 1:]
    left_tail = left[-7:].rjust(7, "_")
    right_tail = right[:7].ljust(7, "_")
    return f"{left_tail}{mod_residue}{right_tail}"


# Kinase motif windows. The Kinase Library reads "_" as "beyond the protein
# terminus", so a window cut from the peptide alone presents real flanking
# residues as absent (and loses the -3 position of R-x-x-S/T motifs whenever
# trypsin cleaved after that R/K). With a FASTA the window is read from the
# protein at the site position named in PTM_Collapse_key; the peptide window is
# kept only as a fallback and `window_source` says which one each row uses.
# Mirrors phospho_tools.site_motif_window and the R helpers.

KSEA_WINDOW_FLANK = 7
_SITE_KEY_PATTERN = re.compile(
    r"^(?P<proteins>[^~]*)~(?P<gene>.*)_(?P<residue>[A-Za-z])(?P<position>\d+)_M\d+$"
)


def read_fasta(path):
    """Accession -> sequence from a FASTA file.

    UniProt headers (``>sp|P12345|NAME_HUMAN ...``) are keyed by accession;
    any other header by its first word. Use the organism's reference proteome
    that the search was run against.
    """
    sequences = {}
    header, chunks = None, []
    opener = gzip.open if str(path).endswith(".gz") else open  # the bundled proteomes are gzipped
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    sequences.setdefault(header, "".join(chunks))
                token = line[1:].split()[0] if line[1:].split() else ""
                header = token.split("|")[1] if token.count("|") >= 2 else token
                chunks = []
            else:
                chunks.append(line)
    if header is not None:
        sequences.setdefault(header, "".join(chunks))
    return sequences


def _resolve_fasta(fasta):
    if fasta is None:
        return None
    if isinstance(fasta, dict):
        return {str(key): str(value) for key, value in fasta.items()}
    return read_fasta(fasta)


def _parse_site_key(key):
    if not isinstance(key, str):
        return None
    match = _SITE_KEY_PATTERN.match(key.strip())
    if match is None:
        return None
    accessions = [part.strip() for part in match.group("proteins").split(";") if part.strip()]
    if not accessions:
        return None
    return accessions, match.group("gene"), match.group("residue").upper(), int(match.group("position"))


def _protein_window(sequence, position, flank=KSEA_WINDOW_FLANK):
    centre = position - 1
    start, end = centre - flank, centre + flank + 1
    core = sequence[max(start, 0):min(end, len(sequence))].upper()
    return "_" * max(0, -start) + core + "_" * max(0, end - len(sequence))


def _windows_agree(protein_window, peptide_window):
    if not isinstance(peptide_window, str) or len(peptide_window) != len(protein_window):
        return True
    return all(pep == "_" or pep == prot for pep, prot in zip(peptide_window, protein_window))


def site_motif_window(key, peptide_sequence, sequences=None):
    """Motif window and provenance for one site (see module note above)."""
    peptide_window = convert_to_centered(peptide_sequence)
    parsed = _parse_site_key(key)
    protein, gene, site = "", "", ""
    if parsed is not None:
        accessions, gene, residue, position = parsed
        protein, site = accessions[0], f"{residue}{position}"
        for accession in accessions if sequences else []:
            sequence = sequences.get(accession)
            if not sequence or not 1 <= position <= len(sequence):
                continue
            if sequence[position - 1].upper() != residue:
                continue
            window = _protein_window(sequence, position)
            if _windows_agree(window, peptide_window):
                return {"UPD_seq": window, "Protein": accession, "Gene": gene, "Site": site,
                        "window_source": "protein"}
    return {"UPD_seq": peptide_window, "Protein": protein, "Gene": gene, "Site": site,
            "window_source": "peptide"}


KSEA_EXPORT_COLUMNS = ("PTM_Collapse_key", "Protein", "Gene", "Site", "window_source")


def _ksea_prepare(data, meta):
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    if "UPD_seq" not in data.columns:
        raise ValueError("Phosphosite data must contain UPD_seq for Kinase Library.")
    working = data.copy()
    # A unique row label keeps the site key and peptide of every row, even when
    # two sites share a peptide window; the volcano keeps row order.
    working["PTM_Collapse_key"] = [str(index) for index in range(len(working))]
    return working


def _ksea_format_volcano(volcano_df, data, fasta):
    sequences = _resolve_fasta(fasta)
    if sequences is None:
        warnings.warn(
            "No FASTA given: Kinase Library motif windows are cut from the peptide sequence only, and flanks "
            "the peptide does not cover are padded with '_' (read as the protein end by the Kinase "
            "Library). Pass fasta= with the searched proteome to read windows from the protein.",
            UserWarning,
            stacklevel=3,
        )
    rows = volcano_df["PTM_Collapse_key"].astype(int).to_numpy()
    keys = (data["PTM_Collapse_key"].to_numpy()[rows] if "PTM_Collapse_key" in data.columns
            else np.array([None] * len(rows), dtype=object))
    peptides = data["UPD_seq"].to_numpy()[rows]
    windows = pd.DataFrame(
        [site_motif_window(key, peptide, sequences) for key, peptide in zip(keys, peptides)],
        index=volcano_df.index,
        columns=["UPD_seq", *KSEA_EXPORT_COLUMNS[1:]],
    )
    columns = ["log2FC", "pval", "adj_pval", "selected_pval", "significance"]
    if "n_pairs" in volcano_df.columns:
        columns.append("n_pairs")
    columns.append("neg_log10_selected_pval")
    result = volcano_df[columns].copy()
    result.insert(0, "UPD_seq", windows["UPD_seq"])
    result["PTM_Collapse_key"] = keys
    for column in KSEA_EXPORT_COLUMNS[1:]:
        result[column] = windows[column]
    for column in volcano_df.columns:
        if column.startswith((IMPUTED_COUNT_PREFIX, "n_measured__", "n_fully_imputed__", "n_partially_imputed__")) or column == IMPUTED_TOTAL_COLUMN:
            result[column] = volcano_df[column].to_numpy()
    return result.reset_index(drop=True)


def kinase_library_data_f(data, meta, condition1, condition2,
                in_pval=0.05, in_log2fc=1,
                paired="Unpaired", uncorrected=False, test_type=None, fasta=None, observed=None,
                localization_cutoff=0.0):
    """Prepare standard Volcano results for the Kinase Library, matching the web pipeline.

    ``fasta`` is a FASTA path (or an accession -> sequence dict) of the searched
    proteome; motif windows are then read from the protein sequence. ``observed``
    adds imputed-value counts as in volcano_data_f.
    """
    data = filter_localization(data, localization_cutoff)
    working = _ksea_prepare(data, meta)
    volcano_df = volcano_data_f(
        working, meta, condition1, condition2,
        in_pval=in_pval, in_log2fc=in_log2fc, workflow="Phosphosite",
        paired=paired, uncorrected=uncorrected, test_type=test_type, observed=observed,
    )
    return _ksea_format_volcano(volcano_df, data, fasta)


def kinase_library_data_f_control(data, meta, condition1, condition2,
                                  condition1_control, condition2_control,
                                  in_pval=0.05, in_log2fc=1,
                                  paired="Unpaired", uncorrected=False, test_type=None, fasta=None,
                                  observed=None, localization_cutoff=0.0):
    """Prepare corrected Control Volcano results for the Kinase Library (see ksea_data_f)."""
    data = filter_localization(data, localization_cutoff)
    working = _ksea_prepare(data, meta)
    volcano_df = volcano_data_f_control(
        working, meta, condition1, condition2,
        condition1_control, condition2_control,
        in_pval=in_pval, in_log2fc=in_log2fc, workflow="Phosphosite",
        paired=paired, uncorrected=uncorrected, test_type=test_type, observed=observed,
    )
    return _ksea_format_volcano(volcano_df, data, fasta)


def phosprot_regulation_data(data: pd.DataFrame, meta: pd.DataFrame,
                        condition1: str, condition2: str,
                        in_pval: float = 0.05, in_log2fc: float = 1,
                        paired: str = "Unpaired", uncorrected: bool = False,
                        max_hover_sites: int = 20,
                        show_phosphosites: bool = True,
                        test_type=None, localization_cutoff: float = 0.0):
    """The per-protein table behind `phosprot_regulation`.

    Split out so the numbers can be read, exported and compared across the
    three pipelines; `phosprot_regulation` plots exactly this frame, so the
    figure and the table cannot drift apart. `x` is the cumulative log2FC of
    significant up-sites, `y` the absolute cumulative log2FC of significant
    down-sites, and proteins with no significant site are absent.
    """
    _validate_meta_samples(meta)
    _validate_sample_values(data, meta)
    """Collapse significant phosphosite Volcano results by phosphoprotein."""
    data = filter_localization(data, localization_cutoff)
    label_col = "PTM_Collapse_key"
    required = {label_col, "Protein_group"}
    missing = sorted(required.difference(data.columns))
    if missing:
        raise ValueError("Phosphosite data is missing required columns: " + ", ".join(missing))

    # A unique temporary label prevents duplicate site names from creating a
    # many-to-many merge after the shared Volcano calculation.
    row_keys = pd.Series(np.arange(len(data)), index=data.index).astype(str)
    mapping = pd.DataFrame({
        "__copylot_row_key": row_keys.to_numpy(),
        "Protein_group": data["Protein_group"].to_numpy(),
        "__copylot_site": data[label_col].to_numpy(),
    })
    working = data.copy()
    working[label_col] = row_keys
    volcano_df = volcano_data_f(
        working, meta, condition1, condition2,
        in_pval=in_pval, in_log2fc=in_log2fc, workflow="Phosphosite",
        paired=paired, uncorrected=uncorrected, test_type=test_type,
    ).rename(columns={label_col: "__copylot_row_key"})
    volcano_df = volcano_df.merge(mapping, on="__copylot_row_key", validate="one_to_one")
    volcano_df = volcano_df.rename(columns={"__copylot_site": label_col})

    collapsed_results = []

    for prot, group in volcano_df.groupby("Protein_group"):
        down = group.loc[group["significance"] == "Downregulated"]
        up = group.loc[group["significance"] == "Upregulated"]
        if down.empty and up.empty:
            continue

        down_sites = down[label_col].astype(str).tolist()
        up_sites = up[label_col].astype(str).tolist()
        down_effects = [
            f"{site} ({effect:.4g})"
            for site, effect in zip(down_sites, down["log2FC"].astype(float), strict=True)
        ]
        up_effects = [
            f"{site} ({effect:+.4g})"
            for site, effect in zip(up_sites, up["log2FC"].astype(float), strict=True)
        ]
        down_sum = float(-down["log2FC"].astype(float).sum())
        up_sum = float(up["log2FC"].astype(float).sum())

        def truncate_items(items):
            if len(items) > max_hover_sites:
                return ";".join(items[:max_hover_sites]) + f";... (+{len(items) - max_hover_sites} more)"
            return ";".join(items)

        collapsed_results.append({
            "Protein_group": prot,
            "Downregulated_sites": truncate_items(down_sites) if show_phosphosites else "",
            "Upregulated_sites": truncate_items(up_sites) if show_phosphosites else "",
            "Downregulated_site_effects": truncate_items(down_effects) if show_phosphosites else "",
            "Upregulated_site_effects": truncate_items(up_effects) if show_phosphosites else "",
            "Downregulated_count": len(down_sites),
            "Upregulated_count": len(up_sites),
            "Downregulated_log2FC_sum": down_sum,
            "Upregulated_log2FC_sum": up_sum
        })

    collapsed_df = pd.DataFrame(
        collapsed_results,
        columns=[
            "Protein_group",
            "Downregulated_sites",
            "Upregulated_sites",
            "Downregulated_site_effects",
            "Upregulated_site_effects",
            "Downregulated_count",
            "Upregulated_count",
            "Downregulated_log2FC_sum",
            "Upregulated_log2FC_sum",
        ],
    )
    collapsed_df["x"] = collapsed_df["Upregulated_log2FC_sum"]
    collapsed_df["y"] = collapsed_df["Downregulated_log2FC_sum"]
    collapsed_df["color_val"] = collapsed_df["x"] - collapsed_df["y"]
    return collapsed_df


def phosprot_regulation(data: pd.DataFrame, meta: pd.DataFrame,
                        condition1: str, condition2: str,
                        in_pval: float = 0.05, in_log2fc: float = 1,
                        paired: str = "Unpaired", uncorrected: bool = False,
                        max_hover_sites: int = 20,
                        show_phosphosites: bool = True,
                        test_type=None, localization_cutoff: float = 0.0):
    """Scatter of the table returned by `phosprot_regulation_data`."""
    collapsed_df = phosprot_regulation_data(
        data, meta, condition1, condition2,
        in_pval=in_pval, in_log2fc=in_log2fc, paired=paired,
        uncorrected=uncorrected, max_hover_sites=max_hover_sites,
        show_phosphosites=show_phosphosites, test_type=test_type,
        localization_cutoff=localization_cutoff,
    )

    fig = px.scatter(
        collapsed_df,
        x="x",
        y="y",
        hover_data={
            "Protein_group": True,
            "Upregulated_count": True,
            "Downregulated_count": True,
            "Upregulated_site_effects": True,
            "Downregulated_site_effects": True
        },
        color="color_val",
        color_continuous_scale=[(0, "blue"), (0.5, "grey"), (1, "red")],
        labels={
            "x": "Cumulative Significant Up-Site log2FC",
            "y": "Cumulative Significant Down-Site |log2FC|"
        },
        opacity=0.7
    )

    fig.update_traces(marker=dict(size=8, line=dict(width=0.5, color='DarkSlateGrey')), text=None)
    if collapsed_df.empty:
        fig.add_annotation(
            text="No phosphosites pass the selected significance and fold-change thresholds",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
        )

    fig.update_layout(title="Cumulative Significant Phosphosite Regulation by Protein",
                      xaxis_title="Cumulative Significant Up-Site log2FC",
                      yaxis_title="Cumulative Significant Down-Site |log2FC|",
                      template="plotly_white",
                      coloraxis_colorbar=dict(title="Up score - Down score"))

    return fig


#PEPTIDE

def rt_vs_pred_rt_plot(data_path, method="Hexbin Plot", add_line=False, bins=1000, header=True, width=8, height=6, dpi=100, seed=69):
    data = read_data(data_path)

    x = data['Predicted.RT']

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    if method == "Scatter Plot":
        if len(data) > 100000:
            data = data.sample(n=100000, random_state=int(seed))
        ax.scatter(data['Predicted.RT'], data['RT'], alpha=0.2, s=1)
    elif method == "Density Plot":
        from matplotlib.colors import LogNorm
        hb = ax.hist2d(data['Predicted.RT'], data['RT'], bins=200, norm=LogNorm())
        plt.colorbar(hb[3], ax=ax)
    elif method == "Hexbin Plot":
        hb = ax.hexbin(data['Predicted.RT'], data['RT'], gridsize=bins, cmap='Blues')
        plt.colorbar(hb, ax=ax)

    if add_line:
        ax.plot([x.min(), x.max()], [x.min(), x.max()], ls='--', color='red')

    ax.set_xlabel("Predicted RT")
    ax.set_ylabel("Actual RT")
    if header:
        ax.set_title("Retention Time Plot")

    return fig


def modification_plot(data2_path, meta, id=True, header=True, legend=True, width=10, height=6, dpi=100):
    if isinstance(data2_path, pd.DataFrame):
        data2 = data2_path.copy()
    else:
        data2 = sanitize_dataframe(read_data(data2_path)).copy()

    meta = meta.copy()
    data2_names = data2['File.Name'].unique()
    for name in data2_names:
        meta['sample'] = np.where(meta['sample'] == name, name, meta['sample'])

    data2_wide = (
        data2.pivot_table(
            index="File.Name",
            columns="Modified.Sequence",
            values="Precursor.Quantity",
            aggfunc="max"
        )
        .T.reset_index()
        .rename(columns={"index": "Modified.Sequence"})
    )

    data2_wide.columns = [extract_id_or_number(c) if c != "Modified.Sequence" else c for c in data2_wide.columns]

    meta["condition"] = meta["condition"].astype(str)
    meta = _sample_meta(meta, id=id, newline=True)

    rename_dict = dict(zip(meta["id"], meta["new_sample"]))
    data2_wide = data2_wide.rename(columns=rename_dict)
    ordered_new_samples = list(meta["new_sample"])
    annotated_cols = [c for c in ordered_new_samples if c in data2_wide.columns]
    data_filtered = data2_wide[["Modified.Sequence"] + annotated_cols].copy()

    def get_mod_count(df, pattern):
        df_mod = df[df["Modified.Sequence"].str.contains(pattern, case=False, na=False)].copy()
        quantities = (
            df_mod.iloc[:, 1:]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf, 0], np.nan)
        )
        return quantities.notna().sum(axis=0)

    # UniMod ids must not match longer ids by prefix: "UniMod:4" would otherwise
    # also count UniMod:40-49 and UniMod:4xx.
    col_carb = get_mod_count(
        data_filtered,
        r"UniMod:4(?!\d)|(?<![A-Za-z])Carbamidomethyl(?:ation)?(?![A-Za-z])",
    )
    col_oxi = get_mod_count(
        data_filtered,
        r"UniMod:35(?!\d)|(?<![A-Za-z])Oxidation(?![A-Za-z])",
    )
    col_ace = get_mod_count(
        data_filtered,
        r"UniMod:1(?!\d)|(?<![A-Za-z])Acetyl(?:ation)?(?![A-Za-z])",
    )

    plot_data = pd.DataFrame({
        "Sample": list(col_carb.index) * 3,
        "Count": list(col_carb.values) + list(col_oxi.values) + list(col_ace.values),
        "Modification": (["Carbamidomethylation"] * len(col_carb)) +
                        (["Oxidation"] * len(col_oxi)) +
                        (["Acetylation"] * len(col_ace))
    })

    plot_data = plot_data[plot_data["Count"] > 0]
    plot_data["Sample"] = pd.Categorical(plot_data["Sample"], categories=ordered_new_samples, ordered=True)
    plot_data = plot_data.sort_values("Sample")

    mod_colors = {
        "Carbamidomethylation": "blue",
        "Oxidation": "red",
        "Acetylation": "green"
    }

    found_mods = [m for m in ["Carbamidomethylation", "Oxidation", "Acetylation"] if m in plot_data["Modification"].unique()]

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    x = np.arange(len(ordered_new_samples))
    bar_w = 0.25
    offs = np.linspace(-bar_w, bar_w, len(found_mods))

    for mod, off in zip(found_mods, offs):
        sub = plot_data[plot_data["Modification"] == mod]
        idx = [ordered_new_samples.index(s) for s in sub["Sample"]]
        ax.bar(np.array(idx) + off, sub["Count"], width=bar_w, label=mod, color=mod_colors.get(mod, None))

    ax.set_xticks(x)
    ax.set_xticklabels(ordered_new_samples, rotation=90)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Number of modified peptides")
    if header:
        ax.set_title("Modifications per sample")

    if legend and len(found_mods) > 0:
        ax.legend(title="Modification", bbox_to_anchor=(1.05,1), loc="upper left")

    plt.tight_layout()
    return fig


def missed_cleavage_plot(data2_path, meta, id=True, text=True, text_size=8, header=True,
                         protease="trypsin", width=10, height=6, dpi=100):
    """Missed cleavages per sample.

    ``protease`` selects the cleavage rule and must match the digest actually
    used: 'trypsin' (K-P and R-P both uncleaved) or 'trypsin_lysc' (the Lys-C
    component cleaves K-P; R-P stays blocked).
    """

    data2 = sanitize_dataframe(read_data(data2_path)).copy()
    meta = meta.copy()

    file_col = [c for c in data2.columns if 'file' in c.lower()][0]
    seq_col = [c for c in data2.columns if 'stripped' in c.lower() and 'sequence' in c.lower()][0]

    df_wide = data2.pivot_table(
        index=file_col,
        columns=seq_col,
        values="Precursor.Quantity",
        aggfunc="max"
    ).T.reset_index()

    df_wide.rename(columns={"index": seq_col}, inplace=True)
    sample_map = _peptide_sample_map(df_wide.columns.drop(seq_col), meta['sample'])
    meta = _sample_meta(meta, id=id, newline=True)
    labels = dict(zip(meta["sample"], meta["new_sample"]))
    rename_dict = {run: labels[sample] for run, sample in sample_map.items()}
    df_wide = df_wide.rename(columns=rename_dict)

    annotated_cols = [c for c in meta["new_sample"] if c in df_wide.columns]
    data_filtered = df_wide[[seq_col] + annotated_cols].copy()

    resolved_protease = normalize_protease(protease)
    rk_counts = [count_missed_cleavages(seq, resolved_protease) for seq in data_filtered[seq_col]]
    for col in data_filtered.columns[1:]:
        data_filtered[col] = np.where(data_filtered[col].notna(), rk_counts, np.nan)

    plot_data = data_filtered.melt(id_vars=seq_col, var_name="Sample", value_name="Count").dropna()
    plot_data["Count"] = plot_data["Count"].astype(int)

    summary = (
        plot_data.groupby(["Sample", "Count"])
        .size()
        .reset_index(name="Occurrences")
    )
    summary["Total"] = summary.groupby("Sample")["Occurrences"].transform("sum")
    summary["Percentage"] = summary["Occurrences"] / summary["Total"] * 100

    samples_order = meta["new_sample"].tolist()
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=samples_order, ordered=True)

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    counts_sorted = sorted(summary["Count"].unique())
    bottom = np.zeros(len(samples_order))

    for c in counts_sorted:
        subset = summary[summary["Count"] == c].set_index("Sample").reindex(samples_order)["Percentage"].fillna(0)
        ax.bar(range(len(samples_order)), subset, bottom=bottom, label=str(c))
        bottom += subset

    ax.set_ylabel("Peptides by missed cleavages (%)")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())

    if header:
        ax.set_title(f"Missed cleavages per sample ({PROTEASE_LABELS[resolved_protease]})")

    ax.set_xticks(range(len(samples_order)))
    ax.set_xticklabels(samples_order, rotation=90)

    if text:
        with_missed = (
            summary[summary["Count"] > 0]
            .groupby("Sample", observed=False)["Percentage"].sum()
            .reindex(samples_order).fillna(0)
        )
        base_y = bottom.max() * 0.03
        for i, val in enumerate(with_missed):
            ax.text(i, base_y, f"{val:.1f}%", ha="center", va="bottom", fontsize=text_size)

    ax.legend(title="Number", bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    return fig


def _peptide_starts(sequence, peptide):
    if not peptide:
        return
    start = sequence.find(peptide)
    while start != -1:
        yield start
        start = sequence.find(peptide, start + 1)


def _protein_peptides(data, protein):
    """Peptides of the protein with at least one quantity above 0, as in the web app."""
    members = data["ProteinNames"].fillna("").astype(str).str.split(";")
    selected = members.map(lambda names: protein in [name.strip() for name in names])
    if "Precursor.Quantity" in data.columns:
        quantity = pd.to_numeric(data["Precursor.Quantity"], errors="coerce")
        selected &= np.isfinite(quantity) & (quantity > 0)
    return data.loc[selected, "Stripped.Sequence"].dropna().astype(str).unique().tolist()


def calculate_coverage(data_path, db, protein):
    data = read_data(data_path).copy()

    peptides = _protein_peptides(data, protein)

    try:
        sequence_row = db.loc[db["name"] == protein, "V1"]
        if sequence_row.empty:
            raise KeyError
        sequence = sequence_row.values[0]
    except KeyError:
        raise ValueError(f"No sequence found in the selected database for protein: {protein}")

    coverage_mask = [0] * len(sequence)
    for pep in peptides:
        for start in _peptide_starts(sequence, pep):
            end = start + len(pep)
            for i in range(start, end):
                coverage_mask[i] = 1

    return round((sum(coverage_mask) / len(sequence)) * 100, 2)


def vis_coverage(data: pd.DataFrame, db: pd.DataFrame, protein: str, chunk_size: int = 30) -> str:
    found_seq = _protein_peptides(data, protein)

    try:
        sequence_row = db.loc[db['name'] == protein, 'V1']
        if sequence_row.empty:
            raise KeyError
        sequence = sequence_row.values[0]
    except KeyError:
        return f"No sequence found in the selected database for protein: {protein}"

    n = len(sequence)
    result_seqs = ["-" * n]

    for pep in found_seq:
        for start_pos in _peptide_starts(sequence, pep):
            end_pos = start_pos + len(pep)
            placed = False
            for i, seq in enumerate(result_seqs):
                if seq[start_pos:end_pos] == "-" * len(pep):
                    result_seqs[i] = seq[:start_pos] + pep + seq[end_pos:]
                    placed = True
                    break
            if not placed:
                new_seq = "-" * n
                new_seq = new_seq[:start_pos] + pep + new_seq[end_pos:]
                result_seqs.append(new_seq)

    num_seq = ""
    count = 10
    for i in range(1, n + 1):
        if i % count == 0:
            num_seq += " " * (10 - len(str(count))) + str(count)
            count += 10

    starts = range(0, n, 10)
    chunks = [sequence[s:s + 10] for s in starts]
    num_chunks = [num_seq[s:s + 10] for s in starts]

    result_chunks_list = []
    for res_seq in result_seqs:
        result_chunks = [res_seq[s:s + 10] for s in starts]
        result_chunks_list.append(" ".join(result_chunks))

    sequence_str = " ".join(chunks)
    num_seq_str = " ".join(num_chunks)

    chunk_size = int(chunk_size * 1.1)
    n2 = len(sequence_str)
    starts = range(0, n2, chunk_size)

    lines = [sequence_str[s:s + chunk_size] for s in starts]
    num_lines = [num_seq_str[s:s + chunk_size] for s in starts]

    result_lines_list = []
    for res_chunk in result_chunks_list:
        result_lines = [res_chunk[s:s + chunk_size] for s in starts]
        result_lines_list.append(result_lines)

    output_lines = []
    for i in range(len(lines)):
        output_lines.append(num_lines[i])
        for res in reversed(result_lines_list):
            output_lines.append(res[i])
        output_lines.append(lines[i])
        output_lines.append("")

    return "\n".join(output_lines)


def fasta_to_dataframe(fasta_path):
    if SeqIO is None:
        raise ModuleNotFoundError(
            "fasta_to_dataframe requires biopython. "
            "Install ProteomicsCoPYlot with: pip install 'proteomicscopylot[bio]'"
        )

    if str(fasta_path).endswith(".gz"):
        with gzip.open(fasta_path, "rt", encoding="utf-8", errors="ignore") as handle:
            records = list(SeqIO.parse(handle, "fasta"))
    else:
        records = list(SeqIO.parse(fasta_path, "fasta"))
    data = {"full_header": [rec.id for rec in records], "V1": [str(rec.seq) for rec in records]}
    df = pd.DataFrame(data)
    df["name"] = df["full_header"].apply(lambda x: x.split("|")[-1])
    df["accession"] = df["full_header"].apply(lambda x: x.split("|")[1] if "|" in x else x)
    return df


#SINGLE PROTEIN
def compare_prot_line(data, meta, conditions, inputs, id=True, header=True, legend=True,
                      workflow="Protein", plot_colors=None, width=10, height=6, dpi=100):
    meta = meta.copy()
    data = data.copy()
    meta = _sample_meta(meta, id=id, newline=True)

    relevant_samples = meta["new_sample"].tolist()
    rename_vector = dict(zip(meta["sample"], meta["new_sample"]))
    data.rename(columns=rename_vector, inplace=True)

    if workflow == "Protein":
        key_col = "ProteinNames"
        data_filtered = data[data[key_col].isin(inputs)][[key_col] + relevant_samples]
        data_melted = data_filtered.melt(id_vars=key_col, var_name="Sample", value_name="Value")
    elif workflow == "Phosphosite":
        key_col = "PTM_Collapse_key"
        data_filtered = data[data[key_col].isin(inputs)][[key_col] + relevant_samples]
        data_melted = data_filtered.melt(id_vars=key_col, var_name="Sample", value_name="Value")
    elif workflow == "Phosphoprotein":
        key_col = "Phosphoprotein"
        data_filtered = data[data[key_col].isin(inputs)][[key_col] + relevant_samples]
        data_melted = data_filtered.melt(id_vars=key_col, var_name="Sample", value_name="Value")
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    ordered_samples = []
    for cond in conditions:
        ordered_samples.extend(meta.loc[meta["condition"] == cond, "new_sample"].tolist())

    data_melted["Value"] = pd.to_numeric(data_melted["Value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    data_melted = (
        data_melted.groupby([key_col, "Sample"], as_index=False, sort=False)["Value"]
        .median()
    )
    data_melted = data_melted.merge(
        meta[["new_sample", "condition"]],
        left_on="Sample",
        right_on="new_sample",
        how="left",
    ).dropna(subset=["Value", "condition"])

    sample_to_x = {s: i for i, s in enumerate(ordered_samples)}
    data_melted["x"] = data_melted["Sample"].map(sample_to_x)
    data_melted = data_melted[data_melted["x"].notna()].copy()

    if plot_colors is None:
        plot_colors = plt.cm.tab10.colors

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    for i, item in enumerate(data_melted[key_col].unique()):
        item_data = data_melted[data_melted[key_col] == item].sort_values("x")
        ax.plot(item_data["x"], item_data["Value"], marker="o", label=item,
                color=plot_colors[i % len(plot_colors)])

    ax.set_xticks(range(len(ordered_samples)))
    ax.set_xticklabels(ordered_samples, rotation=90)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Log2 intensity")

    if header:
        ax.set_title(f"{workflow} Expression Across Samples")

    if legend:
        ax.legend(title=workflow, bbox_to_anchor=(1.05, 1), loc='upper left')

    ax.grid(True)
    plt.tight_layout()
    fig.subplots_adjust(right=0.75)

    return fig


def single_protein_values(data, meta, protein):
    """The values `boxplot_int_single_prot` draws for one protein, as a table.

    The protein is looked up in the index, or else in the first column. When
    several rows match, each sample gets the median of its measured values.
    Returns `condition`, `sample` and `value`, in metadata order; samples
    without a value are left out.
    """
    rows = data[data.index == protein]
    if rows.empty and data.shape[1]:
        rows = data[data.iloc[:, 0].astype(str) == str(protein)]
    if rows.empty:
        raise ValueError(f"No data found for protein: {protein}")
    out = []
    for condition, sample in zip(meta["condition"], meta["sample"].astype(str)):
        if sample not in rows.columns:
            continue
        observed = pd.to_numeric(rows[sample], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(observed):
            out.append((condition, sample, float(observed.median())))
    table = pd.DataFrame(out, columns=["condition", "sample", "value"])
    table.attrs["source_rows"] = int(len(rows))
    return table


def boxplot_int_single_prot(data, meta, protein, outliers=False, dots=False, header=True, legend=True,
                       plot_colors=None, width=8, height=6, dpi=100, seed=69):
    values = single_protein_values(data, meta, protein)
    meta = _sample_meta(meta.copy(), id=False)

    if plot_colors is None:
        plot_colors = plt.cm.tab10.colors

    intensities = []
    labels = []
    colors = []
    plotted_conditions = []
    condition_colors = {cond: plot_colors[i % len(plot_colors)] for i, cond in enumerate(meta['condition'].unique())}

    for condition in meta["condition"].unique():
        vals = values.loc[values["condition"] == condition, "value"].to_numpy(dtype=float)
        if len(vals) == 0:
            continue
        intensities.append(vals)
        labels.append(condition)
        colors.append(condition_colors[condition])
        plotted_conditions.append(condition)

    if not intensities:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.text(0.5, 0.5, "No measured values in the selected conditions", ha="center", va="center")
        ax.axis("off")
        return fig

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    box_positions = [i for i, values in enumerate(intensities, start=1) if len(values) >= 3]
    if box_positions:
        bplots = ax.boxplot(
            [intensities[i - 1] for i in box_positions],
            positions=box_positions,
            patch_artist=True,
            showfliers=outliers,
        )
        for patch, position in zip(bplots['boxes'], box_positions):
            patch.set_facecolor(colors[position - 1])

    rng = np.random.default_rng(seed)
    for i, (vals, cond) in enumerate(zip(intensities, plotted_conditions), start=1):
        if len(vals) < 3:
            visible_values = vals
        elif dots:
            q1, q3 = np.percentile(vals, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            visible_values = vals[(vals >= lower) & (vals <= upper)]
        else:
            continue
        x_jitter = rng.normal(i, 0.05, size=len(visible_values))
        ax.scatter(x_jitter, visible_values, color=condition_colors[cond], alpha=0.8, s=20, zorder=3)

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(
        [f"{label}\n(n={len(values)})" for label, values in zip(labels, intensities)],
        rotation=45,
        ha='right',
    )
    ax.set_xlabel("Condition")
    ax.set_ylabel("log2 Intensity")
    if header:
        display_protein = protein
        suffix = f"\none median per sample across {values.attrs['source_rows']} matching source row(s)" if values.attrs['source_rows'] > 1 else ""
        ax.set_title(f"Measured {display_protein} intensity values (log2){suffix}")
    if legend:
        handles = [plt.Line2D([0], [0], color=condition_colors[c], lw=4) for c in plotted_conditions]
        ax.legend(handles, plotted_conditions, bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    return fig


def phossite_on_prot_regulation(
        data, meta, protein, conditions=None,
        id=True, figsize=(12, 8), cmap_name='plasma',
        filter_M2=False, cluster_rows=False,
        cluster_cols=False, value_type="log2",
        header=True, localization_cutoff=0.0
):
    data = filter_localization(data, localization_cutoff)
    protein_data = data[data['Protein_group'].str.contains(protein, case=False, na=False)]
    if protein_data.empty:
        raise ValueError(f"No data found for protein '{protein}'")

    if conditions is not None:
        meta_filtered = meta[meta['condition'].isin(conditions)].copy()
    else:
        meta_filtered = meta.copy()

    meta_filtered = _sample_meta(meta_filtered, id=id, newline=True)

    sample_cols = [s for s in meta_filtered['sample'] if s in protein_data.columns]
    rename_dict = dict(zip(meta_filtered['sample'], meta_filtered['new_sample']))

    protein_data = protein_data.copy()

    if filter_M2:
        protein_data = protein_data[protein_data['PTM_Collapse_key'].str.endswith('_M1')]

    heatmap_data = protein_data.set_index('PTM_Collapse_key')[sample_cols].rename(columns=rename_dict)

    def extract_site(ptm_key):
        key = str(ptm_key)
        if '~' in key:
            key = key.split('~')[1]
        if filter_M2 and key.endswith('_M1'):
            return key.rsplit('_', 1)[0]
        return key

    heatmap_data.index = heatmap_data.index.map(extract_site)

    value_type = value_type.lower()
    if value_type == "z":
        heatmap_data = pd.DataFrame(row_zscore(heatmap_data), index=heatmap_data.index, columns=heatmap_data.columns)
        cbar_label = "Z-score"
    elif value_type == "log2":
        cbar_label = "log2 Intensity"
    else:
        raise ValueError("value_type must be 'log2' or 'z'")

    heatmap_data = heatmap_data.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    heatmap_data = heatmap_data.dropna(how="all")
    if heatmap_data.empty:
        raise ValueError("No informative phosphosite rows remain after heatmap transformation.")

    cluster_matrix = None
    if (cluster_rows and heatmap_data.shape[0] > 1) or (cluster_cols and heatmap_data.shape[1] > 1):
        cluster_matrix, kept, dropped, total = _drop_incomplete_features(
            heatmap_data, context="phosphosite heatmap"
        )
        heatmap_data = heatmap_data.loc[kept]
        _warn_dropped_features(dropped, total)
    if cluster_rows and heatmap_data.shape[0] > 1:
        row_linkage = linkage(cluster_matrix, method='average', metric='euclidean')
        row_order = leaves_list(row_linkage)
        heatmap_data = heatmap_data.iloc[row_order]
        cluster_matrix = cluster_matrix[row_order]

    if cluster_cols and heatmap_data.shape[1] > 1:
        col_linkage = linkage(cluster_matrix.T, method='average', metric='euclidean')
        col_order = leaves_list(col_linkage)
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(
        heatmap_data,
        cmap=plt.get_cmap(cmap_name),
        # Symmetric limits in z mode, so equal colours mean equal z.
        **({"vmin": -2.5, "vmax": 2.5} if value_type == "z" else {}),
        cbar_kws={'label': cbar_label},
        linewidths=0.5,
        linecolor='gray',
        square=False,
        mask=heatmap_data.isna(),
        annot=False,
        ax=ax
    )

    ax.set_xticklabels(ax.get_xticklabels(), rotation=90)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    if header:
        title_suffix = "Z-transformed" if value_type == "z" else "log2 Intensities"
        ax.set_title(f"{protein} ({title_suffix})", fontsize=14)
    ax.set_xlabel("Sample")
    ax.set_ylabel("PTM site")

    fig.tight_layout()
    return fig


#PHOSPHO-SPECIFIC
def _phossite_coverage_counts(data, meta, is_log2=True):
    samples = meta["sample"].astype(str).tolist()
    values = data[samples].apply(pd.to_numeric, errors="coerce")
    values = values.where(np.isfinite(values))
    if not is_log2:
        values = values.mask(values == 0)
    localization = pd.to_numeric(data.get("PTM_localization", pd.Series(np.nan, index=data.index)), errors="coerce")
    localization = localization.where(localization.between(0, 1))
    return pd.DataFrame({
        "Class I": values.loc[localization >= .75].notna().sum(),
        "Not Class I": values.loc[localization < .75].notna().sum(),
        "Unclassified": values.loc[localization.isna()].notna().sum(),
    })


def phossite_coverage_plot(
    data, meta, id=False, header=True, legend=True,
    width=20, height=10, dpi=300,
    color_classI="blue", color_notclassI="orange", is_log2=True, localization_cutoff=0.0
):
    data = filter_localization(data, localization_cutoff)
    counts = _phossite_coverage_counts(data, meta, is_log2)
    labels = meta["condition"].astype(str) + "_" + meta.groupby("condition").cumcount().astype(str)
    if id:
        labels += "\n(" + meta["sample"].astype(str).map(extract_id_or_number).astype(str) + ")"
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    bottom = np.zeros(len(counts))
    for category, color in zip(counts.columns, [color_classI, color_notclassI, "#94a3b8"]):
        if category == "Unclassified" and not counts[category].any():
            continue
        ax.bar(np.arange(len(counts)), counts[category], bottom=bottom, color=color, label=category)
        bottom += counts[category].to_numpy()
    ax.set_xticks(np.arange(len(counts)))
    ax.set_xticklabels(labels, rotation=90, fontsize=5)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Number of phosphosites" if header else "Number")
    ax.set_title("Phosphosites per sample" if header else "")
    if legend:
        ax.legend(loc="center left", bbox_to_anchor=(1, .5))
    plt.tight_layout()
    return fig


def sty_plot(data, localization_cutoff=0.0):
    data = filter_localization(data, localization_cutoff)
    sty = data["PTM_Collapse_key"].astype(str)
    letter = sty.str.extract(r'~[^_]+_([STY])\d+_')[0]
    letter = letter.fillna(sty.str.extract(r"(?:^|_)([STY])\d+(?:_|$)")[0])

    counts = letter.value_counts().reindex(["S", "T", "Y"], fill_value=0)
    if letter.isna().any():
        counts.loc["Unparsed"] = int(letter.isna().sum())
    total = counts.sum()
    perc = (counts / total * 100) if total > 0 else counts.astype(float)

    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=140)

    colors = {"S": "#4C78A8", "T": "#F58518", "Y": "#54A24B"}
    bar_colors = [colors.get(k, "#64748b") for k in counts.index]

    ax.bar(counts.index, counts.values, color=bar_colors, edgecolor="black", linewidth=0.6)

    ax.set_title("Modified S/T/Y Site Counts", pad=10, fontweight="bold")
    ax.set_xlabel("Peptide")
    ax.set_ylabel("Count")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)

    total_count = int(total)
    if total_count > 0:
        ax2 = ax.secondary_yaxis(
            "right", functions=(lambda count: count * 100 / total_count,
                                lambda percent: percent * total_count / 100),
        )
        ax2.set_ylabel("Share of sites (%)")
        ax2.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))

    y_max = max(counts.values) if len(counts.values) else 0
    offset = 0.02 * y_max if y_max > 0 else 0.1
    for i, (c, p) in enumerate(zip(counts.values, perc.values)):
        ax.text(i, c + offset, f"{p:.1f}%",
                ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    # Every other plotting function in this module returns its figure, and the
    # example notebook assigns the result. This one used to call plt.show() and
    # return None, so `fig = sty_plot(data3)` bound nothing and the figure could
    # not be saved, sized or put in a report from a script.
    return fig


def phossite_coverage_plot_summary(
    data, meta, header=True, legend=True,
    width=20, height=10, dpi=300,
    color_classI="blue", color_notclassI="orange", seed=69, is_log2=True, localization_cutoff=0.0
):
    data = filter_localization(data, localization_cutoff)
    counts = _phossite_coverage_counts(data, meta, is_log2)
    counts["condition"] = meta["condition"].astype(str).to_numpy()
    conditions = counts["condition"].unique()
    categories = ["Class I", "Not Class I"]
    if counts["Unclassified"].any():
        categories.append("Unclassified")
    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54), dpi=dpi)
    rng = np.random.default_rng(seed)
    bar_width = .7 / len(categories)
    for j, category in enumerate(categories):
        groups = [counts.loc[counts["condition"] == condition, category] for condition in conditions]
        means = [group.mean() for group in groups]
        sds = [group.std() if len(group) > 1 else 0 for group in groups]
        positions = np.arange(len(conditions)) + (j - (len(categories) - 1) / 2) * bar_width
        ax.bar(positions, means, width=bar_width, yerr=sds, capsize=3,
               color=[color_classI, color_notclassI, "#94a3b8"][j], label=category)
        for position, group in zip(positions, groups):
            ax.scatter(rng.normal(position, .05, len(group)), group, color="black", alpha=.7)
    ax.set_xticks(np.arange(len(conditions)))
    ax.set_xticklabels(conditions, rotation=45, ha="right")
    ax.set_ylabel("Number of phosphosites" if header else "Number")
    ax.set_title("Phosphosites per condition" if header else "")
    if legend:
        ax.legend(loc="center left", bbox_to_anchor=(1, .5))
    plt.tight_layout()
    return fig


def simple_phos_site_plot(data, filter_value=0, width_cm=15, height_cm=10, dpi=100, color="skyblue"):
    data = data[data["PTM_localization"] >= filter_value].copy()
    phosprot = data["Protein_group"].nunique()
    data["Seq"] = data["UPD_seq"].astype(str).str.replace(r"[^\w]", "", regex=True).str.upper()
    phospep = data["Seq"].nunique()
    phossite = data["PTM_Collapse_key"].nunique()
    df = pd.DataFrame({
        "term": ["Phosphoproteins", "Phosphopeptides", "Phosphosites"],
        "count": [phosprot, phospep, phossite]
    }).sort_values("count", ascending=False)

    width_in = width_cm / 2.54
    height_in = height_cm / 2.54
    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=dpi)
    ax.barh(df["term"], df["count"], color=color)

    for i, v in enumerate(df["count"]):
        ax.text(v + max(df["count"]) * 0.01, i, str(v), color="black", fontweight="bold", va="center")

    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(True)
    ax.spines["bottom"].set_visible(True)
    ax.grid(False)
    plt.tight_layout()
    return fig


def _normalize_ksea_results(data: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=data.index)
    names = {
        column: re.sub(r"[^a-z0-9]", "", str(column).lower().replace("₂", "2"))
        for column in data.columns
    }
    if not data.columns.is_unique:
        raise ValueError("Kinase Library result column names must be unique.")

    def numeric_field(aliases, *, effect=False):
        result = pd.Series(np.nan, index=data.index, dtype=float)
        found = False
        for column, name in names.items():
            if name not in aliases:
                continue
            found = True
            supplied = data[column].notna() & data[column].astype(str).str.strip().ne("")
            values = pd.to_numeric(data[column], errors="coerce")
            if (supplied & ~np.isfinite(values)).any():
                raise ValueError(f"Kinase Library column '{column}' must contain finite numeric values.")
            if effect and name == "frequencyfactor":
                if (supplied & (values <= 0)).any():
                    raise ValueError("Raw Frequency Factor values must be positive.")
                values = np.log2(values.where(supplied))
            elif not effect and (supplied & ((values < 0) | (values > 1))).any():
                raise ValueError("Adjusted p-values must be between 0 and 1.")
            conflict = supplied & result.notna() & ~np.isclose(result, values, rtol=1e-10, atol=1e-12)
            if conflict.any():
                raise ValueError("Conflicting Kinase Library result columns; provide consistent values.")
            result = result.where(result.notna(), values.where(supplied))
        if not found or result.isna().any():
            raise ValueError("Each Kinase Library row requires a frequency factor and adjusted p-value.")
        return result

    if data.empty:
        return pd.DataFrame(columns=["Kinase", "Log2(Frequency Factor)", "Adjusted p-value"])
    frame["Log2(Frequency Factor)"] = numeric_field({"log2frequencyfactor", "frequencyfactor"}, effect=True)
    frame["Adjusted p-value"] = numeric_field({"adjustedpvalue", "adjustedp"})
    labels = pd.Series(pd.NA, index=data.index, dtype="object")
    for alias in ("kinase", "genename", "gene"):
        for column, name in names.items():
            if name == alias:
                labels = labels.fillna(data[column].where(data[column].astype(str).str.strip().ne("")))
    frame["Kinase"] = labels.fillna(frame["Log2(Frequency Factor)"].astype(str)).astype(str)
    return frame


# Classes of uploaded Kinase Library results: a significant frequency factor is
# motif enrichment among up- or down-regulated sites, not kinase activity.
KINASE_ENRICHED_UP = "Enriched in up-regulated sites"
KINASE_ENRICHED_DOWN = "Enriched in down-regulated sites"


def kinase_library_volcano(
        data_st,
        data_tnc,
        pval_thresh=0.1,
        header=True,
        condition1=None,
        condition2=None
):
    df = pd.concat([_normalize_ksea_results(data_st), _normalize_ksea_results(data_tnc)], ignore_index=True)
    if df.empty:
        raise ValueError("Uploaded Kinase Library result files are empty.")
    df = df.rename(columns={"Log2(Frequency Factor)": "Log₂(Frequency Factor)"})
    df["neg_log10_pval"] = -np.log10(df["Adjusted p-value"].clip(lower=1e-300))

    def classify(row):
        if row["Adjusted p-value"] < pval_thresh:
            if row["Log₂(Frequency Factor)"] > 0:
                return KINASE_ENRICHED_UP
            elif row["Log₂(Frequency Factor)"] < 0:
                return KINASE_ENRICHED_DOWN
        return "Not significant"

    df["Regulation"] = df.apply(classify, axis=1)
    df["color"] = df["Regulation"].map({KINASE_ENRICHED_UP: "red", KINASE_ENRICHED_DOWN: "blue", "Not significant": "lightgrey"})

    df["line_color"] = "black"
    df["line_width"] = 0.5

    title = f"Kinase Library Motif Enrichment: {condition1} vs. {condition2}" if header and condition1 and condition2 else (
        "Kinase Library Motif Enrichment" if header else "")
    x_label = f"log₂(Frequency Factor) ({condition1} - {condition2})" if condition1 and condition2 else "log₂(Frequency Factor)"

    fig = go.Figure()

    for reg in df["Regulation"].unique():
        sub = df[df["Regulation"] == reg]
        fig.add_trace(go.Scatter(
            x=sub["Log₂(Frequency Factor)"],
            y=sub["neg_log10_pval"],
            mode="markers",
            marker=dict(
                color=sub["color"],
                line=dict(color=sub["line_color"], width=sub["line_width"]),
                size=10
            ),
            name=reg,
            text=sub["Kinase"],
            hovertemplate="Kinase: %{text}<br>Log₂(Frequency Factor): %{x}<br>-log₁₀(p-value): %{y}<br>Regulation: " + reg + "<extra></extra>"
        ))

    fig.add_hline(y=-np.log10(pval_thresh), line_dash="dash", line_color="green")
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title="-log₁₀(Adjusted p-value)",
        template="plotly_white",
        hovermode="closest",
        height=600
    )

    return fig


def kinase_tree_data_pval(data_st, data_tnc):
    df = pd.concat([data_st, data_tnc], ignore_index=True)
    required_cols = {"Gene Name", "Adjusted p-value"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Input must contain 'Gene Name' and 'Adjusted p-value' columns")
    df = df[["Gene Name", "Adjusted p-value"]].copy()
    adjusted = pd.to_numeric(df["Adjusted p-value"], errors="coerce")
    df["-log10(adj_pval)"] = -np.log10(adjusted.clip(lower=1e-300))
    return df[["Gene Name", "-log10(adj_pval)"]]


def kinase_tree_data_fc(data_st, data_tnc):
    df = pd.concat([data_st, data_tnc], ignore_index=True)
    required_cols = {"Gene Name", "Log₂(Frequency Factor)"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Input must contain 'Gene Name' and 'Log₂(Frequency Factor)' columns")
    df = df[["Gene Name", "Log₂(Frequency Factor)"]]
    return df


def phossite_dist(data, cutoff=0, width=20, height=15, dpi=300, header=True):
    if 'Phosphoprotein' not in data.columns or 'site_num' not in data.columns:
        raise ValueError("Data must contain 'Phosphoprotein' and 'site_num' columns.")

    data = data.copy()
    data['site_num'] = pd.to_numeric(data['site_num'], errors='coerce')
    data = data.dropna(subset=['site_num'])

    if cutoff > 0:
        threshold = data['site_num'].quantile(1 - cutoff)
        data = data[data['site_num'] <= threshold]

    counts = data['site_num'].value_counts().sort_index()
    x = counts.index.astype(int)
    y = counts.values

    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54), dpi=dpi)

    ax.bar(x, y)

    xmax = x.max()
    xticks = np.arange(0, xmax + 1, 10)

    ax.set_xticks(xticks)
    ax.xaxis.set_major_locator(plt.FixedLocator(xticks))
    ax.set_xticklabels(xticks)
    ax.set_xlabel("Number of phosphosites per phosphoprotein")
    ax.set_ylabel("Frequency")

    if header:
        fig.suptitle("Distribution of phosphosite counts per protein", fontsize=14)

    plt.tight_layout()
    return fig


#COMPARISON
def correlation_xy_intensity_single(data, sample1, sample2, alias1=None, alias2=None, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=True):
    valid_data = data[[sample1, sample2]].dropna()
    if valid_data.empty: raise ValueError("No overlapping proteins with intensity in both samples.")
    x, y = valid_data[sample1].values, valid_data[sample2].values
    r, p_val = pearsonr(x, y)
    label1, label2 = alias1.strip() if alias1 else sample1, alias2.strip() if alias2 else sample2
    fig, ax = plt.subplots(figsize=(width_cm/2.54, height_cm/2.54), dpi=dpi)
    ax.scatter(x, y, color=color, edgecolor='k', alpha=0.7, s=dot_size)
    slope, intercept = np.polyfit(x, y, 1)
    ax.plot(x, slope*x + intercept, color='red', linewidth=2, label=f'Fit: y={slope:.2f}x+{intercept:.2f}')
    ax.set_xlabel(f'{label1} (log2 intensity)')
    ax.set_ylabel(f'{label2} (log2 intensity)')
    if show_header: ax.set_title(f'{label1} vs {label2}\nPearson r={r:.3f}, p={p_val:.2e}', fontsize=12)
    ax.legend(loc='upper left', frameon=True); ax.grid(True, linestyle='--', alpha=0.5); plt.tight_layout()
    return fig


def correlation_xy_intensity(data, meta, condition1, condition2, alias1=None, alias2=None, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=True, min_present=1):
    s1 = meta.loc[meta['condition']==condition1,'sample'].astype(str).tolist()
    s2 = meta.loc[meta['condition']==condition2,'sample'].astype(str).tolist()
    if not s1 or not s2: raise ValueError("One or both conditions have no associated samples.")
    # min_present=1 (the default) reports every mean. Raise it to drop means that
    # rest on fewer replicates than that, which would otherwise be plotted at the
    # same weight as a fully observed one.
    mean1, _ = condition_mean(data, s1, min_present=min_present)
    mean2, _ = condition_mean(data, s2, min_present=min_present)
    valid_data = pd.concat([mean1, mean2], axis=1).dropna()
    if valid_data.empty: raise ValueError("No overlapping proteins with intensity in both conditions after the minimum-replicate filter.")
    x, y = valid_data.iloc[:,0].values, valid_data.iloc[:,1].values
    r, p_val = pearsonr(x, y)
    label1, label2 = alias1.strip() if alias1 else condition1, alias2.strip() if alias2 else condition2
    fig, ax = plt.subplots(figsize=(width_cm/2.54, height_cm/2.54), dpi=dpi)
    ax.scatter(x, y, color=color, edgecolor='k', alpha=0.7, s=dot_size)
    slope, intercept = np.polyfit(x, y, 1)
    ax.plot(x, slope*x + intercept, color='red', linewidth=2, label=f'Fit: y={slope:.2f}x+{intercept:.2f}')
    ax.set_xlabel(f'{label1} (mean log2 intensity)')
    ax.set_ylabel(f'{label2} (mean log2 intensity)')
    if show_header: ax.set_title(f'{label1} vs {label2}\nPearson r={r:.3f}, p={p_val:.2e}', fontsize=12)
    ax.legend(loc='upper left', frameon=True); ax.grid(True, linestyle='--', alpha=0.5); plt.tight_layout()
    return fig


def overlap_plot_single(data, sample1, sample2, sample3=None, width=7, height=7, dpi=300, labels=None, colors=None, show_header=True, data_scale="log2"):
    samples = [sample1, sample2] + ([sample3] if sample3 is not None else [])
    data = _prepare_intensity_data(data, samples, data_scale)
    p1 = set(data.index[data[sample1].notna()])
    p2 = set(data.index[data[sample2].notna()])
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    if sample3:
        p3 = set(data.index[data[sample3].notna()])
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn3([p1, p2, p3], set_labels=labels or [sample1, sample2, sample3], ax=ax, **kwargs)
    else:
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn2([p1, p2], set_labels=labels or [sample1, sample2], ax=ax, **kwargs)
    if show_header: ax.set_title("Overlap", fontsize=14)
    plt.tight_layout()
    return fig


def overlap_plot_condition(data, meta, condition1, condition2, condition3=None, width=7, height=7, dpi=300, labels=None, colors=None, show_header=True, data_scale="log2", min_present=1):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    if not np.isfinite(min_present) or int(min_present) != min_present or min_present < 1:
        raise ValueError("min_present must be a positive integer.")
    for condition in [condition1, condition2] + ([condition3] if condition3 else []):
        if (meta['condition'] == condition).sum() < min_present:
            raise ValueError(f"Condition '{condition}' has fewer samples than min_present.")
    s1 = meta.loc[meta['condition']==condition1,'sample'].tolist()
    s2 = meta.loc[meta['condition']==condition2,'sample'].tolist()
    p1 = set(data.index[data[s1].notna().sum(axis=1) >= min_present])
    p2 = set(data.index[data[s2].notna().sum(axis=1) >= min_present])
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    if condition3:
        s3 = meta.loc[meta['condition']==condition3,'sample'].tolist()
        p3 = set(data.index[data[s3].notna().sum(axis=1) >= min_present])
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn3([p1, p2, p3], set_labels=labels or [condition1, condition2, condition3], ax=ax, **kwargs)
    else:
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn2([p1, p2], set_labels=labels or [condition1, condition2], ax=ax, **kwargs)
    if show_header: ax.set_title("Overlap", fontsize=14)
    plt.tight_layout()
    return fig


#DATA COMPLETENESS
def missing_value_plot(data, meta, bin=0, header=True, text=True, text_size=3.88,
                       width=7.87, height=3.94, dpi=300, color='blue', data_scale="log2"):
    annotated_columns = meta['sample'].tolist()
    data_filtered = _prepare_intensity_data(data, annotated_columns, data_scale)[annotated_columns]
    na_count = data_filtered.isna().sum(axis=1)

    if bin > 0:
        na_count = na_count.apply(lambda x: f">{bin}" if x > bin else str(x))
        levels_vec = [str(i) for i in range(bin + 1)] + [f">{bin}"]
    else:
        na_count = na_count.astype(str)
        max_count = int(na_count[na_count != 'nan'].astype(float).max()) if not na_count.empty else 0
        levels_vec = [str(i) for i in range(max_count + 1)]

    miss_vals = na_count.value_counts().reset_index()
    miss_vals.columns = ['na_count', 'Freq']
    miss_vals = miss_vals[miss_vals['na_count'] != str(len(annotated_columns))]
    miss_vals['na_count'] = pd.Categorical(miss_vals['na_count'], categories=levels_vec, ordered=True)
    miss_vals = miss_vals.sort_values('na_count')

    if "Phosphoprotein" in data.columns:
        plot_title = "Missing Value Plot - Phosphoprotein Level"
    elif "ProteinNames" in data.columns:
        plot_title = "Missing Value Plot - Protein Level"
    elif "PTM_Collapse_key" in data.columns:
        plot_title = "Missing Value Plot - Phosphosite Level"
    else:
        plot_title = "Missing value plot"

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.bar(miss_vals['na_count'], miss_vals['Freq'], color=color)
    ax.set_xlabel("Number of Missing Values")
    ax.set_ylabel("Frequency")

    if text:
        for idx, row in miss_vals.iterrows():
            ax.text(row['na_count'], row['Freq'] + max(miss_vals['Freq']) * 0.01, str(row['Freq']),
                    ha='center', fontsize=text_size)

    if header:
        ax.set_title(plot_title)

    ax.tick_params(axis='x', rotation=0)
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    plt.tight_layout()

    return fig


def _missing_bar(counts, bin, title, header, text, text_size, color, width=10, height=6, dpi=100):
    """Bar chart of how many features miss how many samples.

    `counts` holds one missing-value count per feature. With `bin` > 0 every
    count above it is pooled into one `>bin` bar. The R functions' `.missing_bar`
    draws the same chart.
    """
    if bin > 0:
        labels = counts.apply(lambda x: f">{bin}" if x > bin else str(x))
        levels_vec = [str(i) for i in range(bin + 1)] + [f">{bin}"]
    else:
        labels = counts.astype(str)
        levels_vec = None
    miss_vals = labels.value_counts().sort_index()
    if levels_vec is None:
        levels_vec = sorted(miss_vals.index, key=lambda x: int(x))
    miss_vals = miss_vals.reindex(levels_vec, fill_value=0)

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.bar(miss_vals.index, miss_vals.values, color=color)
    if header:
        ax.set_title(title)
    ax.set_xlabel("Number of Missing Values")
    ax.set_ylabel("Frequency")
    if text:
        for i, val in enumerate(miss_vals.values):
            if val > 0:
                ax.text(i, val + 0.5, str(val), ha='center', va='bottom', fontsize=text_size)
    plt.tight_layout()
    return fig


def missing_value_plot_prec(data_path, meta, bin=0, header=True, text=True,
                            text_size=8, width=10, height=6, dpi=100, color='blue', quantity_column='Precursor.Quantity'):
    data = sanitize_dataframe(read_data(data_path)).copy()
    meta = meta.copy()

    df_wide = data.pivot_table(
        index='File.Name',
        columns='Precursor.Id',
        values=quantity_column,
        # 'max' matches missing_value_plot_pep above. 'first' depended on input
        # row order, and raw_zero_to_nan runs immediately after, so which
        # duplicate won decided whether a precursor read as detected.
        aggfunc='max'
    )

    df_wide = df_wide.T
    sample_map = _peptide_sample_map(df_wide.columns, meta['sample'])
    data_filtered = df_wide[list(sample_map)].rename(columns=sample_map)
    data_filtered = raw_zero_to_nan(data_filtered, data_filtered.columns)

    na_count = data_filtered.dropna(how="all").isna().sum(axis=1)
    return _missing_bar(na_count, bin, "Missing Value Plot - Precursor Level", header, text, text_size, color,
                        width=width, height=height, dpi=dpi)


def missing_value_plot_pep(data_path, meta, bin=0, header=True, text=True,
                           text_size=8, width=10, height=6, dpi=100, color='blue', quantity_column='Precursor.Quantity'):
    data = sanitize_dataframe(read_data(data_path)).copy()
    meta = meta.copy()

    if "File.Name" in data.columns:
        df_wide = data.pivot_table(
            index='File.Name',
            columns='Stripped.Sequence',
            values=quantity_column,
            aggfunc='max'
        )
        df_wide = df_wide.T
    else:
        df_wide = data.copy()

    sample_map = _peptide_sample_map(df_wide.columns.drop('Stripped.Sequence', errors='ignore'), meta['sample'])
    data_filtered = df_wide[list(sample_map)].rename(columns=sample_map)
    data_filtered = raw_zero_to_nan(data_filtered, data_filtered.columns)

    na_count = data_filtered.dropna(how="all").isna().sum(axis=1)
    return _missing_bar(na_count, bin, "Missing Value Plot - Peptide Level", header, text, text_size, color,
                        width=width, height=height, dpi=dpi)


def _feature_axis_label(data):
    """What one row of the matrix is, for an axis label: Proteins / Phosphosites / Phosphoproteins."""
    columns = set(data.columns)
    if "Phosphoprotein" in columns:
        return "Phosphoproteins"
    if "PTM_Collapse_key" in columns:
        return "Phosphosites"
    if "ProteinNames" in columns:
        return "Proteins"
    return "Features"


def _quantified_rows(frame, samples):
    """The rows of `frame` with a value in at least one of `samples`.

    A feature missing in every selected sample says nothing about how complete
    those samples are -- it was identified elsewhere, or never quantified -- so
    the completeness heatmap, tables and overall percentage leave it out, as the
    web app and the R functions do. `missing_value_plot` already drops its bar.
    """
    return frame.loc[frame[samples].notna().any(axis=1)]


def missing_value_heatmap(data, meta, id=True, header=True, width=20, height=10, dpi=300,
                          data_scale="log2"):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)

    meta = meta.copy()
    meta = _sample_meta(meta, id=id)
    data_filtered = _rename_samples(data, meta)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = _quantified_rows(data_filtered[annotated_columns], annotated_columns)

    plt.figure(figsize=(width, height), dpi=dpi)
    sns.heatmap(data_filtered.isnull(), cbar=False, cmap='viridis')
    if header:
        plt.title("Missing Values Heatmap")
    plt.xlabel("Sample")
    plt.ylabel(_feature_axis_label(data))
    plt.tight_layout()
    fig = plt.gcf()
    return fig


def missing_protein_table(data, meta, id=True, data_scale="log2"):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    meta = meta.copy()
    meta = _sample_meta(meta, id=id)
    data_filtered = _rename_samples(data, meta)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = _quantified_rows(data_filtered[annotated_columns], annotated_columns)

    na_counts = data_filtered.isna().sum(axis=1)
    summary = na_counts.value_counts().reset_index()
    summary.columns = ['n_MissingProteinValues', 'Counts']
    summary = summary.sort_values('n_MissingProteinValues').reset_index(drop=True)
    summary['%_missing_values'] = (summary['Counts'] / summary['Counts'].sum()) * 100
    return summary


def missing_sample_table(data, meta, id=True, data_scale="log2"):
    data = _prepare_intensity_data(data, meta['sample'].tolist(), data_scale)
    meta = meta.copy()
    meta = _sample_meta(meta, id=id)
    data_filtered = _rename_samples(data, meta)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = _quantified_rows(data_filtered[annotated_columns], annotated_columns)

    na_counts = data_filtered.isna().sum(axis=0)
    summary = na_counts.reset_index()
    summary.columns = ['Sample', 'Counts']
    summary['%_missing_values'] = (summary['Counts'] / data_filtered.shape[0]) * 100
    return summary


def missing_value_outlier(df, thld=50):
    outliers = df[df['%_missing_values'] > thld]['Sample'].tolist()
    return outliers

def all_miss_val(data, meta, data_scale="log2"):
    samples = meta['sample'].tolist()
    data = _quantified_rows(_prepare_intensity_data(data, samples, data_scale)[samples], samples)
    total_values = data.size
    missing_values = data.isna().sum().sum()
    percent_missing = (missing_values / total_values) * 100
    return round(percent_missing, 2)

def _drop_incomplete_features(matrix, context="heatmap", minimum_rows=1):
    """Return the fully observed rows, and how many were dropped to get them.

    Hierarchical clustering is undefined for a feature missing in any sample.
    Refusing the whole matrix over a handful of them denies the plot entirely;
    dropping them silently hides that the figure rests on a subset. The rows are
    dropped and `_warn_dropped_features` states the cost.

    Returns ``(complete_matrix, kept_mask, dropped, total)``.
    """
    if isinstance(matrix, pd.DataFrame):
        numeric = matrix.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    else:
        numeric = np.asarray(matrix, dtype=float)
    if numeric.ndim != 2:
        raise ValueError("Clustering requires a two-dimensional matrix.")

    rows, columns = numeric.shape
    complete = np.isfinite(numeric).all(axis=1)
    kept = int(complete.sum())
    if kept < max(1, int(minimum_rows)):
        raise ValueError(
            f"{context.capitalize()} cannot be computed because only {kept} of {rows} "
            f"features are observed in all {columns} samples. Impute the matrix before "
            "calling this function. The data was not changed automatically."
        )
    return numeric[complete], complete, rows - kept, rows


def _dropped_features_message(dropped, total, purpose="clustering", noun="features"):
    """The same sentence the web app shows beneath the plot."""
    if not dropped or not total:
        return None
    percent = dropped / total * 100.0
    if percent < 0.1:
        text = "<0.1%"
    elif percent < 10:
        text = f"{percent:.1f}%"
    else:
        text = f"{percent:.0f}%"
    return (
        f"{text} of {noun} dropped for {purpose} ({dropped:,} of {total:,}) "
        "\u2014 not observed in every sample"
    )


def _warn_dropped_features(dropped, total, purpose="clustering"):
    """Report the drop where a notebook user sees it: under the cell."""
    message = _dropped_features_message(dropped, total, purpose=purpose)
    if message:
        warnings.warn(message, RuntimeWarning, stacklevel=3)


# The workflow is Kinase Library motif enrichment (Johnson et al., Nature 2023),
# not KSEA (Casado et al., 2013). The ksea_* names are kept as aliases so
# existing notebooks keep working.
ksea_data_f = kinase_library_data_f
ksea_data_f_control = kinase_library_data_f_control
ksea_volcano = kinase_library_volcano
