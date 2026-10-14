"""Native tool calling for Advanced models.

A large model on a server that supports tool calls (llama.cpp with a tool
template, Ollama with a tools-capable model, OpenAI) gets the assistant as
functions instead of one JSON form: it can read results, preview styles and
look at presets as often as it needs (within a bound), then finish with one
finishing call.

What it cannot do is anything the JSON planner cannot do. Every finishing
call is turned into the same AssistantPlan the JSON planner returns, built
from the same planner turn (same advertised controls, same enums), and then
runs through the same validation in scientific_assistant: registered controls
only, scope checks, confirmation for scientific view changes, no pipeline
settings (assistant_safety), no processing buttons. The read-only tools read
the request's own view and the application's computed evidence; none of them
changes anything.
"""
from __future__ import annotations

import copy
import json

TOOL_NOTE = """You are called with tools. Read-only tools (read_results, preview_styles, preset_details,
find_settings) change nothing; use them when they help, then finish with exactly ONE finishing tool:
apply_styles (visual changes), change_view (navigate or change a listed view control), answer (explain
or look something up) or ask_user (clarify). Do not write prose outside tool calls. The JSON-schema
wording above describes the same fields the finishing tools take.
Answering: read_results gives the application's calculated results (kind=results) or its method
description (kind=method) for the open plot or another module (so never tell the user you cannot read
the plot's values: read them); a question about named proteins or sites
in a comparison ("are ANXA1 and ANXA3 affected?", "sites on RPS6 that go down?") is answered from the
comparison's result with lookup=the names, not one boxplot at a time; "up in A but not in B" across two
contrasts is one read with conditions=A and versus=B (the app does the set algebra; enrich=true for the pathways of
the A-only set); "does re-expression revert it" is conditions=KO vs parental, versus=rescue vs parental (or vs KO),
lookup=the names, and the direction words in the result are the answer; module workflow.overview describes the
order of the whole analysis across pages and where downloads are (you never press them; say where
they are). After reading, finish with answer and
write the reply yourself in text: plain, friendly language matched to how the user asks (a beginner gets
what the plot is and how to read it; an expert gets the number or the formula first). Use only what you
read: every number, name and colour you write is checked against it and a sentence that does not match is
removed. Round sensibly; do not invent values, units, tests, significance or causes; tentative
interpretation says may/might/could; no headings, at most a short list. Name pages as the user sees
them (the destination labels), never by module keys such as qc.cv. Describe the processing as the
results state it (normalization, imputation, filters): never assume a step happened. Without text the
application writes the answer.
When the user wants to see a plot that is not open, or to understand one with their data ("show me",
"how does X look", "I don't understand the PCA"), open its page with change_view and
explainAfterChanges=true; the explanation then uses that page's actual results. Questions about a
method in general need no navigation.
If another module's results say incomplete_parameters or need selections the user named (a contrast,
test, threshold or entity), its page has to be opened: finish with change_view navigating there and
explainAfterChanges=true, or, when change_view is not offered, with answer naming that module; the
application opens the page and the user's selections are set there in the next step. Do not ask which
contrast to use when the question names it. With two conditions, the one the question treats as the
treatment ("when GRK is present", "we knocked in GRK") is condition 1, so log2FC reads treatment minus
control. Background knowledge about a protein, kinase or pathway may be given in a sentence or two,
introduced as general knowledge ("In general, MARCKS ..."), never as a finding of this dataset, and without
figures or identifiers of its own (every number is checked against the data and removed otherwise).
Across contrasts, significant in A but not B is a threshold-based set description, not a test of their
difference. Direction words describe point estimates only; never present them as proof of rescue or equivalence."""

READ_ONLY = {"read_results", "preview_styles", "preset_details", "find_settings"}


def _inline(schema: dict, defs: dict) -> dict:
    """The schema with every $ref replaced by its definition (tool parameters stand alone)."""
    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {key: walk(value) for key, value in node.items() if key != "title"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node
    return walk(schema)


def _loose(schema: dict) -> dict:
    """The schema without its enums: a preview is validated by the application anyway, and the
    element and property lists (10 sample names of 90 characters each) are already in apply_styles."""
    def walk(node):
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items() if key != "enum"}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node
    return walk(copy.deepcopy(schema))


