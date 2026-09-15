"""Conservative request narrowing; ambiguous requests retain the full catalogue."""
import re
import json


def canvas_add_request(message: str) -> dict | None:
    """Recognize only complete, add-only requests; leave mixed intent to the planner."""
    match = re.fullmatch(
        r"(?:please\s+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:add|create)\s+"
        r"(?P<count>\d+|a|an|one|two|three|four|five|six|seven|eight)\s+"
        r"(?P<type>protein boxplot|protein lineplot|volcano control|control volcano|volcano|go enrichment|ora)"
        r"(?:\s+(?:plot|tile)s?)?(?:\s+(?:to|on) (?:this |the )?canvas)?[.!?]?",
        message.strip(), re.IGNORECASE,
    )
    if not match:
        return None
    number = match['count'].lower()
    count = int(number) if number.isdigit() else {
        'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4,
        'five': 5, 'six': 6, 'seven': 7, 'eight': 8,
    }[number]
    if not 1 <= count <= 8:
        raise ValueError("Add between one and eight canvas tiles at a time.")
    kind = {'protein boxplot': 'proteinBoxplot', 'protein lineplot': 'proteinLineplot',
            'volcano': 'volcano', 'volcano control': 'volcanoControl', 'control volcano': 'volcanoControl',
            'go enrichment': 'oraList', 'ora': 'oraList'}[match['type'].lower()]
    return {'type': kind, 'count': count}


def ui_actions_schema(view: dict, max_actions: int) -> dict:
    schema = {"type": "array", "maxItems": max_actions}
    if not max_actions:
        return {**schema, "items": {}, "maxItems": 0}
    setters, transitions = [], []

    def action(kind: str, targets: list[str], value: dict) -> dict:
        return {"type": "object", "properties": {
            "type": {"type": "string", "enum": [kind]},
            "target": {"type": "string", "enum": targets}, "value": value},
            "required": ["type", "target", "value"], "additionalProperties": False}

    destinations = [key for key in view.get("destinations", {}) if key != view.get("module")]
    if destinations:
        transitions.append(action("navigate", destinations, {"type": "string", "enum": [""]}))
    if not view.get("advancedOptions"):
        transitions.append(action("advanced_options", [""], {"type": "boolean", "enum": [True]}))
    for control in view.get("controls", []):
        target, kind = [control["id"]], control["type"]
        if kind == "button":
            if view.get("module") == "analysis.canvas":
                transitions.append(action("activate_control", target, {"type": "string", "enum": [""]}))
            continue
        value = {"type": "string", "maxLength": 1000}
        options = control.get("options", [])
        complete_options = control.get("optionCount", 0) <= len(options)
        if kind == "checkbox":
            value = {"type": "boolean"}
        elif kind == "color":
            value["pattern"] = "^#[0-9a-fA-F]{6}$"
        elif kind == "number":
            value["pattern"] = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
            value["description"] = f"Numeric string; minimum {control.get('min', 'unbounded')}, maximum {control.get('max', 'unbounded')}."
        elif kind in {"select", "multiple"}:
            transitions.append(action("search_options", target, {"type": "string", "minLength": 1, "maxLength": 120}))
            item = {"type": "string"}
            if options and complete_options:
                item["enum"] = options
            if kind == "multiple":
                value = {"type": "array", "items": item}
                if not options and complete_options:
                    value["maxItems"] = 0
            elif not options and complete_options:
                continue
            else:
                value.update(item)
        setters.append(action("set_control", target, value))
    choices = [{"maxItems": 0}]
    def grouped(items):
        groups = {}
        for item in items:
            properties = item["properties"]
            key = json.dumps([properties["type"], properties["value"]], sort_keys=True)
            if key in groups:
                groups[key]["properties"]["target"]["enum"].extend(properties["target"]["enum"])
            else:
                groups[key] = item
        return list(groups.values())
    if setters:
        choices.append({"minItems": 1, "maxItems": max_actions, "items": {"anyOf": grouped(setters)}})
    if transitions:
        choices.append({"minItems": 1, "maxItems": 1, "items": {"anyOf": grouped(transitions)}})
    return {**schema, "anyOf": choices}


