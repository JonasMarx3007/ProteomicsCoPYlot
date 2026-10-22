import os
import sys
import io
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from app.app_version import APP_VERSION
from app.services.viewer_policy import auth_route, viewer_request_allowed
from app.services.html_security import GENERATED_HTML_CSP
from app.services.shared_plotly import PLOTLY_ASSET_HEADER, SHARED_PLOTLY_HEADER, plotly_asset_path, share_plotly
from app.services.plot_export import notebook_capture_allowed, notebook_unavailable, plot_notices, plot_output_format

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from anyio import to_thread
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes_annotations import router as annotations_router
from app.api.routes_data_tools import router as data_tools_router
from app.api.routes_datasets import router as datasets_router
from app.api.routes_external import router as external_router
from app.api.routes_chat import router as chat_router
from app.api.routes_plots import router as plots_router
from app.api.routes_peptide import router as peptide_router
from app.api.routes_stats import router as stats_router
from app.api.routes_analysis import router as analysis_router
from app.api.routes_summary import router as summary_router
from app.api.routes_restore import router as restore_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_tool_auth import router as tool_auth_router
from app.api.routes_viewer_auth import router as viewer_auth_router
from app.services.session_context import (
    get_browser_session_id,
    get_session_id,
    new_session_id,
    normalize_session_id,
    reset_session_id,
    session_cookie_name,
    session_cookie_path,
    TabSessionMiddleware,
    session_cookie_secure,
    session_header_name,
    session_isolation_enabled,
    set_session_id,
)
from app.services.session_cleanup import expire_idle_session, touch_and_cleanup_sessions
from app.services.session_operation_gate import session_operation_scope
from app.services.temp_cleanup import cleanup_managed_temp_files
from app.services.request_security import local_path_access_allowed, peer_is_trusted_proxy
from app.services.tool_access import (
    tool_access_enabled,
    tool_session_authenticated,
    validate_tool_access_configuration,
)
from app.services.viewer_bootstrap import (
    bootstrap_current_viewer_session,
    bootstrap_viewer_mode_if_enabled,
    viewer_mode_enabled,
)

from app.services.viewer_portal import (
    ensure_viewer_session_bootstrapped,
    validate_viewer_portal_configuration,
    viewer_portal_enabled,
    viewer_session_authenticated,
)
from app.services.workload_manager import (
    ProviderWorkloadMiddleware,
    HeavyWorkloadBusyError,
    heavy_workload_scope,
    is_heavy_request,
    sync_thread_worker_limit,
)
from app.services.plot_limits import PlotSizeValidationError, validate_plot_request
from app.services.env_settings import env_flag

LOGGER = logging.getLogger(__name__)
_DEFAULT_PLOT_CONVERSION_MAX_BYTES = 128 * 1024 * 1024


def _plot_conversion_max_bytes() -> int:
    raw = str(os.getenv("COPYLOT_PLOT_CONVERSION_MAX_BYTES", "")).strip()
    try:
        return max(1, int(raw)) if raw else _DEFAULT_PLOT_CONVERSION_MAX_BYTES
    except ValueError:
        return _DEFAULT_PLOT_CONVERSION_MAX_BYTES


_AUTH_PROTECTED_RUNTIME = env_flag("COPYLOT_TOOL_ACCESS_ENABLED") or env_flag("COPYLOT_VIEWER_PORTAL_ENABLED")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    configuration_error = _authentication_configuration_error()
    if configuration_error:
        raise RuntimeError(configuration_error)
    cleanup_managed_temp_files()
    to_thread.current_default_thread_limiter().total_tokens = sync_thread_worker_limit()
    bootstrap_viewer_mode_if_enabled()
    yield


app = FastAPI(
    title="Proteomics CoPYlot API",
    version=APP_VERSION,
    docs_url=None if _AUTH_PROTECTED_RUNTIME else "/docs",
    redoc_url=None if _AUTH_PROTECTED_RUNTIME else "/redoc",
    openapi_url=None if _AUTH_PROTECTED_RUNTIME else "/openapi.json",
    lifespan=_lifespan,
)

@app.exception_handler(RequestValidationError)
async def safe_chat_validation(request: Request, exc: RequestValidationError):
    if "/api/chat/" in request.url.path:
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": error["loc"], "type": error["type"], "msg": "Invalid assistant request value."}
            for error in exc.errors()
        ]})
    return await request_validation_exception_handler(request, exc)


