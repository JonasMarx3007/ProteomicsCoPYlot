from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app import main
from app.api import routes_restore
from app.schemas.chat import ChatMessage, ChatRequest
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
    normal = ChatRequest(
        message="Summarize the PCA.",
        messages=[ChatMessage(role="system", content="evidence" * 1000)]
        + [ChatMessage(role="user", content="earlier question") for _ in range(8)],
    )
    assert len(normal.messages) == 9

    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 32_001)
    with pytest.raises(ValidationError):
        ChatRequest(
            message="hello",
            messages=[ChatMessage(role="user", content="history") for _ in range(65)],
        )
    with pytest.raises(ValidationError, match="total text limit"):
        ChatRequest(
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


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError, OSError])
def test_plot_conversion_sanitizes_internal_errors(monkeypatch, error_type) -> None:
    secret = r"C:\\private\\plot.png"
    monkeypatch.setattr(
        main,
        "_convert_png_bytes",
        lambda content, target: (_ for _ in ()).throw(error_type(secret)),
    )

    async def call_next(_request: Request) -> Response:
        return Response(content=b"png", media_type="image/png")

    response = asyncio.run(main.plot_download_format_middleware(_plot_request(), call_next))
    assert response.status_code == 500
    assert secret.encode() not in response.body
    assert b"Failed to convert plot download" in response.body


def test_unsupported_download_format_is_rejected_before_rendering() -> None:
    request = _plot_request()
    request.scope["query_string"] = b"downloadFormat=not-a-format"

    async def call_next(_request):
        pytest.fail("An unsupported format must not start a render")

    response = asyncio.run(main.plot_download_format_middleware(request, call_next))
    assert response.status_code == 400
    assert json.loads(response.body) == {"detail": "Unsupported download format. Choose png, jpg, jpeg, webp, pdf or svg."}


def test_plot_conversion_rejects_excessive_generated_image(monkeypatch) -> None:
    monkeypatch.setattr(main, "_plot_conversion_max_bytes", lambda: 2)

    async def call_next(_request: Request) -> Response:
        return Response(content=b"png", media_type="image/png")

    response = asyncio.run(main.plot_download_format_middleware(_plot_request(), call_next))
    assert response.status_code == 413


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_plot_conversion_preserves_alpha_and_composites_white(mode) -> None:
    from PIL import Image

    source = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
    source.paste((200, 0, 0, 255), (200, 100, 400, 200))
    source.paste((0, 0, 0, 128), (400, 100, 500, 200))
    source = source.convert(mode)
    buf = io.BytesIO()
    source.save(buf, format="PNG", dpi=(300, 300))
    png = buf.getvalue()
    assert main._convert_png_bytes(png, "png") == (png, "image/png")
    webp, media = main._convert_png_bytes(png, "webp")
    assert media == "image/webp"
    with Image.open(io.BytesIO(webp)) as result:
        assert result.size == source.size
        for point in [(0, 0), (300, 150), (450, 150)]:
            assert result.getpixel(point) == source.convert("RGBA").getpixel(point)
    for fmt in ("jpg", "jpeg", "pdf"):
        data, media = main._convert_png_bytes(png, fmt)
        if fmt == "pdf":
            box = re.search(rb"/MediaBox\s*\[([^\]]+)\]", data)
            assert box is not None
            assert list(map(float, box[1].split())) == pytest.approx([0, 0, 144, 72], abs=0.01)
            # Pillow embeds the composited RGB raster as a JPEG stream.
            start, end = data.index(b"\xff\xd8"), data.index(b"\xff\xd9") + 2
            data = data[start:end]
        with Image.open(io.BytesIO(data)) as result:
            assert result.size == source.size
            assert result.mode == "RGB"
            assert result.getpixel((0, 0)) == (255, 255, 255)
            assert result.getpixel((450, 150)) == pytest.approx((127, 127, 127), abs=2)
            if fmt != "pdf":
                assert result.info["dpi"] == (300, 300)


def test_plot_pdf_size_without_resolution_metadata() -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (600, 300), "white").save(buf, format="PNG")
    pdf, _ = main._convert_png_bytes(buf.getvalue(), "pdf")
    box = re.search(rb"/MediaBox\s*\[([^\]]+)\]", pdf)
    assert list(map(float, box[1].split())) == [0, 0, 600, 300]


def _spy_on_qc_renders(monkeypatch) -> list[str]:
    """Record the output format of each real QC render without replacing it."""
    from app.services import notebook_qc
    from app.services.plot_export import plot_output_format

    formats: list[str] = []
    real = notebook_qc.render_qc

    def spy(*args, **kwargs):
        formats.append(plot_output_format.get())
        return real(*args, **kwargs)

    monkeypatch.setattr(notebook_qc, "render_qc", spy)
    return formats


