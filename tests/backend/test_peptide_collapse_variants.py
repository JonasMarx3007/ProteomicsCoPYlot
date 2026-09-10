from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.external import PeptideCollapseRequest
from app.services.external_functions import (
    peptideCollapse,
)

RUNS = ["run1", "run2"]
PEPTIDES = [
    ("SAMPLE[Phospho (STY)]PEPTIDEK", "P00001", "GENEA", 10),
    ("ANOTHER[Phospho (STY)]PEPTIDER", "P00002", "GENEB", 20),
    ("THIRDPEP[Phospho (STY)]TIDEK", "P00003", "GENEC", 30),
]


def _table(run2_first) -> pd.DataFrame:
    quantities = {"run1": [1000.0, 2000.0, 4000.0], "run2": [run2_first, 2000.0, 4000.0]}
    rows = []
    for run in RUNS:
        for (seq, protein, gene, position), quantity in zip(PEPTIDES, quantities[run]):
            rows.append(
                {
                    "R.FileName": run,
                    "EG.PrecursorId": f"_{seq}_.2",
                    "EG.TotalQuantity (Settings)": quantity,
                    "PEP.PeptidePosition": str(position),
                    "EG.PTMAssayProbability": 0.99,
                    "PG.Genes": gene,
                    "PG.ProteinGroups": protein,
                }
            )
    return pd.DataFrame(rows)


def _collapse(func, table: pd.DataFrame) -> pd.DataFrame:
    with contextlib.redirect_stdout(io.StringIO()):
        return func(table.copy(), cutoff=0.0)


def _quantities(frame: pd.DataFrame) -> np.ndarray:
    columns = [c for c in frame.columns if any(run in str(c) for run in RUNS)]
    return frame[columns].to_numpy(dtype=float, na_value=np.nan).ravel()


def _upload(**data):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app).post(
        "/api/external/peptide-collapse/upload",
        files={"file": ("x.tsv", io.BytesIO(b"placeholder"), "text/tab-separated-values")},
        data={"cutoff": "0.0", **data},
    )


def test_the_missing_value_sentinel_becomes_nan_not_negative_infinity() -> None:
    values = _quantities(_collapse(peptideCollapse, _table(0.0)))
    assert not np.isinf(values).any(), (
        "log2(0) leaked through as -inf; filter_data counts -inf as an observation, "
        "so the row survives filtering and then yields an infinite fold change"
    )
    assert np.isnan(values).sum() == 1


def test_a_genuine_intensity_of_one_is_not_deleted() -> None:
    values = _quantities(_collapse(peptideCollapse, _table(1.0)))
    assert not np.isnan(values).any(), "a real measurement of 1.0 was dropped as if it were a sentinel"
    assert 0.0 in [round(float(v), 6) for v in values]


def test_a_filtered_cell_does_not_crash_the_collapse() -> None:
    values = _quantities(_collapse(peptideCollapse, _table("Filtered")))
    assert np.isnan(values).sum() == 1
    assert not np.isinf(values).any()



@pytest.mark.parametrize("version", ["fixed", "newest", "legacy", "bogus"])
def test_removed_version_parameter_is_rejected(version) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PeptideCollapseRequest(inputPath="x.tsv", collapseVersion=version)
    response = _upload(collapseVersion=version)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_upload_runs_corrected_collapse_without_version() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/external/peptide-collapse/upload",
            files={"file": ("x.tsv", _table(0.0).to_csv(sep="\t", index=False).encode(), "text/tab-separated-values")},
        )
    assert response.status_code == 200, response.text
    result = pd.read_csv(io.StringIO(response.text), sep="\t")
    values = _quantities(result)
    assert not np.isinf(values).any()
    assert np.isnan(values).sum() == 1


def test_local_json_route_uses_the_same_corrected_output(tmp_path) -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    source = tmp_path / "input.tsv"
    _table(0.0).to_csv(source, sep="\t", index=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/external/peptide-collapse/run", json={"inputPath": str(source)}
        )
        rejected = client.post(
            "/api/external/peptide-collapse/run",
            json={"inputPath": str(source), "collapseVersion": "newest"},
        )
    assert rejected.status_code == 422
    assert response.status_code == 200, response.text
    assert response.json()["success"]
    assert "collapseVersion" not in response.json()
    result = pd.read_csv(response.json()["outputPath"], sep="\t")
    expected = _collapse(peptideCollapse, _table(0.0))
    pd.testing.assert_frame_equal(result, expected, check_dtype=False)


def test_clean_data_has_expected_log2_quantities() -> None:
    values = _quantities(_collapse(peptideCollapse, _table(1500.0)))
    np.testing.assert_allclose(
        np.sort(values), np.sort(np.log2([1000, 2000, 4000, 1500, 2000, 4000]))
    )


def test_default_cutoff_keeps_all_sites_and_explicit_cutoff_filters() -> None:
    table = _table(1500.0)
    table.loc[table["PG.Genes"] == "GENEA", "EG.PTMAssayProbability"] = 0.5
    everything = _collapse(peptideCollapse, table)
    with contextlib.redirect_stdout(io.StringIO()):
        class_one = peptideCollapse(table.copy(), cutoff=0.75)
    assert len(everything) == 3
    assert len(class_one) == 2
    assert PeptideCollapseRequest(inputPath="x.tsv").cutoff == 0.0