def refers_to_visible_result(question: str) -> bool:
    if re.search(r"\b(?:standalone|separate|other|another)\b|\bstats\.ora\b", question, re.I):
        return False
    return bool(re.search(
        r"\b(?:this|that|current|visible|displayed|completed)\s+"
        r"(?:(?:completed|ORA|enrichment|canvas)\s+){0,2}(?:ORA|enrichment|result|plot|tile|canvas)\b",
        question, re.I))


def canvas_explanation_request(question: str) -> bool:
    match = re.fullmatch(r"(.+?)\s+(?:and|then)\s+(?:then\s+)?(?:explain|describe|review)\s+"
                        r"(?:it|them|the results|the plots|the canvas)[.!?]?", question.strip(), re.I)
    return bool(match and planner_tasks(match[1]) == ["canvas_focus", "clarify"])


def planner_tasks(question: str) -> list[str]:
    science = ["current_plot", "qc_review", "entity_lookup", "project_state", "help"]
    text = question.strip().lower()
    if re.search(r"\bmore significant\b", text):
        return ["clarify"]
    if canvas_explanation_request(question):
        return ["canvas_focus", "clarify"]
    # Advice/questions must not accidentally become interface mutations.
    explicit_following_action = re.search(
        r"(?:[;.]\s*|\b(?:and|then)\s+)(?:then\s+)?(?:please\s+)?"
        r"(?:show|open|select|rotate|rename|recolor|colour|color|hide|bold|resize|set|change)\b", text)
    if re.match(r"^(?:what|why|how|explain|describe|review|assess|is\b|are\b|does\b)\b", text) and not explicit_following_action:
        return [*science, "clarify"]
    if (re.match(r"^(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:give|show|build|create|focus|everything for|all (?:the )?plots for)\b", text)
            and re.search(r"\b(?:canvas|everything|all (?:the )?plots)\b", text)
            and re.search(r"\b(?:protein|phosphoprotein|phosphosite)s?\b", text)
            and not re.search(r"\b(?:explain|describe|review|why|assess|do not|don't|never)\b", text)):
        return ["canvas_focus", "clarify"]
    if re.match(r"^(?:please\s+)?(?:open|show|select|add|remove|rotate|rename|recolor|colour|color|hide|bold|resize|öffne)\b", text) and not re.search(r"\b(?:explain|describe|review|why|assess|compare|erkläre)\b", text):
        return ["ui", "clarify"]
    return [*science, "ui", "clarify"]


def requests_canvas_guidance(question: str) -> bool:
    return ("ui" not in planner_tasks(question)
            and bool(re.search(r"\bcanvas\b", question, re.I))
            and bool(re.search(r"\b(?:show|build|create|add|focus|open|use|set up)\b", question, re.I))
            and bool(re.match(r"^(?:please\s+)?(?:(?:explain|describe)\s+how|how\s+(?:do|can|to))\b", question.strip(), re.I)))


def response_guidance(style: str) -> str:
    return {
        "concise": "Answer directly in one or two short paragraphs. Include only the values needed to answer; no routine headings.",
        "explanation": "Explain the relevant method or meaning in plain language, defining necessary terms. Use short paragraphs and evidence-backed examples when available.",
        "review": "Give an overall assessment, then the most important supporting observations and limitations. Distinguish observations from possible explanations; do not list every available field.",
    }[style]


def requests_advanced_styling(question: str) -> bool:
    if "ui" not in planner_tasks(question) or re.search(r"\b(?:do not|don't|never|without)\b", question, re.I):
        return False
    return bool(re.match(r"^(?:please\s+)?(?:rotate|rename|recolor|colour|color|hide|bold|resize|set|change|make|use|remove|open|show)\b", question, re.I)
                and re.search(r"\b(?:rotate|rotation|border|font|bold|rename|tick labels?|colou?r)\b", question, re.I))
