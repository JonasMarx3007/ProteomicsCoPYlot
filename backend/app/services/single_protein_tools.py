from __future__ import annotations

import io
import re
from typing import Literal

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.runtime_cache import apply_cached_wrappers

SingleProteinIdentifier = Literal["workflow", "genes"]


def _get_plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plot rendering. Install it with: pip install matplotlib"
        ) from exc


def _get_seaborn():
    try:
        import seaborn as sns

        return sns
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "seaborn is required for heatmap rendering. Install it with: pip install seaborn"
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


def _cm_to_inch(value_cm: float) -> float:
    return max(1.0, float(value_cm) / 2.54)


def _extract_id_or_number(sample: str) -> str:
    match = re.search(r"\d+|[A-Za-z]+", str(sample))
    return match.group(0) if match else str(sample)


def _metadata_for_kind(kind: AnnotationKind, frame: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        meta = meta[meta["sample"].isin(sample_columns)]
        if not meta.empty:
            meta = meta.drop_duplicates(subset=["sample"])
            meta = meta.set_index("sample").reindex(sample_columns).reset_index()
            meta["condition"] = meta["condition"].fillna("sample").astype(str)
            return meta
    return pd.DataFrame({"sample": sample_columns, "condition": ["sample"] * len(sample_columns)})


def _analysis_frame(kind: AnnotationKind) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.log2_data.empty:
        frame = annotation.log2_data.copy()
    elif annotation is not None and not annotation.filtered_data.empty:
        frame = annotation.filtered_data.copy()
    elif annotation is not None and not annotation.source_data.empty:
        frame = annotation.source_data.copy()
    else:
        frame = raw

    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")
    meta = _metadata_for_kind(kind, frame, sample_columns)
    return frame, sample_columns, meta


def _line_box_key_column(kind: AnnotationKind, frame: pd.DataFrame) -> str:
    return _line_box_key_column_for_identifier(kind, frame, identifier="workflow")


def _normalize_identifier(identifier: str) -> SingleProteinIdentifier:
    normalized = str(identifier).strip().lower()
    if normalized == "genes":
        return "genes"
    return "workflow"


def _line_box_key_column_for_identifier(
    kind: AnnotationKind,
    frame: pd.DataFrame,
    identifier: str = "workflow",
) -> str:
    resolved_identifier = _normalize_identifier(identifier)
    if resolved_identifier == "genes":
        gene_candidates = ["GeneNames", "Gene_group"]
        for candidate in gene_candidates:
            if candidate in frame.columns:
                return candidate
        raise ValueError("Gene names are not available for this dataset.")

    if kind == "protein":
        candidates = ["ProteinNames", "Protein", "Gene"]
    else:
        candidates = ["PTM_Collapse_key", "Phosphoprotein", "Protein_group"]
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    raise ValueError(
        f"Could not find a feature identifier column for {kind}. "
        f"Expected one of: {', '.join(candidates)}"
    )


def _heatmap_protein_group_column(frame: pd.DataFrame) -> str:
    for candidate in ["Protein_group", "ProteinNames", "Phosphoprotein"]:
        if candidate in frame.columns:
            return candidate
    raise ValueError(
        "Could not find a protein-group column for phosphosite heatmap. "
        "Expected one of: Protein_group, ProteinNames, Phosphoprotein."
    )


def _heatmap_key_column_for_identifier(
    frame: pd.DataFrame,
    identifier: str = "workflow",
) -> str:
    resolved_identifier = _normalize_identifier(identifier)
    if resolved_identifier == "genes":
        for candidate in ["GeneNames", "Gene_group"]:
            if candidate in frame.columns:
                return candidate
        raise ValueError("Gene names are not available for this phospho dataset.")
    return _heatmap_protein_group_column(frame)


def _build_sample_labels(meta: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    labeled = meta.copy()
    labeled["sample"] = labeled["sample"].astype(str)
    labeled["condition"] = labeled["condition"].astype(str)
    labeled["sample_idx"] = labeled.groupby("condition").cumcount() + 1
    if include_id:
        labeled["new_sample"] = labeled.apply(
            lambda row: f"{row['condition']}_{row['sample_idx']}\n({_extract_id_or_number(str(row['sample']))})",
            axis=1,
        )
    else:
        labeled["new_sample"] = labeled.apply(
            lambda row: f"{row['condition']}_{row['sample_idx']}",
            axis=1,
        )
    return labeled


def _feature_label(value: object, kind: AnnotationKind) -> str:
    text = str(value)
    if kind == "protein":
        return text.split(";")[0].strip()
    return text


def _gene_tokens(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [token.strip() for token in text.split(";") if token.strip()]


def _feature_options(
    frame: pd.DataFrame,
    key_col: str,
    kind: AnnotationKind,
    identifier: SingleProteinIdentifier,
) -> list[str]:
    if identifier == "genes":
        tokens: set[str] = set()
        for value in frame[key_col].dropna().astype(str).tolist():
            for token in _gene_tokens(value):
                tokens.add(token)
        return sorted(tokens)

    values = (
        frame[key_col]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda series: series != ""]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    if kind == "protein":
        # Keep workflow selection compact and human-readable.
        values = sorted({value.split(";")[0].strip() for value in values if value})
    return values


def _feature_match_mask(
    values: pd.Series,
    selected: set[str],
    kind: AnnotationKind,
    identifier: SingleProteinIdentifier,
) -> pd.Series:
    text_values = values.astype(str)
    if identifier == "genes":
        def _has_gene(value: str) -> bool:
            tokens = _gene_tokens(value)
            return any(token in selected for token in tokens)

        return text_values.apply(_has_gene)

    if kind == "protein":
        return text_values.str.split(";").str[0].str.strip().isin(selected)
    return text_values.isin(selected)


def _identifier_options(kind: AnnotationKind, frame: pd.DataFrame) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    workflow_label = "Protein Names" if kind == "protein" else "Workflow Names"
    options.append({"key": "workflow", "label": workflow_label})

    for candidate in ["GeneNames", "Gene_group"]:
        if candidate in frame.columns:
            options.append(
                {
                    "key": "genes",
                    "label": "Gene Group" if candidate == "Gene_group" else "Gene Names",
                }
            )
            break
    return options


def _select_conditions(meta: pd.DataFrame, conditions: list[str]) -> tuple[pd.DataFrame, list[str]]:
    available = meta["condition"].astype(str).dropna().tolist()
    unique_available = list(dict.fromkeys(available))
    if not conditions:
        selected = unique_available
    else:
        selected = [condition for condition in conditions if condition in unique_available]
    if not selected:
        raise ValueError("No matching conditions selected.")
    filtered = meta[meta["condition"].isin(selected)].copy()
    if filtered.empty:
        raise ValueError("No samples found for the selected conditions.")
    return filtered, selected


def _lineplot_long_table(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    include_id: bool,
    identifier: str = "workflow",
) -> tuple[pd.DataFrame, list[str]]:
    if not proteins:
        raise ValueError("Please select at least one protein/site for the lineplot.")

    frame, sample_columns, meta = _analysis_frame(kind)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)
    data = frame[[key_col] + sample_columns].copy()

    meta_filtered, selected_conditions = _select_conditions(meta, conditions)
    labeled = _build_sample_labels(meta_filtered, include_id=include_id)
    rename_map = dict(zip(labeled["sample"], labeled["new_sample"]))
    ordered_samples: list[str] = []
    for condition in selected_conditions:
        ordered_samples.extend(labeled.loc[labeled["condition"] == condition, "new_sample"].tolist())

    data = data.rename(columns=rename_map)
    selected_set = {str(item).strip() for item in proteins if str(item).strip()}
    if not selected_set:
        raise ValueError("Please select at least one protein/site for the lineplot.")

    mask = _feature_match_mask(data[key_col], selected_set, kind, resolved_identifier)
    feature_rows = data[mask].copy()
    if feature_rows.empty:
        raise ValueError("No rows matched the selected proteins/sites.")

    available_plot_samples = [sample for sample in ordered_samples if sample in feature_rows.columns]
    if not available_plot_samples:
        raise ValueError("No sample columns available after condition filtering.")

    if resolved_identifier == "genes":
        feature_rows["__feature_tokens"] = feature_rows[key_col].astype(str).apply(
            lambda value: [token for token in _gene_tokens(value) if token in selected_set]
        )
        feature_rows = feature_rows.explode("__feature_tokens")
        feature_rows = feature_rows[feature_rows["__feature_tokens"].notna()].copy()
        if feature_rows.empty:
            raise ValueError("No rows matched the selected genes.")
        melted = feature_rows[["__feature_tokens"] + available_plot_samples].melt(
            id_vars="__feature_tokens",
            var_name="Sample",
            value_name="Value",
        )
        melted["Feature"] = melted["__feature_tokens"].astype(str)
    else:
        melted = feature_rows[[key_col] + available_plot_samples].melt(
            id_vars=key_col,
            var_name="Sample",
            value_name="Value",
        )
        melted["Feature"] = melted[key_col].apply(lambda value: _feature_label(value, kind))

    melted["Value"] = pd.to_numeric(melted["Value"], errors="coerce")
    melted = melted.dropna(subset=["Value"])
    if melted.empty:
        raise ValueError("Selected proteins/sites have no numeric values in the chosen conditions.")

    melted = melted.merge(
        labeled[["new_sample", "condition"]].rename(columns={"new_sample": "Sample", "condition": "Condition"}),
        on="Sample",
        how="left",
    )
    order_index = {sample: idx for idx, sample in enumerate(available_plot_samples)}
    melted["x"] = melted["Sample"].map(order_index)
    melted = melted.sort_values(["Feature", "x"]).reset_index(drop=True)
    return melted, available_plot_samples


def _boxplot_data(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
) -> tuple[list[np.ndarray], list[str], dict[str, np.ndarray], pd.DataFrame]:
    if not str(protein).strip():
        raise ValueError("Please select one protein/site for the boxplot.")

    frame, sample_columns, meta = _analysis_frame(kind)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)
    data = frame[[key_col] + sample_columns].copy()
    meta_filtered, _ = _select_conditions(meta, conditions)

    selected_set = {str(protein).strip()}
    mask = _feature_match_mask(data[key_col], selected_set, kind, resolved_identifier)
    selected_rows = data[mask].copy()
    if selected_rows.empty:
        raise ValueError("No row matched the selected protein/site.")

    labeled = _build_sample_labels(meta_filtered, include_id=False)
    rename_map = dict(zip(labeled["sample"], labeled["new_sample"]))
    selected_rows = selected_rows.rename(columns=rename_map)

    condition_values: dict[str, np.ndarray] = {}
    for condition in labeled["condition"].astype(str).drop_duplicates().tolist():
        columns = labeled.loc[labeled["condition"] == condition, "new_sample"].tolist()
        present = [column for column in columns if column in selected_rows.columns]
        if len(present) < 3:
            continue
        values = selected_rows[present].apply(pd.to_numeric, errors="coerce").values.flatten()
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        condition_values[condition] = values

    labels = list(condition_values.keys())
    intensities = [condition_values[label] for label in labels]
    summary_rows: list[dict[str, object]] = []
    for label, values in condition_values.items():
        q1 = float(np.percentile(values, 25))
        median = float(np.median(values))
        q3 = float(np.percentile(values, 75))
        summary_rows.append(
            {
                "Condition": label,
                "N": int(values.size),
                "Mean": round(float(np.mean(values)), 4),
                "Median": round(median, 4),
                "Q1": round(q1, 4),
                "Q3": round(q3, 4),
                "Min": round(float(np.min(values)), 4),
                "Max": round(float(np.max(values)), 4),
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    return intensities, labels, condition_values, summary_df


def _heatmap_matrix(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    include_id: bool,
    filter_m1: bool,
    cluster_rows: bool,
    cluster_cols: bool,
    value_type: str,
    identifier: str = "workflow",
) -> tuple[pd.DataFrame, str]:
    if kind != "phospho":
        raise ValueError("Phosphosite-on-protein heatmap is only available for phospho dataset.")
    if not str(protein).strip():
        raise ValueError("Please select a protein for the heatmap.")

    frame, _, meta = _analysis_frame(kind)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _heatmap_key_column_for_identifier(frame, identifier=resolved_identifier)
    if "PTM_Collapse_key" not in frame.columns:
        raise ValueError("Phospho dataset is missing PTM_Collapse_key column.")

    selected_value = str(protein).strip()
    if resolved_identifier == "genes":
        selected_set = {selected_value}
        mask = _feature_match_mask(frame[key_col], selected_set, kind="phospho", identifier="genes")
        protein_data = frame[mask].copy()
    else:
        protein_data = frame[
            frame[key_col].astype(str).str.contains(selected_value, case=False, na=False, regex=False)
        ].copy()

    if protein_data.empty:
        entity_label = "gene" if resolved_identifier == "genes" else "protein"
        raise ValueError(f"No phosphosite rows found for {entity_label} '{selected_value}'.")

    meta_filtered, _ = _select_conditions(meta, conditions)
    labeled = _build_sample_labels(meta_filtered, include_id=include_id)
    sample_cols = [sample for sample in labeled["sample"].astype(str).tolist() if sample in protein_data.columns]
    if not sample_cols:
        raise ValueError("No sample columns available for selected conditions.")

    if filter_m1:
        protein_data = protein_data[
            protein_data["PTM_Collapse_key"].astype(str).str.endswith("_M1", na=False)
        ]
        if protein_data.empty:
            raise ValueError("No phosphosite rows remain after filtering to *_M1 entries.")

    rename_map = dict(zip(labeled["sample"], labeled["new_sample"]))
    matrix = protein_data.set_index("PTM_Collapse_key")[sample_cols].rename(columns=rename_map)
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    matrix = matrix.dropna(how="all")
    if matrix.empty:
        raise ValueError("No numeric phosphosite values available for the selected settings.")

    def _extract_site(site_key: str) -> str:
        text = str(site_key)
        if "~" in text:
            text = text.split("~", maxsplit=1)[1]
        if filter_m1 and text.endswith("_M1"):
            text = text.rsplit("_", maxsplit=1)[0]
        return text

    matrix.index = matrix.index.map(_extract_site)

    value_type_normalized = str(value_type).lower()
    if value_type_normalized == "z":
        def _z_row(row: pd.Series) -> pd.Series:
            mean = row.mean(skipna=True)
            std = row.std(skipna=True)
            if std == 0 or np.isnan(std):
                return row * np.nan
            return (row - mean) / std
        matrix = matrix.apply(_z_row, axis=1)
        cbar_label = "Z-score"
    elif value_type_normalized == "log2":
        cbar_label = "log2 Intensity"
    else:
        raise ValueError("valueType must be 'log2' or 'z'.")

    if cluster_rows and matrix.shape[0] > 1:
        try:
            from scipy.cluster.hierarchy import leaves_list, linkage
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "scipy is required for row clustering. Install it with: pip install scipy"
            ) from exc
        row_linkage = linkage(matrix.fillna(0), method="average", metric="euclidean")
        matrix = matrix.iloc[leaves_list(row_linkage)]

    if cluster_cols and matrix.shape[1] > 1:
        try:
            from scipy.cluster.hierarchy import leaves_list, linkage
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "scipy is required for column clustering. Install it with: pip install scipy"
            ) from exc
        col_linkage = linkage(matrix.T.fillna(0), method="average", metric="euclidean")
        matrix = matrix.iloc[:, leaves_list(col_linkage)]

    matrix = matrix.dropna(how="all")
    if matrix.empty:
        raise ValueError("Heatmap matrix is empty after preprocessing.")
    return matrix, cbar_label


def single_protein_options(
    kind: AnnotationKind,
    tab: str = "boxplot",
    identifier: str = "workflow",
) -> dict[str, object]:
    frame, _, meta = _analysis_frame(kind)
    tab_normalized = str(tab).lower()
    available_identifiers = _identifier_options(kind, frame)
    available_identifier_keys = [str(item["key"]) for item in available_identifiers]
    resolved_identifier = _normalize_identifier(identifier)
    if resolved_identifier not in available_identifier_keys:
        resolved_identifier = _normalize_identifier(available_identifier_keys[0] if available_identifier_keys else "workflow")

    if tab_normalized == "heatmap":
        if kind != "phospho":
            return {
                "proteins": [],
                "conditions": [],
                "proteinCount": 0,
                "conditionCount": 0,
                "identifier": resolved_identifier,
                "availableIdentifiers": available_identifiers,
            }
        key_col = _heatmap_key_column_for_identifier(frame, identifier=resolved_identifier)
    else:
        key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)

    proteins = _feature_options(frame, key_col, kind, resolved_identifier)
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
    return {
        "proteins": proteins,
        "conditions": conditions,
        "proteinCount": len(proteins),
        "conditionCount": len(conditions),
        "identifier": resolved_identifier,
        "availableIdentifiers": available_identifiers,
    }


