"""Application-owned factual sentences, reviewed methods and explicit answer coverage."""
import ast
import re

from app.schemas.assistant import Evidence, ScientificAnswer
from app.services.assistant_answers import answer_facts, _comparison, render_hypotheses, evidence_qualifications, evidence_entity_names
from app.services.assistant_methods import cv_method_text, METHODS

_TOPICS = {
    "method": (r"\b(how|calculat\w*|formula|method|berechn\w*)\b", "method explanation"),
    "scale": (r"\b(scale|linear|skala)\b", "intensity scale"),
    "contrast": (r"\b(direction|contrast|fold.change|x.axis|richtung|left and right|right and left)\b", "contrast direction"),
    "axis": (r"\b(axes|axis|achse)\b", "axis meaning"),
    "causality": (r"\b(batch.effect|prove|caus\w*|beweis\w*|chargeneffekt)\b", "causal interpretation"),
    "direction": (r"\b(higher|lower|larger|smaller|increased?|decreased?|which (?:group|condition)|sign|höher|niedriger)\b", "direction of change"),
}


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def _unresolved_items(unresolved: dict[str, list[str | None]], evidence: list[Evidence]) -> list[tuple[str, dict]]:
    """What the evidence cannot settle, said once.

    Round 33: every unanswered topic produced its own "The supplied
    evidence does not resolve the requested ..." sentence, once per canvas
    tile, which read like a machine apologising in a loop. Topics that share
    the same scope are now named together in one ordinary sentence.
    """
    by_scope: dict[tuple[str | None, ...], list[str]] = {}
    for name, sources in unresolved.items():
        by_scope.setdefault(tuple(dict.fromkeys(sources)), []).append(name)
    items = []
    for sources, names in by_scope.items():
        topics = _join(names)
        if len(sources) == 1 and sources[0] is None:
            items.append(("limitations", {"text": f"I can't settle the {topics} from the evidence I have here.", "source": None}))
        elif len(sources) == 1:
            prefix = tile_prefix(evidence[int(sources[0][1:])].tool)
            items.append(("limitations", {"text": f"{prefix}The evidence here doesn't settle the {topics}.", "source": sources[0]}))
        else:
            items.append(("limitations", {"text": f"Across these tiles the evidence doesn't settle the {topics}.", "source": None}))
    return items


def _volcano_direction(fields: dict, text: str) -> str | None:
    """Which condition the significant features are higher in, from the app's own counts.

    log2FC is condition1 minus condition2 (``comparison_contrast``), so an
    upregulated feature is higher in condition1. The sentence is written by the
    application from the classification counts; the model only selects it.
    Control-volcano contrasts are differences of differences and get no such
    sentence.
    """
    comparison = next((line for line in text.splitlines() if line.startswith("volcano_comparison|")), "")
    names = dict(part.split("=", 1) for part in comparison.split("|")[1:] if "=" in part)
    first, second = names.get("condition1"), names.get("condition2")
    try:
        up, down = int(fields["upregulated"]), int(fields["downregulated"])
    except (KeyError, ValueError):
        return None
    if not first or not second or "volcano_control_comparison|" in text:
        return None
    if up == down == 0:
        return (f"No feature passes both cutoffs, so the significant set shows no direction. Positive log2 fold change "
                f"would mean higher in {first}, negative higher in {second}.")
    lead = f"log2 fold change is {first} minus {second}, so a positive value means higher in {first}."
    # Iteration 22: "the 0 upregulated features ... are higher in A" read oddly;
    # a one-sided result is now stated as one side.
    if up == 0 or down == 0:
        count, higher, sign = (down, second, "negative") if up == 0 else (up, first, "positive")
        every = "the only significant feature has" if count == 1 else f"all {count} significant features have"
        return f"{lead} {every[0].upper() + every[1:]} {sign} log2FC, i.e. {'is' if count == 1 else 'are'} higher in {higher}."
    majority = (f"most are higher in {first}" if up > down else f"most are higher in {second}" if down > up
                else f"they split evenly between {first} and {second}")
    return (f"{lead} Of the {up + down} significant features, {up} are higher in {first} (positive log2FC) and "
            f"{down} are higher in {second} (negative log2FC); {majority}.")


