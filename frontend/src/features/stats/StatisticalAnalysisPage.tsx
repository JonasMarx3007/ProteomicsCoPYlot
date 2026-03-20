import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  buildPlotUrl,
  getPathwayOptions,
  getStatisticalOptions,
  runEnrichmentAnalysis,
  runSimulationAnalysis,
  runVolcanoAnalysis,
  runVolcanoControlAnalysis,
} from "../../lib/api";
import type {
  AnnotationKind,
  EnrichmentRequest,
  EnrichmentResultResponse,
  PathwayOptionsResponse,
  SimulationRequest,
  SimulationResultResponse,
  StatsIdentifier,
  StatsTab,
  StatsTestType,
  StatisticalOptionsResponse,
  VolcanoControlRequest,
  VolcanoResultResponse,
  VolcanoRequest,
} from "../../lib/types";

type Props = {
  activeTab: StatsTab;
};

const kindOptions = [
  { value: "protein", label: "Protein" },
  { value: "phospho", label: "Phospho" },
];

export default function StatisticalAnalysisPage({ activeTab }: Props) {
  if (activeTab === "volcano") return <VolcanoPanel control={false} />;
  if (activeTab === "volcanoControl") return <VolcanoPanel control />;
  if (activeTab === "gsea") return <GseaPanel />;
  if (activeTab === "pathwayHeatmap") return <PathwayHeatmapPanel />;
  return <SimulationPanel />;
}

function conditionOptions(options: StatisticalOptionsResponse | null) {
  return (options?.availableConditions ?? []).map((item) => ({ value: item, label: item }));
}

function hasGeneNameSupport(options: StatisticalOptionsResponse | null) {
  return (options?.availableIdentifiers ?? []).some((item) => item.key === "genes");
}

function SelectField({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900">
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function formatNumberInputValue(value: number) {
  return Number.isFinite(value) ? String(value) : "";
}

function NumberField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (value: number) => void; step?: number }) {
  const [draft, setDraft] = useState(() => formatNumberInputValue(value));

  useEffect(() => {
    setDraft(formatNumberInputValue(value));
  }, [value]);

  const commit = () => {
    if (!draft.trim()) {
      setDraft(formatNumberInputValue(value));
      return;
    }
    const nextValue = Number(draft);
    if (Number.isFinite(nextValue)) {
      onChange(nextValue);
      setDraft(formatNumberInputValue(nextValue));
      return;
    }
    setDraft(formatNumberInputValue(value));
  };

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="number"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        step={step}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
    </div>
  );
}

function TextareaField({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const commit = () => {
    onChange(draft);
  };

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            commit();
          }
        }}
        rows={rows}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
        placeholder={placeholder}
      />
    </div>
  );
}

function CheckboxField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function MultiSelect({ values, onChange, options }: { values: string[]; onChange: (value: string[]) => void; options: { value: string; label: string }[] }) {
  return (
    <select
      multiple
      value={values}
      onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((option) => option.value))}
      className="min-h-36 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function Notice({ error, warnings }: { error: string | null; warnings?: string[] }) {
  if (!error && (!warnings || warnings.length === 0)) return null;
  return (
    <div className="mt-4 space-y-3">
      {error ? <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      {warnings && warnings.length > 0 ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{warnings.join(" ")}</div> : null}
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SummarySection({ items, warnings }: { items: { label: string; value: string }[]; warnings?: string[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{item.label}</div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{item.value}</div>
          </div>
        ))}
      </div>
      {warnings && warnings.length > 0 ? <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{warnings.join(" ")}</div> : null}
    </section>
  );
}

function PlotFrame({ title, url, height }: { title: string; url: string; height: number }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Open Plot
        </a>
      </div>
      <iframe src={url} title={title} className="w-full rounded-xl border border-slate-200 bg-white" style={{ height }} />
    </section>
  );
}

function ImageSection({ title, url }: { title: string; url: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Open Image
        </a>
      </div>
      <img src={url} alt={title} className="w-full rounded-xl border border-slate-200" />
    </section>
  );
}

function SplitImageSection({ leftTitle, leftUrl, rightTitle, rightUrl }: { leftTitle: string; leftUrl: string; rightTitle: string; rightUrl: string }) {
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <ImageSection title={leftTitle} url={leftUrl} />
      <ImageSection title={rightTitle} url={rightUrl} />
    </div>
  );
}

