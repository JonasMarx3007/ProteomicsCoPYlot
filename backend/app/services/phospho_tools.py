from __future__ import annotations


from app.services.plot_export import (
    cm_to_inch as _cm_to_inch,
    to_png_bytes as _to_png_bytes,
)

import re
from functools import lru_cache

import numpy as np
import pandas as pd

from app.services.annotation_store import get_annotation
from app.services.phospho_localization import apply_session_localization_cutoff
from app.schemas.annotation import DataSource
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.functions import (
    DATA_SOURCES,
    comparison_contrast,
    data_source_options,
    select_matrix,
    extract_sample_id as _extract_id_or_number,
    imputed_data_available,
)
from app.services.plot_styling import (
    advanced_label,
    advanced_plotly_layout,
    apply_advanced_axes,
    advanced_color,
    marker_style,
    plotly_marker,
    resolve_reference_line,
)
from app.services.runtime_cache import apply_cached_wrappers
from app.services.plotting_common import get_plt_with_ticker as _get_plt, get_plotly_px as _get_plotly, get_plotly_go as _get_plotly_go, plotly_html as _plotly_html
from app.services.json_records import json_records


def _phospho_context() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = _get_current_frame("phospho")
    annotation = get_annotation("phospho")
    frame = annotation.source_data.copy() if annotation is not None and not annotation.source_data.empty else raw.copy()
    # Every Phospho-specific plot shows the sites that pass the session's
    # localization probability cutoff (services/phospho_localization.py).
    frame = apply_session_localization_cutoff(frame)

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


