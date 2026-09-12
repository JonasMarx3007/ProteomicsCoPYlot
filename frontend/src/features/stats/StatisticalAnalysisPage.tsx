import { contextMode } from "../../lib/plotSerialization";
import { useId, useEffect, useMemo, useState, type ReactNode } from "react";
import { collectColumns, rowsToQuotedCsv } from "../../lib/tableData";
import OraTermCounts, { ORA_CORRECTION_SCOPE } from "../../components/OraTermCounts";
import PaginatedTable from "../../components/PaginatedTable";
import PairingEditor from "../../components/PairingEditor";
import {
  buildPlotUrl,
  getPathwayOptions,
  getStatisticalOptions,
  isAbortError,
  pairingIsReady,
  runAnovaAnalysis,
  runEnrichmentAnalysis,
  runSimulationAnalysis,
  runVolcanoAnalysis,
  runVolcanoControlAnalysis,
} from "../../lib/api";
import { clampPlotDimensionCm, clampPlotDpi } from "../../lib/plotLimits";
import { useCurrentDatasetsSnapshot, useDatasetRevision } from "../../lib/datasetAvailability";
import {
  addVolcanoReportEntry,
  listVolcanoReportEntries,
  removeVolcanoReportEntry,
} from "../../lib/reportState";
import { IS_VIEWER_MODE } from "../../lib/appMode";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type {
  AnnotationKind,
  AnovaRequest,
  AnovaResultResponse,
  AnovaPostHoc,
  AnovaSource,
  EnrichmentRequest,
  EnrichmentResultResponse,
  EnrichmentTerm,
  PathwayOptionsResponse,
  SimulationRequest,
  SimulationResultResponse,
  SimulationTestType,
  StatsIdentifier,
  StatsTab,
  StatsTestType,
  StatisticalOptionsResponse,
  VolcanoResultResponse,
  SummaryVolcanoEntry,
} from "../../lib/types";

import { TEST_TYPE_OPTIONS, SIMULATION_TEST_TYPE_OPTIONS, restoreTestType, CONTROL_TEST_TYPE_OPTIONS, controlTestType } from "../../lib/statisticalTests";

function restoreSimulationTestType(value: unknown): SimulationTestType {
  return value === "unpaired_welch" ? "unpaired_welch" : "unpaired";
}

const SIMULATION_SAMPLE_SIZE_MIGRATION_WARNING =
  "Legacy Simulation sample-size override 1 was migrated to 0 (use observed sample sizes). A t-test cannot estimate variance from one sample per group.";

function restoreSimulationSampleSize(value: unknown): { value: number; warning: string | null } {
  const parsed = Number(value ?? 0);
  if (parsed === 1) {
    return { value: 0, warning: SIMULATION_SAMPLE_SIZE_MIGRATION_WARNING };
  }
  if (Number.isInteger(parsed) && (parsed === 0 || (parsed >= 2 && parsed <= 100))) {
    return { value: parsed, warning: null };
  }
  return { value: 0, warning: null };
}

function validateSimulationSampleSize(value: number): string | null {
  if (!Number.isInteger(value)) return "Sample size must be a whole number.";
  if (value === 1) {
    return "Use 0 for observed sample sizes or a value from 2 to 100; a t-test cannot estimate variance from n=1.";
  }
  if (value < 0 || value > 100) return "Sample size must be 0 or an integer from 2 to 100.";
  return null;
}

function formatEffectiveSampleSize(minimum: number, maximum: number): string {
  return minimum === maximum ? String(minimum) : `${minimum}-${maximum}`;
}

function isPairedTestType(value: StatsTestType): boolean {
  return value === "paired";
}

type Props = {
  activeTab: StatsTab;
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};


export default function StatisticalAnalysisPage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const { kindOptions } = useCurrentDatasetsSnapshot();

  if (kindOptions.length === 0) {
    return (
      <div className="space-y-6">
        <SectionCard title="Statistical Analysis">
          <InfoSection message="Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable statistical plots." />
        </SectionCard>
      </div>
    );
  }

  if (activeTab === "volcano") return <VolcanoPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "anova") return <AnovaPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "ora") return <OraPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "pathwayHeatmap") return <PathwayHeatmapPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  return <SimulationPanel kindOptions={kindOptions} advancedPlotOptions={advancedPlotOptions} />;
}

function conditionOptions(options: StatisticalOptionsResponse | null) {
  return (options?.availableConditions ?? []).map((item) => ({ value: item, label: item }));
}

function hasGeneNameSupport(options: StatisticalOptionsResponse | null) {
  return (options?.availableIdentifiers ?? []).some((item) => item.key === "genes");
}

function removeSourceUsageWarnings(warnings: string[] | undefined): string[] {
  if (!warnings || warnings.length === 0) return [];
  return warnings.filter((warning) => {
    const normalized = warning.trim().toLowerCase();
    if (!normalized) return false;
    if (normalized.includes("using raw data because filtered/log2 annotated data is unavailable")) {
      return false;
    }
    if (normalized.includes("using imputed data for statistical analysis")) {
      return false;
    }
    if (normalized.includes("imputation settings were detected")) {
      return false;
    }
    return true;
  });
}

function SelectField({ label, value, onChange, options, disabled = false }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; disabled?: boolean }) {
  const fieldId = useId();
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select id={fieldId} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500">
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

function parseNumberDraft(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  validate,
  onValidationError,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  validate?: (value: number) => string | null;
  onValidationError?: (message: string | null) => void;
}) {
  const fieldId = useId();
  const [draft, setDraft] = useState(() => formatNumberInputValue(value));

  useEffect(() => {
    setDraft(formatNumberInputValue(value));
  }, [value]);

  const commit = () => {
    const nextValue = parseNumberDraft(draft);
    if (nextValue == null) {
      setDraft(formatNumberInputValue(value));
      return;
    }
    const validationError = validate?.(nextValue) ?? null;
    if (validationError) {
      onValidationError?.(validationError);
      setDraft(formatNumberInputValue(value));
      return;
    }
    onValidationError?.(null);
    onChange(nextValue);
    setDraft(formatNumberInputValue(nextValue));
  };

  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input id={fieldId}
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(",", "."))}
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
  const fieldId = useId();
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const commit = () => {
    onChange(draft);
  };

  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <textarea id={fieldId}
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
      id="pathway-conditions"
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
      {error ? <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
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
  const resolvedHeight = Math.max(height, 760);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Open Plot
        </a>
      </div>
      <iframe sandbox="allow-scripts allow-downloads" src={url} title={title} className="w-full rounded-xl border border-slate-200 bg-white" style={{ height: resolvedHeight }} />
    </section>
  );
}

function ImageSection({ title, url }: { title: string; url: string }) {
  const [imageError, setImageError] = useState<{ url: string; message: string } | null>(null);

  async function handleImageError() {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const payload = JSON.parse(text) as { detail?: string };
          if (payload.detail) {
            setImageError({ url, message: payload.detail });
            return;
          }
        } catch {}
      }
    } catch {}
    setImageError({
      url,
      message: "Failed to load the plot image. Check the selected data and plot options.",
    });
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Open Image
        </a>
      </div>
      <img
        src={url}
        alt={title}
        className="w-full rounded-xl border border-slate-200"
        onLoad={() => setImageError((current) => (current?.url === url ? null : current))}
        onError={() => void handleImageError()}
      />
      {imageError?.url === url ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {imageError.message}
        </div>
      ) : null}
    </section>
  );
}

