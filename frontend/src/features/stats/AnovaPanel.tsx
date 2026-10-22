// One-way ANOVA panel: omnibus test, Tukey follow-up and clustering of significant rows.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, isAbortError, runAnovaAnalysis } from "../../lib/api";
import { useDatasetRevision } from "../../lib/datasetAvailability";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { ContextMode, AnnotationKind, AnovaRequest, AnovaResultResponse, AnovaClusterMethod, AnovaPostHoc, AnovaSource, StatsIdentifier, DataSource, StatisticalOptionsResponse } from "../../lib/types";
import { dataSourceOptions } from "../../lib/types";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import SelectField from "../../components/SelectField";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { keepIdentifier, useStatisticalOptionsLoader } from "./useStatisticalOptions";
import { InfoSection, Notice, SummarySection } from "./statsShared";
import AnovaOutput from "./AnovaOutput";
import { ANOVA_CLUSTER_METHOD_OPTIONS, conditionOptions, removeSourceUsageWarnings, restoreClusterCount, restoreClusterMethod, restorePValueThreshold } from "./statsHelpers";

export function AnovaPanel({
  kindOptions,
  onContextModeChange,
  advancedPlotOptions,
}: {
  kindOptions: { value: string; label: string }[];
  onContextModeChange?: (mode: ContextMode | null) => void;
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
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const [identifier, setIdentifier] = useState<StatsIdentifier>(() => {
    const value = String(persisted.identifier ?? "workflow").trim();
    return value === "genes" ? "genes" : "workflow";
  });
  const [pValueThreshold, setPValueThreshold] = useState(() =>
    restorePValueThreshold(persisted.pValueThreshold)
  );
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [showDendrograms, setShowDendrograms] = useState(() => Boolean(persisted.showDendrograms ?? true));
  // Feature names beside the rows of the cluster heatmaps. Their size and
  // colour are in the plot appearance panel, shown while this is on.
  const [showRowLabels, setShowRowLabels] = useState(() => Boolean(persisted.showRowLabels ?? false));
    // Shown or hidden from the advanced panel's Legend card, like every other plot.
  const showLegend = true;
  const [nClusters, setNClusters] = useState(() => restoreClusterCount(persisted.nClusters));
  const [clusterMethod, setClusterMethod] = useState<AnovaClusterMethod>(() =>
    restoreClusterMethod(persisted.clusterMethod)
  );
  const [selectedCluster, setSelectedCluster] = useState(() => String(persisted.selectedCluster ?? "none"));
  const [postHoc, setPostHoc] = useState<AnovaPostHoc>(() =>
    String(persisted.postHoc ?? "none").trim() === "tukey" ? "tukey" : "none"
  );
  // Which pair the post-hoc reports. One comparison costs one studentized-range
  // integral per significant feature, so naming the pair is the difference
  // between ~8 s and ~25 s -- and the numbers are identical, because k and the
  // pooled MSE come from the whole design either way.
  const [postHocCondition1, setPostHocCondition1] = useState(() =>
    String(persisted.postHocCondition1 ?? "")
  );
  const [postHocCondition2, setPostHocCondition2] = useState(() =>
    String(persisted.postHocCondition2 ?? "")
  );
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: AnovaResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const canRun = Boolean(kindAvailable && options && options.availableConditions.length >= 2);
  const postHocAvailable = (options?.availableConditions.length ?? 0) >= 3;
  const postHocPairValid = Boolean(
    postHocCondition1 && postHocCondition2 && postHocCondition1 !== postHocCondition2
  );
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
      clusterMethod,
      postHoc,
      ...(postHoc === "tukey" && postHocPairValid
        ? { postHocCondition1, postHocCondition2 }
        : {}),
    };
  }, [canRun, kind, sourceMode, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showLegend, nClusters, clusterMethod, postHoc, postHocPairValid, postHocCondition1, postHocCondition2]);

  // Derived from `requestPayload`, never written out a second time. When these
  // were two separate object literals the post-hoc pair was in the request and
  // not in the key, so a Tukey result could never match the key it was stored
  // under: `result` stayed null, `running` stayed true, and the panel showed
  // "still working" forever over a response that had already arrived.
  const currentResultKey = requestPayload
    ? JSON.stringify({ revision, ...requestPayload })
    : null;
  const result =
    currentResultKey !== null && resultState?.key === currentResultKey
      ? resultState.data
      : null;

  const anovaDataSourceOptions = useMemo(
    // `options`, not `options?.availableDataSources`: the React Compiler infers
    // the whole object as the dependency and refuses to keep a narrower manual
    // one, which fails the lint gate.
    () => dataSourceOptions(options),
    [options]
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

  useStatisticalOptionsLoader(
    kind,
    kindAvailable,
    (data) => {
      setOptions(data);
      applyDataSourceChoices(data);
      setIdentifier(keepIdentifier(data));
      setPostHocCondition1((current) =>
        data.availableConditions.includes(current) ? current : data.availableConditions[0] ?? ""
      );
      setPostHocCondition2((current) =>
        data.availableConditions.includes(current) && current !== data.availableConditions[0]
          ? current
          : data.availableConditions[1] ?? ""
      );
    },
    setError,
  );


  // Changing a setting invalidates the result, so the plot and tables vanish
  // while the new one is computed. Tukey HSD on a large matrix takes tens of
  // seconds -- studentized_range.sf is evaluated once per comparison -- and an
  // empty panel for that long reads as "nothing happened" rather than
  // "working". Derived rather than stored, so it needs no setState inside an
  // effect and it turns on the moment the settings change.
  const running = Boolean(requestPayload) && !result && !error;

  useEffect(() => {
    if (!onContextModeChange) return;
    const mode: ContextMode = {
      source: sourceMode,
      kind: kind,
      dataSource: dataSource,
      identifier: identifier,
      pValueThreshold: pValueThreshold,
      useUncorrected: useUncorrected,
      showDendrograms: showDendrograms,
      showLegend: showLegend,
      showRowLabels: sourceMode === "anova_cluster" && showRowLabels,
      selectedCluster: displayedSelectedCluster,
      nClusters: Math.max(1, Math.round(nClusters)),
      clusterMethod: clusterMethod,
      postHoc: postHoc,
    };
    onContextModeChange(mode);
  }, [onContextModeChange, sourceMode, kind, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showLegend, showRowLabels, displayedSelectedCluster, nClusters, clusterMethod, postHoc]);

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
        setError(err instanceof Error ? err.message : "Failed to run One-way ANOVA analysis");
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
    ...(sourceMode === "anova_cluster" ? { showRowLabels } : {}),
    nClusters: Math.max(1, Math.round(nClusters)),
    clusterMethod,
    postHoc,
    ...(postHoc === "tukey" && postHocPairValid ? { postHocCondition1, postHocCondition2 } : {}),
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
          showRowLabels,
          nClusters: Math.max(1, Math.round(nClusters)),
          clusterMethod,
          selectedCluster: displayedSelectedCluster,
          postHoc,
          ...(postHoc === "tukey" && postHocPairValid ? { postHocCondition1, postHocCondition2 } : {}),
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
      showRowLabels,
      selectedCluster,
      nClusters,
      clusterMethod,
      postHoc,
      postHocCondition1,
      postHocCondition2,
    });
  }, [kind, sourceMode, dataSource, identifier, pValueThreshold, useUncorrected, showDendrograms, showRowLabels, showLegend, selectedCluster, nClusters, clusterMethod, postHoc, postHocCondition1, postHocCondition2]);

  return (
    <div className="space-y-6">
      <SectionCard title="One-way ANOVA">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
          <LocalizationCutoffField kind={kind} />
        </div>
      </SectionCard>

      <SectionCard title="Options">
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField
            label="Source"
            value={sourceMode}
            onChange={(value) => setSourceMode(value as AnovaSource)}
            options={[
              { value: "anova", label: "One-way ANOVA" },
              { value: "anova_cluster", label: "One-way ANOVA — clusters" },
            ]}
          />
          <SelectField
            label="Data Source"
            value={dataSource}
            onChange={(value) => chooseDataSource(value as DataSource)}
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
        </div>
        {sourceMode === "anova_cluster" ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <NumberField label="Clusters" value={nClusters} onChange={(value) => setNClusters(Math.max(1, Math.round(value)))} />
            <SelectField
              label="Cluster method"
              value={clusterMethod}
              onChange={(value) => setClusterMethod(value as AnovaClusterMethod)}
              options={ANOVA_CLUSTER_METHOD_OPTIONS}
            />
            <SelectField label="Cluster" value={displayedSelectedCluster} onChange={setSelectedCluster} options={clusterOptions} />
            <CheckboxField label="Show feature names" checked={showRowLabels} onChange={setShowRowLabels} />
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

      {postHoc === "tukey" ? (
        <SectionCard title="Post-hoc Comparison">
          {postHocAvailable ? (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <SelectField
                  label="Condition 1"
                  value={postHocCondition1}
                  onChange={setPostHocCondition1}
                  options={conditionOptions(options)}
                />
                <SelectField
                  label="Condition 2"
                  value={postHocCondition2}
                  onChange={setPostHocCondition2}
                  options={conditionOptions(options)}
                />
              </div>
              {!postHocPairValid ? (
                <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  Select two different conditions to run the post-hoc.
                </div>
              ) : null}
            </>
          ) : (
            <InfoSection message="A post-hoc needs at least three conditions. With two, the One-way ANOVA and the single pairwise comparison test the same hypothesis." />
          )}
        </SectionCard>
      ) : null}

      {advancedPlotOptions}
      {!canRun && options ? <InfoSection message="At least two conditions with replicate samples are required to run One-way ANOVA." /> : null}
      {running && !result ? (
        <InfoSection
          message={
            postHoc === "tukey"
              ? "Running the One-way ANOVA and the Tukey HSD post-hoc. The post-hoc evaluates one studentized-range probability per comparison, so on a large matrix it can take a minute; the plot and tables reappear when it finishes."
              : "Running the One-way ANOVA..."
          }
        />
      ) : null}
      {debouncedRequestPayload && result ? (
        <>
          <SummarySection
            items={[
              { label: "Rows", value: String(result.totalRows) },
              { label: "Significant", value: String(result.significantCount) },
              { label: "Source", value: result.source === "anova_cluster" ? "One-way ANOVA — clusters" : "One-way ANOVA" },
              { label: "Clusters", value: result.clusterCount == null ? "-" : String(result.clusterCount) },
              {
                label: "Cluster sizes",
                value: availableClusters.length
                  ? availableClusters.map((cluster) => `${cluster}: ${clusterSizes.get(cluster) ?? 0}`).join(", ")
                  : "-",
              },
            ]}
          />
          <AnovaOutput key={plotUrl} result={result} plotUrl={plotUrl} />
          {selectedClusterPlotUrl ? (
            <AnovaOutput key={selectedClusterPlotUrl} result={result} plotUrl={selectedClusterPlotUrl}
              selectedCluster={displayedSelectedCluster} />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
