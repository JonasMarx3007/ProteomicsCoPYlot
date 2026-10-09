from __future__ import annotations

from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
)

from typing import Literal

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.clustering_tools import drop_incomplete_features, heatmap_notice, row_zscore
from app.services.functions import (
    condition_sample_labels,
    extract_sample_id as _extract_id_or_number,
    _phosprot_values_are_centred,
    data_source_options,
    select_matrix,
    intensity_unit_label,
)
from app.services.plot_styling import (
    advanced_anchor,
    advanced_condition_colors,
    advanced_label,
    advanced_number,
    advanced_text,
    apply_advanced_axes,
    advanced_color_map,
    resolve_marker,
)
from app.services.runtime_cache import apply_cached_wrappers
from app.services.stats_tools import _gene_tokens
from app.services.plotting_common import get_plt as _get_plt, get_sns as _get_seaborn
from app.services.data_tools import metadata_for_kind as _metadata_for_kind

SingleProteinIdentifier = Literal["workflow", "genes"]


def _analysis_frame(
    kind: AnnotationKind,
    data_source: str = "data",
) -> tuple[pd.DataFrame, list[str], pd.DataFrame]:
    _, frame, metadata = select_matrix(kind, data_source)
    sample_columns = [
        sample for sample in metadata["sample"].astype(str).tolist() if sample in frame.columns
    ]
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")
    meta = _metadata_for_kind(kind, frame, sample_columns)
    return frame, sample_columns, meta


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


def _site_label(site_key: object, filter_m1: bool) -> str:
    """The short row label the heatmap draws for one phosphosite.

    `A0A590UK10~ARHGEF18_S1035_M1` becomes `ARHGEF18_S1035_M1`, and `_M1` comes
    off as well when the view is already filtered to multiplicity 1, because
    then it is the same on every row. This is a display label: it drops the
    protein accession, so it is not a collapse key and must never be exported
    under that name.
    """
    text = str(site_key)
    if "~" in text:
        text = text.split("~", maxsplit=1)[1]
    if filter_m1 and text.endswith("_M1"):
        text = text.rsplit("_", maxsplit=1)[0]
    return text


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
    labeled["new_sample"] = condition_sample_labels(labeled)
    if include_id:
        # The id goes on a second line so a long run name cannot widen the axis.
        ids = labeled["sample"].map(lambda sample: _extract_id_or_number(str(sample)))
        labeled["new_sample"] = labeled["new_sample"] + "\n(" + ids.astype(str) + ")"
    return labeled


def _feature_label(value: object, kind: AnnotationKind) -> str:
    return str(value).strip()


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
    return values


def _feature_match_mask(
    values: pd.Series,
    selected: set[str],
    kind: AnnotationKind,
    identifier: SingleProteinIdentifier,
) -> pd.Series:
    text_values = values.astype(str)
    if identifier == "genes":
        selected_keys = {value.casefold() for value in selected}

        def _has_gene(value: str) -> bool:
            tokens = _gene_tokens(value)
            return any(token.casefold() in selected_keys for token in tokens)

        return text_values.apply(_has_gene)

    # Stripped, because _feature_options strips before it offers a value: an
    # unstripped compare here would make a legitimate selection match nothing.
    return text_values.str.strip().isin(selected)


def _unmatched_names(
    values: pd.Series,
    selected: list[str],
    kind: AnnotationKind,
    identifier: SingleProteinIdentifier,
) -> list[str]:
    """The selected names `_feature_match_mask` would match to no row.

    Built from the same keys the mask compares, as sets, so a long selection
    against a large table costs one pass over the column.
    """
    text_values = values.astype(str)
    if identifier == "genes":
        keys = {token.casefold() for value in text_values for token in _gene_tokens(value)}
    else:
        keys = set(text_values.str.strip())
    names = dict.fromkeys(str(item).strip() for item in selected if str(item).strip())
    return [name for name in names if (name.casefold() if identifier == "genes" else name) not in keys]


