"""Natural answer templates with values resolved exclusively from supplied evidence."""
import json
import re
from decimal import Decimal, InvalidOperation

from app.schemas.assistant import Evidence

_REFERENCE = re.compile(r"\{\{(e\d+r\d+(?:f\d+)?|c\d+)\}\}")
_NUMBER = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)?")
_DIMENSION = re.compile(r"(?<![\w.+-])(?:2D|3D)(?![\w.%])", re.I)

_METHOD_FIELDS = frozenset({"method", "selected_test_description", "SD", "scale", "source",
    "log2_uploads", "for_significance", "for_y_axis", "x", "y", "log2FC", "whiskers", "outliers"})
_METHOD_WORDING = {
    "mean_condition2_minus_mean_condition1": "mean log2 intensity in the second condition minus that in the first",
    "negative_log10_of_selected_p_metric": "negative log10 of the selected p-value metric",
    "neg_log10_adj_pval": "negative log10 of the BH-adjusted p-value",
    "neg_log10_pval": "negative log10 of the raw p-value",
    "adj_pval": "BH-adjusted p-value", "pval": "raw p-value",
    "unpaired_student_t_test_with_pooled_variance": "unpaired Student's t-test with pooled variance",
    "unpaired_welch_t_test_with_unequal_variance": "unpaired Welch's t-test allowing unequal variances",
    "paired_student_t_test_on_within_pair_differences": "paired Student's t-test on within-pair differences",
    "paired_experimental_differences_with_propagated_control_variance": "paired experimental differences with propagated control variance",
    "unpaired_propagated_variance_with_satterthwaite_degrees_of_freedom": "unpaired comparison with propagated variance and Satterthwaite degrees of freedom",
    "benjamini_hochberg_fdr_control": "Benjamini–Hochberg false discovery rate correction",
    "sample_standard_deviation_ddof_1": "sample standard deviation, using one fewer than the number of observations as the variance divisor",
    "linear_intensity": "linear intensity",
    "normalized_unfiltered_non_imputed_data_back_transformed_to_linear": "the normalized, unfiltered, non-imputed data back-transformed to the linear scale",
    "back_transformed_to_linear": "back-transformed to linear intensity",
    "outermost_observed_values_within_the_1.5_IQR_fences": "outermost observed values within the 1.5 × IQR fences",
    "observations_outside_the_fences": "observations outside the fences",
}


def _method_wording(name: str, value: str) -> str:
    # Never rewrite identifiers, labels or arbitrary uploaded text.
    return _METHOD_WORDING.get(value, value) if name in _METHOD_FIELDS else value

_CONTEXT_KEYS = frozenset({
    "workflow", "dataset_level", "entity", "source", "source_used", "data_source",
    "scale", "unit", "units", "test", "test_type", "selected_test", "method",
    "condition1", "condition2", "condition1_control", "condition2_control",
    "use_uncorrected", "for_significance", "for_y_axis", "direction",
    "selected_p_metric", "p_value_threshold", "selected_cluster", "requested_clusters", "post_hoc",
    "pValueThreshold", "log2fcThreshold", "varianceMultiplier", "sampleSizeOverride",
    "useUncorrected", "testType", "dataSource",
})


def evidence_context(text: str) -> dict[str, dict[str, str]]:
    """Keep adapter-reported settings before result rows are budgeted away."""
    context = {}
    for line in text.splitlines():
        label, *parts = line.split("|")
        if label == "volcano_contrast":
            context[label] = {"direction": "|".join(parts)}
            continue
        if not label.endswith(("_overview", "_formula", "_parameters", "_testing",
                               "_comparison", "_selected_p_metric", "_multiple_testing", "_tested")):
            continue
        fields = {key.strip(): value.strip() for part in parts if "=" in part
                  for key, value in [part.split("=", 1)] if key.strip() in _CONTEXT_KEYS}
        if fields:
            context[label] = fields
    return context


def _field_meaning(label: str, name: str, context: dict) -> dict[str, str]:
    if label in {"cov_condition", "cov_answer_summary"} and name.endswith("_cv"):
        return {"metric": "coefficient of variation", "summary": name[:-3], "unit": "percent"}
    if label == "volcano_term":
        selected = context.get("volcano_selected_p_metric", {})
        if name == "log2FC":
            return {"metric": "log2 fold change", "unit": "log2 ratio"}
        if name in {"selected_p_value", "minus_log10_selected_p"}:
            metric = selected.get("for_significance", "unknown selected p-value metric")
            return {"metric": metric, "unit": "dimensionless",
                    "transformation": "negative log10" if name.startswith("minus") else "none"}
    return {}


