import json

import pandas as pd
import pytest
from app.schemas.assistant import AssistantRequest, Evidence, ScientificAnswer
from app.services import scientific_assistant as assistant
from app.services.assistant_answers import _comparison, answer_facts, render_hypotheses
from app.services.assistant_narrative import answer_catalogue, assemble_answer, catalogue_fallback
from pydantic import ValidationError


VOLCANO = "\n".join([
    "volcano_contrast|B - A",
    "volcano_comparison|condition1=B|condition2=A",
    "volcano_answer_summary|comparison=B_minus_A|significance_metric=adjusted_p_value|p_value_threshold=0.05|"
    "absolute_log2fc_threshold=1|upregulated=0|downregulated=80|not_significant=0",
])


def _canvas_evidence():
    vol = {"totalRows": 80, "upregulatedCount": 0, "downregulatedCount": 80, "notSignificantCount": 0, "warnings": [],
           "settings": {"kind": "phospho", "condition1": "A", "condition2": "B"}, "highlightedFeatures": ["K9"],
           "points": [{"label": "K9", "workflowLabel": "K9", "significance": "Downregulated", "log2FC": -1.679999999999998,
                       "negLog10P": 5.2039499525168464, "highlighted": True},
                      {"label": "K1", "workflowLabel": "K1", "significance": "Downregulated", "log2FC": -1.2, "negLog10P": 3.1,
                       "highlighted": False}]}
    volcano = assistant._result_evidence("canvas tile 1: volcano", vol, "compact")
    volcano.text = ("volcano_contrast|A - B\nvolcano_selected_p_metric|for_significance=adj_pval\n"
                    "volcano_comparison|condition1=A|condition2=B\nvolcano_answer_summary|upregulated=0|downregulated=80"
                    "|not_significant=0|p_value_threshold=0.05|absolute_log2fc_threshold=1|significance_metric=adjusted_p_value\n"
                    + volcano.text)
    box = {"settings": {"kind": "phospho", "identifier": "workflow", "conditions": ["A", "B"], "dataSource": "filtered", "protein": "K9"},
           "totalRows": 2, "rows": [{"Condition": "A", "Median": 14.88, "SampleCount": 4}, {"Condition": "B", "Median": 16.56, "SampleCount": 4}]}
    line = {"settings": {"kind": "phospho", "identifier": "workflow", "conditions": ["A", "B"], "dataSource": "filtered", "proteins": ["K9"]},
            "totalRows": 8, "rows": [{"Feature": "K9", "Sample": f"A{i}", "Condition": "A", "Value": 14.8} for i in range(4)]}
    return [volcano, assistant._result_evidence("canvas tile 2: proteinBoxplot", box, "compact"),
            assistant._result_evidence("canvas tile 3: proteinLineplot", line, "compact")]


def cv_evidence(status="available"):
    return [Evidence(tool="qc_cov_plot", status=status, text=(
        "cov_condition|name=A|median_cv=10.72\n"
        "cov_condition|name=B|median_cv=10.72\n"
        "cov_answer_summary|lowest_median_cv_condition=A, B|lowest_median_cv=10.72|"
        "highest_median_cv_condition=A, B|highest_median_cv=10.72|all_medians_equal_at_reported_precision=true\n"
        "cov_formula|CV=(SD/mean)*100|scale=linear_intensity"))]


def test_canvas_enrichment_keeps_its_results_in_the_catalogue():
    evidence = assistant._result_evidence("canvas tile 1: oraList", {
        "type": "canvas_ora", "testedCount": 12,
        "terms": [{"term": "Synthetic pathway", "adjusted_p_value": 0.025}],
    }, "compact")
    catalogue, _ = answer_catalogue([evidence], "analysis.canvas", "Explain this enrichment result.")
    text = " ".join(item["text"] for item in catalogue["observations"])
    assert "Synthetic pathway" in text
    assert "0.025" in text
    assert "not a new statistical test" not in text


def test_canvas_imputed_values_are_not_described_as_measurements():
    evidence = assistant._result_evidence("canvas tile 1: proteinBoxplot", {
        "settings": {"protein": "K9", "kind": "phospho", "dataSource": "imputed"}, "rows": [],
    }, "compact")
    catalogue, _ = answer_catalogue([evidence], "analysis.canvas", "Explain this plot.")
    text = " ".join(item["text"] for item in catalogue["observations"])
    assert "imputed" in text and "selected values" in text
    assert "measured values" not in text