def unmatched_lineplot_names(
    kind: AnnotationKind,
    proteins: list[str],
    identifier: str = "workflow",
    data_source: str = "data",
) -> list[str]:
    """Selected proteins/sites/genes the lineplot cannot draw, because no row has them.

    The lineplot draws what matches and leaves the rest out; these are named
    under the plot so a typo or a partial group name does not vanish without
    a word. Workflow selections match the complete group identifier.
    """
    frame, _, _ = _analysis_frame(kind, data_source=data_source)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)
    return _unmatched_names(frame[key_col], proteins, kind, resolved_identifier)


def unmatched_names_notice(names: list[str]) -> str:
    if not names:
        return ""
    return f"Not found in this dataset, so not plotted: {', '.join(names)}."


def _identifier_options(kind: AnnotationKind, frame: pd.DataFrame) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if kind == "protein":
        workflow_label = "Protein Names"
    elif kind == "phospho":
        workflow_label = "Phosphosite Names"
    else:
        workflow_label = "Phosphoprotein Names"
    options.append({"key": "workflow", "label": workflow_label})

    if kind == "phospho":
        return options

    for candidate in ["GeneNames", "Gene_group"]:
        if candidate in frame.columns:
            gene_label = "Gene Names"
            if kind == "protein" and candidate == "Gene_group":
                gene_label = "Gene Group"
            options.append(
                {
                    "key": "genes",
                    "label": gene_label,
                }
            )
            break
    return options


