
import { oraListExportRows } from "../stats/oraExport";
import { collectColumns, csvDataUrl, rowsToQuotedCsv } from "../../lib/tableData";
import { linkedConditionsParam } from "./linkedConditions";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { AssistantSelect, AssistantTextarea, AssistantCanvasButton } from "../../components/AssistantFields";
import { TEST_TYPE_OPTIONS, restoreTestType, CONTROL_TEST_TYPE_OPTIONS, controlTestType } from "../../lib/statisticalTests";
import PairingEditor from "../../components/PairingEditor";
import AdvancedPlotOptions from "../../components/plots/AdvancedPlotOptions";
import { PLOT_DOWNLOAD_FORMAT_OPTIONS, withPlotDownloadFormat, type PlotDownloadFormat } from "../../lib/plotDownload";
import { buildPlotUrl, getStatisticalOptions, getSingleProteinOptions, getLineplotUnmatchedNotice, isAbortError, pairingIsReady, runAnalysisVolcanoData, runListEnrichmentAnalysis } from "../../lib/api";
import { useCurrentDatasetsSnapshot, useDatasetRevision } from "../../lib/datasetAvailability";
import type {
  AnalysisVolcanoPoint,
  AdvancedPlotSettings,
  AnalysisVolcanoResponse,
  AnnotationKind,
  DataSource,
  DataSourceChoices,
  ListEnrichmentRequest,
  StatsIdentifier,
  StatsTestType,
  StatisticalOptionsResponse,
} from "../../lib/types";
import { DATA_SOURCE_LABELS, dataSourceOptions, ENRICHMENT_ORGANISM_OPTIONS } from "../../lib/types";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { useCanvasFocus } from "../../lib/canvasFocus";
import SelectField from "../../components/SelectField";
import NumberField from "../../components/NumberField";
import TextField from "../../components/TextField";
import type { ContextMode, EnrichmentOrganism } from "../../lib/types";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";
import {
  asNumber, asString, CANVAS_VOLCANO_VISIBLE_CONTROLS, canvasImageVisibleControls, canvasPointStyle,
  restoredOraState, restoredVolcanoStyle, type OraState, type VolcanoStyle,
} from "./canvasState";

type TileType = "volcano" | "volcanoControl" | "proteinBoxplot" | "proteinLineplot" | "oraList";
type BoxplotSourceMode = "active" | "manual";
type LineplotSourceMode = "active" | "selected" | "list" | "manual";
type PValueMode = "corrected" | "uncorrected";

type VolcanoSettings = {
  dataSource: DataSource;
  condition1: string;
  condition2: string;
  testType: StatsTestType;
  pValueThreshold: number;
  log2fcThreshold: number;
  pValueMode: PValueMode;
};

type VolcanoControlSettings = VolcanoSettings & {
  condition1Control: string;
  condition2Control: string;
};

function canvasText(style: VolcanoStyle, key: "titleElement" | "xLabelElement" | "yLabelElement") {
  const element = style[key] ?? {};
  return {
    text: element.text?.trim() ?? "",
    size: element.size,
    color: element.color,
    bold: element.bold === true,
    italic: element.italic === true,
  };
}

type AnalysisTile = { collapsed?: boolean; focusGroup?: string; highlightFeatures?: string[]; conditions?: string[]; plotIdentifier?: StatsIdentifier } & (
  | { id: string; type: "volcano" | "volcanoControl"; settings: VolcanoControlSettings; style?: VolcanoStyle }
  | { id: string; type: "proteinBoxplot"; sourceMode: BoxplotSourceMode; protein: string; dataSource: DataSource; advanced?: AdvancedPlotSettings }
  | {
      id: string;
      type: "proteinLineplot";
      advanced?: AdvancedPlotSettings;
      dataSource: DataSource;
      sourceMode: LineplotSourceMode;
      listName: string;
      proteinsText: string;
    }
  | { id: string; type: "oraList"; state: OraState });

const ANALYSIS_UI_STATE_KEY = "analysis.v1";
const EMPTY_SELECTION: string[] = [];
// A saved "log2" is the old name for the annotated, unfiltered matrix, which
// is now called "data" -- so a panel saved before the rename restores to the
// same matrix rather than to an unsupported one.
function restoredPlotSource(value: unknown): DataSource {
  return value === "filtered" || value === "imputed" ? value : "data";
}

/** The contrast, written the way the number is computed.
 *
 * Mirrors `functions.comparison_contrast` on the backend. The first condition
 * is the minuend everywhere in this tool, so a positive log2FC means higher in
 * the condition named first. The canvas used to label its own axis
 * `(condition2 vs condition1)`, which reads as the opposite of what the points
 * mean, and "vs" does not say which way round a difference was taken at all.
 */
function comparisonContrast(
  condition1: string,
  condition2: string,
  condition1Control?: string,
  condition2Control?: string
): string {
  const first = condition1 || "Condition 1";
  const second = condition2 || "Condition 2";
  if (condition1Control && condition2Control) {
    return `(${first} - ${condition1Control}) - (${second} - ${condition2Control})`;
  }
  return `${first} - ${second}`;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "").trim()).filter(Boolean);
}

function asStringRecordArray(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== "object") return {};
  const result: Record<string, string[]> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    const normalizedKey = String(key || "").trim();
    if (!normalizedKey) continue;
    result[normalizedKey] = asStringArray(raw);
  }
  return result;
}

function restoredVolcanoSettings(value: unknown, control: boolean): VolcanoControlSettings {
  const saved = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const test = restoreTestType(saved.testType);
  return {
    // Through `restoredPlotSource`, like every other tile on this canvas. This
    // used to collapse a saved "filtered" to "data", so a volcano restored from
    // a save file silently ran on the unfiltered matrix -- a different row
    // count, a different BH denominator, different adjusted p-values -- while
    // the selector agreed with the value it had just been changed to.
    dataSource: restoredPlotSource(saved.dataSource),
    condition1: asString(saved.condition1), condition2: asString(saved.condition2),
    condition1Control: asString(saved.condition1Control), condition2Control: asString(saved.condition2Control),
    testType: control ? controlTestType(test) : test,
    pValueThreshold: asNumber(saved.pValueThreshold, 0.05),
    log2fcThreshold: asNumber(saved.log2fcThreshold, 1),
    pValueMode: saved.pValueMode === "uncorrected" ? "uncorrected" : "corrected",
  };
}

function asAnalysisTiles(value: unknown, legacy: Record<string, unknown>): AnalysisTile[] {
  if (!Array.isArray(value)) return [];
  const result: AnalysisTile[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    const id = asString(item.id);
    const type = asString(item.type);
    if (!id) continue;
    const focus = { focusGroup: asString(item.focusGroup), highlightFeatures: asStringArray(item.highlightFeatures),
      conditions: Array.isArray(item.conditions) ? asStringArray(item.conditions) : undefined,
      plotIdentifier: item.plotIdentifier === "workflow" || item.plotIdentifier === "genes" ? item.plotIdentifier : undefined } as const;
    if (type === "volcano" || type === "volcanoControl") {
      result.push({ ...focus, id, type, collapsed: item.collapsed === true, style: restoredVolcanoStyle(item.style), settings: restoredVolcanoSettings(item.settings ??
        legacy[type === "volcano" ? "volcanoSettings" : "volcanoControlSettings"], type === "volcanoControl") });
      continue;
    }
    if (type === "oraList") {
      result.push({ ...focus, id, type, collapsed: item.collapsed === true, state: restoredOraState(item.state) });
      continue;
    }
    if (type === "proteinBoxplot") {
      const sourceMode = asString(item.sourceMode, "active");
      result.push({
        id,
        type,
        sourceMode:
          sourceMode === "active" || sourceMode === "manual"
            ? sourceMode
            : "active",
        protein: asString(item.protein),
        ...focus,
        collapsed: item.collapsed === true,
        advanced: item.advanced && typeof item.advanced === "object" && !Array.isArray(item.advanced) ? item.advanced as AdvancedPlotSettings : undefined,
        dataSource: restoredPlotSource(item.dataSource),
      });
      continue;
    }
    if (type === "proteinLineplot") {
      const sourceMode = asString(item.sourceMode, "active");
      result.push({
        id,
        type,
        sourceMode:
          sourceMode === "active" ||
          sourceMode === "selected" ||
          sourceMode === "list" ||
          sourceMode === "manual"
            ? sourceMode
            : "active",
        listName: asString(item.listName),
        proteinsText: asString(item.proteinsText),
        ...focus,
        collapsed: item.collapsed === true,
        advanced: item.advanced && typeof item.advanced === "object" && !Array.isArray(item.advanced) ? item.advanced as AdvancedPlotSettings : undefined,
        dataSource: restoredPlotSource(item.dataSource),
      });
      continue;
    }
  }
  return result;
}

function uid() {
  return `tile_${Date.now()}_${Math.floor(Math.random() * 1_000_000)}`;
}

function parseProteins(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[\s,;\n\r\t]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function toUnique(values: string[]) {
  return Array.from(new Set(values.map((item) => item.trim()).filter(Boolean)));
}


function textDataUrl(values: string[]): string {
  return `data:text/plain;charset=utf-8,${encodeURIComponent(values.join("\n"))}`;
}

function buildDirectionListName(condition1: string, condition2: string, direction: "Upregulated" | "Downregulated"): string {
  const left = condition1.trim() || "Condition1";
  const right = condition2.trim() || "Condition2";
  return `${left}vd${right}${direction}`;
}

function extractUniProtAccession(...values: Array<string | null | undefined>): string | null {
  const pattern =
    /\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9](?:-\d+)?|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}(?:-\d+)?)\b/;
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) continue;
    const parts = text.split(/[;,\s]+/).filter(Boolean);
    for (const part of parts) {
      const match = part.match(pattern);
      if (match) return match[0];
    }
    const fallback = text.match(pattern);
    if (fallback) return fallback[0];
  }
  return null;
}

function extractUniProtEntryName(...values: Array<string | null | undefined>): string | null {
  const pattern = /\b[A-Z0-9]{1,10}_[A-Z0-9]{3,10}\b/;
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) continue;
    const parts = text.split(/[;,\s|]+/).filter(Boolean);
    for (const part of parts) {
      const match = part.match(pattern);
      if (match) return match[0];
    }
    const fallback = text.match(pattern);
    if (fallback) return fallback[0];
  }
  return null;
}

function resolveLineplotProteins(
  tile: Extract<AnalysisTile, { type: "proteinLineplot" }>,
  activeProtein: string,
  selectedProteins: string[],
  lists: Record<string, string[]>
): string[] {
  if (tile.sourceMode === "active") return activeProtein ? [activeProtein] : [];
  if (tile.sourceMode === "selected") return toUnique(selectedProteins);
  if (tile.sourceMode === "list") return toUnique(lists[tile.listName] ?? []);
  if (tile.focusGroup && tile.highlightFeatures && tile.proteinsText === tile.highlightFeatures.join("\n")) return tile.highlightFeatures;
  return parseProteins(tile.proteinsText);
}

