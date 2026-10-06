/**
 * The frontend's request types and value unions, checked against the backend.
 *
 * `generated/api.d.ts` is generated from the backend's OpenAPI schema
 * (`npm run generate:api`; tests/contracts/test_generated_api_is_current.py
 * fails when it is stale). Every line below is a compile-time assertion: if the
 * backend adds, removes or renames a value or field the frontend sends, `tsc`
 * (and so `npm run build`) fails here, naming the pair that disagrees.
 *
 * This replaced tests that read the TypeScript source with regular expressions.
 */
import type { components } from "./generated/api";
import type {
  AdvancedPlotSettings,
  AdvancedTextElementSettings,
  AnalysisVolcanoRequest,
  AnnotationGenerateRequest,
  AnovaClusterMethod,
  AnovaRequest,
  DataSource,
  EnrichmentRequest,
  IdTranslationRequest,
  ImputationRunRequest,
  ListEnrichmentRequest,
  NormalizationMethod,
  PairingUpdateRequest,
  PeptideMetadataGenerateRequest,
  SimulationRequest,
  StatsTestType,
  SummaryReportRequest,
  VolcanoControlRequest,
  VolcanoRequest,
} from "./types";

type Schemas = components["schemas"];

/** True only when A and B are the same set of values. */
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
/** A value of type A can be sent where the backend expects B. */
type Sendable<A, B> = [A] extends [B] ? true : false;
type Assert<T extends true> = T;

/** Value unions the frontend spells out itself must equal the backend's. */
export type ValueUnionsMatchTheBackend = [
  Assert<Same<StatsTestType, NonNullable<Schemas["VolcanoRequest"]["testType"]>>>,
  Assert<Same<AnovaClusterMethod, NonNullable<Schemas["AnovaRequest"]["clusterMethod"]>>>,
  Assert<Same<NormalizationMethod, NonNullable<Schemas["AnnotationFilterConfig"]["normalization"]>>>,
  Assert<Same<DataSource, NonNullable<Schemas["VolcanoRequest"]["dataSource"]>>>,
];

/**
 * Every request the frontend builds is one the backend accepts: same field
 * names, and every value of each field's type is one the backend allows. A field
 * typed with a narrower hand-written union, or a stale enum, fails here.
 */
export type RequestsAreAccepted = [
  Assert<Sendable<PairingUpdateRequest, Schemas["PairingUpdateRequest"]>>,
  Assert<Sendable<AnnotationGenerateRequest, Schemas["AnnotationGenerateRequest"]>>,
  Assert<Sendable<ImputationRunRequest, Schemas["ImputationRunRequest"]>>,
  Assert<Sendable<IdTranslationRequest, Schemas["IdTranslationRequest"]>>,
  Assert<Sendable<PeptideMetadataGenerateRequest, Schemas["PeptideMetadataGenerateRequest"]>>,
  Assert<Sendable<VolcanoRequest, Schemas["VolcanoRequest"]>>,
  Assert<Sendable<VolcanoControlRequest, Schemas["VolcanoControlRequest"]>>,
  Assert<Sendable<EnrichmentRequest, Schemas["EnrichmentRequest"]>>,
  Assert<Sendable<ListEnrichmentRequest, Schemas["ListEnrichmentRequest"]>>,
  Assert<Sendable<SimulationRequest, Schemas["SimulationRequest"]>>,
  Assert<Sendable<AnalysisVolcanoRequest, Schemas["AnalysisVolcanoRequest"]>>,
  Assert<Sendable<SummaryReportRequest, Schemas["SummaryReportRequest"]>>,
  Assert<Sendable<AnovaRequest, Schemas["AnovaRequest"]>>,
];

/**
 * The advanced plot settings travel as JSON inside one query parameter, so the
 * backend declares their shape separately (backend/app/schemas/plot_settings.py).
 * Same keys on both sides; the panel and the renderers are held to them by
 * frontend/tests/component/advanced-panel-keys.test.tsx and
 * tests/contracts/test_advanced_settings_reach_the_renderers.py.
 */
export type AdvancedSettingsMatchTheBackend = [
  Assert<Same<keyof AdvancedPlotSettings, keyof Schemas["AdvancedPlotSettings"]>>,
  Assert<Same<keyof AdvancedTextElementSettings, keyof Schemas["AdvancedTextElementSettings"]>>,
];