def answer_facts(evidence: list[Evidence]) -> tuple[list[dict], dict[str, str]]:
    sources, values = [], {}
    budget = 14000 // max(1, len(evidence))
    for i, item in enumerate(evidence):
        facts = []
        if item.status == "unavailable":
            sources.append({"tool": item.tool, "status": item.status, "facts": [],
                            "limitation": "No usable calculated evidence is available for this selection."})
            continue
        context = item.context or evidence_context(item.text)
        remaining = budget - len(json.dumps(context, ensure_ascii=True))
        if remaining <= 0:
            if item.status == "available":
                item.status = "partial"
            sources.append({"tool": item.tool, "status": item.status, "facts": [],
                            "limitation": "Scientific context exceeds the evidence budget; no values supplied."})
            continue
        for j, line in enumerate(item.text.splitlines()):
            if not line.strip():
                continue
            key = f"e{i}r{j}"
            label, *parts = line.split("|")
            readable_parts = []
            for part in parts:
                if "=" not in part:
                    readable_parts.append(part)
                    continue
                name, value = (piece.strip() for piece in part.split("=", 1))
                display = _method_wording(name, value)
                if _field_meaning(label, name, context).get("unit") == "percent":
                    display += "%"
                readable_parts.append(f"{name.replace('_', ' ').lower()}: {display}")
            statement = label.replace('_', ' ').capitalize() + ": " + "; ".join(readable_parts) + "." if parts else line
            row_values = {key: statement}
            fields = []
            for k, part in enumerate(line.split("|")[1:]):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                field_key = f"{key}f{k}"
                row_values[field_key] = value.strip()
                field = {"ref": field_key, "name": name.strip(), "value": _method_wording(name.strip(), value.strip())}
                meaning = _field_meaning(line.split("|", 1)[0], name.strip(), context)
                if meaning:
                    field["meaning"] = meaning
                fields.append(field)
            fact = {"ref": key, "fields": fields, "statement": statement if not fields else line.split("|", 1)[0]}
            size = len(json.dumps(fact, ensure_ascii=True)) + 2
            if size > remaining:
                if item.status == "available":
                    item.status = "partial"
                continue
            remaining -= size
            values.update(row_values)
            facts.append(fact)
        readable_context = {label: {name: _method_wording(name, value) for name, value in fields.items()}
                            for label, fields in context.items()}
        sources.append({"tool": item.tool, "status": item.status, "context": readable_context, "facts": facts})
    return sources, values



def _comparison(left: str, right: str, values: dict[str, str], evidence: list[Evidence]) -> str:
    # Both spellings refer to the same supplied field; neither permits literal values.
    def reference(value):
        match = _REFERENCE.fullmatch(value)
        return match[1] if match else value
    left, right = reference(left), reference(right)
    def field(ref):
        match = re.fullmatch(r"e(\d+)r(\d+)f(\d+)", ref)
        if match and int(match[1]) < len(evidence) and evidence[int(match[1])].status == "unavailable":
            raise ValueError("Unavailable evidence cannot support a comparison.")
        if ref not in values or not match:
            raise ValueError("A comparison must reference supplied numerical fields.")
        source, row, column = map(int, match.groups())
        label, *parts = evidence[source].text.splitlines()[row].split("|")
        name = parts[column].split("=", 1)[0].strip()
        fields = dict(part.strip().split("=", 1) for part in parts if "=" in part)
        subject_keys = ("sample", "identifier", "term", "condition", "Condition")
        if label == "cov_condition":
            subject_keys = ("name",)
        subject = next(((key, fields[key]) for key in subject_keys if fields.get(key)), None)
        try:
            number = Decimal(values[ref])
        except InvalidOperation:
            raise ValueError("These values cannot be compared numerically.") from None
        if not number.is_finite() or not subject:
            raise ValueError("A comparison needs finite values and identified subjects.")
        return source, name, fields, subject, number, label

    a, b = field(left), field(right)
    qualifiers = _CONTEXT_KEYS | {"metric", "contrast", "adjustment", "transformation"}
    if a[:2] != b[:2] or a[5] != b[5] or a[3][0] != b[3][0] or a[3][1] == b[3][1] or any(a[2].get(key) != b[2].get(key) for key in qualifiers):
        raise ValueError("Compare the same metric and settings for two distinct subjects.")
    relation = "higher than" if a[4] > b[4] else "lower than" if a[4] < b[4] else "equal to"
    metric = a[1].replace("_", " ").lower()
    item = evidence[a[0]]
    meaning = _field_meaning(a[5], a[1], item.context or evidence_context(item.text))
    if meaning:
        metric = meaning["metric"]
        if metric.startswith("unknown"):
            raise ValueError("The selected p-value metric is unavailable; do not compare it.")
        metric = {"pval": "raw p-value", "adj_pval": "BH-adjusted p-value"}.get(metric, metric)
        if meaning.get("summary"):
            metric = meaning["summary"] + " " + metric
        if meaning.get("transformation") == "negative log10":
            metric = "negative log10 " + metric
    suffix = "%" if meaning.get("unit") == "percent" else ""
    return f"The {metric} for {a[3][1]} ({values[left]}{suffix}) is {relation} that for {b[3][1]} ({values[right]}{suffix})."


def render_hypotheses(hypotheses: list[str]) -> list[str]:
    result = []
    for text in hypotheses:
        if not text.strip():
            continue
        if "{{" in text or "}}" in text or _NUMBER.search(_DIMENSION.sub("dimension", text)):
            raise ValueError("Hypotheses cannot introduce numerical claims or evidence references.")
        result.append("One possible explanation—not established by these results—is: " + text.strip())
    return result


def evidence_qualifications(evidence: list[Evidence], used: set[int] | None = None) -> list[str]:
    """Caveats a person needs, for the evidence the answer actually used.

    Round 34: a truncated tile made every canvas answer end with "Only part
    of the available evidence is included; this is not an exhaustive
    assessment." -- including answers that quoted nothing from the truncated
    source, and conceptual answers that quoted no numbers at all. The caveat is
    now tied to the sources the answer drew on and worded as a person would.
    """
    qualifications = []
    for index, item in enumerate(evidence):
        if used is not None and index not in used:
            continue
        for line in item.text.splitlines():
            if line.startswith(("Requested module uses default settings", "Entity lookup uses the application's data source")) or "default module settings (not current UI selections)" in line:
                qualifications.append(line)
        if item.status == "partial":
            qualifications.append("I read part of the result here, not every row of it, so take this as a read of what is shown rather than a complete assessment.")
        if item.status == "unavailable":
            qualifications.append("Some of what you asked about is not available for this selection.")
    return list(dict.fromkeys(qualifications))
