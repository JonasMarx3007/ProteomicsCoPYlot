"""The server draws one figure at a time.

Requests are answered on several threads, and matplotlib is not thread-safe:
its math-text parser, used for every tick label, keeps state between calls, so
two figures laid out at once could fail with an internal error ("pop from empty
list") or spoil each other. That is what made the retention-time browser test
fail once in a full run and pass alone. Plot routes and report building now
take one lock (`RENDER_LOCK` in plot_export.py).
"""
from __future__ import annotations

import threading
import time

from fastapi.responses import Response

from app.api import plot_responses, plots_qc, routes_summary


class Overlap:
    """Counts how many renders are inside at once."""

    def __init__(self) -> None:
        self.inside = 0
        self.most = 0
        self.guard = threading.Lock()

    def render(self, *_args, **_kwargs):
        with self.guard:
            self.inside += 1
            self.most = max(self.most, self.inside)
        time.sleep(0.05)
        with self.guard:
            self.inside -= 1
        return b"png"


def _together(calls) -> None:
    threads = [threading.Thread(target=call) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_plot_routes_never_render_at_the_same_time() -> None:
    overlap = Overlap()

    def route():
        with plot_responses.plot_errors("Failed to render QC plot"):
            overlap.render()

    _together([route] * 6)
    assert overlap.most == 1


def test_concurrent_requests_are_drawn_one_after_another(client, monkeypatch) -> None:
    """Through the real route and the server's own threads."""
    overlap = Overlap()
    monkeypatch.setattr(plots_qc, "_qc_paired_plot", lambda *a, **k: Response(overlap.render()))
    responses = []
    _together([lambda: responses.append(client.get("/api/plots/qc/protein/cv.png"))] * 5)
    assert [response.status_code for response in responses] == [200] * 5
    assert overlap.most == 1


def test_a_report_waits_for_the_plot_being_drawn(monkeypatch) -> None:
    overlap = Overlap()
    monkeypatch.setattr(routes_summary, "report_with_notebook", lambda *a, **k: overlap.render())

    def plot():
        with plot_responses.plot_errors("Failed to render QC plot"):
            overlap.render()

    _together([plot, lambda: routes_summary.summary_report_route(None), plot])
    assert overlap.most == 1
