import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getPeptideQuantityOptions, getQcPcaFeatures, getQcPlotOptions, getQcTable, isAbortError } from "../../lib/api";
import { clampPlotDimensionCm, clampPlotDpi } from "../../lib/plotLimits";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { saveQcReportSettings } from "../../lib/reportState";
import {
  readPersistedSessionUiState,
  readPersistedUiState,
  writePersistedSessionUiState,
  writePersistedUiState,
} from "../../lib/persistedUiState";
import { getAdvancedPlotMode } from "../../lib/appSettings";
import { IS_VIEWER_MODE } from "../../lib/appMode";
import AdvancedPlotOptions, {
  type AdvancedPlotControlDefaults,
  type AdvancedPlotVisibleControls,
} from "../../components/plots/AdvancedPlotOptions";
import type {
  AdvancedPlotSettings,
  AnnotationKind,
  QcPcaFeatureSummary,
  QcTab,
} from "../../lib/types";

type Props = {
  activeTab: QcTab;
  onWorkflowScopeChange?: (workflow: string) => void;
  onBoxplotModeChange?: (mode: string) => void;
  onPcaContextModeChange?: (mode: string) => void;
};

type QcTableRequest = {
  tab: "coverage" | "boxplot" | "cv";
  params?: Record<string, string | number | boolean>;
};

type QcKind = AnnotationKind | "peptide";
type AdvancedPlotState = Partial<Record<QcTab, AdvancedPlotSettings>>;

function isAnnotationKind(kind: QcKind): kind is AnnotationKind {
  return kind === "protein" || kind === "phospho" || kind === "phosprot";
}

function workflowScopeFromKind(kind: QcKind): string {
  if (kind === "phospho") return "phosphosite";
  if (kind === "phosprot") return "phosphoprotein";
  if (kind === "peptide") return "peptide";
  return "protein";
}

function compactMap(value: Record<string, string> | undefined): Record<string, string> | undefined {
  const entries = Object.entries(value ?? {})
    .map(([key, val]) => [key.trim(), val.trim()] as const)
    .filter(([key, val]) => key && val);
  return entries.length ? Object.fromEntries(entries) : undefined;
}

function compactTextElement(value: AdvancedPlotSettings["titleElement"]) {
  if (!value) return undefined;
  const text = value.text?.trim();
  const next = {
    ...(text ? { text } : {}),
    ...(value.size && value.size > 0 ? { size: value.size } : {}),
    ...(value.xOffset ? { xOffset: value.xOffset } : {}),
    ...(value.yOffset ? { yOffset: value.yOffset } : {}),
    ...(value.bold ? { bold: true } : {}),
    ...(value.italic ? { italic: true } : {}),
  };
  return Object.keys(next).length ? next : undefined;
}

function compactAdvancedSettings(settings: AdvancedPlotSettings): AdvancedPlotSettings {
  const next: AdvancedPlotSettings = {};
  const title = settings.title?.trim();
  const xLabel = settings.xLabel?.trim();
  const yLabel = settings.yLabel?.trim();
  const referenceLineColor = settings.referenceLineColor?.trim();
  const boxBorderColor = settings.boxBorderColor?.trim();
  const boxMedianColor = settings.boxMedianColor?.trim();
  const boxOutlierColor = settings.boxOutlierColor?.trim();
  const boxOutlierEdgeColor = settings.boxOutlierEdgeColor?.trim();
  const correlationColorMap = settings.correlationColorMap?.trim();
  const backgroundColor = settings.backgroundColor?.trim();
  const plotTheme = settings.plotTheme?.trim();
  const axisLineColor = settings.axisLineColor?.trim();
  const axisLineStyle = settings.axisLineStyle?.trim();
  const gridLineAxis = settings.gridLineAxis?.trim();
  const gridLineColor = settings.gridLineColor?.trim();
  const gridLineStyle = settings.gridLineStyle?.trim();
  const titleElement = compactTextElement(settings.titleElement);
  const xLabelElement = compactTextElement(settings.xLabelElement);
  const yLabelElement = compactTextElement(settings.yLabelElement);

  if (title) next.title = title;
  if (xLabel) next.xLabel = xLabel;
  if (yLabel) next.yLabel = yLabel;
  if (titleElement) {
    next.titleElement = titleElement;
    if (titleElement.text) next.title = titleElement.text;
    if (titleElement.size) next.titleSize = titleElement.size;
  }
  if (xLabelElement) {
    next.xLabelElement = xLabelElement;
    if (xLabelElement.text) next.xLabel = xLabelElement.text;
  }
  if (yLabelElement) {
    next.yLabelElement = yLabelElement;
    if (yLabelElement.text) next.yLabel = yLabelElement.text;
  }
  if (settings.titleSize && settings.titleSize > 0) next.titleSize = settings.titleSize;
  if (settings.axisLabelSize && settings.axisLabelSize > 0) next.axisLabelSize = settings.axisLabelSize;
  if (settings.tickLabelSize && settings.tickLabelSize > 0) next.tickLabelSize = settings.tickLabelSize;
  if (settings.xTickLabelSize && settings.xTickLabelSize > 0) next.xTickLabelSize = settings.xTickLabelSize;
  if (settings.yTickLabelSize && settings.yTickLabelSize > 0) next.yTickLabelSize = settings.yTickLabelSize;
  if (Number.isFinite(settings.xTickLabelRotation)) next.xTickLabelRotation = settings.xTickLabelRotation;
  if (Number.isFinite(settings.yTickLabelRotation)) next.yTickLabelRotation = settings.yTickLabelRotation;
  if (settings.legendFontSize && settings.legendFontSize > 0) next.legendFontSize = settings.legendFontSize;
  if (settings.legendXOffset) next.legendXOffset = settings.legendXOffset;
  if (settings.legendYOffset) next.legendYOffset = settings.legendYOffset;
  if (referenceLineColor) next.referenceLineColor = referenceLineColor;
  if (boxBorderColor) next.boxBorderColor = boxBorderColor;
  if (boxMedianColor) next.boxMedianColor = boxMedianColor;
  if (boxOutlierColor) next.boxOutlierColor = boxOutlierColor;
  if (boxOutlierEdgeColor) next.boxOutlierEdgeColor = boxOutlierEdgeColor;
  if (settings.boxOutlierSize && settings.boxOutlierSize > 0) next.boxOutlierSize = settings.boxOutlierSize;
  if (correlationColorMap) next.correlationColorMap = correlationColorMap;
  if (backgroundColor) next.backgroundColor = backgroundColor;
  if (typeof settings.transparentBackground === "boolean") next.transparentBackground = settings.transparentBackground;
  if (plotTheme && plotTheme !== "default") next.plotTheme = plotTheme;
  if (typeof settings.axisLineVisible === "boolean") next.axisLineVisible = settings.axisLineVisible;
  if (axisLineColor) next.axisLineColor = axisLineColor;
  if (settings.axisLineWidth && settings.axisLineWidth > 0) next.axisLineWidth = settings.axisLineWidth;
  if (axisLineStyle && axisLineStyle !== "solid") next.axisLineStyle = axisLineStyle;
  if (typeof settings.axisLineTop === "boolean") next.axisLineTop = settings.axisLineTop;
  if (typeof settings.axisLineRight === "boolean") next.axisLineRight = settings.axisLineRight;
  if (typeof settings.axisLineBottom === "boolean") next.axisLineBottom = settings.axisLineBottom;
  if (typeof settings.axisLineLeft === "boolean") next.axisLineLeft = settings.axisLineLeft;
  if (typeof settings.gridLineVisible === "boolean") next.gridLineVisible = settings.gridLineVisible;
  if (gridLineAxis && gridLineAxis !== "y") next.gridLineAxis = gridLineAxis;
  if (gridLineColor) next.gridLineColor = gridLineColor;
  if (settings.gridLineWidth && settings.gridLineWidth > 0) next.gridLineWidth = settings.gridLineWidth;
  if (gridLineStyle && gridLineStyle !== "solid") next.gridLineStyle = gridLineStyle;

  const conditionLabels = compactMap(settings.conditionLabels);
  const sampleLabels = compactMap(settings.sampleLabels);
  const conditionColors = compactMap(settings.conditionColors);
  if (conditionLabels) next.conditionLabels = conditionLabels;
  if (sampleLabels) next.sampleLabels = sampleLabels;
  if (conditionColors) next.conditionColors = conditionColors;

  return next;
}

