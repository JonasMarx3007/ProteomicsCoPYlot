"""ANOVA flags rows with no variation within any condition.

Such a row (A = 20, 20, 20; B = 22, 22, 22; C = 24, 24, 24) gets an infinite F
and p = 0, so it tops the ranking although nothing about the difference is
unusual, and Tukey HSD then cannot compare it. The web app, the pip package and
the R package all add a `zero_variance` column; the web app also says so on the
page and when Tukey leaves such rows out.
Rows constant throughout are still dropped as untestable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]

SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]


def _data() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(rng.normal(20, 1, (30, 9)), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(30)])
    frame.loc[0, SAMPLES] = [20, 20, 20, 22, 22, 22, 24, 24, 24]          # infinite F
    frame.loc[1, SAMPLES] = [14.05] * 3 + [15.05] * 3 + [16.05] * 3       # float noise: huge F
    frame.loc[2, SAMPLES] = [18.0] * 9                                    # constant: untestable
    frame.loc[3, SAMPLES] = [20, 20, 20, 22, 22.5, 21.5, 24, 24, 24]      # one group varies
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})
    return frame, meta


def _flags(table: pd.DataFrame) -> dict[str, bool]:
    return dict(zip(table["ProteinNames"].astype(str), table["zero_variance"].astype(bool)))


def test_the_pip_package_flags_only_rows_without_any_within_group_variation():
    frame, meta = _data()
    table = notebook.anova_data_f(frame, meta)
    flags = _flags(table)
    assert flags["P0"] and flags["P1"]
    assert not flags["P3"]
    assert sum(flags.values()) == 2
    assert "P2" not in flags  # constant throughout: still dropped
    assert table.columns.get_loc("zero_variance") == table.columns.get_loc("neg_log10_selected_pval") + 1


@pytest.mark.requires_r()
def test_r_matches_python(tmp_path):
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    frame, meta = _data()
    frame.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    script = f"""
    suppressPackageStartupMessages(source("{(ROOT / 'proteomicscopylot' / 'notebook_functions.R').as_posix()}"))
    data <- read.csv("{(tmp_path / 'data.csv').as_posix()}", check.names = FALSE, stringsAsFactors = FALSE)
    meta <- read.csv("{(tmp_path / 'meta.csv').as_posix()}", check.names = FALSE, stringsAsFactors = FALSE)
    out <- anova_data_f(data, meta)
    write.csv(out[, c("ProteinNames", "zero_variance", "neg_log10_selected_pval")],
              "{(tmp_path / 'out.csv').as_posix()}", row.names = FALSE)
    """
    completed = subprocess.run([str(runtime["executable"]), "-e", script], capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    r_table = pd.read_csv(tmp_path / "out.csv")
    python = notebook.anova_data_f(frame, meta)
    assert r_table["ProteinNames"].tolist() == python["ProteinNames"].tolist()
    assert r_table["zero_variance"].tolist() == python["zero_variance"].tolist()


def test_the_web_app_flags_them_and_says_so_including_for_tukey():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.schemas.annotation import AnnotationFilterConfig
    from app.services.annotation_store import reset_all_annotations, save_annotation
    from app.services.dataset_store import reset_all_datasets, save_table_dataset

    frame, meta = _data()
    reset_all_datasets()
    reset_all_annotations()
    save_table_dataset("anova.tsv", "protein", frame)
    save_annotation(kind="protein", source_data=frame, log2_data=frame, filtered_data=frame, metadata=meta,
                    is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[])
    try:
        with TestClient(app) as client:
            response = client.post("/api/stats/anova/run", json={"kind": "protein", "postHoc": "tukey"})
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        flags = {row["ProteinNames"]: row["zero_variance"] for row in body["rows"]}
        assert flags["P0"] and flags["P1"] and not flags["P3"]
        text = " ".join(body["warnings"])
        assert "2 rows have no variation within any condition" in text
        compared = {row["ProteinNames"] for row in body["postHocRows"]}
        assert "P0" not in compared
        left_out = sum(1 for name in ("P0", "P1") if name not in compared)
        assert f"Tukey HSD left out {left_out:,} significant rows" in text
    finally:
        reset_all_datasets()
        reset_all_annotations()
