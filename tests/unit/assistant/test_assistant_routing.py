import json

import pytest
from app.schemas.assistant import AssistantPlan, AssistantRequest, Evidence
from app.services import scientific_assistant as assistant
from app.services.assistant_routing import (
    appearance_only_request,
    contradictory_preservation,
    explanation_requested,
    explicit_destination,
    explicit_selection,
    planner_tasks,
    requests_current_result,
    significance_tuning,
    where_request,
)
from assistant_support import (
    DESTINATIONS,
    PLAN,
    VALID,
    _control,
    _labels_view,
    _site_view,
    _styling_view,
    _view,
)


@pytest.mark.parametrize("message", [
    "If I select K23, what would happen?", "I might select K23 later.",
    "Select K23 or K17.", "Select K23 and K17.", "Select K23, K17.",
    'The instruction says "select K23"; explain what that means.',
])
def test_selection_shortcut_does_not_infer_permission_or_choose_between_options(message):
    assert explicit_selection(message) is None


@pytest.mark.parametrize("message,expected", [
    ("Change the test to Welch and explain the result.", True),
    ("Open the protein boxplot and explain what it shows.", True),
    ("Rotate the labels and tell me what changed.", True),
    ("Explain how I can change the statistical test. Do not change it for me.", False),
    ("Rotate the labels without explaining anything.", False),
    ("Rotate the labels to 45 degrees.", False),
])
def test_explanation_requests_are_read_from_the_sentence(message, expected):
    assert explanation_requested(message) is expected