# Formats matplotlib writes itself. The renderer is told the format before it
# draws, so the response body already is that format and nothing is re-encoded
# afterwards -- which is the only way to keep a vector export vector.
_NATIVE_DOWNLOAD_FORMATS = {"pdf", "svg"}
_SUPPORTED_DOWNLOAD_FORMATS = {"png", "jpg", "jpeg", "webp", "pdf", "svg"}
_REMOTE_LOCAL_PATH_EXACT: set[tuple[str, str]] = {
    ("POST", "/api/datasets/table-path"),
    ("POST", "/api/datasets/peptide-path"),
}


def _authentication_configuration_error(*, validate_credentials: bool = True) -> str | None:
    tool_auth = env_flag("COPYLOT_TOOL_ACCESS_ENABLED")
    viewer_auth = env_flag("COPYLOT_VIEWER_PORTAL_ENABLED")
    if tool_auth and viewer_auth:
        return "Tool access and viewer portal authentication cannot be enabled in the same process."
    if (tool_auth or viewer_auth) and not session_isolation_enabled():
        return (
            "Password-protected deployments require COPYLOT_SESSION_ISOLATION=1. "
            "The API is unavailable until the deployment is configured safely."
        )
    if viewer_auth and not viewer_mode_enabled():
        return (
            "COPYLOT_VIEWER_PORTAL_ENABLED=1 requires COPYLOT_VIEWER_MODE=1. "
            "The API is unavailable until the deployment is configured safely."
        )
    if validate_credentials:
        try:
            if tool_auth:
                validate_tool_access_configuration()
            elif viewer_auth:
                validate_viewer_portal_configuration()
        except (FileNotFoundError, OSError, ValueError) as exc:
            return f"Invalid authentication configuration: {exc}"
    return None


def _auth_route(path: str) -> bool:
    return auth_route(path)


def _viewer_request_denied(request: Request) -> bool:
    return not viewer_request_allowed(request.method, request.url.path)


def _remote_local_path_request_denied(request: Request) -> bool:
    operation = (request.method.upper(), request.url.path)
    return operation in _REMOTE_LOCAL_PATH_EXACT and not local_path_access_allowed(request)


def _request_policy_response(request: Request) -> JSONResponse | None:
    path = request.url.path
    if not path.startswith("/api/"):
        return None
    if viewer_mode_enabled() and _viewer_request_denied(request):
        return JSONResponse(
            status_code=403,
            content={"detail": "This operation is disabled in read-only viewer mode."},
        )
    if _remote_local_path_request_denied(request):
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Server-local path operations are unavailable to remote clients and are "
                    "disabled by default in password-protected mode. Use a file-upload "
                    "endpoint instead."
                )
            },
        )
    return None


def _convert_png_bytes(content: bytes, target_format: str) -> tuple[bytes, str]:
    fmt = target_format.strip().lower()
    if fmt == "png":
        return content, "image/png"
    if fmt not in _SUPPORTED_DOWNLOAD_FORMATS:
        raise ValueError(
            f"Unsupported download format '{target_format}'. Choose one of: "
            "png, jpg, jpeg, webp, pdf, svg."
        )
    if fmt == "svg":
        # Tracing a raster back into SVG would wrap the pixels in an <image>
        # tag and call it a vector. SVG only ever comes from the renderer.
        raise ValueError("SVG is written by the renderer and is never converted from a raster image.")

    from PIL import Image

    with Image.open(io.BytesIO(content)) as source:
        dpi = source.info.get("dpi", (72, 72))
        image = source.convert("RGBA")
    if fmt in {"jpg", "jpeg", "pdf"}:
        # Raster exports without alpha use white, including antialiased edges.
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image).convert("RGB")

    out = io.BytesIO()
    if fmt in {"jpg", "jpeg"}:
        image.save(out, format="JPEG", quality=95, dpi=dpi)
        media_type = "image/jpeg"
    elif fmt == "webp":
        image.save(out, format="WEBP", lossless=True)
        media_type = "image/webp"
    else:
        image.save(out, format="PDF", dpi=dpi)
        media_type = "application/pdf"
    return out.getvalue(), media_type


