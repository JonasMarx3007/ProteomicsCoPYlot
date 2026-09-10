import type { ListEnrichmentResultResponse } from "../lib/types";

export const ORA_CORRECTION_SCOPE = "BH correction is applied separately for each query/direction across all size-eligible terms with at least one overlapping gene, across ontologies. Zero-overlap terms are excluded. The adjusted-p cutoff and top-N display limit are applied afterward.";

export default function OraTermCounts({ counts }: { counts: ListEnrichmentResultResponse["termCounts"] }) {
  const csv = [
    "query,searchSpace,overlapTested,passingCutoff,displayed,correctionScope",
    ...Object.entries(counts ?? {}).map(([query, value]) =>
      [query, value.searchSpace, value.overlapTested, value.passingCutoff, value.displayed,
        `"${ORA_CORRECTION_SCOPE}"`].join(",")),
  ].join("\r\n");
  return <div className="mt-3 space-y-2 text-sm text-slate-700">
    <p>{ORA_CORRECTION_SCOPE}</p>
    {Object.entries(counts ?? {}).map(([query, value]) => <p key={query}>
      <strong>{query === "query" ? "Input list" : query === "cluster" ? "Selected cluster" : query === "up" ? "Upregulated" : "Downregulated"}</strong>
      {`: Search space: ${value.searchSpace} · Overlapping/tested (BH family): ${value.overlapTested} · Passing adjusted-p cutoff (before top N): ${value.passingCutoff} · Displayed terms: ${value.displayed}`}
    </p>)}
    <a className="inline-block text-sky-700 underline" download="ora_term_counts.csv"
      href={`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`}>Download ORA counts CSV</a>
  </div>;
}
