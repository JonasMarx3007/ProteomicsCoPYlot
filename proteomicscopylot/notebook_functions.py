"""Notebook-facing CoPYlot functions.

This module mirrors the original notebook API used by notebooks such as
``8cell.ipynb``. Keep it in sync with the app/backend implementation when
analysis behavior changes, and keep notebook-friendly signatures stable so this
file can later become the basis for a pip package import.
"""

import os
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pyarrow.parquet as pq
import scipy.stats as stats
import seaborn as sns
from matplotlib.patches import Ellipse
from matplotlib.patches import Rectangle
from matplotlib_venn import venn2, venn3
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform
from scipy.stats import gaussian_kde, pearsonr
from scipy.stats import t
from scipy.stats import ttest_ind, ttest_rel
from sklearn.decomposition import PCA

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

try:
    from gprofiler import GProfiler
except ModuleNotFoundError:
    GProfiler = None

try:
    from Bio import SeqIO
except ModuleNotFoundError:
    SeqIO = None


#BASIC AND DATA
def resource_path_manual(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


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
    if isinstance(value, (int, float)):
        return str(value)
    else:
        return ""


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


def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
    return str(base_path / relative_path)


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


def extract_id_or_number(x):
    matches = re.findall(r'\d+', x)
    return matches[-1] if matches else x


def log2_transform_data(data: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns].copy()
    data_filtered.replace(0, np.nan, inplace=True)
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


def filter_data(data, meta, num, filterops="per group"):
    meta = meta.copy()
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns].copy()

    conditions = meta['condition'].unique()

    mask = pd.DataFrame(False, index=data_filtered.index, columns=conditions)
    for cond in conditions:
        cols = meta.loc[meta['condition'] == cond, 'sample']
        mask[cond] = (data_filtered[cols].notna().sum(axis=1) >= num)

    if filterops == "per group":
        rows_to_keep = mask.all(axis=1)
    else:
        rows_to_keep = mask.any(axis=1)

    return data.loc[rows_to_keep]


def transform_phosprot(data: pd.DataFrame, meta: pd.DataFrame, mode: str = "sum_mean_impute"):
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

    sample_cols = list(meta["sample"])
    missing_samples = [s for s in sample_cols if s not in data.columns]
    if missing_samples:
        raise ValueError(f"`meta.sample` contains names not found in data: {missing_samples}")

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
        return vals.fillna(0).sum()

    def mean(series: pd.Series):
        vals = pd.to_numeric(series, errors="coerce")
        return vals.mean()

    if mode == "sum_mean_impute":
        df = data.copy()

        intensity_cols = sample_cols

        for cond in meta["condition"].unique():
            cond_samples = meta.loc[meta["condition"] == cond, "sample"]
            cond_samples = [s for s in cond_samples if s in intensity_cols]

            if len(cond_samples) > 0:
                mean_vals = df[cond_samples].mean()
                df[cond_samples] = df[cond_samples].fillna(mean_vals)

        data = df
        summarizer = lambda s: pd.to_numeric(s, errors="coerce").sum()

    elif mode == "sum_propagate_na":
        summarizer = sum_propagate_nan
    elif mode == "sum_ignore_na":
        summarizer = sum_ignore_nan
    elif mode == "mean":
        summarizer = mean
    else:
        raise ValueError("mode must be 'sum_mean_impute', 'sum_propagate_na', 'sum_ignore_na', or 'mean'")

    agg_dict = {
        "Gene_group": "first",
        "PTM_Collapse_key": collapse,
        "PTM_localization": arrange_elements,
        "UPD_seq": collapse,
        **{col: summarizer for col in sample_cols}
    }

    data_phosprot = data.groupby("Protein_group", as_index=False).agg(agg_dict)

    site_counts = data.groupby("Protein_group").size().reset_index(name="site_num")
    data_phosprot = data_phosprot.merge(site_counts, on="Protein_group", how="left")

    data_phosprot = data_phosprot.rename(columns={
        "PTM_Collapse_key": "PTM_Collapse_keys",
        "Protein_group": "Phosphoprotein"
    })

    cols = data_phosprot.columns.tolist()
    cols.remove("site_num")
    insert_pos = cols.index("Gene_group") + 1
    cols.insert(insert_pos, "site_num")
    data_phosprot = data_phosprot[cols]

    return data_phosprot


def qqnorm_plot(data, meta):
    sample_columns = meta['sample'].tolist()
    data_values = data[sample_columns].replace(0, np.nan)

    values_vector = data_values.values.flatten()
    values_vector = values_vector[~np.isnan(values_vector)]
    values_vector = values_vector[values_vector > 0]

    if len(values_vector) > 100_000:
        np.random.seed(187)
        values_vector = np.random.choice(values_vector, 100_000, replace=False)

    fig, ax = plt.subplots()
    stats.probplot(values_vector, plot=ax)
    ax.set_title("QQ Plot")
    ax.set_xlabel("Theoretical Quantiles")
    ax.set_ylabel("Sample Quantiles")
    return fig

def impute_values(data: pd.DataFrame, meta: pd.DataFrame, q=0.01, adj_std=1, ret=0, sample_wise=False, seed=69):
    np.random.seed(seed)
    data = data.replace(0, np.nan).copy()
    annotated_columns = meta["sample"].tolist()
    data_filtered = data[annotated_columns]
    combined_data = data_filtered.values.flatten()
    missing_value_mask = data_filtered.isna()
    data_without_na = data_filtered.loc[~data_filtered.isna().any(axis=1)]
    data_with_na = data_filtered.loc[data_filtered.isna().any(axis=1)]
    combined_data_without_na = data_without_na.values.flatten()
    combined_data_with_na = data_with_na.values.flatten()

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

    mean_val = np.nanmean(combined_data)
    sd_val = np.nanstd(combined_data)
    quantile_val = np.nanquantile(combined_data, q)

    if ret == 2:
        fig, ax = plt.subplots()
        ax.hist(combined_data[~np.isnan(combined_data)],
                bins=50, density=True, alpha=0.6, color="blue", histtype='stepfilled')
        x = np.linspace(np.nanmin(combined_data), np.nanmax(combined_data), 200)
        ax.plot(x, (1/(sd_val*np.sqrt(2*np.pi))) * np.exp(-0.5*((x-mean_val)/sd_val)**2),
                color="red", label="Normal fit")
        ax.set_title("Overall data distribution and norm fit")
        ax.set_xlabel("log2 Intensity")
        ax.set_ylabel("Density")
        ax.legend()
        return fig

    if sample_wise:
        for col in annotated_columns:
            col_vals = data_filtered[col]
            col_sd = np.nanstd(col_vals)
            num_na = col_vals.isna().sum()
            col_quantile_val = np.nanquantile(col_vals, q)
            if num_na > 0:
                data_filtered.loc[col_vals.isna(), col] = np.random.normal(col_quantile_val, col_sd, num_na)
    else:
        for col in annotated_columns:
            col_vals = data_filtered[col]
            num_na = col_vals.isna().sum()
            if num_na > 0:
                data_filtered.loc[col_vals.isna(), col] = np.random.normal(quantile_val, sd_val*adj_std, num_na)

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
                  width=20, height=10, dpi=300, text=False, text_size=9):
    data = data.replace(0, np.nan)
    conditions = meta['condition'].unique()
    meta['sample'] = meta['sample'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    if id:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}\n({row['id']})", axis=1
        )
    else:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

    rename_dict = dict(zip(meta['sample'], meta['new_sample']))
    data_filtered = data.rename(columns=rename_dict)
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

    ax.set_xlabel('Condition')

    redline = None

    if 'Phosphoprotein' in data.columns:
        ax.set_ylabel('Number of phosphoproteins')
        redline = len(data['Phosphoprotein'])
        if header: fig.suptitle('Phosphoproteins per sample', fontsize=14)

    elif 'ProteinNames' in data.columns:
        ax.set_ylabel('Number of proteins')
        redline = len(data['ProteinNames'])
        if header: fig.suptitle('Proteins per sample', fontsize=14)

    elif 'PTM_Collapse_key' in data.columns:
        ax.set_ylabel('Number of phosphosites')
        redline = len(data['PTM_Collapse_key'])
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
                          text_size=9):
    data = data.replace(0, np.nan)
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

    rng = np.random.default_rng()
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

    if header:
        if "Phosphoprotein" in data.columns:
            plot_title = "Phosphoproteins per sample"
            y_label = "Number of phosphoproteins"
            red_line_value = len(data["Phosphoprotein"])
            ax.axhline(red_line_value, linestyle="--", color="red")

        elif "ProteinNames" in data.columns:
            plot_title = "Proteins per sample"
            y_label = "Number of proteins"
            red_line_value = len(data["ProteinNames"])
            ax.axhline(red_line_value, linestyle="--", color="red")

        elif "PTM_Collapse_key" in data.columns:
            plot_title = "Phosphosites per sample"
            y_label = "Number of phosphosites"
            red_line_value = len(data["PTM_Collapse_key"])
            ax.axhline(red_line_value, linestyle="--", color="red")

    ax.set_title(plot_title)
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


