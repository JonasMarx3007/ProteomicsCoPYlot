from __future__ import annotations


from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
    cm_to_px as _cm_to_px,
)

import logging

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from matplotlib import ticker as mtick

from app.schemas.peptide import PeptideSpecies
from app.services.annotation_store import get_annotation
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import get_current_dataset
from app.services.functions import extract_sample_id as _extract_id_or_number
from app.services.functions import sample_id_map
from app.services.peptide_metadata_store import get_peptide_metadata
from app.services.plot_styling import (
    advanced_plotly_layout,
    apply_advanced_axes,
    advanced_label_size,
    marker_style,
    plotly_marker,
    resolve_reference_line,
)
from app.services.reference_db import resolve_reference_db
from app.services.plotting_common import get_plt as _get_plt, get_plotly_go as _get_plotly, plotly_html as _plotly_html, truncate_hover_text as _truncate_hover_text


LOGGER = logging.getLogger(__name__)

PEPTIDE_MODIFICATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "Carbamidomethylation": re.compile(
        r"(?:UniMod:4(?!\d)|(?<![A-Za-z])Carbamidomethyl(?:ation)?(?![A-Za-z]))",
        re.IGNORECASE,
    ),
    "Oxidation": re.compile(
        r"(?:UniMod:35(?!\d)|(?<![A-Za-z])Oxidation(?![A-Za-z]))",
        re.IGNORECASE,
    ),
    "Acetylation": re.compile(
        r"(?:UniMod:1(?!\d)|(?<![A-Za-z])Acetyl(?:ation)?(?![A-Za-z]))",
        re.IGNORECASE,
    ),
}


def peptide_modification_counts(
    frame: pd.DataFrame,
    *,
    sequence_column: str,
    sample_columns: list[str],
) -> pd.DataFrame:
    """Count detected modified sequences per sample using shared exact classifiers.

    Each sequence contributes at most once to a modification class in a sample,
    even if the sequence contains that modification more than once. A sequence
    carrying multiple tracked classes contributes once to each relevant class
    but only once to ``UniqueTrackedModifiedPeptides``.
    """
    if sequence_column not in frame.columns:
        raise ValueError("Modified sequence column is missing.")
    missing_samples = [column for column in sample_columns if column not in frame.columns]
    if missing_samples:
        raise ValueError("Modification count sample columns are missing from the peptide table.")

    sequences = frame[sequence_column].fillna("").astype(str)
    quantities = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    quantities = quantities.replace([np.inf, -np.inf], np.nan).replace(0, np.nan)
    detected = quantities.notna()
    detected_by_sequence = detected.groupby(sequences, sort=False).any()
    unique_sequences = pd.Series(
        detected_by_sequence.index.astype(str),
        index=detected_by_sequence.index,
        dtype="string",
    )

    counts = pd.DataFrame(index=sample_columns, dtype="int64")
    matched_masks: list[pd.Series] = []
    for modification, pattern in PEPTIDE_MODIFICATION_PATTERNS.items():
        matched = unique_sequences.str.contains(pattern, na=False)
        matched_masks.append(matched)
        counts[modification] = (
            detected_by_sequence.loc[matched].sum(axis=0).astype("int64")
        )

    any_tracked = (
        pd.concat(matched_masks, axis=1).any(axis=1)
        if matched_masks
        else pd.Series(False, index=detected_by_sequence.index)
    )
    counts["UniqueTrackedModifiedPeptides"] = (
        detected_by_sequence.loc[any_tracked].sum(axis=0).astype("int64")
    )
    counts.index.name = "Sample"
    return counts








def _peptide_dataset_path() -> Path:
    stored = get_current_dataset("peptide")
    if stored is None or not hasattr(stored, "path"):
        raise ValueError("No peptide dataset path is currently loaded. Upload a peptide dataset path first.")
    path = Path(str(stored.path)).expanduser()
    if not path.exists():
        LOGGER.error("Peptide dataset file is missing: %s", path)
        raise ValueError(
            f"The peptide dataset file '{path.name}' is no longer available. "
            "Upload it again."
        )
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


def _peptide_feature_column(frame: pd.DataFrame) -> str | None:
    preferred = [
        "Stripped.Sequence",
        "Modified.Sequence",
        "Precursor.Id",
        "PrecursorID",
        "Precursor",
        "ProteinNames",
    ]
    for column in preferred:
        if column in frame.columns:
            return column
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "sequence" in normalized:
            return str(column)
    return None


