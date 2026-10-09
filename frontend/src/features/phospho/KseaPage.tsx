import NumberField from "../../components/NumberField";
import { AssistantInput, AssistantSelect } from "../../components/AssistantFields";
import CheckboxField from "../../components/CheckboxField";
import { collectColumns } from "../../lib/tableData";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { TEST_TYPE_VALUES, TEST_TYPE_LABELS, restoreTestType, CONTROL_TEST_TYPE_OPTIONS, controlTestType } from "../../lib/statisticalTests";
import type { ContextMode, StatsTestType, DataSource } from "../../lib/types";
import {
  dataSourceOptions,
} from "../../lib/types";
import {
  getPhosphoOptions,
  getPhosphoTable,
  isAbortError,
  pairingIsReady,
  renderKseaVolcanoFromFiles,
} from "../../lib/api";
import PaginatedTable from "../../components/PaginatedTable";
import PairingEditor from "../../components/PairingEditor";
import { useCurrentDatasetsSnapshot, useDatasetRevision } from "../../lib/datasetAvailability";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { PhosphoOptionsResponse } from "../../lib/types";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import SelectField from "../../components/SelectField";
import NotebookDownload from "../../components/NotebookDownload";

const NO_TABLE_ROWS: Record<string, unknown>[] = [];

type KseaSourceMode = "volcano" | "volcano_control";

// Motif windows are read from this reference proteome at each site position;
// "none" keeps the peptide-only window. Values match phospho_tools.KSEA_ORGANISMS.
type KseaOrganism = "human" | "mouse" | "none";
const KSEA_ORGANISM_VALUES: KseaOrganism[] = ["human", "mouse", "none"];
const KSEA_ORGANISM_LABELS: Record<KseaOrganism, string> = {
  human: "Human (UP000005640)",
  mouse: "Mouse (UP000000589)",
  none: "None (peptide sequence only)",
};

type Props = {
  onContextModeChange?: (mode: ContextMode | null) => void;
  advancedPlotOptions?: ReactNode;
};

