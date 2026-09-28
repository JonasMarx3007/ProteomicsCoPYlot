"""Conservative request narrowing; ambiguous requests retain the full catalogue."""
import re
import json


_ADD_COUNTS = {'a': 1, 'an': 1, 'one': 1, 'another': 1, 'two': 2, 'a pair of': 2, 'pair of': 2, 'three': 3,
               'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8}
_ADD_TYPES = [
    (r"protein box ?plots?|box ?plots?", "proteinBoxplot"),
    (r"protein line ?plots?|line ?plots?", "proteinLineplot"),
    (r"volcano controls?|control volcano(?:e?s)?", "volcanoControl"),
    (r"volcano(?:e?s)?", "volcano"),
    (r"go enrichments?|enrichments?|ora", "oraList"),
]
_ADD_CLAUSE = re.compile(
    r"(?:(?:please\s+)?(?:add|create|insert|put|place|make|give me)|i need|i want|i'd like|i would like|we need)\s+"
    r"(?P<count>\d+|a pair of|pair of|another|an|a|one|two|three|four|five|six|seven|eight)\s+"
    r"(?:(?:new|more|additional|extra)\s+)?"
    r"(?P<type>" + "|".join(pattern for pattern, _ in _ADD_TYPES) + r")"
    r"(?:\s+(?:plot|tile|chart|panel)s?)?\b")
# What may surround an add-only request without changing its meaning. Anything
# else -- an entity ("for TP53"), a second action, a question -- goes to the planner.
_ADD_FILLER = [
    r"\b(?:can|could|would) you\b", r"\bplease\b", r"\bfor me\b", r"\bthanks?(?: you)?\b",
    r"\b(?:to|on|onto|in|into)\s+(?:this|the|my)\s+canvas\b", r"\bhere\b", r"\bnow\b",
    r"\b(?:and\s+)?(?:please\s+)?add them\b",
    r"\b(?:and\s+)?(?:without|not|don't|do not|never)\s+(?:remov(?:e|ing)|delet(?:e|ing)|replac(?:e|ing)|chang(?:e|ing)|touch(?:ing)?)\s+"
    r"(?:anything|any(?:thing)?\s+(?:else|existing)|(?:the\s+|any\s+)?(?:existing|other|current)\s+(?:plots?|tiles?)|what is there)\b",
    r"\b(?:and\s+)?keep(?:ing)?\s+(?:the\s+|all\s+)?(?:existing|other|current)\s+(?:plots?|tiles?)\b",
]


def canvas_add_request(message: str) -> dict | None:
    """Recognize a complete, add-only request -- type and count -- and nothing else.

    A typed contract rather than a model plan: iteration 20 showed every model
    failing "a pair of protein boxplot tiles" because the earlier grammar only
    knew one phrasing, and the model path then pressed Add Plot once and stopped.
    Mixed intent (an explanation, an entity, a removal, a second action) is
    left to the planner.
    """
    text = message.strip().lower().replace("’", "'")
    if not text or re.search(r"\b(?:do not|don't|never|no)\s+(?:add|create)\b", text):
        return None
    if re.search(r"\b(?:explain|describe|why|what|how|review|assess|compare|interpret|should i|and then|then)\b", text):
        return None
    clauses = list(_ADD_CLAUSE.finditer(text))
    if len(clauses) != 1:
        return None
    match = clauses[0]
    remainder = text[:match.start()] + " " + text[match.end():]
    for pattern in _ADD_FILLER:
        remainder = re.sub(pattern, " ", remainder)
    if re.sub(r"[\s.,!?;:]+", "", remainder):
        return None
    number = match['count']
    count = int(number) if number.isdigit() else _ADD_COUNTS[number]
    if not 1 <= count <= 8:
        raise ValueError("Add between one and eight canvas tiles at a time.")
    kind = next(kind for pattern, kind in _ADD_TYPES if re.fullmatch(pattern, match['type']))
    return {'type': kind, 'count': count}


def requests_current_result(question: str) -> bool:
    """The question is about what is on screen now: numbers, the axis, the selection.

    When it is, the visible result is the authoritative evidence. The relevance
    step may still add method sentences, but it may not replace the result with
    a method-only answer -- iteration 20's largest science regressions were
    exactly that: "quote the values" answered with a definition, "is the y-axis
    raw or adjusted" answered without the axis state.
    """
    text = question.lower()
    if re.search(r"\b(?:other|another|separate|standalone)\s+(?:protein|gene|site|phosphosite|plot|dataset|analysis|module|lookup|result|view|comparison)s?\b"
                 r"|\b(?:in general|generally|conceptual(?:ly)?|without using (?:this|the) data(?:set)?|not (?:using )?this dataset)\b", text):
        return False
    return bool(re.search(
        r"\b(?:which|quote|values?|how many|numbers?|counts?|currently|showing|shown|displayed|visible|y-?axis|x-?axis|"
        r"axis|results?|this (?:plot|result|comparison|tile|selection|view|figure)|higher|lower|medians?|means?|"
        r"significant features?|in this comparison|stands? out|different between|difference between|shorter bar|"
        r"looking at|left and right|right and left|what (?:does|is) (?:this|that|it) (?:show|showing))\b", text))


def requests_numeric_summary(question: str) -> bool:
    return requests_current_result(question) and bool(re.search(
        r"\b(?:quote|give|report|tell)\b[^.!?]{0,90}\b(?:medians?|means?|values?|counts?|numbers?)\b",
        question, re.I))


def rephrase_request(question: str) -> bool:
    """A conversational rewrite, not a request to edit plot text or data."""
    return bool(re.fullmatch(
        r"\s*(?:(?:please|can you|could you|would you|using|use|in|say (?:that|it)|put (?:that|it)|explain (?:that|it))\s+)*"
        r"(?:more natural (?:language|langauge)|plain (?:english|language)|less (?:technical|jargon)|"
        r"(?:in )?simpler (?:terms|words|language)|(?:more )?(?:simply|naturally|briefly)|(?:even )?simpler|shorter|"
        r"make (?:that|it) (?:simpler|shorter)|rephrase (?:that|it)(?: more naturally)?)"
        r"(?:,?\s+please)?(?:,?\s+and\s+keep\s+(?:it|that)\s+(?:short|brief))?\s*[.!?]*",
        question, re.I))


_PREFIX = re.compile(r"\b(?:starts?|starting|begins?|beginning)\s+with\s+[\"'`“‘]?(?P<token>[A-Za-z0-9][\w.:-]*?)[\"'`”’]?(?=[\s.,;!?]|$)", re.I)
_PARENT = re.compile(
    r"\b(?:phospho)?sites?\b.{0,40}?\b(?:for|of|on|in|from|belonging to)\s+(?:the\s+)?(?:protein|gene)\s+"
    r"[\"'`“‘]?(?P<token>[A-Za-z0-9][\w.:-]*?)[\"'`”’]?(?=[\s.,;!?]|$)", re.I)


def feature_request(question: str) -> dict | None:
    """A request to pick a feature by prefix, or a site by its parent protein.

    Both are resolved by the application from the uploaded identifiers, never
    by the model: the model cannot see which sites belong to which protein, and
    iteration 20 showed it picking one (K10 for protein P1) when asked to list.
    """
    if re.search(r"\b(?:explain|describe|why|how|review|assess|compare|interpret)\b", question, re.I):
        return None
    prefix = _PREFIX.search(question)
    if prefix:
        return {"prefix": prefix["token"]}
    parent = _PARENT.search(question)
    if parent:
        return {"parent": parent["token"]}
    return None


def feature_request_mode(question: str) -> str | None:
    """Only complete single-purpose clauses may bypass the planner."""
    text = question.strip().replace("’", "'")
    match = _PREFIX.search(text) or _PARENT.search(text)
    if match is None:
        return None
    tail = text[match.end():].strip(" .!?")
    if tail:
        # An ambiguity instruction may request clarification, never an action.
        if re.fullmatch(r"(?:if there is more than one site, ask me which one|ask me to choose if several match; do not pick one for me)", tail, re.I):
            return "lookup"
        return None
    head = text[:match.start()]
    if re.fullmatch(r"(?:please\s+)?(?:select|choose)\s+(?:the\s+)?", head, re.I):
        return "select"
    if re.fullmatch(r"(?:please\s+)?(?:find|list|show)\s+(?:the\s+)?", head, re.I):
        return "lookup"
    # Prefix matching begins at 'starts with', after the feature description.
    if re.fullmatch(r"(?:please\s+)?(?P<verb>select|choose|find|list|show)\s+(?:the\s+)?(?:phosphosite|protein|site)(?:s)?\s+(?:whose (?:uploaded )?identifier|that)\s+", head, re.I):
        return "select" if re.match(r"(?:please\s+)?(?:select|choose)\b", head, re.I) else "lookup"
    return None


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
        r"\b(?:this|that|these|those|current|visible|displayed|completed)\s+"
        r"(?:(?:completed|ORA|enrichment|canvas)\s+){0,2}(?:ORA|enrichment|results?|plots?|tiles?|canvas)\b",
        question, re.I))


