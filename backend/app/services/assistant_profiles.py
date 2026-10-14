"""How much of the assistant's toolbox each model gets.

Three levels, named after the planner profiles they replace:

* compact  ("Basic"): one small step at a time, a styling menu narrowed to the
  words in the question, application-written answer sentences. Journal styles
  and "make it look better" are applied by the application, not designed by
  the model. This is what kept 4B models useful (local/AI_REVIEW.md, rounds
  14-35): less to choose from, fewer ways to fail.
* standard ("Standard"): the same contract with more history, more evidence and
  the full styling menu when the question names no element.
* extended ("Advanced"): large batches of visual changes, the whole styling
  menu with current values, plot-part descriptions, journal presets, free
  design within colour-blind-safe palettes, read-only lookups, its own written
  answers (numbers checked by the application) and, where the model reads
  images, the rendered plot.

The rules are the same at every level: only the application's registered
controls are used; visual settings apply directly, anything that changes a
result needs the user's approval; data, processing settings and code are never
touched. A level only decides how much the model is trusted to plan at once.

Classification, most specific first:
1. the user's choice in the AI settings (``assistantLevel``);
2. the operator's ``COPYLOT_AI_MODEL_LEVELS`` (``model=basic|standard|advanced``);
3. models observed in this project's real conversations (``OBSERVED_MODELS``);
4. inference from family, generation, size, context and quantization;
5. a model with no recognisable family and no known size stays Basic.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

LEVELS = {"basic": "compact", "standard": "standard", "advanced": "extended"}
LEVEL_NAMES = {"compact": "Basic", "standard": "Standard", "extended": "Advanced"}


@dataclass(frozen=True)
class Tier:
    history: int              # earlier messages the planner sees
    history_chars: int        # characters kept from each
    evidence: int             # characters of evidence per tool
    max_actions: int          # non-styling actions per step
    setters_per_batch: int    # control changes applied in one step
    action_budget: int        # changes per user request (receipts)
    output_tokens: int        # reply budget without reasoning
    reasoning_tokens: int     # extra budget for models that think first
    narrowed_styling: bool    # styling menu narrowed to the named elements
    presets: bool             # journal presets offered to the model
    lookups: int              # read-only lookup rounds per step
    prose_answers: bool       # writes its own answer (numbers checked)
    free_design: bool         # may choose a design when asked to improve one
    plot_image: bool          # receives the rendered plot when it reads images


TIERS = {
    "compact": Tier(2, 600, 3500, 1, 4, 8, 1024, 3072, True, False, 0, False, False, False),
    "standard": Tier(4, 1000, 5000, 2, 4, 8, 2048, 4096, True, True, 0, False, False, False),
    "extended": Tier(6, 2000, 12000, 4, 30, 40, 4096, 6144, False, True, 2, True, True, True),
}
# (history, characters, evidence budget, actions) -- the planner's original view.
PROFILES = {name: (tier.history, tier.history_chars, tier.evidence, tier.max_actions) for name, tier in TIERS.items()}

# Real conversations reviewed in local/AI_REVIEW.md (rounds 1-35, 2026-09-22)
# and the glm5 request replays of 2026-10-07. Exact names, any local provider.
OBSERVED_MODELS: dict[str, tuple[str, str]] = {
    "qwen3.5:4b": ("compact", "Rounds 14, 17, 21, 25, 27, 30 and 34: single requests work; compound styling "
                   "repeatedly failed through malformed values and omissions."),
    "qwen3.5:9b": ("standard", "Rounds 1-13, 18, 22-24 and 29: reliable navigation, answers and styling; "
                   "compound requests occasionally failed."),
    "ministral-3:8b": ("standard", "Rounds 15, 20, 26 and 31-35: completed compound styling and canvas requests."),
    "gemma4:12b": ("standard", "Rounds 16, 19 and 28: clean compound styling and correct canvas answers."),
    "glm5": ("extended", "2026-10-07 replays: correct multi-condition plans and a coherent restyle once it had "
             "room to reason (320.8B parameters, 131k context)."),
}

# Kept for the reviewed-qualification path: (provider, exact model, quantization)
# -> (profile, evaluation report). Only real evaluations belong here.
TESTED_MODELS: dict[tuple[str, str, str], tuple[str, str]] = {}
RELATED_MODELS: dict[tuple[str, str, str], tuple[str, str, str]] = {}

# Families by inference. `legacy` families are an older generation: they need
# about twice the size for the same level. Sizes are total parameters (B) for
# names that carry none.
_FAMILIES: list[tuple[str, dict]] = [
    (r"glm-?4\.[5-9]-?air", {"reasoning": True, "size": 106}),
    (r"glm-?(?:4\.[5-9]|[5-9])", {"reasoning": True, "size": 355}),
    (r"glm", {}),
    (r"kimi|moonshot", {"size": 1000}),
    (r"minimax", {"size": 456}),
    # Below 600B a "deepseek-r1" is one of the distilled Qwen 2.5 / Llama 3 models.
    (r"deepseek-?r1", {"reasoning": True, "size": 671, "distilled_below": 600}),
    (r"deepseek-?(?:v3|v4|reasoner)", {"reasoning": True, "size": 671}),
    (r"deepseek-?(?:chat|coder-v2)", {"size": 236}),
    (r"deepseek", {"legacy": True}),
    (r"qwq", {"reasoning": True, "size": 32}),
    (r"qwen3", {}),
    (r"qwen2\.5", {"legacy": True}),
    (r"qwen", {"legacy": True}),
    (r"gpt-oss", {"reasoning": True, "size": 20}),
    (r"llama-?4", {"size": 109}),
    (r"llama-?3\.[3-9]", {}),
    (r"llama", {"legacy": True}),
    (r"gemma-?[3-9]", {}),
    (r"gemma", {"legacy": True}),
    (r"magistral", {"reasoning": True, "size": 24}),
    (r"(?:mistral|devstral)-?(?:small|medium)", {"size": 24}),
    (r"mistral-?large", {"size": 123}),
    (r"ministral|mistral-?(?:nemo|3)", {}),
    (r"mistral|mixtral|codestral|pixtral", {"legacy": True}),
    (r"phi-?4.*reason", {"reasoning": True}),
    (r"phi-?4", {"size": 14}),
    (r"phi", {"legacy": True}),
    (r"command-?(?:a|r-?plus)", {"size": 104}),
    (r"command", {"legacy": True, "size": 35}),
    (r"granite-?[4-9]", {}),
    (r"granite|olmo|nemotron|exaone|internlm|hermes|aya|falcon|yi|solar|jamba|dbrx|smollm|openchat|"
     r"zephyr|vicuna|wizardlm|orca|starling|tinyllama|stablelm|nous|dolphin|baichuan|chatglm", {"legacy": True}),
]
_CLOUD_FRONTIER = re.compile(r"^(?:gpt-?(?:4o|4\.1|5(?:\.\d)?)(?!.*(?:mini|nano))|o[134](?!.*mini)|chatgpt|"
                             r"claude.*(?:opus|sonnet|fable|mythos)|claude-(?:opus|sonnet)|claude-?haiku-?(?:4[.-]5|[5-9])|"
                             r"gemini.*pro|grok-?[3-9](?!.*mini))", re.I)
_CLOUD_SMALL = re.compile(r"nano|lite|8b", re.I)
_REASONING_NAME = re.compile(r"(?:^|[-_.:/])(?:o[134]|gpt-?5|qwq|r1|thinking|think|reason\w*|magistral|gpt-oss)"
                             r"(?:$|[-_.:/\d])|gemini-?(?:2\.5|[3-9])|glm-?(?:4\.[5-9]|[5-9])", re.I)


def normalise(model: str) -> str:
    """The model's own name: no registry path, ':latest' or quantization suffix."""
    name = str(model or "").strip().lower()
    name = name.rsplit("/", 1)[-1]
    name = re.sub(r":latest$", "", name)
    return name


