from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib import ticker as mtick

from app.schemas.peptide import PeptideSpecies
from app.services.annotation_store import get_annotation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import get_current_dataset


def _get_plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"format": "png", "dpi": max(72, int(dpi))}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    fig.savefig(buf, **save_kwargs)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _cm_to_inch(value_cm: float) -> float:
    return max(1.0, float(value_cm) / 2.54)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _legacy_root() -> Path:
    return _project_root().parent / "Proteomics-CoPYlot"


def _peptide_dataset_path() -> Path:
    stored = get_current_dataset("peptide")
    if stored is None or not hasattr(stored, "path"):
        raise ValueError("No peptide dataset path is currently loaded. Upload a peptide dataset path first.")
    path = Path(str(stored.path)).expanduser()
    if not path.exists():
        raise ValueError(f"Peptide dataset file does not exist: {path}")
    return path


@lru_cache(maxsize=4)
def _load_peptide_frame_cached(path_str: str, modified_ns: int) -> pd.DataFrame:
    path = Path(path_str)
    with path.open("rb") as handle:
        return read_dataframe(path.name, handle)


def get_peptide_frame() -> pd.DataFrame:
    path = _peptide_dataset_path()
    stat = path.stat()
    return _load_peptide_frame_cached(str(path), stat.st_mtime_ns).copy()


def _extract_id_or_number(value: object) -> str:
    text = str(value)
    matches = re.findall(r"\d+", text)
    return matches[-1] if matches else text


def _require_column(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        raise ValueError(f"Required peptide column '{column}' is missing.")
    return column


def _file_name_column(frame: pd.DataFrame) -> str:
    if "File.Name" in frame.columns:
        return "File.Name"
    matches = [column for column in frame.columns if "file" in str(column).lower()]
    if not matches:
        raise ValueError("Could not find a peptide file-name column.")
    return matches[0]


def _stripped_sequence_column(frame: pd.DataFrame) -> str:
    if "Stripped.Sequence" in frame.columns:
        return "Stripped.Sequence"
    matches = [
        column
        for column in frame.columns
        if "stripped" in str(column).lower() and "sequence" in str(column).lower()
    ]
    if not matches:
        raise ValueError("Could not find a stripped-sequence column in the peptide dataset.")
    return matches[0]


def _protein_names_column(frame: pd.DataFrame) -> str:
    return _require_column(frame, "ProteinNames")


def _prepare_metadata(frame: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    stored = get_annotation("protein")
    if stored is None or stored.metadata.empty:
        raise ValueError(
            "Protein annotation metadata is required for this plot. Generate protein annotation first."
        )

    meta = stored.metadata.copy()
    normalized = {str(column).strip().lower(): str(column) for column in meta.columns}
    if "sample" not in normalized or "condition" not in normalized:
        raise ValueError(
            "Protein annotation metadata must contain 'sample' and 'condition' columns."
        )

    meta = meta.rename(
        columns={
            normalized["sample"]: "sample",
            normalized["condition"]: "condition",
        }
    )[["sample", "condition"]].copy()
    meta["sample"] = meta["sample"].astype(str).str.strip()
    meta["condition"] = meta["condition"].astype(str).str.strip()
    meta = meta[(meta["sample"] != "") & (meta["condition"] != "")].reset_index(drop=True)
    if meta.empty:
        raise ValueError(
            "Protein annotation metadata does not contain any usable sample/condition rows."
        )

    file_col = _file_name_column(frame)
    file_names = frame[file_col].dropna().astype(str).unique().tolist()
    for name in file_names:
        meta["sample"] = np.where(meta["sample"] == name, name, meta["sample"])

    meta["id"] = meta["sample"].apply(_extract_id_or_number)
    meta["sample_index"] = meta.groupby("condition").cumcount() + 1
    if include_id:
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['sample_index']}\n({row['id']})",
            axis=1,
        )
    else:
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['sample_index']}",
            axis=1,
        )
    return meta


