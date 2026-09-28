// Pathway heatmap panel.

import { SizeRow } from "../../components/PlotFields";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { AssistantSelect } from "../../components/AssistantFields";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getPathwayOptions, getStatisticalOptions, isAbortError } from "../../lib/api";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { ContextMode, AnnotationKind, PathwayOptionsResponse, StatisticalOptionsResponse, DataSource } from "../../lib/types";
import { dataSourceOptions } from "../../lib/types";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import SelectField from "../../components/SelectField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import { ImageSection, InfoSection, Notice } from "./statsShared";
import { conditionOptions, hasGeneNameSupport } from "./statsHelpers";

function MultiSelect({ values, onChange, options }: { values: string[]; onChange: (value: string[]) => void; options: { value: string; label: string }[] }) {
  return (
    <AssistantSelect
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
    </AssistantSelect>
  );
}

export function PathwayHeatmapPanel({
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
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const [includeId, setIncludeId] = useState(() => Boolean(persisted.includeId ?? false));
  const [header, setHeader] = useState(() => Boolean(persisted.header ?? true));
  const [removeEmpty, setRemoveEmpty] = useState(() => Boolean(persisted.removeEmpty ?? true));
  // How many dataset rows collapsed onto each gene. Off by default: on a
  // pathway of forty genes it is forty parentheticals down the side.
  const [showSourceCount, setShowSourceCount] = useState(() =>
    Boolean(persisted.showSourceCount ?? false)
  );
  const [clusterRows, setClusterRows] = useState(() => Boolean(persisted.clusterRows ?? false));
  const [clusterCols, setClusterCols] = useState(() => Boolean(persisted.clusterCols ?? false));
  const [widthCm, setWidthCm] = useState(() => restorePlotDimensionCm(persisted.widthCm, 20));
  const [heightCm, setHeightCm] = useState(() => restorePlotDimensionCm(persisted.heightCm, 12));
  const [dpi, setDpi] = useState(() => restorePlotDpi(persisted.dpi, 300));
  const [error, setError] = useState<string | null>(null);
  const geneNamesAvailable = hasGeneNameSupport(options);
  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const pathwayDataSourceOptions = useMemo(() => dataSourceOptions(options), [options]);

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        // Unconditionally: this used to apply the choices only when imputed was
        // *un*available, which is backwards -- the panel then never left the
        // placeholder on exactly the projects that have an imputed matrix.
        applyDataSourceChoices(data);
        setSelectedConditions((current) => (current.length ? current.filter((item) => data.availableConditions.includes(item)) : data.availableConditions));
      })
      .catch((err) => {
        if (!isAbortError(err)) {
          setError(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, kindAvailable, applyDataSourceChoices]);

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
    const mode: ContextMode = {
      kind: kind,
      pathway: pathway,
      conditions: selectedConditions,
      valueType: valueType,
      dataSource: dataSource,
      removeEmpty: removeEmpty,
      showSourceCount: showSourceCount,
      includeId: includeId,
      header: header,
      clusterRows: clusterRows,
      clusterCols: clusterCols,
    };
    onContextModeChange(mode);
  }, [
    onContextModeChange,
    kind,
    pathway,
    selectedConditions,
    valueType,
    dataSource,
    removeEmpty,
    showSourceCount,
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
    showSourceCount,
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
      showSourceCount,
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
    showSourceCount,
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
          <SelectField
            label="Value type"
            value={valueType}
            onChange={(value) => setValueType(value as "log2" | "z")}
            // The wire values stay "z"/"log2"; only the wording changes. The
            // matrix is log2 either way, so "log2" named the scale rather than
            // what the cell shows, which is an intensity.
            options={[{ value: "z", label: "Z-score" }, { value: "log2", label: "Intensity" }]}
          />
          <SelectField
            label="Data source"
            value={dataSource}
            onChange={(value) => chooseDataSource(value as DataSource)}
            options={pathwayDataSourceOptions}
          />
        </div>
        <div className="mt-4">
          <label htmlFor="pathway-conditions" className="mb-2 block text-sm font-medium text-slate-700">Conditions</label>
          <MultiSelect values={selectedConditions} onChange={setSelectedConditions} options={conditionOptions(options)} />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <SizeRow
            widthCm={widthCm}
            heightCm={heightCm}
            dpi={dpi}
            onWidthChange={setWidthCm}
            onHeightChange={setHeightCm}
            onDpiChange={setDpi}
          />
        </div>
        <div className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <CheckboxField label="Show gene labels" checked={header} onChange={setHeader} />
            <CheckboxField label="Toggle ID" checked={includeId} onChange={setIncludeId} />
            <CheckboxField label="Remove empty genes" checked={removeEmpty} onChange={setRemoveEmpty} />
            <CheckboxField label="Show collapsed row count (n)" checked={showSourceCount} onChange={setShowSourceCount} />
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