def test_canvas_answers_are_sentences_not_raw_fields():
    evidence = _canvas_evidence()
    question = "Please build the canvas around phosphosite K9. Once its charts have loaded, explain the displayed comparison."
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", question)
    texts = [item["text"] for item in catalogue["observations"]]
    assert all("{'" not in text and "999999" not in text for text in texts)
    assert "Tile 1 (volcano): K9: log2 fold change -1.68, -log10 p 5.204, classified as downregulated." in texts
    assert "Tile 2 (boxplot): Medians by condition: A: median 14.88 from 4 samples; B: median 16.56 from 4 samples." in texts
    assert not any("K1:" in text for text in texts)  # unhighlighted points stay in the evidence panel
    answer = assemble_answer(ScientificAnswer(observations=[catalogue["observations"][0]["id"]]), catalogue, values, evidence)
    assert "does not resolve the requested method" not in answer
    assert "Tile 3 (line plot)" in answer


def test_a_method_question_on_the_canvas_gets_each_tiles_reviewed_description():
    evidence = _canvas_evidence()
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "How is each canvas plot calculated?")
    answer = assemble_answer(ScientificAnswer(observations=[catalogue["observations"][0]["id"]]), catalogue, values, evidence)
    tiles = {paragraph.split(": ", 1)[0]: paragraph for paragraph in answer.split("\n\n") if paragraph.startswith("Tile ")}
    assert "Displays a selected protein or site's values by condition." in tiles["Tile 2 (boxplot)"]
    assert "does not resolve the requested method" not in answer


def test_one_sided_volcano_direction_reads_naturally():
    evidence = _canvas_evidence()
    catalogue, _ = answer_catalogue(evidence, "analysis.canvas", "Explain the displayed comparison.")
    direction = next(row["text"] for row in catalogue["observations"] if row["id"].endswith("d"))
    assert "All 80 significant features have negative log2FC, i.e. are higher in B." in direction
    assert "the 0 upregulated" not in direction


def test_tile_method_text_is_not_offered_for_a_plain_comparison_question():
    catalogue, _ = answer_catalogue(_canvas_evidence(), "analysis.canvas", "Explain the displayed comparison.")
    assert not [row for row in catalogue["methods"] if row.get("kind") == "tile_method"]


def test_coverage_keeps_complete_condition_names(monkeypatch):
    from app.services import ai_functions
    labels = ["Ctx_DMSO_1", "Ctx_RAPA_1", "Hy_DMSO_1", "Hy_RAPA_1", "All Samples"]
    monkeypatch.setattr(ai_functions._table_functions, "qc_coverage_table", lambda *a, **k:
                        pd.DataFrame({"Sample":labels, "Number":[10, 9, 8, 7, 10]}))
    rows, total = ai_functions._coverage_rows_from_wide("protein")
    assert rows.Condition.tolist() == ["Ctx_DMSO", "Ctx_RAPA", "Hy_DMSO", "Hy_RAPA"]
    assert total == 10


def test_coverage_catalogue_uses_readable_grounded_sentences():
    evidence = [Evidence(tool="qc_coverage_plot", status="available", text=(
        "coverage_overview|workflow=protein|entity=proteins|samples=12|conditions=2|total_features=7855\n"
        "coverage_visual|bars=detected_features_per_sample|bar_color=condition\n"
        "coverage_answer_summary|lowest_count=7719|lowest_sample=Ctx_RAPA_2|highest_count=7795|highest_sample=Ctx_DMSO_1"))]
    catalogue, _ = answer_catalogue(evidence, "qc.coverage", "what can i see?")
    text = " ".join(item["text"] for item in catalogue["observations"])
    assert "12 samples" in text and "2 groups" in text and "7719" in text
    assert "detected_features_per_sample" not in text and "workflow:" not in text


def test_requested_group_medians_are_not_dropped_from_the_answer():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text="\n".join([
        "single_protein_boxplot_selection|selected_input=K9|conditions=A,B",
        "single_protein_boxplot_table_row|Condition=A|Median=14.88|SampleCount=4",
        "single_protein_boxplot_table_row|Condition=B|Median=16.56|SampleCount=4",
    ]))]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Report the group medians.")
    answer = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "14.88" in answer and "16.56" in answer


def test_direction_is_stated_by_the_application():
    """held-out 'contrast': counts were given but the higher group was left to the reader."""
    evidence = [Evidence(tool="stats_volcano_plot", status="available", text=VOLCANO)]
    catalogue, _ = answer_catalogue(evidence, "stats.volcano", "Which group is higher for most sites?")
    direction = [fact for fact in catalogue["observations"] if "direction" in fact["topics"]]
    assert direction and "significant features have negative log2FC, i.e. are higher in A" in direction[0]["text"]
    assert "direction" in catalogue["requiredTopics"]


def test_direction_is_not_required_where_no_direction_exists():
    evidence = [Evidence(tool="qc_cv", status="available", text="cov_answer_summary|lowest_median_cv=1")]
    catalogue, _ = answer_catalogue(evidence, "qc.cv", "Which condition is higher?")
    assert "direction" not in catalogue["requiredTopics"]