def _ksea_context(
    *,
    data_source: DataSource = "data",
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    _, frame, meta = select_matrix("phospho", data_source)
    sample_columns = [
        sample for sample in meta["sample"].astype(str).tolist() if sample in frame.columns
    ]
    meta = meta[meta["sample"].astype(str).isin(sample_columns)].copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    if not sample_columns:
        raise ValueError("No phospho sample columns available for Kinase Library.")
    return frame, meta, sample_columns


def _phospho_regulation_context(
    data_source: str = "data",
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """The matrix the regulation plot's volcano runs on.

    `data_source` is the same choice the Statistics volcano offers (data /
    filtered / imputed), so the sites this plot sums are the sites that volcano
    shows for the same settings.
    """
    data_mode = str(data_source).strip().lower()
    if data_mode not in DATA_SOURCES:
        raise ValueError(
            "Unsupported phosphoprotein-regulation data source. Choose 'data', 'filtered', or 'imputed'."
        )
    annotation = get_annotation("phospho")
    if annotation is not None and not annotation.metadata.empty:
        _, frame, meta = select_matrix("phospho", data_mode)
        sample_columns = [
            sample for sample in meta["sample"].astype(str).tolist() if sample in frame.columns
        ]
        return frame, meta, sample_columns
    if data_mode != "data":
        raise ValueError("Generate phosphosite annotations before selecting filtered or imputed data.")
    return _phospho_context()


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


def phospho_options() -> dict[str, object]:
    frame, meta, _ = _phospho_context()
    imputed_available = imputed_data_available("phospho")
    conditions = (
        meta["condition"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda series: series != ""]
        # In the order the metadata lists them, as every plot draws them.
        .drop_duplicates()
        .tolist()
    )
    has_localization = "PTM_localization" in frame.columns
    has_ptm_key = "PTM_Collapse_key" in frame.columns
    samples_by_condition = {
        condition: meta.loc[
            meta["condition"].astype(str) == condition, "sample"
        ].astype(str).tolist()
        for condition in conditions
    }
    pair_ids_by_sample = {}
    if "pair_id" in meta.columns:
        pair_ids_by_sample = {
            str(sample): str(pair_id).strip()
            for sample, pair_id in meta[["sample", "pair_id"]].itertuples(
                index=False, name=None
            )
            if pd.notna(pair_id) and str(pair_id).strip()
        }
    return {
        "conditions": conditions,
        "samplesByCondition": samples_by_condition,
        "pairIdsBySample": pair_ids_by_sample,
        "features": [
            "PTM_localization" if has_localization else "",
            "PTM_Collapse_key" if has_ptm_key else "",
        ],
        "imputedAvailable": imputed_available,
        **data_source_options("phospho"),
    }


def phosphosite_plot_table() -> pd.DataFrame:
    # The localization cutoff is the session-wide one, applied in _phospho_context.
    filtered, _, _ = _phospho_context()

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
    color: str = "#87CEEB",
    width_cm: float = 15,
    height_cm: float = 10,
    dpi: int = 100,
    advanced: dict | None = None,
) -> bytes:
    plt, _ = _get_plt()
    summary = phosphosite_plot_table()
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))

    if summary.empty:
        ax.text(0.5, 0.5, "No phospho rows available", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    ax.barh(summary["Term"], summary["Count"], color=advanced_color(advanced, "barColor", color))
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
    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def _coverage_counts(
    include_id: bool = False,
    conditions: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame, meta, _ = _phospho_context()

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

    localization = pd.to_numeric(frame.get("PTM_localization", pd.Series(np.nan, index=frame.index)), errors="coerce")
    localization = localization.where(localization.between(0, 1))
    observed = labeled_frame[sample_labels].apply(pd.to_numeric, errors="coerce")
    observed = observed.where(np.isfinite(observed))
    annotation = get_annotation("phospho")
    if not bool(getattr(annotation, "is_log2_transformed", False)):
        observed = observed.mask(observed == 0)
    class_i = observed.loc[localization >= 0.75]
    not_class_i = observed.loc[localization < 0.75]

    counts = pd.DataFrame(
        {
            "Sample": sample_labels,
            "Class I": class_i.notna().sum().reindex(sample_labels, fill_value=0).astype(int).tolist(),
            "Not Class I": not_class_i.notna().sum().reindex(sample_labels, fill_value=0).astype(int).tolist(),
            "Unclassified": observed.loc[localization.isna()].notna().sum().tolist(),
        }
    )
    sample_to_condition = dict(zip(meta_filtered["new_sample"], meta_filtered["condition"]))
    counts["Condition"] = counts["Sample"].map(sample_to_condition).fillna("sample")
    counts["Total"] = counts[["Class I", "Not Class I", "Unclassified"]].sum(axis=1)

    summary = (
        counts.groupby("Condition", as_index=False)
        .agg(
            classIMean=("Class I", "mean"),
            classISd=("Class I", "std"),
            notClassIMean=("Not Class I", "mean"),
            notClassISd=("Not Class I", "std"),
            unclassifiedMean=("Unclassified", "mean"),
            unclassifiedSd=("Unclassified", "std"),
            totalMean=("Total", "mean"),
            totalSd=("Total", "std"),
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
    random_seed: int = 69,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    conditions: list[str] | None = None,
    advanced: dict | None = None,
) -> bytes:
    plt, _ = _get_plt()
    counts, summary = _coverage_counts(include_id=include_id, conditions=conditions)
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))

    if str(mode).lower() == "summary":
        rng = np.random.default_rng(random_seed)
        conds = summary["Condition"].astype(str).tolist()
        x = np.arange(len(conds))
        categories = [
            ("Class I", "classI", advanced_color(advanced, "classIColor", color_class_i)),
            (
                "Not Class I",
                "notClassI",
                advanced_color(advanced, "classNotIColor", color_not_class_i),
            ),
        ]
        if counts["Unclassified"].any():
            categories.append(("Unclassified", "unclassified", "#94a3b8"))
        width = .7 / len(categories)
        for index, (category, prefix, color) in enumerate(categories):
            offset = (index - (len(categories) - 1) / 2) * width
            ax.bar(x + offset, summary[prefix + "Mean"], width=width,
                   yerr=summary[prefix + "Sd"], capsize=3, color=color, label=category)
            for idx, condition in enumerate(conds):
                values = counts.loc[counts["Condition"] == condition, category].to_numpy(dtype=float)
                ax.scatter(rng.normal(idx + offset, .04, values.size), values,
                           color="black", alpha=.6, s=8)
        ax.set_xticks(x)
        ax.set_xticklabels(
            [advanced_label(str(condition), advanced, "conditionLabels") for condition in conds],
            rotation=45,
            ha="right",
        )
        if header:
            ax.set_title("Phosphosites per condition")
        ax.set_ylabel("Number of phosphosites")
    else:
        x = np.arange(len(counts))
        class_vals = counts["Class I"].to_numpy(dtype=float)
        not_vals = counts["Not Class I"].to_numpy(dtype=float)
        ax.bar(
            x,
            class_vals,
            color=advanced_color(advanced, "classIColor", color_class_i),
            label="Class I",
        )
        ax.bar(
            x,
            not_vals,
            bottom=class_vals,
            color=advanced_color(advanced, "classNotIColor", color_not_class_i),
            label="Not Class I",
        )
        if counts["Unclassified"].any():
            ax.bar(x, counts["Unclassified"], bottom=class_vals + not_vals,
                   color="#94a3b8", label="Unclassified")
        ax.set_xticks(x)
        ax.set_xticklabels(counts["Sample"].astype(str).tolist(), rotation=90, fontsize=7)
        ax.set_xlabel("Sample")
        ax.set_ylabel("Number of phosphosites")
        if header:
            ax.set_title("Phosphosites per sample")

    if legend:
        ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))
        apply_advanced_axes(ax, advanced)
        fig.tight_layout(rect=[0, 0, 0.86, 1])
    else:
        apply_advanced_axes(ax, advanced)
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
    advanced: dict | None = None,
) -> bytes:
    plt, _ = _get_plt()
    table = phospho_distribution_table(cutoff=cutoff)
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))

    if table.empty:
        ax.text(0.5, 0.5, "No phosphosite distribution data available", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    ax.bar(
        table["SiteCount"].to_numpy(),
        table["Frequency"].to_numpy(),
        color=advanced_color(advanced, "barColor", color),
    )
    max_site = int(table["SiteCount"].max())
    xticks = np.arange(0, max_site + 1, 10 if max_site >= 10 else 1)
    ax.set_xticks(xticks)
    ax.set_xlabel("Number of phosphosites per phosphoprotein")
    ax.set_ylabel("Frequency")
    if header:
        ax.set_title("Distribution of phosphosite counts per protein")
    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def phospho_sty_table() -> pd.DataFrame:
    frame, _, _ = _phospho_context()
    if "PTM_Collapse_key" not in frame.columns:
        raise ValueError("Phospho dataset must contain PTM_Collapse_key for STY plot.")

    keys = frame["PTM_Collapse_key"].astype(str)
    letters = keys.str.extract(r"~[^_]+_([STY])\d+_")[0]
    letters = letters.fillna(keys.str.extract(r"(?:^|_)([STY])\d+(?:_|$)")[0])

    counts = letters.value_counts().reindex(["S", "T", "Y"], fill_value=0)
    if letters.isna().any():
        counts.loc["Unparsed"] = int(letters.isna().sum())
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
    advanced: dict | None = None,
) -> bytes:
    plt, mtick = _get_plt()
    table = phospho_sty_table()
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    colors = {"S": "#4C78A8", "T": "#F58518", "Y": "#54A24B"}
    bar_colors = [colors.get(label, "#64748b") for label in table["Residue"].tolist()]
    ax.bar(table["Residue"], table["Count"], color=bar_colors, edgecolor="black", linewidth=0.6)

    if header:
        # One bar counts rows of the phosphosite matrix -- site identifiers, not
        # peptides. A peptide carrying two sites is two rows here.
        ax.set_title("Modified S/T/Y site counts", pad=10, fontweight="bold")
    ax.set_xlabel("Residue")
    ax.set_ylabel("Count")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.set_axisbelow(True)
    apply_advanced_axes(ax, advanced)

    total_count = int(table["Count"].sum())
    if total_count > 0:
        ax2 = ax.secondary_yaxis(
            "right", functions=(lambda count: count * 100 / total_count,
                                lambda percent: percent * total_count / 100),
        )
        ax2.set_ylabel("Share of sites (%)")
        ax2.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))

    y_max = float(table["Count"].max()) if not table.empty else 0.0
    offset = 0.02 * y_max if y_max > 0 else 0.1
    for idx, row in table.iterrows():
        ax.text(idx, float(row["Count"]) + offset, f"{float(row['Percentage']):.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


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
    left_tail = left[-7:].rjust(7, "_")
    right_tail = right[:7].ljust(7, "_")
    return f"{left_tail}{mod_residue}{right_tail}"


# Kinase motif windows ------------------------------------------------------
#
# The Kinase Library scores a 15-residue window (7 + site + 7) and reads "_" as
# "beyond the protein terminus". A window cut from the peptide alone pads with
# "_" wherever the peptide ends, which presents real flanking residues as
# absent -- and because trypsin cleaves after R/K, the -3 position of basophilic
# R-x-x-S/T motifs is lost systematically. Windows are therefore read from the
# protein sequence at the site position named in PTM_Collapse_key, and the
# peptide window is kept only as a fallback, with the source reported per row.

KSEA_ORGANISMS = ("human", "mouse", "none")
KSEA_WINDOW_FLANK = 7
_SITE_KEY_PATTERN = re.compile(
    r"^(?P<proteins>[^~]*)~(?P<gene>.*)_(?P<residue>[A-Za-z])(?P<position>\d+)_M\d+$"
)


def _parse_site_key(key: object) -> tuple[list[str], str, str, int] | None:
    """(accessions, gene, residue, 1-based position) from a PTM_Collapse_key."""
    if not isinstance(key, str):
        return None
    match = _SITE_KEY_PATTERN.match(key.strip())
    if match is None:
        return None
    accessions = [part.strip() for part in match.group("proteins").split(";") if part.strip()]
    if not accessions:
        return None
    return accessions, match.group("gene"), match.group("residue").upper(), int(match.group("position"))


def _protein_window(sequence: str, position: int, flank: int = KSEA_WINDOW_FLANK) -> str:
    """The window centred on 1-based `position`, "_" only past the protein ends."""
    centre = position - 1
    start, end = centre - flank, centre + flank + 1
    core = sequence[max(start, 0):min(end, len(sequence))].upper()
    return "_" * max(0, -start) + core + "_" * max(0, end - len(sequence))


def _windows_agree(protein_window: str, peptide_window: str) -> bool:
    """Every residue the peptide does cover must match the protein window."""
    if len(peptide_window) != len(protein_window):
        return True  # no centred peptide window to compare against
    return all(pep == "_" or pep == prot for pep, prot in zip(peptide_window, protein_window))


def site_motif_window(key: object, peptide_sequence: object, sequences: dict[str, str] | None) -> dict[str, str]:
    """Motif window for one site plus the provenance the export reports.

    `window_source` is "protein" when the window was read from the FASTA
    sequence (the residue at the reported position must be the modified one and
    every residue the peptide covers must agree), otherwise "peptide".
    """
    peptide_window = _convert_to_centered(peptide_sequence)
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
                return {"UPD_seq": window, "Protein": accession, "Gene": gene, "Site": site, "window_source": "protein"}
    return {"UPD_seq": peptide_window, "Protein": protein, "Gene": gene, "Site": site, "window_source": "peptide"}


def _resolve_ksea_organism(organism: object) -> str:
    key = str(organism if organism is not None else "human").strip().lower() or "human"
    if key not in KSEA_ORGANISMS:
        raise ValueError(
            f"Unsupported organism '{organism}' for motif windows. Choose one of: {', '.join(KSEA_ORGANISMS)}."
        )
    return key


def _ksea_protein_sequences(organism: str) -> dict[str, str] | None:
    """Accession -> sequence from the bundled reference proteome, or None."""
    if organism == "none":
        return None
    from app.services.peptide_tools import _fasta_path

    path = _fasta_path(organism)
    return _fasta_sequence_map(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _fasta_sequence_map(path_str: str, modified_ns: int) -> dict[str, str]:
    from app.services.peptide_tools import _load_fasta_dataframe_cached

    frame = _load_fasta_dataframe_cached(path_str, modified_ns)
    return dict(zip(frame["accession"].astype(str), frame["V1"].astype(str)))


KSEA_EXPORT_COLUMNS = ("PTM_Collapse_key", "Protein", "Gene", "Site", "window_source")


def _ksea_format(frame: pd.DataFrame, organism: str) -> pd.DataFrame:
    """The Kinase Library upload table: motif window, statistics, then provenance."""
    columns = ["UPD_seq", "log2FC", "pval", "adj_pval", "selected_pval", "significance"]
    if "n_pairs" in frame.columns:
        columns.append("n_pairs")
    columns.append("neg_log10_selected_pval")
    result = frame[columns].copy()
    sequences = _ksea_protein_sequences(organism)
    keys = frame["PTM_Collapse_key"].tolist() if "PTM_Collapse_key" in frame.columns else [None] * len(frame)
    windows = pd.DataFrame(
        [site_motif_window(key, peptide, sequences) for key, peptide in zip(keys, frame["UPD_seq"].tolist())],
        index=frame.index,
        columns=["UPD_seq", *KSEA_EXPORT_COLUMNS[1:]],
    )
    result["UPD_seq"] = windows["UPD_seq"]
    result["PTM_Collapse_key"] = keys
    for column in KSEA_EXPORT_COLUMNS[1:]:
        result[column] = windows[column]
    # Present only when the volcano ran on imputed values (see stats_tools).
    for column in frame.columns:
        if column.startswith(("n_imputed__", "n_measured__", "n_fully_imputed__", "n_partially_imputed__")) or column == "imputed_values":
            result[column] = frame[column].to_numpy()
    return result


def _ksea_control_table(
    *,
    organism: str = "human",
    condition1: str,
    condition2: str,
    condition1_control: str,
    condition2_control: str,
    data_source: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    test_type: str,
    use_uncorrected: bool,
) -> pd.DataFrame:
    """Format the exact corrected Control Volcano result for Kinase Library upload."""
    from app.schemas.stats import VolcanoControlRequest
    from app.services.stats_tools import run_volcano_control

    volcano = run_volcano_control(
        VolcanoControlRequest(
            kind="phospho",
            dataSource=data_source,
            condition1=condition1,
            condition2=condition2,
            condition1Control=condition1_control,
            condition2Control=condition2_control,
            identifier="workflow",
            pValueThreshold=p_value_threshold,
            log2fcThreshold=log2fc_threshold,
            testType=test_type,
            useUncorrected=use_uncorrected,
        )
    )
    frame = pd.DataFrame(volcano.rows)
    required = {"UPD_seq", "log2FC", "pval", "adj_pval", "selected_pval", "significance"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "Control Volcano output is missing Kinase Library columns: " + ", ".join(missing)
        )

    return _ksea_format(frame, organism)


def _ksea_standard_table(
    *,
    organism: str = "human",
    condition1: str,
    condition2: str,
    data_source: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    test_type: str,
    use_uncorrected: bool,
) -> pd.DataFrame:
    """Format the exact standard Volcano result for Kinase Library upload."""
    from app.services.stats_tools import _volcano_dataframe

    source_frame, source_metadata, _ = _ksea_context(data_source=data_source)
    _, _, frame, _ = _volcano_dataframe(
        kind="phospho",
        data_source=data_source,
        condition1=condition1,
        condition2=condition2,
        identifier="workflow",
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
        frame_override=source_frame,
        metadata_override=source_metadata,
    )
    required = {"UPD_seq", "log2FC", "pval", "adj_pval", "selected_pval", "significance"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("Volcano output is missing Kinase Library columns: " + ", ".join(missing))

    return _ksea_format(frame, organism)


def ksea_table(
    *,
    condition1: str,
    condition2: str,
    source: str = "volcano",
    data_source: str = "data",
    condition1_control: str | None = None,
    condition2_control: str | None = None,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    organism: str = "human",
) -> pd.DataFrame:
    organism = _resolve_ksea_organism(organism)
    source_mode = str(source).strip().lower()
    if source_mode not in {"volcano", "volcano_control"}:
        raise ValueError("Unsupported Kinase Library source. Choose 'volcano' or 'volcano_control'.")
    data_mode = str(data_source).strip().lower()
    if data_mode not in DATA_SOURCES:
        raise ValueError("Unsupported Kinase Library data source. Choose 'data', 'filtered', or 'imputed'.")

    if source_mode == "volcano_control":
        if not condition1_control or not condition2_control:
            raise ValueError("Volcano Control source requires both control conditions.")
        unique_conditions = {
            str(condition1).strip(),
            str(condition2).strip(),
            str(condition1_control).strip(),
            str(condition2_control).strip(),
        }
        if len([value for value in unique_conditions if value]) < 4:
            raise ValueError("Volcano Control source requires four different conditions.")
        return _ksea_control_table(
            organism=organism,
            condition1=condition1,
            condition2=condition2,
            condition1_control=condition1_control,
            condition2_control=condition2_control,
            data_source=data_mode,
            p_value_threshold=p_value_threshold,
            log2fc_threshold=log2fc_threshold,
            test_type=test_type,
            use_uncorrected=use_uncorrected,
        )

    return _ksea_standard_table(
        organism=organism,
        condition1=condition1,
        condition2=condition2,
        data_source=data_mode,
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
    )


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
    for column, name in names.items():
        if name in {"substratecount", "numberofsubstrates", "nsubstrates"}:
            values = pd.to_numeric(data[column], errors="coerce")
            missing = data[column].isna() | data[column].astype(str).str.strip().eq("")
            if ((~missing & ~np.isfinite(values)) | (values < 0) | (values.notna() & (values % 1 != 0))).any():
                raise ValueError("Substrate counts must be nonnegative integers.")
            if "substrate_count" in frame:
                previous = frame["substrate_count"]
                if (previous.notna() & values.notna() & previous.ne(values)).any():
                    raise ValueError("Conflicting substrate counts.")
                values = previous.fillna(values)
            frame["substrate_count"] = values
    return frame


# Classes of the uploaded Kinase Library results; see ksea_uploaded_volcano_html.
KINASE_ENRICHED_UP = "Enriched in up-regulated sites"
KINASE_ENRICHED_DOWN = "Enriched in down-regulated sites"


def ksea_uploaded_volcano_html(
    *,
    st_results: pd.DataFrame,
    tnc_results: pd.DataFrame,
    p_value_threshold: float = 0.1,
    header: bool = True,
    condition1: str = "",
    condition2: str = "",
    condition1_control: str = "",
    condition2_control: str = "",
    annotate_hits: bool = False,
    advanced: dict | None = None,
    evidence_out: dict | None = None,
) -> str:
    go = _get_plotly_go()
    if not 0 < p_value_threshold <= 1:
        raise ValueError("Kinase Library adjusted p-value threshold must be between zero and one.")
    df = pd.concat([_normalize_ksea_results(st_results).assign(result_group="S/T"),
                    _normalize_ksea_results(tnc_results).assign(result_group="Y")], ignore_index=True)
    if df.empty:
        raise ValueError("Uploaded Kinase Library result files are empty.")

    frame = df.rename(columns={"Kinase": "kinase", "Log2(Frequency Factor)": "log2ff", "Adjusted p-value": "adj_pval"})
    frame["neg_log10_pval"] = -np.log10(frame["adj_pval"].clip(lower=1e-300))

    # The Kinase Library frequency factor compares a kinase's motif frequency
    # among up- and down-regulated sites. A significant positive value means the
    # motif is enriched among sites higher in condition 1 -- motif enrichment,
    # not a measured change in kinase activity -- and the classes say so.
    def classify(row: pd.Series) -> str:
        if float(row["adj_pval"]) < p_value_threshold:
            if float(row["log2ff"]) > 0:
                return KINASE_ENRICHED_UP
            if float(row["log2ff"]) < 0:
                return KINASE_ENRICHED_DOWN
        return "Not significant"

    frame["regulation"] = frame.apply(classify, axis=1)
    if evidence_out is not None:
        evidence_out.update({"type": "external_ksea", "threshold": p_value_threshold,
            "condition1": condition1, "condition2": condition2,
            "condition1Control": condition1_control, "condition2Control": condition2_control,
            "totalRows": len(frame), "counts": frame["regulation"].value_counts().to_dict(),
            "rows": json_records(frame, 10),
            "limitations": "Uploaded external results; adjustment procedure is not independently verified. Substrate counts are included only when explicitly supplied; absent counts are unknown. Frequency factor is not a direct activity measurement."})
    color_map = {
        KINASE_ENRICHED_UP: "red",
        KINASE_ENRICHED_DOWN: "blue",
        "Not significant": "lightgrey",
    }

    fig = go.Figure()
    for regulation in [KINASE_ENRICHED_UP, KINASE_ENRICHED_DOWN, "Not significant"]:
        subset = frame[frame["regulation"] == regulation]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["log2ff"],
                y=subset["neg_log10_pval"],
                mode="markers",
                # The Points card: size, opacity, outline and shape. The class
                # keeps its own colour, which is why the card has no colour
                # field on this plot.
                marker=plotly_marker(
                    advanced,
                    size=10,
                    alpha=1.0,
                    color=color_map[regulation],
                    edge_width_default=0.5,
                    edge_color_default="black",
                ),
                name=regulation,
                text=subset["kinase"],
                hovertemplate=(
                    "Kinase: %{text}<br>Log2(Frequency Factor): %{x:.4f}<br>"
                    "-log10(Adjusted p-value): %{y:.4f}<br>Regulation: "
                    f"{regulation}<extra></extra>"
                ),
            )
        )

    if annotate_hits:
        significant_main = frame[frame["regulation"] != "Not significant"]
        if not significant_main.empty:
            fig.add_trace(
                go.Scatter(
                    x=significant_main["log2ff"],
                    y=significant_main["neg_log10_pval"],
                    mode="text",
                    text=significant_main["kinase"],
                    textposition="top right",
                    textfont=dict(color="black", size=10),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
    y_line = float(-np.log10(max(float(p_value_threshold), 1e-300)))
    threshold_line = resolve_reference_line(advanced, color="green")
    if threshold_line.visible:
        fig.add_hline(y=y_line, line=threshold_line.plotly())

    title = ""
    if header:
        if condition1 and condition2:
            title = f"Kinase Library Motif Enrichment: {condition1} vs. {condition2}"
            if condition1_control and condition2_control:
                title += f" (controls: {condition1_control} vs {condition2_control})"
        else:
            title = "Kinase Library Motif Enrichment"

    x_label = "Log2(Frequency Factor)"
    if condition1 and condition2:
        x_label = f"Log2(Frequency Factor) (contrast: {comparison_contrast(condition1, condition2, condition1_control, condition2_control)})"

    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title="-log10(Adjusted p-value)",
        template="plotly_white",
        hovermode="closest",
        margin=dict(l=40, r=20, t=60 if header else 30, b=40),
    )
    fig.update_layout(**advanced_plotly_layout(advanced))
    return _plotly_html(fig)


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
    data_source: str = "data",
) -> pd.DataFrame:
    if str(condition1).strip() == str(condition2).strip():
        raise ValueError("Select two different conditions to plot.")

    label_col = "PTM_Collapse_key"
    group_col = "Protein_group"
    from app.services.stats_tools import _volcano_dataframe

    source_frame, source_metadata, _ = _phospho_regulation_context(data_source)
    _, _, volcano_df, _ = _volcano_dataframe(
        kind="phospho",
        data_source=data_source,
        condition1=condition1,
        condition2=condition2,
        identifier="workflow",
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
        frame_override=source_frame,
        metadata_override=source_metadata,
    )
    required = {label_col, group_col, "log2FC", "pval", "adj_pval", "significance"}
    missing = sorted(required.difference(volcano_df.columns))
    if missing:
        raise ValueError(
            "Volcano output is missing phosphoprotein-regulation columns: "
            + ", ".join(missing)
        )

    def truncate_items(items: list[str]) -> str:
        if len(items) > max_hover_sites:
            return ";".join(items[:max_hover_sites]) + f";... (+{len(items) - max_hover_sites} more)"
        return ";".join(items)

    rows: list[dict[str, object]] = []
    for protein_group, group in volcano_df.groupby(group_col):
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
        # The magnitude of the down-regulated sum; abs() rather than a sign flip,
        # so a protein without down-regulated sites reads 0, not -0.0.
        down_sum = abs(float(down["log2FC"].astype(float).sum()))
        up_sum = float(up["log2FC"].astype(float).sum())

        rows.append(
            {
                "Protein_group": str(protein_group),
                "Downregulated_sites": truncate_items(down_sites) if show_phosphosites else "",
                "Upregulated_sites": truncate_items(up_sites) if show_phosphosites else "",
                "Downregulated_site_effects": truncate_items(down_effects) if show_phosphosites else "",
                "Upregulated_site_effects": truncate_items(up_effects) if show_phosphosites else "",
                "Downregulated_count": int(len(down_sites)),
                "Upregulated_count": int(len(up_sites)),
                "Downregulated_log2FC_sum": down_sum,
                "Upregulated_log2FC_sum": up_sum,
            }
        )

    collapsed_df = pd.DataFrame(
        rows,
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
    if collapsed_df.empty:
        collapsed_df["x"] = pd.Series(dtype=float)
        collapsed_df["y"] = pd.Series(dtype=float)
        collapsed_df["color_val"] = pd.Series(dtype=float)
        return collapsed_df
    collapsed_df["x"] = collapsed_df["Upregulated_log2FC_sum"]
    collapsed_df["y"] = collapsed_df["Downregulated_log2FC_sum"]
    collapsed_df["color_val"] = collapsed_df["x"] - collapsed_df["y"]
    return collapsed_df.sort_values("Protein_group").reset_index(drop=True)


PHOSPROT_REGULATION_EMPTY_MESSAGE = (
    "No phosphosites pass the selected significance and fold-change thresholds"
)


def _empty_phosprot_regulation_html(
    *, header: bool = True, advanced: dict | None = None
) -> str:
    """An empty figure that says why it is empty, matching the PNG."""
    go = _get_plotly_go()
    fig = go.Figure()
    fig.update_layout(
        title="Cumulative Significant Phosphosite Regulation by Protein" if header else "",
        template="plotly_white",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=40, r=20, t=60 if header else 30, b=40),
        annotations=[
            dict(
                text=PHOSPROT_REGULATION_EMPTY_MESSAGE,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
        ],
    )
    fig.update_layout(**advanced_plotly_layout(advanced))
    return _plotly_html(fig)


def _phosprot_regulation_figure(
    table: pd.DataFrame, header: bool = True, advanced: dict | None = None
):
    px = _get_plotly()
    fig = px.scatter(
        table,
        x="x",
        y="y",
        hover_data={
            "Protein_group": True,
            "Upregulated_count": True,
            "Downregulated_count": True,
            "Upregulated_site_effects": True,
            "Downregulated_site_effects": True,
        },
        color="color_val",
        color_continuous_scale=[(0, "blue"), (0.5, "grey"), (1, "red")],
        labels={
            "x": "Cumulative Significant Up-Site log2FC",
            "y": "Cumulative Significant Down-Site |log2FC|",
        },
        opacity=0.7,
    )
    fig.update_traces(
        marker=plotly_marker(
            advanced,
            size=8,
            use_color=False,
            edge_width_default=0.5,
            edge_color_default="DarkSlateGrey",
        ),
        text=None,
    )
    fig.update_layout(
        title="Cumulative Significant Phosphosite Regulation by Protein" if header else "",
        xaxis_title="Cumulative Significant Up-Site log2FC",
        yaxis_title="Cumulative Significant Down-Site |log2FC|",
        template="plotly_white",
        coloraxis_colorbar=dict(title="Up score - Down score"),
        margin=dict(l=40, r=20, t=60 if header else 30, b=40),
    )
    return fig


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
    data_source: str = "data",
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 220,
    advanced: dict | None = None,
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
        data_source=data_source,
    )
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    if table.empty:
        ax.text(
            0.5,
            0.5,
            PHOSPROT_REGULATION_EMPTY_MESSAGE,
            ha="center",
            va="center",
        )
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    scatter = ax.scatter(
        table["x"].to_numpy(dtype=float),
        table["y"].to_numpy(dtype=float),
        c=table["color_val"].to_numpy(dtype=float),
        cmap="coolwarm",
        # `use_color=False`: this scatter colours its points from `color_val`
        # through the colour map, so it must not also be handed one colour.
        # marker_style supplies edgecolors; the outline is off unless asked for.
        **marker_style(advanced, size=4.5, alpha=0.75, use_color=False),
    )
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Up score - Down score")
    ax.set_xlabel("Cumulative Significant Up-Site log2FC")
    ax.set_ylabel("Cumulative Significant Down-Site |log2FC|")
    if header:
        ax.set_title("Cumulative Significant Phosphosite Regulation by Protein")
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def phosprot_regulation_html(
    *,
    condition1: str,
    condition2: str,
    p_value_threshold: float = 0.05,
    log2fc_threshold: float = 1.0,
    test_type: str = "unpaired",
    use_uncorrected: bool = False,
    max_hover_sites: int = 20,
    show_phosphosites: bool = True,
    data_source: str = "data",
    header: bool = True,
    advanced: dict | None = None,
) -> str:
    table = phosprot_regulation_table(
        condition1=condition1,
        condition2=condition2,
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
        max_hover_sites=max_hover_sites,
        show_phosphosites=show_phosphosites,
        data_source=data_source,
    )
    if table.empty:
        # The same empty result the PNG draws an explanation for. It used to
        # raise here, so the interactive view answered a legitimate question --
        # "does anything pass these thresholds?" -- with an error in the frame
        # while the static view answered it with a sentence. One question, one
        # answer, whichever renderer the Type selector is on.
        return _empty_phosprot_regulation_html(header=header, advanced=advanced)
    fig = _phosprot_regulation_figure(table, header=header, advanced=advanced)
    fig.update_layout(**advanced_plotly_layout(advanced))
    return _plotly_html(fig)


apply_cached_wrappers(
    globals(),
    [
        "phospho_options",
        "phosphosite_plot_table",
        "phosphosite_plot_png",
        "phospho_coverage_table",
        "phospho_coverage_png",
        "phospho_distribution_table",
        "phospho_distribution_png",
        "phospho_sty_table",
        "phospho_sty_png",
        "ksea_table",
        "phosprot_regulation_table",
        "phosprot_regulation_png",
        "phosprot_regulation_html",
    ],
)