function TableSection({ title, rows, filename }: { title: string; rows: Record<string, unknown>[]; filename: string }) {
  const csvUrl = useMemo(() => {
    if (!rows.length) return null;
    const csv = rowsToQuotedCsv(rows, collectColumns(rows));
    return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
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
  return <PaginatedTable rows={rows} pageSize={50} emptyText="No rows available." maxHeightClassName="max-h-[36rem]" />;
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

function OraProvenanceSection({ result }: { result: EnrichmentResultResponse }) {
  return (
    <SectionCard title="ORA Provenance">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div className="text-sm text-slate-700">Method: <span className="font-medium text-slate-900">ORA</span></div>
        <div className="text-sm text-slate-700">Organism: <span className="font-medium text-slate-900">{result.organism}</span></div>
        <div className="text-sm text-slate-700">Upstream correction: <span className="font-medium text-slate-900">{result.upstreamCorrectionMethod}</span></div>
        <div className="text-sm text-slate-700">ORA term correction: <span className="font-medium text-slate-900">{result.correctionMethod}</span></div>
        <div className="text-sm text-slate-700">Terms in search space: <span className="font-medium text-slate-900">{result.testedTermCount}</span></div>
      </div>
      <div className="mt-3 break-all text-xs text-slate-600">GO database SHA-256: {result.databaseSha256}</div>
      <OraTermCounts counts={result.termCounts} />
    </SectionCard>
  );
}

function InfoSection({ message }: { message: string }) {
  return (
    <section className="rounded-2xl border border-sky-200 bg-sky-50 p-6 shadow-sm">
      <div className="text-sm text-sky-800">{message}</div>
    </section>
  );
}

function VolcanoPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
}) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("stats.volcano.v1", {}),
    []
  );
  const revision = useDatasetRevision();
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const kind = (kindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : kindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [sourceMode, setSourceMode] = useState<"volcano" | "volcano_control">(() => {
    const value = String(persisted.sourceMode ?? "volcano").trim();
    return value === "volcano_control" ? "volcano_control" : "volcano";
  });
  const [dataSource, setDataSource] = useState<"data" | "imputed">(() => {
    const value = String(persisted.dataSource ?? "data").trim();
    return value === "imputed" ? "imputed" : "data";
  });
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState(() => String(persisted.condition1 ?? ""));
  const [condition2, setCondition2] = useState(() => String(persisted.condition2 ?? ""));
  const [condition1Control, setCondition1Control] = useState(() => String(persisted.condition1Control ?? ""));
  const [condition2Control, setCondition2Control] = useState(() => String(persisted.condition2Control ?? ""));
  const [identifier, setIdentifier] = useState<StatsIdentifier>(() => {
    const value = String(persisted.identifier ?? "workflow").trim();
    return value === "genes" ? "genes" : "workflow";
  });
  const [selectedTestType, setTestType] = useState<StatsTestType>(() => {
    return restoreTestType(persisted.testType);
  });
  const testType = sourceMode === "volcano_control" ? controlTestType(selectedTestType) : selectedTestType;
  const [pValueThreshold, setPValueThreshold] = useState(() => Number(persisted.pValueThreshold ?? 0.05));
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [highlightText, setHighlightText] = useState(() => String(persisted.highlightText ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: VolcanoResultResponse;
  } | null>(null);
  const [reportLogMessage, setReportLogMessage] = useState<string | null>(null);
  const [reportLogVersion, setReportLogVersion] = useState(0);

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const volcanoDataSourceOptions = useMemo(
    () =>
      options?.imputedAvailable
        ? [
            { value: "data", label: "Data" },
            { value: "imputed", label: "Imputed Data" },
          ]
        : [{ value: "data", label: "Data" }],
    [options?.imputedAvailable]
  );

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        setDataSource((current) =>
          data.imputedAvailable
            ? (current === "imputed" ? "imputed" : "data")
            : "data"
        );
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition1Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setIdentifier((current) => (data.availableIdentifiers.some((item) => item.key === current) ? current : data.availableIdentifiers[0]?.key ?? "workflow"));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable]);

  const controlSelectionValid =
    sourceMode !== "volcano_control" ||
    new Set([condition1, condition1Control, condition2, condition2Control].filter(Boolean)).size === 4;
  const canRun = Boolean(
    kindAvailable &&
      condition1 &&
      condition2 &&
      condition1 !== condition2 &&
      controlSelectionValid &&
      (!isPairedTestType(testType) ||
        pairingIsReady(
          condition1,
          condition2,
          options?.samplesByCondition ?? {},
          options?.pairIdsBySample ?? {}
        ))
  );
  const highlightTerms = useMemo(() => highlightText.split(/\s+/).map((term) => term.trim()).filter(Boolean), [highlightText]);
  const requestPayload = useMemo(() => {
    if (!canRun) return null;
    return {
      source: sourceMode,
      kind,
      dataSource,
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
    };
  }, [
    canRun,
    sourceMode,
    kind,
    dataSource,
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

  useEffect(() => {
    if (!onContextModeChange) return;
    const sanitize = (value: string) => String(value ?? "");
    const parts = [
      `source=${sourceMode}`,
      `kind=${kind}`,
      `dataSource=${dataSource}`,
      `condition1=${sanitize(condition1)}`,
      `condition2=${sanitize(condition2)}`,
      `condition1Control=${sanitize(condition1Control)}`,
      `condition2Control=${sanitize(condition2Control)}`,
      `identifier=${identifier}`,
      `testType=${testType}`,
      `pValueThreshold=${pValueThreshold}`,
      `log2fcThreshold=${log2fcThreshold}`,
      `useUncorrected=${useUncorrected ? "true" : "false"}`,
    ];
    onContextModeChange(contextMode(parts));
  }, [
    onContextModeChange,
    sourceMode,
    kind,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    identifier,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
  ]);
  const debouncedRequestPayload = useDebouncedValue(requestPayload, 650);
  const currentRequestKey = requestPayload ? JSON.stringify({ revision, ...requestPayload }) : "";
  const result = currentRequestKey && resultState?.key === currentRequestKey ? resultState.data : null;

  const currentReportEntry = useMemo<SummaryVolcanoEntry>(
    () => ({
      kind,
      control: sourceMode === "volcano_control",
      dataSource,
      condition1,
      condition2,
      condition1Control: sourceMode === "volcano_control" ? condition1Control : null,
      condition2Control: sourceMode === "volcano_control" ? condition2Control : null,
      identifier,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
      highlightTerms,
    }),
    [
      kind,
      sourceMode,
      dataSource,
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
    ]
  );
  const reportEntryCount = useMemo(
    () => {
      void reportLogVersion;
      return listVolcanoReportEntries().filter(
        (entry) => !entry.control && entry.kind === kind
      ).length;
    },
    [kind, reportLogVersion]
  );

  function handleAddToReport() {
    if (!canRun) {
      setReportLogMessage("Please choose valid conditions before adding this volcano plot.");
      return;
    }
    const added = addVolcanoReportEntry(currentReportEntry);
    setReportLogVersion((value) => value + 1);
    setReportLogMessage(
      added
        ? "Volcano plot added to report list."
        : "This volcano configuration is already in the report list."
    );
  }

  useEffect(() => {
    writePersistedUiState("stats.volcano.v1", {
      kind,
      sourceMode,
      dataSource,
      condition1,
      condition2,
      condition1Control,
      condition2Control,
      identifier,
      testType,
      pValueThreshold,
      log2fcThreshold,
      useUncorrected,
      highlightText,
    });
  }, [
    kind,
    sourceMode,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    identifier,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    highlightText,
  ]);

  function handleRemoveFromReport() {
    const removed = removeVolcanoReportEntry(currentReportEntry);
    setReportLogVersion((value) => value + 1);
    setReportLogMessage(
      removed > 0
        ? `Removed ${removed} volcano entr${removed === 1 ? "y" : "ies"} from report list.`
        : "No matching volcano entry found in report list."
    );
  }

  useEffect(() => {
    if (!debouncedRequestPayload) {
      return;
    }

    const controller = new AbortController();

    const run = async () => {
      try {
        const response = debouncedRequestPayload.source === "volcano_control"
          ? await runVolcanoControlAnalysis({
            kind: debouncedRequestPayload.kind,
              dataSource: debouncedRequestPayload.dataSource,
              condition1: debouncedRequestPayload.condition1,
              condition2: debouncedRequestPayload.condition2,
              condition1Control: debouncedRequestPayload.condition1Control,
              condition2Control: debouncedRequestPayload.condition2Control,
              identifier: debouncedRequestPayload.identifier,
              pValueThreshold: debouncedRequestPayload.pValueThreshold,
              log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
              testType: debouncedRequestPayload.testType,
              useUncorrected: debouncedRequestPayload.useUncorrected,
              highlightTerms: debouncedRequestPayload.highlightTerms,
            }, { signal: controller.signal })
          : await runVolcanoAnalysis({
              kind: debouncedRequestPayload.kind,
              dataSource: debouncedRequestPayload.dataSource,
              condition1: debouncedRequestPayload.condition1,
              condition2: debouncedRequestPayload.condition2,
              identifier: debouncedRequestPayload.identifier,
              pValueThreshold: debouncedRequestPayload.pValueThreshold,
              log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
              testType: debouncedRequestPayload.testType,
              useUncorrected: debouncedRequestPayload.useUncorrected,
              highlightTerms: debouncedRequestPayload.highlightTerms,
            }, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setResultState({ key: JSON.stringify({ revision, ...debouncedRequestPayload }), data: response });
        setError(null);
      } catch (err) {
        if (isAbortError(err)) return;
        setResultState(null);
        setError(err instanceof Error ? err.message : "Failed to run volcano analysis");
      }
    };

    run();

    return () => {
      controller.abort();
    };
  }, [
    debouncedRequestPayload,
    revision,
  ]);

  const plotUrl = useMemo(() => {
    void advancedPlotSignal;
    if (!debouncedRequestPayload) return "";
    if (debouncedRequestPayload.source === "volcano_control") {
      return buildPlotUrl(`/api/plots/stats/${debouncedRequestPayload.kind}/volcano-control.html`, {
        condition1: debouncedRequestPayload.condition1,
        condition2: debouncedRequestPayload.condition2,
        dataSource: debouncedRequestPayload.dataSource,
        condition1Control: debouncedRequestPayload.condition1Control,
        condition2Control: debouncedRequestPayload.condition2Control,
        identifier: debouncedRequestPayload.identifier,
        pValueThreshold: debouncedRequestPayload.pValueThreshold,
        log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
        testType: debouncedRequestPayload.testType,
        useUncorrected: debouncedRequestPayload.useUncorrected,
        highlightTerms: debouncedRequestPayload.highlightTerms.join(","),
      });
    }
    return buildPlotUrl(`/api/plots/stats/${debouncedRequestPayload.kind}/volcano.html`, {
      condition1: debouncedRequestPayload.condition1,
      condition2: debouncedRequestPayload.condition2,
      dataSource: debouncedRequestPayload.dataSource,
      identifier: debouncedRequestPayload.identifier,
      pValueThreshold: debouncedRequestPayload.pValueThreshold,
      log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
      testType: debouncedRequestPayload.testType,
      useUncorrected: debouncedRequestPayload.useUncorrected,
      highlightTerms: debouncedRequestPayload.highlightTerms.join(","),
    });
  }, [debouncedRequestPayload, advancedPlotSignal, revision]);

  return (
    <div className="space-y-6">
      <SectionCard title="Volcano Plot">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Source"
            value={sourceMode}
            onChange={(value) => setSourceMode(value as "volcano" | "volcano_control")}
            options={[
              { value: "volcano", label: "Volcano" },
              { value: "volcano_control", label: "Volcano Control" },
            ]}
          />
          <SelectField
            label="Data Source"
            value={dataSource}
            onChange={(value) => setDataSource(value as "data" | "imputed")}
            options={volcanoDataSourceOptions}
          />
        </div>
        {sourceMode === "volcano_control" ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
            <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
            <SelectField label="Condition 1 Control" value={condition1Control} onChange={setCondition1Control} options={conditionOptions(options)} />
            <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
            <SelectField label="Condition 2 Control" value={condition2Control} onChange={setCondition2Control} options={conditionOptions(options)} />
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
            <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
          </div>
        )}

        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Label column" value={identifier} onChange={(value) => setIdentifier(value as StatsIdentifier)} options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))} />
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as StatsTestType)} options={sourceMode === "volcano_control" ? CONTROL_TEST_TYPE_OPTIONS : TEST_TYPE_OPTIONS} />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
        </div>
        {isPairedTestType(testType) ? (
          <PairingEditor
            kind={kind}
            condition1={condition1}
            condition2={condition2}
            samplesByCondition={options?.samplesByCondition ?? {}}
            pairIdsBySample={options?.pairIdsBySample ?? {}}
            onSaved={async () => setOptions(await getStatisticalOptions(kind))}
          />
        ) : null}

        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
          </div>
        </div>

        <div className="mt-4 max-w-3xl">
          <TextareaField label="Highlight terms" value={highlightText} onChange={setHighlightText} rows={3} placeholder="Space-separated labels to highlight" />
        </div>

        {sourceMode === "volcano" && !IS_VIEWER_MODE ? (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleAddToReport}
                className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
              >
                Add Volcano To Report
              </button>
              <button
                type="button"
                onClick={handleRemoveFromReport}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Remove Volcano From Report
              </button>
              <span className="text-sm text-slate-600">
                Saved entries for {kind}: {reportEntryCount}
              </span>
            </div>
            {reportLogMessage ? (
              <div className="mt-3 text-sm text-slate-700">{reportLogMessage}</div>
            ) : null}
          </div>
        ) : null}

      <Notice error={error} warnings={removeSourceUsageWarnings(options?.warnings)} />
      </SectionCard>
      {advancedPlotOptions}
      {!canRun && options ? (
        <InfoSection message="Please select two different conditions to generate the plot." />
      ) : null}
      {canRun && result ? (
        <>
          <SummarySection items={[{ label: "Rows", value: String(result.totalRows) }, { label: "Upregulated", value: String(result.upregulatedCount) }, { label: "Downregulated", value: String(result.downregulatedCount) }, { label: "Not Significant", value: String(result.notSignificantCount) }]} warnings={removeSourceUsageWarnings(result.warnings)} />
          <PlotFrame title="Volcano Plot" url={plotUrl} height={760} />
          <TableSection title="Result Table" rows={result.rows} filename={`volcano_${kind}.csv`} />
        </>
      ) : null}
    </div>
  );
}

