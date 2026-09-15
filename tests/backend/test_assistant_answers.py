import json

import pytest
from pydantic import ValidationError

from app.schemas.assistant import Evidence, ScientificAnswer
from app.services.assistant_answers import answer_facts, _comparison, render_hypotheses
from app.services.assistant_narrative import answer_catalogue, assemble_answer, catalogue_fallback


def cv_evidence(status="available"):
    return [Evidence(tool="qc_cov_plot", status=status, text=(
        "cov_condition|name=A|median_cv=10.72\n"
        "cov_condition|name=B|median_cv=10.72\n"
        "cov_answer_summary|lowest_median_cv_condition=A, B|lowest_median_cv=10.72|"
        "highest_median_cv_condition=A, B|highest_median_cv=10.72|all_medians_equal_at_reported_precision=true\n"
        "cov_formula|CV=(SD/mean)*100|scale=linear_intensity"))]


@pytest.mark.parametrize("fallback", [False, True])
def test_canvas_completeness_requires_each_contrast_and_p_metric(fallback):
    evidence = [Evidence(tool="canvas", status="available", text="canvas_overview|tiles=2")]
    for index, contrast, metric in [(1, "B - A", "adj_pval"), (2, "A - B", "pval")]:
        evidence.append(Evidence(tool=f"canvas tile {index}: volcano", status="available", text=(
            f"volcano_contrast|{contrast}\nvolcano_selected_p_metric|for_significance={metric}\n"
            f"volcano_answer_summary|upregulated={index}|downregulated=0|not_significant=3|"
            "p_value_threshold=0.05|absolute_log2fc_threshold=1|"
            f"significance_metric={'raw_p_value' if metric == 'pval' else 'adjusted_p_value'}")))
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "Explain these plots")
    assert not catalogue["comparisonPairs"]
    assert not any(row.get("source") == "e0" for row in catalogue["observations"])
    answer = (catalogue_fallback(catalogue, values, evidence) if fallback else
              assemble_answer(ScientificAnswer(observations=["e1r2"]), catalogue, values, evidence))
    assert "contrast B - A" in answer and "contrast A - B" in answer
    assert "canvas tile 1: volcano: The y-axis is the negative log10 of the BH-adjusted p-value" in answer
    assert "canvas tile 2: volcano: The y-axis is the negative log10 of the raw p-value" in answer
    assert "1 features" in answer and "2 features" in answer


def test_comparison_choices_exclude_cross_tile_pairs():
    evidence = cv_evidence() + [cv_evidence()[0].model_copy(update={"tool": "canvas tile 2: cv"})]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "Compare")
    assert catalogue["comparisonPairs"]
    assert all(pair["left"].split("r")[0] == pair["right"].split("r")[0] for pair in catalogue["comparisonPairs"])
    with pytest.raises(ValueError, match="compatible comparison pair"):
        assemble_answer(ScientificAnswer(observations=["e0r2"], comparisons=[{"left": "e0r0f1", "right": "e1r1f1"}]), catalogue, values, evidence)


def test_cv_sentences_keep_units_and_raw_numbers():
    evidence = cv_evidence()
    original = evidence[0].text
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Which condition has larger median CV?")
    assert catalogue["observations"][0]["text"] == "Median CV is tied at 10.72% for A, B at the reported precision."
    assert values["e0r0f1"] == "10.72"
    assert evidence[0].text == original
    assert "10.72%" in assemble_answer(ScientificAnswer(observations=["e0r2"]), catalogue, values, evidence)


def test_simple_summaries_exclude_irrelevant_project_metadata_and_detailed_requests_keep_fields():
    evidence = [Evidence(tool="project_state", status="available", text="project_dataset|kind=protein|status=not_loaded"),
                Evidence(tool="qc_cov_plot", status="available", text="cov_condition|name=A|median_cv=10.72|mean_cv=11.23\ncov_overview|rows=1")]
    simple, _ = answer_catalogue(evidence, "qc.cv", "Summarize this plot")
    assert len(simple["observations"]) == 1
    assert simple["observations"][0]["text"] == "Median CV for A: 10.72%."
    detail, _ = answer_catalogue(evidence, "qc.cv", "Give the mean and median")
    assert any("11.23%" in row["text"] for row in detail["observations"])


