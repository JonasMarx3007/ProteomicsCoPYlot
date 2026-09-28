import io
import json

import pytest
from app.schemas.assistant import AssistantPlan, AssistantRequest, Evidence, ScientificAnswer
from app.services import chat_tools, scientific_assistant as assistant
from app.services.assistant_narrative import answer_catalogue, assemble_answer
from assistant_support import _control, _view


class _Capability:
    def __init__(self, tier, size, window=None):
        self.contextTier, self.parameterCountB, self.contextWindow = tier, size, window


def _advanced_panel(count=90):
    controls = [_control("rot", "X axis / X tick label rotation"), _control("top", "Frame and grid / Axis frame / Top", "checkbox", True)]
    for index in range(count):
        controls.append(_control(f"c{index}", f"Boxes and their points / Marker {index} outline width (0 = none)", value="0.4"))
    controls.append(_control("site", "Protein / Site", "select", "K17", options=[f"K{i}" for i in range(40)], optionCount=80))
    return {"module": "singleProtein.boxplot", "mode": {"kind": "phospho"}, "advancedOptions": True, "controls": controls}


@pytest.fixture
def ollama_limits(monkeypatch):
    monkeypatch.setattr(chat_tools, "_NUM_CTX_IN_USE", {})
    monkeypatch.setattr(chat_tools, "_resolve_ollama_base_url", lambda *args: "http://ollama")
    window = {"value": None}

    class Capability:
        @property
        def contextWindow(self):
            return window["value"]
    monkeypatch.setattr(chat_tools, "model_capability", lambda *args: Capability())
    monkeypatch.delenv("COPYLOT_OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("COPYLOT_OLLAMA_MAX_CTX", raising=False)
    return window


def test_ordinary_requests_keep_the_8192_window(ollama_limits):
    assert chat_tools._ollama_num_ctx("small", None, 3000) == 8192


def test_full_generation_allowance_has_context_headroom(ollama_limits):
    assert chat_tools.ASSISTANT_OUTPUT_RESERVE >= 1024
    assert chat_tools._ollama_num_ctx("small", None, 7200) == 12288


def test_a_larger_request_gets_a_larger_window_in_4096_steps_and_keeps_it(ollama_limits):
    assert chat_tools._ollama_num_ctx("small", None, 8000) == 12288
    # Never shrinks back for the same model: every new num_ctx is a model reload.
    assert chat_tools._ollama_num_ctx("small", None, 1000) == 12288
    assert chat_tools._ollama_num_ctx("other", None, 1000) == 8192


def test_the_window_never_exceeds_the_owner_ceiling_or_the_model(ollama_limits, monkeypatch):
    with pytest.raises(chat_tools.AssistantContextExhausted, match="context is limited to 16384"):
        chat_tools._ollama_num_ctx("small", None, 16000)
    monkeypatch.setenv("COPYLOT_OLLAMA_MAX_CTX", "32768")
    assert chat_tools._ollama_num_ctx("big", None, 16000) == 20480
    ollama_limits["value"] = 8192  # the model's own trained window wins
    with pytest.raises(chat_tools.AssistantContextExhausted):
        chat_tools._ollama_num_ctx("tiny-window", None, 9000)


def test_a_reply_that_fills_the_window_is_named_as_such(ollama_limits, monkeypatch):
    from app.schemas.chat import ChatRequest
    sent = {}

    def open_request(payload, *, messages, output_schema=None, num_ctx=None):
        sent["num_ctx"] = num_ctx
        body = {"message": {"content": '{"task":"ui","actions":[{"ty'}, "done_reason": "length",
                "prompt_eval_count": 8164, "eval_count": 28}
        return "synthetic", io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(chat_tools, "_open_ollama_request", open_request)
    monkeypatch.setattr(chat_tools, "_resolve_model", lambda *args: "synthetic")
    with pytest.raises(chat_tools.AssistantContextExhausted, match="filled the model's 8192-token context window"):
        chat_tools.assistant_completion(ChatRequest(message="x", model="synthetic"), "instruction", "{}")
    assert sent["num_ctx"] == 8192


def test_small_models_see_the_relevant_controls_within_the_preferred_budget(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_prompt_budget", lambda *args: (4000, 15000))
    request = AssistantRequest(message="Rotate the x-axis tick labels to 30 degrees and remove the top border.",
                               view=_advanced_panel())
    call = assistant.plan_request(request)
    keys = {(row["element"], row["property"]) for row in call.inputs["styling"]}
    assert ("x ticks", "rotation") in keys and ("frame", "top") in keys
    assert all("protein" not in element for element, _ in keys)
    assert chat_tools.estimate_tokens(call.system, call.payload) <= 4000
    assert not call.control_targets


def test_larger_models_also_omit_unrelated_cosmetic_controls(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("standard", 4, 1000))
    monkeypatch.setattr(assistant, "assistant_prompt_budget", lambda *args: (4000, 15000))
    request = AssistantRequest(message="Rotate the x-axis tick labels to 30 degrees.", view=_advanced_panel())
    call = assistant.plan_request(request)
    assert not call.control_targets
    assert any(row["element"] == "x ticks" for row in call.inputs["styling"])
    assert not any("marker" in row["property"] for row in call.inputs["styling"])


def test_ambiguous_styling_is_not_offered_as_arbitrary_numbered_controls(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    view = {"module": "singleProtein.boxplot", "advancedOptions": True, "controls": [
        _control("f", "Frame and grid / Color", "color", "#000000"), _control("g", "Frame and grid / Color", "color", "#b0b0b0")]}
    call = assistant._build_planner_call(AssistantRequest(message="Make the grid grey", view=view))
    assert call.inputs["styling"] == []


@pytest.mark.parametrize("tier,size,expected", [
    ("standard", 30.5, 12288),
    ("standard", 35.0, 12288),
    ("standard", 12.2, 8192),
    ("compact", 9.0, 8192),
    ("compact", 40.0, 8192),     # compact profile keeps the trimmed 8k path
])
def test_large_models_start_at_the_window_they_will_need(monkeypatch, tier, size, expected):
    monkeypatch.setattr(chat_tools, "_NUM_CTX_IN_USE", {})
    monkeypatch.setattr(chat_tools, "_resolve_ollama_base_url", lambda *args: "http://ollama")
    monkeypatch.setattr(chat_tools, "model_capability", lambda *args: _Capability(tier, size))
    monkeypatch.delenv("COPYLOT_OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("COPYLOT_OLLAMA_MAX_CTX", raising=False)
    assert chat_tools._ollama_num_ctx("m", None, 1000) == expected


def test_the_owner_ceiling_still_caps_the_larger_start(monkeypatch):
    monkeypatch.setattr(chat_tools, "_NUM_CTX_IN_USE", {})
    monkeypatch.setattr(chat_tools, "_resolve_ollama_base_url", lambda *args: "http://ollama")
    monkeypatch.setattr(chat_tools, "model_capability", lambda *args: _Capability("standard", 35.0))
    monkeypatch.setenv("COPYLOT_OLLAMA_MAX_CTX", "10000")
    assert chat_tools._ollama_num_ctx("m", None, 1000) == 10000
    monkeypatch.setattr(chat_tools, "model_capability", lambda *args: _Capability("standard", 35.0, window=8192))
    monkeypatch.setattr(chat_tools, "_NUM_CTX_IN_USE", {})
    assert chat_tools._ollama_num_ctx("m", None, 1000) == 8192


def test_small_models_keep_the_short_task_list(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.records
    run(['{"task":"current_plot"}', '{"source":"current_result","query":""}', '{"observations":["e0r0"]}'],
        message="Summarise the QC, the volcano and the enrichment results.", view=_view("qc.cv"))
    assert "results_overview" not in calls[0]["schema"]["properties"]["task"]["enum"]
    assert calls[0]["schema"]["properties"]["modules"]["maxItems"] == 0


def test_larger_models_can_read_several_analyses_together(assistant_rig):
    run, calls, reads, profile = assistant_rig.run, assistant_rig.records, assistant_rig.plans, assistant_rig.profile
    profile["value"] = ("standard", 4, 1000)
    plan = {"task": "results_overview", "modules": ["qc.cv", "stats.volcano", "stats.ora"]}
    result = run([json.dumps(plan), '{"observations":["e0r0"]}'],
                 message="Summarise the QC, the volcano and the enrichment results.", view=_view("qc.cv"))
    assert "results_overview" in calls[0]["schema"]["properties"]["task"]["enum"]
    assert calls[0]["schema"]["properties"]["modules"]["maxItems"] == 3
    assert reads[-1].task == "results_overview" and reads[-1].modules == ["qc.cv", "stats.volcano", "stats.ora"]
    assert len(calls) == 2  # no single-module relevance pick collapses the overview
    assert result.answer


@pytest.mark.parametrize("status", ["available", "partial", "unavailable"])
def test_overview_evidence_keeps_each_module_labelled_and_scoped(monkeypatch, status):
    from app.services import ai_functions
    monkeypatch.setattr(ai_functions, "general_proteomics_context", lambda workflow: {"data": {"text": "project|workflow=phosphosite"}})
    seen = []

    def module_evidence(module, workflow, mode, profile="compact"):
        seen.append((module, mode))
        return [Evidence(tool=module, status=status, text=f"{module.replace('.', '_')}_answer_summary|count={len(seen)}")]
    monkeypatch.setattr(assistant, "_module_evidence", module_evidence)
    request = AssistantRequest(message="Summarise QC and the volcano", view=_view("qc.cv", mode={"kind": "phospho", "x": 1}))
    evidence = assistant.scientific_evidence(request, AssistantPlan(task="results_overview", modules=["qc.cv", "stats.volcano", "bogus", "qc.cv"]))
    assert [item.tool for item in evidence[1:]] == ["overview: QC Pipeline / Cov Plot", "overview: Statistical Analysis / Volcano Plot"]
    assert seen == [("qc.cv", {"kind": "phospho", "x": 1}), ("stats.volcano", None)]
    assert "current selections" in evidence[1].text and "default module settings" in evidence[2].text
    assert all(item.status == status for item in evidence[1:])
    if status == "unavailable":
        return
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Summarise QC and the volcano")
    answer = assemble_answer(ScientificAnswer(observations=[catalogue["observations"][0]["id"]]), catalogue, values, evidence)
    assert "QC Pipeline / Cov Plot:" in answer and "Statistical Analysis / Volcano Plot:" in answer


def test_larger_models_get_a_page_map_when_it_fits(assistant_rig):
    run, calls, profile = assistant_rig.run, assistant_rig.records, assistant_rig.profile
    profile["value"] = ("standard", 4, 1000)
    run(['{"task":"ui","actions":[]}'], message="Take me somewhere I can judge sample quality.", view=_view())
    destinations = calls[0]["data"]["view"]["destinations"]
    assert destinations["qc.cv"].startswith("QC Pipeline / Cov Plot - CV = 100")


def test_small_models_keep_bare_page_labels(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.records
    run(['{"task":"ui","actions":[]}'], message="Take me somewhere I can judge sample quality.", view=_view())
    assert calls[0]["data"]["view"]["destinations"]["qc.cv"] == "QC Pipeline / Cov Plot"


def test_a_displayed_option_name_keeps_its_control_when_trimming(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_prompt_budget", lambda *args: (3000, 15000))
    controls = [{"id": f"c{i}", "label": f"Boxes and their points / Marker {i} outline width", "type": "number",
                 "value": "0.4", "permission": "view", "appearance": True} for i in range(80)]
    controls.append({"id": "font", "label": "Font / All text", "type": "select", "value": "", "permission": "view",
                     "appearance": True, "options": ["", "times", "arial"], "optionCount": 3,
                     "optionLabels": {"times": "Times New Roman", "arial": "Arial"}})
    request = AssistantRequest(message="Use Times New Roman everywhere. Keep the analysis settings unchanged.",
                               view={"module": "singleProtein.boxplot", "advancedOptions": True, "controls": controls})
    call = assistant.plan_request(request)
    assert any(row["element"] == "all text" and row["property"] == "font family" for row in call.inputs["styling"])
