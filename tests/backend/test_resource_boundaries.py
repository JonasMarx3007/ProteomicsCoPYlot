from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app import main
from app.api import routes_restore
from app.schemas.chat import ChatMessage, OllamaChatRequest
from app.services import restore_state, viewer_bootstrap
from app.services.restore_state import RestoreStateError


class _Upload:
    def __init__(self, content: bytes, filename: str = "replacement.csv") -> None:
        self.file = io.BytesIO(content)
        self.size = len(content)
        self.filename = filename


def _manifest(count: int) -> str:
    return json.dumps(
        [
            {"packageName": f"package-{index}", "kind": "protein"}
            for index in range(count)
        ]
    )


def test_restore_table_accepts_normal_payload_and_rejects_dimension_abuse(monkeypatch) -> None:
    normal = restore_state._frame_from_payload(
        {"columns": ["protein", "s1"], "data": [["P1", 1.0], ["P2", None]]}
    )
    assert normal.shape == (2, 2)

    monkeypatch.setenv("COPYLOT_RESTORE_TABLE_MAX_ROWS", "2")
    with pytest.raises(RestoreStateError, match="row limit"):
        restore_state._frame_from_payload({"columns": ["s1"], "data": [[1], [2], [3]]})

    monkeypatch.setenv("COPYLOT_RESTORE_TABLE_MAX_ROWS", "100")
    monkeypatch.setenv("COPYLOT_RESTORE_TABLE_MAX_COLUMNS", "2")
    with pytest.raises(RestoreStateError, match="column limit"):
        restore_state._frame_from_payload({"columns": ["a", "b", "c"], "data": []})

    monkeypatch.setenv("COPYLOT_RESTORE_TABLE_MAX_COLUMNS", "100")
    monkeypatch.setenv("COPYLOT_RESTORE_TABLE_MAX_CELLS", "3")
    with pytest.raises(RestoreStateError, match="cell limit"):
        restore_state._frame_from_payload({"columns": ["a", "b"], "data": [[1, 2], [3, 4]]})


def test_restore_table_rejects_ragged_rows() -> None:
    with pytest.raises(RestoreStateError, match="declared columns"):
        restore_state._frame_from_payload({"columns": ["a", "b"], "data": [[1]]})


def test_restore_replacements_enforce_per_file_and_aggregate_limits(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES", "10")
    monkeypatch.setenv("COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES", "15")

    with pytest.raises(RestoreStateError, match="upload limit"):
        restore_state.parse_replacements_manifest(_manifest(1), [_Upload(b"x" * 11)])

    with pytest.raises(RestoreStateError, match="aggregate upload limit"):
        restore_state.parse_replacements_manifest(
            _manifest(2),
            [_Upload(b"x" * 8), _Upload(b"y" * 8)],
        )

    accepted = restore_state.parse_replacements_manifest(
        _manifest(2),
        [_Upload(b"x" * 7), _Upload(b"y" * 8)],
    )
    assert sum(item.size_bytes or 0 for item in accepted.values()) == 15


def test_restore_replacement_count_and_manifest_are_bounded(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_RESTORE_REPLACEMENT_MAX_FILES", "1")
    with pytest.raises(RestoreStateError, match="Too many replacement files"):
        restore_state.parse_replacements_manifest(
            _manifest(2),
            [_Upload(b"x"), _Upload(b"y")],
        )

    monkeypatch.setenv("COPYLOT_RESTORE_REPLACEMENT_MAX_FILES", "10")
    monkeypatch.setenv("COPYLOT_RESTORE_MANIFEST_MAX_CHARS", "10")
    with pytest.raises(RestoreStateError, match="manifest exceeds"):
        restore_state.parse_replacements_manifest(_manifest(1), [_Upload(b"x")])


def test_chat_limits_allow_normal_context_but_reject_abuse() -> None:
    normal = OllamaChatRequest(
        message="Summarize the PCA.",
        messages=[ChatMessage(role="system", content="evidence" * 1000)]
        + [ChatMessage(role="user", content="earlier question") for _ in range(8)],
    )
    assert len(normal.messages) == 9

    with pytest.raises(ValidationError):
        OllamaChatRequest(message="x" * 32_001)
    with pytest.raises(ValidationError):
        OllamaChatRequest(
            message="hello",
            messages=[ChatMessage(role="user", content="history") for _ in range(65)],
        )
    with pytest.raises(ValidationError, match="total text limit"):
        OllamaChatRequest(
            message="hello",
            messages=[ChatMessage(role="system", content="x" * 250_000) for _ in range(4)],
        )


def _plot_request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/plots/test.png",
            "raw_path": b"/api/plots/test.png",
            "query_string": b"downloadFormat=pdf",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )


def test_plot_conversion_sanitizes_internal_errors(monkeypatch) -> None:
    secret = r"C:\\private\\plot.png"
    monkeypatch.setattr(
        main,
        "_convert_png_bytes",
        lambda content, target: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    async def call_next(_request: Request) -> Response:
        return Response(content=b"png", media_type="image/png")

    response = asyncio.run(main.plot_download_format_middleware(_plot_request(), call_next))
    assert response.status_code == 500
    assert secret.encode() not in response.body
    assert b"Failed to convert plot download" in response.body


def test_plot_conversion_rejects_excessive_generated_image(monkeypatch) -> None:
    monkeypatch.setattr(main, "_plot_conversion_max_bytes", lambda: 2)

    async def call_next(_request: Request) -> Response:
        return Response(content=b"png", media_type="image/png")

    response = asyncio.run(main.plot_download_format_middleware(_plot_request(), call_next))
    assert response.status_code == 413


def test_health_reports_frontend_availability_without_filesystem_path() -> None:
    with TestClient(main.app) as client:
        payload = client.get("/api/health").json()
    assert "frontendDist" not in payload
    assert isinstance(payload["frontendAvailable"], bool)


def test_unexpected_restore_parse_error_is_not_disclosed(monkeypatch) -> None:
    secret = r"C:\\private\\restore.copylotstate"
    monkeypatch.setattr(
        routes_restore,
        "decode_restore_blob",
        lambda blob: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    with TestClient(main.app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/api/restore/import",
            files={"stateFile": ("state.copylotstate", b"{}", "application/octet-stream")},
        )
    assert response.status_code == 400
    assert secret not in response.text
    assert response.json()["detail"] == "Failed to parse restore state."


def test_viewer_missing_path_warning_does_not_disclose_path(tmp_path: Path) -> None:
    missing = tmp_path / "private" / "protein.tsv"
    warnings: list[str] = []
    resolved = viewer_bootstrap._resolve_config_file_path(
        config={"protein_file": str(missing)},
        key="protein_file",
        base_dir=tmp_path,
        warnings=warnings,
        label="protein file",
    )
    assert resolved is None
    assert warnings
    assert str(missing) not in warnings[0]


def test_compose_services_have_resource_and_read_only_limits() -> None:
    root = Path(__file__).resolve().parents[2]
    for filename in ("docker-compose.yml", "docker-compose.viewer.yml"):
        content = (root / filename).read_text(encoding="utf-8")
        assert "read_only: true" in content
        assert "mem_limit:" in content
        assert "cpus:" in content
        assert "tmpfs:" in content