def test_omitted_causal_and_scale_questions_are_filled_by_application():
    evidence = cv_evidence()
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Compare CV, explain its calculation and scale. Does that prove a batch effect?")
    answer = assemble_answer(ScientificAnswer(observations=["e0r2"]), catalogue, values, evidence)
    assert "sample standard deviation" in answer and "linear intensities" in answer
    assert "before application normalization and imputation" in answer
    assert "cannot establish or rule out a batch effect" in answer
    assert "One possible explanation" not in answer


def test_unknown_requested_topic_is_explicit_not_invented():
    evidence = [Evidence(tool="test", status="available", text="result|count=12")]
    catalogue, values = answer_catalogue(evidence, "unknown", "What intensity scale is used?")
    answer = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "does not resolve the requested intensity scale" in answer


@pytest.mark.parametrize("choice", [
    {"observations": ["e9r9"]}, {"observations": ["method"]},
    {"methods": ["e0r0"]}, {"observations": ["The p-value is 0.01."]},
    {"observations": ["{{e0r0}}"]},
])
def test_answer_cannot_rewrite_or_relabel_observations(choice):
    evidence = cv_evidence()
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Summarize")
    with pytest.raises(ValueError, match="supplied sentence IDs"):
        assemble_answer(ScientificAnswer(**choice), catalogue, values, evidence)


@pytest.mark.parametrize("old", [
    {"paragraphs": ["Made-up result"]}, {"actions": []}, {"answered": True}, {"method_only": True},
])
def test_old_or_self_authorizing_provider_contract_is_rejected(old):
    with pytest.raises(ValidationError):
        ScientificAnswer.model_validate(old)


def test_hypotheses_allow_general_comparative_language_with_explicit_label():
    text = "Higher variability could reflect heterogeneous responses."
    assert render_hypotheses([text]) == ["One possible explanation—not established by these results—is: " + text]


@pytest.mark.parametrize("text", ["The p-value is 0.01.", "{{e0r0}} indicates change.", "There are 42 samples.", "{{malformed"])
def test_hypotheses_cannot_smuggle_values_or_references(text):
    with pytest.raises(ValueError):
        render_hypotheses([text])


@pytest.mark.parametrize("wrapped", [False, True])
def test_verified_comparison_has_units_metric_and_direction(wrapped):
    evidence = [Evidence(tool="cv", status="available", text="cov_condition|name=A|median_cv=12.50\ncov_condition|name=B|median_cv=0")]
    _, values = answer_facts(evidence)
    left, right = "e0r0f1", "e0r1f1"
    if wrapped:
        left, right = "{{" + left + "}}", "{{" + right + "}}"
    text = _comparison(left, right, values, evidence)
    assert "12.50%" in text and "0%" in text and "higher than" in text


@pytest.mark.parametrize("second", [
    "result|condition=B|count=12",
    "result|condition=B|missing_percent=NaN",
    "result|condition=B|missing_percent=12|source=imputed",
    "result|condition=A|missing_percent=12",
])
def test_incompatible_comparisons_remain_rejected(second):
    evidence = [Evidence(tool="missing", status="available", text="result|condition=A|missing_percent=0\n" + second)]
    _, values = answer_facts(evidence)
    with pytest.raises(ValueError):
        _comparison("e0r0f1", "e0r1f1", values, evidence)


@pytest.mark.parametrize("right", ["0", "e9r9f9", "{{unknown}}"])
def test_comparisons_cannot_invent_references_or_values(right):
    evidence = cv_evidence()
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Compare")
    with pytest.raises(ValueError):
        assemble_answer(ScientificAnswer(observations=["e0r2"], comparisons=[{"left":"e0r0f1", "right":right}]), catalogue, values, evidence)


