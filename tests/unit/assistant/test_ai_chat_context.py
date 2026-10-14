from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import ai_functions
from app.services.ai_context_tools import _MODULE_SPECIFIC_AI_FUNCTIONS, _function_payload
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def load_example_project() -> None:
    result = load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    assert not result.warnings


@pytest.fixture(autouse=True)
def no_model_discovery(monkeypatch):
    from types import SimpleNamespace
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "_resolve_chat_model", lambda *args: "synthetic")
    monkeypatch.setattr(assistant, "model_capability", lambda *args: SimpleNamespace(contextTier="compact"))


# 2026-10-02: moved here from ai_context_tools.py, where nothing called them.
# They only make the context lines easier to assert on; the model reads the
# raw `label|key=value` lines.
def _humanize_segment(segment: str) -> str:
    text = str(segment or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(word.capitalize() for word in text.split(" "))


def _readable_context_line(line: str) -> str:
    text = str(line or "").strip()
    if not text or "|" not in text:
        return text
    parts = [part.strip() for part in text.split("|") if part.strip()]
    if not parts:
        return ""
    raw_label = parts[0]
    if raw_label.endswith("_answer_summary"):
        label = "Direct answer evidence"
    elif raw_label.endswith(("_response_rule", "_quality_rule", "_inference_rule", "_evidence_limit")):
        label = "Interpretation constraint"
    else:
        label = _humanize_segment(raw_label)
    fields: list[str] = []
    for part in parts[1:]:
        if "=" not in part:
            fields.append(_humanize_segment(part).lower())
            continue
        key, value = part.split("=", 1)
        readable_key = re.sub(r"[_-]+", " ", key).strip().lower()
        readable_value = value.strip()
        preserve_identifier = any(
            token in readable_key
            for token in ("identifier", "term", "sample", "pair", "filename", "column", "path", "model")
        ) or "_HUMAN" in readable_value.upper()
        if not preserve_identifier:
            readable_value = readable_value.replace("_", " ")
        fields.append(f"{readable_key}: {readable_value}")
    if not fields:
        return f"{label}."
    return f"{label}: {'; '.join(fields)}."


def context(
    module: str,
    workflow: str = "protein",
    mode: dict | None = None,
) -> str:
    lines = []
    for name in ["general_proteomics_context", *_MODULE_SPECIFIC_AI_FUNCTIONS.get(module, [])]:
        payload, warning = _function_payload(name, workflow, mode)
        lines.extend(str(payload["data"]["text"]).splitlines() if payload else [f"status=unavailable|{warning}"])
    return "\n".join(_readable_context_line(line) for line in lines)


def test_context_sanitizer_preserves_numeric_zero() -> None:
    assert ai_functions._safe_context_text(0) == "0"


def test_unknown_restored_imputation_does_not_invent_a_draw_scope(monkeypatch):
    from app.schemas.annotation import AnnotationImputationInfo

    annotation = ai_functions.get_annotation("protein")
    monkeypatch.setattr(annotation, "imputation", AnnotationImputationInfo(mode="unknown", applied=True))
    payload = ai_functions.general_proteomics_context(workflow="protein")
    line = next(line for line in payload["data"]["text"].splitlines() if "project_dataset|kind=protein|" in line)
    assert "parameters=unknown:applied=true" in line
    assert "sample_wise=" not in line and "q=" not in line and "seed=" not in line


def test_assistant_retains_late_summary_and_method_when_evidence_is_long():
    from app.services.scientific_assistant import _bounded_evidence
    rows = "\n".join(f"plot_row|entity=P{i}|value={i}" for i in range(100))
    result = _bounded_evidence("plot", rows + "\nplot_formula|scale=linear\nplot_answer_summary|count=100\nplot_evidence_limit|causality=not_established", 220)
    assert result.status == "partial"
    assert "count=100" in result.text and "scale=linear" in result.text
    assert "causality=not_established" in result.text
    assert "not an exhaustive result" in result.text


def test_assistant_empty_evidence_is_not_available():
    from app.services.scientific_assistant import _bounded_evidence
    assert _bounded_evidence("plot", "plot_data|status=empty").status == "unavailable"


@pytest.mark.parametrize("profile,count,characters", [("compact", 2, 600), ("standard", 4, 1000), ("extended", 6, 2000), ("unknown", 2, 600)])
def test_assistant_execution_profiles(monkeypatch, profile, count, characters):
    from types import SimpleNamespace
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "model_capability", lambda *args: SimpleNamespace(contextTier="compact" if profile == "unknown" else profile))
    actual, actual_count, actual_characters = assistant._execution_profile(AssistantRequest(message="test", view={"module":"qc.cv"}))
    assert actual == ("compact" if profile == "unknown" else profile)
    assert (actual_count, actual_characters) == (count, characters)


def test_assistant_other_module_uses_disclosed_defaults(monkeypatch):
    from app.schemas.assistant import AssistantPlan, AssistantRequest, Evidence
    from app.services import scientific_assistant as assistant
    calls = []
    def evidence(module, workflow, mode, profile="compact"):
        calls.append((module, workflow, mode))
        return [Evidence(tool="cv", status="available", text="CV evidence")]
    monkeypatch.setattr(assistant, "_module_evidence", evidence)
    request = AssistantRequest(message="Explain CV", view={"module": "qc.coverage", "workflow": "protein", "mode": {"summary": True}})
    result = assistant.scientific_evidence(request, AssistantPlan(task="current_plot", module="qc.cv"))
    assert calls == [("qc.cv", "protein", None)]
    assert "default settings" in result[-1].text
    assert assistant.scientific_evidence(request, AssistantPlan(task="help", module="arbitrary.code"))[0].status == "unavailable"