function oraExportRows(
  terms: EnrichmentTerm[],
  result: EnrichmentResultResponse,
  context: Record<string, unknown>
): Record<string, unknown>[] {
  return terms.map((term) => ({
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
    databaseSha256: result.databaseSha256,
    testedTermCount: result.testedTermCount,
    ...result.termCounts[String(context.direction ?? "cluster")],
    correctionScope: ORA_CORRECTION_SCOPE,
    ...context,
    ...term,
  }));
}

function AnovaPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
}) {
  useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("stats.anova.v1", {}),
    []
  );
  const revision = useDatasetRevision();
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const kind = (kindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : kindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [sourceMode, setSourceMode] = useState<AnovaSource>(() => {
    const value = String(persisted.sourceMode ?? "anova").trim();
    return value === "anova_cluster" ? "anova_cluster" : "anova";
  });
  const [dataSource, setDataSource] = useState<"data" | "imputed">(() => {
    const value = String(persisted.dataSource ?? "data").trim();
    return value === "imputed" ? "imputed" : "data";
  });
  const [identifier, setIdentifier] = useState<StatsIdentifier>(() => {
    const value = String(persisted.identifier ?? "workflow").trim();
    return value === "genes" ? "genes" : "workflow";
  });
  const [pValueThreshold, setPValueThreshold] = useState(() => Number(persisted.pValueThreshold ?? 0.05));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [showDendrograms, setShowDendrograms] = useState(() => Boolean(persisted.showDendrograms ?? true));
  const [showLegend, setShowLegend] = useState(() => Boolean(persisted.showLegend ?? true));
  const [nClusters, setNClusters] = useState(() => Number(persisted.nClusters ?? 4));
  const [selectedCluster, setSelectedCluster] = useState(() => String(persisted.selectedCluster ?? "none"));
  const [postHoc, setPostHoc] = useState<AnovaPostHoc>(() =>
    String(persisted.postHoc ?? "none").trim() === "tukey" ? "tukey" : "none"
  );
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: AnovaResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentResultKey = JSON.stringify({
    revision,
    kind,
    source: sourceMode,
    dataSource,
    identifier,
    pValueThreshold,
    useUncorrected,
    showDendrograms,
    showLegend,
    nClusters: Math.max(1, Math.round(nClusters)),
    postHoc,
  });
  const result = resultState?.key === currentResultKey ? resultState.data : null;

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const anovaDataSourceOptions = useMemo(
    () =>
      options?.imputedAvailable
        ? [
            { value: "data", label: "Data" },
            { value: "imputed", label: "Imputed Data" },
          ]
        : [{ value: "data", label: "Data" }],
    [options?.imputedAvailable]
  );
  const clusterSizes = useMemo(() => {
    const counts = new Map<string, number>();
    if (sourceMode !== "anova_cluster" || !result?.clusterRows.length) return counts;
    result.clusterRows.forEach((row) => {
      const value = row.cluster;
      if (value !== null && value !== undefined && String(value).trim() !== "") {
        const cluster = String(value);
        counts.set(cluster, (counts.get(cluster) ?? 0) + 1);
      }
    });
    return counts;
  }, [result, sourceMode]);
  const availableClusters = useMemo(() => {
    return Array.from(clusterSizes.keys()).sort((a, b) => {
      const aNumber = Number(a);
      const bNumber = Number(b);
      if (Number.isFinite(aNumber) && Number.isFinite(bNumber)) return aNumber - bNumber;
      return a.localeCompare(b, undefined, { numeric: true });
    });
  }, [clusterSizes]);
  const displayedSelectedCluster = sourceMode === "anova_cluster" && availableClusters.includes(selectedCluster)
    ? selectedCluster
    : "none";
  const clusterOptions = useMemo(
    () => [
      { value: "none", label: "None" },
      ...availableClusters.map((cluster) => ({
        value: cluster,
        label: `Cluster ${cluster} (n=${clusterSizes.get(cluster) ?? 0})`,
      })),
    ],
    [availableClusters, clusterSizes]
  );
  const selectedClusterRows = useMemo(() => {
    if (displayedSelectedCluster === "none" || !result?.clusterRows.length) return [];
    return result.clusterRows.filter((row) => String(row.cluster ?? "") === displayedSelectedCluster);
  }, [result, displayedSelectedCluster]);

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        setDataSource((current) =>
          data.imputedAvailable
            ? (current === "imputed" ? "imputed" : "data")
            : "data"
        );
        setIdentifier((current) => (data.availableIdentifiers.some((item) => item.key === current) ? current : data.availableIdentifiers[0]?.key ?? "workflow"));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable]);

  const canRun = Boolean(kindAvailable && options && options.availableConditions.length >= 2);
  const requestPayload = useMemo<AnovaRequest | null>(() => {
    if (!canRun) return null;
    return {
      kind,
      source: sourceMode,
      dataSource,
      identifier,
      pValueThreshold,
      useUncorrected,
      showDendrograms,
      showLegend,
      nClusters: Math.max(1, Math.round(nClusters)),
      postHoc,
    };
  }, [canRun, kind, sourceMode, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showLegend, nClusters, postHoc]);

  useEffect(() => {
    if (!onContextModeChange) return;
    const parts = [
      `source=${sourceMode}`,
      `kind=${kind}`,
      `dataSource=${dataSource}`,
      `identifier=${identifier}`,
      `pValueThreshold=${pValueThreshold}`,
      `useUncorrected=${useUncorrected ? "true" : "false"}`,
      `showDendrograms=${showDendrograms ? "true" : "false"}`,
      `showLegend=${showLegend ? "true" : "false"}`,
      `selectedCluster=${displayedSelectedCluster}`,
      `nClusters=${Math.max(1, Math.round(nClusters))}`,
      `postHoc=${postHoc}`,
    ];
    onContextModeChange(contextMode(parts));
  }, [onContextModeChange, sourceMode, kind, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showLegend, displayedSelectedCluster, nClusters, postHoc]);

  const debouncedRequestPayload = useDebouncedValue(requestPayload, 650);

  useEffect(() => {
    if (!debouncedRequestPayload) return;
    const controller = new AbortController();
    runAnovaAnalysis(debouncedRequestPayload, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setResultState({ key: JSON.stringify({ revision, ...debouncedRequestPayload }), data: response });
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setResultState(null);
        setError(err instanceof Error ? err.message : "Failed to run ANOVA analysis");
      });
    return () => {
      controller.abort();
    };
  }, [debouncedRequestPayload, revision]);

  const plotUrl = buildPlotUrl(`/api/plots/stats/${kind}/anova.png`, {
    source: sourceMode,
    dataSource,
    identifier,
    pValueThreshold,
    useUncorrected,
    showDendrograms,
    showLegend,
    nClusters: Math.max(1, Math.round(nClusters)),
  });
  const selectedClusterPlotUrl =
    sourceMode === "anova_cluster" && displayedSelectedCluster !== "none"
      ? buildPlotUrl(`/api/plots/stats/${kind}/anova.png`, {
          source: sourceMode,
          dataSource,
          identifier,
          pValueThreshold,
          useUncorrected,
          showDendrograms,
          showLegend,
          nClusters: Math.max(1, Math.round(nClusters)),
          selectedCluster: displayedSelectedCluster,
        })
      : null;

  useEffect(() => {
    writePersistedUiState("stats.anova.v1", {
      kind,
      sourceMode,
      dataSource,
      identifier,
      pValueThreshold,
      useUncorrected,
      showDendrograms,
      showLegend,
      selectedCluster,
      nClusters,
      postHoc,
    });
  }, [kind, sourceMode, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showLegend, selectedCluster, nClusters, postHoc]);

  return (
    <div className="space-y-6">
      <SectionCard title="ANOVA">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField
            label="Source"
            value={sourceMode}
            onChange={(value) => setSourceMode(value as AnovaSource)}
            options={[
              { value: "anova", label: "ANOVA" },
              { value: "anova_cluster", label: "ANOVA Cluster" },
            ]}
          />
          <SelectField
            label="Data Source"
            value={dataSource}
            onChange={(value) => setDataSource(value as "data" | "imputed")}
            options={anovaDataSourceOptions}
          />
          <SelectField
            label="Label column"
            value={identifier}
            onChange={(value) => setIdentifier(value as StatsIdentifier)}
            options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))}
          />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
          <CheckboxField label="Show dendrograms" checked={showDendrograms} onChange={setShowDendrograms} />
          <CheckboxField label="Legend" checked={showLegend} onChange={setShowLegend} />
        </div>
        {sourceMode === "anova_cluster" ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <NumberField label="Clusters" value={nClusters} onChange={(value) => setNClusters(Math.max(1, Math.round(value)))} />
            <SelectField label="Cluster" value={displayedSelectedCluster} onChange={setSelectedCluster} options={clusterOptions} />
          </div>
        ) : null}
        <div className="mt-4 max-w-xs">
          <SelectField
            label="Post-hoc test"
            value={postHoc}
            onChange={(value) => setPostHoc(value as AnovaPostHoc)}
            options={[
              { value: "none", label: "None" },
              { value: "tukey", label: "Tukey HSD" },
            ]}
          />
        </div>
        <Notice error={error} warnings={removeSourceUsageWarnings(options?.warnings)} />
      </SectionCard>

      {advancedPlotOptions}
      {!canRun && options ? <InfoSection message="At least two conditions with replicate samples are required to run ANOVA." /> : null}
      {debouncedRequestPayload && result ? (
        <>
          <SummarySection
            items={[
              { label: "Rows", value: String(result.totalRows) },
              { label: "Significant", value: String(result.significantCount) },
              { label: "Source", value: result.source === "anova_cluster" ? "ANOVA Cluster" : "ANOVA" },
              { label: "Clusters", value: result.clusterCount == null ? "-" : String(result.clusterCount) },
              {
                label: "Cluster sizes",
                value: availableClusters.length
                  ? availableClusters.map((cluster) => `${cluster}: ${clusterSizes.get(cluster) ?? 0}`).join(", ")
                  : "-",
              },
            ]}
            warnings={removeSourceUsageWarnings(result.warnings)}
          />
          {result.significantCount === 0 ? (
            <InfoSection message="No rows passed the selected ANOVA threshold, so no significant-row heatmap or clusters were generated." />
          ) : (
            <ImageSection title={sourceMode === "anova_cluster" ? "ANOVA Cluster Heatmap" : "ANOVA Heatmap"} url={plotUrl} />
          )}
          {selectedClusterPlotUrl ? <ImageSection title={`Cluster ${displayedSelectedCluster} Heatmap`} url={selectedClusterPlotUrl} /> : null}
          <TableSection title="Result Table" rows={result.rows} filename={`anova_${sourceMode}_${kind}.csv`} />
          {selectedClusterRows.length > 0 ? (
            <TableSection title={`Cluster ${displayedSelectedCluster} Result Table`} rows={selectedClusterRows} filename={`anova_${sourceMode}_${kind}_cluster_${displayedSelectedCluster}.csv`} />
          ) : null}
          {postHoc === "tukey" && result.postHocRows.length > 0 ? (
            <TableSection
              title={`Post-hoc: ${result.postHocMethod ?? "Tukey HSD"} (${result.postHocSignificantCount} significant of ${result.postHocRows.length} comparisons, ANOVA-significant rows only)`}
              rows={result.postHocRows}
              filename={`anova_${sourceMode}_${kind}_tukey.csv`}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function OraPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
}) {
  useAdvancedPlotSignal();
  const oraKindOptions = useMemo(
    () => kindOptions.filter((option) => option.value === "protein" || option.value === "phosprot"),
    [kindOptions]
  );
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("stats.ora.v1", {}),
    []
  );
  const revision = useDatasetRevision();
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const kind = (oraKindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : oraKindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState(() => String(persisted.condition1 ?? ""));
  const [condition2, setCondition2] = useState(() => String(persisted.condition2 ?? ""));
  const [sourceMode, setSourceMode] = useState<"volcano" | "volcano_control" | "anova">(() => {
    const value = String(persisted.sourceMode ?? "volcano").trim();
    if (value === "anova") return "anova";
    return value === "volcano_control" ? "volcano_control" : "volcano";
  });
  const [dataSource, setDataSource] = useState<"data" | "imputed">(() => {
    const value = String(persisted.dataSource ?? "data").trim();
    return value === "imputed" ? "imputed" : "data";
  });
  const [condition1Control, setCondition1Control] = useState(() => String(persisted.condition1Control ?? ""));
  const [condition2Control, setCondition2Control] = useState(() => String(persisted.condition2Control ?? ""));
  const [selectedTestType, setTestType] = useState<StatsTestType>(() => {
    return restoreTestType(persisted.testType);
  });
  const testType = sourceMode === "volcano_control" ? controlTestType(selectedTestType) : selectedTestType;
  const [pValueThreshold, setPValueThreshold] = useState(() => Number(persisted.pValueThreshold ?? 0.05));
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [nClusters, setNClusters] = useState(() => Number(persisted.nClusters ?? 4));
  const [selectedCluster, setSelectedCluster] = useState(() => String(persisted.selectedCluster ?? ""));
  const [adjPValueCutoff, setAdjPValueCutoff] = useState(() => Number(persisted.adjPValueCutoff ?? 0.05));
  const [topN, setTopN] = useState(() => Number(persisted.topN ?? 10));
  const [minTermSize, setMinTermSize] = useState(() => Number(persisted.minTermSize ?? 20));
  const [maxTermSize, setMaxTermSize] = useState(() => Number(persisted.maxTermSize ?? 300));
  const [backgroundMode, setBackgroundMode] = useState<"experiment" | "global">(() =>
    String(persisted.backgroundMode ?? "experiment") === "global" ? "global" : "experiment"
  );
  const [anovaResult, setAnovaResult] = useState<AnovaResultResponse | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: EnrichmentResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentResultKey = JSON.stringify({
    revision,
    kind,
    sourceMode,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    selectedCluster,
    nClusters: Math.max(1, Math.round(nClusters)),
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
  });
  const result = resultState?.key === currentResultKey ? resultState.data : null;

  const kindAvailable = oraKindOptions.some((option) => option.value === kind);
  const oraDataSourceOptions = useMemo(
    () =>
      options?.imputedAvailable
        ? [
            { value: "data", label: "Data" },
            { value: "imputed", label: "Imputed Data" },
          ]
        : [{ value: "data", label: "Data" }],
    [options?.imputedAvailable]
  );
  const anovaClusterSizes = (() => {
    const counts = new Map<string, number>();
    if (sourceMode !== "anova" || !anovaResult?.clusterRows.length) return counts;
    anovaResult.clusterRows.forEach((row) => {
      const value = row.cluster;
      if (value !== null && value !== undefined && String(value).trim()) {
        const cluster = String(value);
        counts.set(cluster, (counts.get(cluster) ?? 0) + 1);
      }
    });
    return counts;
  })();
  const availableAnovaClusters = Array.from(anovaClusterSizes.keys()).sort((a, b) => Number(a) - Number(b));
  const anovaClusterOptions = [
    { value: "", label: availableAnovaClusters.length ? "Select a cluster" : "No clusters available" },
    ...availableAnovaClusters.map((cluster) => ({
      value: cluster,
      label: `Cluster ${cluster} (n=${anovaClusterSizes.get(cluster) ?? 0})`,
    })),
  ];

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        setDataSource((current) =>
          data.imputedAvailable
            ? (current === "imputed" ? "imputed" : "data")
            : "data"
        );
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition1Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2Control((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable]);

  const geneNamesAvailable = hasGeneNameSupport(options);
  const roundedClusterCount = Math.max(1, Math.round(nClusters));
  const anovaRequest = useMemo<AnovaRequest | null>(() => {
    if (
      sourceMode !== "anova" ||
      !kindAvailable ||
      !geneNamesAvailable ||
      !options ||
      options.availableConditions.length < 2
    ) {
      return null;
    }
    return {
      kind,
      source: "anova_cluster",
      dataSource,
      identifier: "genes",
      pValueThreshold,
      useUncorrected,
      showDendrograms: true,
      showLegend: true,
      nClusters: roundedClusterCount,
      // ORA runs off the cluster assignments; pairwise post-hoc is not involved.
      postHoc: "none",
    };
  }, [
    sourceMode,
    kindAvailable,
    geneNamesAvailable,
    options,
    kind,
    dataSource,
    pValueThreshold,
    useUncorrected,
    roundedClusterCount,
  ]);
  const debouncedAnovaRequest = useDebouncedValue(anovaRequest, 650);

  useEffect(() => {
    if (sourceMode !== "anova" || !debouncedAnovaRequest) return;
    const controller = new AbortController();
    runAnovaAnalysis(debouncedAnovaRequest, { signal: controller.signal })
      .then((response) => {
        setAnovaResult(response);
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setAnovaResult(null);
        setError(err instanceof Error ? err.message : "Failed to generate ANOVA clusters");
      });
    return () => {
      controller.abort();
    };
  }, [debouncedAnovaRequest, sourceMode]);

  const controlSelectionValid =
    sourceMode !== "volcano_control" ||
    new Set([condition1, condition2, condition1Control, condition2Control].filter(Boolean)).size === 4;
  const canRun = Boolean(
    kindAvailable &&
      geneNamesAvailable &&
      (sourceMode === "anova"
        ? selectedCluster && availableAnovaClusters.includes(selectedCluster)
        : condition1 &&
          condition2 &&
          condition1 !== condition2 &&
          controlSelectionValid &&
          (!isPairedTestType(testType) ||
            pairingIsReady(
              condition1,
              condition2,
              options?.samplesByCondition ?? {},
              options?.pairIdsBySample ?? {}
            )))
  );

  useEffect(() => {
    if (!onContextModeChange) return;
    const sanitize = (value: string) => String(value ?? "");
    const parts = [
      `source=${sourceMode}`,
      `kind=${kind}`,
      `dataSource=${dataSource}`,
      `condition1=${sanitize(condition1)}`,
      `condition2=${sanitize(condition2)}`,
      `condition1Control=${sanitize(condition1Control)}`,
      `condition2Control=${sanitize(condition2Control)}`,
      `testType=${testType}`,
      `pValueThreshold=${pValueThreshold}`,
      `log2fcThreshold=${log2fcThreshold}`,
      `useUncorrected=${useUncorrected ? "true" : "false"}`,
      `selectedCluster=${selectedCluster || "none"}`,
      `nClusters=${roundedClusterCount}`,
      `adjPValueCutoff=${adjPValueCutoff}`,
      `topN=${topN}`,
      `minTermSize=${minTermSize}`,
      `maxTermSize=${maxTermSize}`,
      `backgroundMode=${backgroundMode}`,
    ];
    onContextModeChange(contextMode(parts));
  }, [
    onContextModeChange,
    sourceMode,
    kind,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    selectedCluster,
    roundedClusterCount,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
  ]);

  useEffect(() => {
    if (!geneNamesAvailable || !canRun) return;

    const controller = new AbortController();

    runEnrichmentAnalysis({
      kind,
      source: sourceMode,
      dataSource,
      condition1,
      condition2,
      condition1Control: sourceMode === "volcano_control" ? condition1Control : null,
      condition2Control: sourceMode === "volcano_control" ? condition2Control : null,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
      selectedCluster: sourceMode === "anova" ? Number(selectedCluster) : null,
      nClusters: roundedClusterCount,
      adjPValueCutoff,
      topN,
      minTermSize,
      maxTermSize,
      backgroundMode,
    } satisfies EnrichmentRequest, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setResultState({ key: currentResultKey, data: response });
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setResultState(null);
        setError(err instanceof Error ? err.message : "Failed to run enrichment analysis");
      });

    return () => {
      controller.abort();
    };
  }, [
    canRun,
    geneNamesAvailable,
    kind,
    sourceMode,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    selectedCluster,
    roundedClusterCount,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
    currentResultKey,
  ]);

  const commonPlotParams = {
    source: sourceMode,
    dataSource,
    condition1,
    condition2,
    condition1Control: sourceMode === "volcano_control" ? condition1Control : "",
    condition2Control: sourceMode === "volcano_control" ? condition2Control : "",
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    nClusters: roundedClusterCount,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
  };
  const upPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/ora/up.png`, commonPlotParams);
  const downPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/ora/down.png`, commonPlotParams);
  const clusterPlotUrl =
    sourceMode === "anova" && selectedCluster
      ? buildPlotUrl(`/api/plots/stats/${kind}/ora/cluster.png`, {
          ...commonPlotParams,
          selectedCluster: Number(selectedCluster),
        })
      : null;

  useEffect(() => {
    writePersistedUiState("stats.ora.v1", {
      kind,
      condition1,
      condition2,
      sourceMode,
      dataSource,
      condition1Control,
      condition2Control,
      testType,
      pValueThreshold,
      log2fcThreshold,
      useUncorrected,
      selectedCluster,
      nClusters,
      adjPValueCutoff,
      topN,
      minTermSize,
      maxTermSize,
      backgroundMode,
    });
  }, [
    kind,
    condition1,
    condition2,
    sourceMode,
    dataSource,
    condition1Control,
    condition2Control,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    selectedCluster,
    nClusters,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
  ]);

  if (oraKindOptions.length === 0) {
    return (
      <div className="space-y-6">
        <SectionCard title="GO Enrichment (ORA)">
          <InfoSection message="Load a protein or phosphoproteome dataset to run GO over-representation analysis." />
        </SectionCard>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard title="GO Enrichment (ORA)">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={oraKindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div>
          <div className="max-w-xs">
            <SelectField
              label="Analysis source"
              value={sourceMode === "anova" ? "anova" : "volcano"}
              onChange={(value) => setSourceMode(value === "anova" ? "anova" : "volcano")}
              options={[
                { value: "volcano", label: "Volcano" },
                { value: "anova", label: "ANOVA" },
              ]}
            />
          </div>

          {sourceMode === "anova" ? (
            <div className="mt-6 border-t border-slate-200 pt-6">
              <h4 className="text-sm font-semibold text-slate-900">ANOVA Options</h4>
              <div className="mt-3 grid gap-4 lg:grid-cols-2">
                <SelectField
                  label="Source"
                  value="anova"
                  onChange={() => undefined}
                  options={[{ value: "anova", label: "ANOVA Cluster" }]}
                  disabled
                />
                <SelectField
                  label="Data Source"
                  value={dataSource}
                  onChange={(value) => setDataSource(value as "data" | "imputed")}
                  options={oraDataSourceOptions}
                />
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
                <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
                <NumberField label="Clusters" value={nClusters} onChange={(value) => setNClusters(Math.max(1, Math.round(value)))} />
                <SelectField label="Protein cluster" value={selectedCluster} onChange={setSelectedCluster} options={anovaClusterOptions} />
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
              </div>
            </div>
          ) : (
            <div className="mt-6 border-t border-slate-200 pt-6">
              <h4 className="text-sm font-semibold text-slate-900">Volcano Options</h4>
              <div className="mt-3 grid gap-4 lg:grid-cols-2">
                <SelectField
                  label="Source"
                  value={sourceMode}
                  onChange={(value) => setSourceMode(value as "volcano" | "volcano_control")}
                  options={[
                    { value: "volcano", label: "Volcano" },
                    { value: "volcano_control", label: "Volcano Control" },
                  ]}
                />
                <SelectField
                  label="Data Source"
                  value={dataSource}
                  onChange={(value) => setDataSource(value as "data" | "imputed")}
                  options={oraDataSourceOptions}
                />
              </div>
              {sourceMode === "volcano_control" ? (
                <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
                  <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
                  <SelectField
                    label="Condition 1 Control"
                    value={condition1Control}
                    onChange={setCondition1Control}
                    options={conditionOptions(options)}
                  />
                  <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
                  <SelectField
                    label="Condition 2 Control"
                    value={condition2Control}
                    onChange={setCondition2Control}
                    options={conditionOptions(options)}
                  />
                </div>
              ) : (
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
                  <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
                </div>
              )}
              <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
                <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as StatsTestType)} options={sourceMode === "volcano_control" ? CONTROL_TEST_TYPE_OPTIONS : TEST_TYPE_OPTIONS} />
                <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
                <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
              </div>
              {isPairedTestType(testType) ? (
                <PairingEditor
                  kind={kind}
                  condition1={condition1}
                  condition2={condition2}
                  samplesByCondition={options?.samplesByCondition ?? {}}
                  pairIdsBySample={options?.pairIdsBySample ?? {}}
                  onSaved={async () => setOptions(await getStatisticalOptions(kind))}
                />
              ) : null}
              <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
              </div>
            </div>
          )}
        </div>
        <div className="mt-6 border-t border-slate-200 pt-6">
          <h4 className="text-sm font-semibold text-slate-900">ORA Options</h4>
          <div className="mt-3 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
            <NumberField
              label="Adj p-value cutoff"
              value={adjPValueCutoff}
              onChange={(value) => setAdjPValueCutoff(Math.max(1e-12, Math.min(1, value)))}
              step={0.001}
            />
            <NumberField label="Top terms" value={topN} onChange={(value) => setTopN(Math.max(1, Math.round(value)))} />
            <NumberField label="Min term size" value={minTermSize} onChange={(value) => setMinTermSize(Math.max(1, Math.round(value)))} />
            <NumberField label="Max term size" value={maxTermSize} onChange={(value) => setMaxTermSize(Math.max(1, Math.round(value)))} />
            <SelectField
              label="Background"
              value={backgroundMode}
              onChange={(value) => setBackgroundMode(value as "experiment" | "global")}
              options={[
                { value: "experiment", label: "Tested genes in this analysis (recommended)" },
                { value: "global", label: "All annotated human genes (global)" },
              ]}
            />
          </div>
          <p className="mt-3 text-xs text-slate-600">
            {backgroundMode === "experiment"
              ? "ORA uses every gene that received the selected upstream statistical test."
              : "Global background can overstate enrichment when detectability is restricted by the experiment."}
          </p>
        </div>
        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {advancedPlotOptions}
      {options && !geneNamesAvailable ? <InfoSection message="Gene names are required for ORA. Please generate or load gene names first." /> : null}
      {options && geneNamesAvailable && !canRun ? (
        <InfoSection
          message={
            sourceMode === "anova"
              ? anovaResult?.significantCount === 0
                ? "No rows passed the selected ANOVA threshold, so no clusters are available for ORA."
                : availableAnovaClusters.length
                ? "Select a protein cluster to run ORA."
                : "ANOVA clusters are being generated from conditions with replicate samples."
              : sourceMode === "volcano_control"
              ? "Please select four different conditions and controls to generate the plot."
              : "Please select two different conditions to generate the plot."
          }
        />
      ) : null}
      {canRun && result ? (
        <>
          <OraProvenanceSection result={result} />
          {sourceMode === "anova" ? (
          <>
            <SummarySection
              items={[
                { label: "Cluster", value: String(result.selectedCluster ?? selectedCluster) },
                { label: "Genes", value: String(result.clusterGenes.length) },
                { label: "Terms", value: String(result.clusterTerms.length) },
                { label: "Background", value: result.backgroundMode === "experiment" ? "Tested genes" : "All annotated genes" },
                { label: "Background genes", value: String(result.backgroundSize) },
                { label: "Annotated background", value: String(result.annotatedBackgroundSize) },
                { label: "Organism", value: result.organism },
              ]}
              warnings={result.warnings}
            />
            {result.clusterGenes.length > 0 && result.clusterTerms.length > 0 && clusterPlotUrl ? (
              <ImageSection title={`ANOVA Cluster ${result.selectedCluster ?? selectedCluster} Terms`} url={clusterPlotUrl} />
            ) : (
              <InfoSection
                message={
                  result.clusterGenes.length === 0
                    ? `ANOVA cluster ${result.selectedCluster ?? selectedCluster} does not contain genes that can be used for ORA.`
                    : "No enrichment terms were found for the selected ANOVA cluster and parameters."
                }
              />
            )}
            <GeneListSection
              title={`ANOVA Cluster ${result.selectedCluster ?? selectedCluster} Genes`}
              genes={result.clusterGenes}
              filename={`ora_anova_cluster_${result.selectedCluster ?? selectedCluster}_${kind}.txt`}
            />
            {result.backgroundMode === "experiment" ? (
              <GeneListSection
                title="Tested-gene Background"
                genes={result.backgroundGenes}
                filename={`ora_background_${kind}.txt`}
              />
            ) : null}
            <TableSection
              title={`ANOVA Cluster ${result.selectedCluster ?? selectedCluster} Terms`}
              rows={oraExportRows(result.clusterTerms, result, {
                analysisSource: sourceMode,
                selectedCluster: result.selectedCluster ?? selectedCluster,
                pValueThreshold,
                useUncorrected,
                nClusters: roundedClusterCount,
                adjPValueCutoff,
                minTermSize,
                maxTermSize,
              })}
              filename={`ora_anova_cluster_${result.selectedCluster ?? selectedCluster}_${kind}.csv`}
            />
          </>
        ) : (
          <>
            <SummarySection
              items={[
                { label: "Up Genes", value: String(result.upGenes.length) },
                { label: "Down Genes", value: String(result.downGenes.length) },
                { label: "Up Terms", value: String(result.upTerms.length) },
                { label: "Down Terms", value: String(result.downTerms.length) },
                { label: "Background", value: result.backgroundMode === "experiment" ? "Tested genes" : "All annotated genes" },
                { label: "Background genes", value: String(result.backgroundSize) },
                { label: "Annotated background", value: String(result.annotatedBackgroundSize) },
                { label: "Organism", value: result.organism },
              ]}
              warnings={result.warnings}
            />
            <div className="grid gap-6 xl:grid-cols-2">
              {result.upGenes.length > 0 && result.upTerms.length > 0 ? (
                <ImageSection title="Upregulated Terms" url={upPlotUrl} />
              ) : (
                <InfoSection
                  message={
                    result.upGenes.length === 0
                      ? "Upregulated gene list is empty. Upregulated ORA plot is not generated."
                      : "No upregulated enrichment terms found for the selected parameters."
                  }
                />
              )}
              {result.downGenes.length > 0 && result.downTerms.length > 0 ? (
                <ImageSection title="Downregulated Terms" url={downPlotUrl} />
              ) : (
                <InfoSection
                  message={
                    result.downGenes.length === 0
                      ? "Downregulated gene list is empty. Downregulated ORA plot is not generated."
                      : "No downregulated enrichment terms found for the selected parameters."
                  }
                />
              )}
            </div>
            <GeneListSection title="Upregulated Genes" genes={result.upGenes} filename={`ora_up_${kind}.txt`} />
            <GeneListSection title="Downregulated Genes" genes={result.downGenes} filename={`ora_down_${kind}.txt`} />
            {result.backgroundMode === "experiment" ? (
              <GeneListSection title="Tested-gene Background" genes={result.backgroundGenes} filename={`ora_background_${kind}.txt`} />
            ) : null}
            <TableSection
              title="Upregulated Terms"
              rows={oraExportRows(result.upTerms, result, {
                analysisSource: sourceMode,
                direction: "up",
                condition1,
                condition2,
                condition1Control: sourceMode === "volcano_control" ? condition1Control : "",
                condition2Control: sourceMode === "volcano_control" ? condition2Control : "",
                testType,
                pValueThreshold,
                log2fcThreshold,
                useUncorrected,
                adjPValueCutoff,
                minTermSize,
                maxTermSize,
              })}
              filename={`ora_up_${kind}.csv`}
            />
            <TableSection
              title="Downregulated Terms"
              rows={oraExportRows(result.downTerms, result, {
                analysisSource: sourceMode,
                direction: "down",
                condition1,
                condition2,
                condition1Control: sourceMode === "volcano_control" ? condition1Control : "",
                condition2Control: sourceMode === "volcano_control" ? condition2Control : "",
                testType,
                pValueThreshold,
                log2fcThreshold,
                useUncorrected,
                adjPValueCutoff,
                minTermSize,
                maxTermSize,
              })}
              filename={`ora_down_${kind}.csv`}
            />
          </>
          )}
        </>
      ) : null}
    </div>
  );
}

function PathwayHeatmapPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
}) {
  useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("stats.pathwayHeatmap.v1", {}),
    []
  );
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const kind = (kindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : kindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [pathways, setPathways] = useState<PathwayOptionsResponse | null>(null);
  const [pathway, setPathway] = useState(() => String(persisted.pathway ?? ""));
  const [selectedConditions, setSelectedConditions] = useState<string[]>(() =>
    Array.isArray(persisted.selectedConditions)
      ? persisted.selectedConditions.map((value) => String(value ?? ""))
      : []
  );
  const [valueType, setValueType] = useState<"log2" | "z">(() =>
    String(persisted.valueType ?? "z") === "log2" ? "log2" : "z"
  );
  const [dataSource, setDataSource] = useState<"data" | "imputed">(() =>
    String(persisted.dataSource ?? "data") === "imputed" ? "imputed" : "data"
  );
  const [includeId, setIncludeId] = useState(() => Boolean(persisted.includeId ?? false));
  const [header, setHeader] = useState(() => Boolean(persisted.header ?? true));
  const [removeEmpty, setRemoveEmpty] = useState(() => Boolean(persisted.removeEmpty ?? true));
  const [clusterRows, setClusterRows] = useState(() => Boolean(persisted.clusterRows ?? false));
  const [clusterCols, setClusterCols] = useState(() => Boolean(persisted.clusterCols ?? false));
  const [widthCm, setWidthCm] = useState(() => Number(persisted.widthCm ?? 20));
  const [heightCm, setHeightCm] = useState(() => Number(persisted.heightCm ?? 12));
  const [dpi, setDpi] = useState(() => Number(persisted.dpi ?? 300));
  const [error, setError] = useState<string | null>(null);
  const geneNamesAvailable = hasGeneNameSupport(options);
  const kindAvailable = kindOptions.some((option) => option.value === kind);

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        if (!data.imputedAvailable) {
          setDataSource((current) => (current === "imputed" ? "data" : current));
        }
        setSelectedConditions((current) => (current.length ? current.filter((item) => data.availableConditions.includes(item)) : data.availableConditions));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable]);

  useEffect(() => {
    const controller = new AbortController();
    getPathwayOptions({ signal: controller.signal })
      .then((data) => {
        setPathways(data);
        setPathway((current) => current || data.pathways[0] || "");
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load pathway options");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!onContextModeChange) return;
    const sanitize = (value: string) => String(value ?? "");
    const parts = [
      `kind=${kind}`,
      `pathway=${sanitize(pathway)}`,
      `conditions=${JSON.stringify(selectedConditions)}`,
      `valueType=${valueType}`,
      `dataSource=${dataSource}`,
      `removeEmpty=${removeEmpty ? "true" : "false"}`,
      `includeId=${includeId ? "true" : "false"}`,
      `header=${header ? "true" : "false"}`,
      `clusterRows=${clusterRows ? "true" : "false"}`,
      `clusterCols=${clusterCols ? "true" : "false"}`,
    ];
    onContextModeChange(contextMode(parts));
  }, [
    onContextModeChange,
    kind,
    pathway,
    selectedConditions,
    valueType,
    dataSource,
    removeEmpty,
    includeId,
    header,
    clusterRows,
    clusterCols,
  ]);

  const heatmapUrl = buildPlotUrl(`/api/plots/stats/${kind}/pathway-heatmap.png`, {
    pathway,
    dataSource,
    conditions: JSON.stringify(selectedConditions),
    valueType,
    includeId,
    header,
    removeEmpty,
    clusterRows,
    clusterCols,
    widthCm,
    heightCm,
    dpi,
  });

  useEffect(() => {
    writePersistedUiState("stats.pathwayHeatmap.v1", {
      kind,
      pathway,
      selectedConditions,
      valueType,
      dataSource,
      includeId,
      header,
      removeEmpty,
      clusterRows,
      clusterCols,
      widthCm,
      heightCm,
      dpi,
    });
  }, [
    kind,
    pathway,
    selectedConditions,
    valueType,
    dataSource,
    includeId,
    header,
    removeEmpty,
    clusterRows,
    clusterCols,
    widthCm,
    heightCm,
    dpi,
  ]);

  return (
    <div className="space-y-6">
      <SectionCard title="Pathway Heatmap">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-3">
          <SelectField label="Pathway" value={pathway} onChange={setPathway} options={(pathways?.pathways ?? []).map((item) => ({ value: item, label: item }))} />
          <SelectField label="Value type" value={valueType} onChange={(value) => setValueType(value as "log2" | "z")} options={[{ value: "z", label: "Z-score" }, { value: "log2", label: "log2" }]} />
          <SelectField
            label="Data source"
            value={dataSource}
            onChange={(value) => setDataSource(value as "data" | "imputed")}
            options={options?.imputedAvailable
              ? [{ value: "data", label: "Data" }, { value: "imputed", label: "Imputed Data" }]
              : [{ value: "data", label: "Data" }]}
          />
        </div>
        <div className="mt-4">
          <label htmlFor="pathway-conditions" className="mb-2 block text-sm font-medium text-slate-700">Conditions</label>
          <MultiSelect values={selectedConditions} onChange={setSelectedConditions} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <NumberField label="Width (cm)" value={widthCm} onChange={(value) => setWidthCm(clampPlotDimensionCm(value))} step={1} />
          <NumberField label="Height (cm)" value={heightCm} onChange={(value) => setHeightCm(clampPlotDimensionCm(value))} step={1} />
          <NumberField label="DPI" value={dpi} onChange={(value) => setDpi(clampPlotDpi(value))} />
        </div>
        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Show gene labels" checked={header} onChange={setHeader} />
            <CheckboxField label="Toggle ID" checked={includeId} onChange={setIncludeId} />
            <CheckboxField label="Remove empty genes" checked={removeEmpty} onChange={setRemoveEmpty} />
            <CheckboxField label="Cluster rows" checked={clusterRows} onChange={setClusterRows} />
            <CheckboxField label="Cluster columns" checked={clusterCols} onChange={setClusterCols} />
          </div>
        </div>
        <Notice error={error} warnings={options?.warnings} />
        {(clusterRows || clusterCols) && dataSource !== "imputed" ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Clustering uses only complete values. If this Data matrix contains missing values, select a successfully imputed dataset or disable clustering; values and data sources are never changed automatically.
          </div>
        ) : null}
      </SectionCard>
      {advancedPlotOptions}
      {!geneNamesAvailable && options ? <InfoSection message="Gene names are required for pathway heatmaps. Please generate or load gene names first." /> : null}
      {geneNamesAvailable && pathway && selectedConditions.length > 0 ? <ImageSection title="Pathway Heatmap" url={heatmapUrl} /> : null}
    </div>
  );
}