def coverage_plot_pep(data2_path, meta, id=True, header=True, legend=True,
                      plot_colors=None, width=10, height=6, dpi=100):

    if isinstance(data2_path, pd.DataFrame):
        data = data2_path.copy()
    else:
        data = sanitize_dataframe(read_data(data2_path)).copy()

    meta = meta.copy()
    meta['sample'] = meta['sample'].astype(str)
    meta['condition'] = meta['condition'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number).astype(str)
    meta = meta.reset_index(drop=True)
    cnt = meta.groupby('condition').cumcount() + 1
    if id:
        meta['new_sample'] = meta['condition'] + "_" + cnt.astype(str) + "\n(" + meta['id'].astype(str) + ")"
    else:
        meta['new_sample'] = meta['condition'] + "_" + cnt.astype(str)

    ordered_new_samples = list(meta['new_sample'])
    id_to_new = dict(zip(meta['id'], meta['new_sample']))
    sample_to_new = dict(zip(meta['sample'], meta['new_sample']))
    new_to_condition = dict(zip(meta['new_sample'], meta['condition']))

    if "File.Name" in data.columns:
        pivot = data.pivot_table(index='Stripped.Sequence', columns='File.Name',
                                 values='Precursor.Quantity', aggfunc='max')
        peptides_count = pivot.shape[0]
        pivot.columns = [extract_id_or_number(str(c)) for c in pivot.columns]
        rename_map = {c: id_to_new[c] for c in pivot.columns if c in id_to_new}
        pivot = pivot.rename(columns=rename_map)
        annotated_cols = [c for c in ordered_new_samples if c in pivot.columns]
        data_filtered = pivot[annotated_cols].reset_index()
    else:
        if 'Stripped.Sequence' in data.columns:
            peptides_count = data['Stripped.Sequence'].nunique()
        else:
            peptides_count = data.shape[0]
        rename_map = {s: sample_to_new[s] for s in meta['sample'] if s in data.columns}
        d2 = data.rename(columns=rename_map)
        annotated_cols = [c for c in ordered_new_samples if c in d2.columns]
        data_filtered = d2[annotated_cols].copy()
        if 'Stripped.Sequence' in data.columns:
            data_filtered = pd.concat([data[['Stripped.Sequence']].reset_index(drop=True),
                                       data_filtered.reset_index(drop=True)], axis=1)
        else:
            data_filtered = data_filtered.reset_index().rename(columns={'index': 'Stripped.Sequence'})

    for c in data_filtered.columns:
        if c != 'Stripped.Sequence':
            data_filtered[c] = pd.to_numeric(data_filtered[c], errors='coerce')
            data_filtered[c] = np.where(data_filtered[c].notna() & (data_filtered[c] != 0), 1, 0)

    plot_data = data_filtered.melt(id_vars='Stripped.Sequence', var_name='Sample', value_name='Value')
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
        ax.set_title("Peptides per sample")
    ax.set_ylabel("Number of peptides")
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
            colors = plt.cm.get_cmap('tab20').colors
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
        ax.set_title('Distribution of measured intensity (log2)')

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
            base_colors = plt.cm.get_cmap('tab20').colors
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
                    pos, med * 1.02,  # slightly above the median line
                    f"{med:.2f}",
                    ha='center', va='bottom', fontsize=text_size,
                    color='black', rotation=0, fontweight='bold'
                )

    ax.set_xticks(positions)
    ax.set_xticklabels(conditions_order)
    ax.set_xlabel("Condition")
    ax.set_ylabel("log2 Intensity")

    if header:
        ax.set_title("Measured intensity values (log2)")

    if ax.get_legend() is not None:
        ax.get_legend().remove()

    plt.tight_layout(rect=[0, 0, 0.85, 1])
    return fig


def boxplot_int_single(
    data, meta, outliers=False, id=True, header=True, legend=True, plot_colors=None,
    width_cm=20, height_cm=10, dpi=100, text=False, text_size=9
):
    meta = meta.copy()
    meta["id"] = meta["sample"].apply(extract_id_or_number)

    if id:
        meta["new_sample"] = meta.groupby("condition").cumcount() + 1
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})", axis=1
        )
    else:
        meta["new_sample"] = meta.groupby("condition").cumcount() + 1
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data = data.rename(columns=rename_dict)

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
        cmap = plt.cm.get_cmap("tab10", len(unique_conditions))
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
                    i + 1, median * 1.02,
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
             width_cm=20, height_cm=10, dpi=100, text=False, text_size=9):
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
            base_colors = plt.cm.get_cmap('tab20').colors
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
    while err > tol:
        X = Q @ np.diag(u) @ QT
        M = np.diag(QT @ np.linalg.inv(X) @ Q)
        j = np.argmax(M)
        step_size = (M[j] - d - 1) / ((d + 1) * (M[j] - 1))
        new_u = (1 - step_size) * u
        new_u[j] += step_size
        err = np.linalg.norm(new_u - u)
        u = new_u
    center = points.T @ u
    A = np.linalg.inv(points.T @ np.diag(u) @ points - np.outer(center, center)) / d
    U, s, _ = np.linalg.svd(A)
    axes = 1. / np.sqrt(s)
    angle = np.degrees(np.arctan2(U[1, 0], U[0, 0]))
    return center, axes, angle


def pca_plot(data, meta, header=True, legend=True, dot_size=3,
             width_cm=20, height_cm=10, dpi=100, plot_colors=None,
             plot_3d=False, add_ellipses=False):
    meta['condition'] = pd.Categorical(meta['condition'], categories=meta['condition'].unique(), ordered=True)
    annotated_columns = meta['sample'].tolist()
    data_filtered = data[annotated_columns].dropna()
    transposed_expr = data_filtered.T
    zero_variance_columns = transposed_expr.var(axis=0) == 0
    transposed_expr = transposed_expr.loc[:, ~zero_variance_columns]
    n_components = 3 if plot_3d else 2
    pca = PCA(n_components=n_components)
    pca_result = pca.fit_transform(transposed_expr)
    explained_variance = pca.explained_variance_ratio_ * 100
    pcs = [f'PC{i+1}' for i in range(n_components)]
    pca_scores = pd.DataFrame(pca_result, columns=pcs)
    pca_scores['sample'] = transposed_expr.index
    pca_scores = pca_scores.merge(meta, on='sample')
    pca_scores['condition'] = pd.Categorical(pca_scores['condition'], categories=meta['condition'].unique(), ordered=True)
    figsize = (width_cm / 2.54, height_cm / 2.54)
    if plot_3d:
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_subplot(111, projection='3d')
    else:
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    colors = plot_colors if plot_colors is not None else plt.cm.tab10.colors
    conditions = pca_scores['condition'].unique()
    color_map = {cond: colors[i % len(colors)] for i, cond in enumerate(conditions)}
    for cond in conditions:
        subset = pca_scores[pca_scores['condition'] == cond]
        if plot_3d:
            ax.scatter(subset['PC1'], subset['PC2'], subset['PC3'],
                       label=cond, s=dot_size*10, alpha=0.7, color=color_map[cond])
        else:
            ax.scatter(subset['PC1'], subset['PC2'],
                       label=cond, s=dot_size*10, alpha=0.7, color=color_map[cond])
            if add_ellipses and len(subset) > 2:
                points = subset[['PC1', 'PC2']].to_numpy()
                center, axes, angle = minimum_enclosing_ellipse(points)
                ellipse = Ellipse(xy=center, width=2*axes[0], height=2*axes[1],
                                  angle=angle, facecolor=color_map[cond], alpha=0.15,
                                  edgecolor=color_map[cond], lw=1)
                ax.add_patch(ellipse)
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
    annotated_columns = meta["sample"].tolist()
    data_filtered = data.loc[:, annotated_columns].dropna()
    transposed_expr = data_filtered.T
    transposed_expr = transposed_expr.loc[:, transposed_expr.var(axis=0) > 0]
    n_components = 3 if plot_3d else 2
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
                zaxis=dict(title=f"PC3 - {explained_variance[2]:.2f}%")
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
            for i, cond in enumerate(pca_scores["condition"].unique()):
                subset = pca_scores[pca_scores["condition"] == cond]
                if len(subset) > 2:
                    points = subset[["PC1","PC2"]].to_numpy()
                    center, axes, angle = minimum_enclosing_ellipse(points)
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
    fig.update_layout(**layout_kwargs)
    return fig


def abundance_plot(data, meta, workflow="Protein", plot_colors=None, width_cm=20, height_cm=10, dpi=300,
                   legend=True, header=True):
    data = data.replace(0, np.nan)
    unique_conditions = meta['condition'].unique()

    if plot_colors is not None:
        if len(plot_colors) < len(unique_conditions):
            reps = int(np.ceil(len(unique_conditions) / len(plot_colors)))
            plot_colors = (plot_colors * reps)[:len(unique_conditions)]
    else:
        plot_colors = plt.cm.get_cmap('tab10').colors[:len(unique_conditions)]

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
        means_log = np.log10(means + 1)
        mean_intensities[condition] = means_log

    if mean_intensities.shape[1] > 2:
        mean_intensities = mean_intensities[
            mean_intensities.iloc[:, 1:].isna().sum(axis=1) < mean_intensities.shape[1] - 2
        ]
    else:
        mean_intensities = mean_intensities.dropna(subset=[mean_intensities.columns[1]])

    long_intensities = mean_intensities.melt(
        id_vars=[key_col], var_name="Condition", value_name="log10Intensity"
    )
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
    ax.set_ylabel(f"log10 {workflow} Intensity")

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


def interactive_abundance_plot(data, meta, condition, workflow="Protein", search=None, max_ptms=5):
    data = data.replace(0, np.nan)
    annotated_columns = meta.loc[meta["condition"] == condition, "sample"].tolist()

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
    condition_means = np.log10(condition_means + 1)

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
        yaxis_title=f"log10 {workflow} Intensity",
        showlegend=False
    )

    return fig