def _function(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": required, "additionalProperties": False}}}


def definitions(schema: dict, tasks: list[str], presets: list[str], modules: list[str] | None = None) -> list[dict]:
    """The tools for one planner turn, derived from that turn's plan schema."""
    defs = schema.get("$defs", {})
    props = schema["properties"]
    tools = [
        _function("read_results", "Calculated results (kind=results) or the method description (kind=method) of the "
                  "open plot (module empty) or of another module (read-only). lookup: protein, gene or site names "
                  "(comma separated; a site as 'GENE S123') whose own rows of a comparison result you need, "
                  "wherever they rank, including rows the test could not use. conditions: read another contrast "
                  "('C5 vs C0') with the open plot's settings without changing the page. versus: a second contrast "
                  "('dQ5 vs dQ0'); the app then reports which significant rows of the first are also, not, or "
                  "oppositely significant in the second, and, when both share a reference condition (or the second "
                  "is measured from the first's treatment), whether each row moved back toward that reference. "
                  "enrich=true adds GO over-representation of the first-only and shared gene sets. Supply organism "
                  "from the user's stated species or the visible settings; ask if it is unknown.",
                  {"module": {"type": "string", "enum": ["", *(modules or [])]},
                   "kind": {"type": "string", "enum": ["results", "method"]},
                   "lookup": {"type": "string", "maxLength": 300},
                   "conditions": {"type": "string", "maxLength": 130},
                   "versus": {"type": "string", "maxLength": 130},
                   "enrich": {"type": "boolean"},
                   "organism": {"type": "string", "enum": ["human", "mouse"]}}, []),
        _function("preview_styles", "Check style edits without applying them: what each would change and any problem. "
                  "Same edit form as apply_styles.",
                  {"styles": _loose(_inline(props["styles"], defs))}, ["styles"]),
        _function("find_settings", "Visual settings whose names contain a word, with current values (read-only).",
                  {"word": {"type": "string", "maxLength": 60}}, ["word"]),
    ]
    if presets:
        tools.append(_function("preset_details", "The exact edits a journal/publication preset makes on this plot.",
                               {"preset": {"type": "string", "enum": presets}}, ["preset"]))
    if "ui" in tasks:
        tools.append(_function(
            "apply_styles", "Finish: apply visual changes (and/or a preset). The application validates every edit.",
            {"styles": _inline(props["styles"], defs),
             "preset": _inline(props.get("preset", {"type": "string", "enum": [""]}), defs),
             "designNote": _inline(props.get("designNote", {"type": "string", "maxLength": 0}), defs),
             "explainAfterChanges": {"type": "boolean"}}, ["styles"]))
        actions = _inline(props.get("actions", {"type": "array", "maxItems": 0}), defs)
        if actions.get("maxItems", 0):
            tools.append(_function(
                "change_view", "Finish: navigate, search options or change listed non-visual view controls. "
                "Scientific view changes are confirmed by the user.",
                {"actions": actions, "explainAfterChanges": {"type": "boolean"}}, ["actions"]))
    answer_tasks = [task for task in tasks if task not in {"ui", "clarify", "lookup", "canvas_focus", "plot_controls"}]
    if not answer_tasks and "ui" in tasks:
        # A view request can still end in an explanation of what was opened ("show me the
        # PCA, do my groups separate?"): without this tool the model invented one (2026-10-13).
        answer_tasks = ["current_plot"]
    if answer_tasks:
        tools.append(_function(
            "answer", "Finish: answer from the application's evidence (explain the plot, review QC, look up an entity, "
            "describe the project, or a method question).",
            {"task": {"type": "string", "enum": answer_tasks},
             "module": _inline(props.get("module", {"type": "string"}), defs),
             "modules": _inline(props.get("modules", {"type": "array", "maxItems": 0}), defs),
             "query": {"type": "string", "maxLength": 200},
             "responseStyle": {"type": "string", "enum": ["concise", "explanation", "review"]},
             "text": {"type": "string", "maxLength": 3000,
                      "description": "Your reply, written only from what read_results returned; empty lets the "
                                     "application write it."}}, ["task"]))
    tools.append(_function(
        "ask_user", "Finish: ask one precise question instead of guessing.",
        {"clarification": _inline(props["clarification"], defs),
         "question": _inline(props.get("question", {"type": "string", "maxLength": 0}), defs)}, ["clarification"]))
    return tools


def plan_from_call(name: str, arguments: dict) -> dict:
    """The AssistantPlan payload a finishing call stands for."""
    if name == "apply_styles":
        return {"task": "ui", "styles": arguments.get("styles") or [], "preset": arguments.get("preset") or "",
                "designNote": arguments.get("designNote") or "",
                "explainAfterChanges": bool(arguments.get("explainAfterChanges"))}
    if name == "change_view":
        return {"task": "ui", "actions": arguments.get("actions") or [],
                "explainAfterChanges": bool(arguments.get("explainAfterChanges"))}
    if name == "answer":
        plan = {"task": arguments.get("task") or "current_plot", "module": arguments.get("module") or "",
                "query": arguments.get("query") or "", "responseStyle": arguments.get("responseStyle") or "concise"}
        if arguments.get("modules"):
            plan["modules"] = arguments["modules"]
        return plan
    if name == "ask_user":
        return {"task": "clarify", "clarification": arguments.get("clarification") or "request",
                "question": arguments.get("question") or ""}
    raise ValueError(f"Unknown tool {name!r}.")


def parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("The model's tool arguments were not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("The model's tool arguments were not an object.")
    return value
