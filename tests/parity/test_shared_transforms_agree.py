"""The pure transforms the web app and the pip package both carry agree.

Two kinds of check. Functions that exist in both places with the same body are
compared by definition, so a change to one side that is not made to the other
fails here instead of surfacing as a number that differs in a notebook months
later. Functions that are written differently on the two sides (the package
takes a metadata frame where the app takes a column list, say) are compared by
behaviour on the same synthetic input.

`bool_to_str`, `constant_differences` and `without_variation` had no test at
all before this file (2026-10-09 structural review, S8).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import copylot_core, functions as backend
from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]

# Carried in both places with the same body (docstrings and annotations aside).
SAME_DEFINITION = [
    "constant_differences",
    "imputed_cell_mask",
    "imputed_value_counts",
    "missingness_imbalance",
    "missingness_imbalance_warning",
    "resolve_test_type",
    "site_observed_imputed_mask",
    "without_variation",
]


class _Normalised(ast.NodeTransformer):
    """A function with its docstring and type annotations removed."""

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.returns = None
        for argument in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            argument.annotation = None
        for argument in (node.args.vararg, node.args.kwarg):
            if argument is not None:
                argument.annotation = None
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
        return node


def _definition(function) -> str:
    tree = ast.parse(inspect.getsource(function))
    return ast.dump(_Normalised().visit(tree))


@pytest.mark.parametrize("name", SAME_DEFINITION)
def test_a_transform_carried_by_both_sides_has_one_definition(name: str) -> None:
    package_side = getattr(notebook, name)
    app_side = getattr(backend, name, None) or getattr(copylot_core, name)
    assert _definition(package_side) == _definition(app_side), (
        f"{name} is written differently in proteomicscopylot/notebook_functions.py and in the web app; "
        "change both or move it into the shared core"
    )


# --- behaviour parity for the transforms written differently on the two sides --


SAMPLES = ["Ctrl_1", "Ctrl_2", "Ctrl_3", "Treat_1", "Treat_2", "Treat_3"]


def _meta() -> pd.DataFrame:
    return pd.DataFrame({
        "sample": SAMPLES,
        "condition": ["Ctrl"] * 3 + ["Treat"] * 3,
        "pair_id": ["p1", "p2", "p3", "p1", "p2", "p3"],
    })


def _linear_frame(seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = rng.lognormal(14.0, 1.0, (40, len(SAMPLES)))
    values[rng.random(values.shape) < 0.15] = 0.0  # not detected, in the raw convention
    values[3, 1] = np.inf
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(len(frame))])
    return frame


def test_the_log2_and_inverse_transforms_agree() -> None:
    frame, meta = _linear_frame(), _meta()
    from_package = notebook.log2_transform_data(frame.copy(), meta)
    from_app = backend.log2_transform_data(frame.copy(), SAMPLES)
    pd.testing.assert_frame_equal(from_package[SAMPLES], from_app[SAMPLES], check_names=False)
    back_package = notebook.inverse_log2_transform_data(from_package, meta)
    back_app = backend.inverse_log2_transform_data(from_app, SAMPLES)
    pd.testing.assert_frame_equal(back_package[SAMPLES], back_app[SAMPLES], check_names=False)


def test_the_raw_zero_convention_agrees() -> None:
    frame = _linear_frame()
    from_package = notebook.raw_zero_to_nan(frame.copy(), SAMPLES)
    from_app = backend.raw_zero_to_nan(frame.copy(), SAMPLES)
    pd.testing.assert_frame_equal(from_package, from_app)
    assert from_app[SAMPLES].isna().sum().sum() > frame[SAMPLES].isna().sum().sum()
    assert not np.isinf(from_app[SAMPLES].to_numpy(dtype=float)).any()


@pytest.mark.parametrize("cutoff", [0.0, 0.5, 0.75, 1.0])
def test_localization_filtering_agrees(cutoff: float) -> None:
    sites = pd.DataFrame({
        "PTM_Collapse_key": [f"S{i}" for i in range(6)],
        "PTM_localization": [0.2, 0.5, 0.75, 0.9, np.nan, 1.0],
        "Ctrl_1": np.arange(6, dtype=float),
    })
    from_package = notebook.filter_localization(sites.copy(), cutoff)
    from_app = backend.filter_localization(sites.copy(), cutoff)
    assert list(from_package["PTM_Collapse_key"]) == list(from_app["PTM_Collapse_key"])


def test_paired_sample_columns_agree_and_refuse_the_same_metadata() -> None:
    meta = _meta()
    assert notebook.paired_sample_columns(meta, "Ctrl", "Treat") == backend.paired_sample_columns(meta, "Ctrl", "Treat")
    with pytest.raises(ValueError):
        notebook.paired_sample_columns(meta, "Ctrl", "Ctrl")
    with pytest.raises(ValueError):
        backend.paired_sample_columns(meta, "Ctrl", "Ctrl")
    # An unmatched pair id is dropped on both sides, and both refuse fewer than two pairs.
    partial = meta.copy()
    partial.loc[partial["sample"] == "Treat_3", "pair_id"] = "p9"
    assert notebook.paired_sample_columns(partial, "Ctrl", "Treat") == backend.paired_sample_columns(partial, "Ctrl", "Treat")
    single = partial.copy()
    single.loc[single["sample"] == "Treat_2", "pair_id"] = "p8"
    with pytest.raises(ValueError):
        notebook.paired_sample_columns(single, "Ctrl", "Treat")
    with pytest.raises(ValueError):
        backend.paired_sample_columns(single, "Ctrl", "Treat")


@pytest.mark.parametrize("names", [
    ["Sample_1", "Sample_2", "Sample_10"],
    ["Run_12_rep1", "Run_12_rep2", "Run_13_rep3"],
    ["A1.raw", "B2.raw", "C3.d"],
])
def test_sample_id_maps_agree(names: list[str]) -> None:
    assert notebook.sample_id_map(names) == backend.sample_id_map(names)


@pytest.mark.parametrize("names", [
    ["Ctrl_1", "Ctrl_2", "Treat_1", "Treat_2"],
    ["A1.raw", "A1.d", "B2.raw"],
])
def test_both_sides_refuse_sample_names_that_share_a_number(names: list[str]) -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        notebook.sample_id_map(names)
    with pytest.raises(ValueError, match="ambiguous"):
        backend.sample_id_map(names)


@pytest.mark.parametrize("workflow", ["protein", "phospho", "phosprot"])
@pytest.mark.parametrize("centered", [False, True])
def test_abundance_axis_labels_agree(workflow: str, centered: bool) -> None:
    assert notebook.abundance_axis_label(workflow, centered) == backend.abundance_axis_label(workflow, centered)


# --- the three functions no test exercised ----------------------------------


@pytest.mark.parametrize("value,expected", [(True, "TRUE"), (False, "FALSE"), (None, ""), (1, ""), ("TRUE", "")])
def test_bool_to_str_spells_booleans_the_way_r_does_and_nothing_else(value, expected) -> None:
    assert notebook.bool_to_str(value) == expected


def test_constant_differences_ignores_float_subtraction_noise() -> None:
    left = np.array([[0.3, 1.1, 2.2], [1.0, 2.0, 3.0]])
    right = np.array([[0.1, 0.9, 2.0], [1.0, 1.0, 1.0]])
    differences = left - right  # 0.2 three times, as floating point sees it
    assert differences[0].min() != differences[0].max(), "the example must carry subtraction noise"
    assert list(notebook.constant_differences(differences)) == [True, False]
    assert list(backend.constant_differences(differences)) == [True, False]
    # The plain check sees the noise; that is what the rounding is for.
    assert not notebook.constant_within_group(differences)[0]


def test_without_variation_flags_only_rows_where_every_group_is_constant() -> None:
    ctrl = np.array([[1.0, 1.0, 1.0], [1.0, 1.0, 1.0], [1.0, 2.0, 3.0]])
    treat = np.array([[2.0, 2.0, 2.0], [2.0, 2.5, 2.0], [4.0, 4.0, 4.0]])
    expected = [True, False, False]
    assert list(notebook.without_variation([ctrl, treat])) == expected
    assert list(backend.without_variation([ctrl, treat])) == expected
