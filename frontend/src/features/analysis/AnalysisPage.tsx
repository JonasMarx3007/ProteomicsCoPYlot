
import { useEffect, useMemo, useRef, useState } from "react";
import { buildPlotUrl, getStatisticalOptions, runAnalysisVolcanoData, runListEnrichmentAnalysis } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type {
  AnalysisVolcanoResponse,
  AnnotationKind,
  ListEnrichmentResultResponse,
  StatsIdentifier,
  StatsTestType,
  StatisticalOptionsResponse,
} from "../../lib/types";

type TileType = "volcano" | "volcanoControl" | "proteinBoxplot" | "proteinLineplot" | "gseaList";
type BoxplotSourceMode = "active" | "manual";
type LineplotSourceMode = "active" | "selected" | "list" | "manual";
type PValueMode = "corrected" | "uncorrected";

type VolcanoSettings = {
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

type AnalysisTile =
  | { id: string; type: "volcano" | "volcanoControl" }
  | { id: string; type: "proteinBoxplot"; sourceMode: BoxplotSourceMode; protein: string }
  | {
      id: string;
      type: "proteinLineplot";
      sourceMode: LineplotSourceMode;
      listName: string;
      proteinsText: string;
    }
  | { id: string; type: "gseaList" };

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
  return parseProteins(tile.proteinsText);
}

