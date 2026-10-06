"""A group's ellipse depends on its points, not on how they sit in memory.

The app draws the PCA ellipses from a pandas selection and the exported
notebook from its own; the same scores can arrive row-major in one and
column-major in the other. With older numpy the two took different paths
through the linear algebra and the outlines differed in the last bit, so the
interactive figure in the notebook no longer matched the app's.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.plot_images import fitted_group_ellipse as app_ellipse
from proteomicscopylot.notebook_functions import fitted_group_ellipse as package_ellipse


@pytest.mark.parametrize("fitted_group_ellipse", [app_ellipse, package_ellipse], ids=["app", "package"])
def test_the_same_points_give_the_same_ellipse_in_either_layout(fitted_group_ellipse) -> None:
    rng = np.random.default_rng(17)
    for _ in range(25):
        points = rng.normal(0, 3, (int(rng.integers(3, 9)), 2))
        row_major = fitted_group_ellipse(np.ascontiguousarray(points))
        column_major = fitted_group_ellipse(np.asfortranarray(points))
        assert row_major is not None and column_major is not None
        for left, right in zip(row_major, column_major):
            assert np.array_equal(left, right)