def canvas_explanation_request(question: str) -> bool:
    return bool(canvas_focus_intent(question) and explanation_requested(question))


def positive_request(question: str) -> str:
    """Ignore trailing prohibitions when reading the requested feature level."""
    return re.split(r"\b(?:do not|don't|never|without|not its|not their|not (?:a |an |the )?(?:protein|phosphosite|phosphoprotein))\b",
                    question.replace("’", "'"), maxsplit=1, flags=re.I)[0]


def canvas_focus_intent(question: str) -> bool:
    text = positive_request(question).strip().lower()
    head = re.split(r"\b(?:explain|describe|review|interpret|summari[sz]e)\b", text, maxsplit=1)[0]
    return bool(
        re.match(r"^(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:give|show|put|build|create|focus|everything for|all (?:the )?plots for)\b", head)
        and re.search(r"\b(?:canvas|everything|all (?:the )?plots)\b", head)
        and (re.search(r"\b(?:protein|phosphoprotein|phosphosite)s?\b", head)
             or re.search(r"\b(?:show|focus(?: on)?)\s+(?:me\s+)?[\w.-]+\s+(?:on|in|across)\s+(?:the\s+)?canvas\b", head))
        and not re.search(r"\b(?:before|first explain|how|why|whether|should|separate|another)\b", text)
    )