export default function AnalysisPage({
  rightPanel = "none",
  onRightPanelChange,
  aiEnabled = false,
}: {
  rightPanel?: "none" | "list" | "chat";
  onRightPanelChange?: (panel: "none" | "list" | "chat") => void;
  aiEnabled?: boolean;
}) {
  const { kindOptions } = useCurrentDatasetsSnapshot();
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<StatisticalOptionsResponse | null>(null);

  const [identifier, setIdentifier] = useState<StatsIdentifier>("workflow");
  const [volcanoSettings, setVolcanoSettings] = useState<VolcanoSettings>({
    condition1: "",
    condition2: "",
    testType: "unpaired",
    pValueThreshold: 0.05,
    log2fcThreshold: 1,
    pValueMode: "corrected",
  });
  const [volcanoControlSettings, setVolcanoControlSettings] = useState<VolcanoControlSettings>({
    condition1: "",
    condition2: "",
    condition1Control: "",
    condition2Control: "",
    testType: "unpaired",
    pValueThreshold: 0.05,
    log2fcThreshold: 1,
    pValueMode: "corrected",
  });

  const [tiles, setTiles] = useState<AnalysisTile[]>([]);
  const [addType, setAddType] = useState<TileType>("volcano");

  const [volcanoData, setVolcanoData] = useState<AnalysisVolcanoResponse | null>(null);
  const [volcanoControlData, setVolcanoControlData] = useState<AnalysisVolcanoResponse | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);

  const [activeProtein, setActiveProtein] = useState("");
  const [selectedProteins, setSelectedProteins] = useState<string[]>([]);

  const [lists, setLists] = useState<Record<string, string[]>>({});
  const [newListName, setNewListName] = useState("");
  const [activeList, setActiveList] = useState("");
  const [activeListDraft, setActiveListDraft] = useState("");
  const [opA, setOpA] = useState("");
  const [opB, setOpB] = useState("");
  const [opMode, setOpMode] = useState<"intersection" | "union" | "a_minus_b" | "b_minus_a">("intersection");
  const [opTarget, setOpTarget] = useState("");
  const listSidebarOpen = rightPanel === "list";

  const kindAvailable = kindOptions.some((option) => option.value === kind);
  const hasVolcanoTile = tiles.some((tile) => tile.type === "volcano");
  const hasVolcanoControlTile = tiles.some((tile) => tile.type === "volcanoControl");
  const volcanoConditionsValid =
    volcanoSettings.condition1.trim().length > 0 &&
    volcanoSettings.condition2.trim().length > 0 &&
    volcanoSettings.condition1 !== volcanoSettings.condition2;
  const volcanoControlConditionsValid = (() => {
    const values = [
      volcanoControlSettings.condition1,
      volcanoControlSettings.condition2,
      volcanoControlSettings.condition1Control,
      volcanoControlSettings.condition2Control,
    ]
      .map((value) => value.trim())
      .filter(Boolean);
    if (values.length < 4) return false;
    return new Set(values).size === 4;
  })();

  useEffect(() => {
    if (kindOptions.length === 0) return;
    if (!kindOptions.some((option) => option.value === kind)) {
      setKind(kindOptions[0].value as AnnotationKind);
    }
  }, [kindOptions, kind]);

  useEffect(() => {
    if (!kindAvailable) return;
    getStatisticalOptions(kind)
      .then((data) => {
        setOptions(data);
        setVolcanoSettings((current) => ({
          ...current,
          condition1: data.availableConditions.includes(current.condition1)
            ? current.condition1
            : data.availableConditions[0] ?? "",
          condition2: data.availableConditions.includes(current.condition2)
            ? current.condition2
            : data.availableConditions[0] ?? "",
        }));
        setVolcanoControlSettings((current) => ({
          ...current,
          condition1: data.availableConditions.includes(current.condition1)
            ? current.condition1
            : data.availableConditions[0] ?? "",
          condition2: data.availableConditions.includes(current.condition2)
            ? current.condition2
            : data.availableConditions[0] ?? "",
          condition1Control: data.availableConditions.includes(current.condition1Control)
            ? current.condition1Control
            : data.availableConditions[0] ?? "",
          condition2Control: data.availableConditions.includes(current.condition2Control)
            ? current.condition2Control
            : data.availableConditions[0] ?? "",
        }));
        setIdentifier((current) =>
          data.availableIdentifiers.some((item) => item.key === current)
            ? current
            : data.availableIdentifiers[0]?.key ?? "workflow"
        );
      })
      .catch(() => setOptions(null));
  }, [kind, kindAvailable]);

  useEffect(() => {
    if (!kindAvailable) return;
    if (!hasVolcanoTile && !hasVolcanoControlTile) return;

    setAnalysisError(null);
    const tasks: Promise<unknown>[] = [];

    if (hasVolcanoTile && volcanoConditionsValid) {
      tasks.push(
        runAnalysisVolcanoData({
          kind,
          source: "volcano",
          condition1: volcanoSettings.condition1,
          condition2: volcanoSettings.condition2,
          identifier,
          pValueThreshold: volcanoSettings.pValueThreshold,
          log2fcThreshold: volcanoSettings.log2fcThreshold,
          testType: volcanoSettings.testType,
          useUncorrected: volcanoSettings.pValueMode === "uncorrected",
        }).then(setVolcanoData)
      );
    } else if (hasVolcanoTile) {
      setVolcanoData(null);
    }

    if (hasVolcanoControlTile && volcanoControlConditionsValid) {
      tasks.push(
        runAnalysisVolcanoData({
          kind,
          source: "volcano_control",
          condition1: volcanoControlSettings.condition1,
          condition2: volcanoControlSettings.condition2,
          condition1Control: volcanoControlSettings.condition1Control,
          condition2Control: volcanoControlSettings.condition2Control,
          identifier,
          pValueThreshold: volcanoControlSettings.pValueThreshold,
          log2fcThreshold: volcanoControlSettings.log2fcThreshold,
          testType: volcanoControlSettings.testType,
          useUncorrected: volcanoControlSettings.pValueMode === "uncorrected",
        }).then(setVolcanoControlData)
      );
    } else if (hasVolcanoControlTile) {
      setVolcanoControlData(null);
    }

    Promise.all(tasks).catch((err) => {
      setAnalysisError(err instanceof Error ? err.message : "Failed to load analysis data");
    });
  }, [
    kindAvailable,
    kind,
    hasVolcanoTile,
    hasVolcanoControlTile,
    volcanoConditionsValid,
    volcanoControlConditionsValid,
    volcanoSettings.condition1,
    volcanoSettings.condition2,
    volcanoSettings.pValueThreshold,
    volcanoSettings.log2fcThreshold,
    volcanoSettings.testType,
    volcanoSettings.pValueMode,
    volcanoControlSettings.condition1,
    volcanoControlSettings.condition2,
    volcanoControlSettings.condition1Control,
    volcanoControlSettings.condition2Control,
    volcanoControlSettings.pValueThreshold,
    volcanoControlSettings.log2fcThreshold,
    volcanoControlSettings.testType,
    volcanoControlSettings.pValueMode,
    identifier,
  ]);

  const listNames = useMemo(() => Object.keys(lists).sort(), [lists]);

  useEffect(() => {
    if (listNames.length === 0) {
      setActiveList("");
      setActiveListDraft("");
      return;
    }

    if (!activeList || !(activeList in lists)) {
      setActiveList(listNames[0]);
      setActiveListDraft((lists[listNames[0]] ?? []).join("\n"));
      return;
    }

    setActiveListDraft((lists[activeList] ?? []).join("\n"));
  }, [listNames, activeList, lists]);

  function addTile() {
    if (addType === "proteinBoxplot") {
      setTiles((current) => [...current, { id: uid(), type: addType, sourceMode: "active", protein: "" }]);
      return;
    }
    if (addType === "proteinLineplot") {
      setTiles((current) => [
        ...current,
        {
          id: uid(),
          type: addType,
          sourceMode: "active",
          listName: "",
          proteinsText: "",
        },
      ]);
      return;
    }
    setTiles((current) => [...current, { id: uid(), type: addType }]);
  }

  function updateTile(id: string, nextTile: AnalysisTile) {
    setTiles((current) => current.map((tile) => (tile.id === id ? nextTile : tile)));
  }

  function removeTile(id: string) {
    setTiles((current) => current.filter((tile) => tile.id !== id));
  }

  function pointClick(protein: string, multi: boolean) {
    if (!multi && activeProtein === protein) {
      setActiveProtein("");
      setSelectedProteins([]);
      return;
    }
    setActiveProtein(protein);
    if (multi) {
      setSelectedProteins((current) =>
        current.includes(protein) ? current.filter((item) => item !== protein) : [...current, protein]
      );
      return;
    }
    setSelectedProteins([protein]);
  }

  function clearSelection() {
    setActiveProtein("");
    setSelectedProteins([]);
  }

  function selectListInPlot(listName: string) {
    const proteins = toUnique(lists[listName] ?? []);
    setSelectedProteins(proteins);
    setActiveProtein(proteins[0] ?? "");
  }

  function addProteinsToList(listName: string, proteins: string[]) {
    const cleaned = toUnique(proteins);
    setLists((current) => ({
      ...current,
      [listName]: toUnique([...(current[listName] ?? []), ...cleaned]),
    }));
    setActiveList(listName);
  }

  function toggleProteins(proteins: string[]) {
    const unique = toUnique(proteins);
    if (unique.length === 0) return;
    // Multi-select is binary only (selected/unselected), so clear any single-active state.
    setActiveProtein("");
    setSelectedProteins((current) => {
      const next = new Set(current);
      for (const protein of unique) {
        if (next.has(protein)) next.delete(protein);
        else next.add(protein);
      }
      return [...next];
    });
  }

  function createList() {
    const name = newListName.trim();
    if (!name) return;
    setLists((current) => ({ ...current, [name]: current[name] ?? [] }));
    setNewListName("");
    setActiveList(name);
  }

  function addSelectedToActiveList() {
    if (!activeList || selectedProteins.length === 0) return;
    setLists((current) => ({
      ...current,
      [activeList]: toUnique([...(current[activeList] ?? []), ...selectedProteins]),
    }));
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
    setOpTarget("");
  }

  const conditionsCsv = `${volcanoSettings.condition1},${volcanoSettings.condition2}`;

  useEffect(() => {
    clearSelection();
  }, [
    kind,
    identifier,
    volcanoSettings.condition1,
    volcanoSettings.condition2,
    volcanoSettings.testType,
    volcanoSettings.pValueThreshold,
    volcanoSettings.log2fcThreshold,
    volcanoSettings.pValueMode,
    volcanoControlSettings.condition1,
    volcanoControlSettings.condition2,
    volcanoControlSettings.condition1Control,
    volcanoControlSettings.condition2Control,
    volcanoControlSettings.testType,
    volcanoControlSettings.pValueThreshold,
    volcanoControlSettings.log2fcThreshold,
    volcanoControlSettings.pValueMode,
  ]);

  return (
    <div
      className={[
        "relative space-y-6 transition-[padding] duration-300",
        listSidebarOpen ? "pr-[20rem]" : "pr-0",
      ].join(" ")}
    >
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Analysis Pipeline</h2>
        <p className="mt-2 text-sm text-slate-600">
          Single-window analysis canvas with linked volcano selection and reusable protein lists.
        </p>
        {analysisError ? (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {analysisError}
          </div>
        ) : null}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Global Controls</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kind}
            options={kindOptions}
            onChange={(value) => setKind(value as AnnotationKind)}
          />
          <SelectField
            label="Identifier"
            value={identifier}
            options={(options?.availableIdentifiers ?? []).map((entry) => ({
              value: entry.key,
              label: entry.label,
            }))}
            onChange={(value) => setIdentifier(value as StatsIdentifier)}
          />
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-lg font-semibold text-slate-900">Analysis Canvas</h3>
          <div className="flex gap-2">
            <select
              value={addType}
              onChange={(event) => setAddType(event.target.value as TileType)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="volcano">Volcano</option>
              <option value="volcanoControl">Volcano Control</option>
              <option value="proteinBoxplot">Protein Boxplot</option>
              <option value="proteinLineplot">Protein Lineplot</option>
              <option value="gseaList">GSEA (List)</option>
            </select>
            <button
              type="button"
              onClick={addTile}
              className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              + Add Plot
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4">
          {tiles.map((tile) => {
                if (tile.type === "volcano") {
                  return (
                    <div key={tile.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-800">Volcano</div>
                        <button
                          type="button"
                          onClick={() => removeTile(tile.id)}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
                        >
                          Remove
                        </button>
                      </div>
                      <VolcanoBundleControls
                        settings={volcanoSettings}
                        options={options}
                        onChange={(patch) => setVolcanoSettings((current) => ({ ...current, ...patch }))}
                      />
                      {volcanoConditionsValid ? (
                        <VolcanoPointsPanel
                          data={volcanoData}
                          onPointClick={pointClick}
                          onToggleProteins={toggleProteins}
                          onClearSelection={clearSelection}
                          listNames={listNames}
                          onSelectListInPlot={selectListInPlot}
                          selectedProteins={selectedProteins}
                          activeProtein={activeProtein}
                          pValueThreshold={volcanoSettings.pValueThreshold}
                          log2fcThreshold={volcanoSettings.log2fcThreshold}
                          xAxisLabel={`log2 Fold Change (${volcanoSettings.condition2 || "Condition 2"} vs ${volcanoSettings.condition1 || "Condition 1"})`}
                          onAddUpregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoSettings.condition1, volcanoSettings.condition2, "Upregulated"),
                              (volcanoData?.points ?? [])
                                .filter((point) => point.significance === "Upregulated")
                                .map((point) => point.selectionLabel || point.label)
                            )
                          }
                          onAddDownregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoSettings.condition1, volcanoSettings.condition2, "Downregulated"),
                              (volcanoData?.points ?? [])
                                .filter((point) => point.significance === "Downregulated")
                                .map((point) => point.selectionLabel || point.label)
                            )
                          }
                          upregulatedCount={volcanoData?.upregulatedCount ?? 0}
                          downregulatedCount={volcanoData?.downregulatedCount ?? 0}
                        />
                      ) : (
                        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                          Select two different conditions to display the volcano plot.
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "volcanoControl") {
                  return (
                    <div key={tile.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-800">Volcano Control</div>
                        <button
                          type="button"
                          onClick={() => removeTile(tile.id)}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
                        >
                          Remove
                        </button>
                      </div>
                      <VolcanoBundleControls
                        settings={volcanoControlSettings}
                        options={options}
                        showControlConditions
                        onChange={(patch) => setVolcanoControlSettings((current) => ({ ...current, ...patch }))}
                      />
                      {volcanoControlConditionsValid ? (
                        <VolcanoPointsPanel
                          data={volcanoControlData}
                          onPointClick={pointClick}
                          onToggleProteins={toggleProteins}
                          onClearSelection={clearSelection}
                          listNames={listNames}
                          onSelectListInPlot={selectListInPlot}
                          selectedProteins={selectedProteins}
                          activeProtein={activeProtein}
                          pValueThreshold={volcanoControlSettings.pValueThreshold}
                          log2fcThreshold={volcanoControlSettings.log2fcThreshold}
                          xAxisLabel={`log2 Fold Change [(${volcanoControlSettings.condition2 || "Condition 2"} vs ${volcanoControlSettings.condition1 || "Condition 1"}) - (${volcanoControlSettings.condition2Control || "Control 2"} vs ${volcanoControlSettings.condition1Control || "Control 1"})]`}
                          onAddUpregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoControlSettings.condition1, volcanoControlSettings.condition2, "Upregulated"),
                              (volcanoControlData?.points ?? [])
                                .filter((point) => point.significance === "Upregulated")
                                .map((point) => point.selectionLabel || point.label)
                            )
                          }
                          onAddDownregulatedToList={() =>
                            addProteinsToList(
                              buildDirectionListName(volcanoControlSettings.condition1, volcanoControlSettings.condition2, "Downregulated"),
                              (volcanoControlData?.points ?? [])
                                .filter((point) => point.significance === "Downregulated")
                                .map((point) => point.selectionLabel || point.label)
                            )
                          }
                          upregulatedCount={volcanoControlData?.upregulatedCount ?? 0}
                          downregulatedCount={volcanoControlData?.downregulatedCount ?? 0}
                        />
                      ) : (
                        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                          Select four different conditions to display the control volcano plot.
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "proteinBoxplot") {
                  const protein = tile.sourceMode === "active" ? activeProtein : tile.protein.trim();
                  const url = protein
                    ? buildPlotUrl("/api/analysis/boxplot.png", {
                        kind,
                        protein,
                        conditions: conditionsCsv,
                        identifier,
                      })
                    : "";

                  return (
                    <div key={tile.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-800">Protein Boxplot</div>
                        <button
                          type="button"
                          onClick={() => removeTile(tile.id)}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
                        >
                          Remove
                        </button>
                      </div>

                      <div className="grid gap-3 lg:grid-cols-2">
                        <SelectField
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
                            Active: {activeProtein || "None"}
                          </div>
                        )}
                      </div>

                      {url ? (
                        <img
                          src={url}
                          alt="analysis boxplot"
                          className="mt-3 w-full rounded-xl border border-slate-200 bg-white"
                        />
                      ) : (
                        <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                          Select or enter a protein to render the boxplot.
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "proteinLineplot") {
                  const proteins = resolveLineplotProteins(tile, activeProtein, selectedProteins, lists);
                  const url =
                    proteins.length > 0
                      ? buildPlotUrl("/api/analysis/lineplot.png", {
                          kind,
                          proteins: proteins.join(","),
                          conditions: conditionsCsv,
                          identifier,
                        })
                      : "";

                  return (
                    <div key={tile.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-2 flex items-center justify-between">
                        <div className="text-sm font-semibold text-slate-800">Protein Lineplot</div>
                        <button
                          type="button"
                          onClick={() => removeTile(tile.id)}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
                        >
                          Remove
                        </button>
                      </div>

                      <div className="grid gap-3 lg:grid-cols-2">
                        <SelectField
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
                            label="List"
                            value={tile.listName}
                            options={listNames.map((name) => ({ value: name, label: name }))}
                            onChange={(value) => updateTile(tile.id, { ...tile, listName: value })}
                          />
                        ) : null}

                        {tile.sourceMode === "manual" ? (
                          <TextField
                            label="Proteins or genes (comma, space, or newline)"
                            value={tile.proteinsText}
                            onChange={(value) => updateTile(tile.id, { ...tile, proteinsText: value })}
                          />
                        ) : null}

                        {tile.sourceMode === "active" ? (
                          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                            Active: {activeProtein || "None"}
                          </div>
                        ) : null}

                        {tile.sourceMode === "selected" ? (
                          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                            Selected proteins: {selectedProteins.length}
                          </div>
                        ) : null}
                      </div>

                      {url ? (
                        <img
                          src={url}
                          alt="analysis lineplot"
                          className="mt-3 w-full rounded-xl border border-slate-200 bg-white"
                        />
                      ) : (
                        <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                          Provide proteins to render the lineplot.
                        </div>
                      )}
                    </div>
                  );
                }

                if (tile.type === "gseaList") {
                  return (
                    <GseaListTile
                      key={tile.id}
                      tileId={tile.id}
                      onRemove={removeTile}
                      listNames={listNames}
                      lists={lists}
                    />
                  );
                }

                return null;
              })}

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
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            aria-label="Close list sidebar"
          >
            X
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
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
              label="Active list"
              value={activeList}
              options={listNames.map((name) => ({ value: name, label: name }))}
              onChange={setActiveList}
            />
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              Active protein: <span className="font-medium text-slate-900">{activeProtein || "None"}</span>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">Edit active list</label>
              <textarea
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
                  label="List A"
                  value={opA}
                  options={listNames.map((name) => ({ value: name, label: name }))}
                  onChange={setOpA}
                />
                <SelectField
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

      <button
        type="button"
        onClick={() => onRightPanelChange?.(listSidebarOpen ? "none" : "list")}
        className={[
          "fixed z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition-all duration-300 hover:bg-slate-50",
          aiEnabled ? "bottom-16" : "bottom-4",
          listSidebarOpen ? "right-[21rem]" : "right-4",
        ].join(" ")}
        aria-label="Toggle list sidebar"
      >
        Lists
      </button>
    </div>
  );
}

