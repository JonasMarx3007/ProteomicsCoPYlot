from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.annotation import AnnotationKind

StatsSource = Literal["filtered", "log2", "raw", "imputed"]
# Same vocabulary as VisualizationDataSource; see the note there on "data".
VolcanoDataSource = Literal["data", "auto", "log2", "filtered", "imputed"]
AnovaSource = Literal["anova", "anova_cluster"]
# Post-hoc pairwise test run after a significant omnibus F. Gated on the ANOVA
# threshold, as Perseus and classical practice do it.
AnovaPostHoc = Literal["none", "tukey"]
# Design and variance model in one field, for backwards compatibility: "unpaired"
# and "paired" keep their original meaning (pooled Student's t), so stored
# requests and saved reports resolve to exactly the test they always did.
StatsTestType = Literal[
    "unpaired",
    "unpaired_welch",
    "paired",
]
StatsIdentifier = Literal["workflow", "genes"]
OraDirection = Literal["up", "down", "cluster"]
HeatmapValueType = Literal["log2", "z"]
EnrichmentSource = Literal["volcano", "volcano_control", "anova"]
EnrichmentBackgroundMode = Literal["experiment", "global"]
SimulationSource = Literal["volcano"]
SimulationTestType = Literal["unpaired", "unpaired_welch"]


class IdentifierOption(BaseModel):
    key: StatsIdentifier
    label: str


class StatisticalOptionsResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    imputedAvailable: bool = False
    availableConditions: list[str]
    samplesByCondition: dict[str, list[str]] = Field(default_factory=dict)
    pairIdsBySample: dict[str, str] = Field(default_factory=dict)
    availableIdentifiers: list[IdentifierOption]
    warnings: list[str] = Field(default_factory=list)


class VolcanoRequest(BaseModel):
    kind: AnnotationKind
    dataSource: VolcanoDataSource = "data"
    condition1: str
    condition2: str
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_distinct_conditions(self) -> "VolcanoRequest":
        if self.condition1 == self.condition2:
            raise ValueError("Please select two different conditions.")
        return self


class VolcanoControlRequest(BaseModel):
    kind: AnnotationKind
    dataSource: VolcanoDataSource = "data"
    condition1: str
    condition2: str
    # A blank control is a contradiction on this endpoint: the service treats a
    # falsy control as "no control" and quietly returns an ordinary volcano, so
    # asking for a control-corrected result and leaving one field empty gave a
    # 200 that was byte-identical to the uncorrected one. Two wrong controls
    # already raised; one wrong and one blank did not.
    condition1Control: str = Field(min_length=1)
    condition2Control: str = Field(min_length=1)
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_distinct_conditions(self) -> "VolcanoControlRequest":
        conditions = [
            self.condition1,
            self.condition1Control,
            self.condition2,
            self.condition2Control,
        ]
        normalized = [str(condition).strip() for condition in conditions]
        if len(set(normalized)) != len(normalized):
            raise ValueError(
                "Control-corrected volcano analysis requires four distinct conditions; "
                "an experimental condition cannot be used as its own control."
            )
        return self


class VolcanoResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    labelColumn: str
    totalRows: int
    upregulatedCount: int
    downregulatedCount: int
    notSignificantCount: int
    rows: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class EnrichmentTerm(BaseModel):
    source: str
    termId: str
    name: str
    termSize: int
    intersectionSize: int
    hitPercent: float
    pValue: float
    adjPValue: float
    intersectingGenes: list[str]


class EnrichmentRequest(BaseModel):
    kind: AnnotationKind
    source: EnrichmentSource = "volcano"
    dataSource: VolcanoDataSource = "data"
    condition1: str = ""
    condition2: str = ""
    condition1Control: str | None = None
    condition2Control: str | None = None
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    selectedCluster: int | None = Field(default=None, ge=1)
    nClusters: int = Field(default=4, ge=1, le=100)
    adjPValueCutoff: float = Field(default=0.05, gt=0.0, le=1.0)
    topN: int = Field(default=10, ge=1, le=100)
    minTermSize: int = Field(default=20, ge=1)
    maxTermSize: int = Field(default=300, ge=1)
    backgroundMode: EnrichmentBackgroundMode = "experiment"


class EnrichmentResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    selectedCluster: int | None = None
    clusterGenes: list[str] = Field(default_factory=list)
    clusterTerms: list[EnrichmentTerm] = Field(default_factory=list)
    upGenes: list[str] = Field(default_factory=list)
    downGenes: list[str] = Field(default_factory=list)
    upTerms: list[EnrichmentTerm] = Field(default_factory=list)
    downTerms: list[EnrichmentTerm] = Field(default_factory=list)
    backgroundMode: EnrichmentBackgroundMode
    backgroundGenes: list[str] = Field(default_factory=list)
    backgroundSize: int
    annotatedBackgroundSize: int
    # Organism of the bundled Gene Ontology database, not a detected property of
    # the uploaded data. Queries are matched against this universe regardless of
    # their source species; a low-overlap warning is emitted when they disagree.
    organism: str = Field(
        default="Homo sapiens",
        description="Organism of the Gene Ontology database used for enrichment.",
    )
    # Applies to the enrichment TERM p-values, which are always BH-corrected.
    # It does not describe the upstream volcano/ANOVA test, which has its own
    # useUncorrected switch.
    correctionMethod: str = Field(
        default="Benjamini-Hochberg",
        description="Multiple-testing correction applied to enrichment term p-values.",
    )
    upstreamCorrectionMethod: str = Field(
        default="Benjamini-Hochberg",
        description="Multiple-testing correction used to select the upstream volcano/ANOVA genes.",
    )
    databaseSha256: str
    # Terms passing the size filter -- the search space, not the
    # Benjamini-Hochberg denominator. Correction runs over the terms that
    # actually overlap the query, which is smaller. The UI labels this
    # "Terms in search space" for that reason.
    testedTermCount: int
    termCounts: dict[str, dict[str, int]] = Field(default_factory=dict, description="Per-query searchSpace, overlapTested (BH family), passingCutoff before topN, and displayed counts. BH is applied independently per query across eligible ontologies.")
    warnings: list[str] = Field(default_factory=list)


