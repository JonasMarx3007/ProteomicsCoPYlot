"""The viewer carries a phosphoprotein file's collapse provenance, without collapsing.

The viewer never collapses anything -- it is handed a phosphoprotein matrix that
was produced elsewhere, so `collapse_mode` in a viewer config is a statement
about that file, not an instruction. It still matters: `robust_site_median`
centres every site on its own across-sample median, so those values are ratios
rather than abundances, and the axis label depends on knowing that.

The loader used to drop the key entirely, so every shared phosphoprotein project
labelled ratios as "Intensity" for everyone viewing it.

A declaration nothing checks is a claim, not a fact: the shipped example config
declared `robust_site_median` while its CSV was `sum_ignore_na`, which turned the
fix above into a confident wrong label. `test_the_declared_mode_matches_the_file`
is the test that closes that gap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import PhosprotAggregationMode
from app.services.annotation_store import get_annotation
from app.services.functions import abundance_axis_label
from app.services.analysis_matrix import phosprot_values_are_centred
from app.services.phosprot_tools import transform_phosprot
from app.services.viewer_bootstrap import _phosprot_aggregation, load_viewer_state

CONFIG = ROOT / "viewer_config.json"


@pytest.fixture(scope="module")
def loaded():
    return load_viewer_state(CONFIG)


def declared_mode() -> str:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    package = next(iter(config["datasets"].values()))
    return str(package["collapse_mode"])


# --- the declaration is recorded, and is true --------------------------------


def test_the_declared_collapse_mode_is_recorded(loaded) -> None:
    annotation = get_annotation("phosprot")
    assert annotation is not None
    assert getattr(annotation, "phosprot_aggregation", None) == declared_mode(), (
        "the viewer dropped the collapse provenance the config declares"
    )


def test_the_declared_mode_matches_the_file(loaded) -> None:
    """The config's claim about the CSV must be checkable, and checked.

    Nothing verified this, so the shipped example declared `robust_site_median`
    over a file that was `sum_ignore_na`. Every phosphoprotein axis in the
    example project then read "Ratio to Site Median" over plain abundances --
    a wrong label made confident by a correct mechanism.

    Reconstructs the phosphoprotein matrix from the phosphosite file in every
    mode the schema allows and asserts the declared one is the mode that
    reproduces the shipped file.
    """
    phospho = get_annotation("phospho")
    phosprot = get_annotation("phosprot")
    assert phospho is not None and phosprot is not None

    samples = [s for s in phosprot.metadata["sample"].astype(str) if s in phosprot.source_data.columns]
    label = next(c for c in phosprot.source_data.columns if c not in samples)
    stored = (
        phosprot.source_data.set_index(label)[samples]
        .apply(pd.to_numeric, errors="coerce")
        .sort_index()
    )

    reproduced: list[str] = []
    for mode in sorted(get_args(PhosprotAggregationMode)):
        try:
            built = transform_phosprot(
                phospho.source_data,
                phospho.metadata,
                mode=mode,
                data_scale="log2" if phospho.is_log2_transformed else "linear",
            )
        except Exception:  # a mode this dataset cannot support is simply not the one
            continue
        built_label = next(
            (c for c in built.columns if c in stored.index.name or c == stored.index.name),
            stored.index.name,
        )
        if built_label not in built.columns:
            continue
        candidate = (
            built.set_index(built_label)[
                [s for s in samples if s in built.columns]
            ]
            .apply(pd.to_numeric, errors="coerce")
            .sort_index()
        )
        common = stored.index.intersection(candidate.index)
        if len(common) < 0.9 * len(stored):
            continue
        a = stored.loc[common].to_numpy(float)
        b = candidate.loc[common].reindex(columns=samples).to_numpy(float)
        if not np.array_equal(np.isfinite(a), np.isfinite(b)):
            continue
        both = np.isfinite(a)
        if both.any() and np.abs(a[both] - b[both]).max() < 1e-9:
            reproduced.append(mode)

    assert reproduced, (
        "no aggregation mode reproduces the shipped phosphoprotein file, so its "
        "declared provenance cannot be verified at all"
    )
    assert declared_mode() in reproduced, (
        f"viewer_config.json declares {declared_mode()!r} but the phosphoprotein "
        f"file was produced with {reproduced!r}"
    )


# --- what the declaration means for the axis ---------------------------------


def test_only_robust_site_median_means_ratios() -> None:
    """Every other mode keeps real abundances; the label must not claim ratios."""
    for mode in get_args(PhosprotAggregationMode):
        centred = mode == "robust_site_median"
        label = abundance_axis_label("Phosphoprotein", centred)
        if centred:
            assert "Ratio to Site Median" in label
        else:
            assert "Intensity" in label, mode


def test_the_example_project_is_labelled_as_the_abundances_it_holds(loaded) -> None:
    """The shipped file is summed, so its axis must say Intensity."""
    assert declared_mode() != "robust_site_median", (
        "this test describes the shipped example; update it with the example"
    )
    assert phosprot_values_are_centred("phosprot") is False
    label = abundance_axis_label("Phosphoprotein", phosprot_values_are_centred("phosprot"))
    assert label == "log10 Phosphoprotein Intensity"

    annotation = get_annotation("phosprot")
    samples = [s for s in annotation.metadata["sample"].astype(str) if s in annotation.source_data.columns]
    values = annotation.source_data[samples].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    assert np.nanmin(values) >= 0, (
        "summed abundances cannot be negative; this file is not what it claims"
    )


def test_a_centred_project_is_labelled_as_ratios(loaded) -> None:
    """The path no shipped project exercises: real robust_site_median values.

    Built here rather than shipped, so the ratio label is covered without a
    second copy of the example data.
    """
    phospho = get_annotation("phospho")
    centred = transform_phosprot(
        phospho.source_data,
        phospho.metadata,
        mode="robust_site_median",
        data_scale="log2" if phospho.is_log2_transformed else "linear",
    )
    samples = [s for s in phospho.metadata["sample"].astype(str) if s in centred.columns]
    values = centred[samples].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    finite = values[np.isfinite(values)]
    assert finite.size
    assert finite.min() < 0 < finite.max(), (
        "centred values must straddle zero; that is what makes them ratios"
    )
    assert abs(float(np.median(finite))) < 0.5

    annotation = get_annotation("phosprot")
    original = annotation.phosprot_aggregation
    annotation.phosprot_aggregation = "robust_site_median"
    try:
        assert phosprot_values_are_centred("phosprot") is True
        assert abundance_axis_label(
            "Phosphoprotein", phosprot_values_are_centred("phosprot")
        ) == "log10 Phosphoprotein Ratio to Site Median"
    finally:
        annotation.phosprot_aggregation = original


# --- resolving the config key ------------------------------------------------


def test_a_clean_config_produces_no_warnings(loaded) -> None:
    assert loaded.warnings == []


@pytest.mark.parametrize("mode", sorted(get_args(PhosprotAggregationMode)))
def test_every_aggregation_mode_the_tool_supports_is_accepted(mode: str) -> None:
    assert _phosprot_aggregation({"collapse_mode": mode}) == mode


def test_spelling_variants_resolve() -> None:
    assert _phosprot_aggregation({"collapse_mode": "Robust-Site-Median"}) == "robust_site_median"
    assert _phosprot_aggregation({"collapse_mode": " mean "}) == "mean"


def test_an_absent_key_is_not_a_warning() -> None:
    warnings: list[str] = []
    assert _phosprot_aggregation({}, warnings) is None
    assert warnings == []


def test_an_unrecognised_mode_warns_rather_than_failing_the_project() -> None:
    """One bad key must not stop a shared project loading -- but must be said."""
    warnings: list[str] = []
    assert _phosprot_aggregation({"collapse_mode": "median_of_medians"}, warnings) is None
    assert len(warnings) == 1
    assert "median_of_medians" in warnings[0]
    assert "robust_site_median" in warnings[0], "the message should name what is valid"


def test_the_resolver_validates_against_the_schema_not_a_copy(monkeypatch) -> None:
    """A new aggregation mode must not need a second edit here.

    The schema's mode list is extended with a mode no copy could already know;
    a resolver that reads the schema accepts it, and one that checks against
    its own hardcoded list refuses it with the "not recognised" warning.
    """
    from typing import Literal

    import app.schemas.annotation as annotation_schema
    import app.services.viewer_bootstrap as viewer_bootstrap

    extended = Literal[(*get_args(PhosprotAggregationMode), "future_mode")]
    monkeypatch.setattr(annotation_schema, "PhosprotAggregationMode", extended)
    monkeypatch.setattr(viewer_bootstrap, "PhosprotAggregationMode", extended, raising=False)

    warnings: list[str] = []
    assert _phosprot_aggregation({"collapse_mode": "future_mode"}, warnings) == "future_mode"
    assert warnings == []


def test_the_viewer_never_collapses(monkeypatch) -> None:
    """Provenance only: reading collapse_mode must not trigger an aggregation.

    The viewer's contract is that the phosphoprotein matrix arrives ready. If
    loading a config ever called the collapse routine, a shared project would
    silently re-derive its own numbers.
    """
    from app.services import phosprot_tools

    called: list[str] = []
    for name in dir(phosprot_tools):
        if name.startswith("transform_phosprot") or name.startswith("collapse"):
            attr = getattr(phosprot_tools, name)
            if callable(attr):
                monkeypatch.setattr(
                    phosprot_tools,
                    name,
                    lambda *a, _n=name, **k: called.append(_n),
                )

    load_viewer_state(CONFIG)
    assert called == [], f"the viewer invoked a collapse routine: {called}"
