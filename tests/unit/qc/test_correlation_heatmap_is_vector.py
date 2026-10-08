"""The correlation heatmap downloads as shapes, not as a picture of shapes.

`matshow` drew the matrix as one embedded image, so the SVG and PDF downloads
held a bitmap: blurred when scaled, and nothing per cell to recolour or edit in
a vector editor. Each cell is now a rectangle, in the app and the pip package.
The R functions' `image()` already drew rectangles in vector devices.
"""
from __future__ import annotations

import re

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from proteomicscopylot import notebook_functions as nb  # noqa: E402


@pytest.mark.parametrize("fmt", ["svg", "pdf"])
def test_the_app_download_has_no_embedded_image(client, fmt: str) -> None:
    response = client.get("/api/plots/qc/protein/correlation.png", params={"downloadFormat": fmt})
    assert response.status_code == 200, response.text[:300]
    assert b"<image" not in response.content and b"/Subtype /Image" not in response.content


def test_the_app_draws_one_shape_per_cell(client) -> None:
    response = client.get("/api/plots/qc/protein/correlation.png", params={"downloadFormat": "svg"})
    svg = response.content.decode("utf-8")
    # The example project has 10 samples: 100 cells, each its own filled path
    # inside the mesh's group.
    mesh = re.search(r'<g id="QuadMesh_1">(.*?)</g>', svg, re.S)
    assert mesh, "no mesh in the figure"
    assert mesh.group(1).count("<path") == 100


def _matrix():
    rng = np.random.default_rng(3)
    samples = [f"{c}_{i}" for c in ("A", "B") for i in (1, 2, 3)]
    data = pd.DataFrame(rng.normal(20, 1, (40, 6)), columns=samples)
    data.insert(0, "ProteinNames", [f"P{i}" for i in range(40)])
    meta = pd.DataFrame({"sample": samples, "condition": [s.split("_")[0] for s in samples]})
    return data, meta


def test_the_pip_package_draws_the_cells_as_shapes() -> None:
    """The matrix itself; the colour bar's smooth gradient is matplotlib's own
    rasterised strip, which the app's export turns back into vector shapes."""
    from matplotlib.collections import QuadMesh
    from matplotlib.image import AxesImage

    data, meta = _matrix()
    fig = nb.corr_plot(data, meta, method="Matrix", id=False)
    children = fig.axes[0].get_children()
    assert not [child for child in children if isinstance(child, AxesImage)]
    meshes = [child for child in children if isinstance(child, QuadMesh)]
    assert len(meshes) == 1 and not meshes[0].get_rasterized()
    assert meshes[0].get_array().size == 36


def test_the_pip_package_keeps_the_matshow_layout() -> None:
    """Row 0 at the top, square cells, column names along the top."""
    data, meta = _matrix()
    fig = nb.corr_plot(data, meta, method="Matrix", id=False)
    ax = fig.axes[0]
    assert ax.get_ylim()[0] > ax.get_ylim()[1]
    assert ax.get_aspect() == 1.0
    assert ax.xaxis.get_ticks_position() == "top"