def _short_sample_label(value: object, max_len: int = 14) -> str:
    text = str(value or "").strip()
    basename = re.split(r"[\\/]", text)[-1]
    candidate = basename.strip() or text
    return _truncate_hover_text(candidate, max_len=max_len)


PeptideProtease = Literal["trypsin", "trypsin_lysc"]

# Which residues are cleaved after, and whether a following proline blocks it.
#   trypsin       K and R, both proline-blocked (K-P and R-P are not cut).
#   trypsin_lysc  K and R, but the Lys-C component is not proline-inhibited, so
#                 K-P is cleaved. R is cut by trypsin only, so R-P stays blocked.
_PROTEASE_PROLINE_BLOCKED: dict[str, dict[str, bool]] = {
    "trypsin": {"K": True, "R": True},
    "trypsin_lysc": {"K": False, "R": True},
}

PROTEASE_LABELS: dict[str, str] = {
    "trypsin": "Trypsin",
    "trypsin_lysc": "Trypsin / Lys-C",
}


def normalize_protease(value: object) -> PeptideProtease:
    key = str(value or "trypsin").strip().lower().replace("-", "_").replace("/", "_")
    key = key.replace("__", "_")
    if key in {"trypsin_lysc", "trypsin_lys_c", "trypsinlysc"}:
        return "trypsin_lysc"
    if key == "trypsin":
        return "trypsin"
    raise ValueError("Protease must be 'trypsin' or 'trypsin_lysc'.")


def count_missed_cleavages(sequence: object, protease: object = "trypsin") -> int:
    """Count internal missed cleavage sites in a peptide sequence.

    A missed cleavage is a cleavable residue that is neither the C-terminal
    residue -- that one is the expected cut site, not a missed one -- nor
    blocked by a following proline. Proline blocking is protease dependent, so
    it is looked up rather than assumed; see _PROTEASE_PROLINE_BLOCKED.
    """
    rules = _PROTEASE_PROLINE_BLOCKED[normalize_protease(protease)]
    residues = str(sequence or "").strip().upper()
    total = 0
    for index in range(len(residues) - 1):
        proline_blocked = rules.get(residues[index])
        if proline_blocked is None:
            continue
        if proline_blocked and residues[index + 1] == "P":
            continue
        total += 1
    return total


def peptide_missed_cleavage_summary(
    frame: pd.DataFrame,
    *,
    sequence_column: str,
    sample_columns: list[str],
    protease: object = "trypsin",
) -> pd.DataFrame:
    """Summarize detected unique peptide sequences by missed-cleavage count."""
    resolved_protease = normalize_protease(protease)
    if sequence_column not in frame.columns:
        raise ValueError("Stripped sequence column is missing.")
    missing_samples = [column for column in sample_columns if column not in frame.columns]
    if missing_samples:
        raise ValueError("Missed-cleavage sample columns are missing from the peptide table.")

    sequences = frame[sequence_column].fillna("").astype(str).str.strip()
    quantities = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    quantities = quantities.replace([np.inf, -np.inf], np.nan).replace(0, np.nan)
    detected_by_sequence = quantities.notna().groupby(sequences, sort=False).any()
    detected_by_sequence = detected_by_sequence.loc[detected_by_sequence.index != ""]

    columns = ["Sample", "Count", "Occurrences", "Total", "Percentage"]
    if detected_by_sequence.empty:
        return pd.DataFrame(columns=columns)

    cleavage_counts = pd.Series(
        [
            count_missed_cleavages(sequence, resolved_protease)
            for sequence in detected_by_sequence.index
        ],
        index=detected_by_sequence.index,
        dtype="int64",
    )
    detected_counts = detected_by_sequence.astype("int64").mul(cleavage_counts, axis=0)
    long = (
        detected_counts.where(detected_by_sequence)
        .reset_index(names=sequence_column)
        .melt(id_vars=sequence_column, var_name="Sample", value_name="Count")
        .dropna(subset=["Count"])
    )
    if long.empty:
        return pd.DataFrame(columns=columns)

    long["Count"] = long["Count"].astype("int64")
    summary = long.groupby(["Sample", "Count"]).size().reset_index(name="Occurrences")
    summary["Total"] = summary.groupby("Sample")["Occurrences"].transform("sum")
    summary["Percentage"] = (summary["Occurrences"] / summary["Total"]) * 100.0
    return summary[columns]


