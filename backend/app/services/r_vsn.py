"""VSN normalization delegated to Bioconductor `vsn` via Rscript.

A Python reimplementation was written and validated against the reference during
review. It matched exactly on well-conditioned data (max|diff| ~1e-11) but
diverged by up to 2.2 log2 units on wide-dynamic-range and low-abundance inputs,
because VSN's profile likelihood is flat and multimodal there: differences of a
few nLL units out of hundreds of thousands move the fitted transformation
materially, and the optimizer's path decides which optimum is reached. On two of
three disagreeing cases the port found a *better* optimum by vsn's own
criterion, which is still not the same as reproducing vsn.

So VSN is delegated rather than reimplemented: when a user's Methods section says
"VSN", it means Huber et al. as implemented in Bioconductor `vsn`. The option is
hidden in the UI unless both Rscript and the package are present.

See local/review-harness/vsn/README.md for the reverse-engineered model and the
validation numbers.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.r_runtime import detect_r_runtime

# vsn expects linear intensities and returns values on a glog2 scale that
# approaches log2 for large values, so it replaces the log2 step rather than
# following it. The caller hands us log2 values, so we invert first.
_PROBE_SCRIPT = 'cat(requireNamespace("vsn", quietly=TRUE))'

# Raw little-endian float64 rather than CSV. VSN's fit is unstable enough on real
# data that a 1-ULP difference in the input moves the output by ~0.5 log2 units,
# and R's text parser does not reproduce every double that Python writes: on the
# bundled HEK293 phospho matrix 1124 of 101071 values came back off by one ULP,
# which was enough to change the result. Binary transport removes the whole class
# of error and needs no extra R package. NaN survives IEEE-754 unchanged.
_VSN_SCRIPT = """
args <- commandArgs(trailingOnly = TRUE)
suppressMessages(library(vsn))
nr <- as.integer(args[3]); nc <- as.integer(args[4])
con <- file(args[1], "rb")
v <- readBin(con, what = "double", n = nr * nc, size = 8, endian = "little")
close(con)
x <- matrix(v, nrow = nr, ncol = nc, byrow = TRUE)
# vsn rejects NaN but accepts NA. R distinguishes the two (NA_real_ is a NaN with
# a specific payload); IEEE NaN arriving over the wire must be converted, or
# vsn2() aborts with "must be finite numeric or NA; please no NaN".
x[is.nan(x)] <- NA_real_
fit <- suppressWarnings(vsn2(x, verbose = FALSE))
out <- file(args[2], "wb")
writeBin(as.vector(t(exprs(fit))), out, size = 8, endian = "little")
close(out)
"""

_TIMEOUT_SECONDS = 900


def _creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


@lru_cache(maxsize=1)
def vsn_availability() -> dict[str, object]:
    """Whether VSN can actually be run: Rscript present *and* the package installed."""
    runtime = detect_r_runtime()
    executable = runtime.get("executable")
    if not runtime.get("available") or not executable:
        return {
            "available": False,
            "rAvailable": False,
            "packageInstalled": False,
            "reason": "Rscript was not found. VSN requires R with the Bioconductor 'vsn' package.",
        }
    try:
        completed = subprocess.run(
            [str(executable), "-e", _PROBE_SCRIPT],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
            creationflags=_creationflags(),
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {
            "available": False,
            "rAvailable": True,
            "packageInstalled": False,
            "reason": f"Could not query R for the 'vsn' package: {exc}",
        }
    installed = "TRUE" in (completed.stdout or "")
    return {
        "available": installed,
        "rAvailable": True,
        "packageInstalled": installed,
        "reason": (
            None
            if installed
            else (
                "R is available but the Bioconductor 'vsn' package is not installed. "
                'Install it with: BiocManager::install("vsn")'
            )
        ),
    }


def clear_vsn_availability_cache() -> None:
    vsn_availability.cache_clear()


def vsn_normalize_linear(values: pd.DataFrame) -> pd.DataFrame:
    """Run Bioconductor vsn over **linear** intensities, returning glog2 values.

    Takes linear input deliberately. vsn's fit is numerically unstable on real
    data: perturbing the input at machine epsilon -- which is all that
    reconstructing intensities as 2**log2 does -- moves the output by ~0.34 log2
    units, and R reproduces that same disagreement with itself. Handing over the
    untransformed values is what makes the result match a direct vsn2() call.
    """
    availability = vsn_availability()
    if not availability.get("available"):
        raise ValueError(str(availability.get("reason") or "VSN normalization is unavailable."))

    executable = str(detect_r_runtime().get("executable"))
    numeric = values.apply(pd.to_numeric, errors="coerce")
    linear = numeric.to_numpy(dtype=float)

    rows, columns = linear.shape
    with tempfile.TemporaryDirectory(prefix="copylot_vsn_") as directory:
        root = Path(directory)
        script_path, input_path, output_path = (
            root / "vsn.R",
            root / "in.bin",
            root / "out.bin",
        )
        script_path.write_text(_VSN_SCRIPT, encoding="utf-8")
        input_path.write_bytes(np.ascontiguousarray(linear, dtype="<f8").tobytes())
        try:
            completed = subprocess.run(
                [
                    executable,
                    str(script_path),
                    str(input_path),
                    str(output_path),
                    str(rows),
                    str(columns),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                creationflags=_creationflags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"VSN normalization timed out after {_TIMEOUT_SECONDS} seconds."
            ) from exc
        if completed.returncode != 0 or not output_path.is_file():
            # Keep several lines: R prints the cause first and a generic
            # "execution halted" last, so the tail alone is useless.
            detail = [
                line.strip()
                for line in (completed.stderr or completed.stdout or "").splitlines()
                if line.strip()
            ]
            message = " | ".join(detail[-4:]) if detail else "no output"
            raise ValueError(f"VSN normalization failed in R: {message}")
        raw = np.frombuffer(output_path.read_bytes(), dtype="<f8")
        if raw.size != rows * columns:
            raise ValueError(
                f"VSN returned {raw.size} values for a {rows}x{columns} matrix."
            )
        transformed = raw.reshape(rows, columns)

    if transformed.shape != numeric.shape:
        raise ValueError(
            "VSN returned an unexpected shape "
            f"({transformed.shape} for input {numeric.shape})."
        )
    return pd.DataFrame(transformed, index=values.index, columns=values.columns)


def vsn_reference_version() -> str | None:
    """Package version, for the report and Methods section."""
    availability = vsn_availability()
    if not availability.get("available"):
        return None
    executable = str(detect_r_runtime().get("executable"))
    try:
        completed = subprocess.run(
            [executable, "-e", 'cat(as.character(packageVersion("vsn")))'],
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
            creationflags=_creationflags(),
        )
    except Exception:  # noqa: BLE001
        return None
    text = (completed.stdout or "").strip()
    return text or None


__all__ = [
    "clear_vsn_availability_cache",
    "vsn_availability",
    "vsn_normalize_linear",
    "vsn_reference_version",
]
