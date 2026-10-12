"""What every plot route shares: the error contract, the response shapes and the snapshot tables."""
from __future__ import annotations

import logging
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import ValidationError

from app.services.plot_export import RENDER_LOCK
from app.services.functions import (
    parse_selection_list,
)


LOGGER = logging.getLogger(__name__)


def validation_messages(error: ValidationError) -> str:
    """The sentences a request model raised, without pydantic's framing."""
    messages = []
    for item in error.errors():
        message = str(item.get("msg", "")).strip()
        for prefix in ("Value error, ", "Assertion failed, "):
            if message.startswith(prefix):
                message = message[len(prefix):]
        if message and message not in messages:
            messages.append(message)
    return " ".join(messages) or "The request is not valid."


@contextmanager
def plot_errors(what: str, *, optional_dependency: bool = False):
    """Turn a renderer's failure into the answer the page expects.

    A `ValueError` is the renderer refusing the request -- an empty selection, a
    threshold out of range, a comparison that cannot be formed -- so its message
    *is* the answer and goes out as a 400. Anything else is ours to fix: it is
    logged with its traceback and answered with one fixed sentence, because an
    exception string can carry a file path or a column of someone's data.

    `optional_dependency` marks the plots that need a package the base install
    may not have. Those services raise `ModuleNotFoundError` with a message that
    names the package and how to install it, which is actionable and discloses
    nothing about the host, so that one message is passed through.

    Fifty-nine routes wrote these six lines out by hand.
    """
    try:
        # Plots are drawn one at a time (see RENDER_LOCK).
        with RENDER_LOCK:
            yield
    except ValidationError as e:
        # A pydantic ValidationError is a ValueError whose str() is a dump of
        # the model, the input values and a docs URL. The model's own messages
        # are the answer; the rest is not for the page.
        raise HTTPException(status_code=400, detail=validation_messages(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        if optional_dependency:
            LOGGER.exception("Optional dependency missing")
            raise HTTPException(status_code=500, detail=str(e)) from e
        LOGGER.exception(what)
        raise HTTPException(status_code=500, detail=f"{what}.") from e
    except Exception as e:
        LOGGER.exception(what)
        raise HTTPException(status_code=500, detail=f"{what}.") from e



def plot_media_type(content: bytes) -> str:
    """Name the format the renderer actually wrote, rather than assuming PNG.

    PDF and SVG are produced by matplotlib itself when the request asks for
    them, so the body arriving here is not always a raster. Serving an SVG as
    ``image/png`` makes the browser save a file it then refuses to open.
    """
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content[:64].lstrip().startswith((b"<?xml", b"<svg")):
        return "image/svg+xml"
    return "image/png"


def png_response(content: bytes) -> Response:
    from urllib.parse import quote

    notice = getattr(content, "notice", "")
    return Response(
        content=content,
        media_type=plot_media_type(content),
        headers={
            **({"X-CoPYlot-Notice": quote(notice)} if notice else {}),
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            # PNG is already compressed; the gzip middleware leaves a response
            # that names its encoding alone, whatever its content type.
            "Content-Encoding": "identity",
        },
    )


def table_rows(df) -> dict[str, list[dict[str, object]]]:
    # Categorical columns reject replacement values that are not registered
    # categories (including the empty string). Convert to ordinary Python
    # objects before replacing missing values for JSON serialization.
    safe_df = df.astype(object).where(df.notna(), "")
    return {"rows": safe_df.to_dict(orient="records")}




def csv_values(raw: str) -> list[str]:
    return parse_selection_list(raw)


def snapshot_table(kind: str, plot: str, snapshot: str, **settings):
    import io
    import pandas as pd
    from app.services.notebook_snapshots import snapshots
    from app.services.session_context import get_session_id

    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook snapshot unavailable; render the plot again.") from exc
    if (recipe.provenance.get("kind") != kind or recipe.provenance.get("plot") != plot
            or any(recipe.settings.get(key) != value for key, value in settings.items())):
        raise HTTPException(status_code=409, detail="The table settings do not match the rendered plot.")
    if 'table.json' in recipe.resources:
        import json
        return {'rows': json.loads(recipe.resources['table.json'])}
    return table_rows(pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"])))