def test_assistant_cv_method_and_normalization_provenance():
    text = ai_functions.qc_cov_plot()["data"]["text"]
    assert "SD=sample_standard_deviation_ddof_1" in text
    # The fixture applies no normalization, so the source is the uploaded data.
    assert "normalization=none|source=uploaded_unnormalized_non_imputed_data_back_transformed_to_linear" in text
    assert "normalization_scope=within_this_application_only" in ai_functions.general_proteomics_context()["data"]["text"]


@pytest.mark.parametrize("adapter", [ai_functions.qc_boxplot_intensity, ai_functions.qc_cov_plot, ai_functions.single_protein_boxplot])
def test_boxplot_context_distinguishes_whiskers_and_fences(adapter):
    text = adapter()["data"]["text"]
    assert "whiskers=outermost_observed_values_within_the_1.5_IQR_fences" in text
    assert "fences=Q1-1.5xIQR_to_Q3+1.5xIQR" in text
    assert "outliers=observations_outside_the_fences" in text


def test_cv_summary_preserves_ties_at_reported_precision(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(ai_functions._table_functions, "qc_cv_table", lambda *args, **kwargs: pd.DataFrame({
        "Condition": ["A", "B"], "mean": [10.7, 10.7], "median": [10.724597, 10.724598],
        "Q1": [10, 10], "Q3": [11, 11], "lower_whisker": [9, 9], "upper_whisker": [12, 12]}))
    text = ai_functions.qc_cov_plot()["data"]["text"]
    assert "lowest_median_cv_condition=A, B" in text
    assert "highest_median_cv_condition=A, B" in text
    assert "all_medians_equal_at_reported_precision=true" in text


def test_methods_do_not_read_uploaded_data(monkeypatch):
    from app.services.scientific_assistant import scientific_evidence
    from app.schemas.assistant import AssistantRequest, AssistantPlan
    monkeypatch.setattr(ai_functions, "general_proteomics_context", lambda *args: pytest.fail("method accessed dataset"))
    result = scientific_evidence(AssistantRequest(message="How is CV computed?", view={"module":"qc.cv"}), AssistantPlan(task="help"))
    assert result[0].status == "available" and "ddof=1" in result[0].text


@pytest.mark.parametrize("answer", [
    '{"paragraphs":["{{invented}}"]}',
    '{"paragraphs":["The p-value is 0.01."]}',
    '{"hypotheses":["Abundance increased 42-fold."]}',
])
def test_generated_measurements_and_unknown_fact_ids_are_rejected(monkeypatch, answer):
    from app.schemas.assistant import AssistantRequest, Evidence
    from app.services import scientific_assistant as assistant
    replies = iter(['{"task":"project_state"}', '{"source":"project_state","query":""}', answer, answer])
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **kw: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "scientific_evidence", lambda *args: [Evidence(tool="test", status="available", text="result|count=12")])
    result = assistant.assistant_step(AssistantRequest(message="Explain", view={"module":"qc.cv"}))
    assert "couldn't produce a validated explanation" in result.answer
    assert "count: 12" in result.answer
    assert "0.01" not in result.answer and "42-fold" not in result.answer


def test_tool_numbers_are_rendered_unchanged_and_hypotheses_labelled(monkeypatch):
    from app.schemas.assistant import AssistantRequest, Evidence
    from app.services import scientific_assistant as assistant
    replies = iter(['{"task":"project_state"}', '{"source":"project_state","query":""}', '{"observations":["e0r0"],"hypotheses":["This could reflect a technical effect."]}'])
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **kw: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "scientific_evidence", lambda *args: [Evidence(tool="test", status="partial", text="result|p_value=2.588e-07")])
    result = assistant.assistant_step(AssistantRequest(message="Explain", view={"module":"qc.cv"}))
    assert "2.588e-07" in result.answer and "not established" in result.answer and "not every row of it" in result.answer