def single_protein_lineplot_table(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    include_id: bool = False,
    identifier: str = "workflow",
) -> pd.DataFrame:
    table, _ = _lineplot_long_table(
        kind,
        proteins,
        conditions,
        include_id=include_id,
        identifier=identifier,
    )
    result = table[["Feature", "Sample", "Condition", "Value"]].copy()
    result["Value"] = result["Value"].round(4)
    return result


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
) -> bytes:
    plt = _get_plt()
    table, ordered_samples = _lineplot_long_table(
        kind,
        proteins,
        conditions,
        include_id=include_id,
        identifier=identifier,
    )

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    features = table["Feature"].drop_duplicates().tolist()
    color_map = plt.cm.get_cmap("tab10", max(1, len(features)))

    for idx, feature in enumerate(features):
        subset = table[table["Feature"] == feature].sort_values("x")
        ax.plot(
            subset["x"],
            subset["Value"],
            marker="o",
            label=feature,
            color=color_map(idx),
        )

    ax.set_xticks(range(len(ordered_samples)))
    ax.set_xticklabels(ordered_samples, rotation=90)
    ax.set_xlabel("Sample")
    ax.set_ylabel("log2 intensity")
    if header:
        resolved_identifier = _normalize_identifier(identifier)
        workflow = "Gene" if resolved_identifier == "genes" else ("Protein" if kind == "protein" else "Phosphosite")
        ax.set_title(f"{workflow} expression across samples")
    if legend:
        ax.legend(title="Feature", bbox_to_anchor=(1.02, 1), loc="upper left")
        fig.tight_layout(rect=[0, 0, 0.84, 1])
    else:
        fig.tight_layout()

    ax.grid(True, alpha=0.2)
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def single_protein_boxplot_table(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
) -> pd.DataFrame:
    _, _, _, summary_df = _boxplot_data(kind, protein, conditions, identifier=identifier)
    return summary_df