function advancedParam(settings: AdvancedPlotSettings, enabled: boolean): string | undefined {
  if (!enabled) return undefined;
  const compacted = compactAdvancedSettings(settings);
  return Object.keys(compacted).length ? JSON.stringify(compacted) : undefined;
}

function withAdvancedParams(
  params: Record<string, string | number | boolean>,
  advanced: string | undefined
): Record<string, string | number | boolean> {
  return { ...params, advanced: advanced ?? "" };
}

function withBoxplotStyleParams(
  params: Record<string, string | number | boolean>,
  settings: AdvancedPlotSettings
): Record<string, string | number | boolean> {
  const next = { ...params };
  const boxBorderColor = settings.boxBorderColor?.trim();
  const boxMedianColor = settings.boxMedianColor?.trim();
  const boxOutlierColor = settings.boxOutlierColor?.trim();
  const boxOutlierEdgeColor = settings.boxOutlierEdgeColor?.trim();
  if (boxBorderColor) next.boxBorderColor = boxBorderColor;
  if (boxMedianColor) next.boxMedianColor = boxMedianColor;
  if (boxOutlierColor) next.boxOutlierColor = boxOutlierColor;
  if (boxOutlierEdgeColor) next.boxOutlierEdgeColor = boxOutlierEdgeColor;
  if (settings.boxOutlierSize && settings.boxOutlierSize > 0) {
    next.boxOutlierSize = settings.boxOutlierSize;
  }
  return next;
}

function withCorrelationStyleParams(
  params: Record<string, string | number | boolean>,
  settings: AdvancedPlotSettings
): Record<string, string | number | boolean> {
  const next = { ...params };
  const correlationColorMap = settings.correlationColorMap?.trim();
  if (correlationColorMap) {
    next.correlationColorMap = correlationColorMap;
  }
  return next;
}

