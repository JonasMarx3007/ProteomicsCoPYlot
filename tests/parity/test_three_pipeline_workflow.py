"""API upload -> annotation -> selection -> aggregation -> inference parity.

No stochastic draws: a supplied post-filter log2 matrix isolates downstream
agreement. Failures are reported at individual stages, not hidden in totals.
"""
from pathlib import Path
import gzip
import io
import json
import subprocess

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import annotation_store, dataset_store, metadata_upload_store
from app.services.r_runtime import detect_r_runtime
from proteomicscopylot import notebook_functions as nb

ROOT = Path(__file__).resolve().parents[2]
METHODS = ("none", "median", "quantile")
TESTS = ("unpaired", "unpaired_welch", "paired")
MODES = ("robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na")
SAMPLES = [f"{group}{rep}" for group in "ABCD" for rep in range(1, 5)]
IDS = {"protein": "ProteinNames", "phospho": "PTM_Collapse_key"}
STAGES = [(f"{kind}_{stage}", IDS[kind], "matrix") for kind in IDS for stage in ("normalized", "filtered", "empty")]
STAGES += [(f"{kind}_{source}_{test}{suffix}", IDS[kind], "stats")
           for kind in IDS for source in ("observed", "fixed") for test in TESTS for suffix in ("", "_control")]
STAGES += [(f"{prefix}_{source}_{mode}", "Phosphoprotein", category)
           for source in ("observed", "fixed") for mode in MODES
           for prefix, category in (("aggregate", "aggregate"), ("aggregate_filtered", "aggregate"), ("aggregate_stats", "stats"))]


def fixture_frames():
    # Deliberately shuffled pair order and reversed sample columns.
    order = [2, 0, 3, 1, 5, 7, 4, 6, 11, 9, 8, 10, 12, 14, 15, 13]
    meta = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES],
                         "pair_id": [s[1:] for s in SAMPLES]}).iloc[order].reset_index(drop=True)
    values = np.array([[10 + row * .8 + rep * .11 + ((row * rep + group) % 5) * .07 +
                        ([0, 2, .2, .4][group] if row < 4 else [0, -.7, .3, -.2][group])
                        for group in range(4) for rep in range(4)] for row in range(12)])
    values[1, 2] = np.nan
    values[6:8, 0] = np.nan  # Both sites missing in one sample; important after imputation.
    values[10, :] = np.nan
    values[10, [0, 4, 8, 12]] = 12.  # Fails every condition's completeness filter.
    values[11, :] = np.nan
    raw = pd.DataFrame(np.exp2(values), columns=SAMPLES)
    raw.loc[11, "A1"] = 0.  # Raw zero must become missing, not a measured log2 zero.
    protein = raw.copy()
    protein.insert(0, "ProteinNames", [f"P{i:02d}" for i in range(12)])
    protein.insert(1, "GeneNames", [f"G{i:02d}" for i in range(12)])
    phospho = raw.copy()
    for name, column in {
        "UPD_seq": [f"SEQ{i}*S" for i in range(12)], "PTM_localization": [f"S{i}" for i in range(12)],
        "Protein_group": [f"P{i // 2:02d}" for i in range(12)], "Gene_group": [f"G{i // 2:02d}" for i in range(12)],
        "PTM_Collapse_key": [f"K{i:02d}" for i in range(12)],
    }.items():
        phospho[name] = column
    return {kind: frame[[c for c in frame if c not in SAMPLES] + SAMPLES[::-1]]
            for kind, frame in (("protein", protein), ("phospho", phospho))}, meta


def response_frame(response):
    assert response.status_code == 200, response.text
    return pd.read_csv(io.StringIO(response.text))


def post(client, path, **kwargs):
    response = client.post(path, **kwargs)
    assert response.status_code == 200, f"{path}: {response.text}"
    return response


def stats(client, kind, source, test, control=False):
    payload = dict(kind=kind, condition1="A", condition2="B", testType=test,
                   dataSource="imputed" if source == "fixed" else "data")
    if control:
        payload.update(condition1Control="C", condition2Control="D")
    response = post(client, "/api/stats/volcano-control/run" if control else "/api/stats/volcano/run", json=payload)
    return pd.DataFrame(response.json()["rows"])