@pytest.mark.parametrize("question", ["Is the shorter bar a bad sample?", "Is that slightly shorter bar a problem?"])
def test_quality_concern_requires_a_limit_not_just_counts(question):
    evidence = [Evidence(tool="qc_coverage_plot", status="available", text=
        "coverage_overview|entity=proteins|samples=8|conditions=2")]
    catalogue, values = answer_catalogue(evidence, "qc.coverage", question)
    answer = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "not automatically a bad sample" in answer
    assert "before excluding" in answer


def test_qc_limit_is_available_without_forcing_it_into_every_answer():
    catalogue, _ = answer_catalogue(cv_evidence(), "qc.cv", "What do you make of this?")
    assert any(item["id"] == "quality_scope" for item in catalogue["methods"])
    assert "quality_scope" not in catalogue["requiredTopics"]


def test_clarification_i_mean_does_not_request_all_statistics():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text=
        "single_protein_boxplot_table_row|Condition=A|Mean=12.4|Median=12.2|SampleCount=4")]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "I mean MAPK1. Tell me the difference.")
    text = catalogue_fallback(catalogue, values, evidence)
    assert "median is 12.2" in text and "12.4" not in text


def test_simple_activity_answer_retains_explicitly_requested_values():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text=
        "single_protein_boxplot_table_row|Condition=A|Median=12.2|SampleCount=4")]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Is it more active? Explain simply and give the medians.")
    text = catalogue_fallback(catalogue, values, evidence)
    assert "12.2" in text and "not biological activity" in text


def test_abundance_answer_cannot_omit_requested_activity_limitation():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text="single_protein_boxplot_selection|selected_input=MAPK1|conditions=A,B")]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Which protein is shown and is it more active?")
    text = assemble_answer(ScientificAnswer(observations=["e0r0"]), catalogue, values, evidence)
    assert "not biological activity" in text
    assert "activity_scope" not in answer_catalogue(evidence, "external_activity", "Is MAPK1 more active?")[0]["requiredTopics"]


@pytest.mark.parametrize("question", ["Is it more active?", "Is it more active? Explain simply.",
    "Does that mean the treatment caused MAPK1 to be less active?"])
def test_canvas_activity_limitation_is_global_not_missing_per_tile(question):
    evidence = [Evidence(tool="canvas tile 1: proteinBoxplot", status="available", text=
        "result_overview|entity=protein|selected_input=AKT1|conditions=A,B")]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", question)
    text = catalogue_fallback(catalogue, values, evidence)
    assert "not biological activity" in text
    assert "does not resolve" not in text
    assert all("activity_scope" not in topics for topics in catalogue["tileTopics"].values())
    assert all("causality" not in topics for topics in catalogue["tileTopics"].values())
    assert catalogue["observations"] == []


def test_brief_canvas_retains_contrast_and_p_metric_without_global_counts():
    evidence = [Evidence(tool="canvas tile 1: volcano", status="available", text="\n".join([
        "volcano_contrast|Treated - Vehicle", "volcano_comparison|condition1=Treated|condition2=Vehicle",
        "volcano_selected_p_metric|for_significance=adj_pval",
        "volcano_answer_summary|upregulated=4|downregulated=4|not_significant=4|p_value_threshold=0.05|absolute_log2fc_threshold=1",
        "result_row|label=AKT1|log2FC=1.45|negLog10P=5.009|significance=Upregulated|highlighted=True",
    ]))]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "What stands out for AKT1? Briefly.")
    text = catalogue_fallback(catalogue, values, evidence)
    assert "1.45" in text and "Treated" in text and "Vehicle" in text and "BH-adjusted" in text
    assert "4 features" not in text and "8 significant" not in text


def test_simple_boxplot_answer_does_not_require_method_lecture_or_mean_comparison():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text=(
        "single_protein_boxplot_selection|selected_input=AKT1|conditions=Vehicle,Treated\n"
        "single_protein_boxplot_table_row|Condition=Vehicle|Mean=18|Median=18|SampleCount=4\n"
        "single_protein_boxplot_table_row|Condition=Treated|Mean=19|Median=19|SampleCount=4\n"
        "single_protein_boxplot_definition|median=50th_percentile"))]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Explain that in simpler words")
    assert "method" not in catalogue["requiredTopics"]
    assert all(item["metric"] != "Mean" for item in catalogue["comparisonFields"])
    answer = assemble_answer(ScientificAnswer(observations=["e0r0","e0r1"]), catalogue, values, evidence)
    assert "You're looking at AKT1" in answer
    assert "middle value (median)" in answer
    assert "Whiskers" not in answer


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
    tiles = {paragraph.split(": ", 1)[0]: paragraph for paragraph in answer.split("\n\n") if paragraph.startswith("Tile ")}
    assert "The y-axis is the negative log10 of the BH-adjusted p-value" in tiles["Tile 1 (volcano)"]
    assert "The y-axis is the negative log10 of the raw p-value" in tiles["Tile 2 (volcano)"]
    assert answer.count("Tile 1 (volcano):") == 1 and answer.count("Tile 2 (volcano):") == 1
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
    assert "can't settle the intensity scale" in answer


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
    assert "not every row of it" in text


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
    assert "default settings" in text and "not every row of it" in text


