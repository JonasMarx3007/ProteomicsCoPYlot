from __future__ import annotations

import io
import re

import numpy as np
import pandas as pd
from scipy.stats import t

from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns


def _get_plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mtick

        return plt, mtick
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for phospho plot rendering. Install it with: pip install matplotlib"
        ) from exc


def _to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"format": "png", "dpi": max(72, int(dpi))}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    fig.savefig(buf, **save_kwargs)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _extract_id_or_number(sample: str) -> str:
    match = re.search(r"\d+|[A-Za-z]+", str(sample))
    return match.group(0) if match else str(sample)


def _phospho_context() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = _get_current_frame("phospho")
    annotation = get_annotation("phospho")
    frame = annotation.source_data.copy() if annotation is not None and not annotation.source_data.empty else raw.copy()

    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        sample_columns = [sample for sample in meta["sample"].astype(str).tolist() if sample in frame.columns]
        meta = meta[meta["sample"].isin(sample_columns)].copy()
    else:
        sample_columns = _get_sample_columns("phospho", frame)
        meta = pd.DataFrame({"sample": sample_columns, "condition": ["sample"] * len(sample_columns)})

    if "condition" not in meta.columns:
        meta["condition"] = "sample"
    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    if not sample_columns:
        raise ValueError("No phospho sample columns available.")
    return frame, meta, sample_columns


def _filter_meta_conditions(meta: pd.DataFrame, conditions: list[str] | None) -> tuple[pd.DataFrame, list[str]]:
    available = meta["condition"].astype(str).dropna().tolist()
    ordered_available = list(dict.fromkeys(available))
    if conditions:
        selected = [condition for condition in conditions if condition in ordered_available]
    else:
        selected = ordered_available
    if not selected:
        raise ValueError("No matching conditions available for phospho coverage plot.")
    filtered = meta[meta["condition"].isin(selected)].copy()
    if filtered.empty:
        raise ValueError("No phospho samples available for the selected conditions.")
    return filtered, selected


