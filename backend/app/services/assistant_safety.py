"""What no model may touch, whatever its level or interface.

The assistant changes how results are shown and where the user is. It never
changes how the data behind them were produced: filtering, normalization,
imputation, transformation and the session-wide phosphosite localization
cutoff are the user's pipeline choices. Those settings are removed from the
view before any model or application shortcut sees it, refused again if an
action names one, and refused a third time in the browser
(frontend/src/lib/assistantControls.ts, PIPELINE_CONTROL). The pipeline pages
themselves register no assistant controls, and the only buttons the assistant
may press are canvas tile buttons, so no processing step can be run.

Native tool calling (assistant_tools.py) produces the same plan the JSON
planner produces and goes through the same checks; a tool cannot reach
anything a plan cannot.
"""
from __future__ import annotations

import re

from app.schemas.assistant import AssistantRequest

PIPELINE_CONTROL = re.compile(
    r"\b(?:normali[sz]\w*|imput\w*|filter\w*|transform\w*|localization probability|valid values?)\b", re.I)
REFUSAL = ("The assistant never changes how data are filtered, normalized, imputed or transformed, "
           "or the localization cutoff. Change those yourself on their pages. Nothing was changed.")


def is_pipeline_control(label: str) -> bool:
    return bool(PIPELINE_CONTROL.search(label or ""))


def without_pipeline(request: AssistantRequest) -> AssistantRequest:
    """The request with every pipeline setting removed from the view."""
    kept = [control for control in request.view.controls if not is_pipeline_control(control.label)]
    if len(kept) == len(request.view.controls):
        return request
    return request.model_copy(update={"view": request.view.model_copy(update={"controls": kept})})


def check_actions(request: AssistantRequest, actions) -> None:
    """Refuse any action that names a pipeline setting (defence in depth)."""
    labels = {control.id: control.label for control in request.view.controls}
    for action in actions:
        if getattr(action, "type", "") not in {"set_control", "search_options", "activate_control"}:
            continue  # opening a page changes nothing
        target = getattr(action, "target", "") or ""
        if is_pipeline_control(labels.get(target, "")) or is_pipeline_control(target):
            raise ValueError(REFUSAL)