export default function QCPipelinePage({
  activeTab,
  onWorkflowScopeChange,
  onBoxplotModeChange,
  onPcaContextModeChange,
}: Props) {
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("qc.pipeline.v1", {}),
    []
  );
  const persistedCoverage = (persisted.coverage as Record<string, unknown>) ?? {};
  const persistedHist = (persisted.hist as Record<string, unknown>) ?? {};
  const persistedBox = (persisted.box as Record<string, unknown>) ?? {};
  const persistedCv = (persisted.cv as Record<string, unknown>) ?? {};
  const persistedPca = (persisted.pca as Record<string, unknown>) ?? {};
  const persistedAbundance = (persisted.abundance as Record<string, unknown>) ?? {};
  const persistedCorrelation = (persisted.correlation as Record<string, unknown>) ?? {};
  const persistedAdvanced = IS_VIEWER_MODE
    ? readPersistedSessionUiState<AdvancedPlotState>("qc.advanced.v1", {})
    : (persisted.advanced as AdvancedPlotState) ?? {};
  const [kind, setKind] = useState<QcKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    if (value === "protein" || value === "phospho" || value === "phosprot" || value === "peptide") return value;
    return "protein";
  });
  const { datasets, availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [imageError, setImageError] = useState<string | null>(null);
  const [conditionOptions, setConditionOptions] = useState<string[]>([]);
  const [sampleOptions, setSampleOptions] = useState<string[]>([]);
  const [sampleDisplayLabels, setSampleDisplayLabels] = useState<Record<string, string>>({});
  const [sampleDisplayLabelsWithId, setSampleDisplayLabelsWithId] = useState<Record<string, string>>({});
  const [imputedAvailable, setImputedAvailable] = useState(false);
  const [peptideQuantityColumns, setPeptideQuantityColumns] = useState<string[]>([]);
  const [peptideQuantityRequiresSelection, setPeptideQuantityRequiresSelection] = useState(false);
  const [peptideQuantityError, setPeptideQuantityError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() => {
    const value = String(persisted.downloadFormat ?? "png").trim();
    return value === "jpg" || value === "webp" || value === "pdf" ? value : "png";
  });
  const [advancedModeEnabled, setAdvancedModeEnabled] = useState(() => getAdvancedPlotMode());
  const [advancedByTab, setAdvancedByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);
  const [advancedRenderByTab, setAdvancedRenderByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);

  const [coverage, setCoverage] = useState({
    quantityColumn: String(persistedCoverage.quantityColumn ?? ""),
    includeId: Boolean(persistedCoverage.includeId ?? false),
    header: Boolean(persistedCoverage.header ?? true),
    legend: Boolean(persistedCoverage.legend ?? true),
    summary: Boolean(persistedCoverage.summary ?? false),
    text: Boolean(persistedCoverage.text ?? false),
    textSize: Number(persistedCoverage.textSize ?? 9),
    randomSeed: Number(persistedCoverage.randomSeed ?? 187),
    widthCm: Number(persistedCoverage.widthCm ?? 20),
    heightCm: Number(persistedCoverage.heightCm ?? 10),
    dpi: Number(persistedCoverage.dpi ?? 300),
  });
  const [hist, setHist] = useState({
    header: Boolean(persistedHist.header ?? true),
    legend: Boolean(persistedHist.legend ?? true),
    widthCm: Number(persistedHist.widthCm ?? 20),
    heightCm: Number(persistedHist.heightCm ?? 10),
    dpi: Number(persistedHist.dpi ?? 300),
  });
  const [box, setBox] = useState({
    mode: String(persistedBox.mode ?? "Mean"),
    outliers: Boolean(persistedBox.outliers ?? false),
    includeId: Boolean(persistedBox.includeId ?? false),
    header: Boolean(persistedBox.header ?? true),
    legend: Boolean(persistedBox.legend ?? true),
    text: Boolean(persistedBox.text ?? false),
    textSize: Number(persistedBox.textSize ?? 9),
    widthCm: Number(persistedBox.widthCm ?? 20),
    heightCm: Number(persistedBox.heightCm ?? 10),
    dpi: Number(persistedBox.dpi ?? 300),
  });
  const [cv, setCv] = useState({
    outliers: Boolean(persistedCv.outliers ?? false),
    header: Boolean(persistedCv.header ?? true),
    legend: Boolean(persistedCv.legend ?? true),
    text: Boolean(persistedCv.text ?? false),
    textSize: Number(persistedCv.textSize ?? 9),
    widthCm: Number(persistedCv.widthCm ?? 20),
    heightCm: Number(persistedCv.heightCm ?? 10),
    dpi: Number(persistedCv.dpi ?? 300),
  });
  const [pca, setPca] = useState({
    dataSource: String(persistedPca.dataSource ?? "data") === "imputed" ? "imputed" : "data",
    type: String(persistedPca.type ?? "Normal"),
    header: Boolean(persistedPca.header ?? true),
    legend: Boolean(persistedPca.legend ?? true),
    method: String(persistedPca.method ?? "PCA"),
    scaling: String(persistedPca.scaling ?? "auto"),
    plotDim: String(persistedPca.plotDim ?? "2D"),
    addEllipses: Boolean(persistedPca.addEllipses ?? false),
    dotSize: Number(persistedPca.dotSize ?? 5),
    clusterMethod: String(persistedPca.clusterMethod ?? "None"),
    clusterCount: Number(persistedPca.clusterCount ?? 3),
    colorBy: String(persistedPca.colorBy ?? "Condition"),
    umapNNeighbors: Number(persistedPca.umapNNeighbors ?? 15),
    umapMinDist: Number(persistedPca.umapMinDist ?? 0.1),
    tsnePerplexity: Number(persistedPca.tsnePerplexity ?? 30),
    tsneLearningRate: Number(persistedPca.tsneLearningRate ?? 200),
    dbscanEps: Number(persistedPca.dbscanEps ?? 0.5),
    dbscanMinSamples: Number(persistedPca.dbscanMinSamples ?? 2),
    randomState: Number(persistedPca.randomState ?? 42),
    widthCm: Number(persistedPca.widthCm ?? 20),
    heightCm: Number(persistedPca.heightCm ?? 10),
    dpi: Number(persistedPca.dpi ?? 300),
  });
  const [abundance, setAbundance] = useState({
    type: String(persistedAbundance.type ?? "Normal"),
    header: Boolean(persistedAbundance.header ?? true),
    legend: Boolean(persistedAbundance.legend ?? true),
    condition: String(persistedAbundance.condition ?? "All Conditions"),
    widthCm: Number(persistedAbundance.widthCm ?? 20),
    heightCm: Number(persistedAbundance.heightCm ?? 10),
    dpi: Number(persistedAbundance.dpi ?? 300),
  });
  const [correlation, setCorrelation] = useState({
    method: String(persistedCorrelation.method ?? "Matrix"),
    includeId: Boolean(persistedCorrelation.includeId ?? false),
    fullRange: Boolean(persistedCorrelation.fullRange ?? false),
    widthCm: Number(persistedCorrelation.widthCm ?? 20),
    heightCm: Number(persistedCorrelation.heightCm ?? 16),
    dpi: Number(persistedCorrelation.dpi ?? 400),
  });

  useEffect(() => {
    const nextState: Record<string, unknown> = {
      kind,
      downloadFormat,
      coverage,
      hist,
      box,
      cv,
      pca,
      abundance,
      correlation,
    };
    if (!IS_VIEWER_MODE) {
      nextState.advanced = advancedByTab;
    } else {
      writePersistedSessionUiState("qc.advanced.v1", advancedByTab);
    }
    writePersistedUiState("qc.pipeline.v1", nextState);
  }, [kind, downloadFormat, coverage, hist, box, cv, pca, abundance, correlation, advancedByTab]);

  useEffect(() => {
    const refresh = () => setAdvancedModeEnabled(getAdvancedPlotMode());
    window.addEventListener("focus", refresh);
    window.addEventListener("storage", refresh);
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("storage", refresh);
      window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
    };
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setAdvancedRenderByTab(advancedByTab);
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [advancedByTab]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) return;
    saveQcReportSettings(kind, {
      coverage,
      hist,
      box,
      cv,
      pca,
      abundance,
      correlation,
    });
  }, [kind, availableKinds, coverage, hist, box, cv, pca, abundance, correlation]);

  const activeKindOptions = useMemo<Array<{ value: QcKind; label: string }>>(() => {
    if (activeTab !== "coverage") return kindOptions;
    const options: Array<{ value: QcKind; label: string }> = [...kindOptions];
    if (datasets?.peptide) {
      options.push({ value: "peptide", label: "Peptide" });
    }
    return options;
  }, [activeTab, kindOptions, datasets]);

  useEffect(() => {
    if (activeKindOptions.length === 0) {
      setConditionOptions([]);
      return;
    }
    if (!activeKindOptions.some((option) => option.value === kind)) {
      setKind(activeKindOptions[0].value);
    }
  }, [activeKindOptions, kind]);

  useEffect(() => {
    if (kind !== "peptide" || !datasets?.peptide) {
      setPeptideQuantityColumns([]);
      setPeptideQuantityRequiresSelection(false);
      setPeptideQuantityError(null);
      return;
    }
    const controller = new AbortController();
    getPeptideQuantityOptions({ signal: controller.signal })
      .then((payload) => {
        setPeptideQuantityColumns(payload.columns);
        setPeptideQuantityRequiresSelection(payload.requiresSelection);
        setPeptideQuantityError(
          payload.columns.length === 0
            ? "No supported peptide abundance column was found in this dataset."
            : null
        );
        setCoverage((current) => {
          if (current.quantityColumn && payload.columns.includes(current.quantityColumn)) return current;
          return { ...current, quantityColumn: payload.defaultColumn ?? "" };
        });
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setPeptideQuantityColumns([]);
        setPeptideQuantityRequiresSelection(false);
        setPeptideQuantityError(
          error instanceof Error ? error.message : "Failed to load peptide abundance columns"
        );
      });
    return () => controller.abort();
  }, [kind, datasets?.peptide]);

  useEffect(() => {
    if (!onWorkflowScopeChange) return;
    if (activeKindOptions.length === 0) {
      onWorkflowScopeChange("");
      return;
    }
    onWorkflowScopeChange(workflowScopeFromKind(kind));
  }, [activeKindOptions, kind, onWorkflowScopeChange]);

  useEffect(() => {
    if (!onBoxplotModeChange) return;
    if (activeTab !== "boxplot") {
      onBoxplotModeChange("");
      return;
    }
    onBoxplotModeChange(String(box.mode || "").trim());
  }, [activeTab, box.mode, onBoxplotModeChange]);

  useEffect(() => {
    if (!onPcaContextModeChange) return;
    if (activeTab !== "pca") {
      onPcaContextModeChange("");
      return;
    }
    const method = String(pca.method || "").trim();
    const plotDim = String(pca.plotDim || "").trim();
    const type = String(pca.type || "").trim();
    const parts = [
      `method=${method || "PCA"}`,
      `plotDim=${plotDim || "2D"}`,
      `type=${type || "Normal"}`,
      `dataSource=${pca.dataSource}`,
    ];
    onPcaContextModeChange(parts.join("|"));
  }, [activeTab, pca.dataSource, pca.method, pca.plotDim, pca.type, onPcaContextModeChange]);

  const [pcaFeatures, setPcaFeatures] = useState<QcPcaFeatureSummary | null>(null);

  // Dimensionality reduction drops any feature with a missing value, so the
  // projection can rest on a small, abundance-biased subset. Surface that.
  useEffect(() => {
    if (activeTab !== "pca" || !isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setPcaFeatures(null);
      return;
    }
    const controller = new AbortController();
    getQcPcaFeatures(kind, pca.dataSource, pca.plotDim, { signal: controller.signal })
      .then((payload) => {
        setPcaFeatures(payload);
      })
      .catch((error) => {
        if (!isAbortError(error)) setPcaFeatures(null);
      });
    return () => {
      controller.abort();
    };
  }, [activeTab, kind, availableKinds, pca.dataSource, pca.plotDim]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setConditionOptions([]);
      setSampleOptions([]);
      setSampleDisplayLabels({});
      setSampleDisplayLabelsWithId({});
      setImputedAvailable(false);
      return;
    }
    const controller = new AbortController();
    getQcPlotOptions(kind, { signal: controller.signal })
      .then((payload) => {
        const unique = Array.from(new Set(payload.conditions.map((value) => value.trim()).filter(Boolean)));
        setConditionOptions(unique);
        const samples = Array.from(new Set((payload.samples ?? []).map((value) => value.trim()).filter(Boolean)));
        setSampleOptions(samples);
        setSampleDisplayLabels(payload.sampleLabels ?? {});
        setSampleDisplayLabelsWithId(payload.sampleLabelsWithId ?? {});
        setImputedAvailable(payload.imputedAvailable);
        if (!payload.imputedAvailable) {
          setPca((current) =>
            current.dataSource === "data" ? current : { ...current, dataSource: "data" }
          );
        }
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setConditionOptions([]);
        setSampleOptions([]);
        setSampleDisplayLabels({});
        setSampleDisplayLabelsWithId({});
        setImputedAvailable(false);
      });
    return () => {
      controller.abort();
    };
  }, [kind, availableKinds]);

  useEffect(() => {
    setAbundance((prev) => {
      if (prev.condition === "All Conditions") return prev;
      if (conditionOptions.includes(prev.condition)) return prev;
      return { ...prev, condition: "All Conditions" };
    });
  }, [conditionOptions]);

  const tableRequest = useMemo<QcTableRequest | null>(() => {
    if (!isAnnotationKind(kind)) return null;
    if (activeTab === "coverage") {
      const params: Record<string, string | number | boolean> = {
        summary: coverage.summary,
      };
      return {
        tab: "coverage",
        params,
      };
    }
    if (activeTab === "boxplot") {
      const params: Record<string, string | number | boolean> = {
        mode: box.mode,
      };
      return {
        tab: "boxplot",
        params,
      };
    }
    if (activeTab === "cv") {
      return {
        tab: "cv",
        params: undefined,
      };
    }
    return null;
  }, [kind, activeTab, coverage.summary, box.mode]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }
    if (!tableRequest) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }

    const controller = new AbortController();
    setTableLoading(true);
    setTableError(null);

    getQcTable(kind, tableRequest.tab, tableRequest.params, { signal: controller.signal })
      .then((response) => {
        setTableRows(response.rows ?? []);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [kind, tableRequest, availableKinds]);

  const activeAdvancedSettings = advancedByTab[activeTab] ?? {};
  const activeAdvancedRenderSettings = useMemo(
    () => advancedRenderByTab[activeTab] ?? {},
    [activeTab, advancedRenderByTab]
  );
  const activeConditionDisplayLabels = useMemo(
    () => Object.fromEntries(conditionOptions.map((condition) => [condition, condition])),
    [conditionOptions]
  );
  const activeSampleDisplayLabels = useMemo(() => {
    const rawLabels = Object.fromEntries(sampleOptions.map((sample) => [sample, sample]));
    if (activeTab === "coverage" && !coverage.summary) {
      return coverage.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    if (activeTab === "boxplot" && box.mode === "Single") {
      return box.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    if (activeTab === "correlation") {
      return correlation.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    return rawLabels;
  }, [
    activeTab,
    box.includeId,
    box.mode,
    correlation.includeId,
    coverage.includeId,
    coverage.summary,
    sampleDisplayLabels,
    sampleDisplayLabelsWithId,
    sampleOptions,
  ]);
  const activeAdvancedVisibleControls = useMemo<AdvancedPlotVisibleControls>(() => {
    const base: AdvancedPlotVisibleControls = {
      textElements: true,
      tickControls: true,
      legendControls: false,
      referenceLineColor: false,
      conditionLabels: false,
      sampleLabels: false,
      conditionColors: false,
      boxplotStyle: false,
      boxplotOutliers: false,
      correlationGradient: false,
    };
    if (activeTab === "coverage") {
      return {
        ...base,
        legendControls: Boolean(coverage.legend && !coverage.summary),
        referenceLineColor: true,
        conditionLabels: true,
        sampleLabels: !coverage.summary,
        conditionColors: true,
      };
    }
    if (activeTab === "histogram") {
      return {
        ...base,
        legendControls: Boolean(hist.legend),
        conditionLabels: true,
        conditionColors: true,
      };
    }
    if (activeTab === "boxplot") {
      return {
        ...base,
        legendControls: Boolean(box.legend),
        conditionLabels: true,
        sampleLabels: String(box.mode).toLowerCase() === "single",
        conditionColors: true,
        boxplotStyle: true,
        boxplotOutliers: Boolean(box.outliers),
      };
    }
    if (activeTab === "cv") {
      return {
        ...base,
        legendControls: Boolean(cv.legend),
        conditionLabels: true,
        conditionColors: true,
        boxplotStyle: true,
        boxplotOutliers: Boolean(cv.outliers),
      };
    }
    if (activeTab === "pca") {
      const colorBy = String(pca.colorBy || "Condition").trim().toLowerCase();
      const clusterMethod = String(pca.clusterMethod || "None").trim().toLowerCase();
      const usesConditionGroups = colorBy !== "cluster" || clusterMethod === "none";
      return {
        ...base,
        legendControls: Boolean(pca.legend),
        conditionLabels: usesConditionGroups,
        conditionColors: usesConditionGroups,
      };
    }
    if (activeTab === "abundance") {
      return {
        ...base,
        legendControls: Boolean(abundance.legend),
        conditionLabels: true,
        conditionColors: true,
      };
    }
      return {
        ...base,
        sampleLabels: true,
        correlationGradient: true,
      };
  }, [
    activeTab,
    abundance.legend,
    box.legend,
    box.mode,
    box.outliers,
    coverage.legend,
    coverage.summary,
    cv.legend,
    cv.outliers,
    hist.legend,
    pca.clusterMethod,
    pca.colorBy,
    pca.legend,
  ]);
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    const matplotlibDefaults: AdvancedPlotControlDefaults = {
      axisLineLeft: true,
      axisLineRight: true,
      axisLineBottom: true,
      axisLineTop: true,
      gridLineVisible: false,
      gridLineAxis: "y",
      gridLineStyle: "dashed",
      gridLineWidth: 0.8,
    };
    const plotlyDefaults: AdvancedPlotControlDefaults = {
      axisLineLeft: false,
      axisLineRight: false,
      axisLineBottom: false,
      axisLineTop: false,
      gridLineVisible: true,
      gridLineAxis: "both",
      gridLineColor: "#EBF0F8",
      gridLineStyle: "solid",
      gridLineWidth: 1,
    };
    if (activeTab === "pca" && pca.type === "Interactive") {
      return plotlyDefaults;
    }
    if (activeTab === "abundance" && abundance.type === "Interactive") {
      return plotlyDefaults;
    }
    return matplotlibDefaults;
  }, [activeTab, abundance.type, pca.type]);
  const activeAdvancedParam = useMemo(
    () => advancedParam(activeAdvancedRenderSettings, advancedModeEnabled),
    [activeAdvancedRenderSettings, advancedModeEnabled]
  );

  const plotView = useMemo(() => {
    if (!activeKindOptions.some((option) => option.value === kind)) return null;
    if (activeTab === "coverage") {
      if (kind === "peptide" && (!coverage.quantityColumn || peptideQuantityError)) return null;
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/coverage.png`, withAdvancedParams(coverage, activeAdvancedParam)),
      };
    }
    if (activeTab === "histogram") {
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/intensity-histogram.png`, withAdvancedParams(hist, activeAdvancedParam)),
      };
    }
    if (activeTab === "boxplot") {
      const boxParams = withBoxplotStyleParams(box, activeAdvancedRenderSettings);
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/boxplot.png`, withAdvancedParams(boxParams, activeAdvancedParam)),
      };
    }
    if (activeTab === "cv") {
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/cv.png`, withAdvancedParams(cv, activeAdvancedParam)),
      };
    }
    if (activeTab === "pca") {
      const { type, ...params } = pca;
      const plotParams = withAdvancedParams(params, activeAdvancedParam);
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/pca-interactive.html`, plotParams),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/pca.png`, plotParams) };
    }
    if (activeTab === "abundance") {
      const { type, ...params } = abundance;
      const plotParams = withAdvancedParams(params, activeAdvancedParam);
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/abundance-interactive.html`, plotParams),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/abundance.png`, plotParams) };
    }
    const correlationParams = withCorrelationStyleParams(correlation, activeAdvancedRenderSettings);
    return {
      mode: "image" as const,
      url: buildPlotUrl(`/api/plots/qc/${kind}/correlation.png`, withAdvancedParams(correlationParams, activeAdvancedParam)),
    };
  }, [
    activeTab,
    kind,
    coverage,
    hist,
    box,
    cv,
    pca,
    abundance,
    correlation,
    activeKindOptions,
    activeAdvancedParam,
    activeAdvancedRenderSettings,
    peptideQuantityError,
  ]);

  const plotDownloadUrl = useMemo(() => {
    if (!plotView || plotView.mode !== "image") return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView || plotView.mode !== "image") return "";
    return withPlotDownloadFilename(`qc_${activeTab}_${kind}.png`, downloadFormat);
  }, [plotView, activeTab, kind, downloadFormat]);

  const interactiveHeightPx = useMemo(() => {
    if (activeTab === "pca" && pca.type === "Interactive") {
      return cmToIframeHeight(pca.heightCm);
    }
    if (activeTab === "abundance" && abundance.type === "Interactive") {
      return cmToIframeHeight(abundance.heightCm);
    }
    return 760;
  }, [activeTab, pca.type, pca.heightCm, abundance.type, abundance.heightCm]);

  const activePlotTitle = useMemo(() => {
    if (activeTab === "pca") {
      return `${pcaMethodLabel(pca.method)} Plot`;
    }
    return tabTitle(activeTab);
  }, [activeTab, pca.method]);

  const tableCsvUrl = useMemo(() => {
    if (!tableRequest || tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableRows, columns))}`;
  }, [tableRequest, tableRows]);

  async function handleImageError(url: string) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed?.detail) {
            setImageError(parsed.detail);
            return;
          }
        } catch {}
      }
    } catch {}
    setImageError("Failed to load plot image. Check backend logs for details.");
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">QC Pipeline</h2>
        <div className="mt-4 max-w-xs">
            <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
            <select
            value={activeKindOptions.length === 0 ? "" : kind}
            onChange={(e) => setKind(e.target.value as QcKind)}
            disabled={activeKindOptions.length === 0}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
          >
            {activeKindOptions.length === 0 ? (
              <option value="">No dataset available</option>
            ) : (
              activeKindOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </select>
        </div>
      </section>

      {activeKindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, phosphoprotein, or peptide dataset in the Data tab to enable QC plotting.
        </section>
      ) : null}

      {activeKindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        <div className="mt-4">{renderOptions()}</div>
        {kind === "peptide" && peptideQuantityError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {peptideQuantityError}
          </div>
        ) : null}
      </section>
      ) : null}

      {activeKindOptions.length > 0 && advancedModeEnabled ? (
        <AdvancedPlotOptions
          key={activeTab}
          value={activeAdvancedSettings}
          onChange={(next) => setAdvancedByTab((prev) => ({ ...prev, [activeTab]: next }))}
          conditionOptions={conditionOptions}
          conditionDisplayLabels={activeConditionDisplayLabels}
          sampleOptions={sampleOptions}
          sampleDisplayLabels={activeSampleDisplayLabels}
          visibleControls={activeAdvancedVisibleControls}
          controlDefaults={activeAdvancedControlDefaults}
        />
      ) : null}

      {activeKindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{activePlotTitle}</h3>
          {plotView?.mode === "image" ? (
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={downloadFormat}
                onChange={(e) => setDownloadFormat(e.target.value as PlotDownloadFormat)}
                className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
              >
                {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <a
                href={plotDownloadUrl}
                download={plotDownloadFilename}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
          ) : plotView ? (
            <a
              href={plotView.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Open Interactive Plot
            </a>
          ) : null}
        </div>
        <div className="mt-4">
          {plotView?.mode === "image" ? (
            <img
              key={plotView?.url}
              src={plotView?.url}
              alt={activePlotTitle}
              className="w-full rounded-xl border border-slate-200"
              onLoad={() => setImageError(null)}
              onError={() => {
                if (plotView?.url) handleImageError(plotView.url);
              }}
            />
          ) : plotView ? (
            <iframe
              key={plotView.url}
              src={plotView.url}
              title={`${activePlotTitle} interactive plot`}
              className="w-full rounded-xl border border-slate-200"
              style={{ height: `${interactiveHeightPx}px` }}
              onLoad={() => setImageError(null)}
            />
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              No plot available for the selected dataset.
            </div>
          )}
        </div>
        {imageError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {imageError}
          </div>
        ) : null}
      </section>
      ) : null}

      {activeKindOptions.length > 0 && tableRequest ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            {tableCsvUrl ? (
              <a
                href={tableCsvUrl}
                download={`qc_${activeTab}_${kind}_summary.csv`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download CSV
              </a>
            ) : null}
          </div>
          <div className="mt-4">
            {tableLoading ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                Loading table...
              </div>
            ) : tableError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {tableError}
              </div>
            ) : (
              <PreviewTable rows={tableRows} emptyText="No summary rows available." />
            )}
          </div>
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    if (activeTab === "coverage") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="id" label="Toggle IDs" checked={coverage.includeId} onChange={(v) => setCoverage({ ...coverage, includeId: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={coverage.header} onChange={(v) => setCoverage({ ...coverage, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={coverage.legend} onChange={(v) => setCoverage({ ...coverage, legend: v })} />,
            <Checkbox key="summary" label="Summary Type" checked={coverage.summary} onChange={(v) => setCoverage({ ...coverage, summary: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={coverage.text} onChange={(v) => setCoverage({ ...coverage, text: v })} />,
          ]}
          inputs={[
            ...(kind === "peptide"
              ? [
                  <SelectField
                    key="quantity-column"
                    label="Abundance Column"
                    value={coverage.quantityColumn}
                    onChange={(value) => setCoverage({ ...coverage, quantityColumn: value })}
                    options={peptideQuantityColumns}
                    placeholder={peptideQuantityRequiresSelection ? "Select abundance column" : undefined}
                  />,
                ]
              : []),
            <NumericField
              key="text-size"
              label="Text Size"
              value={coverage.textSize}
              onChange={(v) => setCoverage({ ...coverage, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
            ...(coverage.summary
              ? [
                  <NumericField
                    key="random-seed"
                    label="Random Seed"
                    value={coverage.randomSeed}
                    onChange={(v) => setCoverage({ ...coverage, randomSeed: Math.max(0, Math.round(v)) })}
                  />,
                ]
              : []),
          ]}
          sizeRow={
            <SizeRow
              dpi={coverage.dpi}
              heightCm={coverage.heightCm}
              widthCm={coverage.widthCm}
              onDpiChange={(v) => setCoverage({ ...coverage, dpi: Math.round(v) })}
              onHeightChange={(v) => setCoverage({ ...coverage, heightCm: v })}
              onWidthChange={(v) => setCoverage({ ...coverage, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "histogram") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={hist.header} onChange={(v) => setHist({ ...hist, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={hist.legend} onChange={(v) => setHist({ ...hist, legend: v })} />,
          ]}
          sizeRow={
            <SizeRow
              dpi={hist.dpi}
              heightCm={hist.heightCm}
              widthCm={hist.widthCm}
              onDpiChange={(v) => setHist({ ...hist, dpi: Math.round(v) })}
              onHeightChange={(v) => setHist({ ...hist, heightCm: v })}
              onWidthChange={(v) => setHist({ ...hist, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "boxplot") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="outliers" label="Toggle Outliers" checked={box.outliers} onChange={(v) => setBox({ ...box, outliers: v })} />,
            <Checkbox key="id" label="Toggle IDs" checked={box.includeId} onChange={(v) => setBox({ ...box, includeId: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={box.header} onChange={(v) => setBox({ ...box, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={box.legend} onChange={(v) => setBox({ ...box, legend: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={box.text} onChange={(v) => setBox({ ...box, text: v })} />,
          ]}
          inputs={[
            <SelectField
              key="type"
              label="Type"
              value={box.mode}
              onChange={(value) => setBox({ ...box, mode: value })}
              options={["Mean", "Single"]}
            />,
            <NumericField
              key="text-size"
              label="Text Size"
              value={box.textSize}
              onChange={(v) => setBox({ ...box, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={box.dpi}
              heightCm={box.heightCm}
              widthCm={box.widthCm}
              onDpiChange={(v) => setBox({ ...box, dpi: Math.round(v) })}
              onHeightChange={(v) => setBox({ ...box, heightCm: v })}
              onWidthChange={(v) => setBox({ ...box, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "cv") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="outliers" label="Toggle Outliers" checked={cv.outliers} onChange={(v) => setCv({ ...cv, outliers: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={cv.header} onChange={(v) => setCv({ ...cv, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={cv.legend} onChange={(v) => setCv({ ...cv, legend: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={cv.text} onChange={(v) => setCv({ ...cv, text: v })} />,
          ]}
          inputs={[
            <NumericField
              key="text-size"
              label="Text Size"
              value={cv.textSize}
              onChange={(v) => setCv({ ...cv, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={cv.dpi}
              heightCm={cv.heightCm}
              widthCm={cv.widthCm}
              onDpiChange={(v) => setCv({ ...cv, dpi: Math.round(v) })}
              onHeightChange={(v) => setCv({ ...cv, heightCm: v })}
              onWidthChange={(v) => setCv({ ...cv, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "pca") {
      const clusterMethodOptions = ["None", "KMeans", "Agglomerative", "DBSCAN"];
      const showDimensions = pca.method === "PCA";
      const showClusteringControls = pca.method !== "PCA";
      const colorByOptions = pca.clusterMethod === "None" ? ["Condition"] : ["Condition", "Cluster"];
      const showClusterCount =
        showClusteringControls &&
        (pca.clusterMethod === "KMeans" || pca.clusterMethod === "Agglomerative");
      const showDbscan = showClusteringControls && pca.clusterMethod === "DBSCAN";
      const showUmap = pca.method === "UMAP";
      const showTsne = pca.method === "t-SNE";
      const showRandomState = showUmap || showTsne;
      const showEllipsesToggle = pca.plotDim === "2D";

      return (
        <div className="space-y-4">
          <PcaFeatureNotice summary={pcaFeatures} dataSource={pca.dataSource} />
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={pca.header} onChange={(v) => setPca({ ...pca, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={pca.legend} onChange={(v) => setPca({ ...pca, legend: v })} />,
            ...(showEllipsesToggle
              ? [
                  <Checkbox
                    key="ellipses"
                    label="Add Ellipses (2D)"
                    checked={pca.addEllipses}
                    onChange={(v) => setPca({ ...pca, addEllipses: v })}
                  />,
                ]
              : []),
          ]}
          inputs={[
            <SelectField
              key="data-source"
              label="Data Source"
              value={pca.dataSource === "imputed" ? "Imputed Data" : "Data"}
              onChange={(value) =>
                setPca({ ...pca, dataSource: value === "Imputed Data" ? "imputed" : "data" })
              }
              options={imputedAvailable ? ["Data", "Imputed Data"] : ["Data"]}
            />,
            <SelectField
              key="method"
              label="Method"
              value={pca.method}
              onChange={(value) => {
                const nextMethod = value || "PCA";
                setPca({
                  ...pca,
                  method: nextMethod,
                  plotDim: nextMethod === "PCA" ? pca.plotDim : "2D",
                  addEllipses: pca.addEllipses,
                  clusterMethod: nextMethod === "PCA" ? "None" : pca.clusterMethod,
                  colorBy: nextMethod === "PCA" ? "Condition" : pca.colorBy,
                });
              }}
              options={["PCA", "UMAP", "t-SNE"]}
            />,
            <SelectField
              key="scaling"
              label="Feature scaling"
              value={scalingLabel(pca.scaling, pca.method)}
              onChange={(value) => setPca({ ...pca, scaling: scalingValue(value) })}
              options={[scalingDefaultLabel(pca.method), "Centred only", "Unit variance"]}
            />,
            <SelectField
              key="type"
              label="Type"
              value={pca.type}
              onChange={(value) => setPca({ ...pca, type: value })}
              options={["Normal", "Interactive"]}
            />,
            ...(showDimensions
              ? [
                  <SelectField
                    key="dim"
                    label="Dimensions"
                    value={pca.plotDim}
                    onChange={(value) => setPca({ ...pca, plotDim: value })}
                    options={["2D", "3D"]}
                  />,
                ]
              : []),
            <NumericField
              key="dot-size"
              label="Dot Size"
              value={pca.dotSize}
              onChange={(v) => setPca({ ...pca, dotSize: Math.max(1, Math.min(50, Math.round(v))) })}
            />,
            ...(showClusteringControls
              ? [
                  <SelectField
                    key="cluster-method"
                    label="Clustering"
                    value={pca.clusterMethod}
                    onChange={(value) => {
                      const nextClusterMethod = value || "None";
                      setPca({
                        ...pca,
                        clusterMethod: nextClusterMethod,
                        colorBy: nextClusterMethod === "None" ? "Condition" : pca.colorBy,
                      });
                    }}
                    options={clusterMethodOptions}
                  />,
                  <SelectField
                    key="color-by"
                    label="Color By"
                    value={colorByOptions.includes(pca.colorBy) ? pca.colorBy : "Condition"}
                    onChange={(value) => setPca({ ...pca, colorBy: value || "Condition" })}
                    options={colorByOptions}
                  />,
                ]
              : []),
            ...(showClusterCount
              ? [
                  <NumericField
                    key="cluster-count"
                    label="Cluster Count"
                    value={pca.clusterCount}
                    onChange={(v) =>
                      setPca({ ...pca, clusterCount: Math.max(2, Math.min(20, Math.round(v))) })
                    }
                  />,
                ]
              : []),
            ...(showDbscan
              ? [
                  <NumericField
                    key="dbscan-eps"
                    label="DBSCAN Eps"
                    value={pca.dbscanEps}
                    onChange={(v) => setPca({ ...pca, dbscanEps: Math.max(0.001, v) })}
                  />,
                  <NumericField
                    key="dbscan-min-samples"
                    label="DBSCAN Min Samples"
                    value={pca.dbscanMinSamples}
                    onChange={(v) =>
                      setPca({ ...pca, dbscanMinSamples: Math.max(1, Math.min(50, Math.round(v))) })
                    }
                  />,
                ]
              : []),
            ...(showUmap
              ? [
                  <NumericField
                    key="umap-neighbors"
                    label="UMAP Neighbors"
                    value={pca.umapNNeighbors}
                    onChange={(v) =>
                      setPca({ ...pca, umapNNeighbors: Math.max(2, Math.min(200, Math.round(v))) })
                    }
                  />,
                  <NumericField
                    key="umap-min-dist"
                    label="UMAP Min Dist"
                    value={pca.umapMinDist}
                    onChange={(v) => setPca({ ...pca, umapMinDist: Math.max(0, Math.min(1, v)) })}
                  />,
                ]
              : []),
            ...(showTsne
              ? [
                  <NumericField
                    key="tsne-perplexity"
                    label="t-SNE Perplexity"
                    value={pca.tsnePerplexity}
                    onChange={(v) => setPca({ ...pca, tsnePerplexity: Math.max(1, v) })}
                  />,
                  <NumericField
                    key="tsne-learning-rate"
                    label="t-SNE Learning Rate"
                    value={pca.tsneLearningRate}
                    onChange={(v) => setPca({ ...pca, tsneLearningRate: Math.max(10, v) })}
                  />,
                ]
              : []),
            ...(showRandomState
              ? [
                  <NumericField
                    key="random-state"
                    label="Random State"
                    value={pca.randomState}
                    onChange={(v) => setPca({ ...pca, randomState: Math.max(0, Math.round(v)) })}
                  />,
                ]
              : []),
          ]}
          sizeRow={
            <SizeRow
              dpi={pca.dpi}
              heightCm={pca.heightCm}
              widthCm={pca.widthCm}
              onDpiChange={(v) => setPca({ ...pca, dpi: Math.round(v) })}
              onHeightChange={(v) => setPca({ ...pca, heightCm: v })}
              onWidthChange={(v) => setPca({ ...pca, widthCm: v })}
            />
          }
        />
        </div>
      );
    }

    if (activeTab === "abundance") {
      const abundanceConditions = ["All Conditions", ...conditionOptions];
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={abundance.header} onChange={(v) => setAbundance({ ...abundance, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={abundance.legend} onChange={(v) => setAbundance({ ...abundance, legend: v })} />,
          ]}
          inputs={[
            <SelectField
              key="type"
              label="Type"
              value={abundance.type}
              onChange={(value) => setAbundance({ ...abundance, type: value })}
              options={["Normal", "Interactive"]}
            />,
            <SelectField
              key="condition"
              label="Condition"
              value={abundance.condition}
              onChange={(value) => setAbundance({ ...abundance, condition: value || "All Conditions" })}
              options={abundanceConditions}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={abundance.dpi}
              heightCm={abundance.heightCm}
              widthCm={abundance.widthCm}
              onDpiChange={(v) => setAbundance({ ...abundance, dpi: Math.round(v) })}
              onHeightChange={(v) => setAbundance({ ...abundance, heightCm: v })}
              onWidthChange={(v) => setAbundance({ ...abundance, widthCm: v })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        toggles={[
          <Checkbox key="id" label="Toggle IDs" checked={correlation.includeId} onChange={(v) => setCorrelation({ ...correlation, includeId: v })} />,
          <Checkbox key="full-range" label="Use Full Range" checked={correlation.fullRange} onChange={(v) => setCorrelation({ ...correlation, fullRange: v })} />,
        ]}
        inputs={[
          <SelectField
            key="method"
            label="Type"
            value={correlation.method}
            onChange={(value) => setCorrelation({ ...correlation, method: value })}
            options={["Matrix", "Ellipse"]}
          />,
        ]}
        sizeRow={
          <SizeRow
            dpi={correlation.dpi}
            heightCm={correlation.heightCm}
            widthCm={correlation.widthCm}
            onDpiChange={(v) => setCorrelation({ ...correlation, dpi: Math.round(v) })}
            onHeightChange={(v) => setCorrelation({ ...correlation, heightCm: v })}
            onWidthChange={(v) => setCorrelation({ ...correlation, widthCm: v })}
          />
        }
      />
    );
  }
}

function PcaFeatureNotice({
  summary,
  dataSource,
}: {
  summary: QcPcaFeatureSummary | null;
  dataSource: string;
}) {
  if (!summary || summary.featuresTotal <= 0) return null;
  const { featuresComplete, featuresUsed, featuresTotal, featuresRequired } = summary;
  const fraction = featuresUsed / featuresTotal;
  const missingnessBlocksPca = featuresComplete < featuresRequired;
  const constantFeaturesBlockPca = !missingnessBlocksPca && featuresUsed < featuresRequired;
  const cannotRun = missingnessBlocksPca || constantFeaturesBlockPca;
  // Features with any missing value are dropped before projection, so a low
  // fraction means the plot reflects a small, abundance-biased subset.
  const severe = cannotRun || featuresUsed < 3 || fraction < 0.05;
  const warn = severe || fraction < 0.25;
  const tone = severe
    ? "border-red-300 bg-red-50 text-red-800"
    : warn
      ? "border-amber-300 bg-amber-50 text-amber-800"
      : "border-slate-200 bg-slate-50 text-slate-600";
  return (
    <div className={`rounded-xl border px-3 py-2 text-sm ${tone}`}>
      <span className="font-medium">
        PCA-usable features: {featuresUsed.toLocaleString()} of {featuresTotal.toLocaleString()}
        ({(fraction * 100).toFixed(1)}%)
      </span>
      {missingnessBlocksPca ? (
        <span>
          {" "}
          &mdash; PCA cannot run because only {featuresComplete.toLocaleString()} complete feature
          {featuresComplete === 1 ? " remains" : "s remain"}; the missingness is too high. {dataSource === "imputed"
            ? "Rerun Imputation successfully and then retry with Imputed Data."
            : "Run Imputation, then select Imputed Data here."}
        </span>
      ) : null}
      {constantFeaturesBlockPca ? (
        <span>
          {" "}
          &mdash; PCA cannot run because fewer than {featuresRequired} complete, variable features
          remain after constant features are excluded.
        </span>
      ) : null}
      {warn && !cannotRun ? (
        <span>
          {" "}
          &mdash; features missing in any sample are excluded, so this projection reflects only
          the consistently detected (and therefore more abundant) subset.
          {severe ? " Too few features remain for the plot to be meaningful." : ""}
        </span>
      ) : null}
    </div>
  );
}

function OptionsLayout({
  toggles,
  inputs,
  sizeRow,
}: {
  toggles: ReactNode[];
  inputs?: ReactNode[];
  sizeRow: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">{toggles}</div>
      {inputs && inputs.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-3">{inputs}</div>
      ) : null}
      <div>{sizeRow}</div>
    </div>
  );
}

function SizeRow({
  dpi,
  heightCm,
  widthCm,
  onDpiChange,
  onHeightChange,
  onWidthChange,
}: {
  dpi: number;
  heightCm: number;
  widthCm: number;
  onDpiChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onWidthChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="DPI" value={dpi} onChange={(value) => onDpiChange(clampPlotDpi(value))} />
      <NumericField label="Height (cm)" value={heightCm} onChange={(value) => onHeightChange(clampPlotDimensionCm(value))} />
      <NumericField label="Width (cm)" value={widthCm} onChange={(value) => onWidthChange(clampPlotDimensionCm(value))} />
    </div>
  );
}

function tabTitle(tab: QcTab): string {
  switch (tab) {
    case "coverage":
      return "Coverage Plot";
    case "histogram":
      return "Histogram Intensity";
    case "boxplot":
      return "Boxplot Intensity";
    case "cv":
      return "Cov Plot";
    case "pca":
      return "Principal Component Analysis";
    case "abundance":
      return "Abundance Plot";
    case "correlation":
      return "Correlation Plot";
  }
}

function pcaMethodLabel(method: string): string {
  const key = String(method || "").trim().toLowerCase();
  if (key === "umap") return "UMAP";
  if (key === "t-sne" || key === "tsne" || key === "t_sne") return "t-SNE";
  return "PCA";
}

// "Method default" is `auto`: centred for PCA, unit variance for UMAP and
// t-SNE. Both are legitimate and they answer different questions, so the choice
// is exposed rather than left implicit in whichever method was picked.
function scalingDefaultLabel(method: string): string {
  return `Method default (${pcaMethodLabel(method) === "PCA" ? "centred" : "unit variance"})`;
}

function scalingLabel(scaling: string, method: string): string {
  const key = String(scaling || "auto").trim().toLowerCase();
  if (key === "centered" || key === "centred") return "Centred only";
  if (key === "unit_variance" || key === "scaled") return "Unit variance";
  return scalingDefaultLabel(method);
}

function scalingValue(label: string): string {
  if (label === "Centred only") return "centered";
  if (label === "Unit variance") return "unit_variance";
  return "auto";
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function NumericField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const displayedValue = draft ?? (Number.isFinite(value) ? String(value) : "");

  const commit = () => {
    const normalized = displayedValue.trim().replace(",", ".");
    if (!normalized) {
      setDraft(null);
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed)) {
      setDraft(null);
      return;
    }
    onChange(parsed);
    setDraft(null);
  };

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={displayedValue}
        onChange={(e) => {
          const normalized = e.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
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
  const columns = useMemo(() => collectColumns(rows), [rows]);

  if (rows.length === 0 || columns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
              {columns.map((column) => {
                const value = row[column];
                const text = value == null ? "" : String(value);
                return (
                  <td
                    key={`${rowIndex}-${column}`}
                    className="border-b border-slate-100 px-3 py-2 text-slate-600"
                    title={text}
                  >
                    <div className="max-w-[28ch] overflow-hidden text-ellipsis whitespace-nowrap">
                      {text}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function collectColumns(rows: Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => seen.add(key));
  });
  return Array.from(seen);
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]): string {
  if (rows.length === 0 || columns.length === 0) return "";
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ];
  return lines.join("\n");
}

function cmToIframeHeight(heightCm: number): number {
  const basePx = Number.isFinite(heightCm) ? (heightCm * 96) / 2.54 : (10 * 96) / 2.54;
  return Math.max(760, Math.round(basePx + 220));
}