def _protein_names_column(frame: pd.DataFrame) -> str:
    return _require_column(frame, "ProteinNames")


def _prepare_metadata(frame: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    protein_dataset = get_current_dataset("protein")
    if protein_dataset is not None:
        stored = get_annotation("protein")
        if stored is None or stored.metadata.empty:
            raise ValueError(
                "Protein annotation metadata is required for this plot because a protein "
                "dataset is loaded. Generate protein annotation first."
            )
        meta = stored.metadata.copy()
    else:
        peptide_metadata = get_peptide_metadata()
        if peptide_metadata is None or peptide_metadata.frame.empty:
            raise ValueError(
                "Peptide annotation metadata is required for this plot. Annotate the unique "
                "peptide file names in Data > Annotation first."
            )
        meta = peptide_metadata.frame.copy()

    normalized = {str(column).strip().lower(): str(column) for column in meta.columns}
    if "sample" not in normalized or "condition" not in normalized:
        raise ValueError(
            "Annotation metadata must contain 'sample' and 'condition' columns."
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
            "Annotation metadata does not contain any usable sample/condition rows."
        )

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


def _sample_rename_map(
    columns, meta: pd.DataFrame, key_column: str
) -> dict[str, str]:
    """Map run-name columns onto the metadata's display names.

    Exact run names are matched first: they are what the annotation normally
    carries, and they are always unambiguous. The number fallback runs only for
    metadata samples that do not name a run exactly.

    This used to rewrite every column to `extract_sample_id(column)` before
    matching, which reduces a name to its last number. Run sets following the
    common date_cellline_condition_replicate convention then collapse -- both
    20240110_HeLa_ctrl_01.raw and 20240110_HeLa_treat_01.raw become "01" -- so
    `wide` ended up with duplicate column labels and `dict(zip(...))` kept only
    the last metadata row per id. Selecting a sample then returned two columns,
    one of them the other condition's data under this condition's name.
    """
    run_columns = [str(column) for column in columns if str(column) != key_column]
    by_name = dict(
        zip(meta["sample"].astype(str).tolist(), meta["new_sample"].astype(str).tolist())
    )

    mapping = {column: by_name[column] for column in run_columns if column in by_name}
    leftover_columns = [column for column in run_columns if column not in by_name]
    leftover_samples = [sample for sample in by_name if sample not in run_columns]
    if leftover_columns and leftover_samples:
        # Both sides are checked: an ambiguous id is unusable whichever side it
        # comes from, and reporting it here names the offending files.
        id_to_column = sample_id_map(leftover_columns)
        sample_id_map(leftover_samples)
        for sample in leftover_samples:
            column = id_to_column.get(_extract_id_or_number(sample))
            if column is not None:
                mapping[column] = by_name[sample]
    return mapping


def peptide_overview() -> dict[str, object]:
    path = _peptide_dataset_path()
    frame = get_peptide_frame()
    warnings: list[str] = []
    try:
        file_col = _file_name_column(frame)
        sample_values = frame[file_col].dropna().astype(str).str.strip()
        available_samples = sample_values[sample_values != ""].drop_duplicates().tolist()
    except ValueError:
        available_samples = []
        warnings.append("A file-name column is missing, so sample annotation is unavailable.")

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
    protein_dataset = get_current_dataset("protein")
    if protein_dataset is not None:
        protein_annotation = get_annotation("protein")
        metadata_loaded = protein_annotation is not None and not protein_annotation.metadata.empty
        metadata_name = "Protein Annotation (Data > Annotation)" if metadata_loaded else None
        missing_metadata_warning = (
            "Protein annotation metadata is required for modification and missed cleavage "
            "plots because a protein dataset is loaded. Generate protein annotation in "
            "Data > Annotation."
        )
    else:
        peptide_metadata = get_peptide_metadata()
        metadata_loaded = peptide_metadata is not None and not peptide_metadata.frame.empty
        metadata_name = peptide_metadata.filename if metadata_loaded else None
        missing_metadata_warning = (
            "Peptide annotation metadata is required for modification and missed cleavage "
            "plots. Annotate the unique peptide file names in Data > Annotation."
        )
    if not metadata_loaded:
        warnings.append(missing_metadata_warning)

    return {
        "filename": path.name,
        "path": str(path),
        "rows": len(frame),
        "columns": len(frame.columns),
        "columnNames": [str(column) for column in frame.columns],
        "availableSamples": available_samples,
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
    sampling_seed: int = 69,
    width_cm: float = 20,
    height_cm: float = 15,
    dpi: int = 100,
    advanced: dict | None = None,
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
            data = data.sample(n=100000, random_state=int(sampling_seed))
        ax.scatter(data["Predicted.RT"], data["RT"], **marker_style(advanced, size=1.0, alpha=0.2))
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

    # The plot's own switch still decides whether there is a line at all; the
    # reference-line settings decide what it looks like. Its interactive twin
    # used to draw #ef4444 where this drew "red" -- the same line in two
    # different colours depending on which renderer you were looking at.
    identity_line = resolve_reference_line(advanced, color="red")
    if add_line and identity_line.visible:
        x_min = float(data["Predicted.RT"].min())
        x_max = float(data["Predicted.RT"].max())
        ax.plot([x_min, x_max], [x_min, x_max], **identity_line.matplotlib())

    ax.set_xlabel("Predicted RT")
    ax.set_ylabel("Actual RT")
    ax.set_title("Retention Time Plot" if header else "")
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def peptide_rt_interactive_html(
    *,
    add_line: bool = False,
    header: bool = True,
    sampling_seed: int = 69,
    width_cm: float = 20,
    height_cm: float = 15,
    advanced: dict | None = None,
) -> str:
    go = _get_plotly()
    frame = get_peptide_frame()
    _require_column(frame, "Predicted.RT")
    _require_column(frame, "RT")

    feature_col = _peptide_feature_column(frame)
    feature_series = (
        frame[feature_col].fillna("").astype(str)
        if feature_col is not None
        else pd.Series([f"feature_{idx + 1}" for idx in range(len(frame))], index=frame.index, dtype=str)
    )

    try:
        sample_col = _file_name_column(frame)
        sample_series = frame[sample_col].fillna("").astype(str)
    except ValueError:
        sample_series = pd.Series([""] * len(frame), index=frame.index, dtype=str)

    data = pd.DataFrame(
        {
            "feature": feature_series,
            "sample": sample_series,
            "predicted": pd.to_numeric(frame["Predicted.RT"], errors="coerce"),
            "actual": pd.to_numeric(frame["RT"], errors="coerce"),
        }
    ).dropna(subset=["predicted", "actual"])
    if data.empty:
        raise ValueError("No numeric Predicted.RT / RT values are available for the retention-time plot.")

    data["feature"] = data["feature"].replace("", "n/a")
    data["feature_short"] = data["feature"].map(lambda value: _truncate_hover_text(value, max_len=48))
    data["sample_short"] = data["sample"].map(_short_sample_label)
    data["delta"] = data["actual"] - data["predicted"]

    if len(data) > 250_000:
        data = data.sample(n=250_000, random_state=int(sampling_seed))

    custom_data = np.column_stack(
        [
            data["feature"].to_numpy(dtype=object),
            data["sample_short"].to_numpy(dtype=object),
            data["delta"].to_numpy(dtype=float),
            data["feature_short"].to_numpy(dtype=object),
        ]
    )

    fig = go.Figure()
    fig.add_trace(
        # SVG, not Scattergl: see plot_webgl - WebGL fails outright without
        # hardware acceleration, and _plotly_html enforces the same policy.
        go.Scatter(
            x=data["predicted"],
            y=data["actual"],
            mode="markers",
            marker=plotly_marker(advanced, size=4, alpha=0.35, color_default="#1f77b4"),
            customdata=custom_data,
            hovertemplate=(
                "Feature: %{customdata[3]}<br>"
                "Predicted RT: %{x:.4f}<br>"
                "Actual RT: %{y:.4f}<br>"
                "Delta (Actual - Predicted): %{customdata[2]:.4f}<br>"
                "Sample: %{customdata[1]}"
                "<extra></extra>"
            ),
            showlegend=False,
        )
    )

    identity_line = resolve_reference_line(advanced, color="red", width=2.0)
    if add_line and identity_line.visible:
        x_min = float(min(data["predicted"].min(), data["actual"].min()))
        x_max = float(max(data["predicted"].max(), data["actual"].max()))
        line_x = np.array([x_min, x_max], dtype=float)
        fig.add_trace(
            go.Scatter(
                x=line_x,
                y=line_x,
                mode="lines",
                line=identity_line.plotly(),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.update_layout(
        title=("Retention Time Plot" if header else None),
        xaxis_title="Predicted RT",
        yaxis_title="Actual RT",
        template="plotly_white",
        autosize=True,
        height=_cm_to_px(height_cm),
        margin=dict(l=56, r=22, t=(64 if header else 18), b=54),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(148,163,184,0.25)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,0.25)")
    fig.update_layout(**advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=_cm_to_px(height_cm)))
    return _plotly_html(fig)


def peptide_modification_plot(
    *,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 25,
    height_cm: float = 15,
    dpi: int = 100,
    advanced: dict | None = None,
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
    wide.columns = [str(column) for column in wide.columns]
    wide = wide.rename(columns=_sample_rename_map(wide.columns, meta, "Modified.Sequence"))
    ordered_samples = meta["new_sample"].tolist()
    annotated_cols = [column for column in ordered_samples if column in wide.columns]
    if not annotated_cols:
        raise ValueError(
            "Protein annotation metadata does not match any peptide sample columns after normalization."
        )

    filtered = wide[["Modified.Sequence", *annotated_cols]].copy()
    modification_counts = peptide_modification_counts(
        filtered,
        sequence_column="Modified.Sequence",
        sample_columns=annotated_cols,
    )
    carb = modification_counts["Carbamidomethylation"]
    oxi = modification_counts["Oxidation"]
    ace = modification_counts["Acetylation"]

    plot_data = pd.DataFrame(
        {
            "Sample": list(carb.index) * 3,
            "Count": list(carb.values) + list(oxi.values) + list(ace.values),
            "Modification": (["Carbamidomethylation"] * len(carb))
            + (["Oxidation"] * len(oxi))
            + (["Acetylation"] * len(ace)),
        }
    )
    plot_data = plot_data[plot_data["Count"] > 0]
    plot_data["Sample"] = pd.Categorical(plot_data["Sample"], categories=ordered_samples, ordered=True)
    plot_data = plot_data.sort_values("Sample")

    mod_colors = {
        "Carbamidomethylation": "blue",
        "Oxidation": "red",
        "Acetylation": "green",
    }
    found_mods = [
        value
        for value in ["Carbamidomethylation", "Oxidation", "Acetylation"]
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

    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def peptide_missed_cleavage_plot(
    *,
    include_id: bool = False,
    text: bool = True,
    text_size: int = 8,
    header: bool = True,
    protease: PeptideProtease = "trypsin",
    width_cm: float = 25,
    height_cm: float = 15,
    dpi: int = 100,
    advanced: dict | None = None,
) -> bytes:
    resolved_protease = normalize_protease(protease)
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
    wide.columns = [str(column) for column in wide.columns]
    wide = wide.rename(columns=_sample_rename_map(wide.columns, meta, seq_col))
    annotated_cols = [column for column in meta["new_sample"].tolist() if column in wide.columns]
    if not annotated_cols:
        raise ValueError(
            "Protein annotation metadata does not match any peptide sample columns after normalization."
        )

    summary = peptide_missed_cleavage_summary(
        wide[[seq_col, *annotated_cols]],
        sequence_column=seq_col,
        sample_columns=annotated_cols,
        protease=resolved_protease,
    )
    if summary.empty:
        raise ValueError("No peptide intensities are available to calculate missed cleavages.")

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

    ax.set_ylabel("Peptides by missed cleavages (%)")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    # Name the rule on the plot: the same peptides give different counts under
    # trypsin and trypsin/Lys-C, so the figure is ambiguous without it.
    ax.set_title(
        f"Missed cleavages per sample ({PROTEASE_LABELS[resolved_protease]})" if header else ""
    )
    ax.set_xticks(range(len(sample_order)))
    ax.set_xticklabels(sample_order, rotation=90)

    if text:
        # The number quoted when a digest is assessed is the share of sequences
        # with *at least one* missed cleavage, so every non-zero class counts.
        # Printing only the Count == 1 class understated a sample whose peptides
        # carry two or more, which is exactly the sample worth noticing.
        with_missed = (
            summary[summary["Count"] != 0]
            .groupby("Sample", observed=False)["Percentage"]
            .sum()
            .reindex(sample_order)
            .fillna(0.0)
        )
        base_y = float(bottom.max()) * 0.03 if len(bottom) else 0.0
        for index, value in enumerate(with_missed.tolist()):
            ax.text(index, base_y, f"{value:.1f}%", ha="center", va="bottom", fontsize=advanced_label_size(advanced, text_size))

    ax.legend(title="Number", bbox_to_anchor=(1.05, 1), loc="upper left")
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


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
    return resolve_reference_db(filename, f"FASTA database for {species}")


def _load_fasta_dataframe(species: PeptideSpecies) -> pd.DataFrame:
    path = _fasta_path(species)
    stat = path.stat()
    return _load_fasta_dataframe_cached(str(path), stat.st_mtime_ns).copy()


def _fasta_sequence(db: pd.DataFrame, protein: str) -> str | None:
    identifier = str(protein).strip()
    if not identifier:
        return None
    for column in ("name", "accession"):
        sequence_row = db.loc[db[column].astype(str) == identifier, "V1"]
        if not sequence_row.empty:
            return str(sequence_row.iloc[0])
    return None


def _peptide_starts(sequence: str, peptide: str):
    if not peptide:
        return
    start = sequence.find(peptide)
    while start != -1:
        yield start
        start = sequence.find(peptide, start + 1)


def _protein_peptides(frame: pd.DataFrame, protein: str) -> list[str]:
    """Peptides of the protein that were measured: at least one row with a quantity above 0.

    A report lists every precursor it searched for, including runs where it
    was not quantified; a peptide with no quantity anywhere was not observed
    and must not cover sequence. Without a quantity column every row counts.
    """
    members = frame[_protein_names_column(frame)].fillna("").astype(str).str.split(";")
    selected = members.map(lambda names: protein in [name.strip() for name in names])
    if "Precursor.Quantity" in frame.columns:
        quantity = pd.to_numeric(frame["Precursor.Quantity"], errors="coerce")
        selected &= np.isfinite(quantity) & (quantity > 0)
    return frame.loc[selected, _stripped_sequence_column(frame)].dropna().astype(str).unique().tolist()


def _coverage_visualization(
    frame: pd.DataFrame,
    db: pd.DataFrame,
    protein: str,
    chunk_size: int = 30,
) -> str:
    found_sequences = _protein_peptides(frame, protein)

    sequence = _fasta_sequence(db, protein)
    if sequence is None:
        raise ValueError(f"No sequence found in the selected database for protein: {protein}")

    n = len(sequence)
    result_sequences = ["-" * n]

    for peptide in found_sequences:
        for start_pos in _peptide_starts(sequence, peptide):
            end_pos = start_pos + len(peptide)
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
    peptides = _protein_peptides(frame, protein)
    if not peptides:
        raise ValueError(f"No peptides were found for protein '{protein}'.")

    db = _load_fasta_dataframe(species)
    sequence = _fasta_sequence(db, protein)
    if sequence is None:
        raise ValueError(f"The selected protein variant '{protein}' does not exist in the loaded database.")

    # Only peptides that occur in the selected sequence cover positions. A
    # peptide assigned to the protein group that does not occur (another
    # isoform or database entry, a sequence variant, I/L ambiguity) is reported
    # rather than silently counted as "matching".
    coverage_mask = [0] * len(sequence)
    mapped: list[str] = []
    unmapped: list[str] = []
    for peptide in peptides:
        starts = list(_peptide_starts(sequence, peptide))
        if not starts:
            unmapped.append(peptide)
            continue
        mapped.append(peptide)
        for start in starts:
            for index in range(start, start + len(peptide)):
                coverage_mask[index] = 1

    coverage_percent = round((sum(coverage_mask) / len(sequence)) * 100.0, 2)
    coverage_text = _coverage_visualization(frame, db, protein, chunk_size=chunk_size)

    unmapped = sorted(unmapped)
    warnings: list[str] = []
    if unmapped:
        examples = ", ".join(unmapped[:3])
        warnings.append(
            f"{len(unmapped)} of {len(peptides)} peptides assigned to this protein group do not "
            f"occur in the selected sequence (e.g. {examples}); they are not counted in the "
            "coverage. Check whether the report's protein group maps to another isoform or "
            "database entry than the selected variant."
        )

    return {
        "protein": protein,
        "species": species,
        "coveragePercent": coverage_percent,
        "matchingPeptideCount": len(mapped),
        "assignedPeptideCount": len(peptides),
        "unmappedPeptides": unmapped[:20],
        "sequenceText": coverage_text,
        "warnings": warnings,
    }