def test_capability_classification_uses_observations_then_inference(monkeypatch):
    from app.services import assistant_profiles as profiles
    # Models observed in this project's conversations (local/AI_REVIEW.md, glm5 replays).
    assert profiles.classify_model("ollama", "qwen3.5:4b", 4.7, 262144)[0:2] == ("compact", "observed")
    assert profiles.classify_model("ollama", "qwen3.5:9b", 9.65, 262144)[0:2] == ("standard", "observed")
    assert profiles.classify_model("ollama", "ministral-3:8b", 8.92, 262144)[0:2] == ("standard", "observed")
    assert profiles.classify_model("openai_compatible", "glm5", 320.8, 131072)[0:2] == ("extended", "observed")
    # Inference: generation, size, context and quantization.
    assert profiles.classify_model("ollama", "llama3.1:8b", 8, 131072)[0:2] == ("compact", "inferred")
    assert profiles.classify_model("ollama", "qwen3:32b", 32, 131072)[0:2] == ("standard", "inferred")
    assert profiles.classify_model("ollama", "qwen3:32b", 32, 4096)[0] == "compact"
    assert profiles.classify_model("ollama", "llama3.3:70b", 70, 131072)[0] == "extended"
    assert profiles.classify_model("ollama", "llama3.3:70b", 70, 12288)[0] == "standard"
    assert profiles.classify_model("ollama", "llama3.3:70b", 70, 131072, quantization="Q2_K")[0] == "standard"
    assert profiles.classify_model("ollama", "deepseek-r1:7b", 7.6, 131072)[0] == "compact"
    assert profiles.classify_model("openai_compatible", "glm-4.6")[0] == "extended"
    # An unknown family is judged by its reported size but never given the whole toolbox.
    assert profiles.classify_model("ollama", "unknown:80b", 80, 131072)[0:2] == ("standard", "inferred")
    assert profiles.classify_model("ollama", "mystery-model")[0:2] == ("compact", "unknown")
    # Cloud lines.
    assert profiles.classify_model("openai", "gpt-5")[0] == "extended"
    assert profiles.classify_model("openai", "gpt-4o-mini")[0] == "standard"
    # Haiku 4.5 and later call tools reliably in a large window: Advanced since the Claude API
    # rounds of 2026-10-13 (the token-efficient stand-in for a capable local model).
    assert profiles.classify_model("anthropic", "claude-haiku-4-5")[0] == "extended"
    assert profiles.classify_model("anthropic", "claude-3-haiku")[0] == "standard"
    assert profiles.classify_model("gemini", "gemini-2.5-pro")[0] == "extended"
    # The operator's setting wins over everything but the user's own choice.
    monkeypatch.setenv("COPYLOT_AI_MODEL_LEVELS", "qwen3.5:4b=advanced")
    assert profiles.classify_model("ollama", "qwen3.5:4b", 4.7, 262144)[0:2] == ("extended", "configured")
    exact = ("ollama", "qwen3:32b", "Q4_K_M")
    monkeypatch.setitem(profiles.TESTED_MODELS, exact, ("extended", "synthetic-evaluation"))
    assert profiles.classify_model(*exact[:2], quantization=exact[2])[1] == "tested"


def test_the_users_level_wins_and_reasoning_models_get_room_to_think(monkeypatch):
    from types import SimpleNamespace
    from app.schemas.assistant import AssistantRequest
    from app.services import assistant_profiles as profiles
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "model_capability", lambda *args: SimpleNamespace(contextTier="extended"))
    request = AssistantRequest(message="test", view={"module": "qc.cv"}, assistantLevel="basic")
    assert assistant._execution_profile(request)[0] == "compact"
    assert profiles.output_tokens("compact", False) == 1024
    assert profiles.output_tokens("extended", True) > 8000
    assert profiles.output_tokens("extended", True, context=8192) <= 8192 // 3
    assert profiles.reasoning_model("openai_compatible", "glm5") and not profiles.reasoning_model("ollama", "qwen3:8b")


def test_a_local_server_model_is_classified_at_its_own_address(monkeypatch):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    seen = []
    def capability(provider, model, endpoint=None):
        seen.append((provider, endpoint))
        from types import SimpleNamespace
        return SimpleNamespace(contextTier="extended")
    monkeypatch.setattr(assistant, "model_capability", capability)
    request = AssistantRequest(message="test", view={"module": "qc.cv"}, provider="openai_compatible", model="glm5",
                               localServerUrl="http://127.0.0.1:8084/v1", ollamaUrl="http://127.0.0.1:11434")
    assert assistant._execution_profile(request)[0] == "extended"
    assert seen == [("openai_compatible", "http://127.0.0.1:8084/v1")]


@pytest.mark.parametrize("selection", ['{"source":"method:completeness.missingPlot","query":""}', '{"source":"unsupported","query":""}', '{"source":"invented","query":""}', '{"source":"method:qc.cv","query":"","actions":[]}'])
def test_method_question_on_setup_page_gets_one_bounded_read_only_selection(monkeypatch, selection):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    calls = []
    def completion(request, instruction, data, **kwargs):
        calls.append(request.model)
        return "resolved-model", '{"task":"help"}' if len(calls) == 1 else selection
    monkeypatch.setattr(assistant, "assistant_completion", completion)
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Methods must not read calculated data"))
    result = assistant.assistant_step(AssistantRequest(message="Does missingness prove absence?", view={"module":"data.annotation"}))
    assert len(calls) == 2 and calls[1] == "resolved-model"
    assert not result.actions
    if selection == '{"source":"method:completeness.missingPlot","query":""}':
        assert "does not establish biological absence" in result.answer
        assert not result.needsClarification
    else:
        assert result.needsClarification and "method" in result.answer