# --- Canvas tiles in plain sentences --------------------------------------
# Iteration 21: canvas answers were correct but printed raw evidence lines --
# python dicts of settings, every volcano point field, 1.679999999999998 -- and
# "does not resolve the requested method explanation" for boxplot and lineplot
# tiles. The application writes one short typed sentence per tile line instead;
# the exact values stay in the evidence panel and in the numeric references.
_TILE_METHOD = {"volcano": "stats.volcano", "volcanoControl": "stats.volcano", "proteinBoxplot": "singleProtein.boxplot",
                "proteinLineplot": "singleProtein.lineplot", "oraList": "stats.ora"}
_LEVEL_NAMES = {"protein": "protein", "phospho": "phosphosite", "phosprot": "phosphoprotein"}


_TILE_NAMES = {"volcano": "volcano", "volcanoControl": "control volcano", "proteinBoxplot": "boxplot",
               "proteinLineplot": "line plot", "oraList": "ORA"}


# Evidence owners answered per source, each in its own labelled paragraph:
# canvas tiles and the modules of a results overview.
_GROUPED_OWNERS = ("canvas tile", "overview: ")


def tile_prefix(tool: str) -> str:
    """'canvas tile 2: proteinBoxplot' -> 'Tile 2 (boxplot): '; 'overview: X' -> 'X: '; other tools -> ''."""
    if tool.startswith("overview: "):
        return tool[len("overview: "):] + ": "
    match = re.match(r"canvas tile (\d+): (\w+)$", tool)
    if not match:
        return tool + ": " if tool.startswith("canvas tile") else ""
    return f"Tile {match[1]} ({_TILE_NAMES.get(match[2], match[2])}): "


_METHOD_QUESTION = r"\b(?:how|method|calculat\w*|formula|computed|what\s+does\s+(?:each|the|this)\s+(?:plot|tile|chart))\b"