def corr_plot(data, meta, method="Matrix", id=True, full_range=False, width=10, height=8, dpi=100):
    meta = meta.copy()
    meta['sample'] = meta['sample'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    if id:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})", axis=1)
    else:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(lambda row: f"{row['condition']}_{row['new_sample']}", axis=1)

    rename_map = dict(zip(meta['sample'], meta['new_sample']))
    data = data.rename(columns=rename_map)

    annotated_columns = meta['new_sample'].tolist()
    data_filtered = data[annotated_columns]

    correlation_matrix = data_filtered.corr(method='pearson')
    distance_matrix = 1 - correlation_matrix
    linkage_matrix = linkage(squareform(distance_matrix), method='complete')
    ordered_indices = leaves_list(linkage_matrix)
    ordered_corr = correlation_matrix.iloc[ordered_indices, ordered_indices]

    vmin, vmax = (-1, 1) if full_range else (ordered_corr.min().min(), ordered_corr.max().max())

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    if method == "Matrix":
        cax = ax.matshow(ordered_corr, cmap='coolwarm', vmin=vmin, vmax=vmax)
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

    plt.tight_layout()
    return fig


#STATISTIC FUNCTIONS
def volcano_data_f(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                   workflow="Protein", paired="Unpaired", uncorrected=False):
    if workflow == "Protein":
        label_col = "ProteinNames"
    elif workflow == "Phosphosite":
        label_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        label_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()
    cols_to_use = [label_col] + annotated_columns1 + annotated_columns2

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].replace(0, np.nan).copy()
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
    log2fc = mean2 - mean1

    if paired == "Unpaired":
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
        t_stat = log2fc / se
        dfree = n1 + n2 - 2
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        diffs = arr_y - arr_x
        min_len = np.minimum(n1, n2)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(min_len)
        t_stat = mean_diff / se_diff
        pvals = 2 * t.sf(np.abs(t_stat), min_len - 1)

    adj_pvals = pvals if uncorrected else multipletests(pvals, method='fdr_bh')[1]

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(adj_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    result = {
        label_col: df[label_col].values,
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "significance": significance,
        "neg_log10_adj_pval": -np.log10(adj_pvals)
    }

    if workflow == "Phosphoprotein":
        if "site_num" in df.columns:
            result["site_num"] = df["site_num"].values
        if "PTM_Collapse_keys" in df.columns:
            result["PTM_Collapse_keys"] = df["PTM_Collapse_keys"].values

    return pd.DataFrame(result)


def volcano_data_f_control(data, meta, condition1, condition2, condition1_control, condition2_control,
    in_pval=0.05, in_log2fc=1, workflow="Protein", paired="Unpaired", uncorrected=False):
    if workflow == "Protein":
        label_col = "ProteinNames"
    elif workflow == "Phosphosite":
        label_col = "PTM_Collapse_key"
    elif workflow == "Phosphoprotein":
        label_col = "Phosphoprotein"
    else:
        raise ValueError("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'")

    c1_cols = meta.loc[meta["condition"] == condition1, "sample"].tolist()
    c2_cols = meta.loc[meta["condition"] == condition2, "sample"].tolist()
    c1_ctrl_cols = meta.loc[meta["condition"] == condition1_control, "sample"].tolist()
    c2_ctrl_cols = meta.loc[meta["condition"] == condition2_control, "sample"].tolist()

    if not c1_cols or not c2_cols:
        raise ValueError("No samples found for condition1 and/or condition2 in meta.")
    if not c1_ctrl_cols or not c2_ctrl_cols:
        raise ValueError("No samples found for condition1_control and/or condition2_control in meta.")

    cols_to_use = [label_col] + c1_cols + c2_cols + c1_ctrl_cols + c2_ctrl_cols

    if workflow == "Phosphoprotein":
        extra_cols = []
        if "site_num" in data.columns:
            extra_cols.append("site_num")
        if "PTM_Collapse_keys" in data.columns:
            extra_cols.append("PTM_Collapse_keys")
        cols_to_use += extra_cols

    df = data[cols_to_use].replace(0, np.nan).copy()

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

    df = df.loc[valid_mask]
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask]
    n2 = n2_real[valid_mask]

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean2 - mean1

    if paired == "Unpaired":
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
        t_stat = log2fc / se
        dfree = n1 + n2 - 2
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        if arr_x.shape[1] != arr_y.shape[1]:
            raise ValueError(
                "paired != 'Unpaired' requires same number of samples in condition1 and condition2 "
                "(and matching order)."
            )
        diffs = arr_y - arr_x
        n_diff = np.sum(~np.isnan(diffs), axis=1)
        valid_paired = n_diff >= 2

        if not np.all(valid_paired):
            df = df.loc[valid_paired]
            diffs = diffs[valid_paired]
            log2fc = log2fc[valid_paired]
            n_diff = n_diff[valid_paired]

        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(n_diff)
        t_stat = mean_diff / se_diff
        pvals = 2 * t.sf(np.abs(t_stat), n_diff - 1)

    adj_pvals = pvals if uncorrected else multipletests(pvals, method="fdr_bh")[1]

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(adj_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    result = {
        label_col: df[label_col].values,
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "significance": significance,
        "neg_log10_adj_pval": -np.log10(adj_pvals),
    }

    if workflow == "Phosphoprotein":
        if "site_num" in df.columns:
            result["site_num"] = df["site_num"].values
        if "PTM_Collapse_keys" in df.columns:
            result["PTM_Collapse_keys"] = df["PTM_Collapse_keys"].values

    return pd.DataFrame(result)


def volcano_plot(volcano_df, condition1, condition2, in_pval=0.05, in_log2fc=1, uncorrected=False, max_chars=100):
    color_mapping = {'Downregulated': 'blue', 'Not significant': 'gray', 'Upregulated': 'red'}
    y_hline = -np.log10(in_pval)
    max_y = max(y_hline, volcano_df['neg_log10_adj_pval'].max())

    shapes = [
        dict(type="line", x0=in_log2fc, x1=in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=-in_log2fc, x1=-in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=volcano_df['log2FC'].min(), x1=volcano_df['log2FC'].max(),
             y0=y_hline, y1=y_hline, line=dict(color="black", dash="dash"))
    ]

    if 'Phosphoprotein' in volcano_df.columns:
        label_col = 'Phosphoprotein'
        site_col = 'site_num' if 'site_num' in volcano_df.columns else None
        ptm_col = 'PTM_Collapse_keys' if 'PTM_Collapse_keys' in volcano_df.columns else None
    elif 'ProteinNames' in volcano_df.columns:
        label_col = 'ProteinNames'
        site_col = ptm_col = None
    else:
        label_col = 'PTM_Collapse_key'
        site_col = ptm_col = None

    fig = go.Figure()
    for sig, color in color_mapping.items():
        subset = volcano_df[volcano_df['significance'] == sig]

        if label_col == 'Phosphoprotein':
            hover_text = subset[label_col].astype(str)
            if site_col is not None:
                hover_text += " (" + subset[site_col].astype(str) + " sites)"
            if ptm_col is not None:
                truncated_ptm = subset[ptm_col].astype(str).apply(
                    lambda x: x if len(x) <= max_chars else x[:max_chars] + " ..."
                )
                hover_text += "<br>" + truncated_ptm
        else:
            hover_text = subset[label_col].astype(str)

        fig.add_trace(go.Scatter(
            x=subset['log2FC'],
            y=subset['neg_log10_adj_pval'],
            mode='markers',
            marker=dict(color=color, size=5),
            text=hover_text,
            name=sig,
            hoverinfo='text'
        ))

    fig.update_layout(
        title=f"{condition1} vs {condition2}",
        xaxis_title=f"log2 fold change ({condition2} - {condition1})",
        yaxis_title='-log10 adj. p-value' if not uncorrected else '-log10 p-value',
        shapes=shapes,
        hovermode='closest'
    )
    return fig


def volcano_plot_h(volcano_df, condition1, condition2,
                   in_pval=0.05, in_log2fc=1, uncorrected=False,
                   highlight_terms=None, max_chars=100):

    if highlight_terms is not None and not isinstance(highlight_terms, list):
        highlight_terms = [highlight_terms]

    def normalize_name(name):
        return str(name).split('_')[0].lower()

    highlight_terms_norm = [normalize_name(t) for t in highlight_terms] if highlight_terms else []

    color_mapping = {'Downregulated': 'blue', 'Not significant': 'gray', 'Upregulated': 'red'}
    y_hline = -np.log10(in_pval)
    max_y = max(y_hline, volcano_df['neg_log10_adj_pval'].max())

    shapes = [
        dict(type="line", x0=in_log2fc, x1=in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=-in_log2fc, x1=-in_log2fc, y0=0, y1=max_y, line=dict(color="black", dash="dash")),
        dict(type="line", x0=volcano_df['log2FC'].min(), x1=volcano_df['log2FC'].max(),
             y0=y_hline, y1=y_hline, line=dict(color="black", dash="dash"))
    ]

    if 'Phosphoprotein' in volcano_df.columns:
        label_col = 'Phosphoprotein'
        site_col = 'site_num' if 'site_num' in volcano_df.columns else None
        ptm_col = 'PTM_Collapse_keys' if 'PTM_Collapse_keys' in volcano_df.columns else None
    elif 'ProteinNames' in volcano_df.columns:
        label_col = 'ProteinNames'
        site_col = ptm_col = None
    else:
        label_col = 'PTM_Collapse_key'
        site_col = ptm_col = None

    def build_hover(df_subset):
        hover = df_subset[label_col].astype(str)

        if label_col == 'Phosphoprotein':
            if site_col:
                hover += " (" + df_subset[site_col].astype(str) + " sites)"
            if ptm_col:
                trunc = df_subset[ptm_col].astype(str).apply(
                    lambda x: x if len(x) <= max_chars else x[:max_chars] + " ..."
                )
                hover += "<br>" + trunc

        return hover

    fig = go.Figure()

    for sig, color in color_mapping.items():
        subset = volcano_df[volcano_df['significance'] == sig].copy()

        if highlight_terms_norm:
            subset['highlight'] = subset[label_col].apply(
                lambda x: any(n in highlight_terms_norm for n in [normalize_name(y) for y in str(x).split(';')])
            )
            subset_high = subset[subset['highlight']]
            subset_norm = subset[~subset['highlight']]
        else:
            subset_high = pd.DataFrame(columns=subset.columns)
            subset_norm = subset

        if len(subset_norm) > 0:
            fig.add_trace(go.Scatter(
                x=subset_norm['log2FC'],
                y=subset_norm['neg_log10_adj_pval'],
                mode='markers',
                marker=dict(color=color, size=5),
                text=build_hover(subset_norm),
                name=sig,
                hoverinfo='text'
            ))

        if len(subset_high) > 0:
            fig.add_trace(go.Scatter(
                x=subset_high['log2FC'],
                y=subset_high['neg_log10_adj_pval'],
                mode='markers',
                marker=dict(color=color, size=8, line=dict(color='lime', width=3)),
                text=build_hover(subset_high),
                name=f"{sig} (highlighted)",
                hoverinfo='text'
            ))

    fig.update_layout(
        title=f"{condition1} vs {condition2}",
        xaxis_title=f"log2 fold change ({condition2} - {condition1})",
        yaxis_title='-log10 adj. p-value' if not uncorrected else '-log10 p-value',
        shapes=shapes,
        hovermode='closest'
    )

    return fig


gp = GProfiler(return_dataframe=True) if GProfiler is not None else None

def different_genes(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                    workflow="Gene", paired="Unpaired", uncorrected=False):
    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()

    key_col = 'GeneNames'

    cols_to_use = [key_col] + annotated_columns1 + annotated_columns2
    data_filtered = data[cols_to_use].copy()
    threshold = len(annotated_columns1) + len(annotated_columns2) - 2
    data_filtered = data_filtered[data_filtered.iloc[:, 1:].isna().sum(axis=1) < threshold]

    log2fc_list = []
    pvals_list = []

    for idx, row in data_filtered.iterrows():
        values1 = row[annotated_columns1].dropna().astype(float)
        values2 = row[annotated_columns2].dropna().astype(float)

        if paired == "Unpaired":
            if len(values1) < 2 or len(values2) < 2:
                log2fc_list.append(np.nan)
                pvals_list.append(np.nan)
                continue
            log2fc_list.append(values2.mean() - values1.mean())
            pvals_list.append(ttest_ind(values2, values1, equal_var=True).pvalue)

        elif paired == "Paired":
            paired_values = pd.concat([values1, values2], axis=1).dropna()
            if paired_values.shape[0] < 1:
                log2fc_list.append(np.nan)
                pvals_list.append(np.nan)
                continue
            log2fc_list.append(paired_values.iloc[:, 1].mean() - paired_values.iloc[:, 0].mean())
            if paired_values.shape[0] < 2:
                pvals_list.append(np.nan)
            else:
                pvals_list.append(ttest_rel(paired_values.iloc[:, 1], paired_values.iloc[:, 0]).pvalue)

    mask = ~np.isnan(pvals_list)
    log2fc_array = np.array(log2fc_list)[mask]
    pvals_array = np.array(pvals_list)[mask]
    data_filtered = data_filtered.iloc[mask, :]

    if uncorrected:
        adj_pvals = pvals_array
    else:
        adj_pvals = multipletests(pvals_array, method='fdr_bh')[1]

    result_data = pd.DataFrame({
        'Gene': data_filtered[key_col],
        'log2FC': log2fc_array,
        'pval': pvals_array,
        'adj_pval': adj_pvals
    })

    up_genes = result_data.loc[
        (result_data['adj_pval'] < in_pval) & (result_data['log2FC'] > in_log2fc), 'Gene'
    ].apply(lambda x: x.split(";")[0]).tolist()

    down_genes = result_data.loc[
        (result_data['adj_pval'] < in_pval) & (result_data['log2FC'] < -in_log2fc), 'Gene'
    ].apply(lambda x: x.split(";")[0]).tolist()

    return {'Upregulated': up_genes, 'Downregulated': down_genes}


def enrichment_analysis(gene_list, top_n=10, min_num=20, max_num=300):
    gene_list = [g for g in gene_list if g]
    if not gene_list:
        return None

    res = gp.profile(
        organism='hsapiens',
        query=gene_list,
        sources=['GO:BP', 'GO:CC', 'GO:MF'],
        user_threshold=0.05,
        significance_threshold_method='g_SCS'
    )

    if res.empty:
        return None

    res = res[(res['term_size'] >= min_num) & (res['term_size'] <= max_num)].copy()
    res = res.sort_values('p_value').head(top_n)

    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        x=res['intersection_size'] / res['term_size'] * 100,
        y=res['name'],
        s=res['intersection_size']*10,
        c=-np.log10(res['p_value']),
        cmap='RdBu_r'
    )

    ax.set_xlabel('Hits (%)')
    ax.set_ylabel('GO Term')
    ax.set_title('Gene Set Enrichment Analysis')

    cbar = fig.colorbar(scatter, ax=ax, pad=0.15)
    cbar.set_label('-log10(p-value)')

    plt.tight_layout()
    return fig


