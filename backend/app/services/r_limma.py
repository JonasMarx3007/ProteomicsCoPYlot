"""Moderated t-tests delegated to Bioconductor `limma` via Rscript.

limma's empirical-Bayes moderation (Smyth 2004) borrows variance information
across all rows: each row's variance is shrunk towards a prior fitted to the
whole matrix, and the degrees of freedom grow by the prior's. As with VSN, "limma" in a Methods section means limma as
Bioconductor ships it, so the test is delegated, not reimplemented; the option
is offered only when Rscript and the package are present.

Two designs, two variance models:

* unpaired: `lmFit` on a two-group design, contrast condition1 - condition2;
* paired:   `lmFit` on the within-pair differences, intercept only -- the
  classic limma paired analysis (Guide §9.4.1), which equals a blocked
  two-group fit with one block per pair.
* `robust=TRUE` in `eBayes` fits the prior with a robust estimator, so a few
  rows with extreme variances do not dominate it (Phipson et al. 2016).

The bridge returns moderated p-values, standard errors and degrees of freedom.
The caller retains fold changes and computes BH adjustment and significance
from the moderated p-values. Rows with too few
values for a row-wise variance are not sent and keep no p-value, exactly as in
the plain tests.
"""

from __future__ import annotations

import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services.r_runtime import detect_r_runtime

# One probe answers both questions: installed, and which R and limma (so the
# report and the runtime page do not spawn R again for the version, 2026-10-22).
_PROBE_SCRIPT = ('if (requireNamespace("limma", quietly=TRUE)) '
                 'cat("TRUE|", as.character(getRversion()), "|", as.character(packageVersion("limma")), sep="") '
                 'else cat("FALSE")')

# Binary transport as in r_vsn.py: a text round trip does not reproduce every
# double. args: in.bin out.bin nrow ncol n1 paired robust
_LIMMA_SCRIPT = """
args <- commandArgs(trailingOnly = TRUE)
suppressMessages(library(limma))
nr <- as.integer(args[3]); nc <- as.integer(args[4]); n1 <- as.integer(args[5])
paired <- identical(args[6], "1"); robust <- identical(args[7], "1")
con <- file(args[1], "rb")
v <- readBin(con, what = "double", n = nr * nc, size = 8, endian = "little")
close(con)
x <- matrix(v, nrow = nr, ncol = nc, byrow = TRUE)
x[is.nan(x)] <- NA_real_
if (paired) {
  # Columns are the within-pair differences; a one-sample fit of the mean difference.
  design <- matrix(1, nrow = nc, ncol = 1, dimnames = list(NULL, "diff"))
  fit <- lmFit(x, design)
  coef <- "diff"
} else {
  group <- factor(c(rep("g1", n1), rep("g2", nc - n1)), levels = c("g2", "g1"))
  design <- model.matrix(~ group)
  fit <- lmFit(x, design)
  coef <- "groupg1"
}
fit <- eBayes(fit, robust = robust)
out <- file(args[2], "wb")
# Moderated SE per row: stdev.unscaled * sqrt(s2.post), the SE the moderated t divides by.
se <- fit$stdev.unscaled[, coef] * sqrt(fit$s2.post)
writeBin(c(fit$p.value[, coef], fit$df.total, se, fit$df.prior[1], fit$s2.prior[1]), out, size = 8, endian = "little")
close(out)
"""

_TIMEOUT_SECONDS = 900


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


