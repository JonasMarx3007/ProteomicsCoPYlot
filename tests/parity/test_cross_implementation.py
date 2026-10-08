from __future__ import annotations

import importlib.util
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
R_SCRIPT = ROOT / "tests" / "parity" / "r" / "cross_implementation.R"

CONDITIONS = ("Ctrl", "Treat", "Third", "Fourth")


@pytest.mark.parametrize("family", ["mixed", "undefined"])
def test_notebook_degenerate_families_match_backend_and_r(tmp_path, family, monkeypatch, require_r):
    from app.schemas.stats import SimulationRequest, AnovaRequest
    from app.services import stats_tools
    from unittest.mock import patch
    notebook = _notebook()
    samples = [f"{c}{i}" for c in "AB" for i in range(3)]
    meta = pd.DataFrame({"sample": samples, "condition": list("AAABBB")})
    values = np.array([
        [1, 2, 3, 5, 6, 7], [5, 5, 5, 5, 5, 5], [1, 1, 1, 5, 5, 5],
        [0, 1, np.nan, 2, 3, np.nan], [1, np.nan, np.nan, 2, 3, 4],
        [np.nan, np.nan, np.nan, 2, 3, 4],
    ], dtype=float)
    data = pd.DataFrame(values, columns=samples)
    data.insert(0, "ProteinNames", ["P1;P2", "equal", "unequal", "zero", "sparse", "missing_A"])
    if family == "undefined":
        data = data.iloc[[1]].copy()
    before = data.copy(deep=True)
    captured = []
    scatter = notebook.px.scatter
    def capture(frame, **kwargs):
        captured.append(frame.copy())
        return scatter(frame, **kwargs)
    monkeypatch.setattr(notebook.px, "scatter", capture)
    fig = notebook.volcano_plot_sim(data, meta, "A", "B")
    actual = captured[0].set_index("Feature")
    with patch.object(stats_tools, "_stats_source", return_value=("filtered", data, meta, [])):
        expected = stats_tools._simulation_dataframe(SimulationRequest(
            kind="protein", condition1="A", condition2="B"))[2].set_index("ProteinNames")
        backend_anova = stats_tools._anova_dataframe(AnovaRequest(kind="protein"))[2]
    assert actual.index.tolist() == expected.index.tolist()
    np.testing.assert_allclose(actual[["pval", "adj_pval", "log2FC"]], expected[["pval", "adj_pval", "log2FC"]], equal_nan=True)
    assert actual.loc["equal", "significance"] == "Unavailable"
    assert np.isnan(actual.loc["equal", "adj_pval"])
    for trace in fig.data:
        assert not np.isinf(np.asarray(trace.y, dtype=float)).any()
    for shape in fig.layout.shapes:
        assert np.isfinite([shape.x0, shape.x1, shape.y0, shape.y1]).all()
    anova = notebook.anova_data_f(data, meta)
    assert set(anova.ProteinNames) == set(backend_anova.ProteinNames)
    if family == "mixed":
        # log2FC is condition1 - condition2, so B being the higher condition
        # makes this feature downregulated.
        assert actual.loc["P1;P2", "significance"] == "Downregulated"
        # Constant in both groups (1,1,1 vs 5,5,5): no variation, so no p-value
        # at any projected n -- the volcano's rule, in all three implementations.
        assert actual.loc["unequal", "significance"] == "Unavailable"
        assert np.isnan(actual.loc["unequal", "pval"]) and np.isnan(actual.loc["unequal", "adj_pval"])
        assert expected.loc["unequal", "significance"] == "Unavailable"
    else:
        assert anova.empty
    pd.testing.assert_frame_equal(data, before)
    require_r()
    data.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    script = '''
      args <- commandArgs(trailingOnly=TRUE)
      source("proteomicscopylot/notebook_functions.R")
      d <- read.csv(file.path(args[1], "data.csv"), check.names=FALSE)
      m <- read.csv(file.path(args[1], "meta.csv"), check.names=FALSE)
      volcano_plot <- function(volcano_df, ...) volcano_df
      result <- volcano_plot_sim(d,m,"A","B")
      write.csv(result,file.path(args[1],"simulation.csv"),row.names=FALSE)
      write.csv(anova_data_f(d,m),file.path(args[1],"anova.csv"),row.names=FALSE)
    '''
    run = subprocess.run([RSCRIPT, "-e", script, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    r = pd.read_csv(tmp_path / "simulation.csv").set_index("ProteinNames")
    np.testing.assert_allclose(actual[["pval", "adj_pval", "log2FC"]], r.loc[actual.index, ["pval", "adj_pval", "log2FC"]], equal_nan=True)
    assert set(pd.read_csv(tmp_path / "anova.csv").ProteinNames) == set(anova.ProteinNames)
    sparse = data.copy()
    sparse[samples[1:3]] = np.nan
    with pytest.raises(ValueError, match="enough replicate"):
        notebook.volcano_plot_sim(sparse, meta, "A", "B")
    with patch.object(stats_tools, "_stats_source", return_value=("filtered", sparse, meta, [])):
        with pytest.raises(ValueError, match="enough replicate"):
            stats_tools._simulation_dataframe(SimulationRequest(kind="protein", condition1="A", condition2="B"))
    sparse.to_csv(tmp_path / "data.csv", index=False)
    script = '''
      args <- commandArgs(trailingOnly=TRUE)
      source("proteomicscopylot/notebook_functions.R")
      d <- read.csv(file.path(args[1],"data.csv"))
      m <- read.csv(file.path(args[1],"meta.csv"))
      error <- tryCatch({volcano_plot_sim(d,m,"A","B"); ""}, error=conditionMessage)
      stopifnot(grepl("enough replicate",error))
    '''
    run = subprocess.run([RSCRIPT, "-e", script, str(tmp_path)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
REPLICATES = 4
TOLERANCE = 1e-9
TEST_TYPES = (
    "unpaired",
    "unpaired_welch",
    "paired",
)


from _r_runtime import RSCRIPT
requires_r = pytest.mark.requires_r()


def _notebook():
    spec = importlib.util.spec_from_file_location(
        "_nb_cross", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nb_cross"] = module
    spec.loader.exec_module(module)
    return module


def _fixture(directory: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(20260729)
    samples = [f"{c}_{i}_20240131" for c in CONDITIONS for i in range(1, REPLICATES + 1)]
    values = rng.normal(20.0, 2.5, size=(400, 1)) + rng.normal(0.0, 0.6, (400, len(samples)))

    treat = [i for i, s in enumerate(samples) if s.startswith("Treat")]
    values[:40, treat] += 1.5

    frame = pd.DataFrame(values, columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i:04d}_HUMAN" for i in range(400)])
    frame.insert(1, "GeneNames", [f"GENE{i:04d}" for i in range(400)])

    missing = rng.random((400, len(samples))) < 0.12
    missing[300:340, treat] = True
    for index, sample in enumerate(samples):
        frame.loc[missing[:, index], sample] = np.nan

    frame.loc[350:359, samples[0]] = 0.0
    frame.loc[399, samples] = 18.0

    meta = pd.DataFrame(
        {
            "sample": samples,
            "condition": [s.split("_")[0] for s in samples],
            "pair_id": [str(index) for _ in CONDITIONS for index in range(1, REPLICATES + 1)],
        }
    )
    frame.to_csv(directory / "data.csv", index=False)
    meta.to_csv(directory / "meta.csv", index=False)
    return frame, meta


def _phospho_fixture(directory: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    samples = ["ps1", "ps2", "ps3", "ps4"]
    frame = pd.DataFrame(
        {
            "UPD_seq": ["A", "B", "C", "D", "E", "F"],
            "PTM_localization": ["S1", "S2", "S3", "S4", "T1", "T2"],
            "Protein_group": ["P1", "P1", "P1", "P1", "P2", "P2"],
            "Gene_group": ["G1", "G1", "G1", "G1", "G2", "G2"],
            "PTM_Collapse_key": ["P1_S1", "P1_S2", "P1_S3", "P1_S4", "P2_T1", "P2_T2"],
            "ps1": [0.0, 10.0, 20.0, np.nan, -1.0, 5.0],
            "ps2": [1.0, 11.0, np.nan, np.nan, 0.0, 6.0],
            "ps3": [2.0, 12.0, 22.0, np.nan, 1.0, np.nan],
            "ps4": [3.0, 13.0, np.nan, np.nan, 2.0, 8.0],
        }
    )
    meta = pd.DataFrame(
        {"sample": samples, "condition": ["control", "control", "treated", "treated"]}
    )
    frame.to_csv(directory / "phospho.csv", index=False)
    meta.to_csv(directory / "phospho_meta.csv", index=False)
    return frame, meta


def _run_r(directory: Path) -> None:
    completed = subprocess.run(
        [RSCRIPT, str(R_SCRIPT), str(directory)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if completed.returncode != 0:
        detail = [
            line.strip()
            for line in (completed.stderr or completed.stdout or "").splitlines()
            if line.strip()
        ]
        pytest.fail(
            "The R notebook package failed on a fixture the Python package handles. "
            "That is itself a divergence, not an environment problem: "
            + " | ".join(detail[-4:])
        )


@pytest.fixture(scope="module")
def results(tmp_path_factory, require_r) -> dict[str, pd.DataFrame]:
    require_r()
    directory = tmp_path_factory.mktemp("cross_impl")
    frame, meta = _fixture(directory)
    phospho, phospho_meta = _phospho_fixture(directory)
    notebook = _notebook()

    zero_meta = pd.DataFrame({"sample": ["z1", "z2"], "condition": ["A", "A"]})
    raw_zero_fixture = pd.DataFrame(
        {"label": [0, 1, 2], "z1": [0.0, 1.0, 2.0], "z2": [1.0, 2.0, 4.0]}
    )
    transformed = notebook.log2_transform_data(raw_zero_fixture, zero_meta)
    imputation_fixture = pd.DataFrame(
        {"label": [0, 1, 2], "z1": [0.0, np.nan, 2.0], "z2": [1.0, 2.0, 3.0]}
    )
    imputed = notebook.impute_values(imputation_fixture, zero_meta, seed=7)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        volcano = notebook.volcano_data_f(
            frame, meta, "Ctrl", "Treat", workflow="Protein"
        )[["ProteinNames", "log2FC", "pval", "adj_pval"]]

    samples = [str(s) for s in meta["sample"]]
    normalized = {
        f"normalize_{method}": notebook.normalize_data(frame, samples, method)[
            ["ProteinNames", *samples]
        ]
        for method in ("median", "quantile")
    }
    volcano_variants = {
        f"volcano_{test_type}": notebook.volcano_data_f(
            frame, meta, "Ctrl", "Treat", workflow="Protein", test_type=test_type
        )[["ProteinNames", "log2FC", "pval", "adj_pval"]]
        for test_type in ("unpaired_welch",)
    }
    control_volcano = notebook.volcano_data_f_control(
        frame, meta, "Ctrl", "Treat", "Third", "Fourth",
        workflow="Protein", uncorrected=True, in_log2fc=0.0,
    )[["ProteinNames", "log2FC", "pval", "adj_pval"]]
    control_variants = {
        f"volcano_control_{test_type}": notebook.volcano_data_f_control(
            frame, meta, "Ctrl", "Treat", "Third", "Fourth",
            workflow="Protein", uncorrected=True, in_log2fc=0.0,
            test_type=test_type,
        )[["ProteinNames", "log2FC", "pval", "adj_pval"]]
        for test_type in TEST_TYPES
    }
    ksea_input = frame.copy()
    ksea_input["UPD_seq"] = ksea_input["ProteinNames"]
    ksea_variants = {}
    for test_type in TEST_TYPES:
        try:
            ksea_variants[f"ksea_{test_type}"] = notebook.ksea_data_f(
                ksea_input, meta, "Ctrl", "Treat", test_type=test_type
            )[["UPD_seq", "log2FC", "pval", "adj_pval"]]
        except Exception as exc:
            raise AssertionError(f"public Python KSEA failed for {test_type}") from exc
    posthoc = notebook.anova_posthoc_data(
        notebook.anova_data_f(
            frame, meta, conditions=list(CONDITIONS), workflow="Protein"
        ),
        meta,
    )[["ProteinNames", "comparison", "log2FC", "q_statistic", "tukey_pval"]]

    python_results = {
        **normalized,
        **volcano_variants,
        **control_variants,
        **ksea_variants,
        "anova_posthoc": posthoc,
        "volcano_control": control_volcano,
        "filter": notebook.filter_data(frame, meta, 3, "per group", "at_least_n", 70)[["ProteinNames"]],
        "volcano": volcano,
        "anova": notebook.anova_data_f(
            frame, meta, conditions=list(CONDITIONS), workflow="Protein"
        )[["ProteinNames", "f_statistic", "pval", "adj_pval"]].sort_values("ProteinNames"),
        "anova_order": notebook.anova_data_f(
            frame, meta, conditions=list(CONDITIONS), workflow="Protein"
        )[["ProteinNames", "pval", "adj_pval"]],
        "zero_contract": pd.DataFrame(
            {
                "raw_zero_missing": [int(pd.isna(transformed.loc[0, "z1"]))],
                "raw_one_becomes_log2_zero": [int(transformed.loc[1, "z1"] == 0.0)],
                "transformed_zero_preserved_by_imputation": [int(imputed.loc[0, "z1"] == 0.0)],
                "actual_missing_value_imputed": [int(pd.notna(imputed.loc[1, "z1"]))],
                "annotation_zero_preserved": [int(imputed.loc[0, "label"] == 0)],
            }
        ),
    }
    go_db = notebook.load_go_db()
    term_sizes = go_db["genes"].astype(str).str.count(";") + 1
    source_term = go_db[(term_sizes >= 30) & (term_sizes <= 80)].iloc[0]
    enrich_query = [g.strip() for g in str(source_term["genes"]).split(";") if g.strip()][:30]
    universe = sorted({g.strip() for t in go_db["genes"] for g in str(t).split(";") if g.strip()})
    rng = np.random.default_rng(0)
    others = [g for g in universe if g not in set(enrich_query)]
    enrich_background = sorted(
        set(enrich_query) | set(rng.choice(others, 4000, replace=False).tolist())
    )
    pd.DataFrame({"gene": enrich_query}).to_csv(directory / "enrichment_query.csv", index=False)
    pd.DataFrame({"gene": enrich_background}).to_csv(
        directory / "enrichment_background.csv", index=False
    )
    python_results["enrichment"] = notebook.enrichment_data(
        enrich_query,
        top_n=10,
        min_num=5,
        max_num=500,
        background=enrich_background,
        background_mode="experiment",
        adj_p_value_cutoff=1.0,
    )

    for mode in ("robust_site_median", "sum_propagate_na", "sum_ignore_na", "mean"):
        python_results[f"phosprot_{mode}"] = notebook.transform_phosprot(
            phospho,
            phospho_meta,
            mode=mode,
            data_scale="log2",
        ).sort_values("Phosphoprotein").reset_index(drop=True)
    reg_rng = np.random.default_rng(4)
    reg_samples = [f"{c}{i}" for c in ("A", "B") for i in (1, 2, 3)]
    reg_meta = pd.DataFrame(
        {"sample": reg_samples, "condition": [s[0] for s in reg_samples]}
    )
    reg_rows = []
    for protein in range(40):
        baseline = reg_rng.normal(20, 1.5)
        shift = 2.0 if protein < 10 else (-2.0 if protein < 20 else 0.0)
        for site in range(4):
            values = {
                sample: baseline + reg_rng.normal(0, 0.25) + (shift if sample.startswith("B") else 0.0)
                for sample in reg_samples
            }
            reg_rows.append(
                {
                    "Protein_group": f"P{protein}",
                    "Gene_group": f"G{protein}",
                    "PTM_Collapse_key": f"P{protein}_S{site}",
                    "PTM_localization": "1",
                    "UPD_seq": f"SEQ{protein}{site}",
                    **values,
                }
            )
    reg_frame = pd.DataFrame(reg_rows)
    reg_frame.to_csv(directory / "phosreg.csv", index=False)
    reg_meta.to_csv(directory / "phosreg_meta.csv", index=False)
    python_results["phosprot_regulation"] = (
        notebook.phosprot_regulation_data(
            reg_frame, reg_meta, "A", "B", in_pval=0.05, in_log2fc=1.0
        )
        .sort_values("Protein_group")
        .reset_index(drop=True)
    )

    _run_r(directory)
    r_results = {
        name: pd.read_csv(directory / f"r_{name}.csv") for name in python_results
    }
    return {"python": python_results, "r": r_results}


@requires_r
def test_filtering_agrees(results) -> None:
    # The same features, in the same order -- not only the same number of them.
    python_kept = results["python"]["filter"]["ProteinNames"].astype(str).tolist()
    r_kept = results["r"]["filter"]["ProteinNames"].astype(str).tolist()
    assert python_kept == r_kept
    assert python_kept, "fixture should survive filtering"


@requires_r
@pytest.mark.parametrize("table,columns", [
    ("volcano", ["log2FC", "pval", "adj_pval"]),
    ("anova", ["f_statistic", "pval", "adj_pval"]),
])
def test_statistics_agree(results, table: str, columns: list[str]) -> None:
    python_table = results["python"][table].reset_index(drop=True)
    r_table = results["r"][table].reset_index(drop=True)

    assert len(python_table) == len(r_table), (
        f"{table}: Python returned {len(python_table)} features, R returned {len(r_table)}. "
        "The two packages disagree about which features are testable."
    )
    merged = python_table.merge(r_table, on="ProteinNames", suffixes=("_py", "_r"))
    assert len(merged) == len(python_table), f"{table}: feature identities differ"

    for column in columns:
        left = merged[f"{column}_py"].to_numpy(dtype=float)
        right = merged[f"{column}_r"].to_numpy(dtype=float)
        assert np.array_equal(np.isfinite(left), np.isfinite(right)), (
            f"{table}.{column}: the two packages disagree about which values are defined"
        )
        both = np.isfinite(left) & np.isfinite(right)
        if not both.any():
            continue
        worst = float(np.max(np.abs(left[both] - right[both])))
        assert worst < TOLERANCE, (
            f"{table}.{column}: max|difference| = {worst:.3e} between the Python and R "
            f"packages (tolerance {TOLERANCE:.0e}). Both ship to users; they must agree."
        )


@requires_r
def test_python_and_r_enforce_the_same_scale_aware_zero_contract(results) -> None:
    expected = pd.DataFrame(
        {
            "raw_zero_missing": [1],
            "raw_one_becomes_log2_zero": [1],
            "transformed_zero_preserved_by_imputation": [1],
            "actual_missing_value_imputed": [1],
            "annotation_zero_preserved": [1],
        }
    )
    pd.testing.assert_frame_equal(
        results["python"]["zero_contract"].astype(int), expected
    )
    pd.testing.assert_frame_equal(
        results["r"]["zero_contract"].astype(int), expected
    )


@requires_r
@pytest.mark.parametrize(
    "mode", ["robust_site_median", "sum_propagate_na", "sum_ignore_na", "mean"]
)
def test_phosphoprotein_aggregation_agrees(results, mode: str) -> None:
    name = f"phosprot_{mode}"
    python_table = results["python"][name]
    r_table = results["r"][name]
    assert list(python_table["Phosphoprotein"]) == list(r_table["Phosphoprotein"])

    numeric_columns = [
        column
        for column in python_table.columns
        if column.startswith("site_") or column.startswith("ps")
    ]
    assert numeric_columns
    for column in numeric_columns:
        left = pd.to_numeric(python_table[column], errors="coerce").to_numpy(dtype=float)
        right = pd.to_numeric(r_table[column], errors="coerce").to_numpy(dtype=float)
        assert np.array_equal(np.isfinite(left), np.isfinite(right)), (
            f"{name}.{column}: Python and R disagree about missing values"
        )
        both = np.isfinite(left) & np.isfinite(right)
        if both.any():
            assert np.max(np.abs(left[both] - right[both])) < TOLERANCE


@requires_r
def test_the_fixture_still_contains_its_hazards(tmp_path) -> None:
    frame, _ = _fixture(tmp_path)
    samples = [c for c in frame.columns if c not in ("ProteinNames", "GeneNames")]
    numeric = frame[samples]
    assert (numeric == 0).to_numpy().sum() > 0, "fixture must retain exact zeros"
    constant_rows = numeric.nunique(axis=1, dropna=True) == 1
    assert constant_rows.sum() > 0, "fixture must retain a constant-value row"


def test_seeded_fixture_is_reproducible(tmp_path) -> None:
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first, _ = _fixture(first_dir)
    second, _ = _fixture(second_dir)
    pd.testing.assert_frame_equal(first, second)


@requires_r
@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalization_agrees(results, method: str) -> None:
    python_result = results["python"][f"normalize_{method}"]
    r_result = results["r"][f"normalize_{method}"]
    merged = python_result.merge(r_result, on="ProteinNames", suffixes=("_py", "_r"))
    assert len(merged) == len(python_result)
    for column in python_result.columns:
        if column == "ProteinNames":
            continue
        left = merged[f"{column}_py"].to_numpy(dtype=float)
        right = merged[f"{column}_r"].to_numpy(dtype=float)
        both = np.isfinite(left) & np.isfinite(right)
        assert np.array_equal(np.isnan(left), np.isnan(right)), (
            f"{method}: missing-value pattern differs in {column}"
        )
        assert np.abs(left[both] - right[both]).max() < TOLERANCE


@requires_r
@pytest.mark.parametrize("test_type", ["unpaired_welch"])
def test_volcano_variance_models_agree(results, test_type: str) -> None:
    python_result = results["python"][f"volcano_{test_type}"]
    r_result = results["r"][f"volcano_{test_type}"]
    merged = python_result.merge(r_result, on="ProteinNames", suffixes=("_py", "_r"))
    assert len(merged) == len(python_result) == len(r_result)
    for column in ("log2FC", "pval", "adj_pval"):
        np.testing.assert_allclose(
            merged[f"{column}_py"].to_numpy(dtype=float),
            merged[f"{column}_r"].to_numpy(dtype=float),
            rtol=0, atol=TOLERANCE, equal_nan=True, err_msg=f"{test_type}: {column}",
        )


@requires_r
def test_anova_posthoc_agrees(results) -> None:
    python_result = results["python"]["anova_posthoc"]
    r_result = results["r"]["anova_posthoc"]
    assert not python_result.empty and not r_result.empty, "The fixture must exercise post-hoc comparisons"
    key = ["ProteinNames", "comparison"]
    merged = python_result.merge(r_result, on=key, suffixes=("_py", "_r"))
    assert len(merged) == len(python_result) == len(r_result), "post-hoc row sets differ"

    for column in ("log2FC", "q_statistic"):
        difference = np.abs(
            merged[f"{column}_py"].to_numpy(dtype=float)
            - merged[f"{column}_r"].to_numpy(dtype=float)
        ).max()
        assert difference < TOLERANCE, f"post-hoc {column} differs by {difference:.2e}"

    p_difference = np.abs(
        merged["tukey_pval_py"].to_numpy(dtype=float)
        - merged["tukey_pval_r"].to_numpy(dtype=float)
    ).max()
    assert p_difference < 1e-6, f"post-hoc tukey_pval differs by {p_difference:.2e}"


@requires_r
def test_control_volcano_agrees(results) -> None:
    python_result = results["python"]["volcano_control"]
    r_result = results["r"]["volcano_control"]
    merged = python_result.merge(r_result, on="ProteinNames", suffixes=("_py", "_r"))
    assert len(merged) == len(python_result) == len(r_result)
    for column in ("log2FC", "pval", "adj_pval"):
        np.testing.assert_allclose(
            merged[f"{column}_py"].to_numpy(dtype=float),
            merged[f"{column}_r"].to_numpy(dtype=float),
            rtol=0, atol=TOLERANCE, equal_nan=True, err_msg=f"control volcano {column}",
        )


@requires_r
@pytest.mark.parametrize("test_type", TEST_TYPES)
@pytest.mark.parametrize(
    "pipeline,key_column", [("volcano_control", "ProteinNames"), ("ksea", "UPD_seq")]
)
def test_pipeline_variance_models_agree(
    results, test_type: str, pipeline: str, key_column: str
) -> None:
    name = f"{pipeline}_{test_type}"
    python_result = results["python"][name]
    r_result = results["r"][name]
    merged = python_result.merge(r_result, on=key_column, suffixes=("_py", "_r"))
    assert len(merged) == len(python_result) == len(r_result)
    for column in ("log2FC", "pval", "adj_pval"):
        np.testing.assert_allclose(
            merged[f"{column}_py"].to_numpy(dtype=float),
            merged[f"{column}_r"].to_numpy(dtype=float),
            rtol=0, atol=TOLERANCE, equal_nan=True, err_msg=f"{name}: {column}",
        )


def test_control_volcano_propagates_the_control_uncertainty() -> None:
    notebook = _notebook()
    rng = np.random.default_rng(31)
    n, reps = 1500, 4
    conditions = ("A", "Actrl", "B", "Bctrl")
    columns = [f"{c}_{i}" for c in conditions for i in range(reps)]
    meta = pd.DataFrame(
        {"sample": columns, "condition": [c.split("_")[0] for c in columns]}
    )
    base = rng.normal(22, 2, n)
    frame = pd.DataFrame({c: base + rng.normal(0, 0.5, n) for c in columns})
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])

    result = notebook.volcano_data_f_control(
        frame, meta, "A", "B", "Actrl", "Bctrl",
        workflow="Protein", uncorrected=True, in_log2fc=0.0,
    )
    rate = float((result["pval"] < 0.05).mean())
    assert rate < 0.08, (
        f"false-positive rate on a complete null is {rate:.1%}; the control means' "
        f"uncertainty is not being propagated"
    )


@pytest.mark.parametrize("mode", ["per group", "per_group", "in_at_least_one_group", "overall"])
def test_valid_filter_modes_are_still_accepted(mode: str) -> None:
    from proteomicscopylot import notebook_functions

    samples = ["A1", "A2", "B1", "B2"]
    metadata = pd.DataFrame({"sample": samples, "condition": ["A", "A", "B", "B"]})
    frame = pd.DataFrame(
        {
            "ProteinNames": ["complete", "one side only"],
            "A1": [1.0, 1.0],
            "A2": [1.0, 1.0],
            "B1": [1.0, np.nan],
            "B2": [1.0, np.nan],
        }
    )
    kept = notebook_functions.filter_data(frame, metadata, 2, mode=mode)
    assert "complete" in set(kept["ProteinNames"])
    expected = mode.replace("_", " ") != "per group"
    assert ("one side only" in set(kept["ProteinNames"])) is expected


@pytest.mark.parametrize("mode", ["typo", "perGroup", "per-group", "per  group", ""])
def test_an_unrecognised_filter_mode_raises_rather_than_defaulting(mode: str) -> None:
    from proteomicscopylot import notebook_functions

    samples = ["A1", "A2", "B1", "B2"]
    metadata = pd.DataFrame({"sample": samples, "condition": ["A", "A", "B", "B"]})
    frame = pd.DataFrame(
        {"ProteinNames": ["p"], "A1": [1.0], "A2": [1.0], "B1": [1.0], "B2": [1.0]}
    )
    with pytest.raises(ValueError, match="Filter mode must be"):
        notebook_functions.filter_data(frame, metadata, 2, mode=mode)


@requires_r
def test_anova_row_order_is_deterministic_across_ties(results) -> None:
    python_rows = results["python"]["anova_order"].reset_index(drop=True)
    r_rows = results["r"]["anova_order"].reset_index(drop=True)

    label = next(
        (c for c in ("ProteinNames", "GeneNames", "Phosphoprotein", "PTM_Collapse_key")
         if c in python_rows.columns),
        None,
    )
    assert label is not None, python_rows.columns.tolist()
    assert list(python_rows[label].astype(str)) == list(r_rows[label].astype(str))

    adj = python_rows["adj_pval"].to_numpy(dtype=float)
    assert all(a <= b + 1e-12 for a, b in zip(adj, adj[1:])), "not sorted by adj_pval"
    raw = python_rows["pval"].to_numpy(dtype=float)
    for i in range(len(adj) - 1):
        if abs(adj[i] - adj[i + 1]) < 1e-15:
            assert raw[i] <= raw[i + 1] + 1e-12, f"tie at {i} not broken by raw p"


_FORMAT_CASES = [
    (0, "0"),
    (1, "1"),
    (1.0, "1"),
    (-1, "-1"),
    (1.5, "1.5"),
    (-2.75, "-2.75"),
    (0.000123, "0.000123"),
    (123456.0, "123456"),
    (1e6, "1000000"),
    (1e14, "100000000000000"),
    (999999.5, "999999.5"),
]


@pytest.mark.parametrize(("value", "expected"), _FORMAT_CASES)
def test_number_to_str_has_an_explicit_contract(value, expected: str) -> None:
    from proteomicscopylot import notebook_functions

    assert notebook_functions.number_to_str(value) == expected


def test_number_to_str_handles_non_finite_and_non_numeric() -> None:
    from proteomicscopylot import notebook_functions

    assert notebook_functions.number_to_str(float("nan")) == "NaN"
    assert notebook_functions.number_to_str(float("inf")) == "Inf"
    assert notebook_functions.number_to_str(float("-inf")) == "-Inf"
    assert notebook_functions.number_to_str("text") == ""
    assert notebook_functions.number_to_str(True) == ""


@requires_r
def test_enrichment_tables_agree(results) -> None:
    python_table = results["python"]["enrichment"].reset_index(drop=True)
    r_table = results["r"]["enrichment"].reset_index(drop=True)

    assert len(python_table) == len(r_table), (
        f"pip returned {len(python_table)} terms, R returned {len(r_table)}"
    )
    assert not python_table.empty, "the fixture must produce enriched terms"

    for column in ("source", "term_id", "term_name"):
        assert list(python_table[column].astype(str)) == list(r_table[column].astype(str)), column
    for column in ("term_size", "intersection_size", "query_size", "gene_ratio", "p_value", "adj_p_value"):
        left = python_table[column].to_numpy(dtype=float)
        right = r_table[column].to_numpy(dtype=float)
        assert np.allclose(left, right, rtol=1e-10, atol=1e-12), column


@requires_r
def test_phosprot_regulation_tables_agree(results) -> None:
    python_table = results["python"]["phosprot_regulation"].reset_index(drop=True)
    r_table = results["r"]["phosprot_regulation"].reset_index(drop=True)

    assert not python_table.empty, "the fixture must produce regulated proteins"
    assert list(python_table.columns) == list(r_table.columns)
    assert list(python_table["Protein_group"]) == list(r_table["Protein_group"])

    for column in python_table.columns:
        if python_table[column].dtype.kind in "fi":
            assert np.allclose(
                python_table[column].to_numpy(dtype=float),
                r_table[column].to_numpy(dtype=float),
                rtol=1e-10,
                atol=1e-12,
            ), column
        else:
            left = python_table[column].fillna("").astype(str).tolist()
            right = r_table[column].fillna("").astype(str).tolist()
            assert left == right, column


def test_enrichment_corrects_over_tested_terms_not_eligible_ones() -> None:
    from app.services.stats_tools import _enrichment_terms

    notebook = _notebook()
    go_db = notebook.load_go_db()
    term_sizes = go_db["genes"].astype(str).str.count(";") + 1
    source_term = go_db[(term_sizes >= 30) & (term_sizes <= 80)].iloc[0]
    query = [g.strip() for g in str(source_term["genes"]).split(";") if g.strip()][:30]
    universe = sorted({g.strip() for t in go_db["genes"] for g in str(t).split(";") if g.strip()})
    rng = np.random.default_rng(0)
    others = [g for g in universe if g not in set(query)]
    background = sorted(set(query) | set(rng.choice(others, 4000, replace=False).tolist()))

    package = notebook.enrichment_data(
        query, top_n=10**6, min_num=5, max_num=500, background=background,
        background_mode="experiment", adj_p_value_cutoff=1.0,
    )

    universe_set = set(background)
    eligible = []
    for _, row in go_db.iterrows():
        genes = universe_set.intersection(
            {g.strip() for g in str(row["genes"]).split(";") if g.strip()}
        )
        if 5 <= len(genes) <= 500:
            eligible.append((str(row["ontology"]), str(row["term"]), str(row["description"]), genes))
    backend = _enrichment_terms(
        query, top_n=10**6, adj_p_value_cutoff=1.0,
        background=universe_set, eligible_terms=eligible,
    )

    backend_adj = {term.termId: term.adjPValue for term in backend}
    package_adj = {row["term_id"]: row["adj_p_value"] for _, row in package.iterrows()}
    shared = sorted(set(backend_adj) & set(package_adj))
    assert len(shared) > 100, f"the fixture must produce many shared terms, got {len(shared)}"

    left = np.array([package_adj[t] for t in shared], dtype=float)
    right = np.array([backend_adj[t] for t in shared], dtype=float)
    assert np.allclose(left, right, rtol=1e-10, atol=1e-15), (
        "the notebook package and the web app disagree on the adjusted p-values "
        f"(median ratio {np.median(left / np.maximum(right, 1e-300)):.3f}x); "
        "the Benjamini-Hochberg denominators have drifted apart"
    )


@pytest.mark.parametrize(
    ("sequences", "expected"),
    [
        (["PEPKTIDEK", "KKKK"], [1, 3]),
        (("PEPKTIDEK", "KKKK"), [1, 3]),
        ([], []),
        (["NOCLEAVAGESITE"], [0]),
    ],
)
def test_a_sequence_collection_gives_one_count_per_sequence(sequences, expected) -> None:
    notebook = _notebook()
    assert notebook.count_missed_cleavages(sequences) == expected


def test_a_single_sequence_still_returns_a_plain_integer() -> None:
    notebook = _notebook()
    result = notebook.count_missed_cleavages("PEPKTIDEK")
    assert result == 1
    assert isinstance(result, int)


def test_a_pandas_series_of_sequences_is_counted_elementwise() -> None:
    notebook = _notebook()
    counts = notebook.count_missed_cleavages(pd.Series(["PEPKTIDEK", "KKKK", "PEPTIDEK"]))
    assert list(counts) == [1, 3, 0]


@requires_r
def test_missed_cleavages_agree_across_the_packages_for_a_collection() -> None:
    import subprocess

    peptides = ["PEPKTIDEK", "KKKK", "PEPKPTIDEK", "NOCLEAVAGESITE", "MKWVTFISLLLLFSSAYSR"]
    notebook = _notebook()
    python_counts = notebook.count_missed_cleavages(peptides)

    script = (
        'suppressWarnings(suppressMessages(source("proteomicscopylot/notebook_functions.R")));'
        f'cat(count_missed_cleavages(c({", ".join(repr(p) for p in peptides)})))'
    )
    completed = subprocess.run(
        [RSCRIPT, "-e", script], capture_output=True, text=True, timeout=300, cwd=str(ROOT)
    )
    assert completed.returncode == 0, completed.stderr[-300:]
    r_counts = [int(v) for v in completed.stdout.split()]
    assert python_counts == r_counts, f"pip {python_counts} vs R {r_counts}"


@requires_r
def test_paired_constant_and_missing_edges(tmp_path) -> None:
    from app.services.functions import paired_t_test
    from scipy.stats import ttest_1samp

    # Binary-exact perturbations survive CSV round trips and trigger R t.test's
    # near-constant guard without classifying them as exactly zero variance.
    differences = np.array([
        [2., 2., 2., 2.],
        [-2., -2., -2., -2.],
        [0., 0., 0., 0.],
        [2., 2. + 2**-49, 2., 2.],
        [1., 2., 4., 3.],
        [1., np.nan, 4., 3.],
        [1., np.nan, np.nan, np.nan],
    ])
    samples = [f"{group}{i}" for group in "AB" for i in range(4)]
    data = pd.DataFrame(np.hstack([np.zeros_like(differences), differences]), columns=samples)
    data.insert(0, "ProteinNames", [f"P{i}" for i in range(len(data))])
    meta = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples],
                         "pair_id": [s[1:] for s in samples]}).iloc[[3, 1, 0, 2, 6, 4, 7, 5]]
    data.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    script = '''
      args <- commandArgs(trailingOnly=TRUE)
      source("proteomicscopylot/notebook_functions.R")
      data <- read.csv(file.path(args[1], "data.csv"), check.names=FALSE)
      meta <- read.csv(file.path(args[1], "meta.csv"), check.names=FALSE)
      result <- volcano_data_f(data, meta, "A", "B", workflow="Protein", test_type="paired")
      write.csv(result, file.path(args[1], "result.csv"), row.names=FALSE)
    '''
    completed = subprocess.run([RSCRIPT, "-e", script, str(tmp_path)], cwd=ROOT,
                               capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    actual = pd.read_csv(tmp_path / "result.csv").set_index("ProteinNames").sort_index()
    expected = _notebook().volcano_data_f(data, meta, "A", "B", test_type="paired").set_index("ProteinNames").sort_index()
    assert actual.index.tolist() == expected.index.tolist() == [f"P{i}" for i in range(6)]
    np.testing.assert_allclose(actual[["log2FC", "pval", "adj_pval", "n_pairs"]],
                               expected[["log2FC", "pval", "adj_pval", "n_pairs"]], rtol=1e-9, atol=1e-12)
    _, counts, backend_p = paired_t_test(differences[:6])
    np.testing.assert_allclose(actual.pval.iloc[4:], backend_p[4:], rtol=1e-9, atol=1e-12)
    np.testing.assert_array_equal(actual.n_pairs, counts)
    # Identical differences (also within float noise, row 3) have no variation:
    # no p-value in every implementation, where the bare t-test gives 0 or ~1e-47.
    assert np.isnan(actual.pval.iloc[:4]).all()
    assert (actual.significance.iloc[:4] == "Unavailable").all()
    assert 0 < backend_p[3] < 1e-30
    np.testing.assert_allclose(actual.pval.iloc[4:],
                               [ttest_1samp(row[np.isfinite(row)], 0).pvalue for row in differences[4:6]])
