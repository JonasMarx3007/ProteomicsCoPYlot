// GO enrichment (ORA) panel.

import { SizeRow } from "../../components/PlotFields";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { coercePlotDownloadFormat, type PlotDownloadFormat } from "../../lib/plotDownload";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import PairingEditor from "../../components/PairingEditor";
import { oraExportRows } from "./oraExport";
import { buildPlotUrl, getStatisticalOptions, getOraNotebookTables, isAbortError, pairingIsReady, runAnovaAnalysis, runEnrichmentAnalysis } from "../../lib/api";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import { fetchPlot } from "../../lib/fetchPlot";
import { useDatasetRevision } from "../../lib/datasetAvailability";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { ContextMode, AnnotationKind, AnovaRequest, AnovaResultResponse, AnovaClusterMethod, EnrichmentOrganism, EnrichmentRequest, EnrichmentResultResponse, StatsTestType, DataSource, StatisticalOptionsResponse } from "../../lib/types";
import { dataSourceOptions, ENRICHMENT_ORGANISM_OPTIONS } from "../../lib/types";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import { TEST_TYPE_OPTIONS, restoreTestType, CONTROL_TEST_TYPE_OPTIONS, controlTestType } from "../../lib/statisticalTests";
import SelectField from "../../components/SelectField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { keepCondition, useStatisticalOptionsLoader } from "./useStatisticalOptions";
import { ImageSection, InfoSection, Notice, SummarySection, TableSection, ConditionPicker } from "./statsShared";
import { ANOVA_CLUSTER_METHOD_OPTIONS, conditionOptions, hasGeneNameSupport, isPairedTestType, restoreClusterCount, restoreClusterMethod, restorePValueThreshold, sanitizeFilenamePart } from "./statsHelpers";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

function useOraNotebook(kind: AnnotationKind, direction: string, plotUrl: string, tableOnly: boolean) {
  const [rendered, setRendered] = useState<RenderedNotebook | null>(null);
  const [captured, setCaptured] = useState<{ url: string; token: string; data: EnrichmentResultResponse } | null>(null);
  const [error, setError] = useState<{ url: string; message: string } | null>(null);
  useEffect(() => {
    if (!tableOnly || !plotUrl) return;
    const controller = new AbortController();
    fetchPlot(`${plotUrl}&tableOnly=true`, controller.signal).then(async response => {
      if (!response.ok) throw new Error("Could not prepare the ORA notebook.");
      await response.arrayBuffer();
      const token = response.headers.get("X-CoPYlot-Notebook") ?? "";
      if (!controller.signal.aborted) setRendered({ url: plotUrl, token: /^[A-Za-z0-9_-]{32}$/.test(token) ? token : null });
    }).catch(cause => {
      if (!controller.signal.aborted && !isAbortError(cause)) {
        setError({ url: plotUrl, message: cause instanceof Error ? cause.message : "Failed to capture ORA" });
      }
    });
    return () => controller.abort();
  }, [plotUrl, tableOnly]);
  useEffect(() => {
    if (rendered?.url !== plotUrl || !rendered.token) return;
    const controller = new AbortController();
    const token = rendered.token;
    getOraNotebookTables(kind, direction, token, controller.signal).then(data => {
      if (!controller.signal.aborted) setCaptured({ url: plotUrl, token, data });
    }).catch(cause => {
      if (!controller.signal.aborted && !isAbortError(cause)) {
        setError({ url: plotUrl, message: cause instanceof Error ? cause.message : "Failed to load ORA snapshot" });
      }
    });
    return () => controller.abort();
  }, [kind, direction, plotUrl, rendered]);
  const current = captured?.url === plotUrl && captured.token === rendered?.token ? captured : null;
  return { rendered, notebook: current ? rendered : null, data: current?.data,
    error: error?.url === plotUrl ? error.message : null,
    onRendered: (url: string, token: string | null) => setRendered({ url, token }) };
}