@pytest.mark.parametrize("invalidate", ["cancel", "revision"])
def test_method_selection_rechecks_cancellation_and_revision(monkeypatch, invalidate):
    import threading
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    cancelled = threading.Event()
    revision = [1]
    calls = []
    monkeypatch.setattr(assistant, "runtime_cache_version", lambda: revision[0])
    def completion(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return "resolved-model", '{"task":"help"}'
        if invalidate == "cancel":
            cancelled.set()
        else:
            revision[0] += 1
        return "resolved-model", '{"source":"method:qc.cv","query":""}'
    monkeypatch.setattr(assistant, "assistant_completion", completion)
    with pytest.raises(ValueError, match="cancelled|analysis changed"):
        assistant.assistant_step(AssistantRequest(message="What is CV?", view={"module":"data.annotation"}), cancelled)
    assert len(calls) == 2


def test_assistant_schema_limits_targets_and_compact_actions(monkeypatch):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    def completion(*args, schema):
        assert "actions" not in schema["properties"]
        assert schema["properties"]["styles"]["maxItems"] == 8
        assert "UiAction" not in schema["$defs"]
        return "synthetic", '{"task":"ui","styles":[{"element":"plot","property":"rotation","value":"45"},{"element":"plot","property":"rotation","value":"60"}]}'
    monkeypatch.setattr(assistant, "assistant_completion", completion)
    # A two-setter batch is no longer refused for the compact profile (see
    # test_assistant_controls.py); setting one control twice still is.
    with pytest.raises(ValueError, match="only once per request step"):
        assistant.assistant_step(AssistantRequest(message="Rotate labels", view={"module":"qc.cv", "destinations":{"qc.cv":"CV"}, "controls":[{"id":"rotation","label":"Rotation","type":"number","value":"0", "appearance":True, "permission":"view"}]}))


@pytest.mark.parametrize("task", ["current_plot", "qc_review", "entity_lookup", "project_state"])
def test_scientific_assistant_uses_server_evidence(monkeypatch, task):
    import json
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant

    calls = []
    def completion(payload, instruction, data, **kwargs):
        calls.append(json.loads(data))
        if len(calls) == 1:
            return "synthetic", json.dumps({"task": task, "query": "CCN1_HUMAN"})
        if len(calls) == 2:
            return "synthetic", json.dumps({"source": "current_result" if task == "current_plot" else task,
                                             "query": "CCN1_HUMAN" if task == "entity_lookup" else ""})
        return "synthetic", json.dumps({"observations":[calls[-1]["catalogue"]["observations"][0]["id"]]})
    monkeypatch.setattr(assistant, "assistant_completion", completion)
    request = AssistantRequest(message="Explain CCN1_HUMAN",
        view={"module": "qc.coverage", "workflow": "protein"})
    result = assistant.assistant_step(request)
    assert result.answer
    assert "{{" not in result.answer
    assert result.evidence and not result.actions
    assert "UNTRUSTED OLD CONTEXT" not in json.dumps(calls)
    assert calls[2]["catalogue"]["observations"]


@pytest.mark.parametrize("plan", [
    '{"task":"ui","actions":[{"type":"delete","target":"dataset"}]}',
    '{"task":"ui","actions":[{"type":"navigate","target":"unknown"}]}',
    '{"task":"ui","actions":[{"type":"set_control","target":"unknown","value":"x"}]}',
    '{"task":"current_plot","actions":[{"type":"navigate","target":"qc.cv"}]}',
    'This is not a structured plan.',
])
def test_scientific_assistant_rejects_invalid_plans(monkeypatch, plan):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **kw: ("synthetic", plan))
    with pytest.raises(ValueError):
        assistant.assistant_step(AssistantRequest(message="Explain", view={"module": "qc.coverage", "workflow": "protein"}))


def test_scientific_assistant_rejects_changed_analysis(monkeypatch):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    versions = iter([1, 2])
    monkeypatch.setattr(assistant, "runtime_cache_version", lambda: next(versions))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **kw: ("synthetic", '{"task":"project_state"}'))
    with pytest.raises(ValueError, match="analysis changed"):
        assistant.assistant_step(AssistantRequest(message="Explain", view={"module": "qc.coverage", "workflow": "protein"}))


@pytest.mark.parametrize("error,status", [(None, 200), (ValueError("Unavailable"), 400)])
def test_scientific_assistant_route_preserves_response_status(monkeypatch, error, status):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import routes_chat
    from app.schemas.assistant import AssistantResponse

    def step(*args):
        if error:
            raise error
        return AssistantResponse(model="synthetic", answer="Ready", revision=1)
    monkeypatch.setattr(routes_chat, "ai_mode_enabled", lambda: True)
    monkeypatch.setattr(routes_chat, "assistant_step", step)
    app = FastAPI()
    app.include_router(routes_chat.router)
    with TestClient(app) as client:
        result = client.post("/api/chat/assistant", json={"message": "Explain", "view": {"module": "qc.coverage"}})
    assert result.status_code == status
    assert ai_functions._safe_context_text(0.0) == "0.0"


def test_coverage_context_exposes_final_extremes_without_recalculation() -> None:
    text = context("qc.coverage")
    assert "sample values are final computed counts: true" in text
    assert "highest sample: GRK_1; highest count: 7440" in text
    assert "lowest sample: GRK_5; lowest count: 7390" in text


