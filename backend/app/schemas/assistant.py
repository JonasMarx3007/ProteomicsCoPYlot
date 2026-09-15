from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chat import ChatRequest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UiControl(StrictModel):
    permission: Literal["view", "confirm"] = "confirm"
    id: str = Field(max_length=160)
    label: str = Field(max_length=600)
    type: Literal["text", "number", "color", "checkbox", "select", "multiple", "button"]
    value: str | bool | list[str]
    options: list[str] = Field(default_factory=list, max_length=80)
    optionCount: int = 0
    optionQuery: str = Field(default="", max_length=120)
    optionMatchCount: int = Field(default=0, ge=0)
    min: float | None = None
    max: float | None = None


class AssistantView(StrictModel):
    module: str = Field(max_length=160)
    workflow: str = Field(default="", max_length=40)
    mode: str = Field(default="", max_length=16_384)
    controls: list[UiControl] = Field(default_factory=list, max_length=250)
    destinations: dict[str, str] = Field(default_factory=dict, max_length=80)
    advancedOptions: bool = False


class UiAction(StrictModel):
    type: Literal["navigate", "set_control", "advanced_options", "search_options", "activate_control", "focus_canvas", "add_canvas_tiles"]
    target: str = Field(default="", max_length=160)
    value: str | bool | list[str] = ""


class ConversationSelection(StrictModel):
    label: str = Field(max_length=600)
    value: str | bool | list[str]


class ConversationState(StrictModel):
    request: str = Field(max_length=1000)
    module: str = Field(max_length=160)
    workflow: str = Field(max_length=40)
    selections: list[ConversationSelection] = Field(max_length=12)
    completed: list[str] = Field(max_length=8)
    status: Literal["completed", "incomplete", "interrupted", "declined", "needs_clarification"]


class AssistantRequest(ChatRequest):
    answerOnly: bool = False
    conversationState: ConversationState | None = None
    view: AssistantView
    receipts: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def bound_assistant_input(self):
        memory_size = len(self.conversationState.model_dump_json()) if self.conversationState else 0
        if memory_size > 6500 or len(self.view.model_dump_json()) + sum(map(len, self.receipts)) + memory_size > 48_000:
            raise ValueError("The assistant view exceeds the input limit.")
        return self


class CanvasFocusRequest(StrictModel):
    kind: Literal["protein", "phospho", "phosprot"]
    query: str = Field(min_length=1, max_length=200)
    allSites: bool = False
    conditions: list[str] = Field(default_factory=list, max_length=2)


class AssistantPlan(StrictModel):
    explainAfterChanges: bool = False
    task: Literal["current_plot", "qc_review", "entity_lookup", "project_state", "help", "ui", "clarify", "canvas_focus"]
    focus: CanvasFocusRequest | None = None
    module: str = Field(default="", max_length=160)
    query: str = Field(default="", max_length=512)
    actions: list[UiAction] = Field(default_factory=list, max_length=4)
    clarification: Literal["", "entity", "condition", "control", "tile", "sequence", "scientific_choice", "request"] = ""
    responseStyle: Literal["concise", "explanation", "review"] = "concise"


class Evidence(StrictModel):
    tool: str
    status: Literal["available", "partial", "unavailable"]
    text: str
    context: dict[str, dict[str, str]] = Field(default_factory=dict)


class EvidenceComparison(StrictModel):
    left: str = Field(max_length=80, description="Supplied numeric field reference, e.g. e0r1f2 (not a value).")
    right: str = Field(max_length=80, description="Comparable numeric field reference, e.g. e0r2f2 (not a value).")




class ScientificAnswer(StrictModel):
    observations: list[str] = Field(default_factory=list, max_length=4, description="Exact IDs of supplied result sentences.")
    methods: list[str] = Field(default_factory=list, max_length=4, description="Exact IDs of supplied method/limitation sentences.")
    comparisons: list[EvidenceComparison] = Field(default_factory=list, max_length=2)
    hypotheses: list[str] = Field(default_factory=list, max_length=2, description="Optional tentative explanations, not observed results or method definitions.")

    @model_validator(mode="after")
    def bound_text(self):
        if any(len(ref) > 80 for ref in [*self.observations, *self.methods]) or sum(map(len, self.hypotheses)) > 1000:
            raise ValueError("The answer is too long.")
        return self


class AssistantResponse(StrictModel):
    usedEvidenceFallback: bool = False
    explainAfterChanges: bool = False
    needsClarification: bool = False
    model: str
    answer: str = ""
    actions: list[UiAction] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    revision: int