def load_go_db():
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    db_file = os.path.join(base_path, "data", "db", "all_go_terms_genes.csv")
    return pd.read_csv(db_file)


def proteins_in_pathway(
        data, meta, db, pathway, conditions=None,
        figsize=(12, 8), cmap_name='plasma',
        remove_empty=True,
        cluster_rows=False,
        cluster_cols=False,
        value_type="z",
        header=True,
        id=True
):
    pathway_row = db[db['description'].str.lower() == pathway.lower()]
    if pathway_row.empty:
        raise ValueError(f"No pathway found exactly matching '{pathway}' in db")

    genes_str = pathway_row['genes'].values[0]
    genes = [g.strip() for g in genes_str.split(';') if g.strip()]
    genes_lower = [g.lower() for g in genes]

    data = data.copy()
    data['GeneNames_lower'] = data['GeneNames'].str.lower()

    if conditions is not None:
        meta_filtered = meta[meta['condition'].isin(conditions)].copy()
    else:
        meta_filtered = meta.copy()

    meta_filtered['sample'] = meta_filtered['sample'].astype(str)
    if 'id' not in meta_filtered.columns:
        meta_filtered['id'] = meta_filtered['sample'].str.extract(r'(\d+)$')
    meta_filtered['index'] = meta_filtered.groupby('condition').cumcount() + 1

    if id:
        meta_filtered['new_sample'] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['index']}\n({row['id']})",
            axis=1
        )
    else:
        meta_filtered['new_sample'] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['index']}",
            axis=1
        )

    rename_dict = dict(zip(meta_filtered['sample'], meta_filtered['new_sample']))
    sample_cols = list(meta_filtered['sample'])

    heatmap_data = pd.DataFrame(np.nan, index=genes, columns=sample_cols)

    available_data = data[data['GeneNames_lower'].isin(genes_lower)]

    if not available_data.empty:
        for gene, gene_l in zip(genes, genes_lower):
            row = available_data[available_data['GeneNames_lower'] == gene_l]
            if not row.empty:
                for col in sample_cols:
                    if col in row.columns:
                        heatmap_data.at[gene, col] = row[col].values[0]

    if remove_empty:
        heatmap_data = heatmap_data.dropna(how="all")

    if heatmap_data.empty:
        raise ValueError("No matching gene data available for the selected pathway.")

    value_type = value_type.lower()

    if value_type == "z":
        def z_transform(row):
            mean = row.mean(skipna=True)
            std = row.std(skipna=True)
            if std == 0 or np.isnan(std):
                return row * np.nan
            return (row - mean) / std
        heatmap_data = heatmap_data.apply(z_transform, axis=1)
        cbar_label = "Z-score"
    elif value_type == "log2":
        cbar_label = "log2 Intensity"
    else:
        raise ValueError("value_type must be 'z' or 'log2'")

    heatmap_data = heatmap_data.rename(columns=rename_dict)
    ordered_labels = list(meta_filtered['new_sample'])
    heatmap_data = heatmap_data[ordered_labels]

    if cluster_rows and heatmap_data.shape[0] > 1:
        row_linkage = linkage(heatmap_data.fillna(0), method='average', metric='euclidean')
        row_order = leaves_list(row_linkage)
        heatmap_data = heatmap_data.iloc[row_order]

    if cluster_cols and heatmap_data.shape[1] > 1:
        col_linkage = linkage(heatmap_data.T.fillna(0), method='average', metric='euclidean')
        col_order = leaves_list(col_linkage)
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(
        heatmap_data,
        cmap=plt.get_cmap(cmap_name),
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
    ax.set_title(f"{pathway} ({title_suffix})", fontsize=14)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Protein / Gene" if header else "")
    fig.tight_layout()

    return fig


def volcano_plot_sim(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1,
                     workflow="Protein", mod_var=1, mod_n=0):
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
    t_stat = (mean2 - mean1) / se
    df = n1 + n2 - 2
    pvals = 2 * t.sf(np.abs(t_stat), df)
    adj_pvals = multipletests(pvals, method='fdr_bh')[1]
    log2fc = mean2 - mean1
    significance = np.where((adj_pvals < in_pval) & (log2fc > in_log2fc), "Upregulated",
                            np.where((adj_pvals < in_pval) & (log2fc < -in_log2fc), "Downregulated",
                                     "Not significant"))
    volcano_data = pd.DataFrame({
        'Feature': data_filtered[label_col],
        'log2FC': log2fc,
        'pval': pvals,
        'adj_pval': adj_pvals,
        'significance': significance
    })
    volcano_data['neg_log10_pval'] = -np.log10(volcano_data['adj_pval'])
    color_mapping = {"Downregulated": "blue", "Not significant": "gray", "Upregulated": "red"}
    fig = px.scatter(
        volcano_data,
        x='log2FC',
        y='neg_log10_pval',
        color='significance',
        hover_data=['Feature'],
        color_discrete_map=color_mapping,
        title=f"{condition1} vs. {condition2}",
    )
    vline_height = max(volcano_data['neg_log10_pval'].max(), -np.log10(in_pval))
    fig.add_shape(type="line", x0=in_log2fc, x1=in_log2fc, y0=0, y1=vline_height,
                  line=dict(dash='dash', color='black'))
    fig.add_shape(type="line", x0=-in_log2fc, x1=-in_log2fc, y0=0, y1=vline_height,
                  line=dict(dash='dash', color='black'))
    fig.add_shape(type="line", x0=volcano_data['log2FC'].min(), x1=volcano_data['log2FC'].max(),
                  y0=-np.log10(in_pval), y1=-np.log10(in_pval),
                  line=dict(dash='dash', color='black'))
    fig.update_layout(
        xaxis_title=f"log2 fold change ({condition2} - {condition1})",
        yaxis_title="-log10 adj. p-value",
        hovermode='closest'
    )
    return fig


def convert_to_centered(seq: str) -> str | None:
    match = re.search(r"\*", seq)
    if not match:
        return None
    star_index = match.start()
    if star_index == 0:
        return None
    mod_residue = seq[star_index - 1].upper()
    clean_seq = seq[:star_index - 1] + mod_residue + seq[star_index + 1:]
    mod_pos = star_index - 1
    left = clean_seq[:mod_pos]
    right = clean_seq[mod_pos + 1:]
    left_tail = left[-6:] if len(left) >= 6 else "_" * (6 - len(left)) + left
    right_tail = right[:6] if len(right) >= 6 else right + "_" * (6 - len(right))
    return f"_{left_tail}{mod_residue}{right_tail}_"


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
    left_tail = left[-6:] if len(left) >= 6 else "_" * (6 - len(left)) + left
    right_tail = right[:6] if len(right) >= 6 else right + "_" * (6 - len(right))
    return f"_{left_tail}{mod_residue}{right_tail}_"


def ksea_data_f(data, meta, condition1, condition2,
                in_pval=0.05, in_log2fc=1,
                paired="Unpaired", uncorrected=False):
    label_col = "UPD_seq"

    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()
    cols_to_use = [label_col] + annotated_columns1 + annotated_columns2

    df = data[cols_to_use].replace(0, np.nan).copy()
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
    log2fc = mean2 - mean1

    if paired == "Unpaired":
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
        t_stat = log2fc / se
        dfree = n1 + n2 - 2
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        diffs = arr_y - arr_x
        min_len = np.minimum(n1, n2)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(min_len)
        t_stat = mean_diff / se_diff
        pvals = 2 * t.sf(np.abs(t_stat), min_len - 1)

    adj_pvals = pvals if uncorrected else multipletests(pvals, method='fdr_bh')[1]

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(adj_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    return pd.DataFrame({
        "UPD_seq": [convert_to_centered(x) for x in df[label_col].values],
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "significance": significance,
        "neg_log10_adj_pval": -np.log10(adj_pvals)
    })


def phosprot_regulation(data: pd.DataFrame, meta: pd.DataFrame,
                        condition1: str, condition2: str,
                        in_pval: float = 0.05, in_log2fc: float = 1,
                        paired: str = "Unpaired", uncorrected: bool = False,
                        max_hover_sites: int = 20,
                        show_phosphosites: bool = True):
    label_col = "PTM_Collapse_key"
    annotated_columns1 = meta.loc[meta['condition'] == condition1, 'sample'].tolist()
    annotated_columns2 = meta.loc[meta['condition'] == condition2, 'sample'].tolist()

    df = data[[label_col, "Protein_group"] + annotated_columns1 + annotated_columns2].replace(0, np.nan).copy()
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
    log2fc = mean2 - mean1

    if paired == "Unpaired":
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        se = np.sqrt(pooled_var * (1 / n1 + 1 / n2))
        t_stat = log2fc / se
        dfree = n1 + n2 - 2
        pvals = 2 * t.sf(np.abs(t_stat), dfree)
    else:
        diffs = arr_y - arr_x
        min_len = np.minimum(n1, n2)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(min_len)
        t_stat = mean_diff / se_diff
        pvals = 2 * t.sf(np.abs(t_stat), min_len - 1)

    adj_pvals = pvals if uncorrected else multipletests(pvals, method='fdr_bh')[1]

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < in_pval) & (log2fc > in_log2fc)] = "Upregulated"
    significance[(adj_pvals < in_pval) & (log2fc < -in_log2fc)] = "Downregulated"

    volcano_df = pd.DataFrame({
        "Protein_group": df["Protein_group"].values,
        label_col: df[label_col].values,
        "log2FC": log2fc,
        "pval": pvals,
        "adj_pval": adj_pvals,
        "significance": significance
    })

    collapsed_results = []
    all_samples = annotated_columns1 + annotated_columns2

    for prot, group in volcano_df.groupby("Protein_group"):
        down_mask = group["log2FC"] < 0
        up_mask = group["log2FC"] > 0
        down_sites = group.loc[down_mask, label_col].astype(str).tolist()
        up_sites = group.loc[up_mask, label_col].astype(str).tolist()
        down_vals = data.loc[data[label_col].isin(down_sites), all_samples].fillna(0) if down_sites else pd.DataFrame()
        up_vals = data.loc[data[label_col].isin(up_sites), all_samples].fillna(0) if up_sites else pd.DataFrame()
        down_sum = np.log2(down_vals.sum(axis=1).sum()) if not down_vals.empty and down_vals.sum().sum() > 0 else 0
        up_sum = np.log2(up_vals.sum(axis=1).sum()) if not up_vals.empty and up_vals.sum().sum() > 0 else 0

        def truncate_sites(sites):
            if len(sites) > max_hover_sites:
                return ";".join(sites[:max_hover_sites]) + f";... (+{len(sites) - max_hover_sites} more)"
            return ";".join(sites)

        collapsed_results.append({
            "Protein_group": prot,
            "Downregulated_sites": truncate_sites(down_sites) if show_phosphosites else "",
            "Upregulated_sites": truncate_sites(up_sites) if show_phosphosites else "",
            "Downregulated_count": len(down_sites),
            "Upregulated_count": len(up_sites),
            "Downregulated_sum": down_sum,
            "Upregulated_sum": up_sum
        })

    collapsed_df = pd.DataFrame(collapsed_results)
    collapsed_df["x"] = collapsed_df["Upregulated_sum"].abs()
    collapsed_df["y"] = collapsed_df["Downregulated_sum"].abs()
    collapsed_df["color_val"] = collapsed_df["x"] - collapsed_df["y"]

    fig = px.scatter(
        collapsed_df,
        x="x",
        y="y",
        hover_data={
            "Protein_group": True,
            "Upregulated_count": True,
            "Downregulated_count": True,
            "Upregulated_sites": True,
            "Downregulated_sites": True
        },
        color="color_val",
        color_continuous_scale=[(0, "blue"), (0.5, "grey"), (1, "red")],
        labels={
            "x": "Absolute Upregulated Sum (log2)",
            "y": "Absolute Downregulated Sum (log2)"
        },
        opacity=0.7
    )

    fig.update_traces(marker=dict(size=8, line=dict(width=0.5, color='DarkSlateGrey')), text=None)

    fig.update_layout(title="Protein-level Phosphosite Regulation",
                      xaxis_title="Absolute Upregulated Sum (log2)",
                      yaxis_title="Absolute Downregulated Sum (log2)",
                      template="plotly_white",
                      coloraxis_colorbar=dict(title="Up - Down"))

    return fig