function volcanoPointSelectionKey(point: AnalysisVolcanoPoint): string {
  return point.selectionKey || point.selectionLabel || point.label;
}

function volcanoPointListLabel(point: AnalysisVolcanoPoint): string {
  return point.selectionLabel || point.label;
}

function volcanoPointBoxplotTarget(
  point: AnalysisVolcanoPoint | null,
  fallbackIdentifier: StatsIdentifier,
): { protein: string; identifier: StatsIdentifier } {
  if (!point) return { protein: "", identifier: fallbackIdentifier };
  return {
    protein: point.boxplotLabel || volcanoPointSelectionKey(point),
    identifier: point.boxplotIdentifier || fallbackIdentifier,
  };
}

export default function AnalysisPage({
  rightPanel = "none",
  onRightPanelChange,
  aiEnabled = false,
  onContextModeChange,
}: {
  rightPanel?: "none" | "list" | "chat";
  onRightPanelChange?: (panel: "none" | "list" | "chat") => void;
  aiEnabled?: boolean;
  onContextModeChange?: (mode: ContextMode | null) => void;
}) {
  const activeListFieldId = useId();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>(ANALYSIS_UI_STATE_KEY, {}),
    []
  );
  const { kindOptions } = useCurrentDatasetsSnapshot();
  const revision = useDatasetRevision();
  const [preferredKind, setKind] = useState<AnnotationKind>(() => {
    const value = asString(persisted.kind, "protein");
    return value === "protein" || value === "phospho" || value === "phosprot"
      ? value
      : "protein";
  });
  const kind = (kindOptions.some((option) => option.value === preferredKind)
    ? preferredKind
    : kindOptions[0]?.value ?? preferredKind) as AnnotationKind;
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);
  const [plotSources, setPlotSources] = useState<{ kind: AnnotationKind; revision: number; choices: DataSourceChoices } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getSingleProteinOptions(kind, "boxplot", "workflow", "data", { signal: controller.signal })
      .then(data => {
        if (!controller.signal.aborted) setPlotSources({
          kind,
          revision,
          choices: {
            availableDataSources: data.availableDataSources ?? ["data"],
            defaultDataSource: data.defaultDataSource ?? "data",
          },
        });
      }).catch(() => {
        if (!controller.signal.aborted) setPlotSources(null);
      });
    return () => controller.abort();
  }, [kind, revision]);
  // The backend decides which matrices exist; this page only renders the answer,
  // so a canvas tile cannot offer a different ladder from the Statistics page.
  const plotSourceChoices = plotSources?.kind === kind && plotSources.revision === revision
    ? plotSources.choices
    : null;
  const plotSourceAvailable = (source: DataSource) =>
    plotSourceChoices ? plotSourceChoices.availableDataSources.includes(source) : source === "data";
  // A new tile opens on the most processed matrix available, like every other
  // panel; "data" until the ladder has loaded.
  const newTilePlotSource: DataSource = plotSourceChoices?.defaultDataSource ?? "data";
  function plotSourceOptions(selected: DataSource) {
    const offered = dataSourceOptions(plotSourceChoices);
    // A saved choice whose matrix has since gone is kept on screen and marked,
    // rather than silently becoming a different one.
    return offered.some(option => option.value === selected)
      ? offered
      : [...offered, { value: selected, label: `${DATA_SOURCE_LABELS[selected]} (unavailable)` }];
  }

  const [identifier, setIdentifier] = useState<StatsIdentifier>(() => {
    const value = asString(persisted.identifier, "workflow");
    return value === "genes" ? "genes" : "workflow";
  });
  const [tiles, setTiles] = useState<AnalysisTile[]>(() => asAnalysisTiles(persisted.tiles, persisted));
  const [linkedVolcanoId, setLinkedVolcanoId] = useState(() => asString(persisted.linkedVolcanoId));
  const linkedTile = tiles.find(tile => tile.id === linkedVolcanoId && "settings" in tile);
  const sourceTile = linkedTile ?? tiles.find(tile => "settings" in tile);
  const linkedSettings = sourceTile && "settings" in sourceTile ? sourceTile.settings : null;
  const [addType, setAddType] = useState<TileType>(() => {
    const value = asString(persisted.addType, "volcano");
    return value === "volcano" ||
      value === "volcanoControl" ||
      value === "proteinBoxplot" ||
      value === "proteinLineplot" ||
      value === "oraList"
      ? value
      : "volcano";
  });

  const [tileResults, setTileResults] = useState<Record<string, {
    key: string; data: AnalysisVolcanoResponse | null; error?: string;
  }>>({});
  const requestKey = (tile: Extract<AnalysisTile, { settings: VolcanoControlSettings }>) =>
    JSON.stringify({ revision, kind, identifier, ...tile.settings, source: tile.type });
  const visibleResult = (tile: Extract<AnalysisTile, { settings: VolcanoControlSettings }>) =>
    tileResults[tile.id]?.key === requestKey(tile) ? tileResults[tile.id] : undefined;
  const [retryGeneration, setRetryGeneration] = useState(0);
  const selectionContext = JSON.stringify({ revision, kind, identifier, source: sourceTile?.id, settings: linkedSettings });
  const [selection, setSelection] = useState(() => ({
    context: selectionContext,
    activeProtein: asString(persisted.activeProtein),
    selectedProteins: asStringArray(persisted.selectedProteins),
  }));
  const activeProtein = selection.context === selectionContext ? selection.activeProtein : "";
  const selectedProteins = selection.context === selectionContext ? selection.selectedProteins : EMPTY_SELECTION;
  const setActiveProtein = (next: string | ((current: string) => string)) => {
    setSelection((current) => {
      const active = current.context === selectionContext ? current.activeProtein : "";
      return {
        context: selectionContext,
        activeProtein: typeof next === "function" ? next(active) : next,
        selectedProteins: current.context === selectionContext ? current.selectedProteins : [],
      };
    });
  };
  const setSelectedProteins = (next: string[] | ((current: string[]) => string[])) => {
    setSelection((current) => {
      const selected = current.context === selectionContext ? current.selectedProteins : [];
      return {
        context: selectionContext,
        activeProtein: current.context === selectionContext ? current.activeProtein : "",
        selectedProteins: typeof next === "function" ? next(selected) : next,
      };
    });
  };

  const [lists, setLists] = useState<Record<string, string[]>>(() => asStringRecordArray(persisted.lists));
  const [newListName, setNewListName] = useState(() => asString(persisted.newListName));
  const restoredActiveList = asString(persisted.activeList);
  const initialActiveList = restoredActiveList in lists
    ? restoredActiveList
    : Object.keys(lists).sort()[0] ?? "";
  const [activeList, setActiveList] = useState(() => initialActiveList);
  const [activeListDraft, setActiveListDraft] = useState(() =>
    Object.hasOwn(persisted, "activeListDraft")
      ? asString(persisted.activeListDraft)
      : (lists[initialActiveList] ?? []).join("\n")
  );
  const [opA, setOpA] = useState(() => asString(persisted.opA));
  const [opB, setOpB] = useState(() => asString(persisted.opB));
  const [opMode, setOpMode] = useState<"intersection" | "union" | "a_minus_b" | "b_minus_a">(() => {
    const value = asString(persisted.opMode, "intersection");
    return value === "intersection" || value === "union" || value === "a_minus_b" || value === "b_minus_a"
      ? value
      : "intersection";
  });
  const [opTarget, setOpTarget] = useState(() => asString(persisted.opTarget));
  const listSidebarOpen = rightPanel === "list";

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  function conditionsValid(settings: VolcanoControlSettings, control: boolean) {
    const conditions = control
      ? [settings.condition1, settings.condition2, settings.condition1Control, settings.condition2Control]
      : [settings.condition1, settings.condition2];
    const offered = options?.availableDataSources ?? ["data"];
    return offered.includes(settings.dataSource) &&
      conditions.every(value => options?.availableConditions.includes(value)) &&
      new Set(conditions).size === conditions.length &&
      (settings.testType !== "paired" || pairingIsReady(settings.condition1, settings.condition2,
        options?.samplesByCondition ?? {}, options?.pairIdsBySample ?? {}));
  }

  useEffect(() => {
    if (!kindAvailable) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        setTiles(current => current.map(tile => {
          if (!("settings" in tile)) return tile;
          const settings = { ...tile.settings };
          for (const key of ["condition1", "condition2", "condition1Control", "condition2Control"] as const) {
            if (!data.availableConditions.includes(settings[key])) settings[key] = data.availableConditions[0] ?? "";
          }
          return { ...tile, settings };
        }));
        setIdentifier((current) =>
          data.availableIdentifiers.some((item) => item.key === current)
            ? current
            : data.availableIdentifiers[0]?.key ?? "workflow"
        );
      })
      .catch((error) => {
        if (!isAbortError(error)) setOptions(null);
      });
    return () => controller.abort();
  }, [kind, kindAvailable, revision]);

  const volcanoRequests = JSON.stringify(tiles.filter(tile => "settings" in tile)
    .map(tile => ({ id: tile.id, type: tile.type, settings: tile.settings,
      valid: conditionsValid(tile.settings, tile.type === "volcanoControl"), key: requestKey(tile) })));
  const tileRequests = useRef(new Map<string, { key: string; controller: AbortController }>());
  useEffect(() => {
    const requests = tileRequests.current;
    return () => {
      for (const request of requests.values()) request.controller.abort();
      requests.clear();
    };
  }, []);
  useEffect(() => {
    const requests = JSON.parse(volcanoRequests) as Array<{
      id: string; type: "volcano" | "volcanoControl"; settings: VolcanoControlSettings; valid: boolean; key: string;
    }>;
    for (const [id, pending] of tileRequests.current) {
      if (!kindAvailable || !requests.some(tile => tile.id === id && tile.valid && tile.key === pending.key)) {
        pending.controller.abort();
        tileRequests.current.delete(id);
      }
    }
    if (!kindAvailable) return;
    for (const tile of requests) {
      if (!tile.valid || tileRequests.current.get(tile.id)?.key === tile.key) continue;
      const controller = new AbortController();
      tileRequests.current.set(tile.id, { key: tile.key, controller });
      const { pValueMode, ...settings } = tile.settings;
      runAnalysisVolcanoData({
        kind, identifier, ...settings,
        source: tile.type === "volcano" ? "volcano" : "volcano_control",
        useUncorrected: pValueMode === "uncorrected",
      }, { signal: controller.signal }).then(data => {
        if (!controller.signal.aborted) setTileResults(current => ({ ...current,
          [tile.id]: { key: tile.key, data } }));
      }).catch(error => {
        if (!controller.signal.aborted && !isAbortError(error)) setTileResults(current => ({ ...current,
          [tile.id]: { key: tile.key, data: null, error: error instanceof Error ? error.message : "Failed to load analysis data" } }));
      });
    }
  }, [kindAvailable, kind, identifier, volcanoRequests, retryGeneration]);

  function retryVolcano(id: string) {
    tileRequests.current.get(id)?.controller.abort();
    tileRequests.current.delete(id);
    setTileResults(current => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    setRetryGeneration(current => current + 1);
  }

  const listNames = useMemo(() => Object.keys(lists).sort(), [lists]);

  useEffect(() => {
    writePersistedUiState(ANALYSIS_UI_STATE_KEY, {
      kind,
      identifier,
      linkedVolcanoId,
      tiles,
      addType,
      activeProtein,
      selectedProteins,
      lists,
      newListName,
      activeList,
      activeListDraft,
      opA,
      opB,
      opMode,
      opTarget,
    });
  }, [
    kind,
    identifier,
    linkedVolcanoId,
    tiles,
    addType,
    activeProtein,
    selectedProteins,
    lists,
    newListName,
    activeList,
    activeListDraft,
    opA,
    opB,
    opMode,
    opTarget,
  ]);

  function addTile() {
    if (addType === "proteinBoxplot") {
      setTiles((current) => [...current, { id: uid(), type: addType, sourceMode: "active", protein: "", dataSource: newTilePlotSource }]);
      return;
    }
    if (addType === "proteinLineplot") {
      setTiles((current) => [
        ...current,
        {
          id: uid(),
          type: addType,
          sourceMode: "active",
          dataSource: newTilePlotSource,
          listName: "",
          proteinsText: "",
        },
      ]);
      return;
    }
    if (addType === "oraList") {
      setTiles(current => [...current, { id: uid(), type: "oraList", state: restoredOraState(null) }]);
    } else {
      const template = tiles.find(tile => tile.type === addType && "settings" in tile);
      const settings = restoredVolcanoSettings(template && "settings" in template ? template.settings : {
        condition1: options?.availableConditions[0], condition2: options?.availableConditions[0],
        condition1Control: options?.availableConditions[0], condition2Control: options?.availableConditions[0],
      }, addType === "volcanoControl");
      setTiles(current => [...current, { id: uid(), type: addType, settings }]);
    }
  }

  function updateTile(id: string, nextTile: AnalysisTile) {
    setTiles((current) => current.map((tile) => (tile.id === id ? nextTile : tile)));
  }

  useCanvasFocus(focus => {
    if (!kindOptions.some(option => option.value === focus.kind)) throw new Error("The requested data level is unavailable.");
    if (tiles.length && kind !== focus.kind) throw new Error("Existing canvas tiles use another data level. Use an empty canvas to switch levels.");
    const group = JSON.stringify({ kind: focus.kind, features: focus.features });
    const existing = tiles.filter(tile => tile.focusGroup === group);
    const oldVolcano = existing.find(tile => tile.type === "volcano");
    const settings = { ...restoredVolcanoSettings(undefined, false), condition1: focus.conditions[0], condition2: focus.conditions[1] };
    const focused: AnalysisTile[] = [{ ...oldVolcano, id: oldVolcano?.id ?? uid(), type: "volcano", focusGroup: group,
      settings, collapsed: false, highlightFeatures: focus.features }];
    for (const protein of focus.features) {
      const old = existing.find(tile => tile.type === "proteinBoxplot" && tile.protein === protein);
      focused.push({ ...old, id: old?.id ?? uid(), type: "proteinBoxplot", focusGroup: group, collapsed: false,
        sourceMode: "manual", protein, dataSource: newTilePlotSource, plotIdentifier: "workflow", conditions: focus.conditions });
    }
    const oldLine = existing.find(tile => tile.type === "proteinLineplot");
    focused.push({ ...oldLine, id: oldLine?.id ?? uid(), type: "proteinLineplot", focusGroup: group, collapsed: false,
      sourceMode: "manual", proteinsText: focus.features.join("\n"), highlightFeatures: focus.features, listName: "", dataSource: newTilePlotSource, plotIdentifier: "workflow", conditions: focus.conditions });
    setKind(focus.kind);
    setTiles([...tiles.filter(tile => tile.focusGroup !== group), ...focused]);
    return `Focused the ${focus.kind === "phospho" ? "phosphosite" : focus.kind === "phosprot" ? "phosphoprotein" : "protein"} canvas on ${focus.features.join(", ")} (${comparisonContrast(focus.conditions[0], focus.conditions[1])}): volcano highlight, individual boxplots and lineplot. Existing unrelated tiles were kept. Plots may still be loading; a feature excluded from the comparison will have no volcano point.`;
  });

  const updateOraState = useCallback((id: string, patch: Partial<OraState>) => {
    setTiles(current => current.map(tile => tile.id === id && tile.type === "oraList"
      ? { ...tile, state: { ...tile.state, ...patch } } : tile));
  }, []);

  function removeTile(id: string) {
    setTiles((current) => current.filter((tile) => tile.id !== id));
    setTileResults(current => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  }

  function moveTile(id: string, direction: -1 | 1) {
    if (sourceTile) setLinkedVolcanoId(sourceTile.id);
    setTiles(current => {
      const index = current.findIndex(tile => tile.id === id);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function selectFromTile(tile: Extract<AnalysisTile, { settings: VolcanoControlSettings }>, proteins: string[], mode: "single" | "toggle" | "list") {
    const context = JSON.stringify({ revision, kind, identifier, source: tile.id, settings: tile.settings });
    setLinkedVolcanoId(tile.id);
    setSelection(current => {
      const previous = current.context === context ? current : { activeProtein: "", selectedProteins: [] };
      const first = proteins[0] ?? "";
      if (mode === "single") return { context, activeProtein: previous.activeProtein === first ? "" : first,
        selectedProteins: previous.activeProtein === first ? [] : proteins };
      if (mode === "list") return { context, activeProtein: first, selectedProteins: proteins };
      const next = new Set(previous.selectedProteins);
      for (const protein of toUnique(proteins)) {
        if (next.has(protein)) next.delete(protein);
        else next.add(protein);
      }
      return { context, activeProtein: "", selectedProteins: [...next] };
    });
  }

  function clearSelection() {
    setActiveProtein("");
    setSelectedProteins([]);
  }

  function addProteinsToList(listName: string, proteins: string[]) {
    const cleaned = toUnique(proteins);
    const nextValues = toUnique([...(lists[listName] ?? []), ...cleaned]);
    setLists((current) => ({
      ...current,
      [listName]: toUnique([...(current[listName] ?? []), ...cleaned]),
    }));
    setActiveList(listName);
    setActiveListDraft(nextValues.join("\n"));
  }

  function createList() {
    const name = newListName.trim();
    if (!name) return;
    setLists((current) => ({ ...current, [name]: current[name] ?? [] }));
    setNewListName("");
    setActiveList(name);
    setActiveListDraft((lists[name] ?? []).join("\n"));
  }

  function addSelectedToActiveList() {
    if (!activeList || selectedProteins.length === 0) return;
    const nextValues = toUnique([...(lists[activeList] ?? []), ...selectedProteins]);
    setLists((current) => ({
      ...current,
      [activeList]: toUnique([...(current[activeList] ?? []), ...selectedProteins]),
    }));
    setActiveListDraft(nextValues.join("\n"));
  }

  function saveActiveList() {
    if (!activeList) return;
    setLists((current) => ({
      ...current,
      [activeList]: parseProteins(activeListDraft),
    }));
  }

  function applyListOperation() {
    const target = opTarget.trim();
    if (!target || !opA || !opB) return;

    const a = new Set(lists[opA] ?? []);
    const b = new Set(lists[opB] ?? []);
    let out: string[] = [];

    if (opMode === "intersection") out = [...a].filter((item) => b.has(item));
    if (opMode === "union") out = [...new Set([...a, ...b])];
    if (opMode === "a_minus_b") out = [...a].filter((item) => !b.has(item));
    if (opMode === "b_minus_a") out = [...b].filter((item) => !a.has(item));

    setLists((current) => ({ ...current, [target]: toUnique(out) }));
    setActiveList(target);
    setActiveListDraft(toUnique(out).join("\n"));
    setOpTarget("");
  }

  // Kept as text so it is stable across renders.
  const linkedConditionsJson = linkedConditionsParam(linkedSettings);
  const linkedData = sourceTile && "settings" in sourceTile ? visibleResult(sourceTile)?.data : null;
  const activeVolcanoPoint = activeProtein
    ? linkedData?.points.find(point => volcanoPointSelectionKey(point) === activeProtein) ?? null : null;
  const activeBoxplotTarget = useMemo(
    () => volcanoPointBoxplotTarget(activeVolcanoPoint, identifier),
    [activeVolcanoPoint, identifier]
  );
  useEffect(() => {
    const tileEvidence = tiles.slice(0, 8).map(tile => {
      if (tile.collapsed) return { id: tile.id, type: tile.type, collapsed: true };
      if (tile.type === "volcano" || tile.type === "volcanoControl") return { id: tile.id, type: tile.type,
        highlightFeatures: tile.highlightFeatures ?? [],
        settings: { kind, identifier, ...tile.settings,
          useUncorrected: tile.settings.pValueMode === "uncorrected",
          source: tile.type === "volcano" ? "volcano" : "volcano_control" } };
      if (tile.type === "oraList") return { id: tile.id, type: tile.type, token: tile.state.completed?.result.evidenceToken ?? "" };
      if (tile.type !== "proteinBoxplot" && tile.type !== "proteinLineplot") return { id: tile.id, type: tile.type };
      const plotIdentifier = tile.sourceMode === "active" ? activeBoxplotTarget.identifier : tile.plotIdentifier ?? identifier;
      const settings = { kind, identifier: plotIdentifier, conditions: tile.conditions ?? (JSON.parse(linkedConditionsJson) as string[]), dataSource: tile.dataSource };
      return tile.type === "proteinBoxplot"
        ? { id: tile.id, type: tile.type, settings: { ...settings, protein: tile.sourceMode === "active" ? activeBoxplotTarget.protein || activeProtein : tile.protein.trim() } }
        : { id: tile.id, type: tile.type, settings: { ...settings, proteins: resolveLineplotProteins(tile, activeBoxplotTarget.protein || activeProtein, selectedProteins, lists) } };
    });
    onContextModeChange?.({ kind, identifier, linkedVolcanoId: sourceTile?.id ?? "", tiles: tiles.map(tile => tile.type), tileEvidence });
  }, [onContextModeChange, kind, identifier, tiles, sourceTile?.id,
    activeBoxplotTarget, activeProtein, linkedConditionsJson, selectedProteins, lists]);

  return (
    <div
      className={[
        "relative space-y-6 transition-[padding] duration-300",
        listSidebarOpen ? "pr-[20rem]" : "pr-0",
      ].join(" ")}
    >
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Global Controls</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <SelectField
            emptyLabel="No options"
            label="Dataset level"
            value={kind}
            options={kindOptions}
            onChange={(value) => setKind(value as AnnotationKind)}
          />
          <LocalizationCutoffField kind={kind} />
          <SelectField
            emptyLabel="No options"
            label="Identifier"
            value={identifier}
            options={(options?.availableIdentifiers ?? []).map((entry) => ({
              value: entry.key,
              label: entry.label,
            }))}
            onChange={(value) => setIdentifier(value as StatsIdentifier)}
          />
          <SelectField
            emptyLabel="No options"
            label="Linked plot source"
            value={sourceTile?.id ?? ""}
            options={tiles.flatMap((tile, index) => "settings" in tile ? [{
              value: tile.id,
              label: `Tile ${index + 1}: ${tile.type === "volcano" ? "Volcano" : "Volcano Control"} (${comparisonContrast(tile.settings.condition1, tile.settings.condition2)})`,
            }] : [])}
            onChange={setLinkedVolcanoId}
          />
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold text-slate-900">Analysis Canvas</h3>
          <div className="flex flex-wrap gap-2">
            <AssistantSelect aria-label="New tile type" data-assistant-permission="view"
              value={addType}
              onChange={(event) => setAddType(event.target.value as TileType)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="volcano">Volcano</option>
              <option value="volcanoControl">Volcano Control</option>
              <option value="proteinBoxplot">Protein Boxplot</option>
              <option value="proteinLineplot">Protein Lineplot</option>
              <option value="oraList">GO Enrichment (ORA, List)</option>
            </AssistantSelect>
            <AssistantCanvasButton effect="add"
              type="button"
              onClick={addTile}
              className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              + Add Plot
            </AssistantCanvasButton>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {tiles.map((tile, tileIndex) => (
            <CanvasTile key={tile.id} tile={tile} index={tileIndex} count={tiles.length}
              onMove={direction => moveTile(tile.id, direction)}
              onToggle={() => updateTile(tile.id, { ...tile, collapsed: !tile.collapsed })}
              onRemove={() => removeTile(tile.id)}>
              {(() => {
                if (tile.type === "volcano") {
                  const volcanoSettings = tile.settings;
                  const volcanoConditionsValid = conditionsValid(tile.settings, false);
                  const visibleVolcanoData = visibleResult(tile)?.data ?? null;
                  return (
                    <div>
                      <VolcanoBundleControls
                        kind={kind}
                        settings={volcanoSettings}
                        options={options}
                        onPairingSaved={async () => setOptions(await getStatisticalOptions(kind))}
                        onChange={(patch) => updateTile(tile.id, { ...tile, settings: { ...tile.settings, ...patch } })}
                      />
                      {volcanoConditionsValid ? (
                        <VolcanoPointsPanel
                          data={visibleVolcanoData}
                          highlightFeatures={tile.highlightFeatures}
                          error={visibleResult(tile)?.error}
                          onRetry={() => retryVolcano(tile.id)}
                          style={restoredVolcanoStyle(tile.style)}
                          onStyleChange={style => updateTile(tile.id, { ...tile, style })}
                          filename={`canvas_${tile.id}_volcano.svg`}
                          onPointClick={(protein, multi) => selectFromTile(tile, [protein], multi ? "toggle" : "single")}
                          onToggleProteins={proteins => selectFromTile(tile, proteins, "toggle")}
                          onClearSelection={clearSelection}
                          listNames={listNames}
                          onSelectListInPlot={name => selectFromTile(tile, toUnique(lists[name] ?? []), "list")}
                          selectedProteins={sourceTile?.id === tile.id ? selectedProteins : []}
                          activeProtein={sourceTile?.id === tile.id ? activeProtein : ""}
                          pValueThreshold={volcanoSettings.pValueThreshold}
                          useUncorrected={volcanoSettings.pValueMode === "uncorrected"}
                          log2fcThreshold={volcanoSettings.log2fcThreshold}
                          xAxisLabel={`log2 fold change (${comparisonContrast(volcanoSettings.condition1, volcanoSettings.condition2)})`}
                          onAddUpregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoSettings.condition1, volcanoSettings.condition2, "Upregulated"),
                              (visibleVolcanoData?.points ?? [])
                                .filter((point) => point.significance === "Upregulated")
                                .map(volcanoPointListLabel)
                            )
                          }
                          onAddDownregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoSettings.condition1, volcanoSettings.condition2, "Downregulated"),
                              (visibleVolcanoData?.points ?? [])
                                .filter((point) => point.significance === "Downregulated")
                                .map(volcanoPointListLabel)
                            )
                          }
                          upregulatedCount={visibleVolcanoData?.upregulatedCount ?? 0}
                          downregulatedCount={visibleVolcanoData?.downregulatedCount ?? 0}
                        />
                      ) : (
                        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                          {!(options?.availableDataSources ?? ["data"]).includes(volcanoSettings.dataSource)
                            ? `The selected ${DATA_SOURCE_LABELS[volcanoSettings.dataSource].toLowerCase()} is unavailable.`
                            : "Select two different conditions to display the volcano plot."}
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "volcanoControl") {
                  const volcanoControlSettings = tile.settings;
                  const volcanoControlConditionsValid = conditionsValid(tile.settings, true);
                  const visibleVolcanoControlData = visibleResult(tile)?.data ?? null;
                  return (
                    <div>
                      <VolcanoBundleControls
                        kind={kind}
                        settings={volcanoControlSettings}
                        options={options}
                        showControlConditions
                        onPairingSaved={async () => setOptions(await getStatisticalOptions(kind))}
                        onChange={(patch) => updateTile(tile.id, { ...tile, settings: { ...tile.settings, ...patch } })}
                      />
                      {volcanoControlConditionsValid ? (
                        <VolcanoPointsPanel
                          data={visibleVolcanoControlData}
                          highlightFeatures={tile.highlightFeatures}
                          error={visibleResult(tile)?.error}
                          onRetry={() => retryVolcano(tile.id)}
                          style={restoredVolcanoStyle(tile.style)}
                          onStyleChange={style => updateTile(tile.id, { ...tile, style })}
                          filename={`canvas_${tile.id}_volcano_control.svg`}
                          onPointClick={(protein, multi) => selectFromTile(tile, [protein], multi ? "toggle" : "single")}
                          onToggleProteins={proteins => selectFromTile(tile, proteins, "toggle")}
                          onClearSelection={clearSelection}
                          listNames={listNames}
                          onSelectListInPlot={name => selectFromTile(tile, toUnique(lists[name] ?? []), "list")}
                          selectedProteins={sourceTile?.id === tile.id ? selectedProteins : []}
                          activeProtein={sourceTile?.id === tile.id ? activeProtein : ""}
                          pValueThreshold={volcanoControlSettings.pValueThreshold}
                          useUncorrected={volcanoControlSettings.pValueMode === "uncorrected"}
                          log2fcThreshold={volcanoControlSettings.log2fcThreshold}
                          xAxisLabel={`log2 fold change (${comparisonContrast(volcanoControlSettings.condition1, volcanoControlSettings.condition2, volcanoControlSettings.condition1Control || "Control 1", volcanoControlSettings.condition2Control || "Control 2")})`}
                          onAddUpregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoControlSettings.condition1, volcanoControlSettings.condition2, "Upregulated"),
                              (visibleVolcanoControlData?.points ?? [])
                                .filter((point) => point.significance === "Upregulated")
                                .map(volcanoPointListLabel)
                            )
                          }
                          onAddDownregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoControlSettings.condition1, volcanoControlSettings.condition2, "Downregulated"),
                              (visibleVolcanoControlData?.points ?? [])
                                .filter((point) => point.significance === "Downregulated")
                                .map(volcanoPointListLabel)
                            )
                          }
                          upregulatedCount={visibleVolcanoControlData?.upregulatedCount ?? 0}
                          downregulatedCount={visibleVolcanoControlData?.downregulatedCount ?? 0}
                        />
                      ) : (
                        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                          {!(options?.availableDataSources ?? ["data"]).includes(volcanoControlSettings.dataSource)
                            ? `The selected ${DATA_SOURCE_LABELS[volcanoControlSettings.dataSource].toLowerCase()} is unavailable.`
                            : "Select four different conditions to display the control volcano plot."}
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "proteinBoxplot") {
                  const protein =
                    tile.sourceMode === "active"
                      ? activeBoxplotTarget.protein || activeProtein
                      : tile.protein.trim();
                  const plotIdentifier =
                    tile.sourceMode === "active"
                      ? activeBoxplotTarget.identifier
                      : tile.plotIdentifier ?? identifier;
                  const url = protein && plotSourceAvailable(tile.dataSource)
                    ? buildPlotUrl(`/api/plots/single-protein/${kind}/boxplot.png`, {
                        advanced: JSON.stringify(tile.advanced ?? {}),
                        dataSource: tile.dataSource,
                        kind,
                        protein,
                        conditions: tile.conditions ? JSON.stringify(tile.conditions) : linkedConditionsJson,
                        identifier: plotIdentifier,
                      })
                    : "";

                  return (
                    <div>

                      <div className="grid gap-3 lg:grid-cols-2">
                        <SelectField emptyLabel="No options" label="Data source" value={tile.dataSource} options={plotSourceOptions(tile.dataSource)}
                          onChange={value => updateTile(tile.id, { ...tile, dataSource: value as DataSource })} />
                        <SelectField
                          emptyLabel="No options"
                          label="Protein source"
                          value={tile.sourceMode}
                          options={[
                            { value: "active", label: "Active volcano selection" },
                            { value: "manual", label: "Manual input" },
                          ]}
                          onChange={(value) =>
                            updateTile(tile.id, {
                              ...tile,
                              sourceMode: value as BoxplotSourceMode,
                            })
                          }
                        />
                        {tile.sourceMode === "manual" ? (
                          <TextField
                            label="Protein or gene"
                            value={tile.protein}
                            onChange={(value) => updateTile(tile.id, { ...tile, protein: value })}
                          />
                        ) : (
                          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                            Active: {protein || "None"}
                          </div>
                        )}
                      </div>

                      {url ? (
                        <CanvasImagePlot advanced={tile.advanced} onChange={advanced => updateTile(tile.id, { ...tile, advanced })} conditions={options?.availableConditions ?? []} url={url} filename={`canvas_${tile.id}_boxplot`} boxplot alt="analysis boxplot" />
                      ) : (
                        <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                          {plotSourceAvailable(tile.dataSource) ? "Select or enter a protein to render the boxplot." : "The selected data source is unavailable."}
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "proteinLineplot") {
                  const proteins = resolveLineplotProteins(
                    tile,
                    activeBoxplotTarget.protein || activeProtein,
                    selectedProteins,
                    lists
                  );
                  const plotIdentifier =
                    tile.sourceMode === "active"
                      ? activeBoxplotTarget.identifier
                      : tile.plotIdentifier ?? identifier;
                  const url =
                    proteins.length > 0 && plotSourceAvailable(tile.dataSource)
                      ? buildPlotUrl(`/api/plots/single-protein/${kind}/lineplot.png`, {
                          advanced: JSON.stringify(tile.advanced ?? {}),
                          dataSource: tile.dataSource,
                          kind,
                          proteins: JSON.stringify(proteins),
                          conditions: tile.conditions ? JSON.stringify(tile.conditions) : linkedConditionsJson,
                          identifier: plotIdentifier,
                        })
                      : "";

                  return (
                    <div>

                      <div className="grid gap-3 lg:grid-cols-2">
                        <SelectField emptyLabel="No options" label="Data source" value={tile.dataSource} options={plotSourceOptions(tile.dataSource)}
                          onChange={value => updateTile(tile.id, { ...tile, dataSource: value as DataSource })} />
                        <SelectField
                          emptyLabel="No options"
                          label="Protein source"
                          value={tile.sourceMode}
                          options={[
                            { value: "active", label: "Active volcano selection" },
                            { value: "selected", label: "Current multi-selection" },
                            { value: "list", label: "Named list" },
                            { value: "manual", label: "Manual input" },
                          ]}
                          onChange={(value) =>
                            updateTile(tile.id, {
                              ...tile,
                              sourceMode: value as LineplotSourceMode,
                            })
                          }
                        />

                        {tile.sourceMode === "list" ? (
                          <SelectField
                            emptyLabel="No options"
                            label="List"
                            value={tile.listName}
                            options={listNames.map((name) => ({ value: name, label: name }))}
                            onChange={(value) => updateTile(tile.id, { ...tile, listName: value })}
                          />
                        ) : null}

                        {tile.sourceMode === "manual" ? (
                          <label className="block text-sm">
                            <span className="mb-1 block font-medium text-slate-700">Proteins or genes (comma, space, or newline)</span>
                            <AssistantTextarea
                              value={tile.proteinsText}
                              onChange={(event) => updateTile(tile.id, { ...tile, proteinsText: event.target.value })}
                              rows={2}
                              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
                            />
                          </label>
                        ) : null}

                        {tile.sourceMode === "active" ? (
                          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                            Active: {activeBoxplotTarget.protein || activeProtein || "None"}
                          </div>
                        ) : null}

                        {tile.sourceMode === "selected" ? (
                          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                            Selected proteins: {selectedProteins.length}
                          </div>
                        ) : null}
                      </div>

                      {url ? (
                        <>
                          <CanvasImagePlot advanced={tile.advanced} onChange={advanced => updateTile(tile.id, { ...tile, advanced })} conditions={options?.availableConditions ?? []} url={url} filename={`canvas_${tile.id}_lineplot`} alt="analysis lineplot" />
                          <LineplotUnmatchedNotice kind={kind} proteins={JSON.stringify(proteins)} identifier={plotIdentifier} dataSource={tile.dataSource} />
                        </>
                      ) : (
                        <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                          {plotSourceAvailable(tile.dataSource) ? "Provide proteins to render the lineplot." : "The selected data source is unavailable."}
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "oraList") {
                  return (
                    <OraListTile
                      state={tile.state}
                      onChange={updateOraState}
                      key={tile.id}
                      tileId={tile.id}
                      listNames={listNames}
                      lists={lists}
                    />
                  );
                }

                return null;
              })()}
            </CanvasTile>
          ))}

          {tiles.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
              No plots yet. Click <span className="font-semibold">+ Add Plot</span>.
            </div>
          ) : null}
        </div>
      </section>

      <aside
        className={[
          "fixed inset-y-0 right-0 z-40 flex h-screen w-80 shrink-0 flex-col border-l border-slate-200 bg-white transition-transform duration-300",
          listSidebarOpen ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        <div className="flex items-start justify-between p-5">
          <div className="pr-4">
            <div className="text-xl font-bold tracking-tight text-slate-900">Protein Lists</div>
          </div>

          <button
            type="button"
            onClick={() => onRightPanelChange?.("none")}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 shadow-sm transition hover:border-slate-300 hover:bg-white hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
            aria-label="Close list sidebar"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              className="h-4 w-4"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M6 6l12 12" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-28">
          <div className="space-y-4">
            <div className="grid gap-3">
              <TextField label="New list name" value={newListName} onChange={setNewListName} placeholder="list1" />
              <button
                type="button"
                onClick={createList}
                className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
              >
                Create List
              </button>
              <button
                type="button"
                onClick={addSelectedToActiveList}
                disabled={!activeList || selectedProteins.length === 0}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Add Selected ({selectedProteins.length})
              </button>
            </div>

            <SelectField
              emptyLabel="No options"
              label="Active list"
              value={activeList}
              options={listNames.map((name) => ({ value: name, label: name }))}
              onChange={(name) => {
                setActiveList(name);
                setActiveListDraft((lists[name] ?? []).join("\n"));
              }}
            />
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Active protein: <span className="font-medium text-slate-900">{activeProtein || "None"}</span>
            </div>

            <div>
              <label htmlFor={activeListFieldId} className="mb-1 block text-sm font-medium text-slate-700">Edit active list</label>
              <textarea
                id={activeListFieldId}
                value={activeListDraft}
                onChange={(event) => setActiveListDraft(event.target.value)}
                rows={6}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
              />
              <button
                type="button"
                onClick={saveActiveList}
                disabled={!activeList}
                className="mt-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Save List
              </button>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="grid gap-3">
                <SelectField
                  emptyLabel="No options"
                  label="List A"
                  value={opA}
                  options={listNames.map((name) => ({ value: name, label: name }))}
                  onChange={setOpA}
                />
                <SelectField
                  emptyLabel="No options"
                  label="Operation"
                  value={opMode}
                  options={[
                    { value: "intersection", label: "Intersection" },
                    { value: "union", label: "Union" },
                    { value: "a_minus_b", label: "A minus B" },
                    { value: "b_minus_a", label: "B minus A" },
                  ]}
                  onChange={(value) => setOpMode(value as "intersection" | "union" | "a_minus_b" | "b_minus_a")}
                />
                <SelectField
                  emptyLabel="No options"
                  label="List B"
                  value={opB}
                  options={listNames.map((name) => ({ value: name, label: name }))}
                  onChange={setOpB}
                />
                <TextField label="Result list" value={opTarget} onChange={setOpTarget} placeholder="list_result" />
                <button
                  type="button"
                  onClick={applyListOperation}
                  disabled={!opA || !opB || !opTarget.trim()}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                >
                  Create
                </button>
              </div>
            </div>
          </div>
        </div>
      </aside>

      {rightPanel === "none" ? (
        <button
          type="button"
          onClick={() => onRightPanelChange?.("list")}
          className={[
            "fixed z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition-all duration-300 hover:bg-slate-50",
            aiEnabled ? "bottom-16" : "bottom-4",
            "right-4",
          ].join(" ")}
          aria-label="Open list sidebar"
        >
          Lists
        </button>
      ) : null}
    </div>
  );
}

function CanvasTile({ tile, index, count, onMove, onToggle, onRemove, children }: {
  tile: AnalysisTile; index: number; count: number;
  onMove: (direction: -1 | 1) => void; onToggle: () => void; onRemove: () => void;
  children: React.ReactNode;
}) {
  const titles: Record<TileType, string> = {
    volcano: "Volcano", volcanoControl: "Volcano Control", proteinBoxplot: "Protein Boxplot",
    proteinLineplot: "Protein Lineplot", oraList: "GO Enrichment (ORA, List)",
  };
  const buttonClass = "rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100 disabled:opacity-40";
  return <section data-assistant-tile={tile.id} data-assistant-tile-type={tile.type} data-assistant-group={`Tile ${index + 1}: ${tile.type}`}
    className="rounded-xl border border-slate-200 bg-slate-50 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <button type="button" onClick={onToggle} aria-expanded={!tile.collapsed} aria-controls={`tile-body-${tile.id}`}
        aria-label={`${tile.collapsed ? "Expand" : "Collapse"} tile`}
        className="flex items-center gap-2 text-left text-sm font-semibold text-slate-800">
        <span aria-hidden="true">{tile.collapsed ? "▸" : "▾"}</span>{index + 1}. {titles[tile.type]}
      </button>
      <div className="flex gap-1">
        <button type="button" aria-label="Move tile up" title="Move up" disabled={index === 0} onClick={() => onMove(-1)} className={buttonClass}>↑</button>
        <button type="button" aria-label="Move tile down" title="Move down" disabled={index === count - 1} onClick={() => onMove(1)} className={buttonClass}>↓</button>
        <AssistantCanvasButton effect="remove" type="button" onClick={onRemove} className={buttonClass}>Remove</AssistantCanvasButton>
      </div>
    </div>
    <div id={`tile-body-${tile.id}`} hidden={tile.collapsed} className="mt-3">
      {tile.conditions ? <div className="mb-2 text-xs text-slate-600">Conditions: {tile.conditions.join(" → ")}</div> : null}
      {children}
    </div>
  </section>;
}

function OraListTile({
  state,
  onChange,
  tileId,
  listNames,
  lists,
}: {
  state: OraState;
  onChange: (id: string, patch: Partial<OraState>) => void;
  tileId: string;
  listNames: string[];
  lists: Record<string, string[]>;
}) {
  const genesFieldId = useId();
  const backgroundFieldId = useId();
  const { sourceMode, selectedListName, genesText, backgroundMode, backgroundText, organism,
    topN, minTermSize, maxTermSize, adjPValueCutoff, completed } = state;
  const setField = useCallback(<K extends keyof OraState,>(key: K, value: OraState[K]) =>
    onChange(tileId, { [key]: value }), [onChange, tileId]);
  const result = completed?.result ?? null;
  const pendingRequest = useRef<AbortController | null>(null);
  useEffect(() => () => pendingRequest.current?.abort(), []);

  function clearResult() {
    pendingRequest.current?.abort();
    pendingRequest.current = null;
    setField("completed", null);
    setRunning(false);
    setError(null);
  }
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (listNames.length === 0) {
      setField("selectedListName", "");
      return;
    }
    if (!selectedListName || !listNames.includes(selectedListName)) {
      setField("selectedListName", listNames[0]);
    }
  }, [listNames, selectedListName, setField]);

  const parsedGenes = useMemo(() => parseProteins(genesText), [genesText]);
  const parsedBackground = useMemo(() => parseProteins(backgroundText), [backgroundText]);

  async function runOra() {
    if (pendingRequest.current) return;
    const genes = sourceMode === "list" ? toUnique(lists[selectedListName] ?? []) : parsedGenes;
    if (genes.length === 0) {
      setError("Provide at least one gene in the input list.");
      setField("completed", null);
      return;
    }

    setRunning(true);
    setError(null);
    const controller = new AbortController();
    pendingRequest.current = controller;
    const request: ListEnrichmentRequest = {
      genes,
      backgroundMode,
      backgroundGenes: backgroundMode === "experiment" ? parsedBackground : [],
      topN: Math.max(1, Math.round(topN)),
      minTermSize: Math.max(1, Math.round(minTermSize)),
      maxTermSize: Math.max(1, Math.round(maxTermSize)),
      adjPValueCutoff: Math.max(1e-12, Math.min(1, adjPValueCutoff)),
      // Named rather than left to the schema default so the request says
      // which database it wants; an unknown key is refused by the backend.
      organism,
    };
    try {
      const response = await runListEnrichmentAnalysis(request, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setField("completed", { result: response, request, inputSource: sourceMode,
          namedList: sourceMode === "list" ? selectedListName : "" });
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setField("completed", null);
        setError(err instanceof Error ? err.message : "Failed to run list enrichment analysis");
      }
    } finally {
      if (pendingRequest.current === controller) {
        pendingRequest.current = null;
        setRunning(false);
      }
    }
  }

  function loadFromActiveList() {
    const genes = toUnique(lists[selectedListName] ?? []);
    setField("genesText", genes.join("\n"));
    setField("sourceMode", "manual");
  }

  const oraTermRows = completed && result ? oraListExportRows(completed, result) : [];
  const oraCsvUrl = oraTermRows.length ? csvDataUrl(rowsToQuotedCsv(oraTermRows, collectColumns(oraTermRows))) : null;

  return (
    <div>
      <div className="grid gap-3 lg:grid-cols-2">
        <SelectField
          emptyLabel="No options"
          label="Input source"
          value={sourceMode}
          options={[
            { value: "manual", label: "Manual list input" },
            { value: "list", label: "Named list from sidebar" },
          ]}
          onChange={(value) => setField("sourceMode", value as "manual" | "list")}
        />
        {sourceMode === "list" ? (
          <SelectField
            emptyLabel="No options"
            label="Named list"
            value={selectedListName}
            options={listNames.map((name) => ({ value: name, label: name }))}
            onChange={value => setField("selectedListName", value)}
          />
        ) : (
          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
            Genes in input: {parsedGenes.length}
          </div>
        )}
      </div>

      {sourceMode === "manual" ? (
        <div className="mt-3">
          <label htmlFor={genesFieldId} className="mb-1 block text-sm font-medium text-slate-700">Gene list input</label>
          <textarea
            id={genesFieldId}
            value={genesText}
            onChange={(event) => setField("genesText", event.target.value)}
            rows={6}
            placeholder="Paste genes separated by comma, space, or newline"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
          />
          {listNames.length > 0 ? (
            <button
              type="button"
              onClick={loadFromActiveList}
              className="mt-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
            >
              Load from named list
            </button>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
          Selected list size: {toUnique(lists[selectedListName] ?? []).length}
        </div>
      )}

      <div className="mt-3">
        <SelectField
          emptyLabel="No options"
          label="Organism"
          value={organism}
          options={ENRICHMENT_ORGANISM_OPTIONS}
          onChange={(value) => setField("organism", value as EnrichmentOrganism)}
        />
      </div>

      <div className="mt-3">
        <SelectField
          emptyLabel="No options"
          label="Background"
          value={backgroundMode}
          options={[
            { value: "experiment", label: "Custom tested-gene background (recommended)" },
            { value: "global", label: "All annotated genes (global)" },
          ]}
          onChange={(value) => setField("backgroundMode", value as "experiment" | "global")}
        />
      </div>

      {backgroundMode === "experiment" ? (
        <div className="mt-3">
          <label htmlFor={backgroundFieldId} className="mb-1 block text-sm font-medium text-slate-700">Tested-gene background</label>
          <textarea
            id={backgroundFieldId}
            value={backgroundText}
            onChange={(event) => setField("backgroundText", event.target.value)}
            rows={6}
            placeholder="Paste every gene that could have entered the input list"
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
          />
          <div className="mt-1 text-xs text-slate-600">Background genes: {parsedBackground.length}</div>
        </div>
      ) : (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Global background can overstate enrichment for experiment-derived lists.
        </div>
      )}

      <div className="mt-3 grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
        <NumberField label="Adj p-value cutoff" value={adjPValueCutoff} onChange={value => setField("adjPValueCutoff", value)} />
        <NumberField label="Top terms" value={topN} onChange={value => setField("topN", value)} />
        <NumberField label="Min term size" value={minTermSize} onChange={value => setField("minTermSize", value)} />
        <NumberField label="Max term size" value={maxTermSize} onChange={value => setField("maxTermSize", value)} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={runOra}
          disabled={running}
          className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {running ? "Running..." : "Run ORA"}
        </button>
        <button
          type="button"
          onClick={clearResult}
          className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
        >
          Clear Result
        </button>
      </div>

      {error ? (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      ) : null}

      {result ? (
        <div className="mt-3 space-y-3">
          <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
            Genes submitted: <span className="font-medium text-slate-900">{result.genes.length}</span> | Displayed terms:{" "}
            <span className="font-medium text-slate-900">{result.terms.length}</span> | Background:{" "}
            <span className="font-medium text-slate-900">{result.backgroundSize}</span> ({result.backgroundMode === "experiment" ? "custom" : "global"}) | Annotated:{" "}
            <span className="font-medium text-slate-900">{result.annotatedBackgroundSize}</span> | Organism:{" "}
            <span className="font-medium text-slate-900">{result.organism}</span> | Correction:{" "}
            <span className="font-medium text-slate-900">{result.correctionMethod}</span> | Terms in search space:{" "}
            <span className="font-medium text-slate-900">{result.testedTermCount}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {oraCsvUrl ? (
              <a
                href={oraCsvUrl}
                download="ora_terms.csv"
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
              >
                Download Terms CSV
              </a>
            ) : null}
            <a
              href={textDataUrl(result.genes)}
              download="ora_query_genes.txt"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
            >
              Download Query TXT
            </a>
            {result.backgroundMode === "experiment" ? (
              <a
                href={textDataUrl(result.backgroundGenes)}
                download="ora_background_genes.txt"
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
              >
                Download Background TXT
              </a>
            ) : null}
          </div>
          {result.warnings.length > 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {result.warnings.join(" ")}
            </div>
          ) : null}

          {result.terms.length > 0 ? (
            <div className="max-h-80 overflow-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full divide-y divide-slate-200 text-xs sm:text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold text-slate-700">Term</th>
                    <th className="px-3 py-2 text-left font-semibold text-slate-700">Source</th>
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">Adj. p-value</th>
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">Overlap / term</th>
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">GeneRatio</th>
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">Term coverage %</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {result.terms.map((term) => (
                    <tr key={`${term.source}:${term.termId}:${term.name}`}>
                      <td className="px-3 py-2 text-slate-900">{term.name}</td>
                      <td className="px-3 py-2 text-slate-700">{term.source || "-"}</td>
                      <td className="px-3 py-2 text-right text-slate-700">{term.adjPValue.toExponential(3)}</td>
                      <td className="px-3 py-2 text-right text-slate-700">
                        {term.intersectionSize}/{term.termSize}
                      </td>
                      <td className="px-3 py-2 text-right text-slate-700">
                        {term.intersectionSize}/{term.querySize} ({term.geneRatio.toFixed(3)})
                      </td>
                      <td className="px-3 py-2 text-right text-slate-700">{term.hitPercent.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-4 text-sm text-slate-500">
              No enrichment terms were found for the provided list and parameters.
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function VolcanoBundleControls({
  kind,
  settings,
  options,
  showControlConditions,
  onPairingSaved,
  onChange,
}: {
  kind: AnnotationKind;
  settings: VolcanoSettings | VolcanoControlSettings;
  options: StatisticalOptionsResponse | null;
  showControlConditions?: boolean;
  onPairingSaved: () => void | Promise<void>;
  onChange: (patch: Partial<VolcanoControlSettings>) => void;
}) {
  const isControl = showControlConditions === true;

  return (
    <div className="mb-3 rounded-xl border border-slate-200 bg-white p-3">
      <SelectField emptyLabel="No options" label="Data source" value={settings.dataSource}
        options={
          dataSourceOptions(options).some(option => option.value === settings.dataSource)
            ? dataSourceOptions(options)
            : [...dataSourceOptions(options), {
                value: settings.dataSource,
                label: `${DATA_SOURCE_LABELS[settings.dataSource]} (unavailable)`,
              }]
        }
        onChange={value => onChange({ dataSource: value as DataSource })} />
      {isControl ? (
        <div className="grid gap-3 lg:grid-cols-4">
          <SelectField
            emptyLabel="No options"
            label="Condition 1"
            value={settings.condition1}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1: value })}
          />
          <SelectField
            emptyLabel="No options"
            label="Condition 1 Control"
            value={(settings as VolcanoControlSettings).condition1Control}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1Control: value })}
          />
          <SelectField
            emptyLabel="No options"
            label="Condition 2"
            value={settings.condition2}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2: value })}
          />
          <SelectField
            emptyLabel="No options"
            label="Condition 2 Control"
            value={(settings as VolcanoControlSettings).condition2Control}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2Control: value })}
          />
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <SelectField
            emptyLabel="No options"
            label="Condition 1"
            value={settings.condition1}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1: value })}
          />
          <SelectField
            emptyLabel="No options"
            label="Condition 2"
            value={settings.condition2}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2: value })}
          />
        </div>
      )}

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <SelectField
          emptyLabel="No options"
          label="Test type"
          value={settings.testType}
          options={isControl ? CONTROL_TEST_TYPE_OPTIONS : TEST_TYPE_OPTIONS}
          onChange={(value) => onChange({ testType: value as StatsTestType })}
        />
        <SelectField
          emptyLabel="No options"
          label="P-value mode"
          value={settings.pValueMode}
          options={[
            { value: "corrected", label: "Adjusted p-values" },
            { value: "uncorrected", label: "Uncorrected p-values" },
          ]}
          onChange={(value) => onChange({ pValueMode: value as PValueMode })}
        />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <NumberField
          label="P-value threshold"
          value={settings.pValueThreshold}
          onChange={(value) => onChange({ pValueThreshold: value })}
        />
        <NumberField
          label="log2 FC threshold"
          value={settings.log2fcThreshold}
          onChange={(value) => onChange({ log2fcThreshold: value })}
        />
      </div>
      {settings.testType === "paired" ? (
        <PairingEditor
          kind={kind}
          condition1={settings.condition1}
          condition2={settings.condition2}
          samplesByCondition={options?.samplesByCondition ?? {}}
          pairIdsBySample={options?.pairIdsBySample ?? {}}
          onSaved={onPairingSaved}
        />
      ) : null}
    </div>
  );
}

