"""The phosphosite localization-probability cutoff, one value per session.

Phosphosites whose localization probability (`PTM_localization`) is below the
cutoff are left out of every phosphosite analysis -- QC, completeness,
statistics, comparison, single protein, the Phospho-specific plots and the
Kinase Library export -- so every module looks at the same set of sites. Sites
without a probability are left out as soon as the cutoff is above zero: they
cannot be shown to pass it. At the default of 0 every site is kept.

The cutoff selects which sites are analysed; it does not change how the data
were processed. Normalization, the valid-value filter and imputation run on all
sites when the annotation is generated, and the cutoff is applied where a
phosphosite matrix is read (`functions.select_matrix`,
`phospho_tools._phospho_context`, `completeness_tools._frame_and_meta`). The
phosphosite-to-phosphoprotein collapse takes its own cutoff, recorded with the
phosphoprotein table.
"""
from __future__ import annotations

import math

from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id

DEFAULT_LOCALIZATION_CUTOFF = 0.0

_CUTOFF_SESSIONS: dict[str, float] = {}


def validate_localization_cutoff(value: object) -> float:
    try:
        cutoff = float(value)
    except (TypeError, ValueError):
        raise ValueError("The localization probability cutoff must be a number between 0 and 1.") from None
    if not math.isfinite(cutoff) or not 0.0 <= cutoff <= 1.0:
        raise ValueError("The localization probability cutoff must be between 0 and 1.")
    return cutoff


def get_localization_cutoff() -> float:
    return _CUTOFF_SESSIONS.get(get_session_id(), DEFAULT_LOCALIZATION_CUTOFF)


def set_localization_cutoff(value: object) -> float:
    cutoff = validate_localization_cutoff(value)
    if cutoff != get_localization_cutoff():
        _CUTOFF_SESSIONS[get_session_id()] = cutoff
        invalidate_runtime_cache("phospho:localization-cutoff")
    return cutoff


def reset_localization_cutoff(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _CUTOFF_SESSIONS.clear()
    else:
        _CUTOFF_SESSIONS.pop(get_session_id(), None)
    invalidate_runtime_cache("phospho:localization-cutoff-reset", all_sessions=all_sessions)


def snapshot_localization_cutoff_session_state() -> float | None:
    return _CUTOFF_SESSIONS.get(get_session_id())


def restore_localization_cutoff_session_state(snapshot: float | None) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _CUTOFF_SESSIONS.pop(session_id, None)
    else:
        _CUTOFF_SESSIONS[session_id] = snapshot
    invalidate_runtime_cache("phospho:localization-cutoff-restored")


def apply_session_localization_cutoff(frame):
    """`frame` without the sites below this session's cutoff (see module note)."""
    from app.services.functions import filter_localization

    return filter_localization(frame, get_localization_cutoff())


def localization_cutoff_description(cutoff: float | None = None) -> str:
    """One sentence for reports and provenance."""
    value = get_localization_cutoff() if cutoff is None else float(cutoff)
    if value <= 0:
        return "All phosphosites are included, whatever their localization probability."
    return (
        f"Only phosphosites with a localization probability of at least {value:.2f} are included; "
        "sites without a localization probability are excluded."
    )