export default function KseaPage({ advancedPlotOptions, onContextModeChange }: Props) {
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("phospho.ksea.v1", {}),
    []
  );
  const { datasets } = useCurrentDatasetsSnapshot();
  const revision = useDatasetRevision();
  const hasPhosphoDataset = Boolean(datasets?.phospho);
  const [options, setOptions] = useState<PhosphoOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [condition1, setCondition1] = useState(() => String(persisted.condition1 ?? ""));
  const [condition2, setCondition2] = useState(() => String(persisted.condition2 ?? ""));
  const [sourceMode, setSourceMode] = useState<KseaSourceMode>(() =>
    persisted.sourceMode === "volcano_control" ? "volcano_control" : "volcano"
  );
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const [condition1Control, setCondition1Control] = useState(() => String(persisted.condition1Control ?? ""));
  const [condition2Control, setCondition2Control] = useState(() => String(persisted.condition2Control ?? ""));
  const [pValueThreshold, setPValueThreshold] = useState(() => Number(persisted.pValueThreshold ?? 0.05));
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1.0));
  const [selectedTestType, setTestType] = useState<StatsTestType>(() =>
    restoreTestType(persisted.testType)
  );
  const testType = sourceMode === "volcano_control" ? controlTestType(selectedTestType) : selectedTestType;
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [organism, setOrganism] = useState<KseaOrganism>(() =>
    KSEA_ORGANISM_VALUES.includes(persisted.organism as KseaOrganism) ? (persisted.organism as KseaOrganism) : "human"
  );

  const [tableResult, setTableResult] = useState<{ rows: Record<string, unknown>[]; requestKey: string; token: string | null } | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);

  const [fileSt, setFileSt] = useState<File | null>(null);
  const [fileTnc, setFileTnc] = useState<File | null>(null);
  const [volcanoPValueThreshold, setVolcanoPValueThreshold] = useState(() => Number(persisted.volcanoPValueThreshold ?? 0.1));
  // Shown or hidden from the advanced panel's Title card, like every other plot.
  const volcanoHeader = true;
  const [annotateHits, setAnnotateHits] = useState(() => Boolean(persisted.annotateHits ?? false));
  const [volcanoHtml, setVolcanoHtml] = useState("");
  const [externalEvidenceToken, setExternalEvidenceToken] = useState("");
  const [volcanoLoading, setVolcanoLoading] = useState(false);
  const [volcanoError, setVolcanoError] = useState<string | null>(null);
  useEffect(() => {
    onContextModeChange?.({ kind: "phospho", source: sourceMode, dataSource,
      condition1, condition2, condition1Control, condition2Control, pValueThreshold,
      log2fcThreshold, testType, useUncorrected, organism, externalPlotPresent: Boolean(volcanoHtml), externalEvidenceToken });
  }, [onContextModeChange, sourceMode, dataSource, condition1, condition2, condition1Control,
    condition2Control, pValueThreshold, log2fcThreshold, testType, useUncorrected, organism, volcanoHtml, externalEvidenceToken]);

  useEffect(() => {
    writePersistedUiState("phospho.ksea.v1", {
      condition1,
      condition2,
      sourceMode,
      dataSource,
      condition1Control,
      condition2Control,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
      organism,
      volcanoPValueThreshold,
      volcanoHeader,
      annotateHits,
    });
  }, [
    condition1,
    condition2,
    sourceMode,
    dataSource,
    condition1Control,
    condition2Control,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    organism,
    volcanoPValueThreshold,
    volcanoHeader,
    annotateHits,
  ]);

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError("No phospho dataset loaded.");
      return;
    }
    const controller = new AbortController();
    setOptionsLoading(true);
    setOptionsError(null);
    getPhosphoOptions({ signal: controller.signal })
      .then((payload) => {
        setOptions(payload);
        applyDataSourceChoices(payload);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load phospho options");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setOptionsLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [hasPhosphoDataset, applyDataSourceChoices]);

  useEffect(() => {
    const conditionOptions = options?.conditions ?? [];
    if (conditionOptions.length === 0) return;
    const first = conditionOptions[0];
    setCondition1((prev) => (conditionOptions.includes(prev) ? prev : first));
    setCondition2((prev) => (conditionOptions.includes(prev) ? prev : first));
    setCondition1Control((prev) => (conditionOptions.includes(prev) ? prev : first));
    setCondition2Control((prev) => (conditionOptions.includes(prev) ? prev : first));
  }, [options]);

  const controlSelectionValid =
    sourceMode !== "volcano_control" ||
    new Set([condition1, condition2, condition1Control, condition2Control].filter(Boolean)).size === 4;

  const validSelection =
    condition1.trim() !== "" &&
    condition2.trim() !== "" &&
    condition1 !== condition2 &&
    controlSelectionValid &&
    (testType !== "paired" ||
      pairingIsReady(
        condition1,
        condition2,
        options?.samplesByCondition ?? {},
        options?.pairIdsBySample ?? {}
      ));
  const tableRequest = useMemo(() => {
    if (!validSelection) return null;
    return {
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
      organism,
    };
  }, [
    validSelection,
    sourceMode,
    dataSource,
    condition1,
    condition2,
    condition1Control,
    condition2Control,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
    organism,
  ]);
  const debouncedTableRequest = useDebouncedValue(tableRequest, 650);
  // One shared empty array: a fresh `[]` here is a new identity every render,
  // which made every memo downstream of tableRows recompute every render.
  const tableRows = tableResult?.requestKey === JSON.stringify({ revision, ...tableRequest })
    ? tableResult.rows
    : NO_TABLE_ROWS;

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setTableResult(null);
      setTableLoading(false);
      setTableError("No phospho dataset loaded.");
      return;
    }
    if (!debouncedTableRequest) {
      setTableResult(null);
      setTableLoading(false);
      setTableError(null);
      return;
    }
    const controller = new AbortController();
    setTableLoading(true);
    setTableError(null);
    getPhosphoTable("ksea", debouncedTableRequest, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setTableResult({ rows: payload.rows ?? [], requestKey: JSON.stringify({ revision, ...debouncedTableRequest }),
          token: payload.notebookToken ?? null });
      })
      .catch((err) => {
        if (controller.signal.aborted || isAbortError(err)) return;
        setTableResult(null);
        setTableError(err instanceof Error ? err.message : "Failed to load Kinase Library table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [
    hasPhosphoDataset,
    debouncedTableRequest,
    revision,
  ]);

  // Rows whose window could not be read from the protein sequence (accession
  // absent from the selected proteome, or residue/position mismatch) keep the
  // peptide-only window, which pads uncovered flanks with "_".
  const peptideWindowCount = useMemo(
    () => tableRows.filter((row) => row.window_source === "peptide").length,
    [tableRows]
  );

  const tsvDownload = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    const body = rowsToDelimited(tableRows, columns, "\t");
    return `data:text/tab-separated-values;charset=utf-8,${encodeURIComponent(body)}`;
  }, [tableRows]);
  const kseaComparisonLabel = useMemo(() => {
    const c1 = toFilenameToken(condition1);
    const c2 = toFilenameToken(condition2);
    const c1Ctrl = toFilenameToken(condition1Control);
    const c2Ctrl = toFilenameToken(condition2Control);
    if (sourceMode === "volcano_control") {
      // Condition 1 is the minuend: the exported log2FC is
      // (cond1 - its control) - (cond2 - its control). Written the other way
      // round, the file name claimed the opposite sign to the numbers in it.
      return `(${c1}-${c1Ctrl})_minus_(${c2}-${c2Ctrl})`;
    }
    return `${c1}_vs_${c2}`;
  }, [sourceMode, condition1, condition2, condition1Control, condition2Control]);

  async function generateVolcano() {
    if (!(fileSt && fileTnc)) {
      setVolcanoError("Please upload both Kinase Library result files.");
      return;
    }
    if (!validSelection) {
      setVolcanoError(
        sourceMode === "volcano_control"
          ? "Please select four different conditions (Condition 1/2 and both controls)."
          : "Please select two different conditions to generate the plot."
      );
      return;
    }
    setVolcanoLoading(true);
    setVolcanoError(null);
    try {
      const html = await renderKseaVolcanoFromFiles({
        fileSt,
        fileTnc,
        pValueThreshold: volcanoPValueThreshold,
        header: volcanoHeader,
        condition1,
        condition2,
        condition1Control: sourceMode === "volcano_control" ? condition1Control : "",
        condition2Control: sourceMode === "volcano_control" ? condition2Control : "",
        annotateHits,
      });
      setVolcanoHtml(html.html);
      setExternalEvidenceToken(html.evidenceToken);
    } catch (err) {
      setVolcanoHtml("");
      setExternalEvidenceToken("");
      setVolcanoError(err instanceof Error ? err.message : "Failed to generate Kinase Library volcano");
    } finally {
      setVolcanoLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Kinase Library Input Table</h3>
        {!hasPhosphoDataset ? (
          <InfoNotice message="No phospho dataset loaded. Upload data in the Data tab first." />
        ) : optionsLoading ? (
          <NeutralNotice message="Loading options..." />
        ) : optionsError ? (
          <ErrorNotice message={optionsError} />
        ) : (
          <div className="mt-4 space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-2 block font-medium text-slate-700">Source</span>
                <AssistantSelect
                  value={sourceMode}
                  onChange={(event) => setSourceMode(event.target.value as KseaSourceMode)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
                >
                  <option value="volcano">Volcano</option>
                  <option value="volcano_control">Volcano Control</option>
                </AssistantSelect>
              </label>
              <label className="block text-sm">
                <span className="mb-2 block font-medium text-slate-700">Data Source</span>
                <AssistantSelect
                  value={dataSource}
                  onChange={(event) => chooseDataSource(event.target.value as DataSource)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
                >
                  {dataSourceOptions(options).map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </AssistantSelect>
              </label>
            </div>
            {sourceMode === "volcano_control" ? (
              <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
                <SelectField
                  label="Condition 1"
                  value={condition1}
                  options={options?.conditions ?? []}
                  onChange={setCondition1}
                />
                <SelectField
                  label="Condition 1 Control"
                  value={condition1Control}
                  options={options?.conditions ?? []}
                  onChange={setCondition1Control}
                />
                <SelectField
                  label="Condition 2"
                  value={condition2}
                  options={options?.conditions ?? []}
                  onChange={setCondition2}
                />
                <SelectField
                  label="Condition 2 Control"
                  value={condition2Control}
                  options={options?.conditions ?? []}
                  onChange={setCondition2Control}
                />
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                <SelectField
                  label="Condition 1"
                  value={condition1}
                  options={options?.conditions ?? []}
                  onChange={setCondition1}
                />
                <SelectField
                  label="Condition 2"
                  value={condition2}
                  options={options?.conditions ?? []}
                  onChange={setCondition2}
                />
              </div>
            )}
            <div className="grid gap-4 lg:grid-cols-2">
              <NumberField
                label="P-value Threshold"
                value={pValueThreshold}
                onChange={(value) => setPValueThreshold(Math.max(1e-12, Math.min(1, value)))}
              />
              <NumberField
                label="log2 FC Threshold"
                value={log2fcThreshold}
                onChange={(value) => setLog2fcThreshold(Math.max(0, value))}
              />
              <SelectField
                label="Motif Window Proteome"
                value={organism}
                options={KSEA_ORGANISM_VALUES}
                labels={KSEA_ORGANISM_LABELS}
                onChange={(value) => setOrganism(value as KseaOrganism)}
              />
              <SelectField
                label="Test Type"
                value={testType}
                options={sourceMode === "volcano_control" ? CONTROL_TEST_TYPE_OPTIONS.map(({ value }) => value) : TEST_TYPE_VALUES}
                labels={sourceMode === "volcano_control" ? Object.fromEntries(CONTROL_TEST_TYPE_OPTIONS.map(({ value, label }) => [value, label])) : TEST_TYPE_LABELS}
                onChange={(value) => setTestType(value as StatsTestType)}
              />
            </div>
            {testType === "paired" ? (
              <PairingEditor
                kind="phospho"
                condition1={condition1}
                condition2={condition2}
                samplesByCondition={options?.samplesByCondition ?? {}}
                pairIdsBySample={options?.pairIdsBySample ?? {}}
                onSaved={async () => setOptions(await getPhosphoOptions())}
              />
            ) : null}
            <div className="flex flex-wrap gap-3">
              <CheckboxField
                label="Use Uncorrected P-values"
                checked={useUncorrected}
                onChange={setUseUncorrected}
              />
            </div>
            {!validSelection ? (
              <InfoNotice
                message={
                  sourceMode === "volcano_control"
                    ? "Please select four different conditions and controls to generate the table."
                    : "Please select two different conditions to generate the table."
                }
              />
            ) : tableLoading || tableRequest !== debouncedTableRequest ? (
              <NeutralNotice message="Loading Kinase Library input table..." />
            ) : tableError ? (
              <ErrorNotice message={tableError} />
            ) : (
              <>
                {tsvDownload ? (
                  <div className="flex flex-wrap items-center gap-2">
                  <a
                    href={tsvDownload}
                    download={`KinaseLibrary_${kseaComparisonLabel}.tsv`}
                    className="inline-flex rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    Download Kinase Library Table (TSV)
                  </a>
                  <NotebookDownload outputLabel="table" plotUrl={JSON.stringify({ revision, ...tableRequest })}
                    rendered={tableResult ? { url: tableResult.requestKey, token: tableResult.token } : null} />
                  </div>
                ) : null}
                {tableRows.length > 0 && peptideWindowCount > 0 ? (
                  <InfoNotice
                    message={
                      organism === "none"
                        ? "Motif windows are cut from the peptide sequence only; flanks the peptide does not cover are padded with \"_\", which the Kinase Library reads as the protein end."
                        : `${peptideWindowCount} of ${tableRows.length} motif windows could not be read from the ${KSEA_ORGANISM_LABELS[organism]} proteome and use the peptide sequence only (window_source = peptide).`
                    }
                  />
                ) : null}
                <PreviewTable rows={tableRows} emptyText="No rows available for the current selection." />
              </>
            )}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Instructions</h3>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-slate-700">
          <li>
            {sourceMode === "volcano_control"
              ? "Select Condition 1/2 plus both controls (four different conditions) and download the prepared Kinase Library table (TSV)."
              : "Select two conditions and download the prepared Kinase Library table (TSV)."}
          </li>
          <li>Open <a className="text-sky-700 underline" href="https://kinase-library.phosphosite.org/kinase-library/fisher-enrichment-analysis" target="_blank" rel="noreferrer">PhosphoSitePlus Kinase Library</a>.</li>
          <li>Go to <strong>Fisher Enrichment Analysis</strong> and upload the downloaded table.</li>
          <li>Set columns as in the original workflow:
            <div>Motif column: <code>UPD_seq</code> (15-residue window centred on the site, read from the selected proteome)</div>
            <div>log2FC column: <code>log2FC</code></div>
            <div>p-value column (optional): <code>pval</code> or <code>adj_pval</code></div>
          </li>
          <li>Run analysis for Serine/Threonine and again for Tyrosine/non-canonical kinases.</li>
          <li>Download both result files and upload them below to generate the Kinase Library volcano.</li>
        </ol>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Kinase Library Volcano From Uploaded Results</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <FileField
            label="Serine/Threonine Result File"
            onFile={(file) => setFileSt(file)}
            helpText={fileSt ? fileSt.name : "Upload .csv, .tsv, or .txt"}
          />
          <FileField
            label="Tyrosine/Non-canonical Result File"
            onFile={(file) => setFileTnc(file)}
            helpText={fileTnc ? fileTnc.name : "Upload .csv, .tsv, or .txt"}
          />
          <NumberField
            label="Kinase Library Volcano P-value Threshold"
            value={volcanoPValueThreshold}
            onChange={(value) => setVolcanoPValueThreshold(Math.max(1e-12, Math.min(1, value)))}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <CheckboxField label="Annotate Hits" checked={annotateHits} onChange={setAnnotateHits} />
        </div>
        {!validSelection ? (
          <div className="mt-4">
            <InfoNotice
              message={
                sourceMode === "volcano_control"
                  ? "Please select four different conditions and controls to generate the plot."
                  : "Please select two different conditions to generate the plot."
              }
            />
          </div>
        ) : null}
        <div className="mt-4">
          <button
            type="button"
            onClick={generateVolcano}
            disabled={volcanoLoading || !fileSt || !fileTnc || !validSelection}
            className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {volcanoLoading ? "Generating..." : "Generate Kinase Library Volcano"}
          </button>
        </div>
        {volcanoError ? (
          <div className="mt-4">
            <ErrorNotice message={volcanoError} />
          </div>
        ) : null}
      </section>

      {advancedPlotOptions}

      {volcanoHtml ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Kinase Library Volcano</h3>
          <div className="mt-4">
            <iframe
              sandbox="allow-scripts allow-downloads"
              srcDoc={volcanoHtml}
              title="Kinase Library Volcano"
              className="h-[40rem] w-full rounded-xl border border-slate-200"
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}


function FileField({
  label,
  onFile,
  helpText,
}: {
  label: string;
  onFile: (file: File | null) => void;
  helpText: string;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <AssistantInput
        type="file"
        accept=".csv,.tsv,.txt"
        onChange={(event) => onFile(event.currentTarget.files?.[0] ?? null)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1 file:text-slate-700 hover:file:bg-slate-200"
      />
      <span className="mt-1 block text-xs text-slate-500">{helpText}</span>
    </label>
  );
}

function InfoNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
      {message}
    </div>
  );
}

function NeutralNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
      {message}
    </div>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  if (!rows || rows.length === 0) return <NeutralNotice message={emptyText} />;
  return <PaginatedTable rows={rows} pageSize={50} emptyText={emptyText} maxHeightClassName="max-h-[28rem]" />;
}

function rowsToDelimited(rows: Record<string, unknown>[], columns: string[], delimiter: string) {
  const header = columns.join(delimiter);
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const raw = row[column];
        const text = raw == null ? "" : String(raw);
        if (text.includes(delimiter) || text.includes('"') || text.includes("\n")) {
          return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
      })
      .join(delimiter)
  );
  return [header, ...body].join("\n");
}

function toFilenameToken(value: string) {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "NA";
  return normalized
    .replace(/[<>:"/\\|?*]+/g, "_")
    .replace(/\s+/g, "_");
}