def _family(name: str) -> dict | None:
    for pattern, traits in _FAMILIES:
        if re.match(pattern, name):
            return traits
    return None


def reasoning_model(provider: str, model: str) -> bool:
    """Models that think before answering; their thinking uses the reply budget."""
    name = normalise(model)
    traits = _family(name) or {}
    if provider == "ollama" and str(os.getenv("COPYLOT_OLLAMA_THINK", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return False  # Ollama is asked not to think unless the operator enables it.
    return bool(traits.get("reasoning") or _REASONING_NAME.search(name))


def _operator_level(model: str) -> str | None:
    for item in str(os.getenv("COPYLOT_AI_MODEL_LEVELS", "")).split(","):
        name, _, level = item.partition("=")
        if name.strip() and normalise(name) == normalise(model) and level.strip().lower() in LEVELS:
            return LEVELS[level.strip().lower()]
    return None


def _demote(profile: str) -> str:
    return {"extended": "standard", "standard": "compact"}.get(profile, "compact")


def classify_model(provider, model, parameters=None, context=None, tools=None, quantization=""):
    """(profile, assessment, reason). `tools` is accepted for compatibility; the
    assistant uses JSON plans, not provider tool calling, so it does not matter."""
    configured = _operator_level(model)
    if configured:
        return configured, "configured", f"Set to {LEVEL_NAMES[configured]} by COPYLOT_AI_MODEL_LEVELS"
    tested = TESTED_MODELS.get((provider, model, quantization))
    if tested and tested[0] in PROFILES:
        return tested[0], "tested", f"Qualified by {tested[1]}"
    name = normalise(model)
    if provider in ("ollama", "openai_compatible") and name in OBSERVED_MODELS:
        profile, evidence = OBSERVED_MODELS[name]
        if context is not None and context < 8192:
            profile = "compact"
        return profile, "observed", f"Observed in this project's real conversations: {evidence}"
    traits = _family(name)
    size = parameters if parameters is not None else (traits or {}).get("size")
    if provider not in ("ollama", "openai_compatible"):
        # Cloud models: the provider's flagship tiers plan large batches well;
        # their small variants get the standard toolbox.
        profile = "extended" if _CLOUD_FRONTIER.match(name) else "compact" if _CLOUD_SMALL.search(name) else "standard"
        reason = f"Inferred from the provider's model line ({name})"
    elif traits is None and size is None:
        return "compact", "unknown", "Unrecognized model with no reported size; the Basic toolbox is the safe start"
    else:
        legacy = bool((traits or {}).get("legacy")) or (
            size is not None and size < (traits or {}).get("distilled_below", 0))
        lower, upper = (14, 65) if legacy else (6, 60)
        profile = "compact" if size is None or size < lower else "standard" if size < upper else "extended"
        if traits is None and profile == "extended":
            profile = "standard"  # an unknown fine-tune is not trusted with the whole toolbox
        generation = "older-generation " if legacy else ""
        known = f"{size:g}B parameters" if size is not None else "unknown size"
        reason = (f"Inferred from the {generation}model family and {known}" if traits is not None
                  else f"Unrecognized family; inferred from its reported {known}")
    if re.search(r"(?:^|[_-])i?q[123](?:[_-]|$)", str(quantization).lower()):
        profile = _demote(profile)
        reason += "; strong quantization lowers the level"
    if context is not None and context < 8192:
        profile, reason = "compact", reason + "; context below 8192 tokens"
    elif context is not None and context < 16384 and profile == "extended":
        profile, reason = "standard", reason + "; context below 16384 tokens limits it to Standard"
    return profile, "inferred", reason


def output_tokens(profile: str, reasoning: bool, context: int | None = None) -> int:
    """Reply budget: the level's answer room plus room to think, within the window."""
    tier = TIERS.get(profile, TIERS["compact"])
    budget = tier.output_tokens + (tier.reasoning_tokens if reasoning else 0)
    if context:
        budget = min(budget, max(1024, context // 3))
    return budget


def scaled_budgets(profile: str, context: int | None) -> tuple[int, int, int]:
    """(history messages, characters each, evidence characters per source).

    Advanced models with a large window get room in proportion: glm5's 131k
    tokens should not be read through the window sized for an 8k model."""
    tier = TIERS.get(profile, TIERS["compact"])
    if profile != "extended" or not context:
        return tier.history, tier.history_chars, tier.evidence
    if context >= 65536:
        return 12, 6000, 40000
    if context >= 32768:
        return 8, 4000, 24000
    return tier.history, tier.history_chars, tier.evidence


def input_limit(profile: str, context: int | None) -> int:
    """Characters one assistant prompt may carry (24,000 unless an Advanced model has the window)."""
    if profile == "extended" and context and context >= 32768:
        return max(24_000, min(200_000, int(context * 3.3 * 0.5)))
    return 24_000