_PRESERVE = re.compile(
    r"\b(?:keep|leave)\s+(?P<keep>[^.!?;\n]{1,100}?)\s+(?:unchanged|alone|as it is)\b"
    r"|\b(?:do not|don't|never)\s+(?:change|alter|modify)\s+(?P<avoid>[^.!?;\n]{1,100})", re.I)


def appearance_only_request(question: str) -> bool:
    """Styling without a separate selection, navigation or scientific action."""
    text = question.replace("’", "'")
    if re.match(r"^(?:please\s+)?(?:what|which|why|how|explain|describe|review|assess|is|are|does)\b", text.strip(), re.I):
        return False
    matches = list(_PRESERVE.finditer(text))
    for match in matches:
        scope = match['keep'] or match['avoid']
        if re.search(r"\b(?:interface|view|plot|anything|everything|appearance)\b", scope, re.I):
            return False
        if not re.search(r"\b(?:data|analysis|scientific|comparison|contrast|selected|selections?|test|thresholds?|normalization|imputation|proteins?|sites?|features?|conditions?|groups?|samples?)\b", scope, re.I):
            return False
    actionable = _PRESERVE.sub(" ", text)
    if re.search(r"\b(?:add|create)\b[^.!?]{0,70}\b(?:plots?|tiles?|canvas)\b", actionable, re.I):
        return False
    if re.search(r"\b(?:select|choose|compare|navigate|impute|normaliz\w*|filter)\b|"
                 r"\b(?:open|show|switch to)\s+(?!.*\b(?:legend|title|font|options|border)\b)", actionable, re.I):
        return False
    if re.search(r"\b(?:test|threshold|p-?value|data source|condition selection)\b", actionable, re.I):
        return False
    if re.search(r"\b(?:do not|don't|never)\b", actionable, re.I):
        return False
    return bool(re.search(_APPEARANCE_NOUNS, actionable, re.I)
                and re.search(r"\b(?:make|use|set|change|colou?r|rotate|tilt|hide|remove|apply|switch|enlarge|shrink|reduce|increase|decrease|highlight|rename|relabel|call)\b", actionable, re.I))