def peptide_overview() -> dict[str, object]:
    path = _peptide_dataset_path()
    frame = get_peptide_frame()
    warnings: list[str] = []
    if "ProteinNames" in frame.columns:
        first_proteins = (
            frame["ProteinNames"]
            .astype(str)
            .str.split(";")
            .str[0]
            .str.strip()
        )
        proteins = sorted({value for value in first_proteins.tolist() if value})
    else:
        proteins = []
        warnings.append("ProteinNames is missing, so sequence coverage is unavailable for this peptide dataset.")
    protein_annotation = get_annotation("protein")
    metadata_loaded = protein_annotation is not None and not protein_annotation.metadata.empty
    metadata_name = (
        "Protein Annotation (Data > Annotation)"
        if metadata_loaded
        else None
    )
    if not metadata_loaded:
        warnings.append(
            "Protein annotation metadata is required for modification and missed cleavage plots. Generate protein annotation in Data > Annotation."
        )

    return {
        "filename": path.name,
        "path": str(path),
        "rows": len(frame),
        "columns": len(frame.columns),
        "columnNames": [str(column) for column in frame.columns],
        "availableProteins": proteins,
        "metadataLoaded": metadata_loaded,
        "metadataFilename": metadata_name,
        "warnings": warnings,
    }


def peptide_rt_plot(
    *,
    method: str = "Hexbin Plot",
    add_line: bool = False,
    bins: int = 1000,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 15,
    dpi: int = 100,
) -> bytes:
    plt = _get_plt()
    frame = get_peptide_frame()
    _require_column(frame, "Predicted.RT")
    _require_column(frame, "RT")

    data = frame[["Predicted.RT", "RT"]].apply(pd.to_numeric, errors="coerce").dropna()
    if data.empty:
        raise ValueError("No numeric Predicted.RT / RT values are available for the retention-time plot.")

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi)))
    if method == "Scatter Plot":
        if len(data) > 100000:
            data = data.sample(n=100000, random_state=69)
        ax.scatter(data["Predicted.RT"], data["RT"], alpha=0.2, s=1)
    elif method == "Density Plot":
        from matplotlib.colors import LogNorm

        hist = ax.hist2d(
            data["Predicted.RT"],
            data["RT"],
            bins=max(10, min(2000, int(bins))),
            norm=LogNorm(),
        )
        fig.colorbar(hist[3], ax=ax)
    else:
        hb = ax.hexbin(
            data["Predicted.RT"],
            data["RT"],
            gridsize=max(10, min(2000, int(bins))),
            cmap="Blues",
        )
        fig.colorbar(hb, ax=ax)

    if add_line:
        x_min = float(data["Predicted.RT"].min())
        x_max = float(data["Predicted.RT"].max())
        ax.plot([x_min, x_max], [x_min, x_max], ls="--", color="red")

    ax.set_xlabel("Predicted RT")
    ax.set_ylabel("Actual RT")
    ax.set_title("Retention Time Plot" if header else "")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def peptide_modification_plot(
    *,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 25,
    height_cm: float = 15,
    dpi: int = 100,
) -> bytes:
    plt = _get_plt()
    frame = get_peptide_frame()
    meta = _prepare_metadata(frame, include_id=include_id)
    file_col = _file_name_column(frame)
    _require_column(frame, "Modified.Sequence")
    _require_column(frame, "Precursor.Quantity")

    wide = (
        frame.pivot_table(
            index=file_col,
            columns="Modified.Sequence",
            values="Precursor.Quantity",
            aggfunc="max",
        )
        .T.reset_index()
    )
    wide.columns = [
        _extract_id_or_number(column) if str(column) != "Modified.Sequence" else "Modified.Sequence"
        for column in wide.columns
    ]

    rename_map = dict(zip(meta["id"], meta["new_sample"]))
    wide = wide.rename(columns=rename_map)
    ordered_samples = meta["new_sample"].tolist()
    annotated_cols = [column for column in ordered_samples if column in wide.columns]
    if not annotated_cols:
        raise ValueError(
            "Protein annotation metadata does not match any peptide sample columns after normalization."
        )

    filtered = wide[["Modified.Sequence", *annotated_cols]].copy()

    def get_mod_count(pattern: str) -> pd.Series:
        subset = filtered[filtered["Modified.Sequence"].astype(str).str.contains(pattern, na=False)].copy()
        if subset.empty:
            return pd.Series(0, index=filtered.columns[1:], dtype=float)
        for column in subset.columns[1:]:
            subset[column] = subset[column].notna().astype(int)
        return subset.iloc[:, 1:].sum(axis=0)

    carb = get_mod_count("UniMod:4|Carbamidomethyl")
    oxi = get_mod_count("UniMod:35|Oxidation")
    ace = get_mod_count("UniMod:1|Acetyl")

    plot_data = pd.DataFrame(
        {
            "Sample": list(carb.index) * 3,
            "Count": list(carb.values) + list(oxi.values) + list(ace.values),
            "Modification": (["Carbamylation"] * len(carb))
            + (["Oxidation"] * len(oxi))
            + (["Acetylation"] * len(ace)),
        }
    )
    plot_data = plot_data[plot_data["Count"] > 0]
    plot_data["Sample"] = pd.Categorical(plot_data["Sample"], categories=ordered_samples, ordered=True)
    plot_data = plot_data.sort_values("Sample")

    mod_colors = {
        "Carbamylation": "blue",
        "Oxidation": "red",
        "Acetylation": "green",
    }
    found_mods = [
        value
        for value in ["Carbamylation", "Oxidation", "Acetylation"]
        if value in plot_data["Modification"].unique()
    ]

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi)))
    x = np.arange(len(ordered_samples))
    bar_width = 0.25
    offsets = np.linspace(-bar_width, bar_width, max(1, len(found_mods)))

    for modification, offset in zip(found_mods, offsets):
        subset = plot_data[plot_data["Modification"] == modification]
        indices = [ordered_samples.index(sample) for sample in subset["Sample"]]
        ax.bar(
            np.array(indices) + offset,
            subset["Count"],
            width=bar_width,
            label=modification,
            color=mod_colors.get(modification),
        )

    ax.set_xticks(x)
    ax.set_xticklabels(ordered_samples, rotation=90)
    ax.set_xlabel("Sample")
    ax.set_ylabel("Number of modified peptides")
    ax.set_title("Modifications per sample" if header else "")
    if legend and found_mods:
        ax.legend(title="Modification", bbox_to_anchor=(1.05, 1), loc="upper left")

    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def peptide_missed_cleavage_plot(
    *,
    include_id: bool = False,
    text: bool = True,
    text_size: int = 8,
    header: bool = True,
    width_cm: float = 25,
    height_cm: float = 15,
    dpi: int = 100,
) -> bytes:
    plt = _get_plt()
    frame = get_peptide_frame()
    meta = _prepare_metadata(frame, include_id=include_id)
    file_col = _file_name_column(frame)
    seq_col = _stripped_sequence_column(frame)
    _require_column(frame, "Precursor.Quantity")

    wide = (
        frame.pivot_table(
            index=file_col,
            columns=seq_col,
            values="Precursor.Quantity",
            aggfunc="max",
        )
        .T.reset_index()
    )
    wide = wide.rename(columns={"index": seq_col})
    wide.columns = [
        _extract_id_or_number(column) if str(column) != seq_col else seq_col
        for column in wide.columns
    ]

    rename_map = dict(zip(meta["id"], meta["new_sample"]))
    wide = wide.rename(columns=rename_map)
    annotated_cols = [column for column in meta["new_sample"].tolist() if column in wide.columns]
    if not annotated_cols:
        raise ValueError(
            "Protein annotation metadata does not match any peptide sample columns after normalization."
        )

    filtered = wide[[seq_col, *annotated_cols]].copy()

    def count_all_rk(sequence: str) -> int:
        return max(0, sequence.count("R") + sequence.count("K") - 1)

    rk_counts = [count_all_rk(str(sequence)) for sequence in filtered[seq_col].tolist()]
    for column in filtered.columns[1:]:
        filtered[column] = np.where(filtered[column].notna(), rk_counts, np.nan)

    plot_data = filtered.melt(id_vars=seq_col, var_name="Sample", value_name="Count").dropna()
    if plot_data.empty:
        raise ValueError("No peptide intensities are available to calculate missed cleavages.")
    plot_data["Count"] = plot_data["Count"].astype(int)

    summary = plot_data.groupby(["Sample", "Count"]).size().reset_index(name="Occurrences")
    summary["Total"] = summary.groupby("Sample")["Occurrences"].transform("sum")
    summary["Percentage"] = (summary["Occurrences"] / summary["Total"]) * 100.0

    sample_order = meta["new_sample"].tolist()
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=sample_order, ordered=True)

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi)))
    counts_sorted = sorted(summary["Count"].unique())
    bottom = np.zeros(len(sample_order))

    for count in counts_sorted:
        subset = (
            summary[summary["Count"] == count]
            .set_index("Sample")
            .reindex(sample_order)["Percentage"]
            .fillna(0.0)
        )
        ax.bar(range(len(sample_order)), subset, bottom=bottom, label=str(count))
        bottom += subset.to_numpy(dtype=float)

    ax.set_ylabel("Percentage of peptides with missed cleavage (%)")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_title("Missed cleavages per sample" if header else "")
    ax.set_xticks(range(len(sample_order)))
    ax.set_xticklabels(sample_order, rotation=90)

    if text:
        single = (
            summary[summary["Count"] == 1]
            .set_index("Sample")
            .reindex(sample_order)["Percentage"]
            .fillna(0.0)
        )
        base_y = float(bottom.max()) * 0.03 if len(bottom) else 0.0
        for index, value in enumerate(single.tolist()):
            ax.text(index, base_y, f"{value:.1f}%", ha="center", va="bottom", fontsize=text_size)

    ax.legend(title="Number", bbox_to_anchor=(1.05, 1), loc="upper left")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _split_protein_names(value: object) -> list[str]:
    return [token.strip() for token in str(value).split(";") if token.strip()]