def _heatmap_identifier_options(frame: pd.DataFrame) -> list[dict[str, str]]:
    options = [{"key": "workflow", "label": "Protein Names"}]
    for candidate in ["GeneNames", "Gene_group"]:
        if candidate in frame.columns:
            options.append({"key": "genes", "label": "Gene Names"})
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
    data_source: str = "data",
) -> tuple[pd.DataFrame, list[str]]:
    if not proteins:
        raise ValueError("Please select at least one protein/site for the lineplot.")

    frame, sample_columns, meta = _analysis_frame(kind, data_source=data_source)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)
    workflow_col = key_col
    if resolved_identifier == "genes":
        try:
            workflow_col = _line_box_key_column_for_identifier(kind, frame, identifier="workflow")
        except ValueError:
            # The gene itself remains a valid source identity when no separate
            # workflow identifier is present.
            workflow_col = key_col
    selected_columns = list(dict.fromkeys([key_col, workflow_col, *sample_columns]))
    data = frame[selected_columns].copy()

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
        selected_gene_labels = {
            value.casefold(): value
            for value in sorted(selected_set, key=str.casefold)
        }
        feature_rows["__source_row"] = np.arange(len(feature_rows), dtype=int)
        feature_rows["__feature_tokens"] = feature_rows[key_col].apply(
            lambda value: list(
                dict.fromkeys(
                    selected_gene_labels[token.casefold()]
                    for token in _gene_tokens(value)
                    if token.casefold() in selected_gene_labels
                )
            )
        )
        feature_rows = feature_rows.explode("__feature_tokens")
        feature_rows = feature_rows[feature_rows["__feature_tokens"].notna()].copy()
        if feature_rows.empty:
            raise ValueError("No rows matched the selected genes.")

        feature_metadata = (
            feature_rows.groupby("__feature_tokens", sort=True)
            .agg(
                SourceFeatureCount=("__source_row", "nunique"),
                SourceFeatures=(
                    workflow_col,
                    lambda values: "; ".join(
                        sorted(
                            {
                                str(value).strip()
                                for value in values
                                if str(value).strip()
                            },
                            key=str.casefold,
                        )
                    ),
                ),
            )
            .reset_index()
        )
        melted = feature_rows[["__feature_tokens"] + available_plot_samples].melt(
            id_vars="__feature_tokens",
            var_name="Sample",
            value_name="Value",
        )
        melted["Feature"] = melted["__feature_tokens"].astype(str)
        melted["Value"] = pd.to_numeric(melted["Value"], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        melted = (
            melted.groupby(["Feature", "Sample"], as_index=False, sort=True)["Value"]
            .median()
        )
        melted = melted.merge(
            feature_metadata.rename(columns={"__feature_tokens": "Feature"}),
            on="Feature",
            how="left",
        )
        melted["SampleCount"] = melted.groupby("Feature")["Value"].transform("count")
        melted["Aggregation"] = "Per-sample median"
        melted["Warning"] = melted.apply(
            lambda row: (
                f"Combined {int(row['SourceFeatureCount'])} source features mapped to this gene; "
                "each plotted value is their per-sample median."
                if int(row["SourceFeatureCount"]) > 1
                else ""
            ),
            axis=1,
        )
    else:
        feature_rows["Feature"] = feature_rows[key_col].apply(
            lambda value: _feature_label(value, kind)
        )
        feature_rows["__source_row"] = np.arange(len(feature_rows), dtype=int)
        feature_metadata = (
            feature_rows.groupby("Feature", sort=True)
            .agg(
                SourceFeatureCount=("__source_row", "nunique"),
                SourceFeatures=(
                    workflow_col,
                    lambda values: "; ".join(
                        sorted(
                            {
                                str(value).strip()
                                for value in values
                                if str(value).strip()
                            },
                            key=str.casefold,
                        )
                    ),
                ),
            )
            .reset_index()
        )
        melted = feature_rows[["Feature"] + available_plot_samples].melt(
            id_vars="Feature",
            var_name="Sample",
            value_name="Value",
        )
        melted["Value"] = pd.to_numeric(melted["Value"], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        melted = (
            melted.groupby(["Feature", "Sample"], as_index=False, sort=True)["Value"]
            .median()
        )
        melted = melted.merge(feature_metadata, on="Feature", how="left")
        melted["SampleCount"] = melted.groupby("Feature")["Value"].transform("count")
        melted["Aggregation"] = "Per-sample median"
        melted["Warning"] = melted.apply(
            lambda row: (
                f"Consolidated {int(row['SourceFeatureCount'])} duplicate rows for this feature; "
                "each plotted value is their per-sample median."
                if int(row["SourceFeatureCount"]) > 1
                else ""
            ),
            axis=1,
        )

    melted["Value"] = pd.to_numeric(melted["Value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
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
    data_source: str = "data",
) -> tuple[list[np.ndarray], list[str], dict[str, np.ndarray], pd.DataFrame]:
    if not str(protein).strip():
        raise ValueError("Please select one protein/site for the boxplot.")

    frame, sample_columns, meta = _analysis_frame(kind, data_source=data_source)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _line_box_key_column_for_identifier(kind, frame, identifier=resolved_identifier)
    workflow_col = key_col
    if resolved_identifier == "genes":
        try:
            workflow_col = _line_box_key_column_for_identifier(kind, frame, identifier="workflow")
        except ValueError:
            workflow_col = key_col
    selected_columns = list(dict.fromkeys([key_col, workflow_col, *sample_columns]))
    data = frame[selected_columns].copy()
    meta_filtered, _ = _select_conditions(meta, conditions)

    selected_set = {str(protein).strip()}
    mask = _feature_match_mask(data[key_col], selected_set, kind, resolved_identifier)
    selected_rows = data[mask].copy()
    if selected_rows.empty:
        raise ValueError("No row matched the selected protein/site.")

    labeled = _build_sample_labels(meta_filtered, include_id=False)
    rename_map = dict(zip(labeled["sample"], labeled["new_sample"]))
    selected_rows = selected_rows.rename(columns=rename_map)
    source_feature_count = int(len(selected_rows))
    source_features = "; ".join(
        sorted(
            {
                str(value).strip()
                for value in selected_rows[workflow_col].tolist()
                if str(value).strip()
            },
            key=str.casefold,
        )
    )
    aggregation_warning = ""
    if source_feature_count > 1:
        if resolved_identifier == "genes":
            aggregation_warning = (
                f"Combined {source_feature_count} source features mapped to this gene; "
                "each value is their per-sample median."
            )
        else:
            aggregation_warning = (
                f"Consolidated {source_feature_count} duplicate rows matching this feature; "
                "each value is their per-sample median."
            )

    condition_values: dict[str, np.ndarray] = {}
    for condition in labeled["condition"].astype(str).drop_duplicates().tolist():
        columns = labeled.loc[labeled["condition"] == condition, "new_sample"].tolist()
        present = [column for column in columns if column in selected_rows.columns]
        if not present:
            continue
        numeric = selected_rows[present].apply(pd.to_numeric, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        values = numeric.median(axis=0, skipna=True).to_numpy(dtype=float)
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
        summary_row: dict[str, object] = {
            "Condition": label,
            "N": int(values.size),
            "Mean": round(float(np.mean(values)), 4),
            "Median": round(median, 4),
            "Q1": round(q1, 4),
            "Q3": round(q3, 4),
            "Min": round(float(np.min(values)), 4),
            "Max": round(float(np.max(values)), 4),
        }
        summary_row.update(
            {
                "SampleCount": int(values.size),
                "SourceFeatureCount": source_feature_count,
                "SourceFeatures": source_features,
                "Aggregation": "Per-sample median",
                "Warning": aggregation_warning,
            }
        )
        summary_rows.append(summary_row)
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
    data_source: str = "data",
) -> tuple[pd.DataFrame, str]:
    if kind != "phospho":
        raise ValueError("Phosphosite-on-protein heatmap is only available for phospho dataset.")
    if not str(protein).strip():
        raise ValueError("Please select a protein for the heatmap.")

    frame, _, meta = _analysis_frame(kind, data_source=data_source)
    resolved_identifier = _normalize_identifier(identifier)
    key_col = _heatmap_key_column_for_identifier(frame, identifier=resolved_identifier)
    if "PTM_Collapse_key" not in frame.columns:
        raise ValueError("Phospho dataset is missing PTM_Collapse_key column.")

    # The same matcher as the boxplot and the lineplot. This used to be a
    # case-insensitive substring search on the protein-group column, which
    # merged every accession the selection is a prefix of -- an isoform group
    # `P12345-2`, or the group `P12345;Q67890` -- into one heatmap, under the
    # label of the one protein the user picked. The selector offers whole
    # values from this column, so an exact match reaches everything it can
    # reach, and a stale selection now says so instead of drawing something
    # else.
    selected_value = str(protein).strip()
    mask = _feature_match_mask(
        frame[key_col], {selected_value}, kind="phospho", identifier=resolved_identifier
    )
    protein_data = frame[mask].copy()

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
    total_features = len(matrix)
    matrix = matrix.apply(pd.to_numeric, errors="coerce")
    matrix = matrix.dropna(how="all")
    if matrix.empty:
        raise ValueError("No numeric phosphosite values available for the selected settings.")

    # The index stays the full PTM_Collapse_key from here on. The heatmap draws
    # the short site label, because every row belongs to the one protein the
    # user selected and repeating its accession down the axis says nothing --
    # but the table keeps the whole identifier, so an exported row can be traced
    # back to the matrix it came from. Full keys are also unique, which the
    # short labels are not guaranteed to be.
    value_type_normalized = str(value_type).lower()
    if value_type_normalized == "z":
        matrix = pd.DataFrame(row_zscore(matrix), index=matrix.index, columns=matrix.columns)
        cbar_label = "Z-score"
    elif value_type_normalized == "log2":
        cbar_label = intensity_unit_label(_phosprot_values_are_centred(kind))
    else:
        raise ValueError("valueType must be 'log2' or 'z'.")

    # Remove undefined rows before clustering. The shared z-score helper keeps
    # constant rows as zero; they remain valid heatmap rows.
    matrix = matrix.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    if matrix.empty:
        raise ValueError("Heatmap matrix is empty after preprocessing.")

    cluster_matrix = None
    if (cluster_rows and matrix.shape[0] > 1) or (cluster_cols and matrix.shape[1] > 1):
        cluster_matrix, completeness = drop_incomplete_features(
            matrix,
            context="single-protein heatmap",
        )
        matrix = matrix.loc[completeness.kept]

    if cluster_rows and matrix.shape[0] > 1:
        try:
            from scipy.cluster.hierarchy import leaves_list, linkage
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "scipy is required for row clustering. Install it with: pip install scipy"
            ) from exc
        row_linkage = linkage(cluster_matrix, method="average", metric="euclidean")
        row_order = leaves_list(row_linkage)
        matrix = matrix.iloc[row_order]
        cluster_matrix = cluster_matrix[row_order]

    if cluster_cols and matrix.shape[1] > 1:
        try:
            from scipy.cluster.hierarchy import leaves_list, linkage
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "scipy is required for column clustering. Install it with: pip install scipy"
            ) from exc
        col_linkage = linkage(cluster_matrix.T, method="average", metric="euclidean")
        matrix = matrix.iloc[:, leaves_list(col_linkage)]
    matrix.attrs["heatmap_notice"] = heatmap_notice(total_features, len(matrix), noun="phosphosites")
    return matrix, cbar_label


def single_protein_options(
    kind: AnnotationKind,
    tab: str = "boxplot",
    identifier: str = "workflow",
    data_source: str = "data",
) -> dict[str, object]:
    availability = data_source_options(kind)
    requested_source = str(data_source or "data").strip().lower()
    if requested_source not in availability["availableDataSources"]:
        # Asking for a matrix this level does not have is a stale selection, not
        # a mistake worth an error in an options call; the panel is told what it
        # actually got, and what it may pick instead.
        requested_source = "data"
    frame, _, meta = _analysis_frame(kind, data_source=requested_source)
    tab_normalized = str(tab).lower()
    available_identifiers = (
        _heatmap_identifier_options(frame)
        if tab_normalized == "heatmap" and kind == "phospho"
        else _identifier_options(kind, frame)
    )
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
                "dataSource": requested_source,
                **availability,
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
        # In the order the metadata lists them, as every plot draws them.
        .drop_duplicates()
        .tolist()
    )
    return {
        "proteins": proteins,
        "conditions": conditions,
        "proteinCount": len(proteins),
        "conditionCount": len(conditions),
        "identifier": resolved_identifier,
        "availableIdentifiers": available_identifiers,
        "dataSource": requested_source,
        **availability,
    }