function SimulationPanel({
  kindOptions,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  advancedPlotOptions?: ReactNode;
}) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("stats.simulation.v1", {}),
    []
  );
  const revision = useDatasetRevision();
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const kind = (kindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : kindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [dataSource, setDataSource] = useState<"data" | "imputed">(() => {
    const value = String(persisted.dataSource ?? "data").trim();
    return value === "imputed" ? "imputed" : "data";
  });
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [condition1, setCondition1] = useState(() => String(persisted.condition1 ?? ""));
  const [condition2, setCondition2] = useState(() => String(persisted.condition2 ?? ""));
  const [identifier, setIdentifier] = useState<StatsIdentifier>(() => {
    const value = String(persisted.identifier ?? "workflow").trim();
    return value === "genes" ? "genes" : "workflow";
  });
  const [testType, setTestType] = useState<SimulationTestType>(() => {
    return restoreSimulationTestType(persisted.testType);
  });
  const [pValueThreshold, setPValueThreshold] = useState(() => Number(persisted.pValueThreshold ?? 0.05));
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [varianceMultiplier, setVarianceMultiplier] = useState(() => Number(persisted.varianceMultiplier ?? 1));
  const restoredSampleSize = restoreSimulationSampleSize(persisted.sampleSizeOverride);
  const [sampleSizeOverride, setSampleSizeOverride] = useState(() => restoredSampleSize.value);
  const [sampleSizeInputError, setSampleSizeInputError] = useState<string | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: SimulationResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const currentResultKey = JSON.stringify({
    revision,
    kind,
    source: "volcano",
    dataSource,
    condition1,
    condition2,
    identifier,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    varianceMultiplier,
    sampleSizeOverride,
  });
  const result = resultState?.key === currentResultKey ? resultState.data : null;
  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const simulationDataSourceOptions = useMemo(
    () =>
      options?.imputedAvailable
        ? [
            { value: "data", label: "Data" },
            { value: "imputed", label: "Imputed Data" },
          ]
        : [{ value: "data", label: "Data" }],
    [options?.imputedAvailable]
  );

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        setDataSource((current) =>
          data.imputedAvailable
            ? (current === "imputed" ? "imputed" : "data")
            : "data"
        );
        setCondition1((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setCondition2((current) => (data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""));
        setIdentifier((current) => (data.availableIdentifiers.some((item) => item.key === current) ? current : data.availableIdentifiers[0]?.key ?? "workflow"));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable]);

  const canRun = Boolean(
    kindAvailable &&
      condition1 &&
      condition2 &&
      condition1 !== condition2
  );
  const requestPayload = useMemo<SimulationRequest | null>(() => {
    if (!canRun) return null;
    return {
      kind,
      source: "volcano",
      dataSource,
      condition1,
      condition2,
      identifier,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
      varianceMultiplier,
      sampleSizeOverride,
    };
  }, [
    canRun,
    kind,
    dataSource,
    condition1,
    condition2,
    identifier,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    varianceMultiplier,
    sampleSizeOverride,
  ]);
  const debouncedRequestPayload = useDebouncedValue(requestPayload, 650);

  useEffect(() => {
    if (!debouncedRequestPayload) return;

    const controller = new AbortController();

    runSimulationAnalysis(debouncedRequestPayload, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setResultState({ key: JSON.stringify({ revision, ...debouncedRequestPayload }), data: response });
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setResultState(null);
        setError(err instanceof Error ? err.message : "Failed to run simulation");
      });

    return () => {
      controller.abort();
    };
  }, [
    debouncedRequestPayload,
    revision,
  ]);

  const plotUrl = useMemo(() => {
    void advancedPlotSignal;
    if (!debouncedRequestPayload) return "";
    return buildPlotUrl(`/api/plots/stats/${debouncedRequestPayload.kind}/simulation.html`, {
      dataSource: debouncedRequestPayload.dataSource,
      condition1: debouncedRequestPayload.condition1,
      condition2: debouncedRequestPayload.condition2,
      identifier: debouncedRequestPayload.identifier,
      pValueThreshold: debouncedRequestPayload.pValueThreshold,
      log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
      testType: debouncedRequestPayload.testType,
      useUncorrected: debouncedRequestPayload.useUncorrected,
      varianceMultiplier: debouncedRequestPayload.varianceMultiplier,
      sampleSizeOverride: debouncedRequestPayload.sampleSizeOverride,
    });
  }, [debouncedRequestPayload, advancedPlotSignal, revision]);

  useEffect(() => {
    writePersistedUiState("stats.simulation.v1", {
      kind,
      dataSource,
      condition1,
      condition2,
      identifier,
      testType,
      pValueThreshold,
      log2fcThreshold,
      useUncorrected,
      varianceMultiplier,
      sampleSizeOverride,
    });
  }, [
    kind,
    dataSource,
    condition1,
    condition2,
    identifier,
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    varianceMultiplier,
    sampleSizeOverride,
  ]);

  return (
    <div className="space-y-6">
      <SectionCard title="Simulation Volcano Plot">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Source"
            value="volcano"
            onChange={() => undefined}
            options={[{ value: "volcano", label: "Volcano" }]}
            disabled
          />
          <SelectField
            label="Data Source"
            value={dataSource}
            onChange={(value) => setDataSource(value as "data" | "imputed")}
            options={simulationDataSourceOptions}
          />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField label="Condition 1" value={condition1} onChange={setCondition1} options={conditionOptions(options)} />
          <SelectField label="Condition 2" value={condition2} onChange={setCondition2} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Label column" value={identifier} onChange={(value) => setIdentifier(value as StatsIdentifier)} options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))} />
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as SimulationTestType)} options={SIMULATION_TEST_TYPE_OPTIONS} />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
        </div>

        <div className="mt-6 border-t border-slate-200 pt-6">
          <h4 className="text-sm font-semibold text-slate-900">Simulation Options</h4>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <NumberField label="Variance multiplier" value={varianceMultiplier} onChange={(value) => setVarianceMultiplier(Math.max(0.01, value))} step={0.05} />
            <div>
              <NumberField
                label="Sample size override (0 = observed)"
                value={sampleSizeOverride}
                onChange={setSampleSizeOverride}
                validate={validateSimulationSampleSize}
                onValidationError={setSampleSizeInputError}
              />
              <p className="mt-1 text-xs text-slate-500">Use 0 for each row&apos;s observed replicate counts, or 2-100 for a fixed per-group simulation size.</p>
            </div>
          </div>
        </div>
        <Notice
          error={sampleSizeInputError ?? error}
          warnings={[
            ...removeSourceUsageWarnings(options?.warnings),
            ...(restoredSampleSize.warning ? [restoredSampleSize.warning] : []),
          ]}
        />
      </SectionCard>
      {advancedPlotOptions}
      {!canRun && options ? (
        <InfoSection message="Please select two different conditions to generate the plot." />
      ) : null}
      {debouncedRequestPayload && result ? (
        <>
          <SummarySection items={[
            { label: "Method", value: result.testType === "unpaired_welch" ? "Welch unpaired t-test" : "Student's unpaired t-test" },
            { label: "Sample-size mode", value: result.sampleSizeMode === "observed" ? "Observed per row" : `Fixed n=${result.sampleSizeOverride}` },
            { label: `${result.condition1} effective n`, value: formatEffectiveSampleSize(result.effectiveSampleSizeCondition1Min, result.effectiveSampleSizeCondition1Max) },
            { label: `${result.condition2} effective n`, value: formatEffectiveSampleSize(result.effectiveSampleSizeCondition2Min, result.effectiveSampleSizeCondition2Max) },
            { label: "Rows", value: String(result.totalRows) },
            { label: "Upregulated", value: String(result.upregulatedCount) },
            { label: "Downregulated", value: String(result.downregulatedCount) },
            { label: "Not Significant", value: String(result.notSignificantCount) },
          ]} warnings={removeSourceUsageWarnings(result.warnings)} />
          <PlotFrame title="Simulation Volcano Plot" url={plotUrl} height={760} />
        </>
      ) : null}
    </div>
  );
}
