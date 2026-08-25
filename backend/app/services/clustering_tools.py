from __future__ import annotations

import numpy as np
import pandas as pd


def require_complete_clustering_matrix(
    matrix: pd.DataFrame | np.ndarray,
    *,
    context: str = "heatmap",
) -> np.ndarray:
    """Return a finite numeric matrix or reject implicit missing-value handling."""
    if isinstance(matrix, pd.DataFrame):
        numeric = matrix.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    else:
        numeric = np.asarray(matrix, dtype=float)
    if numeric.ndim != 2:
        raise ValueError("Clustering requires a two-dimensional matrix.")

    finite = np.isfinite(numeric)
    if finite.all():
        return numeric

    rows, columns = numeric.shape
    complete_rows = int(finite.all(axis=1).sum()) if rows else 0
    missing_values = int((~finite).sum())
    raise ValueError(
        f"{context.capitalize()} clustering cannot be computed because the selected matrix "
        f"contains {missing_values} missing or non-finite value(s); only {complete_rows} of "
        f"{rows} features are complete across all {columns} samples. Run Imputation "
        "successfully and select 'Imputed Data', or disable row and column clustering. "
        "The data source was not changed automatically."
    )
