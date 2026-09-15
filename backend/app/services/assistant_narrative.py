"""Application-owned factual sentences, reviewed methods and explicit answer coverage."""
import re

from app.schemas.assistant import Evidence, ScientificAnswer
from app.services.assistant_answers import answer_facts, _comparison, render_hypotheses, evidence_qualifications
from app.services.assistant_methods import METHODS

_TOPICS = {
    "method": (r"\b(explain|how|calculat\w*|formula|method|erklär\w*|berechn\w*)\b", "method explanation"),
    "scale": (r"\b(scale|linear|skala)\b", "intensity scale"),
    "contrast": (r"\b(direction|contrast|fold.change|x.axis|richtung)\b", "contrast direction"),
    "axis": (r"\b(axes|axis|achse)\b", "axis meaning"),
    "causality": (r"\b(batch.effect|prove|caus\w*|beweis\w*|chargeneffekt)\b", "causal interpretation"),
}


def answer_catalogue(evidence: list[Evidence], module: str, question: str, *, method_only=False):
    sources, values = answer_facts(evidence)
    facts, methods, comparison_fields = [], [], []
    detailed = bool(re.search(r"\b(mean|quartiles?|whiskers?|minimum|maximum|all statistics|details|q1|q3|count|how many|source|normalization|imputation)\b", question, re.I))
    for source, item in zip(sources, evidence):
        if item.tool in {"project_state", "canvas"} and any(other.tool not in {"project_state", "canvas"} and other.status != "unavailable" for other in evidence):
            continue
        for fact in source.get("facts", []):
            ref = fact["ref"]
            line = item.text.splitlines()[int(ref.split('r')[1])]
            label = line.split('|', 1)[0]
            fields = dict(part.split('=', 1) for part in line.split('|')[1:] if '=' in part)
            subject = next((fields[key] for key in ("Condition", "condition", "sample", "term", "identifier", "name") if fields.get(key)), None)
            if subject:
                for field in fact["fields"]:
                    if field["name"] in {"median_cv", "Mean", "Median", "selected_p_value", "log2FC", "count", "missing_percent"}:
                        comparison_fields.append({"ref": field["ref"], "metric": field["name"], "subject": subject, "value": field["value"]})
            text = values[ref]
            if item.tool.startswith("method:"):
                continue
            topics = ["results"] + (["scale"] if "scale" in fields else [])
            if label == "cov_condition" and not detailed and {"name", "median_cv"} <= fields.keys():
                text = f"Median CV for {fields['name']}: {fields['median_cv']}%."
            elif label == "cov_answer_summary" and fields.get("all_medians_equal_at_reported_precision") == "true":
                text = f"Median CV is tied at {fields['lowest_median_cv']}% for {fields['lowest_median_cv_condition']} at the reported precision."
            elif label == "single_protein_boxplot_table_row" and not detailed and {"Condition", "Median", "SampleCount"} <= fields.keys():
                text = f"{fields['Condition']}: median {fields['Median']}, from {fields['SampleCount']} samples."
            elif label == "single_protein_boxplot_selection" and "selected_input" in fields:
                text = f"Selected entity: {fields['selected_input']}. Conditions: {fields.get('conditions', 'not supplied')}."
            elif label == "volcano_answer_summary" and {"upregulated", "downregulated", "not_significant", "p_value_threshold", "absolute_log2fc_threshold"} <= fields.keys():
                metric = "raw p-value" if fields.get("significance_metric") == "raw_p_value" else "BH-adjusted p-value"
                text = (f"At the selected {metric} cutoff of {fields['p_value_threshold']} and absolute log2 fold-change cutoff of "
                        f"{fields['absolute_log2fc_threshold']}, {fields['upregulated']} features are classified as upregulated, "
                        f"{fields['downregulated']} as downregulated and {fields['not_significant']} as not significant.")
            is_method = label.endswith(("_formula", "_axes", "_testing", "_selected_p_metric", "_multiple_testing", "_definition"))
            if is_method:
                if label == "volcano_axes" and "volcano_selected_p_metric|" in item.text:
                    continue
                tags = ["method"] + (["axis"] if label.endswith("_axes") else [])
                if label.endswith("boxplot_definition"):
                    text = "The line marks the median and the box spans the middle half of the observations. Whiskers end at the outermost observed values within 1.5 times the interquartile range below the first quartile or above the third. Observations outside those fences are outliers."
                elif label == "cov_formula":
                    text = METHODS["qc.cv"]
                    tags += ["scale"]
                elif label == "volcano_selected_p_metric":
                    metric = {"pval": "raw p-value", "adj_pval": "BH-adjusted p-value"}.get(fields.get("for_significance"))
                    if metric:
                        text = f"The y-axis is the negative log10 of the {metric}. A larger y-value means a smaller {metric}, not a larger biological effect."
                    tags += ["axis"]
                elif label == "volcano_formula":
                    tags += ["contrast"]
                methods.append({"id": ref, "text": text, "topics": tags, "kind": label})
            elif label == "volcano_contrast":
                methods.append({"id": ref, "text": f"The x-axis is log2 fold change for the contrast {line.split('|', 1)[1]}. Positive values indicate an increase in that contrast; statistical significance additionally requires the selected cutoffs.", "topics": ["method", "contrast"], "kind": label})
            elif label.startswith("single_protein_boxplot") and label not in {"single_protein_boxplot_table_row", "single_protein_boxplot_selection"} and not detailed:
                continue
            elif label.startswith("cov_") and not detailed and label not in {"cov_answer_summary", "cov_condition"}:
                continue
            elif label == "cov_condition" and not detailed and "all_medians_equal_at_reported_precision=true" in item.text:
                continue
            elif label == "volcano_term" and not (detailed or fields.get("term", "") in question or re.search(r"\b(top|rank|list|which)\b", question, re.I)):
                continue
            elif label.startswith("volcano_") and not detailed and label not in {"volcano_answer_summary", "volcano_term", "volcano_warnings"}:
                continue
            elif fields and not label.endswith(("_rule", "_functions", "_processing", "_general", "_labels")):
                priority = (4 if item.tool == "project_state" else 0 if label.endswith(("_answer_summary", "_selection")) else 1)
                facts.append({"id": ref, "text": text, "topics": topics, "priority": priority})

    # Keep tile attribution when different contrasts or entities share one canvas.
    for row in [*facts, *methods]:
        row["source"] = row["id"].split("r")[0]
        owner = evidence[int(row["id"].split("r")[0][1:])].tool
        if owner.startswith("canvas tile"):
            row["text"] = owner + ": " + row["text"]
    if module in METHODS:
        prefix = {"qc.cv": "cov_", "singleProtein.boxplot": "single_protein_boxplot_", "stats.volcano": "volcano_"}.get(module)
        methods.append({"id": "method", "text": METHODS[module], "topics": ["method"] + (["scale"] if module == "qc.cv" else []),
                        "replacedBy": [row["id"] for row in methods if prefix and row.get("kind", "").startswith(prefix)]})
    if re.search(_TOPICS["causality"][0], question, re.I):
        text = ("A CV comparison alone cannot establish or rule out a batch effect. Investigate batch labels, study design and other diagnostic evidence."
                if module == "qc.cv" else "A descriptive plot or statistical association alone does not establish causation or biological importance; additional design-specific evidence is needed.")
        methods.append({"id": "causality", "text": text, "topics": ["causality"]})
    required = (["method"] if method_only else ["results"])
    required += [topic for topic, (pattern, _) in _TOPICS.items() if re.search(pattern, question, re.I) and topic not in required]
    facts.sort(key=lambda item: item.pop("priority"))
    pairs = []
    for index, left in enumerate(comparison_fields):
        for right in comparison_fields[index + 1:]:
            try:
                _comparison(left["ref"], right["ref"], values, evidence)
            except ValueError:
                continue
            pairs.append({"left": left["ref"], "right": right["ref"]})
    tile_topics = {}
    if not method_only:
        for index, item in enumerate(evidence):
            if item.tool.startswith("canvas tile") and item.status != "unavailable":
                topics = list(required)
                if item.tool.endswith((": volcano", ": volcanoControl")):
                    topics = list(dict.fromkeys([*topics, "contrast", "axis"]))
                tile_topics[f"e{index}"] = topics
    return {"observations": facts, "methods": methods, "requiredTopics": required,
            "tileTopics": tile_topics, "comparisonFields": comparison_fields, "comparisonPairs": pairs}, values