def test_pdf_download_is_native_and_never_swapped_with_the_png_preview(qc_protein_data, monkeypatch) -> None:
    """PDF is drawn as a PDF by the real QC route, at the requested page size.

    Preview and download share one URL and differ only in `downloadFormat`, so
    alternating them must give each request its own format: a PNG preview never
    comes back as PDF bytes, and a PDF is never a re-encoded PNG. Embedded
    TrueType fonts and no image objects show the PDF is vector, and the page is
    the 12 x 8 cm canvas that was asked for.
    """
    from app.services.plot_export import plot_output_format

    formats = _spy_on_qc_renders(monkeypatch)
    size = {"widthCm": 12, "heightCm": 8}
    previews = []
    with TestClient(main.app) as client:
        for fmt in ("png", "pdf", "png", "pdf"):
            response = client.get("/api/plots/qc/protein/coverage.png", params={**size, "downloadFormat": fmt})
            assert response.status_code == 200, response.text[:200]
            # Drawn by the notebook renderer (its fallback adds a notice); a download gets no export.
            assert "x-copylot-notice" not in response.headers
            assert "x-copylot-notebook" not in response.headers
            if fmt == "png":
                assert response.headers["content-type"] == "image/png"
                assert response.content.startswith(b"\x89PNG")
                previews.append(response.content)
            else:
                assert response.headers["content-type"] == "application/pdf"
                assert response.content.startswith(b"%PDF-")
                assert b"/FontFile2" in response.content
                assert b"/Subtype /Image" not in response.content
                box = re.search(rb"/MediaBox\s*\[([^\]]+)\]", response.content)
                assert list(map(float, box[1].split())) == pytest.approx([0, 0, 12 / 2.54 * 72, 8 / 2.54 * 72])
    assert formats == ["png", "pdf", "png", "pdf"]
    assert previews[0] == previews[1]
    assert plot_output_format.get() == "png"


@pytest.mark.parametrize("plot", ["coverage", "boxplot", "cv", "intensity-histogram", "abundance"])
def test_svg_download_is_native_vector_and_served_as_svg(qc_protein_data, monkeypatch, plot) -> None:
    """SVG comes from the renderer, like PDF, and never from re-encoding a PNG.

    Converting the rendered raster would produce a file with the right
    extension and a bitmap inside it, which is the one thing nobody asks for
    SVG in order to get. So the format has to reach matplotlib before it draws
    and the body has to be marked `image/svg+xml` on the way out. The default
    correlation heatmap is left out: `matshow` is an image by construction.
    """
    from app.services.plot_export import plot_output_format

    formats = _spy_on_qc_renders(monkeypatch)
    with TestClient(main.app) as client:
        for fmt in ("png", "svg"):
            response = client.get(f"/api/plots/qc/protein/{plot}.png", params={"downloadFormat": fmt})
            assert response.status_code == 200, response.text[:200]
            # Drawn by the notebook renderer (its fallback adds a notice); a download gets no export.
            assert "x-copylot-notice" not in response.headers
            assert "x-copylot-notebook" not in response.headers
            if fmt == "png":
                assert response.headers["content-type"] == "image/png"
                assert response.content.startswith(b"\x89PNG")
            else:
                assert response.headers["content-type"] == "image/svg+xml"
                assert b"<svg" in response.content[:600]
                # A raster smuggled inside the vector file.
                assert b"<image" not in response.content
                assert b"data:image/png" not in response.content
    assert formats == ["png", "svg"]
    assert plot_output_format.get() == "png"


@pytest.mark.parametrize("fmt", ["svg", "pdf"])
def test_notebook_serializer_unrasterizes_artists_for_vector_downloads(fmt) -> None:
    """The QC routes save through the notebook module's own copy of `to_png_bytes`.

    No QC plot marks an artist as rasterized today, so this checks that copy
    directly: a rasterized scatter must still come out as vector paths.
    """
    from app.services.notebook_qc import _qc_module

    module = _qc_module("coverage")
    plt = module.get_plt()
    fig, ax = plt.subplots(figsize=(3.35, 2.36))
    ax.scatter([0, 1, 2], [1, 3, 2], rasterized=True)
    token = module.plot_output_format.set(fmt)
    try:
        content = bytes(module.to_png_bytes(fig, plt, dpi=150, tight=False))
    finally:
        module.plot_output_format.reset(token)
    if fmt == "svg":
        assert b"<svg" in content[:600]
        assert b"<image" not in content
    else:
        assert content.startswith(b"%PDF-")
        assert b"/Subtype /Image" not in content


def test_svg_is_never_traced_out_of_a_rendered_raster() -> None:
    """The raster converter must refuse rather than wrap pixels in an <image>."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, format="PNG")
    with pytest.raises(ValueError, match="never converted"):
        main._convert_png_bytes(buf.getvalue(), "svg")


def test_plot_figure_is_closed_when_serialization_fails(monkeypatch) -> None:
    import matplotlib.pyplot as plt
    from app.services.plot_export import to_png_bytes

    fig = plt.figure()
    monkeypatch.setattr(fig, "savefig", lambda *a, **k: (_ for _ in ()).throw(ValueError("synthetic")))
    with pytest.raises(ValueError, match="synthetic"):
        to_png_bytes(fig, plt)
    assert not plt.fignum_exists(fig.number)


def test_rendered_plot_keeps_physical_canvas_size_in_pdf() -> None:
    import matplotlib.pyplot as plt
    from PIL import Image
    from app.services.plot_export import to_png_bytes

    fig, ax = plt.subplots(figsize=(3.35, 2.36))
    fig._copylot_transparent_background = True
    ax.plot([0, 1, 2], [0, 2, 1])
    png = to_png_bytes(fig, plt, dpi=300, tight=False)
    with Image.open(io.BytesIO(png)) as source:
        width, height = source.size
        xdpi, ydpi = source.info["dpi"]
        assert source.getpixel((0, 0))[3] == 0
    pdf, _ = main._convert_png_bytes(png, "pdf")
    box = re.search(rb"/MediaBox\s*\[([^\]]+)\]", pdf)
    assert list(map(float, box[1].split())) == pytest.approx(
        [0, 0, width * 72 / xdpi, height * 72 / ydpi], abs=0.001
    )


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
    root = Path(__file__).resolve().parents[3]
    for filename in ("docker-compose.yml", "docker-compose.viewer.yml"):
        content = (root / filename).read_text(encoding="utf-8")
        assert "read_only: true" in content
        assert "mem_limit:" in content
        assert "cpus:" in content
        assert "tmpfs:" in content