function GseaListTile({
  tileId,
  onRemove,
  listNames,
  lists,
}: {
  tileId: string;
  onRemove: (id: string) => void;
  listNames: string[];
  lists: Record<string, string[]>;
}) {
  const [sourceMode, setSourceMode] = useState<"manual" | "list">("manual");
  const [selectedListName, setSelectedListName] = useState("");
  const [genesText, setGenesText] = useState("");
  const [topN, setTopN] = useState(10);
  const [minTermSize, setMinTermSize] = useState(20);
  const [maxTermSize, setMaxTermSize] = useState(300);
  const [result, setResult] = useState<ListEnrichmentResultResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (listNames.length === 0) {
      setSelectedListName("");
      return;
    }
    if (!selectedListName || !listNames.includes(selectedListName)) {
      setSelectedListName(listNames[0]);
    }
  }, [listNames, selectedListName]);

  const parsedGenes = useMemo(() => parseProteins(genesText), [genesText]);

  async function runGsea() {
    const genes = sourceMode === "list" ? toUnique(lists[selectedListName] ?? []) : parsedGenes;
    if (genes.length === 0) {
      setError("Provide at least one gene in the input list.");
      setResult(null);
      return;
    }

    setRunning(true);
    setError(null);
    try {
      const response = await runListEnrichmentAnalysis({
        genes,
        topN: Math.max(1, Math.round(topN)),
        minTermSize: Math.max(1, Math.round(minTermSize)),
        maxTermSize: Math.max(1, Math.round(maxTermSize)),
      });
      setResult(response);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Failed to run list enrichment analysis");
    } finally {
      setRunning(false);
    }
  }

  function loadFromActiveList() {
    const genes = toUnique(lists[selectedListName] ?? []);
    setGenesText(genes.join("\n"));
    setSourceMode("manual");
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold text-slate-800">GSEA (List)</div>
        <button
          type="button"
          onClick={() => onRemove(tileId)}
          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
        >
          Remove
        </button>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <SelectField
          label="Input source"
          value={sourceMode}
          options={[
            { value: "manual", label: "Manual list input" },
            { value: "list", label: "Named list from sidebar" },
          ]}
          onChange={(value) => setSourceMode(value as "manual" | "list")}
        />
        {sourceMode === "list" ? (
          <SelectField
            label="Named list"
            value={selectedListName}
            options={listNames.map((name) => ({ value: name, label: name }))}
            onChange={setSelectedListName}
          />
        ) : (
          <div className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
            Genes in input: {parsedGenes.length}
          </div>
        )}
      </div>

      {sourceMode === "manual" ? (
        <div className="mt-3">
          <label className="mb-1 block text-sm font-medium text-slate-700">Gene list input</label>
          <textarea
            value={genesText}
            onChange={(event) => setGenesText(event.target.value)}
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

      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <NumberField label="Top terms" value={topN} onChange={setTopN} />
        <NumberField label="Min term size" value={minTermSize} onChange={setMinTermSize} />
        <NumberField label="Max term size" value={maxTermSize} onChange={setMaxTermSize} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={runGsea}
          disabled={running}
          className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
        >
          {running ? "Running..." : "Run GSEA"}
        </button>
        <button
          type="button"
          onClick={() => {
            setResult(null);
            setError(null);
          }}
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
            Genes used: <span className="font-medium text-slate-900">{result.genes.length}</span> | Terms found:{" "}
            <span className="font-medium text-slate-900">{result.terms.length}</span>
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
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">Hits</th>
                    <th className="px-3 py-2 text-right font-semibold text-slate-700">Hit %</th>
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
  settings,
  options,
  showControlConditions,
  onChange,
}: {
  settings: VolcanoSettings | VolcanoControlSettings;
  options: StatisticalOptionsResponse | null;
  showControlConditions?: boolean;
  onChange: (patch: Partial<VolcanoControlSettings>) => void;
}) {
  const isControl = showControlConditions === true;

  return (
    <div className="mb-3 rounded-xl border border-slate-200 bg-white p-3">
      {isControl ? (
        <div className="grid gap-3 lg:grid-cols-4">
          <SelectField
            label="Condition 1"
            value={settings.condition1}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1: value })}
          />
          <SelectField
            label="Condition 1 Control"
            value={(settings as VolcanoControlSettings).condition1Control}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1Control: value })}
          />
          <SelectField
            label="Condition 2"
            value={settings.condition2}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2: value })}
          />
          <SelectField
            label="Condition 2 Control"
            value={(settings as VolcanoControlSettings).condition2Control}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2Control: value })}
          />
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <SelectField
            label="Condition 1"
            value={settings.condition1}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition1: value })}
          />
          <SelectField
            label="Condition 2"
            value={settings.condition2}
            options={(options?.availableConditions ?? []).map((value) => ({ value, label: value }))}
            onChange={(value) => onChange({ condition2: value })}
          />
        </div>
      )}

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <SelectField
          label="Test type"
          value={settings.testType}
          options={[
            { value: "unpaired", label: "Unpaired" },
            { value: "paired", label: "Paired" },
          ]}
          onChange={(value) => onChange({ testType: value as StatsTestType })}
        />
        <SelectField
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
    </div>
  );
}