def test_unavailable_evidence_has_no_reusable_observations_or_values():
    evidence = cv_evidence("unavailable")
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Summarize")
    assert not catalogue["observations"] and not values
    with pytest.raises(ValueError):
        assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)


def test_fallback_is_honest_and_keeps_units_and_coverage():
    evidence = cv_evidence("partial")
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Explain CV and scale. Does it prove a batch effect?")
    text = catalogue_fallback(catalogue, values, evidence)
    assert "couldn't produce a validated explanation" in text
    assert "10.72%" in text and "cannot establish or rule out a batch effect" in text
    assert "not an exhaustive" in text


def test_uploaded_identifiers_are_not_reinterpreted_or_translated():
    evidence = [Evidence(tool="test", status="available", text="row|condition={{e9r9}}_adj_pval|p_value=2.588e-07")]
    catalogue, values = answer_catalogue(evidence, "unknown", "Summarize")
    text = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "2.588e-07" in text
    _, raw = answer_facts(evidence)
    assert raw["e0r0f0"] == "{{e9r9}}_adj_pval"


def test_source_qualifications_are_preserved():
    evidence = [Evidence(tool="test", status="partial", text="result|count=12\nRequested module uses default settings, not current UI selections.")]
    catalogue, values = answer_catalogue(evidence, "unknown", "Summarize")
    text = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "default settings" in text and "not an exhaustive" in text


def test_canvas_sentences_retain_their_tile_attribution():
    evidence = [Evidence(tool="canvas tile 1: volcano", status="available", text="result|count=12"),
                Evidence(tool="canvas tile 2: volcano", status="available", text="result|count=24")]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "Summarize both tiles")
    text = assemble_answer(ScientificAnswer(observations=["e0r0", "e1r0"]), catalogue, values, evidence)
    assert "canvas tile 1: volcano: Result: count: 12" in text
    assert "canvas tile 2: volcano: Result: count: 24" in text


def test_boxplot_method_uses_reviewed_sentence_not_field_names():
    evidence = [Evidence(tool="boxplot", status="available", text="single_protein_boxplot_definition|whiskers=outermost_observed_values_within_the_1.5_IQR_fences")]
    catalogue, _ = answer_catalogue(evidence, "singleProtein.boxplot", "Explain")
    assert "outermost observed values" in catalogue["methods"][0]["text"]
    assert "boxplot_definition" not in catalogue["methods"][0]["text"]


def test_specific_volcano_method_replaces_duplicate_formula_and_generic_method():
    evidence = [Evidence(tool="stats_volcano_plot", status="available", text=(
        "volcano_formula|log2FC=mean_condition2_minus_mean_condition1\n"
        "volcano_contrast|B - A\nvolcano_selected_p_metric|for_significance=adj_pval"))]
    catalogue, values = answer_catalogue(evidence, "stats.volcano", "Explain the axes", method_only=True)
    text = assemble_answer(ScientificAnswer(methods=["e0r0", "e0r1", "e0r2", "method"]), catalogue, values, evidence)
    assert "B - A" in text and "BH-adjusted" in text
    assert "Volcano formula" not in text and "control variant" not in text
    assert len(text.split("\n\n")) == 1


def test_deduplication_does_not_remove_another_tiles_formula():
    evidence = [Evidence(tool="canvas tile 1: volcano", status="available", text="volcano_formula|log2FC=first\nvolcano_contrast|B - A"),
                Evidence(tool="canvas tile 2: volcano", status="available", text="volcano_formula|log2FC=second")]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "Explain", method_only=True)
    text = assemble_answer(ScientificAnswer(methods=["e0r0", "e0r1", "e1r0", "method"]), catalogue, values, evidence)
    assert "log2fc: first" not in text
    assert "canvas tile 2: volcano: Volcano formula: log2fc: second" in text
    assert "not a single statistical test" in text