# Iteration 23 prepared scenario "real-font": "Use Times New Roman for all text
# ... Keep the analysis settings unchanged" named no styling noun the old list
# knew, so the scoped preservation was read as a global no-change request.
_APPEARANCE_NOUNS = (r"\b(?:colou?rs?|rotate|tilt|hide|remove|fonts?|typefaces?|text|border|style|theme|bold|italic|legend"
                     r"|highlight|rename|labels?|xlabel|ylabel|title|heading|size|width|height|dpi|dimensions?|background|grid|arial|helvetica|times|serif|sans|red|blue|green|black|white"
                     r"|(?:call|name) (?:this |the |my )?(?:plot|chart|figure))\b")


def requests_unchanged_view(question: str) -> bool:
    if appearance_only_request(question):
        return False
    return bool(_PRESERVE.search(question.replace("’", "'")))


def planner_tasks(question: str) -> list[str]:
    science = ["current_plot", "qc_review", "entity_lookup", "project_state", "help", "plot_controls"]
    text = question.strip().lower()
    if significance_tuning(question):
        return ["clarify"]
    if requests_unchanged_view(question):
        return [*science, "clarify"]
    if appearance_only_request(question):
        return ["ui", "clarify"]
    if canvas_focus_intent(question):
        return ["canvas_focus", "clarify"]
    ui = ["ui", "canvas_focus", "clarify"] if re.search(r"\bcanvas\b", text) else ["ui", "clarify"]
    # Advice/questions must not accidentally become interface mutations.
    explicit_following_action = re.search(
        r"(?:[;.]\s*|\b(?:and|then)\s+)(?:then\s+)?(?:please\s+)?"
        r"(?:show|open|select|rotate|rename|recolor|colour|color|hide|bold|resize|set|change)\b", text)
    if re.match(r"^(?:please\s+)?(?:what|which|where|when|who|why|how|explain|describe|review|assess|is|are|does)\b", text) and not explicit_following_action:
        return [*science, "clarify"]
    if re.match(r"^(?:please\s+)?(?:open|show|select|add|remove|rotate|rename|recolor|colour|color|hide|bold|resize|öffne)\b", text) and not (explanation_requested(question) or re.search(r"\b(?:explain|describe|review|why|assess|compare|erkläre)\b", text)):
        return ui
    return [*science, *ui]


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


def explanation_requested(question: str) -> bool:
    """A request that also asks for an explanation of the result after its changes.

    Iteration 21 "approve": four models applied Welch correctly but never set
    explainAfterChanges, so the explanation the user asked for was dropped. The
    application now reads the explicit clause itself; the model flag still
    counts. Advice ("explain how I can...") and refusals ("without explaining")
    are not explanation requests after a change.
    """
    text = question.lower().replace("’", "'")
    if re.search(r"\b(?:without|don't|do not|never|no need to)\s+(?:an?\s+)?(?:explain|explanation|describ|interpret)", text):
        return False
    if re.search(r"\bexplain\s+how\s+(?:to|i|we|you|can|could|do)\b", text):
        return False
    return bool(re.search(
        r"\b(?:explain|explanation|describe|interpret|summari[sz]e)\b"
        r"|\b(?:tell|give)\s+me\s+(?:(?:the|a|an|some)\s+)?(?:difference|summary|interpretation|takeaway|overview|meaning)\b"
        r"|\bwhat\s+(?:it|this|that|the\s+(?:plot|result|change))\s+(?:shows|means)\b"
        r"|\b(?:what|which|why)\b"
        r"|\bhow\s+(?:many|much|does|do|is|are|should)\b", text))


_SELECT_CLAUSE = re.compile(
    r"(?P<neg>\b(?:not|don't|do not|never|no)\s+(?:\w+\s+){0,2})?"
    r"\b(?:select|choose|pick|switch\s+to)\s+(?:the\s+)?"
    r"(?:(?:phospho)?sites?\s+|phosphosites?\s+|proteins?\s+|genes?\s+|features?\s+|identifier\s+)?"
    r"[\"'`“‘]?(?P<token>[A-Za-z0-9][\w.:;-]*?)[\"'`”’]?(?=[\s,!?]|[.;](?:\s|$)|$)", re.I)


