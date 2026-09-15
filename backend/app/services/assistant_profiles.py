"""Execution estimates are not measured scientific qualifications."""
import re

# Only reviewed real-model runs belong here: (provider, exact model, quantization)
# -> (profile, evaluation report). Never populate this with inferred results.
TESTED_MODELS: dict[tuple[str, str, str], tuple[str, str]] = {}
# Explicit, reviewed similarity links; family resemblance alone never creates a tested label.
RELATED_MODELS: dict[tuple[str, str, str], tuple[str, str, str]] = {}
PROFILES = {"compact": (2, 600, 3500, 1), "standard": (4, 1000, 5000, 2), "extended": (4, 1200, 7000, 4)}


def classify_model(provider, model, parameters=None, context=None, tools=None, quantization=""):
    tested = TESTED_MODELS.get((provider, model, quantization))
    if tested and tested[0] in PROFILES:
        return tested[0], "tested", f"Qualified by {tested[1]}"
    related = TESTED_MODELS.get(RELATED_MODELS.get((provider, model, quantization)))
    if related and related[0] in PROFILES:
        profile = related[0]
        if tools is False or (context is not None and context < 8192):
            profile = "compact"
        return profile, "inferred", f"Estimated from a reviewed related model in {related[1]}; this model is not tested"
    name = model.lower()
    family = re.match(r"^(?:llama|qwen|gemma|phi|mistral|ministral|mixtral|deepseek|gpt|o[134]|claude|gemini)(?:[.\d:_-]|$)", name)
    if not family:
        return "compact", "unknown", "Unrecognized model; conservative single-step execution"
    profile = "compact"
    if parameters is not None and parameters >= 12:
        profile = "standard"
    elif provider != "ollama" and not any(word in name for word in ("nano", "mini", "flash", "haiku")):
        profile = "standard"
    if tools is False or (context is not None and context < 8192) or re.search(r"(?:^|[_-])q[23](?:[_-]|$)", quantization.lower()):
        profile = "compact"
    return profile, "inferred", "Provisional family/size/context estimate; not a real-model qualification"