class AnovaRequest(BaseModel):
    kind: AnnotationKind
    source: AnovaSource = "anova"
    dataSource: VolcanoDataSource = "data"
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    useUncorrected: bool = False
    showDendrograms: bool = True
    showLegend: bool = True
    nClusters: int = Field(default=4, ge=1, le=100)
    postHoc: AnovaPostHoc = "none"


class AnovaResultResponse(BaseModel):
    kind: AnnotationKind
    source: AnovaSource
    sourceUsed: StatsSource
    labelColumn: str
    totalRows: int
    significantCount: int
    clusterCount: int | None = None
    rows: list[dict[str, Any]]
    clusterRows: list[dict[str, Any]] = Field(default_factory=list)
    postHocMethod: str | None = None
    postHocRows: list[dict[str, Any]] = Field(default_factory=list)
    postHocSignificantCount: int = 0
    warnings: list[str] = Field(default_factory=list)


class ListEnrichmentRequest(BaseModel):
    genes: list[str] = Field(default_factory=list)
    backgroundMode: EnrichmentBackgroundMode = "experiment"
    backgroundGenes: list[str] = Field(default_factory=list)
    topN: int = Field(default=10, ge=1, le=100)
    minTermSize: int = Field(default=20, ge=1)
    maxTermSize: int = Field(default=300, ge=1)
    adjPValueCutoff: float = Field(default=0.05, gt=0.0, le=1.0)


class ListEnrichmentResultResponse(BaseModel):
    genes: list[str]
    terms: list[EnrichmentTerm]
    backgroundMode: EnrichmentBackgroundMode
    backgroundGenes: list[str] = Field(default_factory=list)
    backgroundSize: int
    annotatedBackgroundSize: int
    # Organism of the bundled Gene Ontology database, not a detected property of
    # the uploaded data. Queries are matched against this universe regardless of
    # their source species; a low-overlap warning is emitted when they disagree.
    organism: str = Field(
        default="Homo sapiens",
        description="Organism of the Gene Ontology database used for enrichment.",
    )
    # Applies to the enrichment TERM p-values, which are always BH-corrected.
    # It does not describe the upstream volcano/ANOVA test, which has its own
    # useUncorrected switch.
    correctionMethod: str = Field(
        default="Benjamini-Hochberg",
        description="Multiple-testing correction applied to enrichment term p-values.",
    )
    databaseSha256: str
    # Terms passing the size filter -- the search space, not the
    # Benjamini-Hochberg denominator. Correction runs over the terms that
    # actually overlap the query, which is smaller. The UI labels this
    # "Terms in search space" for that reason.
    testedTermCount: int
    termCounts: dict[str, dict[str, int]] = Field(default_factory=dict, description="Per-query searchSpace, overlapTested (BH family), passingCutoff before topN, and displayed counts. BH is applied independently per query across eligible ontologies.")
    warnings: list[str] = Field(default_factory=list)


class PathwayOptionsResponse(BaseModel):
    pathways: list[str]


class SimulationRequest(BaseModel):
    kind: AnnotationKind
    source: SimulationSource = "volcano"
    dataSource: VolcanoDataSource = "data"
    condition1: str
    condition2: str
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: SimulationTestType = "unpaired"
    useUncorrected: bool = False
    varianceMultiplier: float = Field(default=1.0, gt=0.0)
    sampleSizeOverride: int = Field(default=0, ge=0, le=100)

    @field_validator("sampleSizeOverride")
    @classmethod
    def validate_sample_size_override(cls, value: int) -> int:
        if value == 1:
            raise ValueError(
                "sampleSizeOverride must be 0 (use observed sample sizes) or an integer from 2 to 100. "
                "A t-test cannot estimate variance from one sample per group."
            )
        return value


class SimulationResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    testType: SimulationTestType
    condition1: str
    condition2: str
    sampleSizeMode: Literal["observed", "override"]
    sampleSizeOverride: int
    effectiveSampleSizeCondition1Min: int
    effectiveSampleSizeCondition1Max: int
    effectiveSampleSizeCondition2Min: int
    effectiveSampleSizeCondition2Max: int
    labelColumn: str
    totalRows: int
    upregulatedCount: int
    downregulatedCount: int
    notSignificantCount: int
    rows: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)