def test_a_missing_value_method_question_gets_completeness_not_distribution(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    plan = {"task": "help", "module": "data.distribution"}
    run([json.dumps(plan), '{"source":"method:data.distribution","query":""}', '{"observations":[],"methods":["method"]}'],
        message="Does a missing phosphosite intensity prove that the protein is absent? Explain briefly without changing anything.",
        view={"module": "singleProtein.boxplot"})
    assert reads[-1].module == "completeness.missingPlot"


def test_a_cv_question_on_the_cv_plot_is_not_answered_with_correlations(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    plan = {"task": "current_plot", "module": "qc.correlation"}
    run([json.dumps(plan), '{"source":"result:qc.correlation","query":""}', '{"observations":["e0r0"]}'],
        message="Which condition has the larger median coefficient of variation?", view={"module": "qc.cv"})
    assert reads[-1].module in {"", "qc.cv"}


def test_questions_naming_two_diagnostics_are_left_to_the_plan():
    request = AssistantRequest(message="Is the CV related to the correlation?", view={"module": "qc.cv"})
    plan = AssistantPlan(task="current_plot", module="qc.correlation")
    assert assistant._diagnostic_consistent(request, plan).module == "qc.correlation"


def test_broad_review_choice_cannot_replace_a_specific_cv_comparison(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    run(['{"task":"qc_review"}', '{"source":"qc_review","query":""}', '{"observations":["e0r0"]}'],
        message="Which condition has the larger median coefficient of variation? Quote the values.",
        view={"module": "qc.cv"})
    assert reads[-1].task == "current_plot" and reads[-1].module == "qc.cv"


@pytest.mark.parametrize("message", ["Review overall data quality including CV.",
                                     "Give a QC overview including CV.", "Compare CV and correlation."])
def test_explicit_broad_or_multiple_diagnostic_review_is_preserved(message):
    request = AssistantRequest(message=message, view={"module": "qc.cv"})
    assert assistant._diagnostic_consistent(request, AssistantPlan(task="qc_review")).task == "qc_review"


@pytest.mark.parametrize("source,query", [("entity_lookup", "K9"), ("qc_review", ""), ("unsupported", "")])
def test_canvas_explanation_after_focus_uses_the_canvas_not_a_standalone_lookup(assistant_rig, source, query):
    run, reads = assistant_rig.run, assistant_rig.plans
    run(['{"task":"entity_lookup","query":"K9"}', json.dumps({"source": source, "query": query}),
         '{"observations":["e0r0"]}'],
        message="Please build the canvas around phosphosite K9. Once its charts have loaded, explain the displayed comparison.",
        answerOnly=True, view={"module": "analysis.canvas"})
    assert reads[-1].task == "current_plot" and reads[-1].module == "analysis.canvas"
    assert reads[-1].query == ""


def test_explicit_separate_lookup_is_not_replaced_by_canvas_evidence(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    run(['{"task":"entity_lookup","query":"K23"}', '{"source":"entity_lookup","query":"K23"}',
         '{"observations":["e0r0"]}'], message="After building the canvas, do a separate lookup of K23.",
        answerOnly=True, view={"module": "analysis.canvas"})
    assert reads[-1].task == "entity_lookup" and reads[-1].query == "K23"


def test_a_separate_lookup_is_not_presented_as_the_selection():
    request = AssistantRequest(message="Now select K23", view=_site_view("K17"))
    note = assistant._separate_lookup_note(request, AssistantPlan(task="entity_lookup", query="K23"))
    assert "separate lookup of K23" in note and "still shows K17" in note
    assert assistant._separate_lookup_note(request, AssistantPlan(task="entity_lookup", query="K17")) == ""


@pytest.mark.parametrize("question", [
    "Which condition has the larger median coefficient of variation?",
    "Please explain which group has a higher median.",
    "Where are missing values shown?", "When should I use Welch?", "Who is included in this comparison?",
])
def test_information_questions_do_not_advertise_ui_actions(assistant_rig, question):
    request = AssistantRequest(message=question, model="synthetic", view={"module": "qc.cv"})
    call = assistant.plan_request(request)
    assert "ui" not in call.tasks
    assert call.schema["properties"]["actions"]["maxItems"] == 0
    assert "Action example:" not in call.system
    assert "No UI actions are allowed" in call.system


def test_question_followed_by_an_explicit_change_keeps_ui_actions(assistant_rig):
    request = AssistantRequest(message="Which plot is open? Then rotate the x-axis labels to 45 degrees.",
                               model="synthetic", view=_labels_view())
    call = assistant.plan_request(request)
    assert "ui" in call.tasks and "styles" in call.schema["properties"]
    assert "Action example:" not in call.system


def test_canvas_feature_request_without_explicit_level_offers_focus_tool():
    request = AssistantRequest(message="Show AKT1 on the canvas for these two conditions.", view={"module":"stats.volcano"})
    assert "canvas_focus" in planner_tasks(request.message)
    assert "canvas_focus" not in planner_tasks("How do I show AKT1 on the canvas?")


@pytest.mark.parametrize("status,restored", [("needs_clarification", True), ("incomplete", True), ("declined", False), ("interrupted", False), ("completed", False)])
def test_explicit_clarification_retains_only_an_outstanding_task(monkeypatch, status, restored):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    request = AssistantRequest(message="I mean protein AKT1, on the canvas.",
        view={"module":"analysis.canvas", "workflow":"protein"},
        conversationState={"request":"Show AKT1 on the canvas for A and B.", "module":"analysis.canvas", "workflow":"protein",
                           "selections":[], "completed":[], "status":status})
    assert assistant._clarifies_pending(request) is restored
    if restored:
        assert assistant.plan_request(request).tasks == ["canvas_focus", "clarify"]
    assert not assistant._clarifies_pending(request.model_copy(update={"answerOnly":True}))


@pytest.mark.parametrize("message,expected", [("Show AKT1 and give me a short explanation.", True),
                                             ("Show MAPK1 and tell me the difference between the groups.", True),
                                             ("Show AKT1 without an explanation.", False)])
def test_explanation_noun_retains_requested_sequence(message, expected):
    from app.services.assistant_routing import explanation_requested
    assert explanation_requested(message) is expected


def test_ordinary_visible_question_cannot_become_generic_help(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    result = run(['{"task":"help"}', '{"observations":["e0r0"]}'], message="What does this show?")
    assert reads[-1].task == "current_plot" and result.evidence


@pytest.mark.parametrize("message,key", [
    ("Open the protein boxplot.", "singleProtein.boxplot"),
    ("Please open the single-protein boxplot for AKT1.", "singleProtein.boxplot"),
    ("Open the protein boxplot and explain what it shows.", "singleProtein.boxplot"),
    ("Öffne bitte den Protein-Boxplot.", "singleProtein.boxplot"),
    ("Open the CV plot", "qc.cv"),
    ("Go to the volcano plot and explain it", "stats.volcano"),
    ("Show me the PCA", "qc.pca"),
    ("Open the analysis canvas", "analysis.canvas"),
    ("Open the correlation plot", "qc.correlation"),     # the spoken label breaks the tie
    ("Open the missing value plot.", "completeness.missingPlot"),
    ("Open the phosphosites on protein heatmap.", "singleProtein.heatmap"),
    ("Open the protein boxplot, select K79 and explain it.", "singleProtein.boxplot"),
])
def test_named_pages_are_resolved(message, key):
    assert explicit_destination(message, DESTINATIONS, "data.annotation") == key


@pytest.mark.parametrize("message", [
    "Open the advanced plot options.",             # not a page
    "Open the boxplot",                            # protein boxplot vs intensity boxplot
    "Open the correlation",                        # QC correlation plot vs Pearson comparison
    "Show protein PROT11 across the canvas, comparing A and B.",
    "Show everything on the canvas for phosphosite K1.",
])
def test_unclear_or_non_page_requests_are_left_to_the_planner(message):
    assert explicit_destination(message, DESTINATIONS, "data.annotation") is None


def test_open_and_explain_navigates_without_a_model_call(monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: pytest.fail("No model call needed"))
    result = assistant.assistant_step(AssistantRequest(message="Open the protein boxplot and explain what it shows.",
                                                       view=_view()))
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "singleProtein.boxplot")]
    assert result.explainAfterChanges and result.model == "application"


def test_the_open_page_is_not_reopened(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.records
    run(['{"task":"ui","actions":[]}'], message="Open the protein boxplot.", view=_view("singleProtein.boxplot"))
    assert calls  # the planner decides; no self-navigation


@pytest.mark.parametrize("message,first", [
    ("Where can I see which proteins have missing values?", "Completeness / Missing Value Plot"),
    ("Which page shows kinase activity?", "Phospho-specific / Kinase Library"),
    ("How do I find the enrichment results?", "Statistical Analysis / GO Enrichment (ORA)"),
    ("Where can I check whether my replicates cluster together?", "QC Pipeline / Principal Component Analysis"),
    ("Where can I compare CVs between conditions?", "QC Pipeline / CV Plot"),
    ("How can I see all phosphosites of one protein?", "Single Protein / Phosphosites on Protein Heatmap"),
    ("Which page shows significantly changed proteins?", "Statistical Analysis / Volcano Plot"),
    ("Which page shows which phosphosites change between A and B?", "Statistical Analysis / Volcano Plot"),
    ("Can I see the kinase activity of AKT1 in my data? Where would I look?", "Phospho-specific / Kinase Library"),
    ("I'm new here. Where can I check whether my replicates are consistent?", "QC Pipeline / CV Plot"),
    ("Where are missing values shown?", "Completeness / Missing Value Plot"),
])
def test_where_questions_point_to_pages_and_change_nothing(monkeypatch, message, first):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: pytest.fail("No model call needed"))
    result = assistant.assistant_step(AssistantRequest(message=message, view=_view("singleProtein.boxplot")))
    assert not result.actions and "Nothing was changed" in result.answer
    assert result.answer.split("\n")[1].startswith(f"- {first}")


def test_kinase_guidance_does_not_claim_the_page_computes_activity(monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: pytest.fail("No model call needed"))
    result = assistant.assistant_step(AssistantRequest(message="Which page shows kinase activity?", view=_view()))
    assert "external Kinase Library tool" in result.answer


def test_where_is_the_highest_point_is_a_result_question():
    assert not where_request("Where is the highest point in this volcano?")


def test_a_font_request_with_scoped_preservation_is_styling():
    message = "Use Times New Roman for all text in this figure. Keep the analysis settings unchanged."
    assert appearance_only_request(message) and planner_tasks(message) == ["ui", "clarify"]


def test_contradictory_preservation_asks_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: pytest.fail("No model call needed"))
    result = assistant.assistant_step(AssistantRequest(message="Keep the whole view unchanged, but change condition A to red.",
                                                       view=_view("singleProtein.boxplot")))
    assert result.needsClarification and not result.actions and "change condition A to red" in result.answer


@pytest.mark.parametrize("message", [
    "Keep the view unchanged; explain its results.",
    "How could I make the plot easier to read on a slide? Please only give advice; keep the interface unchanged.",
    "Keep this A minus B comparison unchanged. Which condition is higher?",
])
def test_plain_preservation_is_not_a_conflict(message):
    assert contradictory_preservation(message) is None


@pytest.mark.parametrize("message,tuning", [
    ("Impute the data differently until this protein has a significant p-value.", True),
    ("Make this look more significant so it is convincing for a paper.", True),
    ("Tune the settings to get significance", True),
    ("Make the significance threshold line red.", False),
    ("Make the significant points bigger", False),
    # A threshold change for more hits is tuning; the change on its own is not (2026-10-02).
    ("Lower the p threshold so more proteins are significant.", True),
    ("Relax the FDR cutoff to get more hits.", True),
    ("Switch off the BH correction so these sites show up as significant.", True),
    ("Use raw p values so that my protein becomes significant.", True),
    ("Reduce the fold change threshold to find more significant genes.", True),
    ("Lower the p threshold to 0.01.", False),
    ("Set the fold-change cutoff to 1.5.", False),
    ("Use the uncorrected p-values for this exploratory plot.", False),
    ("Raise the p threshold so fewer proteins are significant.", False),
])
def test_significance_tuning_is_refused_but_styling_significance_is_not(message, tuning):
    assert significance_tuning(message) is tuning
    assert (planner_tasks(message) == ["clarify"]) is tuning


@pytest.mark.parametrize("question,expected", [
    ("Is one condition noisier than the other? Quote the medians.", True),
    ("Which group has a higher median than the other group?", True),
    ("Quote values from another dataset.", False),
    ("Explain CV in general.", False),
])
def test_comparing_groups_does_not_mean_a_separate_analysis(question, expected):
    from app.services.assistant_routing import requests_current_result
    assert requests_current_result(question) == expected


def test_explicit_medians_cannot_be_replaced_by_a_method_only_plan(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    run(['{"task":"help","module":"qc.cv"}', '{"source":"method:qc.cv","query":""}',
         '{"observations":["e0r0"]}'], message="Do these CVs suggest more noise? Give the medians.", view=_view("qc.cv"))
    assert reads[-1].task == "current_plot"


@pytest.mark.parametrize("message", [
    "Keep this A minus B comparison unchanged. Which condition is higher?",
    "Leave the current view unchanged; explain its results.",
    "Do not alter the interface. Explain this plot.",
    "Keep the settings unchanged and add two protein boxplots to the canvas.",
])
def test_explicit_preservation_excludes_ui_in_schema_and_runtime(assistant_rig, message):
    from app.services.assistant_routing import planner_tasks
    assert "ui" not in planner_tasks(message)
    assert "canvas_focus" not in planner_tasks(message)
    request = AssistantRequest(message=message, view=_styling_view())
    call = assistant.plan_request(request)
    assert call.schema["properties"]["actions"]["maxItems"] == 0
    assert "controls" not in call.inputs["view"]
    run = assistant_rig.run
    with pytest.raises(ValueError, match="does not authorize"):
        run(['{"task":"ui","actions":[{"type":"set_control","target":"rot","value":"30"}]}'],
            message=message, view=_styling_view())


@pytest.mark.parametrize("message", [
    "Build the canvas around phosphosite K9. Explain the comparison.",
    "Please build the canvas around phosphosite K9. Once its charts have loaded, explain the displayed comparison.",
    "Show protein P1 on the canvas; describe this comparison.",
])
def test_canvas_explanation_across_sentences_keeps_dedicated_route(message):
    from app.services.assistant_routing import planner_tasks, canvas_explanation_request
    assert canvas_explanation_request(message)
    assert planner_tasks(message) == ["canvas_focus", "clarify"]


@pytest.mark.parametrize("message", [
    "How can I change the font? Keep the analysis settings unchanged.",
    "Keep the entire view unchanged and colour condition A red.",
    "Do not change anything. Hide the top border.",
    "Keep settings unchanged and add two protein boxplots to the canvas.",
])
def test_global_preservation_and_advice_do_not_open_styling(message):
    from app.services.assistant_routing import planner_tasks
    assert "ui" not in planner_tasks(message)


@pytest.mark.parametrize("message", [
    "Which condition has the larger median coefficient of variation? Quote the values.",
    "Is the y-axis showing adjusted p-values or raw p-values? Explain its transformation without changing it.",
])
def test_a_method_choice_cannot_replace_the_visible_result(assistant_rig, message):
    run, reads = assistant_rig.run, assistant_rig.reads
    run(['{"task":"current_plot"}', '{"source":"method:stats.volcano","query":""}',
         '{"observations":[],"methods":["method"]}'], message=message, view={"module": "stats.volcano"})
    assert reads and reads[0][1].task == "current_plot" and reads[0][1].module in {"", "stats.volcano"}


def test_explanation_after_a_change_uses_the_changed_view(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    run(['{"task":"current_plot"}', '{"source":"method:stats.anova","query":""}', '{"observations":[],"methods":["method"]}'],
        message="Change the test to Welch and explain the result.", view={"module": "stats.volcano"}, answerOnly=True)
    assert reads[0][1].task == "current_plot" and reads[0][1].module == ""
    run(['{"task":"current_plot"}', '{"source":"result:stats.anova","query":""}', '{"observations":[],"methods":["method"]}'],
        message="Change the test to Welch and explain the result.", view={"module": "stats.volcano"}, answerOnly=True)
    assert reads[1][1].module == ""


@pytest.mark.parametrize("task,answer_only,message,module", [
    ("qc_review", False, "Which condition has the larger median coefficient of variation? Quote the values.", "qc.cv"),
    ("help", True, "Change the test to Welch and explain the result.", "stats.volcano"),
])
def test_a_different_initial_task_cannot_drop_required_results(assistant_rig, task, answer_only, message, module):
    run, reads = assistant_rig.run, assistant_rig.reads
    run([json.dumps({"task": task}), json.dumps({"source": f"method:{module}", "query": ""}),
         '{"observations":[],"methods":["method"]}'],
        message=message, view={"module": module}, answerOnly=answer_only)
    assert reads[0][1].task == "current_plot"
    assert reads[0][1].module in {"", module}


def test_conceptual_questions_still_get_the_method(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    result = run(['{"task":"current_plot"}', '{"source":"method:completeness.missingPlot","query":""}'],
                 message="Does non-detection prove absence in general?", view={"module": "qc.cv"})
    assert reads[0][1].task == "help" and result.answer


def test_current_result_detection():
    assert requests_current_result("In this comparison, which group is higher for most sites?")
    assert not requests_current_result("Explain the other CV plot")
    assert not requests_current_result("Is that enough evidence? Explain briefly without using this dataset as proof.")


def test_visible_ora_route_is_shared_by_evidence_and_answer_catalogue(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run(['{"task":"current_plot","module":"stats.ora"}', VALID],
        message="Explain this completed ORA result", view={"module": "analysis.canvas",
        "mode": {"tileEvidence": [{"type": "oraList", "token": "synthetic"}]}})
    assert reads[0][1].module == "analysis.canvas"
    assert calls[1]["module"] == "analysis.canvas"
    assert not result.usedEvidenceFallback


def test_incomplete_conversation_is_forwarded_with_fresh_evidence(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    memory = {"request": "Explain the plot", "module": "qc.cv", "workflow": "protein",
              "selections": [], "completed": ["Opened CV."], "status": "incomplete"}
    result = run([PLAN, VALID], conversationState=memory)
    assert calls[0]["conversationState"] == memory
    assert len(reads) == 1 and not result.usedEvidenceFallback


def test_pure_navigation_does_not_authorize_unrequested_explanation():
    from app.services.assistant_routing import planner_tasks
    assert planner_tasks("Open the protein boxplot.") == ["ui", "clarify"]
    assert "current_plot" in planner_tasks("Open the protein boxplot and explain it.")
    assert planner_tasks("Make the plot more significant.") == ["clarify"]


def test_styling_applies_without_asking_the_user_to_open_a_panel(assistant_rig):
    # The appearance panel is the user's display switch. Its settings are
    # registered either way, so a styling request resolves in one step.
    result = assistant_rig.run(['{"task":"ui","styles":[{"element":"x ticks","property":"rotation","operation":"set","value":"45"}]}'],
        message="Rotate x labels to 45 degrees", view={"module": "singleProtein.boxplot", "controls": [
            _control("rot", "X axis / X tick label rotation", value="0", min=-90, max=90)]})
    assert [(a.type, a.target, a.value) for a in result.actions] == [("set_control", "rot", "45")]


@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "gemini"])
def test_relevance_corrects_wrong_diagnostic_before_reading(assistant_rig, provider):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run(['{"task":"qc_review"}', '{"source":"result:qc.cv","query":""}', VALID],
                 message="Which condition has the greater CV?", provider=provider)
    assert reads[0][1].task == "current_plot" and reads[0][1].module == "qc.cv"
    assert len(reads) == 1 and not result.actions
    assert "source" not in calls[0] and calls[1]["proposed"]["task"] == "qc_review"
    assert len(json.dumps(calls[1])) < assistant.ASSISTANT_INPUT_MAX_CHARS


def test_visible_result_cannot_be_replaced_by_other_module(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    run(['{"task":"current_plot","module":"phospho.phosphositePlot"}', VALID],
        message="Explain this plot", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "singleProtein.boxplot"
    assert len(calls) == 2


def test_explicit_other_result_uses_relevance_selection(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    run([PLAN, '{"source":"result:qc.cv","query":""}', VALID],
        message="Explain the other CV plot", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "qc.cv"


def test_specific_question_about_visible_plot_still_checks_relevance(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    run([PLAN, '{"source":"external_activity","query":""}', VALID],
        message="Does this plot establish AKT1 kinase activity?", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "external_activity" and len(calls) == 3


def test_followup_keeps_results_when_relevance_picks_same_plots_method(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    run([PLAN, '{"source":"method:singleProtein.boxplot","query":""}', VALID],
        message="And what is the difference?", view={"module":"singleProtein.boxplot"})
    assert reads[0][1].task == "current_plot"
    assert reads[0][1].module == "singleProtein.boxplot"


def test_canvas_results_are_not_replaced_by_a_single_plot_definition(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    run([PLAN, '{"source":"method:singleProtein.boxplot","query":""}', VALID],
        message="What are these plots telling me about AKT1? Keep it short.", view={"module":"analysis.canvas"})
    assert reads[0][1].task == "current_plot" and reads[0][1].module == "analysis.canvas"


def test_completed_action_only_request_does_not_append_unrequested_science(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN], message="Highlight AKT1.", receipts=['Set Highlight terms to "AKT1".'])
    assert not result.actions and not result.answer and not reads
    assert len(calls) == 1


@pytest.mark.parametrize("selection", ["not json", "[]", '{"source":[],"query":""}',
    '{"source":"ui","query":""}', '{"source":"result:invented","query":""}',
    '{"source":"current_result","query":"","actions":[]}',
    '{"source":"current_result","query":"P1"}', '{"source":"entity_lookup","query":"invented"}',
    '{"source":"entity_lookup","query":""}', '{"source":"unsupported","query":""}'])
def test_invalid_relevance_selection_never_reads_or_changes_data(assistant_rig, selection):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, selection], message="What is measured for P1?")
    assert result.needsClarification and not result.actions and not reads and len(calls) == 2


def test_valid_but_irrelevant_method_can_be_replaced_without_data_access(monkeypatch):
    replies = iter(['{"task":"help","module":"phospho.phosprotRegulation"}',
                    '{"source":"method:completeness.missingPlot","query":""}'])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Method read uploaded data"))
    result = assistant.assistant_step(AssistantRequest(message="Does non-detection establish absence?", view={"module": "qc.cv"}))
    assert "does not establish biological absence" in result.answer and not result.actions


def test_activity_question_recovers_from_unnecessary_entity_clarification(monkeypatch):
    replies = iter(['{"task":"clarify","clarification":"entity"}',
                    '{"source":"external_activity","query":""}'])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Activity must not use abundance/export"))
    result = assistant.assistant_step(AssistantRequest(message="Is AKT1 kinase activity increased?", view={"module": "qc.cv"}))
    assert "inputs, not kinase-activity results" in result.answer
    assert not result.actions and result.evidence[0].status == "unavailable"


def test_activity_uses_only_the_uploaded_snapshot(monkeypatch):
    from app.schemas.assistant import AssistantPlan
    seen = []
    monkeypatch.setattr(assistant, "_snapshot_evidence", lambda *args: seen.append(args) or Evidence(tool="uploaded", status="available", text="result"))
    request = AssistantRequest(message="Explain kinase activity", view={"module": "phospho.ksea",
        "mode": {"externalPlotPresent": True, "externalEvidenceToken": "snapshot"}})
    result = assistant.scientific_evidence(request, AssistantPlan(task="current_plot", module="external_activity"))
    assert result[0].tool == "uploaded" and seen[0][:2] == ("snapshot", "external_ksea")
