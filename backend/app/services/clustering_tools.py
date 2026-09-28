from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def heatmap_notice(total: int, used: int, *, noun: str = "features") -> str:
    percent = used / total * 100 if total else 0
    message = f"Heatmap-usable {noun}: {used:,} of {total:,} ({percent:.1f}%)"
    if used < total:
        message += (
            f" — {total - used:,} excluded because of missing or undefined values "
            "in the selected samples after preprocessing"
        )
    return message


@dataclass(frozen=True)
class CompletenessReport:
    """How many features a projection or clustering could actually use.

    Hierarchical clustering and PCA are undefined on a feature that is missing in
    any sample, so those features are excluded. Excluding them silently is the
    real hazard: the projection then rests on a smaller, abundance-biased subset
    and nothing says so. The count travels back with the result so the interface
    can state it in a notice beneath the plot.
    """

    kept: np.ndarray
    dropped: int
    total: int

    @property
    def any_dropped(self) -> bool:
        return self.dropped > 0

    @property
    def percent(self) -> float:
        return (self.dropped / self.total * 100.0) if self.total else 0.0


def _percent_text(value: float) -> str:
    """One significant-ish digit, but never rounded to a bare 0%.

    Reporting "0% dropped" when 27 features were dropped is worse than saying
    nothing, so anything above zero reports at least "<0.1%".
    """
    if value <= 0:
        return "0%"
    if value < 0.1:
        return "<0.1%"
    if value < 10:
        return f"{value:.1f}%"
    return f"{value:.0f}%"


def completeness_message(
    report: CompletenessReport,
    *,
    noun: str = "features",
    purpose: str = "clustering",
) -> str | None:
    """The short red note shown under a plot, or None when nothing was dropped."""
    if not report.any_dropped:
        return None
    return (
        f"{_percent_text(report.percent)} of {noun} dropped for {purpose} "
        f"({report.dropped:,} of {report.total:,}) — not observed in every sample"
    )


def drop_incomplete_features(
    matrix: pd.DataFrame | np.ndarray,
    *,
    context: str = "heatmap",
    minimum_rows: int = 1,
) -> tuple[np.ndarray, CompletenessReport]:
    """Return the fully observed rows, plus what that cost.

    Replaces the previous behaviour of refusing the whole matrix when any value
    was missing. On the bundled HEK293 data that refusal cost the entire protein
    ANOVA heatmap because 27 of 2,908 features were incomplete, and the remedy it
    suggested -- disabling clustering -- was not reachable from the interface.

    Raises only when nothing usable is left, which is a real failure rather than
    a reportable one.
    """
    if isinstance(matrix, pd.DataFrame):
        numeric = matrix.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    else:
        numeric = np.asarray(matrix, dtype=float)
    if numeric.ndim != 2:
        raise ValueError("Clustering requires a two-dimensional matrix.")

    rows, columns = numeric.shape
    complete = np.isfinite(numeric).all(axis=1)
    kept_count = int(complete.sum())

    if kept_count < max(1, minimum_rows):
        raise ValueError(
            f"{context.capitalize()} cannot be computed because only {kept_count} of "
            f"{rows} features are observed in all {columns} samples. Run Imputation "
            "successfully and select 'Imputed Data', or relax the completeness "
            "filter. The data source was not changed automatically."
        )

    return numeric[complete], CompletenessReport(
        kept=complete, dropped=rows - kept_count, total=rows
    )


def row_zscore(matrix):
    """Row-wise z-scores with the sample standard deviation (ddof=1).

    One definition for every heatmap: the ANOVA heatmaps used the population
    SD (ddof=0) while the pathway and phosphosite heatmaps used ddof=1, and all
    three said "z-score". ddof=1 is the convention of the tool's other
    statistics and of the R package. A row with no spread (or a non-finite SD)
    is centred and left at zero rather than made undefined, as R does.
    """
    values = np.asarray(matrix, dtype=float)
    row_mean = np.nanmean(values, axis=1, keepdims=True)
    row_sd = np.nanstd(values, axis=1, ddof=1, keepdims=True)
    row_sd[(row_sd == 0) | ~np.isfinite(row_sd)] = 1.0
    return (values - row_mean) / row_sd