function VolcanoPointsPanel({
  data,
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
  log2fcThreshold,
  xAxisLabel,
}: {
  data: AnalysisVolcanoResponse | null;
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
  log2fcThreshold: number;
  xAxisLabel: string;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragCurrent, setDragCurrent] = useState<{ x: number; y: number } | null>(null);
  const [suppressClick, setSuppressClick] = useState(false);
  const [plotListName, setPlotListName] = useState("");

  useEffect(() => {
    if (listNames.length === 0) {
      setPlotListName("");
      return;
    }
    if (!plotListName || !listNames.includes(plotListName)) {
      setPlotListName(listNames[0]);
    }
  }, [listNames, plotListName]);

  if (!data || data.points.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
        No volcano points available.
      </div>
    );
  }

  const points = data.points;
  const xs = points.map((point) => point.log2FC);
  const ys = points.map((point) => point.negLog10P);

  const thresholdAbs = Math.abs(log2fcThreshold);
  const dataAbs = Math.max(Math.abs(Math.min(...xs)), Math.abs(Math.max(...xs)));
  const xAbs = Math.max(1, Math.max(dataAbs, thresholdAbs) * 1.1);
  const xMin = -xAbs;
  const xMax = xAbs;
  const hasDualThreshold = thresholdAbs > 0;

  const thresholdY = -Math.log10(Math.max(pValueThreshold, 1e-12));
  const yDataMax = Math.max(...ys, 0);
  const yMax = Math.max(1, Math.max(yDataMax, thresholdY) * 1.1);

  const width = 900;
  const height = 460;
  const margin = { top: 20, right: 20, bottom: 40, left: 56 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const mapX = (value: number) => margin.left + ((value - xMin) / (xMax - xMin || 1)) * innerWidth;
  const mapY = (value: number) => margin.top + innerHeight - (value / (yMax || 1)) * innerHeight;
  const xTicks = [xMin, xMin / 2, 0, xMax / 2, xMax];
  const yTicks = [0, yMax / 4, yMax / 2, (3 * yMax) / 4, yMax];
  const isDragging = multiSelectMode && dragStart !== null && dragCurrent !== null;
  const activePoint =
    !multiSelectMode && activeProtein
      ? points.find((point) => (point.selectionLabel || point.label) === activeProtein) ?? null
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
          .map((point) => point.selectionLabel || point.label)
      );
      onToggleProteins(hitLabels);
      setSuppressClick(true);
    }

    setDragStart(null);
    setDragCurrent(null);
  }

  function pointColor(significance: string) {
    const lower = significance.toLowerCase();
    if (lower.includes("up")) return "#dc2626";
    if (lower.includes("down")) return "#2563eb";
    return "#94a3b8";
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
        <span>Total rows: {data.totalRows}</span>
        <span>Up: {data.upregulatedCount}</span>
        <span>Down: {data.downregulatedCount}</span>
        <span>Not significant: {data.notSignificantCount}</span>
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
              value={plotListName}
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
                if (!plotListName) return;
                onSelectListInPlot(plotListName);
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
          <div>-log10(p-value): {activePoint.negLog10P.toFixed(4)}</div>
          <div>Significance: {activePoint.significance}</div>
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
          viewBox={`0 0 ${width} ${height}`}
          className={`min-w-[42rem] ${multiSelectMode ? "select-none" : ""}`}
          style={multiSelectMode ? { userSelect: "none", WebkitUserSelect: "none" } : undefined}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
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
            const selectionId = point.selectionLabel || point.label;
            const isSelected = selectedProteins.includes(selectionId);
            const isActive = !multiSelectMode && activeProtein === selectionId;
            const radius = multiSelectMode ? (isSelected ? 3.8 : 2.8) : isActive ? 4.5 : isSelected ? 3.6 : 2.8;
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
                  `-log10(p)=${point.negLog10P.toFixed(4)}`,
                  `Significance=${point.significance}`,
                  point.workflowLabel ? `Workflow=${point.workflowLabel}` : "",
                  point.geneLabel ? `Gene=${point.geneLabel}` : "",
                ]
                  .filter(Boolean)
                  .join("\n")
              : `${point.label} | log2FC=${point.log2FC.toFixed(3)} | -log10(p)=${point.negLog10P.toFixed(3)} | ${point.significance}`;

            return (
              <circle
                key={`${selectionId}_${index}`}
                cx={mapX(point.log2FC)}
                cy={mapY(point.negLog10P)}
                r={radius}
                fill={pointColor(point.significance)}
                stroke={stroke}
                strokeWidth={strokeWidth}
                opacity={0.9}
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

          <text x={width / 2} y={height - 10} textAnchor="middle" fontSize="12" fill="#334155">{xAxisLabel}</text>
          <text x={16} y={height / 2} textAnchor="middle" fontSize="12" fill="#334155" transform={`rotate(-90 16 ${height / 2})`}>
            -log10(p-value)
          </text>
        </svg>
      </div>
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.length === 0 ? <option value="">No options</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      <input
        type="text"
        value={String(value)}
        onChange={(event) => {
          const parsed = Number(event.target.value.replace(",", "."));
          if (Number.isFinite(parsed)) onChange(parsed);
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}
