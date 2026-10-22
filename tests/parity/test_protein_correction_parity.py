"""Protein-corrected phosphosite changes agree across the app, pip and R.

The three implementations share one definition (proteomicscopylot/_core.py,
notebook_functions.R): site minus protein log2 fold change, standard errors in
quadrature, Satterthwaite degrees of freedom, accession matching with the
unique protein group listing the accession. Every design is checked -- the
three plain tests, both control-corrected ones and, where limma is present,
the moderated tests -- plus the Kinase Library table, the phosphoprotein
regulation table and the simulated volcano at the observed n.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from _r_runtime import RSCRIPT  # noqa: E402
from app.services import r_limma  # noqa: E402
from app.services.stats_tools import _simulation_dataframe, _volcano_dataframe  # noqa: E402
from app.schemas.stats import SimulationRequest  # noqa: E402
from proteomicscopylot import notebook_functions as pkg  # noqa: E402

SAMPLES = [f"{c}{i}" for c in "ABCD" for i in (1, 2, 3)]
META = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES], "pair_id": ["p1", "p2", "p3"] * 4})
DESIGNS = [("unpaired", False), ("unpaired_welch", False), ("paired", False), ("unpaired", True), ("paired", True)]
STATS = ["log2FC", "pval", "adj_pval", "se", "dof", "site_log2FC", "site_pval", "site_se", "site_dof", "protein_log2FC", "protein_pval"]


def _fixture():
    """80 proteins (the first ten up in A, one listed as a two-member group, one
    accession shared by two groups) and 200 sites on them, a few on proteins
    that were not quantified."""
    rng = np.random.default_rng(5)
    proteins = pd.DataFrame(rng.normal(20, 1, (80, 12)), columns=SAMPLES)
    proteins.iloc[:10, :3] += 1.5
    proteins.insert(0, "ProteinNames", [f"PN{k}" for k in range(80)])
    proteins.insert(1, "ProteinAccessions", [f"P{k:05d}" + (";Q00001" if k == 3 else "") for k in range(80)])
    proteins.loc[4, "ProteinAccessions"] = "P00003"
    owner = rng.integers(0, 85, 200)
    sites = pd.DataFrame(proteins[SAMPLES].to_numpy()[np.minimum(owner, 79)] + rng.normal(0, 0.3, (200, 12)), columns=SAMPLES)
    sites.insert(0, "PTM_Collapse_key", [f"P{p:05d}_S{k}" for k, p in enumerate(owner)])
    sites.insert(1, "Protein_group", [f"P{p:05d}" for p in owner])
    sites.insert(2, "UPD_seq", ["AAAS*AAA"] * 200)
    return sites, proteins


def _app(sites, proteins, test_type, control):
    controls = dict(condition1_control="C", condition2_control="D") if control else {}
    _, _, protein, _ = _volcano_dataframe(
        kind="protein", condition1="A", condition2="B", identifier="workflow", p_value_threshold=0.05, log2fc_threshold=0,
        test_type=test_type, use_uncorrected=True, data_source="data", frame_override=proteins, metadata_override=META, **controls)
    stats = protein[["ProteinAccessions", "log2FC", "se", "dof", "pval"]].reset_index(drop=True)
    _, _, table, warnings = _volcano_dataframe(
        kind="phospho", condition1="A", condition2="B", identifier="workflow", p_value_threshold=0.05, log2fc_threshold=1,
        test_type=test_type, use_uncorrected=False, data_source="data", frame_override=sites, metadata_override=META,
        protein_correction=True, protein_stats=stats, **controls)
    return table.set_index("PTM_Collapse_key"), warnings


def _pip(sites, proteins, test_type, control):
    if control:
        table = pkg.volcano_data_f_control(sites, META, "A", "B", "C", "D", workflow="Phosphosite", test_type=test_type,
                                           protein_data=proteins, protein_meta=META)
    else:
        table = pkg.volcano_data_f(sites, META, "A", "B", workflow="Phosphosite", test_type=test_type,
                                   protein_data=proteins, protein_meta=META)
    return table.set_index("PTM_Collapse_key")


def _same(left: pd.DataFrame, right: pd.DataFrame, columns=STATS) -> None:
    assert set(left.index) == set(right.index)
    right = right.loc[left.index]
    for column in columns:
        assert np.allclose(left[column].astype(float), right[column].astype(float), equal_nan=True, rtol=1e-9), column
    for column in ("protein_matched", "protein_ambiguous"):
        assert (left[column].astype(bool).to_numpy() == right[column].astype(bool).to_numpy()).all(), column
    assert (left["significance"].astype(str) == right["significance"].astype(str)).all()


@pytest.mark.parametrize("test_type,control", DESIGNS)
def test_app_and_pip_agree(test_type, control) -> None:
    sites, proteins = _fixture()
    app, warnings = _app(sites, proteins, test_type, control)
    _same(app, _pip(sites, proteins, test_type, control))
    # Exported uncertainty must reproduce the p-value of the corrected estimate.
    from scipy.stats import t
    expected = 2 * t.sf(np.abs(app["log2FC"] / app["se"]), app["dof"])
    np.testing.assert_allclose(app["pval"], expected, rtol=1e-12)
    assert int(app["protein_matched"].sum()) == 185 and int(app["protein_ambiguous"].sum()) == 3
    ambiguous = app["protein_ambiguous"]
    assert not app.loc[ambiguous, "protein_matched"].any()
    assert app.loc[ambiguous, "protein_log2FC"].isna().all()
    np.testing.assert_array_equal(app.loc[ambiguous, "log2FC"], app.loc[ambiguous, "site_log2FC"])
    np.testing.assert_array_equal(app.loc[ambiguous, "pval"], app.loc[ambiguous, "site_pval"])
    assert any("3 sites match more than one protein group and keep their uncorrected" in w for w in warnings)
    assert any(w.startswith("Protein correction: 12 of 200 sites have no quantified protein") for w in warnings)
    # The point of the correction: sites on proteins that changed are no longer called.
    on_changed = app["protein_matched"] & (app["protein_log2FC"].abs() > 1)
    assert (app.loc[on_changed, "site_log2FC"].abs() > 1).sum() > 30
    assert (app.loc[on_changed, "log2FC"].abs() > 1).sum() < 5


def _run_r(tmp_path: Path, sites, proteins, script: str) -> None:
    sites.to_csv(tmp_path / "site.csv", index=False)
    proteins.to_csv(tmp_path / "prot.csv", index=False)
    META.to_csv(tmp_path / "meta.csv", index=False)
    preamble = f'''
      source("proteomicscopylot/notebook_functions.R")
      d <- "{tmp_path.as_posix()}"
      site <- read.csv(file.path(d, "site.csv"), check.names = FALSE)
      prot <- read.csv(file.path(d, "prot.csv"), check.names = FALSE)
      meta <- read.csv(file.path(d, "meta.csv"), check.names = FALSE)
    '''
    run = subprocess.run([RSCRIPT, "-e", preamble + script], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr


@pytest.mark.requires_r()
def test_ambiguous_correction_is_independent_of_protein_row_order(tmp_path) -> None:
    sites, proteins = _fixture()
    app, _ = _app(sites, proteins, "unpaired", False)
    reversed_app, _ = _app(sites, proteins.iloc[::-1], "unpaired", False)
    _same(app, reversed_app)
    with pytest.warns(UserWarning, match="3 sites match more than one protein group"):
        reversed_pip = _pip(sites, proteins.iloc[::-1], "unpaired", False)
    _same(app, reversed_pip)
    _run_r(tmp_path, sites, proteins, '''
      warned <- FALSE
      result <- withCallingHandlers(
        volcano_data_f(site, meta, "A", "B", workflow = "Phosphosite", test_type = "unpaired",
                       protein_data = prot[nrow(prot):1, ], protein_meta = meta),
        warning = function(w) {
          if (grepl("3 sites match more than one protein group and keep their uncorrected", conditionMessage(w))) warned <<- TRUE
          invokeRestart("muffleWarning")
        })
      stopifnot(warned)
      write.csv(result, file.path(d, "reversed.csv"), row.names = FALSE)
    ''')
    _same(app, pd.read_csv(tmp_path / "reversed.csv").set_index("PTM_Collapse_key"))


@pytest.mark.requires_r()
@pytest.mark.parametrize("test_type,control", DESIGNS)
def test_r_agrees(tmp_path, test_type, control) -> None:
    sites, proteins = _fixture()
    call = (f'volcano_data_f_control(site, meta, "A", "B", "C", "D", workflow = "Phosphosite", test_type = "{test_type}", '
            'protein_data = prot, protein_meta = meta)' if control else
            f'volcano_data_f(site, meta, "A", "B", workflow = "Phosphosite", test_type = "{test_type}", '
            'protein_data = prot, protein_meta = meta)')
    _run_r(tmp_path, sites, proteins, f'write.csv({call}, file.path(d, "r.csv"), row.names = FALSE)')
    r_table = pd.read_csv(tmp_path / "r.csv").set_index("PTM_Collapse_key")
    _same(_pip(sites, proteins, test_type, control), r_table)


@pytest.mark.requires_r("limma")
@pytest.mark.parametrize("test_type", ["moderated", "moderated_robust_paired"])
def test_moderated_tests_agree_in_all_three(tmp_path, test_type) -> None:
    r_limma.clear_limma_availability_cache()
    sites, proteins = _fixture()
    app, _ = _app(sites, proteins, test_type, False)
    _run_r(tmp_path, sites, proteins,
           f'write.csv(volcano_data_f(site, meta, "A", "B", workflow = "Phosphosite", test_type = "{test_type}", '
           'protein_data = prot, protein_meta = meta), file.path(d, "r.csv"), row.names = FALSE)')
    r_table = pd.read_csv(tmp_path / "r.csv").set_index("PTM_Collapse_key")
    _same(app, r_table, columns=["log2FC", "pval", "adj_pval", "se", "dof", "protein_log2FC"])
    with pytest.raises(ValueError, match="Bioconductor limma"):
        _pip(sites, proteins, test_type, False)


@pytest.mark.requires_r()
def test_ksea_regulation_and_simulation_tables_agree(tmp_path) -> None:
    sites, proteins = _fixture()
    _run_r(tmp_path, sites, proteins, '''
      write.csv(kinase_library_data_f(site, meta, "A", "B", test_type = "unpaired", protein_data = prot, protein_meta = meta),
                file.path(d, "ksea.csv"), row.names = FALSE)
      write.csv(phosprot_regulation_data(site, meta, "A", "B", in_pval = 1, in_log2fc = 0.5, uncorrected = TRUE,
                test_type = "unpaired", protein_data = prot, protein_meta = meta), file.path(d, "reg.csv"), row.names = FALSE)
      # The projected table behind volcano_plot_sim, corrected as the plot corrects it (plotly is not needed).
      sim <- protein_correct_site_results(.volcano_sim_table(site, meta, "A", "B", "Phosphosite", 1, 6),
                                          .volcano_sim_table(prot, meta, "A", "B", "Protein", 1, 6), 0.05, 1, FALSE)
      write.csv(sim[, c("Feature", "log2FC", "pval")], file.path(d, "sim.csv"), row.names = FALSE)
    ''')
    ksea = pkg.kinase_library_data_f(sites, META, "A", "B", test_type="unpaired", protein_data=proteins, protein_meta=META)
    r_ksea = pd.read_csv(tmp_path / "ksea.csv")
    assert np.allclose(ksea["log2FC"], r_ksea["log2FC"]) and np.allclose(ksea["pval"], r_ksea["pval"], equal_nan=True)
    regulation = pkg.phosprot_regulation_data(sites, META, "A", "B", in_pval=1, in_log2fc=0.5, uncorrected=True,
                                              test_type="unpaired", protein_data=proteins, protein_meta=META)
    r_regulation = pd.read_csv(tmp_path / "reg.csv")
    assert list(regulation["Protein_group"]) == list(r_regulation["Protein_group"]) and not regulation.empty
    assert np.allclose(regulation["x"], r_regulation["x"]) and np.allclose(regulation["y"], r_regulation["y"])
    # The simulation at a projected n: pip and R share the pooled projection; the app's at the observed n equals its volcano.
    sim = pkg.volcano_plot_sim(sites, META, "A", "B", workflow="Phosphosite", mod_n=6, protein_data=proteins, protein_meta=META)
    pip_sim = pd.DataFrame({"Feature": np.concatenate([np.asarray(t.customdata)[:, 0] for t in sim.data]),
                            "log2FC": np.concatenate([np.asarray(t.x, dtype=float) for t in sim.data])}).set_index("Feature")
    r_sim = pd.read_csv(tmp_path / "sim.csv").set_index("Feature").loc[pip_sim.index]
    assert len(pip_sim) == 200 and np.allclose(pip_sim["log2FC"], r_sim["log2FC"])


def test_the_app_simulation_at_the_observed_n_is_the_corrected_volcano() -> None:
    sites, proteins = _fixture()
    _, _, protein, _ = _simulation_dataframe(SimulationRequest(kind="protein", source="volcano", condition1="A", condition2="B",
                                                                identifier="workflow", testType="unpaired"),
                                             frame_override=proteins, metadata_override=META)
    stats = protein[["ProteinAccessions", "log2FC", "se", "dof", "pval"]].reset_index(drop=True)
    _, _, simulated, _ = _simulation_dataframe(SimulationRequest(kind="phospho", source="volcano", condition1="A", condition2="B",
                                                                  identifier="workflow", testType="unpaired", proteinCorrection=True),
                                               frame_override=sites, metadata_override=META, protein_stats=stats)
    # frame_override switches the correction off (the protein side is prepared by the caller); apply it here
    from app.services.stats_tools import _apply_protein_correction
    fc, pv, matched, _, _, _, _, _ = _apply_protein_correction(simulated, simulated["log2FC"].to_numpy(), simulated["se"].to_numpy(),
                                                         simulated["dof"].to_numpy(), simulated["pval"].to_numpy(), stats)
    app, _ = _app(sites, proteins, "unpaired", False)
    merged = simulated.assign(fc=fc, pv=pv).set_index("PTM_Collapse_key").loc[app.index]
    assert np.allclose(merged["fc"], app["log2FC"]) and np.allclose(merged["pv"], app["pval"], equal_nan=True)


def test_projection_distinguishes_ambiguous_and_unmatched_sites(monkeypatch) -> None:
    from app.services import stats_tools

    sites, proteins = _fixture()
    _, _, protein, _ = _simulation_dataframe(
        SimulationRequest(kind="protein", condition1="A", condition2="B"),
        frame_override=proteins, metadata_override=META)
    monkeypatch.setattr(stats_tools, "_stats_source", lambda *args, **kwargs: ("data", sites, META, []))
    _, _, result, warnings = _simulation_dataframe(
        SimulationRequest(kind="phospho", condition1="A", condition2="B", proteinCorrection=True),
        protein_stats=protein)
    assert any("3 sites match more than one protein group" in w for w in warnings)
    assert any("12 of 200 sites have no quantified protein" in w for w in warnings)
    unchanged = ~result["protein_matched"]
    np.testing.assert_array_equal(result.loc[unchanged, "log2FC"], result.loc[unchanged, "site_log2FC"])
    np.testing.assert_array_equal(result.loc[unchanged, "pval"], result.loc[unchanged, "site_pval"])
