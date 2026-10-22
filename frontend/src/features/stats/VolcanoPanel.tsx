// Volcano panel: ordinary, paired and control-adjusted comparisons.

import { SizeRow } from "../../components/PlotFields";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { coercePlotDownloadFormat, type PlotDownloadFormat } from "../../lib/plotDownload";
import { AssistantTextarea } from "../../components/AssistantFields";
import { useId, useEffect, useMemo, useState, type ReactNode } from "react";
import PairingEditor from "../../components/PairingEditor";
import { buildPlotUrl, getStatisticalOptions, getVolcanoNotebookTable, isAbortError, pairingIsReady, runVolcanoAnalysis, runVolcanoControlAnalysis } from "../../lib/api";
import type { RenderedNotebook } from "../../components/NotebookDownload";
import { useDatasetRevision } from "../../lib/datasetAvailability";
import { addVolcanoReportEntry, listVolcanoReportEntries, removeVolcanoReportEntry } from "../../lib/reportState";
import { IS_VIEWER_MODE } from "../../lib/appMode";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { ContextMode, AnnotationKind, StatsIdentifier, StatsTestType, VolcanoResultResponse, SummaryVolcanoEntry, DataSource, VolcanoRenderType, StatisticalOptionsResponse } from "../../lib/types";
import { VOLCANO_RENDER_TYPE_OPTIONS } from "../../lib/types";
import { PROTEIN_CORRECTION_LABEL, useProteinCorrection } from "../../lib/proteinCorrection";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import { restoreTestType, CONTROL_TEST_TYPE_OPTIONS, controlTestType, useTestTypeOptions, availableTestType } from "../../lib/statisticalTests";
import SelectField from "../../components/SelectField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { keepCondition, keepIdentifier, useStatisticalOptionsLoader } from "./useStatisticalOptions";
import { ImageSection, InfoSection, Notice, PlotFrame, SummarySection, TableSection, ConditionPicker } from "./statsShared";
import { conditionOptions, isPairedTestType, removeSourceUsageWarnings, restorePValueThreshold, sanitizeFilenamePart } from "./statsHelpers";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

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
      <AssistantTextarea id={fieldId} data-assistant-permission="view"
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

function volcanoExportFilename(
  sourceMode: "volcano" | "volcano_control",
  kind: string,
  condition1: string,
  condition2: string
): string {
  const prefix = sourceMode === "volcano_control" ? "volcano_control" : "volcano";
  const first = sanitizeFilenamePart(condition1);
  const second = sanitizeFilenamePart(condition2);
  if (!first || !second) return `${prefix}_${kind}.csv`;
  return `${prefix}_${kind}_${first}_vs_${second}.csv`;
}