def phospho_options() -> dict[str, list[str]]:
    frame, meta, _ = _phospho_context()
    conditions = (
        meta["condition"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda series: series != ""]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    has_localization = "PTM_localization" in frame.columns
    has_ptm_key = "PTM_Collapse_key" in frame.columns
    return {
        "conditions": conditions,
        "features": [
            "PTM_localization" if has_localization else "",
            "PTM_Collapse_key" if has_ptm_key else "",
        ],
    }


def phosphosite_plot_table(cutoff: float = 0.0) -> pd.DataFrame:
    frame, _, _ = _phospho_context()
    if "PTM_localization" in frame.columns:
        filtered = frame[frame["PTM_localization"].apply(pd.to_numeric, errors="coerce") >= float(cutoff)].copy()
    else:
        filtered = frame.copy()

    if filtered.empty:
        return pd.DataFrame({"Term": [], "Count": []})

    protein_col = "Protein_group" if "Protein_group" in filtered.columns else "Phosphoprotein"
    phosphoproteins = int(filtered[protein_col].dropna().astype(str).nunique()) if protein_col in filtered.columns else 0

    if "UPD_seq" in filtered.columns:
        clean_seq = filtered["UPD_seq"].astype(str).str.replace(r"[^\w]", "", regex=True).str.upper()
        phosphopeptides = int(clean_seq.replace("", np.nan).dropna().nunique())
    else:
        phosphopeptides = int(filtered["PTM_Collapse_key"].dropna().astype(str).nunique()) if "PTM_Collapse_key" in filtered.columns else 0

    phosphosites = int(filtered["PTM_Collapse_key"].dropna().astype(str).nunique()) if "PTM_Collapse_key" in filtered.columns else 0

    summary = pd.DataFrame(
        {
            "Term": ["Phosphoproteins", "Phosphopeptides", "Phosphosites"],
            "Count": [phosphoproteins, phosphopeptides, phosphosites],
        }
    ).sort_values("Count", ascending=False)
    return summary.reset_index(drop=True)


def phosphosite_plot_png(
    cutoff: float = 0.0,
    color: str = "#87CEEB",
    width_cm: float = 15,
    height_cm: float = 10,
    dpi: int = 100,
) -> bytes:
    plt, _ = _get_plt()
    summary = phosphosite_plot_table(cutoff=cutoff)
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))

    if summary.empty:
        ax.text(0.5, 0.5, "No phospho rows available", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    ax.barh(summary["Term"], summary["Count"], color=color)
    max_count = max(summary["Count"].max(), 1)
    for index, value in enumerate(summary["Count"]):
        ax.text(float(value) + max_count * 0.01, index, str(int(value)), va="center", fontweight="bold")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def _coverage_counts(
    include_id: bool = False,
    conditions: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame, meta, _ = _phospho_context()
    if "PTM_localization" not in frame.columns:
        raise ValueError("Phospho dataset must contain PTM_localization for coverage plots.")

    meta_filtered, selected_conditions = _filter_meta_conditions(meta, conditions)
    meta_filtered["sample_idx"] = meta_filtered.groupby("condition").cumcount() + 1
    if include_id:
        meta_filtered["new_sample"] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['sample_idx']}\n({_extract_id_or_number(row['sample'])})",
            axis=1,
        )
    else:
        meta_filtered["new_sample"] = meta_filtered.apply(
            lambda row: f"{row['condition']}_{row['sample_idx']}",
            axis=1,
        )

    rename_map = dict(zip(meta_filtered["sample"], meta_filtered["new_sample"]))
    labeled_frame = frame.rename(columns=rename_map)
    sample_labels = [rename_map[sample] for sample in meta_filtered["sample"] if sample in frame.columns]
    if not sample_labels:
        raise ValueError("No samples available in phospho dataset for coverage plot.")

    localization = pd.to_numeric(frame["PTM_localization"], errors="coerce")
    class_i = labeled_frame.loc[localization >= 0.75, sample_labels]
    not_class_i = labeled_frame.loc[localization < 0.75, sample_labels]

    counts = pd.DataFrame(
        {
            "Sample": sample_labels,
            "Class I": class_i.notna().sum().reindex(sample_labels, fill_value=0).astype(int).tolist(),
            "Not Class I": not_class_i.notna().sum().reindex(sample_labels, fill_value=0).astype(int).tolist(),
        }
    )
    sample_to_condition = dict(zip(meta_filtered["new_sample"], meta_filtered["condition"]))
    counts["Condition"] = counts["Sample"].map(sample_to_condition).fillna("sample")
    counts["Total"] = counts["Class I"] + counts["Not Class I"]

    summary = (
        counts.groupby("Condition", as_index=False)
        .agg(
            classIMean=("Class I", "mean"),
            classISd=("Class I", "std"),
            notClassIMean=("Not Class I", "mean"),
            notClassISd=("Not Class I", "std"),
        )
        .fillna(0.0)
    )
    summary["Condition"] = pd.Categorical(summary["Condition"], categories=selected_conditions, ordered=True)
    summary = summary.sort_values("Condition").reset_index(drop=True)
    return counts, summary


def phospho_coverage_table(include_id: bool = False, conditions: list[str] | None = None, mode: str = "Normal") -> pd.DataFrame:
    counts, summary = _coverage_counts(include_id=include_id, conditions=conditions)
    return counts if str(mode).lower() == "normal" else summary