function TableSection({ title, rows, filename }: { title: string; rows: Record<string, unknown>[]; filename: string }) {
  const csvUrl = useMemo(() => {
    if (!rows.length) return null;
    const columns = Array.from(
      rows.reduce((set, row) => {
        Object.keys(row).forEach((key) => set.add(key));
        return set;
      }, new Set<string>())
    );
    const lines = [
      columns.join(","),
      ...rows.map((row) =>
        columns.map((column) => `"${String(row[column] ?? "").replaceAll("\"", "\"\"")}"`).join(",")
      ),
    ];
    return `data:text/csv;charset=utf-8,${encodeURIComponent(lines.join("\n"))}`;
  }, [rows]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        {csvUrl ? <a href={csvUrl} download={filename} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">Download CSV</a> : null}
      </div>
      <PreviewTable rows={rows} />
    </section>
  );
}

function PreviewTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) {
    return <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">No rows available.</div>;
  }
  const columns = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>())
  );
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="max-h-[36rem] overflow-auto">
        <table className="min-w-full table-fixed divide-y divide-slate-200 text-left text-sm">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              {columns.map((column) => (
                <th key={column} className="overflow-hidden px-4 py-3 font-medium text-slate-700 text-ellipsis whitespace-nowrap">{column}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td key={column} title={String(row[column] ?? "")} className="max-w-xs overflow-hidden px-4 py-3 align-top text-ellipsis whitespace-nowrap text-slate-600">{String(row[column] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function GeneListSection({ title, genes, filename }: { title: string; genes: string[]; filename: string }) {
  const href = `data:text/plain;charset=utf-8,${encodeURIComponent(genes.join("\n"))}`;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={href} download={filename} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Download TXT
        </a>
      </div>
      <div className="max-h-60 overflow-auto rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        {genes.length ? genes.join(", ") : "No genes available."}
      </div>
    </section>
  );
}

function InfoSection({ message }: { message: string }) {
  return (
    <section className="rounded-2xl border border-sky-200 bg-sky-50 p-6 shadow-sm">
      <div className="text-sm text-sky-800">{message}</div>
    </section>
  );
}

function VolcanoPanel({ control }: { control: boolean }) {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState("");
  const [condition2, setCondition2] = useState("");
  const [condition1Control, setCondition1Control] = useState("");
  const [condition2Control, setCondition2Control] = useState("");
  const [identifier, setIdentifier] = useState<StatsIdentifier>("workflow");
  const [testType, setTestType] = useState<StatsTestType>("unpaired");
  const [pValueThreshold, setPValueThreshold] = useState(0.05);
  const [log2fcThreshold, setLog2fcThreshold] = useState(1);
  const [useUncorrected, setUseUncorrected] = useState(false);
  const [highlightText, setHighlightText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<VolcanoResultResponse | null>(null);

  useEffect(() => {
    getStatisticalOptions(kind)
      .then((data) => {
        setOptions(data);
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition1Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setIdentifier((current) => (data.availableIdentifiers.some((item) => item.key === current) ? current : data.availableIdentifiers[0]?.key ?? "workflow"));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load statistical options"));
  }, [kind]);

  const canRun = Boolean(
    condition1 &&
      condition2 &&
      condition1 !== condition2 &&
      (!control ||
        new Set([condition1, condition1Control, condition2, condition2Control].filter(Boolean)).size === 4)
  );
  const highlightTerms = useMemo(() => highlightText.split(/\s+/).map((term) => term.trim()).filter(Boolean), [highlightText]);

  useEffect(() => {
    if (!canRun) {
      setResult(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setError(null);

    const run = async () => {
      try {
        const response = control
          ? await runVolcanoControlAnalysis({
              kind,
              condition1,
              condition2,
              condition1Control,
              condition2Control,
              identifier,
              pValueThreshold,
              log2fcThreshold,
              testType,
              useUncorrected,
              highlightTerms,
            } satisfies VolcanoControlRequest)
          : await runVolcanoAnalysis({
              kind,
              condition1,
              condition2,
              identifier,
              pValueThreshold,
              log2fcThreshold,
              testType,
              useUncorrected,
              highlightTerms,
            } satisfies VolcanoRequest);
        if (cancelled) return;
        setResult(response);
      } catch (err) {
        if (cancelled) return;
        setResult(null);
        setError(err instanceof Error ? err.message : "Failed to run volcano analysis");
      } finally {
        if (cancelled) return;
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [
    canRun,
    control,
    kind,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    identifier,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    highlightTerms,
  ]);

  const plotUrl = control
    ? buildPlotUrl(`/api/plots/stats/${kind}/volcano-control.html`, {
        condition1,
        condition2,
        condition1Control,
        condition2Control,
        identifier,
        pValueThreshold,
        log2fcThreshold,
        testType,
        useUncorrected,
        highlightTerms: highlightTerms.join(","),
      })
    : buildPlotUrl(`/api/plots/stats/${kind}/volcano.html`, {
        condition1,
        condition2,
        identifier,
        pValueThreshold,
        log2fcThreshold,
        testType,
        useUncorrected,
        highlightTerms: highlightTerms.join(","),
      });

  return (
    <div className="space-y-6">
      <SectionCard title={control ? "Volcano Plot Control" : "Volcano Plot"}>
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
          {control ? <SelectField label="Condition 1 Control" value={condition1Control} onChange={setCondition1Control} options={conditionOptions(options)} /> : null}
          <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
          {control ? <SelectField label="Condition 2 Control" value={condition2Control} onChange={setCondition2Control} options={conditionOptions(options)} /> : null}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Label column" value={identifier} onChange={(value) => setIdentifier(value as StatsIdentifier)} options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))} />
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as StatsTestType)} options={[{ value: "unpaired", label: "Unpaired" }, { value: "paired", label: "Paired" }]} />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
        </div>

        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
          </div>
        </div>

        <div className="mt-4 max-w-3xl">
          <TextareaField label="Highlight terms" value={highlightText} onChange={setHighlightText} rows={3} placeholder="Space-separated labels to highlight" />
        </div>

        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {!canRun && options ? (
        <InfoSection
          message={
            control
              ? "Please select four different conditions and controls to generate the plot."
              : "Please select two different conditions to generate the plot."
          }
        />
      ) : null}
      {result ? (
        <>
          <SummarySection items={[{ label: "Rows", value: String(result.totalRows) }, { label: "Upregulated", value: String(result.upregulatedCount) }, { label: "Downregulated", value: String(result.downregulatedCount) }, { label: "Not Significant", value: String(result.notSignificantCount) }]} warnings={result.warnings} />
          <PlotFrame title="Volcano Plot" url={plotUrl} height={540} />
          <TableSection title="Result Table" rows={result.rows} filename={`volcano_${kind}.csv`} />
        </>
      ) : null}
    </div>
  );
}

function GseaPanel() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState("");
  const [condition2, setCondition2] = useState("");
  const [testType, setTestType] = useState<StatsTestType>("unpaired");
  const [pValueThreshold, setPValueThreshold] = useState(0.05);
  const [log2fcThreshold, setLog2fcThreshold] = useState(1);
  const [useUncorrected, setUseUncorrected] = useState(false);
  const [topN, setTopN] = useState(10);
  const [minTermSize, setMinTermSize] = useState(20);
  const [maxTermSize, setMaxTermSize] = useState(300);
  const [result, setResult] = useState<EnrichmentResultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStatisticalOptions(kind)
      .then((data) => {
        setOptions(data);
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load statistical options"));
  }, [kind]);

  const geneNamesAvailable = hasGeneNameSupport(options);
  const canRun = Boolean(geneNamesAvailable && condition1 && condition2 && condition1 !== condition2);

  useEffect(() => {
    if (!geneNamesAvailable || !canRun) {
      setResult(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setError(null);

    runEnrichmentAnalysis({
      kind,
      condition1,
      condition2,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
      topN,
      minTermSize,
      maxTermSize,
    } satisfies EnrichmentRequest)
      .then((response) => {
        if (cancelled) return;
        setResult(response);
      })
      .catch((err) => {
        if (cancelled) return;
        setResult(null);
        setError(err instanceof Error ? err.message : "Failed to run enrichment analysis");
      })
      .finally(() => {
        if (cancelled) return;
      });

    return () => {
      cancelled = true;
    };
  }, [
    canRun,
    kind,
    condition1,
    condition2,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    topN,
    minTermSize,
    maxTermSize,
  ]);

  const upPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/gsea/up.png`, { condition1, condition2, pValueThreshold, log2fcThreshold, testType, useUncorrected, topN, minTermSize, maxTermSize });
  const downPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/gsea/down.png`, { condition1, condition2, pValueThreshold, log2fcThreshold, testType, useUncorrected, topN, minTermSize, maxTermSize });

  return (
    <div className="space-y-6">
      <SectionCard title="GSEA">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2">
          <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
          <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as StatsTestType)} options={[{ value: "unpaired", label: "Unpaired" }, { value: "paired", label: "Paired" }]} />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
          <NumberField label="Top terms" value={topN} onChange={(value) => setTopN(Math.max(1, Math.round(value)))} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <NumberField label="Min term size" value={minTermSize} onChange={(value) => setMinTermSize(Math.max(1, Math.round(value)))} />
          <NumberField label="Max term size" value={maxTermSize} onChange={(value) => setMaxTermSize(Math.max(1, Math.round(value)))} />
        </div>
        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
          </div>
        </div>
        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {options && !geneNamesAvailable ? <InfoSection message="Gene names are required for GSEA. Please generate or load gene names first." /> : null}
      {options && geneNamesAvailable && !canRun ? <InfoSection message="Please select two different conditions to generate the plot." /> : null}
      {result ? (
        <>
          <SummarySection items={[{ label: "Up Genes", value: String(result.upGenes.length) }, { label: "Down Genes", value: String(result.downGenes.length) }, { label: "Up Terms", value: String(result.upTerms.length) }, { label: "Down Terms", value: String(result.downTerms.length) }]} warnings={result.warnings} />
          <SplitImageSection leftTitle="Upregulated Terms" leftUrl={upPlotUrl} rightTitle="Downregulated Terms" rightUrl={downPlotUrl} />
          <GeneListSection title="Upregulated Genes" genes={result.upGenes} filename={`gsea_up_${kind}.txt`} />
          <GeneListSection title="Downregulated Genes" genes={result.downGenes} filename={`gsea_down_${kind}.txt`} />
          <TableSection title="Upregulated Terms" rows={result.upTerms as unknown as Record<string, unknown>[]} filename={`gsea_up_${kind}.csv`} />
          <TableSection title="Downregulated Terms" rows={result.downTerms as unknown as Record<string, unknown>[]} filename={`gsea_down_${kind}.csv`} />
        </>
      ) : null}
    </div>
  );
}

function PathwayHeatmapPanel() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [pathways, setPathways] = useState<PathwayOptionsResponse | null>(null);
  const [pathway, setPathway] = useState("");
  const [selectedConditions, setSelectedConditions] = useState<string[]>([]);
  const [valueType, setValueType] = useState<"log2" | "z">("z");
  const [includeId, setIncludeId] = useState(true);
  const [header, setHeader] = useState(true);
  const [removeEmpty, setRemoveEmpty] = useState(true);
  const [clusterRows, setClusterRows] = useState(false);
  const [clusterCols, setClusterCols] = useState(false);
  const [widthCm, setWidthCm] = useState(20);
  const [heightCm, setHeightCm] = useState(12);
  const [dpi, setDpi] = useState(300);
  const [error, setError] = useState<string | null>(null);
  const geneNamesAvailable = hasGeneNameSupport(options);

  useEffect(() => {
    getStatisticalOptions(kind)
      .then((data) => {
        setOptions(data);
        setSelectedConditions((current) => (current.length ? current.filter((item) => data.availableConditions.includes(item)) : data.availableConditions));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load statistical options"));
  }, [kind]);

  useEffect(() => {
    getPathwayOptions()
      .then((data) => {
        setPathways(data);
        setPathway((current) => current || data.pathways[0] || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load pathway options"));
  }, []);

  const heatmapUrl = buildPlotUrl(`/api/plots/stats/${kind}/pathway-heatmap.png`, { pathway, conditions: selectedConditions.join(","), valueType, includeId, header, removeEmpty, clusterRows, clusterCols, widthCm, heightCm, dpi });

  return (
    <div className="space-y-6">
      <SectionCard title="Pathway Heatmap">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2">
          <SelectField label="Pathway" value={pathway} onChange={setPathway} options={(pathways?.pathways ?? []).map((item) => ({ value: item, label: item }))} />
          <SelectField label="Value type" value={valueType} onChange={(value) => setValueType(value as "log2" | "z")} options={[{ value: "z", label: "Z-score" }, { value: "log2", label: "log2" }]} />
        </div>
        <div className="mt-4">
          <label className="mb-2 block text-sm font-medium text-slate-700">Conditions</label>
          <MultiSelect values={selectedConditions} onChange={setSelectedConditions} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <NumberField label="Width (cm)" value={widthCm} onChange={setWidthCm} step={1} />
          <NumberField label="Height (cm)" value={heightCm} onChange={setHeightCm} step={1} />
          <NumberField label="DPI" value={dpi} onChange={(value) => setDpi(Math.max(72, Math.round(value)))} />
        </div>
        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Include sample IDs" checked={includeId} onChange={setIncludeId} />
            <CheckboxField label="Show gene labels" checked={header} onChange={setHeader} />
            <CheckboxField label="Remove empty genes" checked={removeEmpty} onChange={setRemoveEmpty} />
            <CheckboxField label="Cluster rows" checked={clusterRows} onChange={setClusterRows} />
            <CheckboxField label="Cluster columns" checked={clusterCols} onChange={setClusterCols} />
          </div>
        </div>
        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {!geneNamesAvailable && options ? <InfoSection message="Gene names are required for pathway heatmaps. Please generate or load gene names first." /> : null}
      {geneNamesAvailable && pathway && selectedConditions.length > 0 ? <ImageSection title="Pathway Heatmap" url={heatmapUrl} /> : null}
    </div>
  );
}

function SimulationPanel() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState("");
  const [condition2, setCondition2] = useState("");
  const [pValueThreshold, setPValueThreshold] = useState(0.05);
  const [log2fcThreshold, setLog2fcThreshold] = useState(1);
  const [varianceMultiplier, setVarianceMultiplier] = useState(1);
  const [sampleSizeOverride, setSampleSizeOverride] = useState(0);
  const [result, setResult] = useState<SimulationResultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStatisticalOptions(kind)
      .then((data) => {
        setOptions(data);
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load statistical options"));
  }, [kind]);

  const canRun = Boolean(condition1 && condition2 && condition1 !== condition2);

  useEffect(() => {
    if (!canRun) {
      setResult(null);
      setError(null);
      return;
    }

    let cancelled = false;
    setError(null);

    runSimulationAnalysis({
      kind,
      condition1,
      condition2,
      pValueThreshold,
      log2fcThreshold,
      varianceMultiplier,
      sampleSizeOverride,
    } satisfies SimulationRequest)
      .then((response) => {
        if (cancelled) return;
        setResult(response);
      })
      .catch((err) => {
        if (cancelled) return;
        setResult(null);
        setError(err instanceof Error ? err.message : "Failed to run simulation");
      })
      .finally(() => {
        if (cancelled) return;
      });

    return () => {
      cancelled = true;
    };
  }, [
    canRun,
    kind,
    condition1,
    condition2,
    pValueThreshold,
    log2fcThreshold,
    varianceMultiplier,
    sampleSizeOverride,
  ]);

  const plotUrl = buildPlotUrl(`/api/plots/stats/${kind}/simulation.html`, { condition1, condition2, pValueThreshold, log2fcThreshold, varianceMultiplier, sampleSizeOverride });

  return (
    <div className="space-y-6">
      <SectionCard title="Simulation">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2">
          <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
          <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
          <NumberField label="Variance multiplier" value={varianceMultiplier} onChange={setVarianceMultiplier} step={0.05} />
          <NumberField label="Sample size override" value={sampleSizeOverride} onChange={(value) => setSampleSizeOverride(Math.max(0, Math.round(value)))} />
        </div>
        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {!canRun && options ? <InfoSection message="Please select two different conditions to generate the plot." /> : null}
      {result ? (
        <>
          <SummarySection items={[{ label: "Rows", value: String(result.totalRows) }, { label: "Upregulated", value: String(result.upregulatedCount) }, { label: "Downregulated", value: String(result.downregulatedCount) }, { label: "Not Significant", value: String(result.notSignificantCount) }]} warnings={result.warnings} />
          <PlotFrame title="Simulation Volcano Plot" url={plotUrl} height={540} />
        </>
      ) : null}
    </div>
  );
}