def test_canvas_sentences_retain_their_tile_attribution():
    evidence = [Evidence(tool="canvas tile 1: volcano", status="available", text="result|count=12"),
                Evidence(tool="canvas tile 2: volcano", status="available", text="result|count=24")]
    catalogue, values = answer_catalogue(evidence, "analysis.canvas", "Summarize both tiles")
    text = assemble_answer(ScientificAnswer(observations=["e0r0", "e1r0"]), catalogue, values, evidence)
    assert "Tile 1 (volcano): Result: count: 12" in text
    assert "Tile 2 (volcano): Result: count: 24" in text


def test_boxplot_method_uses_reviewed_sentence_not_field_names():
    evidence = [Evidence(tool="boxplot", status="available", text="single_protein_boxplot_definition|whiskers=outermost_observed_values_within_the_1.5_IQR_fences")]
    catalogue, _ = answer_catalogue(evidence, "singleProtein.boxplot", "Explain the whiskers")
    assert "outermost observed values" in catalogue["methods"][0]["text"]
    assert "boxplot_definition" not in catalogue["methods"][0]["text"]


def test_specific_volcano_method_replaces_duplicate_formula_and_generic_method():
    evidence = [Evidence(tool="stats_volcano_plot", status="available", text=(
        "volcano_formula|log2FC=mean_condition1_minus_mean_condition2\n"
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
    assert "Tile 2 (volcano): Volcano formula: log2fc: second" in text
    assert "not a single statistical test" in text


def test_related_observations_share_a_paragraph_without_changing_values():
    evidence = [Evidence(tool="single_protein_boxplot", status="available", text=(
        "single_protein_boxplot_table_row|Condition=A|Median=12.240|SampleCount=3\n"
        "single_protein_boxplot_table_row|Condition=B|Median=13.860|SampleCount=4"))]
    catalogue, values = answer_catalogue(evidence, "singleProtein.boxplot", "Summarize")
    text = assemble_answer(ScientificAnswer(observations=["e0r0", "e0r1"]), catalogue, values, evidence)
    assert text == "In A, the median is 12.240 across 3 samples. In B, the median is 13.860 across 4 samples."


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


@pytest.mark.parametrize("text", [
    "GRK signalling is upregulated in these cells.",
    "The kinase pathway appears down-regulated.",
    "Phosphorylation increased after treatment.",
    "Stress proteins are enriched among the hits.",
    "These sites are more abundant in the treated cells.",
    "This change is statistically significant.",
    "A low p value would point to a real effect.",
    "The fold change suggests a strong response.",
])
def test_hypotheses_cannot_state_a_direction_of_change_or_significance(text):
    """The app cannot check free text against the table, so it may not make result claims (2026-10-02)."""
    with pytest.raises(ValueError, match="tentative wording"):
        render_hypotheses([text])


def test_hypotheses_can_name_features_when_explicitly_tentative():
    from app.schemas.assistant import Evidence
    from app.services.assistant_answers import evidence_entity_names

    evidence = [Evidence(tool="t", status="available", text=(
        "single_protein_lineplot_entity_summary|entity=MYC|n_values=15\n"
        "single_protein_lineplot_overview|entity=proteins|identifier=workflow\n"
        "volcano_top|genes=JUN;FOS|term=mitochondrial translation"))]
    names = evidence_entity_names(evidence)
    assert {"MYC", "JUN", "FOS", "mitochondrial translation"} <= names
    assert "proteins" not in names
    assert render_hypotheses(["MYC could act through a feedback loop."], names)
    assert render_hypotheses(["Mitochondrial translation may be involved."], names)
    assert render_hypotheses(["A possible explanation is reduced sample loading; this has not been established."])
    assert render_hypotheses(["14-3-3 could participate."], {'14-3-3'})
    # General wording, including the generic noun, is still allowed.
    assert render_hypotheses(["The proteins may share a regulatory mechanism."], names)


def test_formula_wording_follows_the_fold_change_orientation():
    """log2FC is condition1 - condition2; the pre-flip key is gone (2026-10-02)."""
    from app.services.assistant_answers import _METHOD_WORDING

    assert "mean_condition2_minus_mean_condition1" not in _METHOD_WORDING
    assert _METHOD_WORDING["mean_condition1_minus_mean_condition2"].startswith("mean log2 intensity in the first")