def _short(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number or number in (float("inf"), float("-inf")):
        return str(value)
    return f"{number:.4g}"


def _field(fields: dict, name: str):
    return next((value for key, value in fields.items() if key.lower() == name.lower()), None)


def _canvas_sentence(tool: str, label: str, fields: dict, question: str, detailed: bool, brief: bool = False) -> str | None:
    """One readable sentence for a canvas tile's result line, or None to leave it out."""
    tile = tool.split(": ", 1)[-1]
    if label == "result_data":
        return None
    if label == "result_overview":
        if tile in {"volcano", "volcanoControl"}:
            warnings = _field(fields, "warnings")
            return f"Warnings: {warnings}." if warnings not in (None, "", "[]", "None") else None
        try:
            settings = ast.literal_eval(_field(fields, "settings") or "{}")
        except (ValueError, SyntaxError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        entity = settings.get("protein") or ", ".join(map(str, settings.get("proteins", []) or [])) or "the selected feature"
        conditions = ", ".join(map(str, settings.get("conditions", []) or [])) or "the selected conditions"
        level = _LEVEL_NAMES.get(str(settings.get("kind", "")), "feature")
        plot = {"proteinBoxplot": "Boxplot", "proteinLineplot": "Line plot"}.get(tile, tile)
        if brief:
            return f"{plot} shows {level} {entity} in {conditions}."
        return (f"{plot} of {level} {entity} for {conditions}, using the {settings.get('dataSource', 'data')} values "
                "(log2 by default); it displays the selected values and is not a new statistical test.")
    if label != "result_row":
        return None
    if tile in {"volcano", "volcanoControl"}:
        name = _field(fields, "workflowLabel") or _field(fields, "label") or ""
        if not (detailed or str(_field(fields, "highlighted")).lower() == "true"
                or (name and re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", question))):
            return None
        return (f"{name}: log2 fold change {_short(_field(fields, 'log2FC'))}, -log10 p {_short(_field(fields, 'negLog10P'))}"
                f", classified as {str(_field(fields, 'significance') or 'not classified').lower()}.")
    if tile == "proteinBoxplot" and _field(fields, "Condition") is not None and _field(fields, "Median") is not None:
        text = (f"{_field(fields, 'Condition')}: median {_short(_field(fields, 'Median'))} from "
                f"{_field(fields, 'SampleCount') or _field(fields, 'N')} samples")
        if detailed and _field(fields, "Q1") is not None:
            text += f" (Q1 {_short(_field(fields, 'Q1'))}, Q3 {_short(_field(fields, 'Q3'))})"
        return text + "."
    if not detailed:
        return None
    return "; ".join(f"{key}: {_short(value)}" for key, value in list(fields.items())[:8]) + "."


def answer_catalogue(evidence: list[Evidence], module: str, question: str, *, method_only=False):
    sources, values = answer_facts(evidence)
    facts, methods, comparison_fields = [], [], []
    median_refs = set()
    plain = bool(re.search(r"\b(plain|simpler|simple|simply|brief|briefly|short version|shorter (?:answer|explanation)|less technical|natural|naturally|langauge|one sentence)\b", question, re.I))
    detail_question = re.sub(r"\b(?:does|that|this|it|you|I) mean\b", "", question, flags=re.I)
    detailed = bool(re.search(r"\b(mean|quartiles?|whiskers?|minimum|maximum|all statistics|details|q1|q3|count|how many|source|normalization|imputation)\b", detail_question, re.I))
    brief = not detailed and bool(re.search(r"\b(short|shorter|brief|briefly|concise|one sentence|two sentences)\b", question, re.I))
    for source, item in zip(sources, evidence):
        if item.tool in {"project_state", "canvas"} and any(other.tool not in {"project_state", "canvas"} and other.status != "unavailable" for other in evidence):
            continue
        for fact in source.get("facts", []):
            ref = fact["ref"]
            line = item.text.splitlines()[int(ref.split('r')[1])]
            label = line.split('|', 1)[0]
            fields = dict(part.split('=', 1) for part in line.split('|')[1:] if '=' in part)
            if any(key in fields for key in ("Median", "median_cv", "lowest_median_cv")):
                median_refs.add(ref)
            subject = next((fields[key] for key in ("Condition", "condition", "sample", "term", "identifier", "name") if fields.get(key)), None)
            if subject:
                for field in fact["fields"]:
                    if field["name"] in {"median_cv", "Mean", "Median", "selected_p_value", "log2FC", "count", "missing_percent"} and not (field["name"] == "Mean" and not detailed):
                        comparison_fields.append({"ref": field["ref"], "metric": field["name"], "subject": subject, "value": field["value"]})
            text = values[ref]
            if item.tool.startswith("method:"):
                continue
            if (item.tool.startswith("canvas tile")
                    and item.tool.split(": ", 1)[-1] in {"volcano", "volcanoControl", "proteinBoxplot", "proteinLineplot"}
                    and label in {"result_overview", "result_row", "result_data"}):
                sentence = _canvas_sentence(item.tool, label, fields, question, detailed, brief)
                if sentence and label == "result_row" and item.tool.endswith(": proteinBoxplot"):
                    # One sentence per boxplot tile, so every condition's median is kept together.
                    merged = next((fact for fact in facts if fact.get("boxplot") == item.tool), None)
                    if merged:
                        merged["text"] = merged["text"][:-1] + "; " + sentence
                        continue
                    facts.append({"id": ref, "text": "Medians by condition: " + sentence, "topics": ["results"],
                                  "priority": 0, "boxplot": item.tool})
                    continue
                if sentence:
                    facts.append({"id": ref, "text": sentence, "topics": ["results"],
                                  "priority": 1 if label == "result_overview" else 0})
                continue
            topics = ["results"] + (["scale"] if "scale" in fields else [])
            if label == "coverage_overview" and {"entity", "samples", "conditions"} <= fields.keys():
                text = (f"You're looking at {fields['entity']} detected across {fields['samples']} samples. "
                        f"The plot groups those samples into {fields['conditions']} groups; each bar shows how many {fields['entity']} were detected in one sample.")
                if plain:
                    text = f"Each bar shows how many {fields['entity']} were detected in one sample; taller means more were detected."
            elif label == "coverage_visual":
                text = "The bar colours identify the groups shown in the legend."
            elif label == "coverage_reference_line" and fields.get("value") not in {None, "unknown"}:
                text = f"The red reference line marks {fields['value']} unique features detected across the samples—not the count in every sample."
            elif label == "coverage_answer_summary" and {"lowest_count", "highest_count", "lowest_sample", "highest_sample"} <= fields.keys():
                text = (f"Counts range from {fields['lowest_count']} in {fields['lowest_sample']} "
                        f"to {fields['highest_count']} in {fields['highest_sample']}. These are detection counts, not abundance or significance.")
            elif label == "condition_stats" and item.tool == "qc_coverage_plot" and {"name", "min", "max"} <= fields.keys():
                text = (f"All samples in {fields['name']} have {fields['min']} detected features."
                        if fields['min'] == fields['max'] else
                        f"In {fields['name']}, samples have between {fields['min']} and {fields['max']} detected features.")
            elif label in {"condition", "sample_values"} and item.tool == "qc_coverage_plot" and not detailed:
                continue
            elif label == "cov_condition" and not detailed and {"name", "median_cv"} <= fields.keys():
                text = f"Median CV for {fields['name']}: {fields['median_cv']}%."
            elif label == "cov_answer_summary" and fields.get("all_medians_equal_at_reported_precision") == "true":
                text = f"Median CV is tied at {fields['lowest_median_cv']}% for {fields['lowest_median_cv_condition']} at the reported precision."
            elif label == "single_protein_boxplot_table_row" and not detailed and {"Condition", "Median", "SampleCount"} <= fields.keys():
                text = (f"The middle value (median) in {fields['Condition']} is {fields['Median']}." if plain else
                        f"In {fields['Condition']}, the median is {fields['Median']} across {fields['SampleCount']} samples.")
            elif label == "single_protein_boxplot_selection" and "selected_input" in fields:
                conditions = fields.get('conditions', 'the selected conditions').replace(',', ' and ')
                text = f"You're looking at {fields['selected_input']}, comparing {conditions}."
            elif label == "volcano_answer_summary" and {"upregulated", "downregulated", "not_significant", "p_value_threshold", "absolute_log2fc_threshold"} <= fields.keys():
                if brief and item.tool.startswith("canvas tile") and any(
                        row.startswith("result_row|") and "highlighted=True" in row for row in item.text.splitlines()):
                    continue
                direction = _volcano_direction(fields, item.text)
                if direction:
                    facts.append({"id": ref + "d", "text": direction, "topics": ["results", "direction", "contrast"], "priority": 0})
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
                    text = "The line inside each box is the middle value; the box contains the middle half of the measurements."
                    if detailed or method_only or re.search(r"whisker|outlier|calculat|formula", question, re.I):
                        text += " Whiskers end at the outermost observed values within 1.5 times the interquartile range below the first quartile or above the third. Observations outside those fences are outliers."
                elif label == "cov_formula":
                    text = cv_method_text(fields.get("normalization"))
                    tags += ["scale"]
                elif label == "coverage_formula":
                    text = "Each bar counts detected features in that sample; missing measurements are not counted as detections."
                elif label == "volcano_selected_p_metric":
                    metric = {"pval": "raw p-value", "adj_pval": "BH-adjusted p-value"}.get(fields.get("for_significance"))
                    if metric:
                        text = f"The y-axis is the negative log10 of the {metric}. A larger y-value means a smaller {metric}, not a larger biological effect."
                        if brief:
                            text = f"The y-axis uses -log10({metric})."
                    tags += ["axis"]
                elif label == "volcano_formula":
                    tags += ["contrast"]
                methods.append({"id": ref, "text": text, "topics": tags, "kind": label})
            elif label == "volcano_contrast":
                comparison = next((row for row in item.text.splitlines() if row.startswith("volcano_comparison|")), "")
                names = dict(part.split("=", 1) for part in comparison.split("|")[1:] if "=" in part)
                first, second = names.get("condition1"), names.get("condition2")
                text = f"The x-axis is log2 fold change for the contrast {line.split('|', 1)[1]}. Positive values indicate an increase in that contrast; statistical significance additionally requires the selected cutoffs."
                if first and second and "volcano_control_comparison|" not in item.text:
                    text = (f"On the right, values are higher in {first}; on the left, they are higher in {second}. "
                            f"The horizontal position is log2 fold change for the contrast {first} - {second}.")
                    if brief:
                        text = f"Positive log2FC means higher in {first}; negative means higher in {second}."
                methods.append({"id": ref, "text": text, "topics": ["results", "method", "contrast"], "kind": label})
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

    # Each canvas tile gets its reviewed plot description as an optional method
    # sentence, offered only when the question asks how the plots work
    # (iteration 22: a model picked it for a plain comparison question).
    method_question = bool(re.search(_METHOD_QUESTION, question, re.I))
    for index, item in enumerate(evidence if method_question else []):
        tile = item.tool.split(": ", 1)[-1] if item.tool.startswith("canvas tile") else ""
        if tile in _TILE_METHOD and item.status != "unavailable" and _TILE_METHOD[tile] in METHODS:
            methods.append({"id": f"e{index}rm", "text": METHODS[_TILE_METHOD[tile]], "topics": ["method"], "kind": "tile_method"})
    # Keep tile attribution when different contrasts or entities share one canvas.
    for row in [*facts, *methods]:
        row["source"] = row["id"].split("r")[0]
        owner = evidence[int(row["id"].split("r")[0][1:])].tool
        if owner.startswith(_GROUPED_OWNERS):
            row["text"] = tile_prefix(owner) + row["text"]
    if module in METHODS:
        prefix = {"qc.cv": "cov_", "singleProtein.boxplot": "single_protein_boxplot_", "stats.volcano": "volcano_"}.get(module)
        method_text = METHODS[module]
        if module == "qc.coverage" and not method_only and not detailed:
            method_text = "Taller bars mean more features were detected in that sample—not that those features were more abundant."
        if module == "singleProtein.boxplot" and not method_only and not detailed:
            method_text = "The line inside each box is the middle value; the box contains the middle half of the measurements. This view describes the values, not whether a difference is statistically significant."
        methods.append({"id": "method", "text": method_text, "topics": ["method"] + (["scale"] if module == "qc.cv" else []),
                        "replacedBy": [row["id"] for row in methods if prefix and row.get("kind", "").startswith(prefix)]})
    if re.search(_TOPICS["causality"][0], question, re.I):
        text = ("A CV comparison alone cannot establish or rule out a batch effect. Investigate batch labels, study design and other diagnostic evidence."
                if module == "qc.cv" else "Not from this plot alone. It can show a difference or association, but whether a treatment caused it depends on the experimental design and possible confounding factors.")
        if plain and module != "qc.cv":
            text = "Not by itself. A difference between groups could have other explanations; whether treatment caused it depends on how the experiment was designed."
        methods.append({"id": "causality", "text": text, "topics": ["causality"]})
    quality_question = bool(re.search(r"\b(worry|worried|concerning|trust|reliable|bad sample|quality|healthy|problem|problematic)\b", question, re.I))
    if quality_question or module.startswith(("qc.", "completeness.")):
        text = ("A shorter bar means fewer features were detected, not automatically a bad sample. Coverage alone cannot tell whether the difference is a technical problem; compare missingness and the intensity distributions before excluding a sample."
                if module == "qc.coverage" else
                "This plot alone is not enough to judge overall data quality. Consider the study design, missing measurements and the other quality-control views before excluding data.")
        methods.append({"id": "quality_scope", "text": text, "topics": ["quality_scope"]})
    required = (["method"] if method_only else ["results"])
    if quality_question:
        required.append("quality_scope")
    if module in {"singleProtein.boxplot", "singleProtein.lineplot", "stats.volcano", "analysis.canvas"} and re.search(
            r"\b(?:activity|activat\w*|(?:more|less) active)\b", question, re.I):
        methods.append({"id":"activity_scope", "text":"These plots measure abundance, not biological activity. Higher or lower abundance alone does not show whether a protein is more or less active.", "topics":["activity_scope"]})
        required.append("activity_scope")
    has_direction = any("direction" in fact["topics"] for fact in facts)
    required += [topic for topic, (pattern, _) in _TOPICS.items() if re.search(pattern, question, re.I) and topic not in required
                 and (topic != "direction" or has_direction)]
    facts.sort(key=lambda item: item.pop("priority"))
    for fact in facts:
        fact.pop("boxplot", None)
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
            if item.tool.startswith(_GROUPED_OWNERS) and item.status != "unavailable":
                # "Explain the displayed comparison" asks for results per tile,
                # not a method paragraph for every tile.
                topics = [topic for topic in required if topic not in {"activity_scope", "quality_scope", "causality"}
                          and (topic != "method" or re.search(_METHOD_QUESTION, question, re.I))]
                if item.tool.endswith((": volcano", ": volcanoControl")):
                    topics = list(dict.fromkeys([*topics, "contrast", "axis"]))
                tile_topics[f"e{index}"] = topics
    if not method_only and re.search(r"\bmedians\b", question, re.I):
        for fact in facts:
            if fact["id"] in median_refs:
                topic = f"requested_median:{fact['id']}"
                fact["topics"].append(topic)
                required.append(topic)
    if not method_only and (plain or "activity_scope" in required) and set(required) & {"causality", "activity_scope"} and not re.search(
            r"\b(?:values?|medians?|means?|counts?|fold changes?|log2fc|p[- ]?values?|which|compare|difference|higher|lower|results?|summary|summari[sz]e)\b", detail_question, re.I):
        facts, comparison_fields, pairs = [], [], []
        methods = [item for item in methods if set(item["topics"]) & {"causality", "activity_scope"}]
        required, tile_topics = [topic for topic in required if topic in {"causality", "activity_scope"}], {}
    horizontal_question = bool(re.search(r"\b(?:left|right)(?:-hand)?(?: and (?:left|right))? sides?\b|\b(?:x[- ]axis|horizontal)\b", question, re.I))
    if module == "stats.volcano" and horizontal_question and not detailed and not re.search(
            r"\b(?:how many|counts?|significant|which (?:proteins|features)|largest)\b", question, re.I):
        axis_methods = [item for item in methods if item.get("kind") == "volcano_contrast"]
        if axis_methods:
            facts, comparison_fields, pairs = [], [], []
            methods = axis_methods + [item for item in methods if "causality" in item["topics"]]
            required, tile_topics = ["contrast"], {}
    return {"observations": facts, "methods": methods, "requiredTopics": required, "concise": not detailed,
            "tileTopics": tile_topics, "comparisonFields": comparison_fields, "comparisonPairs": pairs}, values


def assemble_answer(answer: ScientificAnswer, catalogue: dict, values: dict, evidence: list[Evidence], *, fallback=False):
    selected = []
    compared_rows = {ref.split('f')[0] for pair in answer.comparisons for ref in (pair.left.strip('{}'), pair.right.strip('{}'))}
    for role, ids in (("observations", answer.observations), ("methods", answer.methods)):
        allowed = {item["id"]: item for item in catalogue[role]}
        for ref in dict.fromkeys(ids):
            if ref not in allowed:
                raise ValueError("Select only supplied sentence IDs in their correct role.")
            item = allowed[ref]
            if role == "observations" and catalogue.get("concise") and ref in compared_rows and item.get("topics") == ["results"]:
                continue
            selected.append((role, item))
    for comparison in answer.comparisons:
        pair = {"left": comparison.left, "right": comparison.right}
        if pair not in catalogue["comparisonPairs"]:
            raise ValueError("Select an advertised compatible comparison pair.")
        text = _comparison(comparison.left, comparison.right, values, evidence)
        source = comparison.left.strip("{}").split("r")[0]
        owner = evidence[int(source[1:])].tool
        if owner.startswith(_GROUPED_OWNERS):
            text = tile_prefix(owner) + text
        selected.append(("observations", {"text": text, "source": source, "topics": ["results"]}))
    if not selected:
        raise ValueError("Select a supplied observation or method sentence.")
    # Coverage is checked by the app, not by a model's self-reported 'answered' flag.
    requirements = [(None, topic) for topic in catalogue["requiredTopics"]]
    requirements += [(source, topic) for source, topics in catalogue["tileTopics"].items() for topic in topics]
    unresolved: dict[str, list[str | None]] = {}
    for source, topic in requirements:
        if any(topic in item.get("topics", []) and (source is None or item.get("source") == source) for _, item in selected):
            continue
        candidates = [item for role in ("observations", "methods") for item in catalogue[role]
                      if topic in item["topics"] and (source is None or item.get("source") == source)]
        if candidates:
            role = "observations" if candidates[0] in catalogue["observations"] else "methods"
            selected.append((role, candidates[0]))
        else:
            unresolved.setdefault(_TOPICS.get(topic, ("", "results"))[1], []).append(source)
    selected.extend(_unresolved_items(unresolved, evidence))
    contrasts = {item.get("source") for role, item in selected if item.get("kind") == "volcano_contrast"}
    # The direction sentence already states the contrast and its sign.
    directed = {item.get("source") for role, item in selected if str(item.get("id", "")).endswith("d") and "direction" in item.get("topics", [])}
    paragraphs, groups, prefixes = [], {}, {}
    role_order = {"observations": 0, "methods": 1, "limitations": 2}
    for role, item in selected:
        replacement_topics = {topic for other_role, other in selected if other_role == "methods" and other.get("id") in item.get("replacedBy", []) for topic in other.get("topics", [])}
        if role == "methods" and ((item.get("replacedBy") and set(item["topics"]) <= replacement_topics) or
                (item.get("kind") == "volcano_formula" and item.get("source") in contrasts)
                or (item.get("kind") == "volcano_contrast" and item.get("source") in directed)):
            continue
        source = item.get("source")
        owner = evidence[int(source[1:])].tool if source and source[1:].isdigit() and int(source[1:]) < len(evidence) else ""
        prefix = tile_prefix(owner) if owner.startswith(_GROUPED_OWNERS) else ""
        text = item["text"]
        if prefix:
            # One paragraph per canvas tile, results before methods, with the
            # tile named once (iteration 22: "Tile 1 (volcano): ..." repeated on
            # every sentence and a tile's facts were split across paragraphs).
            key = ("tile", int(source[1:]), source)
            prefixes[key] = prefix
            text = text[len(prefix):] if text.startswith(prefix) else text
            order = role_order.get(role, 3)
        else:
            key = (role, source or item.get("id", "limitations"))
            order = 0
        groups.setdefault(key, [])
        if (order, text) not in groups[key]:
            groups[key].append((order, text))
    tiles = sorted(key for key in groups if key[0] == "tile")
    ordered = [key for key in groups if key[0] != "tile"]
    # Tile paragraphs keep their canvas order where the first tile sentence stood.
    first_tile = next((index for index, key in enumerate(groups) if key[0] == "tile"), len(ordered))
    ordered[first_tile:first_tile] = tiles
    for key in ordered:
        sentences = [text for _, text in sorted(groups[key], key=lambda pair: pair[0])]
        paragraph = prefixes.get(key, "")
        for sentence in sentences:
            if paragraph.strip() and paragraph != prefixes.get(key, "") and len(paragraph) + len(sentence) > 1000:
                paragraphs.append(paragraph.strip())
                paragraph = prefixes.get(key, "")
            paragraph = (paragraph + " " + sentence) if paragraph and not paragraph.endswith(": ") else paragraph + sentence
        paragraphs.append(paragraph.strip())
    for hypothesis in answer.hypotheses:
        if "{{" in hypothesis or "}}" in hypothesis:
            raise ValueError("Hypotheses cannot introduce evidence references or observations.")
    # Only model-written hypotheses go through prose validation; factual/method text is app-owned.
    paragraphs.extend(render_hypotheses(answer.hypotheses, evidence_entity_names(evidence)))
    used = {int(item["source"][1:]) for _, item in selected
            if isinstance(item.get("source"), str) and item["source"][1:].isdigit()}
    paragraphs.extend(evidence_qualifications(evidence, used or None))
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