function GeneListSection({ title, genes, filename, plotUrl, notebook }: {
  title: string; genes: string[]; filename: string; plotUrl?: string; notebook?: RenderedNotebook | null;
}) {
  const href = `data:text/plain;charset=utf-8,${encodeURIComponent(genes.join("\n"))}`;
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <div className="flex flex-wrap items-center gap-2"><a href={href} download={filename} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Download TXT
        </a>{plotUrl ? <NotebookDownload plotUrl={plotUrl} rendered={notebook ?? null} /> : null}</div>
      </div>
      <div className="max-h-60 overflow-auto rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        {genes.length ? genes.join(", ") : "No genes available."}
      </div>
    </section>
  );
}

export function OraPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: ContextMode | null) => void;
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
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const [condition1Control, setCondition1Control] = useState(() => String(persisted.condition1Control ?? ""));
  const [condition2Control, setCondition2Control] = useState(() => String(persisted.condition2Control ?? ""));
  const [selectedTestType, setTestType] = useState<StatsTestType>(() => {
    return restoreTestType(persisted.testType);
  });
  const testType = sourceMode === "volcano_control" ? controlTestType(selectedTestType) : selectedTestType;
  const [pValueThreshold, setPValueThreshold] = useState(() =>
    restorePValueThreshold(persisted.pValueThreshold)
  );
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [nClusters, setNClusters] = useState(() => restoreClusterCount(persisted.nClusters));
  const [clusterMethod, setClusterMethod] = useState<AnovaClusterMethod>(() =>
    restoreClusterMethod(persisted.clusterMethod)
  );
  const [selectedCluster, setSelectedCluster] = useState(() => String(persisted.selectedCluster ?? ""));
  const [adjPValueCutoff, setAdjPValueCutoff] = useState(() => Number(persisted.adjPValueCutoff ?? 0.05));
  const [topN, setTopN] = useState(() => Number(persisted.topN ?? 10));
  const [minTermSize, setMinTermSize] = useState(() => Number(persisted.minTermSize ?? 20));
  const [maxTermSize, setMaxTermSize] = useState(() => Number(persisted.maxTermSize ?? 300));
  const [backgroundMode, setBackgroundMode] = useState<"experiment" | "global">(() =>
    String(persisted.backgroundMode ?? "experiment") === "global" ? "global" : "experiment"
  );
  // One organism today. It is a request parameter rather than a constant so the
  // result says which database produced it, and so a second organism is a list
  // entry rather than a new code path.
  const [organism, setOrganism] = useState<EnrichmentOrganism>(() =>
    ENRICHMENT_ORGANISM_OPTIONS.some((option) => option.value === persisted.organism)
      ? (persisted.organism as EnrichmentOrganism)
      : "human"
  );
  // The figures have their own size, because the terms decide how much room
  // they need and a GO description is as long as it is. Width and height are a
  // floor rather than a fixed canvas: the renderer grows past them when the
  // labels do not fit, so a figure never comes back as an error message.
  const [widthCm, setWidthCm] = useState(() => restorePlotDimensionCm(persisted.widthCm, 26));
  const [heightCm, setHeightCm] = useState(() => restorePlotDimensionCm(persisted.heightCm, 12));
  const [dpi, setDpi] = useState(() => restorePlotDpi(persisted.dpi, 300));
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );
  const [anovaState, setAnovaState] = useState<{ key: string; data: AnovaResultResponse } | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: EnrichmentResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The request, once; the cache key is derived from it, so a field sent to
  // the backend cannot be missing from the key a result is stored and found
  // under (frontend/tests/component/result-keys.test.tsx).
  const requestPayload = useMemo<EnrichmentRequest>(() => ({
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
    nClusters: Math.max(1, Math.round(nClusters)),
    clusterMethod,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
    organism,
  }), [
    kind, sourceMode, dataSource, condition1, condition2, condition1Control, condition2Control,
    pValueThreshold, log2fcThreshold, testType, useUncorrected, selectedCluster, nClusters,
    clusterMethod, adjPValueCutoff, topN, minTermSize, maxTermSize, backgroundMode, organism,
  ]);
  const currentResultKey = JSON.stringify({ revision, ...requestPayload });
  const result = resultState?.key === currentResultKey ? resultState.data : null;

  const kindAvailable = oraKindOptions.some((option) => option.value === kind);
  const oraDataSourceOptions = useMemo(
    // `options`, not `options?.availableDataSources`: the React Compiler infers
    // the whole object as the dependency and refuses to keep a narrower manual
    // one, which fails the lint gate.
    () => dataSourceOptions(options),
    [options]
  );

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
    },
    setError,
  );


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
      // Must match what the ANOVA page clustered with, or the cluster
      // numbers the user picks between refer to a different partition.
      clusterMethod,
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
    // ORA must run against the partition the ANOVA page drew.
    clusterMethod,
  ]);
  const debouncedAnovaRequest = useDebouncedValue(anovaRequest, 650);
  const anovaKey = JSON.stringify({ revision, request: anovaRequest });
  const anovaResult = sourceMode === "anova" && anovaState?.key === anovaKey ? anovaState.data : null;
  const anovaClusterSizes = new Map<string, number>();
  for (const row of anovaResult?.clusterRows ?? []) {
    if (row.cluster !== null && row.cluster !== undefined && String(row.cluster).trim()) {
      const cluster = String(row.cluster);
      anovaClusterSizes.set(cluster, (anovaClusterSizes.get(cluster) ?? 0) + 1);
    }
  }
  const availableAnovaClusters = Array.from(anovaClusterSizes.keys()).sort((a, b) => Number(a) - Number(b));
  const anovaClusterOptions = [
    { value: "", label: availableAnovaClusters.length ? "Select a cluster" : "No clusters available" },
    ...availableAnovaClusters.map((cluster) => ({
      value: cluster,
      label: `Cluster ${cluster} (n=${anovaClusterSizes.get(cluster) ?? 0})`,
    })),
  ];

  useEffect(() => {
    if (sourceMode !== "anova" || !debouncedAnovaRequest) return;
    const controller = new AbortController();
    runAnovaAnalysis(debouncedAnovaRequest, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setAnovaState({ key: JSON.stringify({ revision, request: debouncedAnovaRequest }), data: response });
        setError(null);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setAnovaState(null);
        setError(err instanceof Error ? err.message : "Failed to generate ANOVA clusters");
      });
    return () => {
      controller.abort();
    };
  }, [debouncedAnovaRequest, sourceMode, revision]);

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
    const mode: ContextMode = {
      source: sourceMode,
      kind: kind,
      dataSource: dataSource,
      condition1: condition1,
      condition2: condition2,
      condition1Control: condition1Control,
      condition2Control: condition2Control,
      testType: testType,
      pValueThreshold: pValueThreshold,
      log2fcThreshold: log2fcThreshold,
      useUncorrected: useUncorrected,
      selectedCluster: selectedCluster || "none",
      nClusters: roundedClusterCount,
      clusterMethod: clusterMethod,
      adjPValueCutoff: adjPValueCutoff,
      topN: topN,
      minTermSize: minTermSize,
      maxTermSize: maxTermSize,
      backgroundMode: backgroundMode,
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
    testType,
    pValueThreshold,
    log2fcThreshold,
    useUncorrected,
    selectedCluster,
    roundedClusterCount,
    // ORA must run against the partition the ANOVA page drew.
    clusterMethod,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
    organism,
  ]);

  useEffect(() => {
    if (!geneNamesAvailable || !canRun) return;

    const controller = new AbortController();

    runEnrichmentAnalysis(requestPayload, { signal: controller.signal })
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
  }, [canRun, geneNamesAvailable, requestPayload, currentResultKey]);

  const commonPlotParams = {
    organism,
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
    clusterMethod,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
    widthCm,
    heightCm,
    dpi,
  };
  const upPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/ora/up.png`, commonPlotParams);
  const downPlotUrl = buildPlotUrl(`/api/plots/stats/${kind}/ora/down.png`, commonPlotParams);
  // The direction belongs in the name as well as in the title: two files called
  // ora_protein.png in a downloads folder are not worth having.
  const plotFileSuffix = [kind, sanitizeFilenamePart(condition1), "vs", sanitizeFilenamePart(condition2)]
    .filter(Boolean)
    .join("_");
  const upPlotFilename = `ora_up_${plotFileSuffix}.png`;
  const downPlotFilename = `ora_down_${plotFileSuffix}.png`;
  const clusterPlotUrl =
    sourceMode === "anova" && selectedCluster
      ? buildPlotUrl(`/api/plots/stats/${kind}/ora/cluster.png`, {
          ...commonPlotParams,
          selectedCluster: Number(selectedCluster),
        })
      : null;

  const upNotebook = useOraNotebook(kind, "up", upPlotUrl, Boolean(canRun && result && sourceMode !== "anova" && !result.upTerms.length));
  const downNotebook = useOraNotebook(kind, "down", downPlotUrl, Boolean(canRun && result && sourceMode !== "anova" && !result.downTerms.length));
  const clusterNotebook = useOraNotebook(kind, "cluster", clusterPlotUrl ?? "", Boolean(canRun && result && sourceMode === "anova" && !result.clusterTerms.length));
  const upResult = upNotebook.data ?? result;
  const downResult = downNotebook.data ?? result;
  const clusterResult = clusterNotebook.data ?? result;

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
      clusterMethod,
      adjPValueCutoff,
      topN,
      minTermSize,
      maxTermSize,
      backgroundMode,
      organism,
      widthCm,
      heightCm,
      dpi,
      downloadFormat,
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
    clusterMethod,
    adjPValueCutoff,
    topN,
    minTermSize,
    maxTermSize,
    backgroundMode,
    organism,
    widthCm,
    heightCm,
    dpi,
    downloadFormat,
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
          <LocalizationCutoffField kind={kind} />
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
                  onChange={(value) => chooseDataSource(value as DataSource)}
                  options={oraDataSourceOptions}
                />
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
                <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
                <NumberField label="Clusters" value={nClusters} onChange={(value) => setNClusters(Math.max(1, Math.round(value)))} />
                <SelectField
                  label="Cluster method"
                  value={clusterMethod}
                  onChange={(value) => setClusterMethod(value as AnovaClusterMethod)}
                  options={ANOVA_CLUSTER_METHOD_OPTIONS}
                />
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
                  onChange={(value) => chooseDataSource(value as DataSource)}
                  options={oraDataSourceOptions}
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
            <SelectField
              label="Organism"
              value={organism}
              onChange={(value) => setOrganism(value as EnrichmentOrganism)}
              options={ENRICHMENT_ORGANISM_OPTIONS}
            />
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
        <div className="mt-6 border-t border-slate-200 pt-6">
          <h4 className="text-sm font-semibold text-slate-900">Figure Size</h4>
          <div className="mt-3 grid gap-4 lg:grid-cols-3">
            <SizeRow
              widthCm={widthCm}
              heightCm={heightCm}
              dpi={dpi}
              onWidthChange={setWidthCm}
              onHeightChange={setHeightCm}
              onDpiChange={setDpi}
            />
          </div>
          <p className="mt-3 text-xs text-slate-600">
            Width and height are a minimum, not a fixed canvas. A Gene Ontology description can be longer
            than any sensible figure is wide, so the plot is enlarged as far as the term labels need and the
            labels are wrapped to the width available. The size set here applies on screen and to the
            download alike.
          </p>
        </div>
        <Notice error={error} warnings={options?.warnings} />
      </SectionCard>
      {advancedPlotOptions}
      <Notice error={upNotebook.error ?? downNotebook.error ?? clusterNotebook.error} />
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
              <ImageSection
                title={`ANOVA Cluster ${result.selectedCluster ?? selectedCluster} Terms`}
                url={clusterPlotUrl}
                notebook={clusterNotebook.rendered}
                onRendered={clusterNotebook.onRendered}
                download={{
                  filename: `ora_anova_cluster_${result.selectedCluster ?? selectedCluster}_${kind}.png`,
                  format: downloadFormat,
                  onFormatChange: setDownloadFormat,
                }}
              />
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
              genes={clusterResult?.clusterGenes ?? result.clusterGenes}
              plotUrl={clusterPlotUrl ?? undefined} notebook={clusterNotebook.notebook}
              filename={`ora_anova_cluster_${result.selectedCluster ?? selectedCluster}_${kind}.txt`}
            />
            {result.backgroundMode === "experiment" ? (
              <GeneListSection
                title="Tested-gene Background"
                genes={clusterResult?.backgroundGenes ?? result.backgroundGenes}
                plotUrl={clusterPlotUrl ?? undefined} notebook={clusterNotebook.notebook}
                filename={`ora_background_${kind}.txt`}
              />
            ) : null}
            <TableSection
              title={`ANOVA Cluster ${result.selectedCluster ?? selectedCluster} Terms`}
              plotUrl={clusterPlotUrl ?? undefined} notebook={clusterNotebook.notebook}
              rows={oraExportRows(clusterResult?.clusterTerms ?? result.clusterTerms, clusterResult ?? result, {
                analysisSource: sourceMode,
                selectedCluster: result.selectedCluster ?? selectedCluster,
                pValueThreshold,
                useUncorrected,
                nClusters: roundedClusterCount,
                clusterMethod,
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
            {/* One above the other rather than side by side: a term label is a
                sentence, and half the window is not enough width for it. */}
            <div className="space-y-6">
              {result.upGenes.length > 0 && result.upTerms.length > 0 ? (
                <ImageSection
                  title={condition1 ? `Upregulated Terms in ${condition1}` : "Upregulated Terms"}
                  url={upPlotUrl}
                  notebook={upNotebook.rendered}
                  onRendered={upNotebook.onRendered}
                  download={{
                    filename: upPlotFilename,
                    format: downloadFormat,
                    onFormatChange: setDownloadFormat,
                  }}
                />
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
                <ImageSection
                  title={condition1 ? `Downregulated Terms in ${condition1}` : "Downregulated Terms"}
                  url={downPlotUrl}
                  notebook={downNotebook.rendered}
                  onRendered={downNotebook.onRendered}
                  download={{
                    filename: downPlotFilename,
                    format: downloadFormat,
                    onFormatChange: setDownloadFormat,
                  }}
                />
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
            <GeneListSection title="Upregulated Genes" genes={upResult?.upGenes ?? result.upGenes} filename={`ora_up_${kind}.txt`}
              plotUrl={upPlotUrl} notebook={upNotebook.notebook} />
            <GeneListSection title="Downregulated Genes" genes={downResult?.downGenes ?? result.downGenes} filename={`ora_down_${kind}.txt`}
              plotUrl={downPlotUrl} notebook={downNotebook.notebook} />
            {result.backgroundMode === "experiment" ? (
              <GeneListSection title="Tested-gene Background" genes={upResult?.backgroundGenes ?? result.backgroundGenes} filename={`ora_background_${kind}.txt`}
                plotUrl={upPlotUrl} notebook={upNotebook.notebook} />
            ) : null}
            <TableSection
              title="Upregulated Terms"
              plotUrl={upPlotUrl} notebook={upNotebook.notebook}
              rows={oraExportRows(upResult?.upTerms ?? result.upTerms, upResult ?? result, {
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
              plotUrl={downPlotUrl} notebook={downNotebook.notebook}
              rows={oraExportRows(downResult?.downTerms ?? result.downTerms, downResult ?? result, {
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
