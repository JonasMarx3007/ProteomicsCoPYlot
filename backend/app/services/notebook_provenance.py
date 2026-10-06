"""Scientific history shared by deterministic notebook adapters."""

class NotebookProvenanceError(ValueError):
    """The plot remains usable, but an exact scientific export is unavailable."""


def _imputation_documentation(info) -> str:
    if info is None:
        raise NotebookProvenanceError("Imputation provenance is unavailable.")
    method = str(info.mode).lower()
    required = ("seed", "sampleWise") + (("qValue", "adjustStd") if method in {"normal", "quantile"} else ("downShift", "width"))
    if method not in {"normal", "quantile", "numerical"} or any(getattr(info, key) is None for key in required):
        raise NotebookProvenanceError("Exact imputation parameters are unavailable.")
    parameters = {"method": method, "seed": info.seed, "sample_wise": info.sampleWise}
    if method in {"normal", "quantile"}:
        parameters.update(q=info.qValue, adj_std=info.adjustStd)
    else:
        parameters.update(down_shift=info.downShift, width=info.width)
    arguments = ", ".join(f"{key}={value!r}" for key, value in parameters.items())
    return (f"Imputation tool version: {info.toolVersion or 'not recorded in this historical state'}.\n"
            "Documentation only: the original CoPYlot imputation call was equivalent to:\n"
            f"impute_values_with_diagnostics(pre_imputation_data, sample_columns, {arguments})\n"
            "pre_imputation_data denotes the input at that time, not a newly selected matrix.\n"
            "Do not rerun random draws: resources/input.parquet contains the exact imputed values used.")


def input_history(kind, annotation, dataset, source="data"):
    if annotation is None or dataset is None:
        raise ValueError("Load and annotate a dataset first.")
    lineage = None
    imputation = annotation.imputation if source == "imputed" else None
    uses_imputed_input = source == "imputed"
    if kind == "phosprot":
        lineage = annotation.phosprot_lineage
        if (lineage is None or lineage != dataset.phosprot_lineage
                or lineage.aggregation != annotation.phosprot_aggregation
                or lineage.aggregation != dataset.phosprot_aggregation):
            raise NotebookProvenanceError("The historical phosphosite collapse record is unavailable or inconsistent.")
        uses_imputed_input = lineage.source == "imputed"
        imputation = lineage.imputation if uses_imputed_input else None
        if uses_imputed_input and (imputation is None or not imputation.applied):
            raise NotebookProvenanceError("The historical phosphosite imputation record is incomplete.")
    imputation_text = _imputation_documentation(imputation) if uses_imputed_input else ""
    if lineage and uses_imputed_input:
        imputation_text = imputation_text.replace("resources/input.parquet contains the exact imputed values used.",
            "resources/input.parquet contains the exact collapsed phosphoprotein matrix used by this plot.")
        imputation_text += f"\nImputation occurred on phosphosites BEFORE {lineage.aggregation} collapse. Collapse tool version: {lineage.toolVersion}."
    return lineage, imputation, uses_imputed_input, imputation_text
