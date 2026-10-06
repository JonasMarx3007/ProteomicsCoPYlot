from __future__ import annotations

import json

from matplotlib import pyplot as plt

from app.services.plot_styling import (
    apply_advanced_axes,
    parse_advanced_plot_settings,
)


def test_parse_advanced_plot_settings() -> None:
    settings = {"titleElement": {"text": "Custom"}, "axisLineWidth": 2.5, "gridLineVisible": False}
    assert parse_advanced_plot_settings(json.dumps(settings)) == settings


def test_invalid_advanced_plot_settings_fall_back_to_empty() -> None:
    for value in (None, "", "not json", "[]", "null"):
        assert parse_advanced_plot_settings(value) == {}


def test_advanced_axes_apply_labels_background_and_visibility() -> None:
    figure, axes = plt.subplots()
    try:
        axes.set_title("Original")
        axes.set_xlabel("Original X")
        apply_advanced_axes(
            axes,
            {
                "titleElement": {"text": "Custom title"},
                "xLabelElement": {"text": "Custom X"},
                "backgroundColor": "#abcdef",
                # The panel's four frame sides; the old single switch is
                # migrated before it reaches a renderer (test_legacy_advanced_settings.py).
                "axisLineTop": False,
                "axisLineRight": False,
                "axisLineBottom": False,
                "axisLineLeft": False,
                "gridLineVisible": False,
            },
        )
        assert axes.get_title() == "Custom title"
        assert axes.get_xlabel() == "Custom X"
        assert not any(spine.get_visible() for spine in axes.spines.values())
    finally:
        plt.close(figure)