def single_protein_lineplot_table(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    include_id: bool = False,
    identifier: str = "workflow",
    data_source: str = "data",
) -> pd.DataFrame:
    table, _ = _lineplot_long_table(
        kind,
        proteins,
        conditions,
        include_id=include_id,
        identifier=identifier,
        data_source=data_source,
    )
    columns = ["Feature", "Sample", "Condition", "Value"]
    for column in (
        "SampleCount",
        "SourceFeatureCount",
        "SourceFeatures",
        "Aggregation",
        "Warning",
    ):
        if column in table.columns:
            columns.append(column)
    result = table[columns].copy()
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
    advanced: dict | None = None,
    data_source: str = "data",
    show_na_low: bool = False,
) -> bytes:
    plt = _get_plt()
    table, ordered_samples = _lineplot_long_table(
        kind,
        proteins,
        conditions,
        include_id=include_id,
        identifier=identifier,
        data_source=data_source,
    )

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    features = table["Feature"].drop_duplicates().tolist()
    color_map = plt.get_cmap("tab10", max(1, len(features)))

    for idx, feature in enumerate(features):
        subset = table[table["Feature"] == feature].sort_values("x")
        measured = subset["Value"].notna()
        # The analysis matrix is log2: 0 corresponds to linear intensity 1.
        # Baseline vertices are presentation only, never observations or markers.
        line = subset if show_na_low else subset.loc[measured]
        ax.plot(
            line["x"],
            line["Value"].fillna(0.0) if show_na_low else line["Value"],
            marker="o",
            markevery=np.flatnonzero(measured.to_numpy()).tolist() if show_na_low else None,
            label=feature,
            color=color_map(idx),
        )

    ax.set_xticks(range(len(ordered_samples)))
    ax.set_xticklabels(ordered_samples, rotation=90)
    ax.set_xlabel("Sample")
    # `robust_site_median` phosphoprotein values are ratios to each site's own
    # across-sample median, not intensities. The heatmap colourbar beside these
    # plots already asks; these two hardcoded it, so the same matrix was called
    # two different things on one page.
    ax.set_ylabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
    if header:
        resolved_identifier = _normalize_identifier(identifier)
        workflow = "Gene" if resolved_identifier == "genes" else ("Protein" if kind == "protein" else "Phosphosite")
        # The collapse is stated in a note under the plot, not in the title: a
        # figure taken out of the tool should not carry a caption about how the
        # tool built it.
        ax.set_title(f"{workflow} expression across samples")
    ax.grid(True, alpha=0.2)
    if legend:
        # Below the axes rather than beside them: a legend to the right took
        # a fixed sixth of the width whatever its content, and long names
        # (full phosphosite keys, several genes) pushed the plot itself to
        # half its width. Names are shortened in the legend only; the table
        # and the hover text keep the full name.
        handles, labels = ax.get_legend_handles_labels()
        # Up to 40 characters per entry; kept inline so the notebook export
        # (which lifts this function) needs no extra helper.
        labels = [label if len(label) <= 40 else label[:37].rstrip() + "..." for label in labels]
        columns = max(1, min(3, len(labels)))
        rows = -(-len(labels) // columns)
        ax.legend(
            handles, labels,
            title="Feature", loc="lower center", ncol=columns, fontsize=8, title_fontsize=8, frameon=False,
            bbox_to_anchor=advanced_anchor(ax, advanced, 0.5, 0.0), bbox_transform=fig.transFigure,
        )
        apply_advanced_axes(ax, advanced)
        # Reserve the legend's height (one line per row plus the title) so
        # tight_layout keeps the sample labels above it.
        font_scale = advanced_number(advanced, "legendFontSize", 8) / 8
        reserved = min(0.5, (0.16 * rows + 0.3) * font_scale / _cm_to_inch(height_cm)) if ax.get_legend() else 0
        fig.tight_layout(rect=[0, reserved, 1, 1])
    else:
        apply_advanced_axes(ax, advanced)
        fig.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def single_protein_boxplot_table(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    data_source: str = "data",
) -> pd.DataFrame:
    _, _, _, summary_df = _boxplot_data(
        kind,
        protein,
        conditions,
        identifier=identifier,
        data_source=data_source,
    )
    return summary_df


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
    plt = _get_plt()
    intensities, labels, condition_values, summary_df = _boxplot_data(
        kind,
        protein,
        conditions,
        identifier=identifier,
        data_source=data_source,
    )
    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))

    if not intensities:
        ax.text(0.5, 0.5, "No measured values in the selected conditions", ha="center", va="center")
        ax.axis("off")
        return _to_png_bytes(fig, plt, dpi=dpi, tight=False)

    # The project palette, and the advanced condition colours over it. This used
    # to be a bare tab20 lookup, so a colour set on the Colors page or in the
    # advanced panel was ignored here while every QC plot honoured it.
    condition_color = advanced_condition_colors(kind, plt, list(labels), advanced)
    box_positions = [
        index
        for index, label in enumerate(labels, start=1)
        if condition_values[label].size >= 3
    ]
    if box_positions:
        box_labels = [labels[index - 1] for index in box_positions]
        box = ax.boxplot(
            [condition_values[label] for label in box_labels],
            positions=box_positions,
            patch_artist=True,
            showfliers=outliers,
            # Fliers are a different class of mark from the jittered points
            # below -- they are the values those points deliberately exclude --
            # so they are styled separately. Both were unstyleable before: the
            # advanced panel offered these controls and this figure read none
            # of them.
            flierprops={
                "marker": "o",
                "markersize": max(1.0, advanced_number(advanced, "boxOutlierSize", 5.0)),
                "markerfacecolor": advanced_text(advanced, "boxOutlierColor") or "red",
                "markeredgecolor": advanced_text(advanced, "boxOutlierEdgeColor") or "black",
                "markeredgewidth": 0.5,
            },
            medianprops={"color": advanced_text(advanced, "boxMedianColor") or "#b22222"},
            boxprops={"edgecolor": advanced_text(advanced, "boxBorderColor") or "#000000"},
        )
        for patch, label in zip(box["boxes"], box_labels):
            patch.set_facecolor(condition_color[label])

    # A thin dark edge by default. Filled dots in the condition's own colour sit
    # on a box of that same colour, so without an outline the points that matter
    # most -- the ones inside the box -- are the ones you cannot see.
    def point_kwargs_for(condition: str) -> dict:
        """This condition's points: its own settings, then this plot's general ones.

        `boxPointSize` and its siblings are the general layer here -- they are
        this plot's own controls and predate the shared ones -- and the
        per-condition overrides sit above them, as on every other point plot.
        """
        return resolve_marker(
            advanced,
            size=4.5,
            alpha=0.8,
            group=condition,
            use_color=False,
            size_key="boxPointSize",
            alpha_key="boxPointAlpha",
            edge_width_key="boxPointEdgeWidth",
            edge_color_key="boxPointEdgeColor",
            edge_width_default=0.4,
        ).matplotlib()
    rng = np.random.default_rng(random_seed)
    for index, label in enumerate(labels, start=1):
        values = condition_values[label]
        if values.size < 3:
            visible_values = values
        elif dots:
            q1, q3 = np.percentile(values, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            visible_values = values[(values >= lower) & (values <= upper)]
        else:
            continue
        jitter = rng.normal(index, 0.05, size=len(visible_values))
        ax.scatter(
            jitter,
            visible_values,
            color=condition_color[label],
            zorder=3,
            **point_kwargs_for(label),
        )

    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(
        [
            f"{advanced_label(label, advanced, 'conditionLabels')} (n={condition_values[label].size})"
            if sample_n
            else advanced_label(label, advanced, "conditionLabels")
            for label in labels
        ],
        rotation=45,
        ha="right",
    )
    ax.set_xlabel("Condition")
    # `robust_site_median` phosphoprotein values are ratios to each site's own
    # across-sample median, not intensities. The heatmap colourbar beside these
    # plots already asks; these two hardcoded it, so the same matrix was called
    # two different things on one page.
    ax.set_ylabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
    if header:
        resolved_identifier = _normalize_identifier(identifier)
        label = str(protein).strip() if resolved_identifier == "genes" else _feature_label(protein, kind)
        # The collapse is stated in a note under the plot, not in the title: a
        # figure taken out of the tool should not carry a caption about how the
        # tool built it.
        # "Measured" is a claim about where the numbers came from, and on the
        # imputed matrix some of them are draws from a down-shifted normal. The
        # exported figure carries no data-source selector, so the title is the
        # only place that can say so.
        measured = "Measured" if data_source != "imputed" else "Imputed"
        ax.set_title(f"{measured} {label} {intensity_unit_label(_phosprot_values_are_centred(kind)).lower()} values")

    if legend:
        handles = [plt.Line2D([0], [0], color=condition_color[label], lw=4) for label in labels]
        ax.legend(
            handles,
            [advanced_label(label, advanced, "conditionLabels") for label in labels],
            title="Condition",
            bbox_to_anchor=(1.02, 1),
            loc="upper left",
        )
        apply_advanced_axes(ax, advanced)
        fig.tight_layout(rect=[0, 0, 0.84, 1])
    else:
        apply_advanced_axes(ax, advanced)
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
    data_source: str = "data",
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
        data_source=data_source,
    )
    # Two label columns, both honest: `Site` is what the plot draws, so a row
    # here can be found on the figure, and `PTM_Collapse_key` is the whole
    # identifier the value was read under. The header used to say
    # `PTM_Collapse_key` over the short label -- a `rename(columns={"index":
    # ...})` that never fired, because reset_index restores the index's own
    # name -- so the exported accession was simply missing.
    keys = matrix.index.astype(str)
    table = matrix.reset_index(drop=True)
    table.insert(0, "PTM_Collapse_key", keys)
    table.insert(0, "Site", [_site_label(key, filter_m1) for key in keys])
    label_cols = {"Site", "PTM_Collapse_key"}
    numeric_cols = [col for col in table.columns if col not in label_cols]
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
    advanced: dict | None = None,
    data_source: str = "data",
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
        data_source=data_source,
    )

    # The axis carries the short site label; the full key stays in the table.
    matrix = matrix.rename(index=lambda key: _site_label(key, filter_m1))

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    sns.heatmap(
        matrix,
        cmap=plt.get_cmap(advanced_color_map(advanced, str(cmap_name))),
        # Symmetric limits in z mode, so equal colours mean equal z as on the
        # other heatmaps; the map itself stays the caller's choice.
        **({"vmin": -2.5, "vmax": 2.5} if str(value_type).lower() == "z" else {}),
        cbar_kws={"label": cbar_label},
        linewidths=0.5,
        linecolor="gray",
        mask=matrix.isna(),
        annot=False,
        ax=ax,
    )
    fig._copylot_notice = matrix.attrs.get("heatmap_notice", "")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=90)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    if header:
        suffix = "Z-transformed" if str(value_type).lower() == "z" else "log2 intensities"
        ax.set_title(f"{protein} ({suffix})")
    ax.set_xlabel("Sample")
    ax.set_ylabel("PTM site")
    apply_advanced_axes(ax, advanced)
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
