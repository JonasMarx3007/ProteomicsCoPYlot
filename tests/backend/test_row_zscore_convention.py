"""One z-score definition for every heatmap, in all three pipelines.

The ANOVA heatmaps used the population SD (ddof=0) while the pathway and
phosphosite heatmaps used the sample SD (ddof=1); every colour bar said
"Z-score". The shared helper uses ddof=1 -- the convention of the tool's other
statistics and of the R package -- and leaves a row with no spread at zero.
"""

from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.services import clustering_tools, single_protein_tools, stats_tools
from proteomicscopylot import notebook_functions

MATRIX = np.array([
    [1.0, 2.0, 3.0, 6.0],
    [5.0, 5.0, 5.0, 5.0],          # no spread -> 0
    [np.nan, 4.0, 8.0, 12.0],      # missing value skipped
    [7.0, np.nan, np.nan, np.nan], # single value -> 0
])


def _expected(matrix):
    frame = pd.DataFrame(matrix)
    sd = frame.std(axis=1, ddof=1).replace(0, 1).fillna(1)
    return frame.sub(frame.mean(axis=1), axis=0).div(sd, axis=0).to_numpy()


def test_helper_uses_the_sample_sd_and_zeroes_flat_rows() -> None:
    z = clustering_tools.row_zscore(MATRIX)
    expected = _expected(MATRIX)
    assert np.allclose(z, expected, equal_nan=True)
    assert np.allclose(z[1], 0)
    assert z[3, 0] == 0 and np.isnan(z[3, 1:]).all()
    # Not the population SD: the first row would then be scaled by sqrt(4/3).
    population = (MATRIX[0] - MATRIX[0].mean()) / MATRIX[0].std()
    assert not np.allclose(z[0], population)


def test_package_helper_is_identical() -> None:
    assert np.allclose(notebook_functions.row_zscore(MATRIX), clustering_tools.row_zscore(MATRIX), equal_nan=True)


def test_every_python_heatmap_calls_the_shared_helper() -> None:
    for module in (stats_tools, single_protein_tools):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "row_zscore(" in source, module.__name__
        assert "np.nanstd(matrix" not in source, module.__name__
        assert "row.std(skipna=True)" not in source, module.__name__
    package = Path(notebook_functions.__file__).read_text(encoding="utf-8")
    assert package.count("row_zscore(") >= 5
    assert "row.std(skipna=True)" not in package


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="Rscript unavailable")
def test_r_helper_agrees(tmp_path) -> None:
    pd.DataFrame(MATRIX).to_csv(tmp_path / "m.csv", index=False)
    script = f'''
      source("{(ROOT / "proteomicscopylot" / "notebook_functions.R").as_posix()}")
      m <- as.matrix(read.csv("{(tmp_path / "m.csv").as_posix()}"))
      write.csv(.row_zscore(m), "{(tmp_path / "z.csv").as_posix()}", row.names = FALSE)
    '''
    result = subprocess.run(["Rscript", "-e", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    r_z = pd.read_csv(tmp_path / "z.csv").to_numpy(dtype=float)
    assert np.allclose(r_z, clustering_tools.row_zscore(MATRIX), equal_nan=True)