def phospho_coverage_png(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: str = "Normal",
    color_class_i: str = "#2563eb",
    color_not_class_i: str = "#f59e0b",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    conditions: list[str] | None = None,
) -> bytes:
    plt, _ = _get_plt()
    counts, summary = _coverage_counts(include_id=include_id, conditions=conditions)
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))

    if str(mode).lower() == "summary":
        conds = summary["Condition"].astype(str).tolist()
        x = np.arange(len(conds))
        width = 0.35
        class_i_mean = summary["classIMean"].to_numpy(dtype=float)
        class_i_sd = summary["classISd"].to_numpy(dtype=float)
        not_class_i_mean = summary["notClassIMean"].to_numpy(dtype=float)
        not_class_i_sd = summary["notClassISd"].to_numpy(dtype=float)

        ax.bar(x - width / 2, class_i_mean, width=width, yerr=class_i_sd, capsize=3, color=color_class_i, label="Class I")
        ax.bar(x + width / 2, not_class_i_mean, width=width, yerr=not_class_i_sd, capsize=3, color=color_not_class_i, label="Not Class I")

        for idx, condition in enumerate(conds):
            y_class = counts.loc[counts["Condition"] == condition, "Class I"].to_numpy(dtype=float)
            y_not = counts.loc[counts["Condition"] == condition, "Not Class I"].to_numpy(dtype=float)
            if y_class.size:
                ax.scatter(np.random.normal(idx - width / 2, 0.04, y_class.size), y_class, color="black", alpha=0.6, s=8)
            if y_not.size:
                ax.scatter(np.random.normal(idx + width / 2, 0.04, y_not.size), y_not, color="black", alpha=0.6, s=8)
        ax.set_xticks(x)
        ax.set_xticklabels(conds, rotation=45, ha="right")
        if header:
            ax.set_title("Phosphosites per condition")
        ax.set_ylabel("Number of phosphosites")
    else:
        x = np.arange(len(counts))
        class_vals = counts["Class I"].to_numpy(dtype=float)
        not_vals = counts["Not Class I"].to_numpy(dtype=float)
        ax.bar(x, class_vals, color=color_class_i, label="Class I")
        ax.bar(x, not_vals, bottom=class_vals, color=color_not_class_i, label="Not Class I")
        ax.set_xticks(x)
        ax.set_xticklabels(counts["Sample"].astype(str).tolist(), rotation=90, fontsize=7)
        ax.set_xlabel("Sample")
        ax.set_ylabel("Number of phosphosites")
        if header:
            ax.set_title("Phosphosites per sample")

    if legend:
        ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))
        fig.tight_layout(rect=[0, 0, 0.86, 1])
    else:
        fig.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def phospho_distribution_table(cutoff: float = 0.0) -> pd.DataFrame:
    frame, _, _ = _phospho_context()
    if "site_num" in frame.columns:
        site_counts = pd.to_numeric(frame["site_num"], errors="coerce").dropna()
    else:
        group_col = "Phosphoprotein" if "Phosphoprotein" in frame.columns else "Protein_group"
        if group_col not in frame.columns or "PTM_Collapse_key" not in frame.columns:
            raise ValueError("Phospho distribution requires site_num or (Phosphoprotein/Protein_group + PTM_Collapse_key).")
        site_counts = (
            frame.groupby(group_col)["PTM_Collapse_key"].nunique().astype(float)
        )

    if site_counts.empty:
        return pd.DataFrame({"SiteCount": [], "Frequency": []})

    if cutoff > 0:
        threshold = float(site_counts.quantile(1 - float(cutoff)))
        site_counts = site_counts[site_counts <= threshold]

    freq = site_counts.value_counts().sort_index()
    return pd.DataFrame({"SiteCount": freq.index.astype(int), "Frequency": freq.values.astype(int)})