def assemble_answer(answer: ScientificAnswer, catalogue: dict, values: dict, evidence: list[Evidence], *, fallback=False):
    selected = []
    for role, ids in (("observations", answer.observations), ("methods", answer.methods)):
        allowed = {item["id"]: item for item in catalogue[role]}
        for ref in dict.fromkeys(ids):
            if ref not in allowed:
                raise ValueError("Select only supplied sentence IDs in their correct role.")
            item = allowed[ref]
            selected.append((role, item))
    for comparison in answer.comparisons:
        pair = {"left": comparison.left, "right": comparison.right}
        if pair not in catalogue["comparisonPairs"]:
            raise ValueError("Select an advertised compatible comparison pair.")
        text = _comparison(comparison.left, comparison.right, values, evidence)
        source = comparison.left.strip("{}").split("r")[0]
        owner = evidence[int(source[1:])].tool
        if owner.startswith("canvas tile"):
            text = owner + ": " + text
        selected.append(("observations", {"text": text, "source": source, "topics": ["results"]}))
    if not selected:
        raise ValueError("Select a supplied observation or method sentence.")
    # Coverage is checked by the app, not by a model's self-reported 'answered' flag.
    requirements = [(None, topic) for topic in catalogue["requiredTopics"]]
    requirements += [(source, topic) for source, topics in catalogue["tileTopics"].items() for topic in topics]
    for source, topic in requirements:
        if any(topic in item.get("topics", []) and (source is None or item.get("source") == source) for _, item in selected):
            continue
        candidates = [item for role in ("observations", "methods") for item in catalogue[role]
                      if topic in item["topics"] and (source is None or item.get("source") == source)]
        if candidates:
            role = "observations" if candidates[0] in catalogue["observations"] else "methods"
            selected.append((role, candidates[0]))
        else:
            owner = evidence[int(source[1:])].tool + ": " if source else ""
            selected.append(("limitations", {"text": owner + f"The supplied evidence does not resolve the requested {_TOPICS.get(topic, ('', 'results'))[1]}.", "source": source}))
    contrasts = {item.get("source") for role, item in selected if item.get("kind") == "volcano_contrast"}
    paragraphs, groups = [], {}
    for role, item in selected:
        replacement_topics = {topic for other_role, other in selected if other_role == "methods" and other.get("id") in item.get("replacedBy", []) for topic in other.get("topics", [])}
        if role == "methods" and ((item.get("replacedBy") and set(item["topics"]) <= replacement_topics) or
                (item.get("kind") == "volcano_formula" and item.get("source") in contrasts)):
            continue
        key = (role, item.get("source", item.get("id", "limitations")))
        groups.setdefault(key, [])
        if item["text"] not in groups[key]:
            groups[key].append(item["text"])
    for sentences in groups.values():
        paragraph = ""
        for sentence in sentences:
            if paragraph and len(paragraph) + len(sentence) > 1000:
                paragraphs.append(paragraph)
                paragraph = ""
            paragraph = (paragraph + " " + sentence).strip()
        paragraphs.append(paragraph)
    for hypothesis in answer.hypotheses:
        if "{{" in hypothesis or "}}" in hypothesis:
            raise ValueError("Hypotheses cannot introduce evidence references or observations.")
    # Only model-written hypotheses go through prose validation; factual/method text is app-owned.
    paragraphs.extend(render_hypotheses(answer.hypotheses))
    paragraphs.extend(evidence_qualifications(evidence))
    if fallback:
        paragraphs.insert(0, "I couldn't produce a validated explanation. Here is a summary of the available evidence.")
    text = "\n\n".join(dict.fromkeys(paragraphs))
    if len(text) > 16000:
        raise ValueError("Select a smaller evidence summary.")
    return text


def catalogue_fallback(catalogue, values, evidence):
    facts = catalogue["observations"]
    methods = catalogue["methods"]
    if not facts and not methods:
        return "No usable evidence summary is available for this selection."
    choice = ScientificAnswer(observations=[facts[0]["id"]] if facts else [], methods=[] if facts else [methods[0]["id"]])
    return assemble_answer(choice, catalogue, values, evidence, fallback=True)