def test_boxplot_and_cv_contexts_expose_bounded_comparisons() -> None:
    boxplot = context("qc.boxplot", mode={"mode": "Mean"})
    assert "comparison is descriptive: true" in boxplot
    assert "inferential test results: not available" in boxplot
    assert "report only numerical differences from available summary statistics" in boxplot
    assert "highest median condition: GRK; highest median: 8.05" in boxplot
    assert "lowest median condition: WT; lowest median: 8.02" in boxplot
    assert "median difference right minus left: 0.03" in boxplot
    assert "left iqr: 2.58; right iqr: 2.56" in boxplot
    assert "quality interpretation" not in boxplot
    assert "general warning signals" not in boxplot

    cv = context("qc.cv")
    assert "lower median cv means more consistent by this descriptive metric: true" in cv
    assert "lowest median cv condition: GRK; lowest median cv: 5.30" in cv
    assert "highest median cv condition: WT; highest median cv: 5.47" in cv
    assert "quality cutoff applied: false" in cv


def test_missingness_threshold_context_does_not_invent_outliers() -> None:
    text = context(
        "completeness.tables",
        mode={"kind": "protein", "outlierThreshold": 20, "includeId": True},
    )
    assert "Direct answer evidence: threshold percent: 20; count: 0" in text
    assert "result: no samples exceed the threshold" in text
    # The model no longer receives instructions in the evidence; the app writes the answer (2026-10-02).


def test_histogram_context_matches_condition_mean_distributions() -> None:
    text = context("qc.histogram")
    assert "Histogram Data: status: available; sample count: 10" in text
    assert "condition: WT; samples: 5; entity condition means: 7460" in text
    assert "condition: GRK; samples: 5; entity condition means: 7487" in text
    assert "normality not proven: true" in text
    assert "mean difference right minus left: 0.04" in text
    # The model no longer receives instructions in the evidence; the app writes the answer (2026-10-02).


def test_pca_context_exposes_scores_and_bounded_geometry() -> None:
    text = context(
        "qc.pca",
        mode={"method": "PCA", "plotDim": "2D", "type": "Normal"},
    )
    assert "Pca Variance: pc1: 49.65; pc2: 9.14; pc1 pc2 total: 58.79" in text
    assert text.count("Pca Sample Score:") == 10
    assert "centroid to within ratio: 4.44" in text
    assert "no universal clean separation cutoff is assumed" in text


def test_abundance_and_correlation_contexts_match_rendered_plot_inputs() -> None:
    abundance = context("qc.abundance")
    assert "condition: WT; rank: 1; identifier: H4_HUMAN; log10 mean intensity: 5.1512" in abundance
    assert "condition: GRK; rank: 1; identifier: H2A1B_HUMAN;H2A1D_HUMAN;H2A3_HUMAN" in abundance

    correlation = context("qc.correlation")
    assert "Correlation Data: status: available; sample count: 10; pair count: 45" in correlation
    assert "lowest pair: WT_5_vs_GRK_1" in correlation
    assert "group median comparison: within condition median is higher" in correlation


def test_pca_context_and_report_use_selected_scaling(monkeypatch):
    import importlib
    import numpy as np
    import pandas as pd
    from app.services import plot_images

    report = importlib.import_module('app.services.report_function')
    samples = ['s1', 's2', 's3', 's4']
    frame = pd.DataFrame([[0, 100, 200, 300], [0, 1, 0, 1], [1, 0, 1, 0]], columns=samples)
    meta = pd.DataFrame({'sample': samples, 'condition': ['A', 'A', 'B', 'B']})
    monkeypatch.setattr(plot_images, 'select_matrix', lambda *a, **k: (None, frame, None))
    monkeypatch.setattr(plot_images, '_get_sample_columns', lambda *a: samples)
    monkeypatch.setattr(plot_images, '_metadata_for_kind', lambda *a: meta)
    projection = plot_images._pca_projection
    captured = []

    def capture(*args, **kwargs):
        result = projection(*args, **kwargs)
        captured.append((kwargs, result[1]))
        return result

    monkeypatch.setattr(plot_images, '_pca_projection', capture)
    for scaling, expected_pc1 in [('unit_variance', 76.87419249), ('centered', 99.99680015)]:
        options = report._pca_plot_options({'scaling': scaling})
        _, report_variance, _ = projection('protein', scaling=options['scaling'])
        text = context('qc.pca', mode={'method': 'PCA', 'plotDim': '2D', 'dataSource': 'data', 'scaling': scaling})
        assert captured[-1][0]['scaling'] == scaling
        np.testing.assert_allclose(captured[-1][1], report_variance)
        assert report_variance[0] == pytest.approx(expected_pc1)
        assert f'pc1: {expected_pc1:.2f}' in text


def test_abundance_context_respects_condition_and_rejects_stale_selection():
    text = context('qc.abundance', mode={'condition': 'WT'})
    assert 'condition: WT; rank: 1' in text
    assert 'condition: GRK; rank:' not in text
    stale = context('qc.abundance', mode={'condition': 'missing|condition'})
    assert 'status: unavailable' in stale
    assert 'Abundance Top Entity:' not in stale


# The selection transport tests for plots, tables and the AI context live in
# test_selection_transport.py, on a project whose names need it (2026-10-01).


@pytest.mark.parametrize('raw', ['[1]', '[null]', '[["nested"]]', '[broken'])
def test_malformed_selection_arrays_are_not_reinterpreted_as_names(raw):
    from app.services.functions import parse_selection_list
    with pytest.raises(ValueError):
        parse_selection_list(raw)