@lru_cache(maxsize=4)
def _load_fasta_dataframe_cached(path_str: str, modified_ns: int) -> pd.DataFrame:
    headers: list[str] = []
    sequences: list[str] = []
    current_header: str | None = None
    current_sequence: list[str] = []

    with Path(path_str).open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_header is not None:
                    headers.append(current_header)
                    sequences.append("".join(current_sequence))
                current_header = line[1:].split()[0]
                current_sequence = []
            else:
                current_sequence.append(line)

    if current_header is not None:
        headers.append(current_header)
        sequences.append("".join(current_sequence))

    frame = pd.DataFrame({"full_header": headers, "V1": sequences})
    frame["name"] = frame["full_header"].apply(lambda value: str(value).split("|")[-1])
    frame["accession"] = frame["full_header"].apply(
        lambda value: str(value).split("|")[1] if "|" in str(value) else str(value)
    )
    return frame


def _fasta_path(species: PeptideSpecies) -> Path:
    filename = "UP000005640_9606.fasta" if species == "human" else "UP000000589_10090.fasta"
    candidates = [
        _project_root() / "data" / "db" / filename,
        _legacy_root() / "data" / "db" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise ValueError(f"Could not find FASTA database for {species}. Checked: {searched}")


def _load_fasta_dataframe(species: PeptideSpecies) -> pd.DataFrame:
    path = _fasta_path(species)
    stat = path.stat()
    return _load_fasta_dataframe_cached(str(path), stat.st_mtime_ns).copy()


def _coverage_visualization(
    frame: pd.DataFrame,
    db: pd.DataFrame,
    protein: str,
    chunk_size: int = 30,
) -> str:
    protein_col = _protein_names_column(frame)
    seq_col = _stripped_sequence_column(frame)
    filtered = frame[frame[protein_col].astype(str).str.contains(rf"\b{re.escape(protein)}\b", regex=True, na=False)]
    found_sequences = filtered[seq_col].dropna().astype(str).unique()

    sequence_row = db.loc[db["name"] == protein, "V1"]
    if sequence_row.empty:
        raise ValueError(f"No sequence found in the selected database for protein: {protein}")
    sequence = str(sequence_row.iloc[0])

    n = len(sequence)
    result_sequences = ["-" * n]

    for peptide in found_sequences:
        for match in re.finditer(re.escape(peptide), sequence):
            start_pos, end_pos = match.start(), match.end()
            placed = False
            for index, result_sequence in enumerate(result_sequences):
                if result_sequence[start_pos:end_pos] == "-" * len(peptide):
                    result_sequences[index] = (
                        result_sequence[:start_pos] + peptide + result_sequence[end_pos:]
                    )
                    placed = True
                    break
            if not placed:
                new_sequence = "-" * n
                new_sequence = new_sequence[:start_pos] + peptide + new_sequence[end_pos:]
                result_sequences.append(new_sequence)

    number_line = ""
    count = 10
    for index in range(1, n + 1):
        if index % count == 0:
            number_line += " " * (10 - len(str(count))) + str(count)
            count += 10

    starts = range(0, n, 10)
    chunks = [sequence[start : start + 10] for start in starts]
    number_chunks = [number_line[start : start + 10] for start in starts]

    result_chunk_list: list[str] = []
    for result_sequence in result_sequences:
        result_chunks = [result_sequence[start : start + 10] for start in starts]
        result_chunk_list.append(" ".join(result_chunks))

    sequence_str = " ".join(chunks)
    number_str = " ".join(number_chunks)

    effective_chunk_size = int(chunk_size * 1.1)
    seq_length = len(sequence_str)
    starts2 = range(0, seq_length, effective_chunk_size)
    lines = [sequence_str[start : start + effective_chunk_size] for start in starts2]
    number_lines = [number_str[start : start + effective_chunk_size] for start in starts2]

    result_lines_list: list[list[str]] = []
    for result_chunk in result_chunk_list:
        result_lines = [result_chunk[start : start + effective_chunk_size] for start in starts2]
        result_lines_list.append(result_lines)

    output_lines: list[str] = []
    for index in range(len(lines)):
        output_lines.append(number_lines[index])
        for result in reversed(result_lines_list):
            output_lines.append(result[index])
        output_lines.append(lines[index])
        output_lines.append("")

    return "\n".join(output_lines)


def peptide_sequence_coverage(
    *,
    species: PeptideSpecies,
    protein: str,
    chunk_size: int = 100,
) -> dict[str, object]:
    if not protein.strip():
        raise ValueError("A protein must be selected for sequence coverage.")

    frame = get_peptide_frame()
    protein_col = _protein_names_column(frame)
    seq_col = _stripped_sequence_column(frame)
    filtered = frame[
        frame[protein_col].astype(str).str.contains(rf"\b{re.escape(protein)}\b", regex=True, na=False)
    ]
    peptides = filtered[seq_col].dropna().astype(str).unique().tolist()
    if not peptides:
        raise ValueError(f"No peptides were found for protein '{protein}'.")

    db = _load_fasta_dataframe(species)
    sequence_row = db.loc[db["name"] == protein, "V1"]
    if sequence_row.empty:
        raise ValueError(f"The selected protein variant '{protein}' does not exist in the loaded database.")
    sequence = str(sequence_row.iloc[0])

    coverage_mask = [0] * len(sequence)
    for peptide in peptides:
        for match in re.finditer(re.escape(peptide), sequence):
            for index in range(match.start(), match.end()):
                coverage_mask[index] = 1

    coverage_percent = round((sum(coverage_mask) / len(sequence)) * 100.0, 2)
    coverage_text = _coverage_visualization(frame, db, protein, chunk_size=chunk_size)

    return {
        "protein": protein,
        "species": species,
        "coveragePercent": coverage_percent,
        "matchingPeptideCount": len(peptides),
        "sequenceText": coverage_text,
        "warnings": [],
    }