#PEPTIDE
def rt_vs_pred_rt_plot(data_path, method="Hexbin Plot", add_line=False, bins=1000, header=True, width=8, height=6, dpi=100):
    data = read_data(data_path)

    x = data['Predicted.RT']
    y = data['RT']

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)

    if method == "Scatter Plot":
        if len(data) > 100000:
            data = data.sample(n=100000, random_state=69)
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

    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    meta["id"] = meta["sample"].apply(extract_id_or_number).astype(str)
    cnt = meta.groupby("condition").cumcount() + 1

    if id:
        meta["new_sample"] = meta["condition"] + "_" + cnt.astype(str) + "\n(" + meta["id"] + ")"
    else:
        meta["new_sample"] = meta["condition"] + "_" + cnt.astype(str)

    rename_dict = dict(zip(meta["id"], meta["new_sample"]))
    data2_wide = data2_wide.rename(columns=rename_dict)
    ordered_new_samples = list(meta["new_sample"])
    annotated_cols = [c for c in ordered_new_samples if c in data2_wide.columns]
    data_filtered = data2_wide[["Modified.Sequence"] + annotated_cols].copy()

    def get_mod_count(df, pattern):
        df_mod = df[df["Modified.Sequence"].str.contains(pattern, na=False)].copy()
        for col in df_mod.columns[1:]:
            df_mod[col] = df_mod[col].notna().astype(int)
        return df_mod.iloc[:, 1:].sum(axis=0)

    col_carb = get_mod_count(data_filtered, "UniMod:4|Carbamidomethyl")
    col_oxi  = get_mod_count(data_filtered, "UniMod:35|Oxidation")
    col_ace  = get_mod_count(data_filtered, "UniMod:1|Acetyl")

    plot_data = pd.DataFrame({
        "Sample": list(col_carb.index) * 3,
        "Count": list(col_carb.values) + list(col_oxi.values) + list(col_ace.values),
        "Modification": (["Carbamylation"] * len(col_carb)) +
                        (["Oxidation"] * len(col_oxi)) +
                        (["Acetylation"] * len(col_ace))
    })

    plot_data = plot_data[plot_data["Count"] > 0]
    plot_data["Sample"] = pd.Categorical(plot_data["Sample"], categories=ordered_new_samples, ordered=True)
    plot_data = plot_data.sort_values("Sample")

    mod_colors = {
        "Carbamylation": "blue",
        "Oxidation": "red",
        "Acetylation": "green"
    }

    found_mods = [m for m in ["Carbamylation", "Oxidation", "Acetylation"] if m in plot_data["Modification"].unique()]

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
                         width=10, height=6, dpi=100):

    data2 = sanitize_dataframe(read_data(data2_path)).copy()
    meta = meta.copy()

    file_col = [c for c in data2.columns if 'file' in c.lower()][0]
    seq_col = [c for c in data2.columns if 'stripped' in c.lower() and 'sequence' in c.lower()][0]

    data2_names = data2[file_col].unique()
    for name in data2_names:
        meta['sample'] = np.where(meta['sample'] == name, name, meta['sample'])

    df_wide = data2.pivot_table(
        index=file_col,
        columns=seq_col,
        values="Precursor.Quantity",
        aggfunc="max"
    ).T.reset_index()

    df_wide.rename(columns={"index": seq_col}, inplace=True)
    df_wide.columns = [extract_id_or_number(c) if c != seq_col else c for c in df_wide.columns]

    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].apply(extract_id_or_number)

    if id:
        meta["new_sample"] = meta.groupby("condition").cumcount() + 1
        meta["new_sample"] = (
            meta["condition"].astype(str) + "_" +
            meta["new_sample"].astype(str) + "\n(" +
            meta["id"].astype(str) + ")"
        )
    else:
        meta["new_sample"] = meta.groupby("condition").cumcount() + 1
        meta["new_sample"] = meta["condition"].astype(str) + "_" + meta["new_sample"].astype(str)

    rename_dict = dict(zip(meta["id"], meta["new_sample"]))
    df_wide = df_wide.rename(columns=rename_dict)

    annotated_cols = [c for c in meta["new_sample"] if c in df_wide.columns]
    data_filtered = df_wide[[seq_col] + annotated_cols]

    def count_all_RK(sequence):
        return max(0, sequence.count("R") + sequence.count("K") - 1)

    rk_counts = [count_all_RK(seq) for seq in data_filtered[seq_col]]
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

    ax.set_ylabel("Percentage of peptides with missed cleavage (%)")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())

    if header:
        ax.set_title("Missed cleavages per sample")

    ax.set_xticks(range(len(samples_order)))
    ax.set_xticklabels(samples_order, rotation=90)

    if text:
        single = summary[summary["Count"] == 1].set_index("Sample").reindex(samples_order)["Percentage"].fillna(0)
        base_y = bottom.max() * 0.03
        for i, val in enumerate(single):
            ax.text(i, base_y, f"{val:.1f}%", ha="center", va="bottom", fontsize=text_size)

    ax.legend(title="Number", bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    return fig


def calculate_coverage(data_path, db, protein):
    data = read_data(data_path).copy()

    peptides = data[data["ProteinNames"].str.contains(rf"\b{re.escape(protein)}\b", regex=True)][
        "Stripped.Sequence"].unique()

    try:
        sequence_row = db.loc[db["name"] == protein, "V1"]
        if sequence_row.empty:
            raise KeyError
        sequence = sequence_row.values[0]
    except KeyError:
        raise ValueError(f"No sequence found in the selected database for protein: {protein}")

    coverage_mask = [0] * len(sequence)
    for pep in peptides:
        for match in re.finditer(re.escape(pep), sequence):
            start, end = match.start(), match.end()
            for i in range(start, end):
                coverage_mask[i] = 1

    return round((sum(coverage_mask) / len(sequence)) * 100, 2)


def vis_coverage(data: pd.DataFrame, db: pd.DataFrame, protein: str, chunk_size: int = 30) -> str:
    data = data[data['ProteinNames'].str.contains(rf"\b{re.escape(protein)}\b", regex=True)]
    found_seq = data['Stripped.Sequence'].unique()

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
        for match in re.finditer(re.escape(pep), sequence):
            start_pos, end_pos = match.start(), match.end()
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
    meta["sample"] = meta["sample"].astype(str)

    sample_index = meta.groupby("condition").cumcount() + 1
    if id:
        meta["new_sample"] = (
            meta["condition"].astype(str)
            + "_"
            + sample_index.astype(str)
            + "\n("
            + meta["sample"].astype(str)
            + ")"
        )
    else:
        meta["new_sample"] = meta["condition"].astype(str) + "_" + sample_index.astype(str)

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

    data_melted = data_melted.merge(meta[["new_sample", "condition"]],
                                    left_on="Sample", right_on="new_sample", how="left").dropna()

    ordered_samples = []
    for cond in conditions:
        ordered_samples.extend(meta.loc[meta["condition"] == cond, "new_sample"].tolist())

    sample_to_x = {s: i for i, s in enumerate(ordered_samples)}
    data_melted["x"] = data_melted["Sample"].map(sample_to_x)

    if workflow == "Protein":
        data_melted[key_col] = data_melted[key_col].apply(lambda x: x.split(";")[0])

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


def boxplot_int_single_prot(data, meta, protein, outliers=False, dots=False, header=True, legend=True,
                       plot_colors=None, width=8, height=6, dpi=100):
    meta = meta.copy()
    data = data.copy()
    data = data[data.index == protein]
    if data.empty:
        raise ValueError(f"No data found for protein: {protein}")

    sample_index = meta.groupby("condition").cumcount() + 1
    meta["new_sample"] = meta["condition"].astype(str) + "_" + sample_index.astype(str)

    rename_vector = dict(zip(meta["sample"], meta["new_sample"]))
    data.rename(columns=rename_vector, inplace=True)
    annotated_columns = meta["new_sample"].tolist()
    data_filtered = data.loc[:, annotated_columns]

    if plot_colors is None:
        plot_colors = plt.cm.tab10.colors

    intensities = []
    labels = []
    colors = []
    plotted_conditions = []
    condition_colors = {cond: plot_colors[i % len(plot_colors)] for i, cond in enumerate(meta['condition'].unique())}

    for condition in meta["condition"].unique():
        cols = meta.loc[meta["condition"] == condition, "new_sample"]
        if len(cols) < 3:
            continue
        vals = data_filtered[cols].values.flatten()
        vals = vals[~pd.isna(vals)]
        if len(vals) == 0:
            continue
        intensities.append(vals)
        labels.append(condition)
        colors.append(condition_colors[condition])
        plotted_conditions.append(condition)

    if not intensities:
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        ax.text(0.5, 0.5, "No conditions with ≥3 samples", ha="center", va="center")
        ax.axis("off")
        return fig

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    bplots = ax.boxplot(intensities, patch_artist=True, showfliers=outliers)
    for patch, color in zip(bplots['boxes'], colors):
        patch.set_facecolor(color)

    if dots:
        for i, (vals, cond) in enumerate(zip(intensities, plotted_conditions), start=1):
            q1, q3 = np.percentile(vals, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            non_outliers = vals[(vals >= lower) & (vals <= upper)]
            x_jitter = np.random.normal(i, 0.05, size=len(non_outliers))
            ax.scatter(x_jitter, non_outliers, color=condition_colors[cond], alpha=0.7, s=15, zorder=3)

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=45, ha='right')
    ax.set_xlabel("Condition")
    ax.set_ylabel("log2 Intensity")
    if header:
        display_protein = protein.split(";")[0]
        ax.set_title(f"Measured {display_protein} intensity values (log2)")
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
        header=True
):
    protein_data = data[data['Protein_group'].str.contains(protein, case=False, na=False)]
    if protein_data.empty:
        raise ValueError(f"No data found for protein '{protein}'")

    if conditions is not None:
        meta_filtered = meta[meta['condition'].isin(conditions)].copy()
    else:
        meta_filtered = meta.copy()

    meta_filtered['sample'] = meta_filtered['sample'].astype(str)
    meta_filtered['id'] = meta_filtered['sample'].apply(extract_id_or_number)

    if id:
        meta_filtered['new_sample'] = meta_filtered.groupby('condition').cumcount() + 1
        meta_filtered['new_sample'] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}\n({row['id']})", axis=1
        )
    else:
        meta_filtered['new_sample'] = meta_filtered.groupby('condition').cumcount() + 1
        meta_filtered['new_sample'] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

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
        def z_transform(row):
            mean = row.mean(skipna=True)
            std = row.std(skipna=True)
            if std == 0 or np.isnan(std):
                return row * np.nan
            return (row - mean) / std
        heatmap_data = heatmap_data.apply(z_transform, axis=1)
        cbar_label = "Z-score"
    elif value_type == "log2":
        cbar_label = "log2 Intensity"
    else:
        raise ValueError("value_type must be 'log2' or 'z'")

    if cluster_rows and heatmap_data.shape[0] > 1:
        row_linkage = linkage(heatmap_data.fillna(0), method='average', metric='euclidean')
        row_order = leaves_list(row_linkage)
        heatmap_data = heatmap_data.iloc[row_order]

    if cluster_cols and heatmap_data.shape[1] > 1:
        col_linkage = linkage(heatmap_data.T.fillna(0), method='average', metric='euclidean')
        col_order = leaves_list(col_linkage)
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(
        heatmap_data,
        cmap=plt.get_cmap(cmap_name),
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
def phossite_coverage_plot(
    data, meta, id=False, header=True, legend=True,
    width=20, height=10, dpi=300,
    color_classI="blue", color_notclassI="orange"
):
    conditions = meta["condition"].unique()
    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].apply(lambda x: extract_id_or_number(x))

    if id:
        meta["new_sample"] = meta.groupby("condition").cumcount().astype(str)
        meta["new_sample"] = meta["condition"].astype(str) + "_" + meta["new_sample"] + "\n(" + meta["id"].astype(str) + ")"
    else:
        meta["new_sample"] = meta.groupby("condition").cumcount().astype(str)
        meta["new_sample"] = meta["condition"].astype(str) + "_" + meta["new_sample"]

    rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
    data = data.rename(columns=rename_dict)
    annotated_columns = meta["new_sample"].tolist()

    data_classI = data.loc[data["PTM_localization"] >= 0.75, annotated_columns]
    data_notclassI = data.loc[data["PTM_localization"] < 0.75, annotated_columns]

    count_classI = data_classI.notna().sum()
    count_notclassI = data_notclassI.notna().sum()

    plot_data = pd.DataFrame({
        "sample": annotated_columns * 2,
        "PTM_localization": ["Class I"] * len(annotated_columns) + ["Not Class I"] * len(annotated_columns),
        "count": list(count_classI) + list(count_notclassI)
    })

    plot_data["sample"] = pd.Categorical(plot_data["sample"], categories=meta["new_sample"], ordered=True)

    plot_title = "Phosphosites per sample" if header else ""
    y_label = "Number of phosphosites" if header else "Number"

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    classI_data = plot_data[plot_data["PTM_localization"] == "Class I"]
    notclassI_data = plot_data[plot_data["PTM_localization"] == "Not Class I"]

    x = range(len(annotated_columns))
    bars1 = ax.bar(x, classI_data["count"], color=color_classI, label="Class I")
    bars2 = ax.bar(x, notclassI_data["count"], bottom=classI_data["count"], color=color_notclassI, label="Not Class I")

    ax.set_xticks(x)
    ax.set_xticklabels(meta["new_sample"], rotation=90, fontsize=5)
    ax.set_xlabel("Sample")
    ax.set_ylabel(y_label)
    ax.set_title(plot_title)

    if legend:
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

    plt.tight_layout()
    return fig