def _resolve_frontend_dist() -> Path | None:
    candidates: list[Path] = []

    env_dist = os.getenv("COPYLOT_FRONTEND_DIST", "").strip()
    if env_dist:
        candidates.append(Path(env_dist))

    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            project_root / "frontend" / "dist",
            project_root / "frontend_dist",
        ]
    )

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "frontend_dist")

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend_dist")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if (resolved / "index.html").is_file():
            return resolved

    return None

def cors_origins() -> list[str]:
    """Cross-origin callers allowed to send credentials. Empty unless configured.

    Neither shipped path needs this. The packaged app serves the built bundle from
    the same origin as the API, and the dev launchers run Vite with a `/api` proxy
    (`frontend/vite.config.ts`), so the browser only ever talks to port 5173 and
    the request is same-origin there too.

    The Vite dev origins used to be hardcoded here with `allow_credentials=True`,
    and they shipped in the pip package and the desktop bundle. On a default
    install that let any page served from `localhost:5173` -- the most common local
    dev port -- make credentialed calls to the API and read the responses, which
    chained with the server-local path endpoints into arbitrary file read.
    """
    raw = str(os.getenv("COPYLOT_CORS_ORIGINS", "")).strip()
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


_CORS_ORIGINS = cors_origins()


# Loopback names only. "0.0.0.0" is a bind address, never a Host header a client
# sends, and "testserver" is the FastAPI TestClient default -- the test suite adds
# it through COPYLOT_ALLOWED_HOSTS rather than shipping it to users.
_DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def allowed_hosts() -> set[str]:
    """Host header values this server will answer to.

    Set COPYLOT_ALLOWED_HOSTS (comma separated) when serving under a real
    hostname; the entry may include a port or omit it.
    """
    extra = str(os.getenv("COPYLOT_ALLOWED_HOSTS", "")).strip()
    hosts = set(_DEFAULT_ALLOWED_HOSTS)
    for item in extra.split(","):
        cleaned = item.strip().lower()
        if cleaned:
            hosts.add(cleaned)
    return hosts


def _host_is_allowed(header: str) -> bool:
    host = str(header or "").strip().lower()
    if not host:
        # A missing Host header cannot be attributed to a rebound name, and
        # HTTP/1.0 clients omit it legitimately.
        return True
    allowed = allowed_hosts()
    if host in allowed:
        return True
    # Strip the port, taking care not to split an unbracketed IPv6 literal.
    if host.startswith("["):
        bare = host.split("]", 1)[0] + "]"
    elif host.count(":") == 1:
        bare = host.rsplit(":", 1)[0]
    else:
        bare = host
    return bare in allowed


async def host_allowlist_middleware(request: Request, call_next):
    """Refuse requests carrying an unrecognised Host header.

    The loopback peer check cannot see a DNS-rebinding attack: the victim's own
    browser makes the request, so it genuinely originates from 127.0.0.1 and the
    request is same-origin, which also makes CORS irrelevant. The attacker's
    hostname is the one thing that survives rebinding, so it is what gets checked.
    """
    if not _host_is_allowed(request.headers.get("host", "")):
        return JSONResponse(
            status_code=400,
            content={"detail": "Request rejected: unrecognised Host header."},
        )
    return await call_next(request)


def _sets_session_cookie(response, cookie_name: str) -> bool:
    """Whether the route already handed the client a session cookie.

    Authentication rotates the session id and the login route sets the rotated
    one itself. The middleware resolved its own id before the route ran, so
    without this check it appends a second cookie carrying the pre-rotation id;
    last-wins leaves the browser holding the unauthenticated one and login
    silently fails for every cookie-based client.
    """
    prefix = f"{cookie_name}=".encode("latin-1")
    return any(
        key.lower() == b"set-cookie" and value.lstrip().startswith(prefix)
        for key, value in response.raw_headers
    )


