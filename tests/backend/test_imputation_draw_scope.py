from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.schemas.data_tools import ImputationRunRequest
from app.services.functions import impute_values_with_diagnostics
from proteomicscopylot.notebook_functions import impute_values

WT = [f"WT_{i}" for i in range(1, 6)]
KO = [f"KO_{i}" for i in range(1, 6)]
R_SOURCE = ROOT / "proteomicscopylot" / "notebook_functions.R"


def _offset_frame(offset: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(3)
    values = rng.normal(22, 2.0, (3000, 10))
    values[:, 5:] += offset
    frame = pd.DataFrame(values, columns=WT + KO)
    frame.loc[0, "KO_1"] = np.nan
    meta = pd.DataFrame({"sample": WT + KO, "condition": ["WT"] * 5 + ["KO"] * 5})
    return frame, meta


def test_every_pipeline_draws_per_sample_by_default() -> None:
    assert inspect.signature(impute_values).parameters["sample_wise"].default is True
    assert (
        inspect.signature(impute_values_with_diagnostics).parameters["sample_wise"].default
        is True
    )
    assert ImputationRunRequest(kind="protein").sampleWise is True

    r_signature = re.search(r"impute_values <- function\((.*?)\)", R_SOURCE.read_text(encoding="utf-8"), re.S)
    assert r_signature and "sample_wise=TRUE" in r_signature.group(1), (
        "the R package still draws globally by default; the three implementations "
        "must agree on this or the same call gives different numbers per language"
    )


def test_a_per_sample_draw_lands_near_that_sample_own_floor() -> None:
    frame, meta = _offset_frame()
    own_floor = np.nanquantile(frame[KO].to_numpy(), 0.01)
    combined_floor = np.nanquantile(frame[WT + KO].to_numpy(), 0.01)
    assert own_floor - combined_floor > 0.3, "fixture lost its loading offset"

    per_sample = impute_values(frame.copy(), meta).loc[0, "KO_1"]
    global_draw = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]

    assert abs(per_sample - own_floor) < abs(global_draw - own_floor), (
        f"the default draw ({per_sample:.2f}) should sit nearer the sample's own "
        f"detection floor ({own_floor:.2f}) than the global draw ({global_draw:.2f})"
    )


def test_a_global_draw_is_still_available() -> None:
    frame, meta = _offset_frame()
    a = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]
    b = impute_values(frame.copy(), meta, sample_wise=False).loc[0, "KO_1"]
    assert a == b
    assert a != impute_values(frame.copy(), meta).loc[0, "KO_1"]


def test_the_draw_is_still_reproducible_for_a_given_seed() -> None:
    frame, meta = _offset_frame()
    first = impute_values(frame.copy(), meta, seed=99)[WT + KO].to_numpy()
    second = impute_values(frame.copy(), meta, seed=99)[WT + KO].to_numpy()
    assert np.array_equal(first, second, equal_nan=True)
