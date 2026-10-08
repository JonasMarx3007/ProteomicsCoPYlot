"""The R phosphoprotein collapse keeps real sample names and matches Python.

`transform_phosprot` in R built its table with `as.data.frame(row)`, whose
default `check.names = TRUE` rewrote names starting with a digit or containing
"-" -- which Spectronaut and DIA-NN names nearly always do -- and the next
lookup failed with "undefined columns selected". The fixtures used names like
`ps1`, and the R example loads a pre-collapsed table, so nothing caught it.
This runs the bundled phosphosite report, real names and all, through both
packages and every aggregation mode.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "proteomicscopylot" / "example_data"
SITES = EXAMPLE / "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv"
META = EXAMPLE / "phospho_metadata_full.csv"
MODES = ("robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na")


from _r_runtime import RSCRIPT


def test_example_sample_names_are_the_kind_that_broke():
    samples = pd.read_csv(META)["sample"].astype(str)
    assert samples.str.match(r"^\d").all() and samples.str.contains("-").all()


@pytest.mark.requires_r()
def test_r_collapse_keeps_real_sample_names_and_matches_python(tmp_path):
    sites = pd.read_csv(SITES, sep="\t")
    meta = pd.read_csv(META)
    samples = meta["sample"].astype(str).tolist()
    # The bundled report is linear; log2 it once so both packages read the same values.
    log2 = sites.copy()
    log2[samples] = np.log2(log2[samples].apply(pd.to_numeric, errors="coerce").where(lambda v: v > 0))
    log2.to_csv(tmp_path / "sites.tsv", sep="\t", index=False)
    meta.to_csv(tmp_path / "meta.tsv", sep="\t", index=False)
    script = r'''
      args <- commandArgs(trailingOnly = TRUE)
      source("proteomicscopylot/notebook_functions.R")
      d <- read.delim(file.path(args[1], "sites.tsv"), check.names = FALSE, stringsAsFactors = FALSE)
      m <- read.delim(file.path(args[1], "meta.tsv"), check.names = FALSE, stringsAsFactors = FALSE)
      for (mode in c("robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na")) {
        out <- transform_phosprot(d, m, mode = mode, data_scale = "log2", coverage_data = d)
        stopifnot(all(m$sample %in% names(out)))
        write.table(out, file.path(args[1], paste0("r_", mode, ".tsv")), sep = "\t", row.names = FALSE, quote = TRUE)
      }
    '''
    run = subprocess.run([RSCRIPT, "-e", script, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout + run.stderr
    for mode in MODES:
        python = notebook.transform_phosprot(log2, meta, mode=mode, data_scale="log2", coverage_data=log2)
        r = pd.read_csv(tmp_path / f"r_{mode}.tsv", sep="\t")
        python = python.sort_values("Phosphoprotein").reset_index(drop=True)
        r = r.sort_values("Phosphoprotein").reset_index(drop=True)
        assert python["Phosphoprotein"].tolist() == r["Phosphoprotein"].tolist(), mode
        np.testing.assert_allclose(
            python[samples].to_numpy(dtype=float), r[samples].to_numpy(dtype=float),
            rtol=1e-9, atol=1e-10, equal_nan=True, err_msg=mode,
        )