# Requests that change a session's datasets, annotations or settings. They take
# the session's gate exclusively, so two of them never interleave and no read
# sees a half-made change. Every PUT, PATCH and DELETE counts as well.
_SESSION_WRITE_POSTS = frozenset({
    "/api/annotations/generate",
    "/api/annotations/normalize",
    "/api/annotations/metadata/upload",
    "/api/annotations/phosprot/aggregate",
    "/api/annotations/phosprot/upload",
    "/api/data-tools/imputation/run",
    "/api/data-tools/id-translation/run",
    "/api/data-tools/phospho-localization-cutoff",
    "/api/datasets/upload",
    "/api/datasets/table-path",
    "/api/datasets/peptide-path",
    "/api/datasets/peptide-file",
    "/api/datasets/packages/create",
    "/api/datasets/packages/rename",
    "/api/datasets/active",
    "/api/datasets/metadata/profiles/create",
    "/api/datasets/metadata/profiles/rename",
    "/api/datasets/metadata/profiles/active",
    "/api/peptide/metadata/generate",
    "/api/restore/import",
    "/api/restore/browser-session-reset",
})
_SESSION_WRITE_PREFIXES = ("/api/data-tools/condition-colors/",)


def session_gate_mode(method: str, path: str) -> str | None:
    """'exclusive' for a change to session data, 'shared' for a read, None for no gate.

    AI-provider calls take no gate: an assistant answer can take minutes, and a
    reader holding the gate that long would make every change in the session wait.
    """
    path = path.rstrip("/") or "/"
    if path.startswith("/api/chat/"):
        return None
    method = method.upper()
    if method in {"PUT", "PATCH", "DELETE"}:
        return "exclusive"
    if method == "POST" and (path in _SESSION_WRITE_POSTS or path.startswith(_SESSION_WRITE_PREFIXES)):
        return "exclusive"
    return "shared"


async def session_scope_middleware(request: Request, call_next):
    configuration_error = _authentication_configuration_error(validate_credentials=False)
    if configuration_error:
        return JSONResponse(status_code=503, content={"detail": configuration_error})

    if not session_isolation_enabled():
        cookie_name = session_cookie_name()
        header_name = session_header_name()
        raw_cookie = str(request.cookies.get(cookie_name, "")).strip()
        raw_header = str(request.headers.get(header_name, "")).strip()
        resolved = normalize_session_id(raw_cookie or raw_header or new_session_id())
        should_set_cookie = raw_cookie != resolved
        token = set_session_id(resolved)
        try:
            policy_response = _request_policy_response(request)
            if policy_response is not None:
                response = policy_response
            else:
                mode = session_gate_mode(request.method, request.url.path)
                if mode is None:
                    response = await call_next(request)
                else:
                    async with session_operation_scope("global", exclusive=mode == "exclusive"):
                        response = await call_next(request)
        finally:
            reset_session_id(token)
        if should_set_cookie:
            response.set_cookie(
                key=cookie_name,
                value=resolved,
                httponly=True,
                secure=session_cookie_secure(),
                samesite="lax",
                path=session_cookie_path(),
            )
        return response

    cookie_name = session_cookie_name()
    header_name = session_header_name()
    raw_cookie = str(request.cookies.get(cookie_name, "")).strip()
    raw_header = str(request.headers.get(header_name, "")).strip()
    resolved = normalize_session_id(raw_cookie or raw_header or new_session_id())
    effective = resolved

    token = set_session_id(resolved)
    try:
        path = request.url.path
        protected_auth = tool_access_enabled() or viewer_portal_enabled()
        if protected_auth:
            expire_idle_session(resolved)
        else:
            touch_and_cleanup_sessions(resolved)
        if (
            path.startswith("/api/")
            and path != "/api/health"
            and not _auth_route(path)
        ):
            if tool_access_enabled():
                if not tool_session_authenticated():
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Tool password required."},
                    )
            elif viewer_portal_enabled():
                if not viewer_session_authenticated():
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Viewer password required."},
                    )
                try:
                    # Loading a project reads and processes files: off the event loop.
                    await to_thread.run_sync(lambda: ensure_viewer_session_bootstrapped(force_reload=False))
                except FileNotFoundError as exc:
                    LOGGER.exception("Viewer project configuration was not found")
                    return JSONResponse(
                        status_code=500,
                        content={"detail": "Viewer project configuration is unavailable."},
                    )
                except Exception as exc:
                    LOGGER.exception("Failed to initialize viewer project")
                    return JSONResponse(
                        status_code=500,
                        content={"detail": "Failed to initialize viewer project."},
                    )
            elif viewer_mode_enabled():
                try:
                    await to_thread.run_sync(lambda: bootstrap_current_viewer_session(force_reload=False))
                except FileNotFoundError as exc:
                    LOGGER.exception("Viewer configuration was not found")
                    return JSONResponse(
                        status_code=500,
                        content={"detail": "Viewer configuration is unavailable."},
                    )
                except Exception as exc:
                    LOGGER.exception("Failed to initialize viewer session")
                    return JSONResponse(
                        status_code=500,
                        content={"detail": "Failed to initialize viewer session."},
                    )
            policy_response = _request_policy_response(request)
            if policy_response is not None:
                return policy_response
        mode = session_gate_mode(request.method, path)
        if mode is None:
            response = await call_next(request)
        else:
            async with session_operation_scope(resolved, exclusive=mode == "exclusive"):
                response = await call_next(request)
        effective = get_browser_session_id()
        if (
            tool_access_enabled() and tool_session_authenticated()
        ) or (
            viewer_portal_enabled() and viewer_session_authenticated()
        ):
            touch_and_cleanup_sessions(resolved)
    finally:
        reset_session_id(token)

    if effective != raw_cookie and not _sets_session_cookie(response, cookie_name):
        response.set_cookie(
            key=cookie_name,
            value=effective,
            httponly=True,
            secure=session_cookie_secure(),
            samesite="lax",
            path=session_cookie_path(),
        )
    return response