def test_selection_transport_retains_legacy_contracts():
    from app.services.functions import parse_selection_list
    assert parse_selection_list('A,B;C') == ['A', 'B;C']
    assert ai_functions._split_mode_list('A,B;C') == ['A', 'B', 'C']
    # One reader for the view's selections: keys lower-cased, native values as
    # the text the evidence builders compare, empty selections dropped.
    assert ai_functions._mode_fields({'Protein': 'P1', 'header': False, 'n': 3, 'ids': ['a', 'b'], 'x': '', 'y': None}) == {
        'protein': 'P1', 'header': 'false', 'n': '3', 'ids': '["a", "b"]'}


@pytest.mark.parametrize('level,quantity,expected', [
    ('peptide', 'Precursor.Quantity', 1), ('precursor', 'Precursor.Quantity', 2),
    ('peptide', 'LFQ intensity', 1), ('precursor', 'LFQ intensity', 1),
])
def test_peptide_coverage_context_matches_plot_and_selected_input(monkeypatch, level, quantity, expected):
    import pandas as pd
    from app.services import peptide_tools, plot_images

    frame = pd.DataFrame({'File.Name': ['ctrl_01.raw'] * 4 + ['treat_01.raw'] * 4,
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB', 'CCC'] * 2,
        'Precursor.Id': ['AAA2', 'AAA3', 'BBB2', 'CCC2'] * 2,
        'Precursor.Quantity': [10, 20, 0, None, 10, 10, 10, 10],
        'LFQ intensity': [0, 0, 30, None, 10, 10, 10, 10]})
    meta = pd.DataFrame({'sample': ['ctrl_01.raw'], 'label': ['C_1'], 'condition': ['C']})
    monkeypatch.setattr(peptide_tools, 'get_peptide_frame', lambda: frame)
    monkeypatch.setattr(plot_images, '_peptide_coverage_metadata', lambda *a, **k: meta)
    rows, total = ai_functions._coverage_rows_from_peptide(quantity_column=quantity, level=level)
    assert rows['Count'].tolist() == [expected]
    assert rows['Condition'].tolist() == ['C']
    def inspect(fig, plt, **kwargs):
        try:
            assert [bar.get_height() for bar in fig.axes[0].patches] == [expected]
            assert list(fig.axes[0].lines[0].get_ydata()) == [total, total]
        finally:
            plt.close(fig)
        return b'png'
    monkeypatch.setattr(plot_images, '_to_png_bytes', inspect)
    assert plot_images.qc_peptide_coverage_plot(quantity_column=quantity, level=level) == b'png'
    text = context('qc.coverage', workflow='peptide', mode={'level': level, 'quantityColumn': quantity})
    assert f'entity: {level}s' in text
    assert f'count: {expected}' in text
    assert 'samples: 1' in text
    invalid = context('qc.coverage', workflow='peptide', mode={'level': level, 'quantityColumn': 'Removed'})
    assert 'unavailable' in invalid


def test_missing_heatmap_context_distinguishes_aggregates_from_visual_patterns() -> None:
    text = context("completeness.heatmap", mode={"kind": "protein"})
    assert "Missing Heatmap Data: status: available" in text
    assert "sample summaries support column level comparisons" in text
    assert "specific row or block patterns require the rendered heatmap or row level matrix" in text


def test_general_context_exposes_active_project_state_without_machine_delimiters() -> None:
    text = context("data.upload")
    assert "Project State: active dataset package: HEK293" in text
    assert "Project Dataset: kind: protein; status: loaded" in text
    assert "annotation: available" in text
    assert "samples: 10; conditions: 2" in text
    assert "|" not in text


def test_volcano_context_is_rank_limited_and_uses_informative_significance_values() -> None:
    text = context(
        "stats.volcano",
        mode=(
            # Pinned on the filtered matrix: this test is about how the context
            # is formatted and rank-limited, so it names its matrix explicitly
            # rather than riding on whatever the default happens to be.
            {"source": "volcano", "kind": "protein", "dataSource": "filtered", "condition1": "WT",
             "condition2": "GRK", "identifier": "workflow", "testType": "unpaired", "pValueThreshold": 0.05,
             "log2fcThreshold": 1, "useUncorrected": False, "maxRanked": 2}
        ),
    )
    assert "max per group: 2" in text
    assert text.count("Volcano Term:") == 4
    assert "term: CCN1_HUMAN; log2fc: -2.75; selected p value: 2.588e-07" in text
    assert "term: NFM_HUMAN; log2fc: 1.00; selected p value: 3.942e-08" in text
    # The model no longer receives instructions in the evidence; the app writes the answer (2026-10-02).
    assert "|" not in text


@pytest.mark.parametrize(
    ("test_type", "description", "is_paired"),
    [
        ("unpaired", "unpaired_student_t_test_with_pooled_variance", False),
        ("unpaired_welch", "unpaired_welch_t_test_with_unequal_variance", False),
        ("paired", "paired_student_t_test_on_within_pair_differences", True),
    ],
)
def test_all_ai_statistical_contexts_preserve_the_selected_test_type(
    test_type: str,
    description: str,
    is_paired: bool,
) -> None:
    volcano = ai_functions.stats_volcano_plot(
        mode={"source": "volcano_control", "testType": test_type}
    )["summary"]
    ora = ai_functions.stats_ora_plot(
        mode={"source": "volcano_control", "testType": test_type}
    )["summary"]
    phosprot = ai_functions.phospho_phosprot_regulation_plot(
        mode={"testType": test_type}
    )["summary"]

    for payload in (volcano, ora, phosprot):
        assert f"test_type={test_type}" in payload
        assert f"selected_test={test_type}" in payload
    assert f"selected_test_description={description}" in phosprot
    control_description = (
        "paired_experimental_differences_with_propagated_control_variance"
        if is_paired else "unpaired_propagated_variance_with_satterthwaite_degrees_of_freedom"
    )
    for payload in (volcano, ora):
        assert f"selected_test_description={control_description}" in payload
    assert "_minus_(mean_condition1_control_minus_mean_condition2_control)" in volcano

    assert ("volcano_pairing|" in volcano) is is_paired
    assert "supported_tests=unpaired,unpaired_welch,paired" in volcano


