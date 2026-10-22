"""Protein-corrected phosphosite changes.

A phosphosite that rises because its whole protein rose is not a signalling
event. With a protein dataset in the same package, every site comparison --
volcano, control volcano, simulated volcano, Kinase Library table,
phosphoprotein regulation -- can subtract the protein-level change of the same
comparison: log2FC_site - log2FC_protein, standard errors in quadrature,
Satterthwaite degrees of freedom. Sites are matched by accession
(`Protein_group` against the protein table's `ProteinAccessions`); unmatched
sites keep their own values and say so. The data source is mirrored, never
substituted, so only the matrices both datasets hold are offered.
"""
from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.schemas.data_tools import ImputationRunRequest
from app.services.data_tools import run_imputation
from app.schemas.stats import SimulationRequest, VolcanoControlRequest, VolcanoRequest
from app.services import stats_tools
from app.services.annotation_store import get_annotation, save_annotation
from app.services.dataset_store import save_table_dataset
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_snapshots import snapshots
from app.services.session_context import get_session_id
from app.services.stats_core import protein_corrected_site_changes

SAMPLES = [f"{group}{i}" for group in "ABCD" for i in range(1, 5)]
META = pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES], "pair_id": [s[1] for s in SAMPLES]})


def _save(kind, frame, filtered=None):
    save_table_dataset(f"{kind}.csv", kind, frame)
    save_annotation(kind=kind, source_data=frame, log2_data=frame, filtered_data=frame if filtered is None else filtered,
                    metadata=META.copy(), is_log2_transformed=True, metadata_source="manual",
                    filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[])


@pytest.fixture
def package(phosphosites):
    """The `phosphosites` fixture's package plus a protein dataset: proteins
    P0..P3 (P0 up in A, P3 listed as a group with an isoform), sites on
    P0..P3 (P0-P3 quantified) and P4 (no protein)."""
    rng = np.random.default_rng(3)
    sites = pd.DataFrame(rng.normal(12, 1, (15, 16)), columns=SAMPLES)
    sites["Protein_group"] = [f"P{i // 3}" for i in range(15)]
    sites["Gene_group"] = sites["Protein_group"]
    sites["PTM_Collapse_key"] = [f"P{i // 3}~G{i // 3}_S{i}_M1" for i in range(15)]
    sites["PTM_localization"] = [f"S{i}" for i in range(15)]
    sites["UPD_seq"] = ["AAAAAAASAAAAAAA"] * 15
    sites.loc[0:2, ["A1", "A2", "A3", "A4"]] += 2.0  # P0's sites all rise with P0
    _save("phospho", sites)
    run_imputation(ImputationRunRequest(kind="phospho", seed=87, sampleWise=False))
    proteins = pd.DataFrame(rng.normal(20, 1, (4, 16)), columns=SAMPLES)
    proteins.loc[0, ["A1", "A2", "A3", "A4"]] += 2.0
    proteins.insert(0, "ProteinNames", [f"PN{i}" for i in range(4)])
    proteins.insert(1, "ProteinAccessions", ["P0", "P1", "P2", "P3;P3-2"])
    _save("protein", proteins, filtered=proteins.iloc[:3])
    return sites, proteins


def _manual(site_table, protein_table):
    protein = protein_table.assign(key=protein_table["ProteinAccessions"].str.split(";").str[0]).set_index("key")
    matched = site_table["Protein_group"].isin(protein.index)
    p = protein.reindex(site_table["Protein_group"])
    fc, _, _, pv = protein_corrected_site_changes(
        site_table["site_log2FC"], site_table["site_se"], site_table["site_dof"],
        p["log2FC"].to_numpy(), p["se"].to_numpy(), p["dof"].to_numpy())
    return np.where(matched, fc, site_table["site_log2FC"]), np.where(matched, pv, site_table["site_pval"]), matched.to_numpy()