def sty_plot(data):
    sty = data["PTM_Collapse_key"].astype(str)
    letter = sty.str.extract(r'~[^_]+_([STY])\d+_')[0]

    counts = letter.value_counts().reindex(["S", "T", "Y"], fill_value=0)
    total = counts.sum()
    perc = (counts / total * 100) if total > 0 else counts.astype(float)

    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=140)

    colors = {"S": "#4C78A8", "T": "#F58518", "Y": "#54A24B"}
    bar_colors = [colors[k] for k in counts.index]

    ax.bar(counts.index, counts.values, color=bar_colors, edgecolor="black", linewidth=0.6)

    ax.set_title("Modified S/T/Y Peptide Counts", pad=10, fontweight="bold")
    ax.set_xlabel("Peptide")
    ax.set_ylabel("Count")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)

    ax2 = ax.twinx()
    ax2.set_ylabel("Percentage (%)")
    ax2.set_ylim(0, 100)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax2.spines["top"].set_visible(False)

    y_max = max(counts.values) if len(counts.values) else 0
    offset = 0.02 * y_max if y_max > 0 else 0.1
    for i, (c, p) in enumerate(zip(counts.values, perc.values)):
        ax.text(i, c + offset, f"{p:.1f}%",
                ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    plt.show()


def phossite_coverage_plot_summary(
    data, meta, header=True, legend=True,
    width=20, height=10, dpi=300,
    color_classI="blue", color_notclassI="orange"
):
    meta = meta.copy()
    meta["sample"] = meta["sample"].astype(str)

    meta["new_sample"] = meta.groupby("condition").cumcount().add(1).astype(str)
    meta["new_sample"] = meta.apply(lambda row: f'{row.condition}_{row["new_sample"]}', axis=1)

    rename_vector = dict(zip(meta["sample"], meta["new_sample"]))
    data = data.copy()
    data.columns = [rename_vector.get(col, col) for col in data.columns]
    annotated_columns = meta["new_sample"]

    data_classI = data[data["PTM_localization"] >= 0.75][annotated_columns]
    data_notclassI = data[data["PTM_localization"] < 0.75][annotated_columns]

    count_classI = data_classI.notna().sum()
    count_notclassI = data_notclassI.notna().sum()

    plot_data = pd.DataFrame({
        "sample": list(annotated_columns) * 2,
        "PTM_localization": ["Class I"] * len(annotated_columns) + ["Not Class I"] * len(annotated_columns),
        "count": list(count_classI) + list(count_notclassI)
    })
    plot_data["condition"] = plot_data["sample"].str.extract(r'(^.*?)_')[0]

    summarized_plot_data = plot_data.groupby(["condition", "PTM_localization"]).agg(
        mean_count=("count", "mean"),
        sd_count=("count", "std")
    ).reset_index()

    plot_title = "Phosphosites per condition" if header else ""
    y_label = "Number of phosphosites" if header else "Number"

    fig, ax = plt.subplots(figsize=(width / 2.54, height / 2.54), dpi=dpi)

    conditions = summarized_plot_data["condition"].unique()
    locs = np.arange(len(conditions))
    width_bar = 0.35

    classI_means = summarized_plot_data[summarized_plot_data["PTM_localization"] == "Class I"]["mean_count"].values
    classI_sd = summarized_plot_data[summarized_plot_data["PTM_localization"] == "Class I"]["sd_count"].values
    notclassI_means = summarized_plot_data[summarized_plot_data["PTM_localization"] == "Not Class I"]["mean_count"].values
    notclassI_sd = summarized_plot_data[summarized_plot_data["PTM_localization"] == "Not Class I"]["sd_count"].values

    bars1 = ax.bar(locs - width_bar/2, classI_means, width=width_bar, yerr=classI_sd, capsize=3, color=color_classI, label="Class I")
    bars2 = ax.bar(locs + width_bar/2, notclassI_means, width=width_bar, yerr=notclassI_sd, capsize=3, color=color_notclassI, label="Not Class I")

    for i, condition in enumerate(conditions):
        y_classI = plot_data[(plot_data["condition"] == condition) & (plot_data["PTM_localization"] == "Class I")]["count"].values
        y_notclassI = plot_data[(plot_data["condition"] == condition) & (plot_data["PTM_localization"] == "Not Class I")]["count"].values
        ax.scatter(np.random.normal(i - width_bar/2, 0.05, len(y_classI)), y_classI, color='black', alpha=0.7)
        ax.scatter(np.random.normal(i + width_bar/2, 0.05, len(y_notclassI)), y_notclassI, color='black', alpha=0.7)

    ax.set_xticks(locs)
    ax.set_xticklabels(conditions, rotation=45, ha='right')
    ax.set_ylabel(y_label)
    ax.set_title(plot_title)

    if legend:
        ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

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


def ksea_volcano(
        data_st,
        data_tnc,
        pval_thresh=0.1,
        header=True,
        condition1=None,
        condition2=None,
        GRK=False
):
    df = pd.concat([data_st, data_tnc], ignore_index=True)
    if "Log₂(Frequency Factor)" not in df.columns or "Adjusted p-value" not in df.columns:
        raise ValueError("Input must contain 'Log₂(Frequency Factor)' and 'Adjusted p-value' columns")

    df["neg_log10_pval"] = -np.log10(df["Adjusted p-value"])

    def classify(row):
        if row["Adjusted p-value"] < pval_thresh:
            if row["Log₂(Frequency Factor)"] > 0:
                return "Upregulated"
            elif row["Log₂(Frequency Factor)"] < 0:
                return "Downregulated"
        return "Not significant"

    df["Regulation"] = df.apply(classify, axis=1)
    df["color"] = df["Regulation"].map({"Upregulated": "red", "Downregulated": "blue", "Not significant": "lightgrey"})

    is_grk = df["Kinase"].str.contains(r'\bGRK\d*\b', case=False, na=False)
    df_grk = df[is_grk] if GRK else pd.DataFrame(columns=df.columns)
    df_non_grk = df[~is_grk]

    df_non_grk["line_color"] = "black"
    df_non_grk["line_width"] = 0.5
    if GRK:
        df_grk["line_color"] = "yellow"
        df_grk["line_width"] = 2

    title = f"KSEA Volcano Plot: {condition1} vs. {condition2}" if header and condition1 and condition2 else (
        "KSEA Volcano Plot" if header else "")
    x_label = f"log₂(Frequency Factor) ({condition2} - {condition1})" if condition1 and condition2 else "log₂(Frequency Factor)"

    fig = go.Figure()

    for reg in df_non_grk["Regulation"].unique():
        sub = df_non_grk[df_non_grk["Regulation"] == reg]
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

    if GRK and not df_grk.empty:
        fig.add_trace(go.Scatter(
            x=df_grk["Log₂(Frequency Factor)"],
            y=df_grk["neg_log10_pval"],
            mode="markers",
            marker=dict(
                color=df_grk["color"],
                line=dict(color=df_grk["line_color"], width=df_grk["line_width"]),
                size=12
            ),
            name="GRK",
            text=df_grk["Kinase"],
            hovertemplate="Kinase: %{text}<br>Log₂(Frequency Factor): %{x}<br>-log₁₀(p-value): %{y}<br>Regulation: %{marker.color}<extra></extra>"
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
    df["-log10(adj_pval)"] = -np.log10(df["Adjusted p-value"].replace(0, np.nan))
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


def correlation_xy_intensity(data, meta, condition1, condition2, alias1=None, alias2=None, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=True):
    s1 = meta.loc[meta['condition']==condition1,'sample'].astype(str).tolist()
    s2 = meta.loc[meta['condition']==condition2,'sample'].astype(str).tolist()
    if not s1 or not s2: raise ValueError("One or both conditions have no associated samples.")
    mean1, mean2 = data[s1].mean(axis=1), data[s2].mean(axis=1)
    valid_data = pd.concat([mean1, mean2], axis=1).dropna()
    if valid_data.empty: raise ValueError("No overlapping proteins with intensity in both conditions.")
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


def overlap_plot_single(data, sample1, sample2, sample3=None, width=7, height=7, dpi=300, labels=None, colors=None, show_header=True):
    p1 = set(data.index[(data[sample1].notna()) & (data[sample1] != 0)])
    p2 = set(data.index[(data[sample2].notna()) & (data[sample2] != 0)])
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    if sample3:
        p3 = set(data.index[(data[sample3].notna()) & (data[sample3] != 0)])
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn3([p1, p2, p3], set_labels=labels or [sample1, sample2, sample3], ax=ax, **kwargs)
    else:
        kwargs = {"set_colors": colors} if colors is not None else {}
        venn2([p1, p2], set_labels=labels or [sample1, sample2], ax=ax, **kwargs)
    if show_header: ax.set_title("Overlap", fontsize=14)
    plt.tight_layout()
    return fig


def overlap_plot_condition(data, meta, condition1, condition2, condition3=None, width=7, height=7, dpi=300, labels=None, colors=None, show_header=True):
    s1 = meta.loc[meta['condition']==condition1,'sample'].tolist()
    s2 = meta.loc[meta['condition']==condition2,'sample'].tolist()
    p1 = set(data.index[(data[s1].notna() & (data[s1]!=0)).any(axis=1)])
    p2 = set(data.index[(data[s2].notna() & (data[s2]!=0)).any(axis=1)])
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    if condition3:
        s3 = meta.loc[meta['condition']==condition3,'sample'].tolist()
        p3 = set(data.index[(data[s3].notna() & (data[s3]!=0)).any(axis=1)])
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
                       width=7.87, height=3.94, dpi=300, color='blue'):
    annotated_columns = meta['sample']
    data_filtered = data[annotated_columns].copy()
    data_filtered = data_filtered.replace(0, np.nan)
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


def missing_value_plot_prec(data_path, meta, bin=0, header=True, text=True,
                            text_size=8, width=10, height=6, dpi=100, color='blue'):
    data = sanitize_dataframe(read_data(data_path)).copy()
    meta = meta.copy()

    df_wide = data.pivot_table(
        index='File.Name',
        columns='Precursor.Id',
        values='Precursor.Quantity',
        aggfunc='first'
    )

    df_wide = df_wide.T
    df_wide.columns = df_wide.columns.map(lambda x: extract_id_or_number(x))
    meta['sample'] = meta['sample'].map(lambda x: extract_id_or_number(x))

    annotated_columns = meta['sample'].tolist()
    data_filtered = df_wide.loc[:, df_wide.columns.isin(annotated_columns)]

    na_count = data_filtered.isna().sum(axis=1)

    if bin > 0:
        na_count = na_count.apply(lambda x: f">{bin}" if x > bin else str(x))
    else:
        na_count = na_count.astype(str)

    miss_vals = na_count.value_counts().sort_index()

    if bin > 0:
        levels_vec = [str(i) for i in range(bin + 1)] + [f">{bin}"]
    else:
        levels_vec = sorted(miss_vals.index, key=lambda x: int(x))

    miss_vals = miss_vals.reindex(levels_vec, fill_value=0)

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.bar(miss_vals.index, miss_vals.values, color=color)

    if header:
        ax.set_title("Missing Value Plot - Precursor Level")
    ax.set_xlabel("Number of Missing Values")
    ax.set_ylabel("Frequency")

    if text:
        for i, val in enumerate(miss_vals.values):
            if val > 0:
                ax.text(i, val + 0.5, str(val), ha='center', va='bottom', fontsize=text_size)

    plt.tight_layout()
    return fig


def missing_value_plot_pep(data_path, meta, bin=0, header=True, text=True,
                           text_size=8, width=10, height=6, dpi=100, color='blue'):
    data = sanitize_dataframe(read_data(data_path)).copy()
    meta = meta.copy()

    if "File.Name" in data.columns:
        df_wide = data.pivot_table(
            index='File.Name',
            columns='Stripped.Sequence',
            values='Precursor.Quantity',
            aggfunc='max'
        )
        df_wide = df_wide.T
        df_wide.columns = df_wide.columns.map(lambda x: extract_id_or_number(x))
    else:
        df_wide = data.copy()

    meta['sample'] = meta['sample'].map(lambda x: extract_id_or_number(x))
    annotated_columns = meta['sample'].tolist()
    data_filtered = df_wide.loc[:, df_wide.columns.isin(annotated_columns)]

    na_count = data_filtered.isna().sum(axis=1)

    if bin > 0:
        na_count = na_count.apply(lambda x: f">{bin}" if x > bin else str(x))
    else:
        na_count = na_count.astype(str)

    miss_vals = na_count.value_counts().sort_index()

    if bin > 0:
        levels_vec = [str(i) for i in range(bin + 1)] + [f">{bin}"]
    else:
        levels_vec = sorted(miss_vals.index, key=lambda x: int(x))

    miss_vals = miss_vals.reindex(levels_vec, fill_value=0)

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    ax.bar(miss_vals.index, miss_vals.values, color=color)

    if header:
        ax.set_title("Missing Value Plot - Peptide Level")
    ax.set_xlabel("Number of Missing Values")
    ax.set_ylabel("Frequency")

    if text:
        for i, val in enumerate(miss_vals.values):
            if val > 0:
                ax.text(i, val + 0.5, str(val), ha='center', va='bottom', fontsize=text_size)

    plt.tight_layout()
    return fig


def missing_value_heatmap(data, meta, id=True, header=True, width=20, height=10, dpi=300):
    data = data.replace(0, np.nan)

    meta = meta.copy()
    meta['sample'] = meta['sample'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    if id:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})", axis=1
        )
    else:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

    rename_dict = dict(zip(meta['sample'], meta['new_sample']))
    data_filtered = data.rename(columns=rename_dict)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = data_filtered[annotated_columns]

    plt.figure(figsize=(width, height), dpi=dpi)
    sns.heatmap(data_filtered.isnull(), cbar=False, cmap='viridis')
    if header:
        plt.title("Missing Values Heatmap")
    plt.xlabel("Sample")
    plt.ylabel("Protein Numbers")
    plt.tight_layout()
    fig = plt.gcf()
    return fig