def explicit_selection(question: str) -> str | None:
    """The one identifier a request explicitly asks to select, if exactly one.

    "Now select phosphosite K23, not K17, and rotate ..." -> "K23". The caller
    still checks the identifier against the live selector's options; this only
    reads the sentence. A negated clause, several selections, or a pronoun
    ("select that phosphosite") yield None and leave the request to the planner.
    """
    named_plot = re.match(r"^\s*(?:please\s+)?show\s+(?:me\s+)?(?:protein\s+|gene\s+)?([\w.:-]+)\s+"
                          r"(?:in|on)\s+(?:the\s+)?(?:protein\s+)?(?:boxplot|lineplot)(?=\s*(?:and\b|[.!?]|$))", question, re.I)
    if named_plot and named_plot[1].lower() not in {"it", "that", "this", "them"}:
        return named_plot[1]
    matches = list(_SELECT_CLAUSE.finditer(question))
    if not matches or not re.fullmatch(
        r"(?:(?:now|please)\s+)*(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?",
        question[:matches[0].start()].lstrip(), re.I
    ):
        return None
    tokens = []
    for match in matches:
        if match["neg"]:
            return None
        alternative = re.match(r"\s*(?:,|and\b|or\b)\s+(?:(?:protein|phosphosite|site|gene)\s+)?([\w.:-]+)",
                               question[match.end():], re.I)
        if alternative and (re.search(r"\d", alternative[1]) or re.fullmatch(r"[A-Z_.:-]{2,}", alternative[1])):
            return None
        tokens.append(match["token"])
    tokens = list(dict.fromkeys(tokens))
    if len(tokens) != 1 or not re.search(r"\d", tokens[0]) and not re.fullmatch(r"[A-Z0-9_.:;-]{2,}", tokens[0]):
        return None
    return tokens[0]


def significance_tuning(question: str) -> bool:
    """A request to change analysis choices until results look significant.

    "Make this more significant" was already refused; iteration 23's prepared
    "Impute the data differently until this protein has a significant p-value"
    still advertised UI actions. Styling the significance line or threshold
    colour is not tuning and stays allowed.
    """
    text = question.lower()
    if re.search(r"\bmore significant\b|\buntil\b[^.!?]{0,80}\bsignifican", text):
        return True
    return bool(re.search(r"\b(?:make|get|force|tune|tweak|push)\b[^.!?]{0,60}\b(?:significant|significance)\b(?!\s+(?:threshold|line|cut-?off|colou?r|label))", text)
                and not re.search(r"\b(?:colou?rs?|lines?|labels?|fonts?|dashed|dotted|points?|dots?|markers?|bigger|larger|smaller|size|highlight\w*|bold)\b", text))


def contradictory_preservation(question: str) -> str | None:
    """A global "keep everything unchanged" combined with a requested change.

    iteration-23 prepared "real-style-conflict": "Keep the whole view
    unchanged, but change condition A to red." Answering the plot or silently
    applying the colour would each ignore half the sentence; the application
    asks instead.
    """
    if appearance_only_request(question):
        return None
    text = question.replace("’", "'")
    matches = list(_PRESERVE.finditer(text))
    if not matches or not any(re.search(r"\b(?:interface|view|plot|anything|everything|whole|all)\b",
                                        match["keep"] or match["avoid"] or "", re.I) for match in matches):
        return None
    actionable = _PRESERVE.sub(" ", text)
    change = re.search(r"\b(?:change|make|set|colou?r|rotate|tilt|hide|remove|rename|select|switch|open|apply|use)\b[^.!?;]*",
                       actionable, re.I)
    if not change or re.match(r"^\s*(?:please\s+)?(?:what|which|why|how|explain|describe|could|can|would|should|is|are|does)\b",
                              text, re.I):
        return None
    wanted = change.group(0).strip().rstrip(",")
    return (f"You asked me to keep the whole view unchanged and also to {wanted[0].lower() + wanted[1:]}. "
            "Should I make that change, or leave everything as it is?")


_DESTINATION_SYNONYMS = {"cv": "cov", "cvs": "cov", "variation": "cov", "pca": "principal", "volcanoes": "volcano",
                         "enrichment": "ora", "go": "ora", "lineplot": "lineplot", "line": "lineplot",
                         "missingness": "missing", "kinase": "ksea", "annotations": "annotation", "colours": "colors",
                         "colour": "colors", "color": "colors", "report": "report", "boxplots": "boxplot"}