@pytest.mark.parametrize("test_type", ["unpaired", "unpaired_welch", "paired"])
def test_volcano_subtracts_the_protein_change_of_the_same_comparison(package, test_type):
    plain = stats_tools.run_volcano(VolcanoRequest(kind="phospho", condition1="A", condition2="B", testType=test_type))
    corrected = stats_tools.run_volcano(VolcanoRequest(kind="phospho", condition1="A", condition2="B", testType=test_type,
                                                       proteinCorrection=True))
    table = pd.DataFrame(corrected.rows)
    protein = pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="protein", condition1="A", condition2="B", testType=test_type, useUncorrected=True)).rows)
    fc, pv, matched = _manual(table, protein)
    assert np.allclose(table["log2FC"].astype(float), fc) and np.allclose(table["pval"].astype(float), pv, equal_nan=True)
    assert list(table["protein_matched"]) == list(matched) and matched.sum() == 12
    # The uncorrected values are kept beside the corrected ones ...
    assert np.allclose(table["site_log2FC"].astype(float), pd.DataFrame(plain.rows)["log2FC"].astype(float))
    # ... P0's sites no longer look regulated once P0's own rise is removed ...
    p0 = table[table["Protein_group"] == "P0"]
    assert (p0["site_log2FC"].astype(float) - p0["log2FC"].astype(float)).round(9).nunique() == 1  # one protein change subtracted
    assert (p0["site_log2FC"].astype(float) - p0["log2FC"].astype(float)).iloc[0] > 1
    # ... sites on P3 are matched through the group's first member, and P4's are not.
    assert table.loc[table["Protein_group"] == "P3", "protein_matched"].all()
    assert not table.loc[table["Protein_group"] == "P4", "protein_matched"].any()
    assert any(w.startswith("Protein correction: 3 of 15 sites have no quantified protein") for w in corrected.warnings)
    np.testing.assert_allclose(table["site_se"], pd.DataFrame(plain.rows)["se"])
    np.testing.assert_allclose(table["site_dof"], pd.DataFrame(plain.rows)["dof"])
    from scipy.stats import t
    np.testing.assert_allclose(table["pval"], 2 * t.sf(np.abs(table["log2FC"] / table["se"]), table["dof"]))


def test_control_volcano_corrects_with_the_same_four_conditions(package):
    corrected = stats_tools.run_volcano_control(VolcanoControlRequest(
        kind="phospho", condition1="A", condition2="B", condition1Control="C", condition2Control="D",
        testType="unpaired_welch", proteinCorrection=True))
    table = pd.DataFrame(corrected.rows)
    protein = pd.DataFrame(stats_tools.run_volcano_control(VolcanoControlRequest(
        kind="protein", condition1="A", condition2="B", condition1Control="C", condition2Control="D",
        testType="unpaired_welch", useUncorrected=True)).rows)
    fc, pv, _ = _manual(table, protein)
    assert np.allclose(table["log2FC"].astype(float), fc) and np.allclose(table["pval"].astype(float), pv, equal_nan=True)


def test_the_simulation_at_the_observed_n_reproduces_the_corrected_volcano(package):
    volcano = pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="phospho", condition1="A", condition2="B", testType="unpaired", proteinCorrection=True)).rows)
    simulated = pd.DataFrame(stats_tools.run_simulation(SimulationRequest(
        kind="phospho", source="volcano", condition1="A", condition2="B", testType="unpaired", proteinCorrection=True)).rows)
    merged = volcano.merge(simulated, on="PTM_Collapse_key", suffixes=("", "_sim"))
    assert len(merged) == len(volcano)
    assert np.allclose(merged["log2FC"].astype(float), merged["log2FC_sim"].astype(float))
    assert np.allclose(merged["pval"].astype(float), merged["pval_sim"].astype(float), equal_nan=True)
    # More replicates: the protein side is projected too, so corrected p-values move with both.
    bigger = pd.DataFrame(stats_tools.run_simulation(SimulationRequest(
        kind="phospho", source="volcano", condition1="A", condition2="B", testType="unpaired",
        proteinCorrection=True, sampleSizeOverride=12)).rows)
    assert (bigger["pval"].astype(float) < simulated["pval"].astype(float)).mean() > 0.8


def test_ksea_and_regulation_tables_use_the_corrected_site_changes(package, monkeypatch):
    from app.services import phospho_tools
    monkeypatch.setattr(phospho_tools, "_ksea_protein_sequences", lambda organism: {})
    volcano = pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="phospho", condition1="A", condition2="B", testType="unpaired", proteinCorrection=True)).rows)
    ksea = phospho_tools.ksea_table(condition1="A", condition2="B", test_type="unpaired", protein_correction=True)
    assert np.allclose(ksea["log2FC"].to_numpy(dtype=float), volcano["log2FC"].astype(float))
    regulation = phospho_tools.phosprot_regulation_table(
        condition1="A", condition2="B", test_type="unpaired", log2fc_threshold=0.5, p_value_threshold=1,
        use_uncorrected=True, protein_correction=True)
    uncorrected = phospho_tools.phosprot_regulation_table(
        condition1="A", condition2="B", test_type="unpaired", log2fc_threshold=0.5, p_value_threshold=1, use_uncorrected=True)
    before = uncorrected.set_index("Protein_group").loc["P0", "x"]
    after = regulation.set_index("Protein_group")["x"].get("P0", 0.0)
    assert before > 3 and after < before - 3, (before, after)  # three sites, each ~2 log2 lower