def test_related_observations_share_a_paragraph_without_changing_values():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text=(
        "single_protein_boxplot_table_row|Condition=A|Median=12.240|SampleCount=3\n"
        "single_protein_boxplot_table_row|Condition=B|Median=13.860|SampleCount=4"))]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Summarize")
    text = assemble_answer(ScientificAnswer(observations=["e0r0", "e0r1"]), catalogue, values, evidence)
    assert text == "A: median 12.240, from 3 samples. B: median 13.860, from 4 samples."


def test_deduplication_keeps_generic_method_when_it_supplies_required_scale():
    evidence = [Evidence(tool="qc_cov_plot", status="available", text="cov_boxplot_definition|median=50th_percentile")]
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Explain the scale", method_only=True)
    text = assemble_answer(ScientificAnswer(methods=["e0r0", "method"]), catalogue, values, evidence)
    assert "linear intensities" in text and "middle half" in text


def test_other_plot_method_does_not_replace_current_plot_description():
    evidence = [Evidence(tool="other", status="available", text="correlation_formula|method=Pearson")]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Explain", method_only=True)
    text = assemble_answer(ScientificAnswer(methods=["e0r0", "method"]), catalogue, values, evidence)
    assert "Pearson" in text and "selected protein or site's values" in text


@pytest.mark.parametrize("metric,expected", [("pval", "raw p-value"), ("adj_pval", "BH-adjusted p-value")])
def test_volcano_actual_contrast_and_axis_are_application_owned(metric, expected):
    evidence = [Evidence(tool="stats_volcano_plot", status="available", text=(
        "volcano_contrast|(B - BC) - (A - AC)\n"
        f"volcano_selected_p_metric|for_significance={metric}\n"
        "volcano_answer_summary|significance_metric=adjusted_p_value|p_value_threshold=0.05|absolute_log2fc_threshold=1|upregulated=80|downregulated=0|not_significant=0"))]
    catalogue, values = answer_catalogue(evidence, "stats.volcano", "Explain the direction and y-axis")
    text = assemble_answer(ScientificAnswer(observations=["e0r2"]), catalogue, values, evidence)
    assert "(B - BC) - (A - AC)" in text and "negative log10 of the " + expected in text
    assert "80 features" in text


def test_method_sentence_does_not_run_dataset_comparison_guard():
    evidence = [Evidence(tool="method:qc.cv", status="available", text="Reviewed method.")]
    catalogue, values = answer_catalogue(evidence, "qc.cv", "Explain CV", method_only=True)
    text = assemble_answer(ScientificAnswer(methods=["method"]), catalogue, values, evidence)
    assert "CV = 100" in text and "ddof=1" in text
    assert not catalogue["observations"]


def test_concise_method_answer_covers_causality_without_narration_call(monkeypatch):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    calls = []
    def complete(*args, **kwargs):
        calls.append(1)
        return "synthetic", ('{"task":"help","module":"qc.cv"}' if len(calls) == 1
                             else '{"source":"method:qc.cv","query":""}')
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(AssistantRequest(message="How is CV calculated? Does it prove a batch effect?", view={"module":"qc.cv"}))
    assert len(calls) == 2
    assert "sample standard deviation" in result.answer
    assert "cannot establish or rule out a batch effect" in result.answer


@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "gemini"])
def test_same_contract_for_all_providers_and_method_scope_excludes_history(monkeypatch, provider):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    calls = []
    def complete(payload, instruction, data, **kwargs):
        calls.append(json.loads(data))
        if len(calls) == 1:
            return "synthetic", '{"task":"help","module":"qc.cv","responseStyle":"explanation"}'
        if len(calls) == 2:
            return "synthetic", '{"source":"method:qc.cv","query":""}'
        assert "paragraphs" not in kwargs["schema"]["properties"]
        return "synthetic", '{"methods":["method"]}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(AssistantRequest(message="Explain CV", provider=provider,
        messages=[{"role":"assistant", "content":"Previous result: CV 99."}], view={"module":"qc.pca"}))
    assert "sample standard deviation" in result.answer
    assert calls[2]["conversation"] == [] and calls[2]["answerScope"] == "method_only"
    assert not calls[2]["catalogue"]["observations"]