async def heavy_workload_middleware(request: Request, call_next):
    try:
        validate_plot_request(request)
    except PlotSizeValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if not is_heavy_request(request.method, request.url.path):
        return await call_next(request)
    # Runs inside the session middleware, so the request's session is known and
    # an unauthenticated request never reaches the queue.
    try:
        async with heavy_workload_scope(get_session_id()):
            return await call_next(request)
    except HeavyWorkloadBusyError as exc:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
            headers={"Retry-After": "2"},
        )


def _request_is_https(request: Request) -> bool:
    """TLS terminated here, or at a trusted reverse proxy that says so."""
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client and request.client.host else ""
    return (
        peer_is_trusted_proxy(peer)
        and str(request.headers.get("x-forwarded-proto", "")).split(",", 1)[0].strip().lower() == "https"
    )


async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if request.url.path.startswith("/api/plots/") and response.headers.get(
        "content-type", ""
    ).lower().startswith("text/html"):
        # Also contain HTML opened directly, outside the frontend iframe.
        response.headers.setdefault(
            "Content-Security-Policy", GENERATED_HTML_CSP + "; sandbox allow-scripts allow-downloads"
        )
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if _request_is_https(request):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    if request.url.path.startswith("/api/") and "immutable" not in response.headers.get("cache-control", ""):
        # Nothing this API returns is safely cacheable, except a versioned asset. Every response is a
        # function of the session's current matrices, and those change under the
        # same URL: re-filtering or re-imputing rewrites every number without
        # moving an endpoint. The plot bodies have always said `no-store`; the
        # JSON tables beside them carry the same numbers and said nothing, so a
        # table could be answered from a cache while the plot next to it was
        # re-rendered. Auth responses additionally must never be stored at all.
        response.headers["Cache-Control"] = "no-store"
    return response