def single_protein_boxplot_plot(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    outliers: bool = False,
    dots: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    plt = _get_plt()
    intensities, labels, condition_values, _ = _boxplot_data(
        kind,
        protein,
        conditions,
        identifier=identifier,
    )
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))

    if not intensities:
        ax.text(0.5, 0.5, "No conditions with >=3 samples", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    color_map = plt.cm.get_cmap("tab20", max(1, len(labels)))
    condition_color = {label: color_map(index) for index, label in enumerate(labels)}
    box = ax.boxplot(intensities, patch_artist=True, showfliers=outliers)
    for patch, label in zip(box["boxes"], labels):
        patch.set_facecolor(condition_color[label])

    if dots:
        for index, label in enumerate(labels, start=1):
            values = condition_values[label]
            q1, q3 = np.percentile(values, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            non_outliers = values[(values >= lower) & (values <= upper)]
            jitter = np.random.normal(index, 0.05, size=len(non_outliers))
            ax.scatter(jitter, non_outliers, s=15, alpha=0.7, color=condition_color[label], zorder=3)

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_xlabel("Condition")
    ax.set_ylabel("log2 intensity")
    if header:
        resolved_identifier = _normalize_identifier(identifier)
        label = str(protein).strip() if resolved_identifier == "genes" else _feature_label(protein, kind)
        ax.set_title(f"Measured {label} intensity values (log2)")

    if legend:
        handles = [plt.Line2D([0], [0], color=condition_color[label], lw=4) for label in labels]
        ax.legend(handles, labels, title="Condition", bbox_to_anchor=(1.02, 1), loc="upper left")
        fig.tight_layout(rect=[0, 0, 0.84, 1])
    else:
        fig.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def single_protein_heatmap_table(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    include_id: bool = False,
    filter_m1: bool = True,
    cluster_rows: bool = False,
    cluster_cols: bool = False,
    value_type: str = "log2",
) -> pd.DataFrame:
    matrix, _ = _heatmap_matrix(
        kind=kind,
        protein=protein,
        conditions=conditions,
        include_id=include_id,
        filter_m1=filter_m1,
        cluster_rows=cluster_rows,
        cluster_cols=cluster_cols,
        value_type=value_type,
        identifier=identifier,
    )
    table = matrix.reset_index().rename(columns={"index": "Site"})
    numeric_cols = [col for col in table.columns if col != "Site"]
    table[numeric_cols] = table[numeric_cols].round(4)
    return table


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
) -> bytes:
    plt = _get_plt()
    sns = _get_seaborn()
    matrix, cbar_label = _heatmap_matrix(
        kind=kind,
        protein=protein,
        conditions=conditions,
        include_id=include_id,
        filter_m1=filter_m1,
        cluster_rows=cluster_rows,
        cluster_cols=cluster_cols,
        value_type=value_type,
        identifier=identifier,
    )

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    sns.heatmap(
        matrix,
        cmap=plt.get_cmap(str(cmap_name)),
        cbar_kws={"label": cbar_label},
        linewidths=0.5,
        linecolor="gray",
        mask=matrix.isna(),
        annot=False,
        ax=ax,
    )
    ax.set_xticklabels(ax.get_xticklabels(), rotation=90)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    if header:
        suffix = "Z-transformed" if str(value_type).lower() == "z" else "log2 intensities"
        ax.set_title(f"{protein} ({suffix})")
    ax.set_xlabel("Sample")
    ax.set_ylabel("PTM site")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


apply_cached_wrappers(
    globals(),
    [
        "single_protein_options",
        "single_protein_lineplot_table",
        "single_protein_lineplot_plot",
        "single_protein_boxplot_table",
        "single_protein_boxplot_plot",
        "single_protein_heatmap_table",
        "single_protein_heatmap_plot",
    ],
)
