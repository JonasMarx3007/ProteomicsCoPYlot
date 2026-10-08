"""One z-score definition for every heatmap, in all three pipelines.

The ANOVA heatmaps used the population SD (ddof=0) while the pathway and
phosphosite heatmaps used the sample SD (ddof=1); every colour bar said
"Z-score". The shared helper uses ddof=1 -- the convention of the tool's other
statistics and of the R functions -- and leaves a row with no spread at zero.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import clustering_tools, single_protein_tools, stats_tools
from proteomicscopylot import notebook_functions

MATRIX = np.array([
    [1.0, 2.0, 3.0, 6.0],
    [5.0, 5.0, 5.0, 5.0],          # no spread -> 0
    [np.nan, 4.0, 8.0, 12.0],      # missing value skipped
    [7.0, np.nan, np.nan, np.nan], # single value -> 0
])


def _expected(matrix):
    frame = pd.DataFrame(matrix)
    sd = frame.std(axis=1, ddof=1).replace(0, 1).fillna(1)
    return frame.sub(frame.mean(axis=1), axis=0).div(sd, axis=0).to_numpy()


def test_helper_uses_the_sample_sd_and_zeroes_flat_rows() -> None:
    z = clustering_tools.row_zscore(MATRIX)
    expected = _expected(MATRIX)
    assert np.allclose(z, expected, equal_nan=True)
    assert np.allclose(z[1], 0)
    assert z[3, 0] == 0 and np.isnan(z[3, 1:]).all()
    # Not the population SD: the first row would then be scaled by sqrt(4/3).
    population = (MATRIX[0] - MATRIX[0].mean()) / MATRIX[0].std()
    assert not np.allclose(z[0], population)


def test_package_helper_is_identical() -> None:
    assert np.allclose(notebook_functions.row_zscore(MATRIX), clustering_tools.row_zscore(MATRIX), equal_nan=True)


# --- what every z-score heatmap actually draws -------------------------------------
#
# Whatever rows a heatmap selects, clusters or reorders, a row z-scored with the
# sample SD has mean 0 and sample SD 1 across the samples it is drawn over. A
# heatmap that z-scores with the population SD (ddof=0) draws rows whose sample
# SD is sqrt(n / (n - 1)) instead -- 1.095 for six samples -- and one that does
# not z-score at all draws intensities. The colour matrix is read back from the
# figure, so this holds however the renderer computes it.


def _drawn_matrices(fig) -> list[np.ndarray]:
    """Every value matrix in the figure that spans several samples.

    Heatmaps are drawn as a QuadMesh (seaborn) or an image (imshow); colour bars
    and condition strips are one column wide or RGB, and are left out.
    """
    from matplotlib.collections import QuadMesh

    found = []
    for axis in fig.axes:
        for artist in axis.collections:
            if isinstance(artist, QuadMesh):
                rows, columns = (n - 1 for n in artist.get_coordinates().shape[:2])
                found.append(np.ma.filled(np.ma.asarray(artist.get_array(), dtype=float), np.nan).reshape(rows, columns))
        for image in axis.images:
            found.append(np.ma.filled(np.ma.asarray(image.get_array(), dtype=float), np.nan))
    return [matrix for matrix in found if matrix.ndim == 2 and matrix.shape[1] >= 3]


def _assert_sample_sd_rows(name: str, fig) -> None:
    matrices = _drawn_matrices(fig)
    assert matrices, f"{name} drew no heatmap"
    for matrix in matrices:
        spread = np.nanstd(matrix, axis=1, ddof=1) > 0
        assert spread.any(), f"{name} drew no row with any spread"
        rows = matrix[spread]
        assert np.allclose(np.nanmean(rows, axis=1), 0, atol=1e-9), f"{name}: rows are not centred"
        assert np.allclose(np.nanstd(rows, axis=1, ddof=1), 1, atol=1e-9), (
            f"{name}: rows are not scaled by the sample SD "
            f"(row SDs {np.unique(np.round(np.nanstd(rows, axis=1, ddof=1), 4))})"
        )


SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]


@pytest.fixture(scope="module")
def package_inputs():
    rng = np.random.default_rng(5)
    n = 30
    values = rng.normal(20, 1, (n, len(SAMPLES)))
    values[:20, 3:] += rng.uniform(2, 5, (20, 1))  # regulated rows, so ANOVA has something to draw
    genes = [f"G{i}" for i in range(n)]
    data = pd.DataFrame(values, columns=SAMPLES)
    data.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    data.insert(1, "GeneNames", genes)
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A"] * 3 + ["B"] * 3})
    sites = data.drop(columns=["ProteinNames"]).assign(
        PTM_Collapse_key=[f"P1~S{i}_M1" for i in range(n)], Protein_group="P1", Gene_group="G1",
        PTM_localization=0.99,
    )
    go_db = pd.DataFrame({"ontology": ["BP"], "term": ["GO:1"], "description": ["term one"],
                          "genes": [";".join(genes[:10])]})
    return {"data": data, "meta": meta, "sites": sites, "go_db": go_db,
            "anova": notebook_functions.anova_data_f(data, meta)}


PACKAGE_HEATMAPS = {
    "anova_plot": lambda i: notebook_functions.anova_plot(i["anova"], i["meta"]),
    "anova_plot_cluster": lambda i: notebook_functions.anova_plot_cluster(
        notebook_functions.anova_cluster_data(i["anova"], i["meta"], n_clusters=2), i["meta"]),
    "proteins_in_pathway": lambda i: notebook_functions.proteins_in_pathway(
        i["data"], i["meta"], i["go_db"], "term one", value_type="z"),
    "phossite_on_prot_regulation": lambda i: notebook_functions.phossite_on_prot_regulation(
        i["sites"], i["meta"], "P1", value_type="z"),
}


@pytest.mark.parametrize("name", list(PACKAGE_HEATMAPS))
def test_every_package_heatmap_draws_sample_sd_z_scores(package_inputs, name: str) -> None:
    import matplotlib.pyplot as plt

    _assert_sample_sd_rows(name, PACKAGE_HEATMAPS[name](package_inputs))
    plt.close("all")


def _app_heatmaps() -> dict:
    from app.schemas.stats import AnovaRequest

    phospho_protein = single_protein_tools.single_protein_options(
        "phospho", tab="heatmap", identifier="workflow")["proteins"][0]
    return {
        "anova": lambda: stats_tools.anova_png(AnovaRequest(kind="protein")),
        "anova cluster": lambda: stats_tools.anova_png(AnovaRequest(kind="protein", source="anova_cluster")),
        "pathway": lambda: stats_tools.pathway_heatmap_png(
            kind="protein", pathway="mitochondrial genome maintenance", conditions=[], value_type="z",
            include_id=False, header=True, remove_empty=True, cluster_rows=False, cluster_cols=False,
            width_cm=20, height_cm=12, dpi=72),
        "phosphosites on a protein": lambda: single_protein_tools.single_protein_heatmap_plot(
            kind="phospho", protein=phospho_protein, conditions=[], value_type="z", filter_m1=False),
    }


@pytest.mark.parametrize("name", ["anova", "anova cluster", "pathway", "phosphosites on a protein"])
def test_every_app_heatmap_draws_sample_sd_z_scores(example_project, monkeypatch, name: str) -> None:
    import matplotlib.pyplot as plt

    figures = []
    for module in (stats_tools, single_protein_tools):
        monkeypatch.setattr(module, "_to_png_bytes", lambda fig, plt, **kw: figures.append(fig) or b"")
    _app_heatmaps()[name]()
    _assert_sample_sd_rows(name, figures[-1])
    plt.close("all")


@pytest.mark.requires_r()
def test_r_helper_agrees(tmp_path, rscript) -> None:
    pd.DataFrame(MATRIX).to_csv(tmp_path / "m.csv", index=False)
    script = f'''
      source("{(ROOT / "proteomicscopylot" / "notebook_functions.R").as_posix()}")
      m <- as.matrix(read.csv("{(tmp_path / "m.csv").as_posix()}"))
      write.csv(row_zscore(m), "{(tmp_path / "z.csv").as_posix()}", row.names = FALSE)
    '''
    result = subprocess.run([rscript, "-e", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    r_z = pd.read_csv(tmp_path / "z.csv").to_numpy(dtype=float)
    assert np.allclose(r_z, clustering_tools.row_zscore(MATRIX), equal_nan=True)