async def plot_download_format_middleware(request: Request, call_next):
    native_format = "png"
    if request.method == "GET" and request.url.path.startswith("/api/plots/"):
        asked = request.query_params.get("downloadFormat", "").strip().lower()
        if asked and asked not in _SUPPORTED_DOWNLOAD_FORMATS:
            return JSONResponse(status_code=400, content={"detail": "Unsupported download format. Choose png, jpg, jpeg, webp, pdf or svg."})
        if asked in _NATIVE_DOWNLOAD_FORMATS:
            native_format = asked
    token = plot_output_format.set(native_format)
    capture_token = notebook_capture_allowed.set(
        not request.query_params.get("downloadFormat", "").strip())
    unavailable: dict = {}
    unavailable_token = notebook_unavailable.set(unavailable)
    notices: list = []
    notices_token = plot_notices.set(notices)
    try:
        response = await call_next(request)
    finally:
        plot_notices.reset(notices_token)
        notebook_unavailable.reset(unavailable_token)
        notebook_capture_allowed.reset(capture_token)
        plot_output_format.reset(token)
    if unavailable.get("reason") and "x-copylot-notebook" not in response.headers:
        from urllib.parse import quote
        response.headers["X-CoPYlot-Notebook-Unavailable"] = quote(unavailable["reason"])
    if notices:
        from urllib.parse import quote, unquote
        existing = unquote(response.headers.get("X-CoPYlot-Notice", ""))
        response.headers["X-CoPYlot-Notice"] = quote(" ".join(filter(None, [*notices, existing])))
    if request.method != "GET":
        return response
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if not request.url.path.startswith("/api/plots/"):
        return response

    media_type = response.headers.get("content-type", "").lower()
    if "text/html" in media_type:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        if request.headers.get(SHARED_PLOTLY_HEADER) == "1":
            # The app's own display: plotly.js comes from the cached shared asset.
            body = bytearray()
            async for chunk in response.body_iterator:
                body.extend(chunk)
            text = bytes(body).decode("utf-8")
            shared = share_plotly(text)
            headers = {key: value for key, value in response.headers.items() if key.lower() != "content-length"}
            if shared is not None:
                headers[PLOTLY_ASSET_HEADER] = plotly_asset_path()
            return Response(content=shared if shared is not None else text, status_code=response.status_code,
                            media_type="text/html", headers=headers)

    requested_format = request.query_params.get("downloadFormat", "").strip().lower()
    if not requested_format or requested_format == "png":
        return response

    if "image/png" not in media_type:
        return response

    body = bytearray()
    conversion_limit = _plot_conversion_max_bytes()
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is not None:
        async for chunk in body_iterator:
            body.extend(chunk)
            if len(body) > conversion_limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Plot is too large to convert safely."},
                )
    else:
        body.extend(getattr(response, "body", b""))
        if len(body) > conversion_limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "Plot is too large to convert safely."},
            )

    try:
        converted, converted_media_type = _convert_png_bytes(bytes(body), requested_format)
    except Exception:
        LOGGER.exception("Failed to convert plot download")
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to convert plot download."},
        )

    passthrough_headers: dict[str, str] = {}
    for key, value in response.headers.items():
        lowered = key.lower()
        if lowered in {"content-type", "content-length"}:
            continue
        passthrough_headers[key] = value
    return Response(
        content=converted,
        status_code=response.status_code,
        media_type=converted_media_type,
        headers=passthrough_headers,
    )

# Middleware order, outermost first (Starlette runs the last one added first):
#   1. Host allowlist: a rebinding request is refused before anything else runs.
#   1b. Gzip of the finished response.
#   2. Tab sessions: rewrites /api/tabs/<id>/api/... before any path is read.
#   3. Security headers: on every response, including refusals further in.
#   4. CORS (only when COPYLOT_CORS_ORIGINS is set).
#   5. Session and authentication; viewer bootstrap; the session's operation gate.
#   6. Heavy-work admission, then AI-provider admission: both per authenticated
#      session, so a fair share is counted per session, not per client address.
#   7. Plot download format and notices, closest to the route.
app.add_middleware(BaseHTTPMiddleware, dispatch=plot_download_format_middleware)
app.add_middleware(ProviderWorkloadMiddleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=heavy_workload_middleware)
app.add_middleware(BaseHTTPMiddleware, dispatch=session_scope_middleware)
if _CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-CoPYlot-Notice", "X-CoPYlot-Notebook", "X-CoPYlot-Notebook-Unavailable"],
    )
app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers_middleware)
app.add_middleware(TabSessionMiddleware)
# Compresses JSON tables and HTML for clients that accept gzip; images and ZIP
# downloads are skipped. Volcano and ANOVA results ship whole matrices, which
# shrink several-fold.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
app.add_middleware(BaseHTTPMiddleware, dispatch=host_allowlist_middleware)

app.include_router(datasets_router)
app.include_router(annotations_router)
app.include_router(data_tools_router)
app.include_router(chat_router)
app.include_router(stats_router)
app.include_router(analysis_router)
app.include_router(peptide_router)
app.include_router(plots_router)
app.include_router(external_router)
app.include_router(summary_router)
app.include_router(restore_router)
app.include_router(runtime_router)
app.include_router(tool_auth_router)
app.include_router(viewer_auth_router)

_FRONTEND_DIST = _resolve_frontend_dist()


@app.get("/api/health")
async def health():
    return {
        "message": "Backend is running",
        "frontendAvailable": _FRONTEND_DIST is not None,
    }


if _FRONTEND_DIST is None:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "Backend is running"}
else:
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