def test_only_the_data_sources_both_datasets_hold_are_offered_and_accepted(package):
    options = stats_tools.statistical_options("phospho").proteinCorrection
    assert options.available and options.dataSources == ["data", "filtered"]
    assert not stats_tools.statistical_options("protein").proteinCorrection.available
    with pytest.raises(ValueError, match="no 'imputed' matrix"):
        stats_tools.run_volcano(VolcanoRequest(kind="phospho", condition1="A", condition2="B", dataSource="imputed",
                                               proteinCorrection=True))
    with pytest.raises(ValueError, match="phosphosite comparisons only"):
        stats_tools.run_volcano(VolcanoRequest(kind="protein", condition1="A", condition2="B", proteinCorrection=True))


def test_a_protein_table_without_accessions_is_refused_by_name(package):
    for frame in (get_annotation("protein").log2_data, get_annotation("protein").filtered_data):
        frame.drop(columns=["ProteinAccessions"], inplace=True)
    with pytest.raises(ValueError, match="A protein accession column is required for protein correction."):
        stats_tools.run_volcano(VolcanoRequest(kind="phospho", condition1="A", condition2="B", proteinCorrection=True))


def _replay(tmp_path, recipe):
    _, blob = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(blob)) as archive:
        archive.extractall(tmp_path)
        name = next(n for n in archive.namelist() if n.endswith(".ipynb"))
    notebook = json.loads((tmp_path / name).read_text())
    cells = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    run = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0,'.');\n" + cells],
                         cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("control", [False, True])
def test_the_volcano_notebook_carries_the_protein_matrix_and_replays(package, tmp_path, control):
    from app.services.notebook_volcano import render_volcano
    cls = VolcanoControlRequest if control else VolcanoRequest
    extra = dict(condition1Control="C", condition2Control="D", testType="unpaired_welch") if control else {}
    payload = cls(kind="phospho", condition1="A", condition2="B", dataSource="filtered", proteinCorrection=True, **extra)
    content, token = render_volcano(payload, dpi=80)
    assert content == stats_tools.volcano_png(payload, dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    assert {"protein_input.parquet", "protein_metadata.parquet"} <= set(recipe.resources)
    assert recipe.settings["calculation"]["protein_correction"] and recipe.settings["protein_calculation"]["kind"] == "protein"
    assert "corrected for its protein's change" in recipe.input_explanation
    table = pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"]))
    expected, _ = stats_tools._volcano_inputs(payload)
    pd.testing.assert_frame_equal(table, expected)
    _replay(tmp_path, recipe)
    assert (tmp_path / "reproduced.png").read_bytes() == content


def test_the_ksea_and_regulation_notebooks_replay_the_correction(package, tmp_path, monkeypatch):
    from app.services import phospho_tools
    from app.services.notebook_ksea import capture_table
    from app.services.notebook_regulation import render_regulation
    monkeypatch.setattr(phospho_tools, "_ksea_protein_sequences", lambda organism: {})
    options = dict(condition1="A", condition2="B", test_type="unpaired", protein_correction=True)
    table, token = capture_table(organism="human", **options)
    pd.testing.assert_frame_equal(table, phospho_tools.ksea_table(organism="human", **options))
    recipe = snapshots.get(get_session_id(), token)
    assert "protein_input.parquet" in recipe.resources
    _replay(tmp_path / "ksea", recipe)
    regulation = dict(options, p_value_threshold=1, log2fc_threshold=0.5, use_uncorrected=True)
    content, token = render_regulation(interactive=False, **regulation)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.settings["protein_calculation"]["kind"] == "protein"
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"])),
                                  phospho_tools.phosprot_regulation_table(**regulation))
    _replay(tmp_path / "regulation", recipe)
    assert (tmp_path / "regulation" / "reproduced.png").read_bytes() == content


@pytest.mark.requires_r("limma")
def test_moderated_tests_correct_with_the_moderated_standard_error(package):
    corrected = pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="phospho", condition1="A", condition2="B", testType="moderated", proteinCorrection=True)).rows)
    protein = pd.DataFrame(stats_tools.run_volcano(VolcanoRequest(
        kind="protein", condition1="A", condition2="B", testType="moderated", useUncorrected=True)).rows)
    fc, pv, _ = _manual(corrected, protein)
    assert np.allclose(corrected["log2FC"].astype(float), fc) and np.allclose(corrected["pval"].astype(float), pv, equal_nan=True)
    from scipy import stats
    # The moderated p-value is the t-test on the moderated SE and df the correction combines.
    expected = 2 * stats.t.sf(np.abs(corrected["site_log2FC"].astype(float) / corrected["site_se"].astype(float)), corrected["site_dof"].astype(float))
    assert np.allclose(corrected["site_pval"].astype(float), expected)
