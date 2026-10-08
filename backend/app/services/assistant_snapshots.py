"""Bounded server-owned evidence for uploaded and explicitly executed results."""
from collections import OrderedDict
from copy import deepcopy
from secrets import token_urlsafe
from threading import RLock
from time import monotonic

from app.services.runtime_cache import runtime_cache_version
from app.services.session_context import get_session_id

_snapshots: OrderedDict = OrderedDict()
_lock = RLock()


def store_snapshot(data: dict) -> str:
    import json
    if len(json.dumps(data, default=str)) > 32000:
        return ""
    token = token_urlsafe(24)
    with _lock:
        _snapshots[token] = (get_session_id(), runtime_cache_version(), monotonic(), deepcopy(data))
        while len(_snapshots) > 64:
            _snapshots.popitem(last=False)
    return token


def read_snapshot(token: str) -> dict:
    with _lock:
        item = _snapshots.get(token)
        if not item or item[0] != get_session_id() or item[1] != runtime_cache_version() or monotonic() - item[2] > 3600:
            raise ValueError("Result evidence expired or is unavailable; render or run the result again.")
        return deepcopy(item[3])
