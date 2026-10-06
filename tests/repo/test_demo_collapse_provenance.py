"""The demo configs state how the shipped phosphoprotein file was collapsed, truthfully.

The viewer never collapses anything; `collapse_mode` is provenance, and it
decides whether the phosphoprotein values are labelled as intensities or as
ratios to each site's median. The root config said `sum_ignore_na` while the
portal config said `robust_site_median` for the same file, so the portal
labelled sums as ratios. Recomputing the file shows `sum_ignore_na` is right.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "proteomicscopylot" / "example_data"
CONFIGS = [ROOT / "viewer_config.json", ROOT / "viewer_data" / "HEK293" / "viewer_config.json",
           ROOT / "tests" / "fixtures" / "viewer_config.json"]


def _mode(config: Path) -> str:
    datasets = json.loads(config.read_text(encoding="utf-8"))["datasets"]
    return datasets["HEK293"]["collapse_mode"]


def test_both_demo_configs_declare_the_same_collapse_mode():
    assert {_mode(config) for config in CONFIGS} == {"sum_ignore_na"}


def test_the_declared_mode_reproduces_the_shipped_phosphoprotein_file():
    meta = pd.read_csv(EXAMPLE / "phospho_metadata_full.csv")
    sites = pd.read_csv(EXAMPLE / "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv", sep="\t")
    shipped = pd.read_csv(EXAMPLE / "phosprot_filtered_data_full.csv")
    rebuilt = notebook.transform_phosprot(sites, meta, mode=_mode(CONFIGS[0]), data_scale="log2")
    rebuilt = rebuilt[0] if isinstance(rebuilt, tuple) else rebuilt
    samples = meta["sample"].astype(str).tolist()
    merged = shipped.merge(rebuilt, on="Phosphoprotein", suffixes=("_shipped", "_rebuilt"))
    assert len(merged) == len(shipped) == len(rebuilt)
    left = merged[[f"{s}_shipped" for s in samples]].to_numpy(float)
    right = merged[[f"{s}_rebuilt" for s in samples]].to_numpy(float)
    np.testing.assert_array_equal(np.isfinite(left), np.isfinite(right))
    np.testing.assert_allclose(left[np.isfinite(left)], right[np.isfinite(right)], rtol=0, atol=1e-9)
