// Replicate & variance projection: the volcano recomputed under a chosen
// variance factor and replicate count.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, isAbortError, runSimulationAnalysis } from "../../lib/api";
import { useDatasetRevision } from "../../lib/datasetAvailability";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { ContextMode, AnnotationKind, SimulationRequest, SimulationResultResponse, SimulationTestType, StatsIdentifier, DataSource, StatisticalOptionsResponse } from "../../lib/types";
import { PROTEIN_CORRECTION_LABEL, useProteinCorrection } from "../../lib/proteinCorrection";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import { SIMULATION_TEST_TYPE_OPTIONS } from "../../lib/statisticalTests";
import SelectField from "../../components/SelectField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { keepCondition, keepIdentifier, useStatisticalOptionsLoader } from "./useStatisticalOptions";
import { InfoSection, Notice, PlotFrame, SummarySection, ConditionPicker } from "./statsShared";
import { conditionOptions, removeSourceUsageWarnings, restorePValueThreshold } from "./statsHelpers";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

function restoreSimulationTestType(value: unknown): SimulationTestType {
  return value === "unpaired_welch" ? "unpaired_welch" : "unpaired";
}

function restoreSimulationSampleSize(value: unknown): number {
  const parsed = Number(value ?? 0);
  // 0 means "use the observed sample sizes"; anything the field cannot hold --
  // including 1, which no t-test can work with -- falls back to it.
  if (Number.isInteger(parsed) && (parsed === 0 || (parsed >= 2 && parsed <= 100))) return parsed;
  return 0;
}

function validateSimulationSampleSize(value: number): string | null {
  if (!Number.isInteger(value)) return "Replicates per group must be a whole number.";
  if (value === 1) {
    return "Use 0 for the observed replicate counts or a value from 2 to 100; a t-test cannot estimate variance from one replicate.";
  }
  if (value < 0 || value > 100) return "Replicates per group must be 0 or a whole number from 2 to 100.";
  return null;
}

function formatEffectiveSampleSize(minimum: number, maximum: number): string {
  return minimum === maximum ? String(minimum) : `${minimum}-${maximum}`;
}

export function SimulationPanel({
  kindOptions,
  advancedPlotOptions,
  onContextModeChange,
}: {
  kindOptions: { value: string; label: string }[];
  advancedPlotOptions?: ReactNode;
  onContextModeChange?: (mode: ContextMode | null) => void;
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
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
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
  const [pValueThreshold, setPValueThreshold] = useState(() =>
    restorePValueThreshold(persisted.pValueThreshold)
  );
  const [log2fcThreshold, setLog2fcThreshold] = useState(() => Number(persisted.log2fcThreshold ?? 1));
  const [useUncorrected, setUseUncorrected] = useState(() => Boolean(persisted.useUncorrected ?? false));
  const [varianceMultiplier, setVarianceMultiplier] = useState(() => Number(persisted.varianceMultiplier ?? 1));
  const [sampleSizeOverride, setSampleSizeOverride] = useState(
    () => restoreSimulationSampleSize(persisted.sampleSizeOverride)
  );
  const [sampleSizeInputError, setSampleSizeInputError] = useState<string | null>(null);
  const [resultState, setResultState] = useState<{
    key: string;
    data: SimulationResultResponse;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const proteinCorrection = useProteinCorrection(
    kind, options, persisted.proteinCorrection, dataSource, chooseDataSource);
  const simulationDataSourceOptions = proteinCorrection.dataSourceOptions;

  useStatisticalOptionsLoader(
    kind,
    kindAvailable,
    (data) => {
      setOptions(data);
      applyDataSourceChoices(data);
      setCondition1(keepCondition(data.availableConditions));
      setCondition2(keepCondition(data.availableConditions));
      setIdentifier(keepIdentifier(data));
    },
    setError,
  );


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
      proteinCorrection: proteinCorrection.active,
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
    proteinCorrection.active,
    varianceMultiplier,
    sampleSizeOverride,
  ]);
  useEffect(() => {
    onContextModeChange?.(requestPayload ?? { kind, status: "incomplete_parameters" });
  }, [onContextModeChange, requestPayload, kind]);
  // Derived from `requestPayload`: one description of the request, so a field
  // can never be in the request and missing from the key it is stored under.
  const currentResultKey = requestPayload
    ? JSON.stringify({ revision, ...requestPayload })
    : null;
  const result =
    currentResultKey !== null && resultState?.key === currentResultKey
      ? resultState.data
      : null;
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
    // Also a recompute trigger rather than a value: buildPlotUrl reads the
    // dataset-scope nonce, so a new revision has to rebuild this URL.
    void revision;
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
      proteinCorrection: Boolean(debouncedRequestPayload.proteinCorrection),
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
      proteinCorrection: proteinCorrection.enabled,
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
    proteinCorrection.enabled,
    varianceMultiplier,
    sampleSizeOverride,
  ]);

  return (
    <div className="space-y-6">
      <SectionCard title="Replicate & Variance Projection">
        <div className="max-w-xs">
          <SelectField label="Dataset level" value={kind} onChange={(value) => setKind(value as AnnotationKind)} options={kindOptions} />
          <LocalizationCutoffField kind={kind} />
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
            onChange={(value) => chooseDataSource(value as DataSource)}
            options={simulationDataSourceOptions}
          />
        </div>
        <ConditionPicker
          conditions={conditionOptions(options)}
          condition1={{ value: condition1, onChange: setCondition1 }}
          condition2={{ value: condition2, onChange: setCondition2 }}
        />
        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <SelectField label="Label column" value={identifier} onChange={(value) => setIdentifier(value as StatsIdentifier)} options={(options?.availableIdentifiers ?? []).map((item) => ({ value: item.key, label: item.label }))} />
          <SelectField label="Test type" value={testType} onChange={(value) => setTestType(value as SimulationTestType)} options={SIMULATION_TEST_TYPE_OPTIONS} />
          <NumberField label="P-value threshold" value={pValueThreshold} onChange={setPValueThreshold} step={0.001} />
          <NumberField label="log2 FC threshold" value={log2fcThreshold} onChange={setLog2fcThreshold} step={0.1} />
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <CheckboxField label="Use uncorrected p-values" checked={useUncorrected} onChange={setUseUncorrected} />
          {proteinCorrection.offered ? (
            <CheckboxField
              label={PROTEIN_CORRECTION_LABEL}
              checked={proteinCorrection.enabled}
              onChange={proteinCorrection.setEnabled}
            />
          ) : null}
        </div>

        <div className="mt-6 border-t border-slate-200 pt-6">
          <h4 className="text-sm font-semibold text-slate-900">Projection settings</h4>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <NumberField label="Variance × factor" value={varianceMultiplier} onChange={(value) => setVarianceMultiplier(Math.max(0.01, value))} step={0.05} />
            <NumberField
              label="Replicates per group (0 = observed, 2-100 fixed)"
              value={sampleSizeOverride}
              onChange={setSampleSizeOverride}
              validate={validateSimulationSampleSize}
              onValidationError={setSampleSizeInputError}
            />
          </div>
        </div>
        <Notice
          error={sampleSizeInputError ?? error}
          warnings={removeSourceUsageWarnings(options?.warnings)}
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
            { label: "No p-value", value: String(result.unavailableCount ?? 0) },
          ]} />
          <PlotFrame title="Projected volcano plot" url={plotUrl} height={760} />
          <Notice error={null} warnings={removeSourceUsageWarnings(result.warnings)} />
        </>
      ) : null}
    </div>
  );
}