def test_ai_statistical_context_uses_safe_default_for_unknown_test_type() -> None:
    assert ai_functions._normalize_stats_test_type("not-a-test") == "unpaired"
def test_plot_catalogue_has_explicit_evidence_coverage_gaps():
    """Every view that shows a plot or result has assistant evidence.

    The views are listed in tests/fixtures/assistant_plot_modules.json, which
    frontend/tests/unit/assistant-plot-catalogue.test.ts compares with the
    app's own tabs (src/lib/navigationTabs.ts).
    """
    import json
    from pathlib import Path
    from app.services.ai_context_tools import _MODULE_SPECIFIC_AI_FUNCTIONS
    from app.services.assistant_methods import METHODS
    from app.services import ai_functions

    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "assistant_plot_modules.json"
    modules = set(json.loads(fixture.read_text(encoding="utf-8")))
    gaps = set()
    assert modules - set(_MODULE_SPECIFIC_AI_FUNCTIONS) == gaps
    assert set(_MODULE_SPECIFIC_AI_FUNCTIONS) <= modules
    assert set(METHODS) == set(_MODULE_SPECIFIC_AI_FUNCTIONS)
    for functions in _MODULE_SPECIFIC_AI_FUNCTIONS.values():
        # A tool is named after its renderer; its context function is `*_context` (CONTEXT_TOOL_FUNCTIONS).
        assert functions and all(
            callable(getattr(ai_functions, ai_functions.CONTEXT_TOOL_FUNCTIONS.get(name, name), None)) for name in functions)


@pytest.mark.parametrize("source", ["anova", "anova_cluster"])
@pytest.mark.parametrize("uncorrected", [False, True])
@pytest.mark.parametrize("posthoc", ["none", "tukey"])
def test_anova_evidence_matches_ui_calculation(monkeypatch, source, uncorrected, posthoc):
    import pandas as pd
    from app.schemas.stats import AnovaRequest
    from app.services import stats_tools
    from app.services.scientific_assistant import _module_evidence

    samples = [f"{condition}{rep}" for condition in "ABC" for rep in range(3)]
    frame = pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(8)],
                          **{sample: [10 + i * .1 + "ABC".index(sample[0]) * 3 + int(sample[1]) * .2
                                      for i in range(8)] for sample in samples}})
    metadata = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    monkeypatch.setattr(stats_tools, "_stats_source", lambda *args, **kwargs: ("filtered", frame.copy(), metadata.copy(), []))
    request = AnovaRequest(kind="protein", source=source, useUncorrected=uncorrected, nClusters=2, postHoc=posthoc)
    expected = stats_tools.run_anova(request)
    mode = request.model_dump()
    selected = str(expected.clusterRows[0]["cluster"]) if source == "anova_cluster" else "none"
    mode["selectedCluster"] = selected
    text = ai_functions.stats_anova_plot("protein", mode)["data"]["text"]
    assert f"full_analysis_tested={expected.totalRows}" in text
    assert f"full_analysis_significant={expected.significantCount}" in text
    assert "source_used=filtered" in text
    metric = "raw_p_value" if uncorrected else "BH_adjusted_p_value"
    assert f"selected_p_metric={metric}" in text
    selected_rows = [row for row in expected.clusterRows if str(row["cluster"]) == selected] if source == "anova_cluster" else expected.rows
    assert f"selected_view_rows={len(selected_rows)}" in text
    assert f"comparisons={len(expected.postHocRows)}" in text
    for row in selected_rows[:5]:
        assert f"term={row['ProteinNames']}|f_statistic={ai_functions._fmt_value(row['f_statistic'])}|raw_p_value={ai_functions._fmt_probability(row['pval'])}|selected_p_value={ai_functions._fmt_probability(row['selected_pval'])}" in text
    evidence = _module_evidence("stats.anova", "protein", mode)[0]
    assert evidence.status != "unavailable"
    assert evidence.context["anova_parameters"]["selected_p_metric"] == metric
    if len(selected_rows) > 5:
        assert evidence.status == "partial"


def test_anova_evidence_invalid_parameters_and_peptides_are_unavailable():
    from app.services.scientific_assistant import _module_evidence
    for workflow, mode in [("peptide", None), ("protein", {"nClusters": 0}), ("protein", {"source": "invented"})]:
        assert _module_evidence("stats.anova", workflow, mode)[0].status == "unavailable"