def phospho_distribution_png(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    width_cm: float = 20,
    height_cm: float = 15,
    dpi: int = 300,
) -> bytes:
    plt, _ = _get_plt()
    table = phospho_distribution_table(cutoff=cutoff)
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))

    if table.empty:
        ax.text(0.5, 0.5, "No phosphosite distribution data available", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    ax.bar(table["SiteCount"].to_numpy(), table["Frequency"].to_numpy(), color=color)
    max_site = int(table["SiteCount"].max())
    xticks = np.arange(0, max_site + 1, 10 if max_site >= 10 else 1)
    ax.set_xticks(xticks)
    ax.set_xlabel("Number of phosphosites per phosphoprotein")
    ax.set_ylabel("Frequency")
    if header:
        ax.set_title("Distribution of phosphosite counts per protein")
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def phospho_sty_table() -> pd.DataFrame:
    frame, _, _ = _phospho_context()
    if "PTM_Collapse_key" not in frame.columns:
        raise ValueError("Phospho dataset must contain PTM_Collapse_key for STY plot.")

    keys = frame["PTM_Collapse_key"].astype(str)
    letters = keys.str.extract(r"~[^_]+_([STY])\d+_")[0]
    if letters.isna().all():
        letters = keys.str.extract(r"([STY])\d+")[0]

    counts = letters.value_counts().reindex(["S", "T", "Y"], fill_value=0)
    total = int(counts.sum())
    percentages = (counts / total * 100.0) if total > 0 else counts.astype(float)
    return pd.DataFrame(
        {
            "Residue": counts.index.tolist(),
            "Count": counts.values.astype(int),
            "Percentage": percentages.values.round(2),
        }
    )


def phospho_sty_png(
    header: bool = True,
    width_cm: float = 17.78,
    height_cm: float = 11.43,
    dpi: int = 140,
) -> bytes:
    plt, mtick = _get_plt()
    table = phospho_sty_table()
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))
    colors = {"S": "#4C78A8", "T": "#F58518", "Y": "#54A24B"}
    bar_colors = [colors.get(label, "#64748b") for label in table["Residue"].tolist()]
    ax.bar(table["Residue"], table["Count"], color=bar_colors, edgecolor="black", linewidth=0.6)

    if header:
        ax.set_title("Modified S/T/Y peptide counts", pad=10, fontweight="bold")
    ax.set_xlabel("Residue")
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

    y_max = float(table["Count"].max()) if not table.empty else 0.0
    offset = 0.02 * y_max if y_max > 0 else 0.1
    for idx, row in table.iterrows():
        ax.text(idx, float(row["Count"]) + offset, f"{float(row['Percentage']):.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def _bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    pvalues = np.asarray(pvalues, dtype=float)
    if pvalues.size == 0:
        return pvalues
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    adjusted = np.empty_like(ranked)
    n = float(len(ranked))
    running = 1.0
    for idx in range(len(ranked) - 1, -1, -1):
        rank = idx + 1.0
        value = float(ranked[idx] * n / rank)
        running = min(running, value)
        adjusted[idx] = running
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty_like(adjusted)
    restored[order] = adjusted
    return restored


def _safe_neg_log10(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), 1e-300, 1.0)
    return -np.log10(clipped)


def _convert_to_centered(seq: object) -> str:
    if not isinstance(seq, str):
        return ""
    match = re.search(r"\*", seq)
    if not match:
        return seq
    star_index = match.start()
    if star_index == 0:
        return seq
    mod_residue = seq[star_index - 1].upper()
    clean_seq = seq[: star_index - 1] + mod_residue + seq[star_index + 1 :]
    mod_pos = star_index - 1
    left = clean_seq[:mod_pos]
    right = clean_seq[mod_pos + 1 :]
    left_tail = left[-6:] if len(left) >= 6 else "_" * (6 - len(left)) + left
    right_tail = right[:6] if len(right) >= 6 else right + "_" * (6 - len(right))
    return f"_{left_tail}{mod_residue}{right_tail}_"


def _condition_columns(meta: pd.DataFrame, condition: str) -> list[str]:
    return meta.loc[meta["condition"].astype(str) == str(condition), "sample"].astype(str).tolist()