def missing_protein_table(data, meta, id=True):
    data = data.replace(0, np.nan)
    meta = meta.copy()
    meta['sample'] = meta['sample'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    if id:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})", axis=1
        )
    else:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

    rename_dict = dict(zip(meta['sample'], meta['new_sample']))
    data_filtered = data.rename(columns=rename_dict)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = data_filtered[annotated_columns]

    na_counts = data_filtered.isna().sum(axis=1)
    summary = na_counts.value_counts().reset_index()
    summary.columns = ['n_MissingProteinValues', 'Counts']
    summary = summary.sort_values('n_MissingProteinValues').reset_index(drop=True)
    summary['%_missing_values'] = (summary['Counts'] / summary['Counts'].sum()) * 100
    return summary


def missing_sample_table(data, meta, id=True):
    data = data.replace(0, np.nan)
    meta = meta.copy()
    meta['sample'] = meta['sample'].astype(str)
    meta['id'] = meta['sample'].apply(extract_id_or_number)

    if id:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})", axis=1
        )
    else:
        meta['new_sample'] = meta.groupby('condition').cumcount() + 1
        meta['new_sample'] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}", axis=1
        )

    rename_dict = dict(zip(meta['sample'], meta['new_sample']))
    data_filtered = data.rename(columns=rename_dict)
    annotated_columns = [c for c in meta['new_sample'].tolist() if c in data_filtered.columns]
    data_filtered = data_filtered[annotated_columns]

    na_counts = data_filtered.isna().sum(axis=0)
    summary = na_counts.reset_index()
    summary.columns = ['Sample', 'Counts']
    summary['%_missing_values'] = (summary['Counts'] / data_filtered.shape[0]) * 100
    return summary


def missing_value_outlier(df, thld=50):
    outliers = df[df['%_missing_values'] > thld]['Sample'].tolist()
    return outliers

def all_miss_val(data, meta):
    data = data.replace(0, np.nan)
    data = data[meta['sample'].tolist()]
    total_values = data.size
    missing_values = data.isna().sum().sum()
    percent_missing = (missing_values / total_values) * 100
    return round(percent_missing, 2)
