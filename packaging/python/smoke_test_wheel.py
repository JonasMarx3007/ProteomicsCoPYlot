"""Run a small analysis against an installed ProteomicsCoPYlot wheel.

CI installs the built wheel into a clean environment and runs this from outside
the repository, so it uses only what the wheel ships: the notebook functions and
the bundled example data. It fails if any step raises or returns nothing.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import proteomicscopylot  # noqa: E402
from proteomicscopylot import notebook_functions as nb  # noqa: E402

repository = Path(__file__).resolve().parents[2]
assert repository not in Path(proteomicscopylot.__file__).resolve().parents, (
    f"imported the source tree ({proteomicscopylot.__file__}), not the installed wheel"
)

data_dir = resources.files("proteomicscopylot.example_data")
data = nb.read_data(str(data_dir / "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv"))
meta = nb.read_data(str(data_dir / "protein_metadata_full.csv"))

filtered = nb.filter_data(data, meta, 3, "per_group")
assert len(filtered) > 1000, len(filtered)
volcano = nb.volcano_data_f(filtered, meta, "WT", "GRK")
assert {"log2FC", "pval", "adj_pval"} <= set(volcano.columns)
scores = nb.pca_scores(filtered, meta)
assert len(scores) == len(meta)
figure = nb.pca_plot(filtered, meta)
figure.savefig(Path.cwd() / "pca.png")
print(f"ProteomicsCoPYlot {proteomicscopylot.__version__}: {len(filtered)} proteins, "
      f"{int((volcano['adj_pval'] < 0.05).sum())} with adjusted p < 0.05")