function VolcanoPointsPanel({
  data,
  highlightFeatures = [],
  error,
  onRetry,
  style,
  onStyleChange,
  filename,
  onPointClick,
  onToggleProteins,
  onClearSelection,
  listNames,
  onSelectListInPlot,
  onAddUpregulatedToList,
  onAddDownregulatedToList,
  upregulatedCount,
  downregulatedCount,
  selectedProteins,
  activeProtein,
  pValueThreshold,
  useUncorrected,
  log2fcThreshold,
  xAxisLabel,
}: {
  data: AnalysisVolcanoResponse | null;
  highlightFeatures?: string[];
  error?: string;
  onRetry: () => void;
  style: VolcanoStyle;
  onStyleChange: (style: VolcanoStyle) => void;
  filename: string;
  onPointClick: (protein: string, multi: boolean) => void;
  onToggleProteins: (proteins: string[]) => void;
  onClearSelection: () => void;
  listNames: string[];
  onSelectListInPlot: (listName: string) => void;
  onAddUpregulatedToList: () => void;
  onAddDownregulatedToList: () => void;
  upregulatedCount: number;
  downregulatedCount: number;
  selectedProteins: string[];
  activeProtein: string;
  pValueThreshold: number;
  useUncorrected: boolean;
  log2fcThreshold: number;
  xAxisLabel: string;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(null);
  const [suppressClick, setSuppressClick] = useState(false);
  const [plotListName, setPlotListName] = useState("");

  const effectivePlotListName = listNames.includes(plotListName) ? plotListName : listNames[0] ?? "";

  if (!data) return <CanvasPlotStatus error={error} onRetry={onRetry} />;
  if (data.points.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
        No volcano points available.
      </div>
    );
  }

  const points = data.points;
  const selected = new Set(selectedProteins);
  const highlighted = new Set(highlightFeatures);

  const thresholdAbs = Math.abs(log2fcThreshold);
  const dataAbs = points.reduce((max, point) => Math.max(max, Math.abs(point.log2FC)), 0);
  const xAbs = Math.max(1, Math.max(dataAbs, thresholdAbs) * 1.1);
  const xMin = -xAbs;
  const xMax = xAbs;
  const hasDualThreshold = thresholdAbs > 0;

  const thresholdY = -Math.log10(Math.max(pValueThreshold, 1e-12));
  const yDataMax = points.reduce((max, point) => Math.max(max, point.negLog10P), 0);
  const yMax = Math.max(1, Math.max(yDataMax, thresholdY) * 1.1);

  const width = 900;
  const height = 460;
  const titleStyle = canvasText(style, "titleElement");
  const xLabelStyle = canvasText(style, "xLabelElement");
  const yLabelStyle = canvasText(style, "yLabelElement");
  const titleShown = style.titleVisible !== false && Boolean(titleStyle.text);
  const margin = { top: titleShown ? 42 : 20, right: 20, bottom: 40, left: 56 };
  const pAxisLabel = useUncorrected ? "-log10(p-value)" : "-log10(BH-adjusted p-value)";
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const mapX = (value: number) => margin.left + ((value - xMin) / (xMax - xMin || 1)) * innerWidth;
  const mapY = (value: number) => margin.top + innerHeight - (value / (yMax || 1)) * innerHeight;
  const xTicks = [xMin, xMin / 2, 0, xMax / 2, xMax];
  const yTicks = [0, yMax / 4, yMax / 2, (3 * yMax) / 4, yMax];
  const isDragging = multiSelectMode && dragStart !== null && dragCurrent !== null;
  const activePoint =
    !multiSelectMode && activeProtein
      ? points.find((point) => volcanoPointSelectionKey(point) === activeProtein) ?? null
      : null;
  const uniProtEntryId = activePoint
    ? activePoint.uniprotAccession ??
      extractUniProtAccession(
        activePoint.workflowLabel ?? "",
        activePoint.label ?? "",
        activePoint.selectionLabel ?? ""
      ) ??
      extractUniProtEntryName(
        activePoint.label ?? "",
        activePoint.workflowLabel ?? "",
        activePoint.selectionLabel ?? "",
        activePoint.geneLabel ?? ""
      )
    : null;
  const uniProtUrl = uniProtEntryId
    ? `https://www.uniprot.org/uniprotkb/${encodeURIComponent(uniProtEntryId)}/entry`
    : null;

  function pointerToSvg(event: React.PointerEvent<SVGSVGElement>): { x: number; y: number } | null {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const scaleX = width / rect.width;
    const scaleY = height / rect.height;
    return {
      x: (event.clientX - rect.left) * scaleX,
      y: (event.clientY - rect.top) * scaleY,
    };
  }

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (!multiSelectMode || event.button !== 0) return;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // no-op: pointer capture can fail in some environments
    }
    const point = pointerToSvg(event);
    if (!point) return;
    setDragStart(point);
    setDragCurrent(point);
    setSuppressClick(false);
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!multiSelectMode || !dragStart) return;
    const point = pointerToSvg(event);
    if (!point) return;
    setDragCurrent(point);
  }

  function handlePointerUp(event: React.PointerEvent<SVGSVGElement>) {
    if (!multiSelectMode || !dragStart || !dragCurrent) return;
    try {
      event.currentTarget.releasePointerCapture(event.pointerId);
    } catch {
      // no-op: pointer release can fail if capture was not set
    }
    const endPoint = pointerToSvg(event) ?? dragCurrent;
    const dx = Math.abs(endPoint.x - dragStart.x);
    const dy = Math.abs(endPoint.y - dragStart.y);
    const hasWindow = dx >= 4 || dy >= 4;

    if (hasWindow) {
      const minX = Math.min(dragStart.x, endPoint.x);
      const maxX = Math.max(dragStart.x, endPoint.x);
      const minY = Math.min(dragStart.y, endPoint.y);
      const maxY = Math.max(dragStart.y, endPoint.y);

      const hitLabels = toUnique(
        points
          .filter((point) => {
            const px = mapX(point.log2FC);
            const py = mapY(point.negLog10P);
            return px >= minX && px <= maxX && py >= minY && py <= maxY;
          })
          .map((point) => volcanoPointSelectionKey(point))
      );
      onToggleProteins(hitLabels);
      setSuppressClick(true);
    }

    setDragStart(null);
    setDragCurrent(null);
  }


  function downloadSvg() {
    if (!svgRef.current) return;
    const copy = svgRef.current.cloneNode(true) as SVGSVGElement;
    copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    copy.setAttribute("width", String(width));
    copy.setAttribute("height", String(height));
    copy.removeAttribute("class");
    copy.removeAttribute("style");
    copy.querySelectorAll('[data-selection-overlay]').forEach(node => node.remove());
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="space-y-2">
      <div className="flow-root">
      <button type="button" onClick={downloadSvg} disabled={isDragging}
        className="float-right mb-2 ml-3 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-50">Download SVG</button>
      <details>
        <summary className="w-fit cursor-pointer py-2 text-sm text-slate-700">Plot styling</summary>
        <div className="clear-both py-3">
            <AdvancedPlotOptions
              value={style}
              onChange={onStyleChange}
              visibleControls={CANVAS_VOLCANO_VISIBLE_CONTROLS}
            />
        </div>
      </details>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
        <span>Total rows: {data.totalRows}</span>
        <span>Up: {data.upregulatedCount}</span>
        <span>Down: {data.downregulatedCount}</span>
        <span>Not significant: {data.notSignificantCount}</span>
        <span>No p-value: {data.unavailableCount ?? 0}</span>
          <button
            type="button"
            onClick={() =>
              setMultiSelectMode((current) => {
              const next = !current;
              if (current && !next) {
                onClearSelection();
              }
              return next;
            })
          }
          className={`rounded-md border px-2 py-1 text-xs transition ${
            multiSelectMode
              ? "border-sky-300 bg-sky-50 text-sky-700"
              : "border-slate-300 bg-white text-slate-700 hover:bg-slate-100"
          }`}
        >
          Multi-select mode: {multiSelectMode ? "On" : "Off"}
        </button>
        <button
          type="button"
          onClick={onAddUpregulatedToList}
          disabled={upregulatedCount <= 0}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
        >
          Add all upregulated to list
        </button>
        <button
          type="button"
          onClick={onAddDownregulatedToList}
          disabled={downregulatedCount <= 0}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
        >
          Add all downregulated to list
        </button>
        <button
          type="button"
          onClick={onClearSelection}
          disabled={selectedProteins.length === 0}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
        >
          Deselect all
        </button>
        {multiSelectMode && listNames.length > 0 ? (
          <>
            <select
              value={effectivePlotListName}
              onChange={(event) => setPlotListName(event.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 outline-none focus:border-slate-900"
            >
              {listNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => {
                if (!effectivePlotListName) return;
                onSelectListInPlot(effectivePlotListName);
              }}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
            >
              Select list in plot
            </button>
          </>
        ) : null}
      </div>

      {!multiSelectMode && activePoint ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
          <div className="font-semibold text-slate-900">{activePoint.label}</div>
          <div>log2FC: {activePoint.log2FC.toFixed(4)}</div>
          <div>{pAxisLabel}: {activePoint.negLog10P.toFixed(4)}</div>
          <div>Significance: {activePoint.significance}</div>
          {activePoint.workflowLabel ? (
            <div>{data.kind === "phospho" ? "Site" : "Feature"}: {activePoint.workflowLabel}</div>
          ) : null}
          {activePoint.geneLabel ? <div>Gene: {activePoint.geneLabel}</div> : null}
          {uniProtUrl ? (
            <div>
              Uniprot:{" "}
              <a
                href={uniProtUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-700 underline"
              >
                Open protein entry ({uniProtEntryId})
              </a>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="overflow-auto rounded-xl border border-slate-200 bg-white">
        <svg
          ref={svgRef}
          fontFamily="Arial, sans-serif"
          viewBox={`0 0 ${width} ${height}`}
          className={`block w-full ${multiSelectMode ? "select-none" : ""}`}
          style={multiSelectMode ? { userSelect: "none", WebkitUserSelect: "none" } : undefined}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          <rect width={width} height={height} fill="white" />
          {titleShown ? (
            <text
              x={width / 2}
              y={24}
              textAnchor="middle"
              fontSize={titleStyle.size ?? 16}
              fill={titleStyle.color ?? "#334155"}
              fontWeight={titleStyle.bold ? "bold" : undefined}
              fontStyle={titleStyle.italic ? "italic" : undefined}
            >
              {titleStyle.text}
            </text>
          ) : null}
          {yTicks.map((tick, idx) => (
            <line
              key={`ygrid_${idx}`}
              x1={margin.left}
              y1={mapY(tick)}
              x2={margin.left + innerWidth}
              y2={mapY(tick)}
              stroke="#e2e8f0"
              strokeWidth={1}
            />
          ))}
          {xTicks.map((tick, idx) => (
            <line
              key={`xgrid_${idx}`}
              x1={mapX(tick)}
              y1={margin.top}
              x2={mapX(tick)}
              y2={margin.top + innerHeight}
              stroke={Math.abs(tick) < 1e-9 ? "#cbd5e1" : "#e2e8f0"}
              strokeWidth={1}
            />
          ))}

          <line x1={margin.left} y1={margin.top + innerHeight} x2={margin.left + innerWidth} y2={margin.top + innerHeight} stroke="#334155" strokeWidth={1} />
          <line x1={margin.left} y1={margin.top} x2={margin.left} y2={margin.top + innerHeight} stroke="#334155" strokeWidth={1} />

          {hasDualThreshold ? (
            <>
              <line
                x1={mapX(-thresholdAbs)}
                y1={margin.top}
                x2={mapX(-thresholdAbs)}
                y2={margin.top + innerHeight}
                stroke="#64748b"
                strokeWidth={1.3}
                strokeDasharray="5 4"
              />
              <line
                x1={mapX(thresholdAbs)}
                y1={margin.top}
                x2={mapX(thresholdAbs)}
                y2={margin.top + innerHeight}
                stroke="#64748b"
                strokeWidth={1.3}
                strokeDasharray="5 4"
              />
            </>
          ) : (
            <line
              x1={mapX(0)}
              y1={margin.top}
              x2={mapX(0)}
              y2={margin.top + innerHeight}
              stroke="#64748b"
              strokeWidth={1.3}
              strokeDasharray="5 4"
            />
          )}
          <line x1={margin.left} y1={mapY(thresholdY)} x2={margin.left + innerWidth} y2={mapY(thresholdY)} stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 4" />

          {points.map((point, index) => {
            const selectionId = volcanoPointSelectionKey(point);
            const isSelected = selected.has(selectionId) || highlighted.has(point.workflowLabel ?? point.label);
            const isActive = !multiSelectMode && activeProtein === selectionId;
            const pointStyle = canvasPointStyle(style, point.significance);
            const radius = pointStyle.radius + (multiSelectMode ? (isSelected ? 1 : 0) : isActive ? 1.7 : isSelected ? 0.8 : 0);
            const stroke = multiSelectMode
              ? isSelected
                ? "#334155"
                : "none"
              : isActive
              ? "#0f172a"
              : isSelected
              ? "#334155"
              : "none";
            const strokeWidth = multiSelectMode ? (isSelected ? 1.2 : 0) : isActive || isSelected ? 1.2 : 0;
            const title = !multiSelectMode && isActive
              ? [
                  `${point.label}`,
                  `log2FC=${point.log2FC.toFixed(4)}`,
                  `${pAxisLabel}=${point.negLog10P.toFixed(4)}`,
                  `Significance=${point.significance}`,
                  point.workflowLabel ? `Workflow=${point.workflowLabel}` : "",
                  point.geneLabel ? `Gene=${point.geneLabel}` : "",
                ]
                  .filter(Boolean)
                  .join("\n")
              : `${point.label} | log2FC=${point.log2FC.toFixed(3)} | ${pAxisLabel}=${point.negLog10P.toFixed(3)} | ${point.significance}`;

            return (
              <circle
                key={`${selectionId}_${index}`}
                cx={mapX(point.log2FC)}
                cy={mapY(point.negLog10P)}
                r={radius}
                fill={pointStyle.color}
                stroke={stroke}
                strokeWidth={strokeWidth}
                opacity={pointStyle.opacity}
                onPointerDown={(event) => {
                  if (!multiSelectMode) return;
                  event.stopPropagation();
                  event.preventDefault();
                }}
                onPointerUp={(event) => {
                  if (!multiSelectMode) return;
                  event.stopPropagation();
                  event.preventDefault();
                  onToggleProteins([selectionId]);
                  setSuppressClick(true);
                }}
                onClick={(event) => {
                  if (suppressClick) {
                    setSuppressClick(false);
                    return;
                  }
                  if (multiSelectMode) return;
                  onPointClick(selectionId, event.ctrlKey || event.metaKey || event.shiftKey);
                }}
                className="cursor-pointer"
              >
                <title>{title}</title>
              </circle>
            );
          })}

          {isDragging ? (
            <rect
              data-selection-overlay="true"
              x={Math.min(dragStart.x, dragCurrent.x)}
              y={Math.min(dragStart.y, dragCurrent.y)}
              width={Math.abs(dragCurrent.x - dragStart.x)}
              height={Math.abs(dragCurrent.y - dragStart.y)}
              fill="#0ea5e91a"
              stroke="#0284c7"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
          ) : null}

          {xTicks.map((tick, idx) => (
            <text
              key={`xtick_${idx}`}
              x={mapX(tick)}
              y={margin.top + innerHeight + 16}
              textAnchor="middle"
              fontSize="11"
              fill="#475569"
            >
              {tick.toFixed(1)}
            </text>
          ))}
          {yTicks.map((tick, idx) => (
            <text
              key={`ytick_${idx}`}
              x={margin.left - 8}
              y={mapY(tick) + 3}
              textAnchor="end"
              fontSize="11"
              fill="#475569"
            >
              {tick.toFixed(1)}
            </text>
          ))}

          <text
            x={width / 2}
            y={height - 10}
            textAnchor="middle"
            fontSize={xLabelStyle.size ?? 12}
            fill={xLabelStyle.color ?? "#334155"}
            fontWeight={xLabelStyle.bold ? "bold" : undefined}
            fontStyle={xLabelStyle.italic ? "italic" : undefined}
          >
            {xLabelStyle.text || xAxisLabel}
          </text>
          <text
            x={16}
            y={height / 2}
            textAnchor="middle"
            fontSize={yLabelStyle.size ?? 12}
            fill={yLabelStyle.color ?? "#334155"}
            fontWeight={yLabelStyle.bold ? "bold" : undefined}
            fontStyle={yLabelStyle.italic ? "italic" : undefined}
            transform={`rotate(-90 16 ${height / 2})`}
          >
            {yLabelStyle.text || pAxisLabel}
          </text>
        </svg>
      </div>
    </div>
  );
}

function CanvasPlotStatus({ error, onRetry }: { error?: string; onRetry: () => void }) {
  return <div role={error ? "alert" : "status"} className="my-3 rounded-xl border border-slate-200 bg-white px-4 py-5 text-sm text-slate-600">
    {error ? <><span>{error}</span><button type="button" onClick={onRetry}
      className="ml-3 rounded-lg border border-slate-300 px-3 py-1 text-slate-800">Retry plot</button></> : "Loading plot…"}
  </div>;
}

function CanvasImagePlot({ url, alt, ...options }: React.ComponentProps<typeof CanvasPlotOptions> & { alt: string }) {
  const [render, setRender] = useState<{ url: string; attempt: number; status: "loading" | "ready" | "error" }>(
    { url, attempt: 0, status: "loading" });
  if (render.url !== url) setRender({ url, attempt: 0, status: "loading" });
  const current = render.url === url;
  const ready = current && render.status === "ready";
  const imageUrl = current && render.attempt ? `${url}&_retry=${render.attempt}` : url;
  const status = (next: "ready" | "error") => setRender(previous =>
    previous.url === url && previous.attempt === render.attempt ? { ...previous, status: next } : previous);
  return <>
    <CanvasPlotOptions {...options} url={ready ? imageUrl : ""} />
    {!ready ? <CanvasPlotStatus error={current && render.status === "error" ? "Could not render this plot. Check the selection or try again." : undefined}
      onRetry={() => setRender(previous => ({ ...previous, attempt: previous.attempt + 1, status: "loading" }))} /> : null}
    <img key={imageUrl} src={imageUrl} alt={alt} onLoad={() => status("ready")} onError={() => status("error")}
      className={ready ? "mt-3 w-full rounded-xl border border-slate-200 bg-white" : "hidden"} />
  </>;
}

/** Names the canvas lineplot leaves out because no row has them, under the plot. */
function LineplotUnmatchedNotice({ kind, proteins, identifier, dataSource }: {
  kind: AnnotationKind; proteins: string; identifier: string; dataSource: string;
}) {
  const request = JSON.stringify([kind, proteins, identifier, dataSource]);
  const [result, setResult] = useState<{ request: string; notice: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getLineplotUnmatchedNotice(kind, { proteins, identifier, dataSource }, { signal: controller.signal })
      .then(notice => { if (!controller.signal.aborted) setResult({ request, notice }); })
      .catch(() => { /* The plot itself reports a failed request. */ });
    return () => controller.abort();
  }, [request, kind, proteins, identifier, dataSource]);
  const notice = result?.request === request ? result.notice : "";
  return notice
    ? <div role="status" className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{notice}</div>
    : null;
}

function CanvasPlotOptions({ advanced, onChange, conditions, url, filename, boxplot = false }: {
  advanced?: AdvancedPlotSettings;
  onChange: (value: AdvancedPlotSettings) => void;
  conditions: string[];
  url: string;
  filename: string;
  boxplot?: boolean;
}) {
  const [format, setFormat] = useState<PlotDownloadFormat>("png");
  return <div className="mt-3 flow-root">
    {url ? <div className="float-right mb-2 ml-3 flex items-center gap-2">
      <AssistantSelect aria-label="Export format" value={format}
        onChange={event => setFormat(event.target.value as PlotDownloadFormat)}
        className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm">
        {PLOT_DOWNLOAD_FORMAT_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </AssistantSelect>
      <a href={withPlotDownloadFormat(url, format)} download={`${filename}.${format}`}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">Download Plot</a>
    </div> : null}
    <details>
      <summary className="w-fit cursor-pointer py-2 text-sm text-slate-700">Plot styling</summary>
      <div className="clear-both pt-2">
        <AdvancedPlotOptions value={advanced ?? {}} onChange={onChange} conditionOptions={conditions}
          visibleControls={canvasImageVisibleControls(boxplot)} />
      </div>
    </details>
  </div>;
}
