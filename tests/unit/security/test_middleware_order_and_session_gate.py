"""Middleware run in a deliberate order; session changes are serialized; gates are dropped."""
from __future__ import annotations

import asyncio

import pytest

from app.main import app, session_gate_mode


def _stack() -> list[str]:
    """Middleware names, outermost first."""
    names = []
    for item in app.user_middleware:
        dispatch = item.kwargs.get("dispatch")
        names.append(dispatch.__name__ if dispatch else item.cls.__name__)
    return names


def test_middleware_order_outermost_first():
    stack = [name for name in _stack() if name != "CORSMiddleware"]
    assert stack == [
        "host_allowlist_middleware",
        "GZipMiddleware",
        "TabSessionMiddleware",
        "security_headers_middleware",
        "session_scope_middleware",
        "heavy_workload_middleware",
        "ProviderWorkloadMiddleware",
        "plot_download_format_middleware",
    ]


def test_bad_host_is_refused_before_any_other_middleware(client):
    response = client.get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 400
    # Refused outside the security-header middleware: no session cookie is issued.
    assert "set-cookie" not in response.headers


def test_unauthenticated_requests_never_reach_the_heavy_queue(client, monkeypatch):
    from app import main

    reached = []

    def tracking(*args, **kwargs):
        reached.append(args)
        raise AssertionError("heavy queue reached before authentication")

    monkeypatch.setattr(main, "session_isolation_enabled", lambda: True)
    monkeypatch.setattr(main, "tool_access_enabled", lambda: True)
    monkeypatch.setattr(main, "tool_session_authenticated", lambda: False)
    monkeypatch.setattr(main, "_authentication_configuration_error", lambda **kwargs: None)
    monkeypatch.setattr(main, "heavy_workload_scope", tracking)
    response = client.get("/api/plots/qc/protein/cv.png")
    assert response.status_code == 401
    assert not reached


@pytest.mark.parametrize("method,path,mode", [
    ("POST", "/api/datasets/upload", "exclusive"),
    ("POST", "/api/annotations/generate", "exclusive"),
    ("POST", "/api/annotations/normalize", "exclusive"),
    ("POST", "/api/annotations/phosprot/upload", "exclusive"),
    ("POST", "/api/data-tools/imputation/run", "exclusive"),
    ("POST", "/api/data-tools/condition-colors/protein", "exclusive"),
    ("PUT", "/api/annotations/pairing", "exclusive"),
    ("DELETE", "/api/annotations/metadata/current/protein", "exclusive"),
    ("POST", "/api/restore/import", "exclusive"),
    ("POST", "/api/stats/volcano/run", "shared"),
    ("POST", "/api/summary/report", "shared"),
    ("GET", "/api/plots/qc/protein/cv.png", "shared"),
    ("POST", "/api/chat/assistant", None),
])
def test_session_changes_take_the_gate_exclusively(method, path, mode):
    assert session_gate_mode(method, path) == mode


def test_every_state_changing_post_route_is_classified():
    """A new POST route must be listed as a change or confirmed as read-only here."""
    from fastapi.routing import APIRoute

    read_only = {
        "/api/analysis/volcano/data", "/api/annotations/log2-detect", "/api/data-tools/imputation/download",
        "/api/data-tools/id-translation/download", "/api/external/peptide-collapse/upload",
        "/api/plots/phospho/ksea-volcano.html", "/api/restore/export", "/api/stats/volcano/run",
        "/api/stats/volcano-control/run", "/api/stats/anova/run", "/api/stats/ora/run",
        "/api/stats/ora/list/run", "/api/stats/simulation/run", "/api/summary/report",
        # Authentication rotates the session itself; chat takes no gate.
        "/api/tool/auth/login", "/api/tool/auth/link-login", "/api/tool/auth/logout",
        "/api/viewer/auth/login", "/api/viewer/auth/qr-login", "/api/viewer/auth/logout",
    }
    unclassified = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "POST" not in route.methods:
            continue
        path = route.path
        if path.startswith("/api/chat/") or path in read_only:
            continue
        concrete = path.replace("{kind}", "protein")
        if session_gate_mode("POST", concrete) != "exclusive":
            unclassified.append(path)
    assert not unclassified, unclassified


def test_session_gates_are_dropped_when_idle():
    from app.services.session_operation_gate import active_gate_count, session_operation_scope

    async def run():
        before = active_gate_count()
        async with session_operation_scope("gate-test-a"):
            async with session_operation_scope("gate-test-b", exclusive=True):
                assert active_gate_count() == before + 2
        assert active_gate_count() == before

    asyncio.run(run())


def test_a_change_waits_for_running_reads_and_blocks_new_ones():
    from app.services.session_operation_gate import session_operation_scope

    order: list[str] = []

    async def run():
        release = asyncio.Event()

        async def reader(name, wait):
            async with session_operation_scope("gate-order"):
                order.append(f"{name} start")
                if wait:
                    await release.wait()
                order.append(f"{name} end")

        async def writer():
            async with session_operation_scope("gate-order", exclusive=True):
                order.append("write")

        first = asyncio.create_task(reader("read1", True))
        await asyncio.sleep(0)
        change = asyncio.create_task(writer())
        await asyncio.sleep(0)
        late = asyncio.create_task(reader("read2", False))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, change, late)

    asyncio.run(run())
    assert order == ["read1 start", "read1 end", "write", "read2 start", "read2 end"]


def test_json_is_compressed_and_images_are_not(client):
    tables = client.get("/api/datasets/current", headers={"accept-encoding": "gzip"})
    assert tables.status_code == 200
    plot = client.get("/api/plots/qc/protein/cv.png", headers={"accept-encoding": "gzip"})
    assert plot.headers.get("content-encoding") != "gzip"
    big = client.post("/api/stats/volcano/run", json={"kind": "protein", "condition1": "WT", "condition2": "GRK"},
                      headers={"accept-encoding": "gzip"})
    assert big.status_code == 200 and big.headers.get("content-encoding") == "gzip"


def test_interactive_plots_can_share_one_plotly_bundle(client):
    from app.services.shared_plotly import PLOTLY_MARKER, plotly_bundle

    version, source = plotly_bundle()
    url = "/api/plots/qc/protein/abundance-interactive.html"
    standalone = client.get(url)
    assert source in standalone.text, "downloads and exports stay self-contained"
    shared = client.get(url, headers={"x-copylot-shared-plotly": "1"})
    assert source not in shared.text and PLOTLY_MARKER in shared.text
    assert len(shared.content) < len(standalone.content) - 4_000_000
    asset = client.get(shared.headers["x-copylot-plotly-asset"])
    assert asset.status_code == 200 and asset.text == source
    assert "immutable" in asset.headers["cache-control"]
    assert shared.text.replace(PLOTLY_MARKER, source) == standalone.text
    assert client.get("/api/runtime/plotly-0.0.0.js").status_code == 404