def ksea_table(
    *,
    condition1: str,
    condition2: str,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
) -> pd.DataFrame:
    frame, meta, _ = _phospho_context()
    label_col = "UPD_seq"
    if label_col not in frame.columns:
        raise ValueError("Phospho dataset must contain UPD_seq for KSEA.")

    cols1 = _condition_columns(meta, condition1)
    cols2 = _condition_columns(meta, condition2)
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")

    df = frame[[label_col, *cols1, *cols2]].replace(0, np.nan).copy()
    arr_x = df[cols1].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    arr_y = df[cols2].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for KSEA.")

    df = df.loc[valid_mask].reset_index(drop=True)
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask].astype(float)
    n2 = n2_real[valid_mask].astype(float)

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean2 - mean1

    paired = str(test_type).strip().lower() == "paired"
    if paired:
        diffs = arr_y - arr_x
        min_len = np.minimum(n1, n2)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(min_len)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = mean_diff / se_diff
        pvals = 2.0 * t.sf(np.abs(t_stat), min_len - 1.0)
    else:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
        se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = log2fc / se
        pvals = 2.0 * t.sf(np.abs(t_stat), n1 + n2 - 2.0)

    pvals = np.nan_to_num(pvals, nan=1.0, posinf=1.0, neginf=1.0)
    adj_pvals = pvals if use_uncorrected else _bh_adjust(pvals)

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < p_value_threshold) & (log2fc > log2fc_threshold)] = "Upregulated"
    significance[(adj_pvals < p_value_threshold) & (log2fc < -log2fc_threshold)] = "Downregulated"

    result = pd.DataFrame(
        {
            "UPD_seq": [_convert_to_centered(value) for value in df[label_col].tolist()],
            "log2FC": log2fc,
            "pval": pvals,
            "adj_pval": adj_pvals,
            "significance": significance,
        }
    )
    result["neg_log10_adj_pval"] = _safe_neg_log10(result["adj_pval"].to_numpy(dtype=float))
    return result