@pytest.fixture(scope="module", params=METHODS)
def workflow(request, tmp_path_factory, require_r):
    require_r()
    runtime = detect_r_runtime()
    directory = tmp_path_factory.mktemp(f"three_pipeline_{request.param}")
    frames, meta = fixture_frames()
    meta.to_csv(directory / "meta.csv", index=False)
    python, api = {}, {}
    for kind, raw in frames.items():
        raw.to_csv(directory / f"{kind}.csv", index=False)
        # The app's order since 2026-10-20: the filter decides the rows, the
        # normalization is fitted on them and applied to every row.
        logged = nb.log2_transform_data(raw, meta)
        kept = nb.filter_data(logged, meta, 3)
        normalized = nb.normalize_data(logged, meta, request.param, fit_rows=kept.index)
        filtered = normalized.loc[kept.index]
        assert filtered[IDS[kind]].tolist() == raw[IDS[kind]].iloc[:10].tolist(), "Fixture's two rejected rows must stay excluded"
        python[f"{kind}_normalized"] = normalized
        python[f"{kind}_filtered"] = filtered
        python[f"{kind}_empty"] = nb.filter_data(normalized, meta, 5)
        fixed = filtered.copy()
        # A common supplied input, not a replacement imputation algorithm.
        fixed[SAMPLES] = fixed[SAMPLES].fillna(8.25)
        fixed.to_csv(directory / f"{kind}_fixed.csv", index=False)
        for source, frame in (("observed", filtered), ("fixed", fixed)):
            for test in TESTS:
                for control in (False, True):
                    fn = nb.volcano_data_f_control if control else nb.volcano_data_f
                    args = ("A", "B", "C", "D") if control else ("A", "B")
                    python[f"{kind}_{source}_{test}" + ("_control" if control else "")] = fn(
                        frame, meta, *args, workflow="Protein" if kind == "protein" else "Phosphosite", test_type=test)
            if kind == "phospho":
                for mode in MODES:
                    collapsed = nb.transform_phosprot(frame, meta, mode=mode, data_scale="log2", coverage_data=filtered)
                    retained = nb.filter_data(collapsed, meta, 3)
                    python[f"aggregate_{source}_{mode}"] = collapsed
                    python[f"aggregate_filtered_{source}_{mode}"] = retained
                    python[f"aggregate_stats_{source}_{mode}"] = nb.volcano_data_f(
                        retained, meta, "A", "B", workflow="Phosphoprotein", test_type="unpaired_welch")
    completed = subprocess.run([str(runtime["executable"]), str(ROOT / "tests/parity/r/three_pipeline_workflow.R"),
                                str(directory), request.param, str(ROOT)], capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    r = {name: (directory / f"r_{name}.error.txt").read_text() if (directory / f"r_{name}.error.txt").exists()
         else pd.read_csv(directory / f"r_{name}.csv") for name, _, _ in STAGES}
    annotation_store.reset_all_annotations()
    dataset_store.reset_all_datasets()
    metadata_upload_store.reset_all_uploaded_metadata()
    try:
        # Desktop-local caller: restore references the synthetic files uploaded
        # above. Remote callers correctly cannot access server-local paths.
        with TestClient(app, client=("127.0.0.1", 50000)) as client:
            for kind, raw in frames.items():
                post(client, "/api/datasets/upload", data={"kind": kind},
                     files={"file": (f"{kind}.csv", raw.to_csv(index=False).encode(), "text/csv")})
                post(client, "/api/annotations/metadata/upload", data={"kind": kind},
                     files={"file": ("metadata.csv", meta.to_csv(index=False).encode(), "text/csv")})
                settings = dict(kind=kind, isLog2Transformed=False, filter=dict(minPresent=3, mode="per_group", normalization=request.param))
                post(client, "/api/annotations/generate", json=settings)
                api[f"{kind}_normalized"] = annotation_store.get_annotation(kind).log2_data.copy()
                api[f"{kind}_filtered"] = response_frame(client.get(f"/api/annotations/current/{kind}/filtered/download"))
                # The UI restore API accepts the shared pre-imputed matrix. All
                # mutations go through API routes; no direct store injection.
                exported = post(client, "/api/restore/export", json={"uiState": {}})
                state = json.loads(gzip.decompress(exported.content))
                fixed = pd.read_csv(directory / f"{kind}_fixed.csv")
                for package in state["backend"]["packages"]:
                    for annotation in package["annotations"]:
                        if annotation["kind"] == kind:
                            annotation["imputedFrame"] = {"columns": fixed.columns.tolist(), "data": fixed.values.tolist()}
                            annotation["imputation"] = {"mode": "quantile", "applied": True, "seed": 1337}
                restored = post(client, "/api/restore/import", files={"stateFile": (
                    "fixture.copylotstate", gzip.compress(json.dumps(state).encode()), "application/octet-stream")})
                assert restored.json()["ok"], restored.text
                for source in ("observed", "fixed"):
                    for test in TESTS:
                        for control in (False, True):
                            api[f"{kind}_{source}_{test}" + ("_control" if control else "")] = stats(client, kind, source, test, control)
                    if kind == "phospho":
                        for mode in MODES:
                            post(client, "/api/annotations/phosprot/aggregate", json={"mode": mode, "source": "imputed" if source == "fixed" else "non_imputed"})
                            api[f"aggregate_{source}_{mode}"] = response_frame(client.get("/api/annotations/current/phosprot/source/download"))
                            api[f"aggregate_filtered_{source}_{mode}"] = response_frame(client.get("/api/annotations/current/phosprot/filtered/download"))
                            api[f"aggregate_stats_{source}_{mode}"] = stats(client, "phosprot", "observed", "unpaired_welch")
                settings["filter"]["minPresent"] = 5
                post(client, "/api/annotations/generate", json=settings)
                api[f"{kind}_empty"] = annotation_store.get_annotation(kind).filtered_data.copy()
                # Asking for the filtered matrix is refused; asking for the
                # unfiltered one is a different request and is answered, labelled.
                rejected = client.post("/api/stats/volcano/run", json={
                    "kind": kind, "condition1": "A", "condition2": "B", "dataSource": "filtered"})
                assert rejected.status_code == 400 and "No features passed" in rejected.text
                served = client.post("/api/stats/volcano/run", json={
                    "kind": kind, "condition1": "A", "condition2": "B", "dataSource": "data"})
                assert served.status_code == 200 and served.json()["sourceUsed"] == "data"
        yield python, r, api
    finally:
        annotation_store.reset_all_annotations()
        dataset_store.reset_all_datasets()
        metadata_upload_store.reset_all_uploaded_metadata()


@pytest.mark.parametrize("stage,key,category", STAGES)
@pytest.mark.parametrize("peer", ("R", "API"))
def test_three_pipeline_stage(workflow, stage, key, category, peer):
    python, r, api = workflow
    columns = list(SAMPLES) if category in ("matrix", "aggregate") else ["log2FC", "pval", "adj_pval"]
    if category == "aggregate":
        columns += [c for c in python[stage] if c.startswith("site_")]
    for name, outputs in ((peer, r if peer == "R" else api),):
        assert isinstance(outputs[stage], pd.DataFrame), f"{stage}: {name} failed: {outputs[stage]}"
        expected = python[stage].set_index(key).sort_index()
        actual = outputs[stage].set_index(key).sort_index()
        assert actual.index.tolist() == expected.index.tolist(), f"{stage}: {name} feature inclusion"
        np.testing.assert_allclose(actual[columns].to_numpy(float), expected[columns].to_numpy(float),
                                   rtol=1e-8, atol=1e-10, equal_nan=True, err_msg=f"{stage}: {name}")
        if category == "stats":
            # Compare selected identities independently of display-label wording.
            for direction in (1, -1):
                selected = lambda df: df.index[(df.adj_pval < .05) & (direction * df.log2FC > 1)].tolist()
                assert selected(actual) == selected(expected), f"{stage}: {name} significant selection"