export function VolcanoPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: ContextMode | null) => void;
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
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
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
  const { options: testTypeOptions, moderatedAvailable } = useTestTypeOptions();
  const testType = sourceMode === "volcano_control"
    ? controlTestType(selectedTestType)
    : availableTestType(selectedTestType, moderatedAvailable);
  const [pValueThreshold, setPValueThreshold] = useState(() =>
    restorePValueThreshold(persisted.pValueThreshold)
  );
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [highlightText, setHighlightText] = useState(() => String(persisted.highlightText ?? ""));
  // What the highlight terms draw: a ring (default) and/or, on the static
  // figure, a text label placed like the top hits.
  const [highlightOutline, setHighlightOutline] = useState(() => persisted.highlightOutline !== false);
  const [highlightLabels, setHighlightLabels] = useState(() => Boolean(persisted.highlightLabels ?? false));
  // Interactive by default, because this panel is for exploring and the hover
  // text is how you find out which point you are looking at. Normal is the
  // figure you take away.
  const [renderType, setRenderType] = useState<VolcanoRenderType>(() =>
    String(persisted.renderType ?? "Interactive").trim() === "Normal" ? "Normal" : "Interactive"
  );
  const [labelTopUp, setLabelTopUp] = useState(() => Number(persisted.labelTopUp ?? 0));
  const [labelTopDown, setLabelTopDown] = useState(() => Number(persisted.labelTopDown ?? 0));
  // Size and export belong to the static figure only. The interactive plot
  // fills its frame and exports itself through Plotly's camera button, so
  // neither is offered -- nor sent -- while it is selected.
  const [widthCm, setWidthCm] = useState(() => restorePlotDimensionCm(persisted.widthCm, 18));
  const [heightCm, setHeightCm] = useState(() => restorePlotDimensionCm(persisted.heightCm, 14));
  const [dpi, setDpi] = useState(() => restorePlotDpi(persisted.dpi, 300));
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );
  const [error, setError] = useState<string | null>(null);
  const [renderedNotebook, setRenderedNotebook] = useState<RenderedNotebook | null>(null);
  const [notebookTable, setNotebookTable] = useState<{ url: string; token: string; data: VolcanoResultResponse } | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: VolcanoResultResponse;
  } | null>(null);
  const [reportLogMessage, setReportLogMessage] = useState<string | null>(null);
  const [reportLogVersion, setReportLogVersion] = useState(0);

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const proteinCorrection = useProteinCorrection(
    kind, options, persisted.proteinCorrection, dataSource, chooseDataSource);
  const volcanoDataSourceOptions = proteinCorrection.dataSourceOptions;

  useStatisticalOptionsLoader(
    kind,
    kindAvailable,
    (data) => {
      setOptions(data);
      applyDataSourceChoices(data);
      setCondition1(keepCondition(data.availableConditions));
      setCondition2(keepCondition(data.availableConditions));
      setCondition1Control(keepCondition(data.availableConditions));
      setCondition2Control(keepCondition(data.availableConditions));
      setIdentifier(keepIdentifier(data));
    },
    setError,
  );


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
      proteinCorrection: proteinCorrection.active,
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
    proteinCorrection.active,
    highlightTerms,
  ]);

  useEffect(() => {
    if (!onContextModeChange) return;
    const mode: ContextMode = {
      source: sourceMode,
      kind: kind,
      dataSource: dataSource,
      condition1: condition1,
      condition2: condition2,
      condition1Control: condition1Control,
      condition2Control: condition2Control,
      identifier: identifier,
      testType: testType,
      pValueThreshold: pValueThreshold,
      log2fcThreshold: log2fcThreshold,
      useUncorrected: useUncorrected,
      proteinCorrection: proteinCorrection.active,
      type: renderType,
    };
    onContextModeChange(mode);
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
    proteinCorrection.active,
    renderType,
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
      proteinCorrection: proteinCorrection.active,
      highlightTerms,
      // Captured at the moment it is added, so two comparisons in one report
      // can render differently -- the panel's current state is the intent.
      renderType,
      labelTopUp,
      labelTopDown,
      highlightOutline,
      highlightLabels,
    }),
    [
      renderType,
      labelTopUp,
      labelTopDown,
      highlightOutline,
      highlightLabels,
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
      proteinCorrection.active,
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
      proteinCorrection: proteinCorrection.enabled,
      highlightText,
      highlightOutline,
      highlightLabels,
      renderType,
      labelTopUp,
      labelTopDown,
      widthCm,
      heightCm,
      dpi,
      downloadFormat,
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
    proteinCorrection.enabled,
    highlightText,
    highlightOutline,
    highlightLabels,
    renderType,
    labelTopUp,
    labelTopDown,
    widthCm,
    heightCm,
    dpi,
    downloadFormat,
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
              proteinCorrection: debouncedRequestPayload.proteinCorrection,
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
              proteinCorrection: debouncedRequestPayload.proteinCorrection,
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
    // Also a recompute trigger rather than a value: buildPlotUrl reads the
    // dataset-scope nonce, so a new revision has to rebuild this URL.
    void revision;
    if (!debouncedRequestPayload) return "";
    const isStatic = renderType === "Normal";
    const extension = isStatic ? "png" : "html";
    // The label counts only mean something to the static renderer; the
    // interactive one names a point when you hover it.
    const shared = {
      condition1: debouncedRequestPayload.condition1,
      condition2: debouncedRequestPayload.condition2,
      dataSource: debouncedRequestPayload.dataSource,
      identifier: debouncedRequestPayload.identifier,
      pValueThreshold: debouncedRequestPayload.pValueThreshold,
      log2fcThreshold: debouncedRequestPayload.log2fcThreshold,
      testType: debouncedRequestPayload.testType,
      useUncorrected: debouncedRequestPayload.useUncorrected,
      proteinCorrection: debouncedRequestPayload.proteinCorrection,
      highlightTerms: debouncedRequestPayload.highlightTerms.join(","),
      highlightOutline,
      ...(isStatic ? { labelTopUp, labelTopDown, highlightLabels, widthCm, heightCm, dpi } : {}),
    };
    if (debouncedRequestPayload.source === "volcano_control") {
      return buildPlotUrl(
        `/api/plots/stats/${debouncedRequestPayload.kind}/volcano-control.${extension}`,
        {
          ...shared,
          condition1Control: debouncedRequestPayload.condition1Control,
          condition2Control: debouncedRequestPayload.condition2Control,
        }
      );
    }
    return buildPlotUrl(
      `/api/plots/stats/${debouncedRequestPayload.kind}/volcano.${extension}`,
      shared
    );
  }, [
    debouncedRequestPayload,
    advancedPlotSignal,
    revision,
    renderType,
    labelTopUp,
    labelTopDown,
    highlightOutline,
    highlightLabels,
    widthCm,
    heightCm,
    dpi,
  ]);

  useEffect(() => {
    if (renderedNotebook?.url !== plotUrl || !renderedNotebook.token) return;
    const controller = new AbortController();
    const token = renderedNotebook.token;
    getVolcanoNotebookTable(kind, token, controller.signal).then(data => {
      if (!controller.signal.aborted) setNotebookTable({ url: plotUrl, token, data });
    }).catch(cause => {
      if (!controller.signal.aborted && !isAbortError(cause)) {
        setError(cause instanceof Error ? cause.message : "Failed to load the captured volcano table");
      }
    });
    return () => controller.abort();
  }, [kind, plotUrl, renderedNotebook]);
  const capturedTable = notebookTable?.url === plotUrl
    && notebookTable.token === renderedNotebook?.token ? notebookTable : null;
  const displayedResult = capturedTable?.data ?? result;

  return (
    <div className="space-y-6">
      <SectionCard title="Volcano Plot">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
          <LocalizationCutoffField kind={kind} />
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
            onChange={(value) => chooseDataSource(value as DataSource)}
            options={volcanoDataSourceOptions}
          />
        </div>
        <ConditionPicker
          conditions={conditionOptions(options)}
          condition1={{ value: condition1, onChange: setCondition1 }}
          condition2={{ value: condition2, onChange: setCondition2 }}
          controls={sourceMode === "volcano_control" ? {
            condition1: { value: condition1Control, onChange: setCondition1Control },
            condition2: { value: condition2Control, onChange: setCondition2Control },
          } : undefined}
        />

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <SelectField
            label="Type"
            value={renderType}
            onChange={(value) => setRenderType(value as VolcanoRenderType)}
            options={VOLCANO_RENDER_TYPE_OPTIONS}
          />
          <SelectField label="Label column" value={identifier} onChange={(value) => setIdentifier(value as StatsIdentifier)} options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))} />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as StatsTestType)} options={sourceMode === "volcano_control" ? CONTROL_TEST_TYPE_OPTIONS : testTypeOptions} />
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
            {proteinCorrection.offered ? (
              <CheckboxField
                label={PROTEIN_CORRECTION_LABEL}
                checked={proteinCorrection.enabled}
                onChange={proteinCorrection.setEnabled}
              />
            ) : null}
          </div>
        </div>

        {renderType === "Normal" ? (
          <div className="mt-4">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <NumberField
                label="Label top up-regulated"
                value={labelTopUp}
                onChange={(value) => setLabelTopUp(Math.max(0, Math.round(value)))}
                step={1}
              />
              <NumberField
                label="Label top down-regulated"
                value={labelTopDown}
                onChange={(value) => setLabelTopDown(Math.max(0, Math.round(value)))}
                step={1}
              />
            </div>
            <p className="mt-2 text-sm text-slate-600">
              Ranked by significance. A label that cannot be placed without
              covering another one is left off rather than drawn over it.
            </p>
          </div>
        ) : null}

        <div className="mt-4 max-w-3xl" data-assistant-appearance="true">
          <TextareaField label="Highlight terms" value={highlightText} onChange={setHighlightText} rows={3} placeholder="Space-separated labels to highlight" />
          {highlightTerms.length ? (
            <div className="mt-2 grid gap-4 sm:grid-cols-2">
              <CheckboxField label="Outline highlighted points" checked={highlightOutline} onChange={setHighlightOutline} />
              {renderType === "Normal" ? (
                <CheckboxField label="Label highlighted points (static plot)" checked={highlightLabels} onChange={setHighlightLabels} />
              ) : null}
            </div>
          ) : null}
        </div>
        {renderType === "Normal" ? (
          <div className="mt-4 max-w-3xl">
            <SizeRow
              widthCm={widthCm}
              heightCm={heightCm}
              dpi={dpi}
              onWidthChange={setWidthCm}
              onHeightChange={setHeightCm}
              onDpiChange={setDpi}
            />
          </div>
        ) : null}

        {sourceMode === "volcano" && !IS_VIEWER_MODE && kind === "phosprot" ? (
          // The report has no phosphoprotein section (it covers protein and
          // phospho); rather than accept an entry it would then drop in
          // silence, the panel says so and offers nothing to click.
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
            Phosphoprotein volcano plots cannot be added to the report.
          </div>
        ) : null}
        {sourceMode === "volcano" && !IS_VIEWER_MODE && kind !== "phosprot" ? (
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
                Saved entries for {kindOptions.find((option) => option.value === kind)?.label ?? kind}: {reportEntryCount}
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
      {canRun && result && displayedResult ? (
        <>
          <SummarySection items={[{ label: "Rows", value: String(displayedResult.totalRows) }, { label: "Upregulated", value: String(displayedResult.upregulatedCount) }, { label: "Downregulated", value: String(displayedResult.downregulatedCount) }, { label: "Not Significant", value: String(displayedResult.notSignificantCount) }, { label: "No p-value", value: String(displayedResult.unavailableCount ?? 0) }]} />
          {renderType === "Normal" ? (
            <ImageSection
              title="Volcano Plot"
              url={plotUrl}
              notebook={renderedNotebook}
              onRendered={(url, token) => setRenderedNotebook({ url, token })}
              download={{
                filename: volcanoExportFilename(sourceMode, kind, condition1, condition2).replace(/\.csv$/, ".png"),
                format: downloadFormat,
                onFormatChange: setDownloadFormat,
              }}
            />
          ) : (
            <PlotFrame title="Volcano Plot" url={plotUrl} height={760} notebook={renderedNotebook}
              onRendered={(url, token) => setRenderedNotebook({ url, token })} />
          )}
          <Notice error={null} warnings={removeSourceUsageWarnings(Array.from(new Set([...(displayedResult.warnings ?? []), ...(result.warnings ?? [])])))} />
          <TableSection
            title="Result Table"
            rows={displayedResult.rows}
            plotUrl={plotUrl}
            notebook={capturedTable ? { url: capturedTable.url, token: capturedTable.token } : null}
            filename={volcanoExportFilename(sourceMode, kind, condition1, condition2)}
          />
          {result.untestedRows && result.untestedRows.length > 0 ? (
            <TableSection
              title="Rows not tested"
              rows={result.untestedRows}
              filename={volcanoExportFilename(sourceMode, kind, condition1, condition2).replace(/\.csv$/, "_not_tested.csv")}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