def test_anova_empty_results_warnings_and_stale_cluster(monkeypatch):
    from app.schemas.stats import AnovaResultResponse
    from app.services.scientific_assistant import _module_evidence
    result = AnovaResultResponse(kind="protein", source="anova_cluster", sourceUsed="filtered",
        labelColumn="ProteinNames", totalRows=0, significantCount=0, clusterCount=0, rows=[],
        warnings=["No rows passed the ANOVA threshold; clustering was not run."])
    monkeypatch.setattr(ai_functions._stats_tools, "run_anova", lambda request: result)
    evidence = _module_evidence("stats.anova", "protein", {"source": "anova_cluster"})[0]
    assert evidence.status == "available"
    assert "full_analysis_tested=0" in evidence.text and "clustering was not run" in evidence.text
    assert _module_evidence("stats.anova", "protein", {"source": "anova_cluster", "selectedCluster": "99"})[0].status == "unavailable"


def test_anova_infinite_f_and_zero_probability_are_preserved(monkeypatch):
    from app.schemas.stats import AnovaResultResponse
    result = AnovaResultResponse(kind="protein", source="anova", sourceUsed="filtered",
        labelColumn="ProteinNames", totalRows=1, significantCount=1,
        rows=[{"ProteinNames": "P1", "f_statistic": float("inf"), "pval": 0.0, "adj_pval": 0.0, "selected_pval": 0.0, "significance": "Significant"}])
    monkeypatch.setattr(ai_functions._stats_tools, "run_anova", lambda request: result)
    text = ai_functions.stats_anova_plot()["data"]["text"]
    assert "f_statistic=infinity|raw_p_value=0|selected_p_value=0" in text
def test_distribution_adapter_uses_actual_summary_and_preserves_zero(monkeypatch):
    import pandas as pd
    from app.services import data_tools
    frame = pd.DataFrame({"A": [0.0, 2.0], "B": [None, 4.0]})
    monkeypatch.setattr(data_tools, "qc_matrix", lambda kind: (frame, pd.DataFrame()))
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, data: ["A", "B"])
    text = ai_functions.data_distribution_summary("protein")["data"]["text"]
    assert "source_used=data" in text and "count=3" in text and "missingCount=1" in text
    assert "min=0.0" in text and "mean=2.0" in text
    assert "summary_is_not_a_normality_test" in text


@pytest.mark.parametrize("test_type", ["unpaired", "unpaired_welch"])
def test_simulation_adapter_matches_actual_sensitivity_results(monkeypatch, test_type):
    import pandas as pd
    from app.schemas.stats import SimulationRequest
    from app.services import stats_tools
    samples = ["A1", "A2", "A3", "B1", "B2", "B3"]
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2"], **{s: [10 + i, 20 + i * .5] for i, s in enumerate(samples)}})
    metadata = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    monkeypatch.setattr(stats_tools, "_stats_source", lambda *args, **kwargs: ("filtered", frame.copy(), metadata.copy(), []))
    request = SimulationRequest(kind="protein", condition1="A", condition2="B", testType=test_type,
                                varianceMultiplier=2, sampleSizeOverride=6)
    result = stats_tools.run_simulation(request)
    text = ai_functions.stats_simulation_plot("protein", request.model_dump(mode="json"))["data"]["text"]
    assert f"upregulatedCount={result.upregulatedCount}" in text
    assert "sampleSizeOverride=6" in text and "scope=hypothetical_sensitivity_analysis" in text
    assert "effectiveSampleSizeCondition1Min=6" in text


@pytest.mark.parametrize("source", ["volcano", "volcano_control"])
@pytest.mark.parametrize("uncorrected", [True, False])
def test_ksea_adapter_uses_export_contract_not_kinase_results(monkeypatch, source, uncorrected):
    import pandas as pd
    calls = []
    def export(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({"UPD_seq": ["AAAAAAASAAAAAAA"], "log2FC": [0], "pval": [.5], "adj_pval": [.5], "significance": ["Not significant"]})
    monkeypatch.setattr(ai_functions._phospho_tools, "ksea_table", export)
    mode = {"source": source, "condition1": "A", "condition2": "B", "condition1Control": "C", "condition2Control": "D", "useUncorrected": uncorrected}
    text = ai_functions.phospho_ksea_export("phosphosite", mode)["data"]["text"]
    assert calls[0]["source"] == source and calls[0]["use_uncorrected"] is uncorrected
    assert "export_rows=1" in text and "not_kinase_activity_results" in text
    assert "all_testable_sites_not_only_significant=true" in text


def test_canvas_reports_composition_not_fabricated_results():
    text = ai_functions.analysis_canvas_context("protein", {"tiles": ["volcano", "boxplot"]})["data"]["text"]
    assert "tile_count=2" in text and "consult_separate_tile_evidence" in text
    with pytest.raises(ValueError):
        ai_functions.analysis_canvas_context("protein")


@pytest.mark.parametrize("module,workflow,mode", [
    ("stats.simulation", "protein", {"condition1": "A", "condition2": "B", "sampleSizeOverride": 1}),
    ("phospho.ksea", "protein", None), ("phospho.ksea", "phosphosite", {"source": "invalid"}),
    ("analysis.canvas", "protein", {"tiles": {}}),
])
def test_new_adapters_reject_unsupported_context(module, workflow, mode):
    from app.services.scientific_assistant import _module_evidence
    assert _module_evidence(module, workflow, mode)[0].status == "unavailable"
