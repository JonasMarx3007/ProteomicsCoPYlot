/**
 * The rows of the ORA CSV downloads: one per term, with the run's parameters.
 *
 * The run's GO database hash and the correction-scope paragraph were once
 * repeated on every row, identical in all of them; they were taken out on
 * purpose (tests/component/removed-ui.test.tsx keeps them out).
 */
import type {
  EnrichmentResultResponse,
  EnrichmentTerm,
  ListEnrichmentRequest,
  ListEnrichmentResultResponse,
} from "../../lib/types";

export function oraExportRows(
  terms: EnrichmentTerm[],
  result: EnrichmentResultResponse,
  context: Record<string, unknown>
): Record<string, unknown>[] {
  // `source` on a term is its GO ontology (BP, CC or MF); exported as
  // `ontology` so it cannot be read as the data or analysis source.
  return terms.map(({ source: ontology, ...term }) => ({
    method: "ORA",
    organism: result.organism,
    analysisSource: result.selectedCluster == null ? "volcano" : "anova",
    datasetLevel: result.kind,
    dataSource: result.sourceUsed,
    backgroundMode: result.backgroundMode,
    backgroundSize: result.backgroundSize,
    annotatedBackgroundSize: result.annotatedBackgroundSize,
    correctionMethod: result.correctionMethod,
    upstreamCorrectionMethod: result.upstreamCorrectionMethod,
    testedTermCount: result.testedTermCount,
    ...result.termCounts[String(context.direction ?? "cluster")],
    ...context,
    ontology,
    ...term,
  }));
}

/** The canvas's ORA tile: a gene list run on its own, not from a volcano. */
export function oraListExportRows(
  completed: { request: ListEnrichmentRequest; inputSource: string; namedList: string },
  result: ListEnrichmentResultResponse
): Record<string, unknown>[] {
  return result.terms.map((term) => ({
    method: "ORA",
    organism: result.organism,
    inputSource: completed.inputSource,
    namedList: completed.namedList,
    // Genes submitted; `term.querySize` below is those found in the background.
    submittedGeneCount: result.genes.length,
    backgroundMode: result.backgroundMode,
    backgroundSize: result.backgroundSize,
    annotatedBackgroundSize: result.annotatedBackgroundSize,
    correctionMethod: result.correctionMethod,
    testedTermCount: result.testedTermCount,
    ...result.termCounts.query,
    adjPValueCutoff: completed.request.adjPValueCutoff,
    minTermSize: completed.request.minTermSize,
    maxTermSize: completed.request.maxTermSize,
    topN: completed.request.topN,
    ...term,
  }));
}