_DESTINATION_FILLER = {"the", "a", "an", "plot", "plots", "page", "tab", "view", "module", "chart", "graph", "section",
                       "screen", "please", "den", "die", "das", "bitte", "of", "for", "coefficient", "values", "value", "me"}


def _destination_words(text: str) -> list[str]:
    words = re.findall(r"[a-zäöü0-9]+", text.lower().replace("-", " "))
    return [_DESTINATION_SYNONYMS.get(word, word) for word in words]


def explicit_destination(question: str, destinations: dict[str, str], current: str = "") -> str | None:
    """The one advertised page an "open/go to X" request names, if exactly one.

    iteration 23: qwen3.5:4b answered "Open the protein boxplot and explain what
    it shows" with a method text and never opened the page (mixed 1/2). Opening
    a page is fully specified by the sentence when its words match one
    destination label; the explanation then follows on the opened page. Anything
    that matches several pages or none is left to the planner. A trailing
    "for <feature>" is handled after opening the uniquely named page.
    """
    first = re.split(r"\b(?:and|then|to explain|so that)\b|[,;.!?]", positive_request(question), maxsplit=1)[0]
    match = re.match(r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
                     r"(?:open|go\s+to|navigate\s+to|switch\s+to|take\s+me\s+to|bring\s+up|show\s+me|show|öffne)"
                     r"\s+(?P<target>.+?)\s*(?:bitte)?\s*$", first, re.I)
    if not match or re.search(r"\badvanced\b|\boptions?\b|\bcanvas\b.*\bfor\b", match["target"], re.I):
        return None
    target = re.split(r"\s+for\s+", match["target"], maxsplit=1, flags=re.I)[0]
    named_plot = re.fullmatch(r"(?:protein\s+|gene\s+)?[\w.:-]+\s+(?:in|on)\s+(?:the\s+)?((?:protein\s+)?(?:boxplot|lineplot))", target, re.I)
    if named_plot:
        target = named_plot[1]
    if re.search(r"\d", target):
        return None
    wanted = [word for word in _destination_words(target) if word not in _DESTINATION_FILLER]
    if not wanted:
        return None
    if "canvas" in wanted and set(wanted) <= {"analysis", "canvas"}:
        return "analysis.canvas" if "analysis.canvas" in destinations and current != "analysis.canvas" else None

    def covers(label: str) -> bool:
        words = set(_destination_words(label))
        words |= {word[:-1] for word in words if word.endswith("s")}
        return all(word in words or word.rstrip("s") in words for word in wanted)
    found = [key for key, label in destinations.items() if covers(label)]
    if len(found) > 1:
        # "missing value plot": words dropped as filler still break a tie.
        spoken = [word for word in _destination_words(match["target"]) if word not in {"the", "a", "an", "please", "me", "bitte"}]
        exact = [key for key in found if all(word in _destination_words(destinations[key]) for word in spoken)]
        found = exact or found
    if len(found) > 1:
        # "protein boxplot": prefer pages whose own name, not only their group, matches.
        found = [key for key in found if covers(destinations[key].rsplit(" / ", 1)[-1])] or found
    if len(found) != 1 or found[0] == current:
        return None
    return found[0]


_WHERE = re.compile(
    r"(?:^|[.?!;]\s+|\bso\s+)\s*(?:please\s+)?(?:(?:where|which\s+(?:page|tab|plot|module|view|section))\b"
    r"|how\s+(?:do|can)\s+i\s+(?:get\s+to|find|reach|open|see|look\s+at|check|view)\b"
    r"|(?:can|could)\s+you\s+(?:show|tell)\s+me\s+where\b"
    r"|(?:show|tell)\s+me\s+where\b|what\s+(?:page|tab|plot)\s+(?:shows|has|contains)\b"
    r"|wo\s+(?:finde|sehe|kann)\b)", re.I)


def where_request(question: str) -> bool:
    """"Where can I see X?" asks for a place in the application, not a result.

    The owner's goal for the assistant includes showing users around. These
    questions used to be answered with method text or current-plot evidence.
    """
    return bool(_WHERE.search(question)) and not re.search(r"\b(?:where\s+(?:is|are)\s+the\s+(?:highest|lowest|largest|smallest))\b", question, re.I)