def ksea_plot_png(
    *,
    condition1: str,
    condition2: str,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 220,
) -> bytes:
    plt, _ = _get_plt()
    table = ksea_table(
        condition1=condition1,
        condition2=condition2,
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
    )
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))
    color_map = {
        "Downregulated": "#2563eb",
        "Not significant": "#94a3b8",
        "Upregulated": "#dc2626",
    }

    for significance, color in color_map.items():
        subset = table[table["significance"] == significance]
        if subset.empty:
            continue
        ax.scatter(
            subset["log2FC"].to_numpy(dtype=float),
            subset["neg_log10_adj_pval"].to_numpy(dtype=float),
            s=12,
            c=color,
            label=significance,
            alpha=0.85,
            edgecolors="none",
        )

    y_line = float(-np.log10(max(p_value_threshold, 1e-300)))
    max_y = max(y_line, float(table["neg_log10_adj_pval"].max()) if not table.empty else y_line)
    ax.axvline(float(log2fc_threshold), color="black", linestyle="--", linewidth=1)
    ax.axvline(float(-log2fc_threshold), color="black", linestyle="--", linewidth=1)
    ax.hlines(y_line, xmin=float(table["log2FC"].min()), xmax=float(table["log2FC"].max()), colors="black", linestyles="--", linewidth=1)
    ax.set_ylim(bottom=0, top=max_y * 1.05 if max_y > 0 else 1)
    ax.set_xlabel(f"log2 fold change ({condition2} - {condition1})")
    ax.set_ylabel("-log10 adj. p-value" if not use_uncorrected else "-log10 p-value")
    if header:
        ax.set_title(f"KSEA Volcano Plot: {condition1} vs {condition2}")
    ax.legend(loc="best")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def phosprot_regulation_table(
    *,
    condition1: str,
    condition2: str,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    max_hover_sites: int = 20,
    show_phosphosites: bool = True,
) -> pd.DataFrame:
    frame, meta, _ = _phospho_context()
    label_col = "PTM_Collapse_key"
    group_col = "Protein_group"
    required = [label_col, group_col]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Phospho dataset is missing required columns: {missing}")

    cols1 = _condition_columns(meta, condition1)
    cols2 = _condition_columns(meta, condition2)
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")

    df = frame[[label_col, group_col, *cols1, *cols2]].replace(0, np.nan).copy()
    arr_x = df[cols1].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    arr_y = df[cols2].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for phosphoprotein regulation.")

    df = df.loc[valid_mask].reset_index(drop=True)
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask].astype(float)
    n2 = n2_real[valid_mask].astype(float)

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean2 - mean1

    paired = str(test_type).strip().lower() == "paired"
    if paired:
        diffs = arr_y - arr_x
        min_len = np.minimum(n1, n2)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(min_len)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = mean_diff / se_diff
        pvals = 2.0 * t.sf(np.abs(t_stat), min_len - 1.0)
    else:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
        se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = log2fc / se
        pvals = 2.0 * t.sf(np.abs(t_stat), n1 + n2 - 2.0)

    pvals = np.nan_to_num(pvals, nan=1.0, posinf=1.0, neginf=1.0)
    adj_pvals = pvals if use_uncorrected else _bh_adjust(pvals)

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < p_value_threshold) & (log2fc > log2fc_threshold)] = "Upregulated"
    significance[(adj_pvals < p_value_threshold) & (log2fc < -log2fc_threshold)] = "Downregulated"

    volcano_df = pd.DataFrame(
        {
            group_col: df[group_col].astype(str).tolist(),
            label_col: df[label_col].astype(str).tolist(),
            "log2FC": log2fc,
            "pval": pvals,
            "adj_pval": adj_pvals,
            "significance": significance,
        }
    )

    all_samples = [*cols1, *cols2]

    def truncate_sites(sites: list[str]) -> str:
        if len(sites) > max_hover_sites:
            return ";".join(sites[:max_hover_sites]) + f";... (+{len(sites) - max_hover_sites} more)"
        return ";".join(sites)

    rows: list[dict[str, object]] = []
    for protein_group, group in volcano_df.groupby(group_col):
        down_sites = group.loc[group["log2FC"] < 0, label_col].astype(str).tolist()
        up_sites = group.loc[group["log2FC"] > 0, label_col].astype(str).tolist()
        down_vals = frame.loc[frame[label_col].astype(str).isin(down_sites), all_samples].apply(pd.to_numeric, errors="coerce").fillna(0.0) if down_sites else pd.DataFrame()
        up_vals = frame.loc[frame[label_col].astype(str).isin(up_sites), all_samples].apply(pd.to_numeric, errors="coerce").fillna(0.0) if up_sites else pd.DataFrame()
        down_total = float(down_vals.to_numpy(dtype=float).sum()) if not down_vals.empty else 0.0
        up_total = float(up_vals.to_numpy(dtype=float).sum()) if not up_vals.empty else 0.0
        down_sum = float(np.log2(down_total)) if down_total > 0 else 0.0
        up_sum = float(np.log2(up_total)) if up_total > 0 else 0.0

        rows.append(
            {
                "Protein_group": str(protein_group),
                "Downregulated_sites": truncate_sites(down_sites) if show_phosphosites else "",
                "Upregulated_sites": truncate_sites(up_sites) if show_phosphosites else "",
                "Downregulated_count": int(len(down_sites)),
                "Upregulated_count": int(len(up_sites)),
                "Downregulated_sum": down_sum,
                "Upregulated_sum": up_sum,
            }
        )

    collapsed_df = pd.DataFrame(rows)
    if collapsed_df.empty:
        return collapsed_df
    collapsed_df["x"] = collapsed_df["Upregulated_sum"].abs()
    collapsed_df["y"] = collapsed_df["Downregulated_sum"].abs()
    collapsed_df["color_val"] = collapsed_df["x"] - collapsed_df["y"]
    return collapsed_df.sort_values("Protein_group").reset_index(drop=True)


def phosprot_regulation_png(
    *,
    condition1: str,
    condition2: str,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    max_hover_sites: int = 20,
    show_phosphosites: bool = True,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 220,
) -> bytes:
    plt, _ = _get_plt()
    table = phosprot_regulation_table(
        condition1=condition1,
        condition2=condition2,
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
        max_hover_sites=max_hover_sites,
        show_phosphosites=show_phosphosites,
    )
    fig, ax = plt.subplots(figsize=(max(1, width_cm / 2.54), max(1, height_cm / 2.54)))
    if table.empty:
        ax.text(0.5, 0.5, "No phosphoprotein regulation data available", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    scatter = ax.scatter(
        table["x"].to_numpy(dtype=float),
        table["y"].to_numpy(dtype=float),
        c=table["color_val"].to_numpy(dtype=float),
        cmap="coolwarm",
        s=20,
        alpha=0.75,
        edgecolors="none",
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Up - Down")
    ax.set_xlabel("Absolute Upregulated Sum (log2)")
    ax.set_ylabel("Absolute Downregulated Sum (log2)")
    if header:
        ax.set_title("Protein-level Phosphosite Regulation")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)
