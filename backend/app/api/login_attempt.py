"""The shared error handling of the tool and viewer login routes."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException, Request

from app.services.request_security import LoginRateLimit

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


def login_attempt(
    request: Request,
    limit: LoginRateLimit,
    *,
    bucket: str,
    access: str,
    failure: str,
    authenticate: Callable[[], T],
) -> T:
    """Rate-limit one login, run it, and answer failures the same way everywhere.

    A wrong credential (ValueError) is a 401 with its message. A missing access
    file is a 500 that asks for the administrator. Anything else is ours to fix:
    logged with its traceback and answered with one fixed sentence (`failure`).
    """
    limit.enforce(request, bucket=bucket)
    try:
        result = authenticate()
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.exception("%s access configuration is unavailable", access)
        raise HTTPException(
            status_code=500,
            detail=f"{access} access configuration is unavailable. Contact the administrator.",
        ) from exc
    except Exception as exc:
        LOGGER.exception(failure)
        raise HTTPException(status_code=500, detail=f"{failure}.") from exc
    limit.clear(request, bucket=bucket)
    return result
