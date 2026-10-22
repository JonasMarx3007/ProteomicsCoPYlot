"""Loads `proteomicscopylot/_core.py`, the arithmetic the app shares with the pip package.

The backend does not import the pip package (it is not installed next to the
server, and a released version could differ from this checkout). It loads the
one file from this checkout instead: `proteomicscopylot/_core.py` from the
repository (and the container, which copies it), or the copy a frozen build
bundles with the notebook sources.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def core_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "notebook_sources" / "_core.py"
    return Path(__file__).resolve().parents[3] / "proteomicscopylot" / "_core.py"


def _load():
    name = "copylot_shared_core"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, core_path())
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the shared core from {core_path()}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # before exec: dataclasses and pickling look it up
    spec.loader.exec_module(module)
    return module


_core = _load()

_SAMPLE_DOTTED_SUFFIX = _core._SAMPLE_DOTTED_SUFFIX
_SAMPLE_TEXT_SUFFIX = _core._SAMPLE_TEXT_SUFFIX
_SAMPLE_ACQUISITION_SUFFIX = _core._SAMPLE_ACQUISITION_SUFFIX
_SAMPLE_NUMBER = _core._SAMPLE_NUMBER
strip_sample_measurement_suffix = _core.strip_sample_measurement_suffix
extract_sample_id = _core.extract_sample_id
_significance_pval_column = _core._significance_pval_column
constant_within_group = _core.constant_within_group
condition_mean = _core.condition_mean
resolve_feature_scaling = _core.resolve_feature_scaling
_auto_label_col = _core._auto_label_col
bh_adjust = _core.bh_adjust
satterthwaite = _core.satterthwaite
pooled_se_df = _core.pooled_se_df
two_sided_t_pvalues = _core.two_sided_t_pvalues
split_tokens = _core.split_tokens
match_sites_to_proteins = _core.match_sites_to_proteins
protein_corrected_site_changes = _core.protein_corrected_site_changes
