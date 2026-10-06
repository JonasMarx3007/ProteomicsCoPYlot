"""Settings an older panel wrote are read in the current panel's keys.

The single frame switch (`axisLineVisible`) became four per-side boxes, and the
value-label offsets (`textXOffset`/`textYOffset`) lost their control when the
panel was redesigned. Nothing writes them any more, but a saved session can
still carry them. They are converted where settings enter the backend -- a
plot's `advanced` parameter and a report's saved map -- and no renderer reads
the old keys. The frontend half, which keeps the panel showing what the plot
draws, is frontend/tests/unit/legacy-advanced-settings.test.ts.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from app.services import report_function  # noqa: E402
from app.services.plot_styling import (  # noqa: E402
    apply_advanced_axes,
    migrate_advanced_plot_settings,
    parse_advanced_plot_settings,
)

SIDES = ("axisLineTop", "axisLineRight", "axisLineBottom", "axisLineLeft")


@pytest.mark.parametrize("frame", [True, False])
def test_the_frame_switch_becomes_four_sides(frame: bool) -> None:
    migrated = migrate_advanced_plot_settings({"axisLineVisible": frame, "axisLineColor": "#123456"})
    assert migrated == {"axisLineColor": "#123456", **{side: frame for side in SIDES}}


def test_a_side_set_on_its_own_keeps_its_value() -> None:
    migrated = migrate_advanced_plot_settings({"axisLineVisible": False, "axisLineLeft": True})
    assert migrated["axisLineLeft"] is True and migrated["axisLineBottom"] is False


def test_the_value_label_offsets_are_dropped() -> None:
    assert migrate_advanced_plot_settings({"textXOffset": 3, "textYOffset": -2, "valueLabelSize": 8}) == {
        "valueLabelSize": 8
    }


def test_current_settings_pass_through_untouched() -> None:
    settings = {"axisLineTop": False, "markerSize": 4}
    assert migrate_advanced_plot_settings(settings) is settings


def test_a_plot_request_with_the_old_switch_draws_no_frame() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    apply_advanced_axes(ax, parse_advanced_plot_settings(json.dumps({"axisLineVisible": False})))
    assert not any(spine.get_visible() for spine in ax.spines.values())
    plt.close(fig)


def test_a_report_from_an_old_session_is_migrated_too() -> None:
    saved = {"volcano": {"axisLineVisible": False, "textXOffset": 2}}
    assert report_function._advanced_settings_from_map(saved, "volcano") == {side: False for side in SIDES}