@lru_cache(maxsize=1)
def limma_availability() -> dict[str, object]:
    """Whether a moderated test can actually be run: Rscript *and* limma."""
    runtime = detect_r_runtime()
    executable = runtime.get("executable")
    if not runtime.get("available") or not executable:
        return {
            "available": False,
            "rAvailable": False,
            "packageInstalled": False,
            "reason": "Rscript was not found. Moderated t-tests require R with the Bioconductor 'limma' package.",
        }
    try:
        completed = subprocess.run(
            [str(executable), "-e", _PROBE_SCRIPT],
            capture_output=True, check=False, text=True, timeout=60, creationflags=_creationflags(),
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {
            "available": False,
            "rAvailable": True,
            "packageInstalled": False,
            "reason": f"Could not query R for the 'limma' package: {exc}",
        }
    answer = (completed.stdout or "").strip()
    installed = answer.startswith("TRUE")
    parts = answer.split("|")
    return {
        "available": installed,
        "rAvailable": True,
        "packageInstalled": installed,
        "rVersion": parts[1] if installed and len(parts) == 3 else None,
        "packageVersion": parts[2] if installed and len(parts) == 3 else None,
        "reason": (
            None if installed else (
                "R is available but the Bioconductor 'limma' package is not installed. "
                'Install it with: BiocManager::install("limma")'
            )
        ),
    }


def clear_limma_availability_cache() -> None:
    limma_availability.cache_clear()


def moderated_t_pvalues(
    values: np.ndarray,
    n1: int,
    *,
    paired: bool,
    robust: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Row-wise moderated p-values from limma.

    `values` is rows x samples: the first `n1` columns are condition 1 and the
    rest condition 2 (unpaired), or every column is one pair's difference
    (paired; `n1` is then ignored). Returns (p-values, moderated df per row,
    moderated SE per row, prior df, prior variance s0^2). The SE is the one the
    moderated t divides by (stdev.unscaled * sqrt(s2.post)), so a protein
    correction can combine it like a plain SE. A row limma cannot fit (fewer
    than two residual degrees of freedom) comes back NaN.
    """
    availability = limma_availability()
    if not availability.get("available"):
        raise ValueError(str(availability.get("reason") or "Moderated t-tests are unavailable."))

    matrix = np.ascontiguousarray(np.asarray(values, dtype=float), dtype="<f8")
    rows, columns = matrix.shape
    if rows == 0:
        return np.array([]), np.array([]), np.array([]), float("nan"), float("nan")
    executable = str(detect_r_runtime().get("executable"))
    with tempfile.TemporaryDirectory(prefix="copylot_limma_") as directory:
        root = Path(directory)
        script_path, input_path, output_path = root / "limma.R", root / "in.bin", root / "out.bin"
        script_path.write_text(_LIMMA_SCRIPT, encoding="utf-8")
        input_path.write_bytes(matrix.tobytes())
        try:
            completed = subprocess.run(
                [executable, str(script_path), str(input_path), str(output_path),
                 str(rows), str(columns), str(int(n1)), "1" if paired else "0", "1" if robust else "0"],
                capture_output=True, check=False, text=True, timeout=_TIMEOUT_SECONDS,
                creationflags=_creationflags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"The moderated t-test timed out after {_TIMEOUT_SECONDS} seconds.") from exc
        if completed.returncode != 0 or not output_path.is_file():
            detail = [line.strip() for line in (completed.stderr or completed.stdout or "").splitlines() if line.strip()]
            message = " | ".join(detail[-4:]) if detail else "no output"
            raise ValueError(f"The moderated t-test failed in R: {message}")
        raw = np.frombuffer(output_path.read_bytes(), dtype="<f8")
    if raw.size != 3 * rows + 2:
        raise ValueError(f"limma returned {raw.size} values for {rows} rows.")
    return (raw[:rows].copy(), raw[rows:2 * rows].copy(), raw[2 * rows:3 * rows].copy(),
            float(raw[3 * rows]), float(raw[3 * rows + 1]))


def limma_reference_version() -> str | None:
    """Package version, for the report and Methods section; read from the cached probe."""
    availability = limma_availability()
    if not availability.get("available"):
        return None
    return str(availability.get("packageVersion") or "") or None


__all__ = [
    "clear_limma_availability_cache",
    "limma_availability",
    "limma_reference_version",
    "moderated_t_pvalues",
]
