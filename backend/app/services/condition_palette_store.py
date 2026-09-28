from __future__ import annotations

import colorsys
import re

from app.schemas.annotation import AnnotationKind
from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

_BASE_CONDITION_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#aec7e8",
    "#ffbb78",
    "#98df8a",
    "#ff9896",
    "#c5b0d5",
    "#c49c94",
    "#f7b6d2",
    "#c7c7c7",
    "#dbdb8d",
    "#9edae5",
]


def _empty_palette_state() -> dict[AnnotationKind, dict[str, str]]:
    return {
        "protein": {},
        "phospho": {},
        "phosprot": {},
    }


_PALETTE_SESSIONS: dict[str, dict[AnnotationKind, dict[str, str]]] = {}


def _session_palettes() -> dict[AnnotationKind, dict[str, str]]:
    session_id = get_session_id()
    if session_id not in _PALETTE_SESSIONS:
        _PALETTE_SESSIONS[session_id] = _empty_palette_state()
    return _PALETTE_SESSIONS[session_id]


def _normalize_conditions(conditions: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for condition in conditions:
        normalized = str(condition).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _generated_color_hex(index: int) -> str:
    if index < len(_BASE_CONDITION_COLORS):
        return _BASE_CONDITION_COLORS[index].upper()
    hue = (index * 0.618033988749895) % 1.0
    saturation = 0.62 if index % 2 == 0 else 0.78
    value = 0.88 if (index // 2) % 2 == 0 else 0.72
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"#{int(red * 255):02X}{int(green * 255):02X}{int(blue * 255):02X}"


def _normalize_hex(value: str) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    if not HEX_COLOR_RE.match(text):
        return None
    return text.upper()


def get_condition_palette(kind: AnnotationKind) -> dict[str, str]:
    return dict(_session_palettes().get(kind, {}))


def set_condition_palette(kind: AnnotationKind, palette: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for condition, color in palette.items():
        condition_name = str(condition).strip()
        if not condition_name:
            continue
        hex_color = _normalize_hex(color)
        if hex_color is None:
            continue
        normalized[condition_name] = hex_color
    _session_palettes()[kind] = normalized
    invalidate_runtime_cache(f"palette:{kind}:updated")
    return dict(normalized)


def build_condition_color_map(kind: AnnotationKind, conditions: list[str]) -> dict[str, str]:
    ordered = _normalize_conditions(conditions)
    overrides = _session_palettes().get(kind, {})
    result: dict[str, str] = {}
    for index, condition in enumerate(ordered):
        override = _normalize_hex(overrides.get(condition, ""))
        result[condition] = override if override is not None else _generated_color_hex(index)
    return result


def reset_condition_palettes(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _PALETTE_SESSIONS.clear()
    else:
        _PALETTE_SESSIONS.pop(get_session_id(), None)
    invalidate_runtime_cache("palette:reset-all", all_sessions=all_sessions)


def snapshot_condition_palette_session_state():
    """Detach-safe reference used before the session entry is atomically replaced."""
    return _PALETTE_SESSIONS.get(get_session_id())


def restore_condition_palette_session_state(snapshot) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _PALETTE_SESSIONS.pop(session_id, None)
    else:
        _PALETTE_SESSIONS[session_id] = snapshot
    invalidate_runtime_cache("palette:transaction-restored")
