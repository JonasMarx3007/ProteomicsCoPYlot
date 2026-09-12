import type {
  AnnotationKind,
  AdvancedPlotSettings,
  CurrentDatasetsResponse,
  SummaryReportContext,
  SummaryVolcanoEntry,
} from "./types";
import { getAdvancedPlotMode, getAdvancedPlotSettingsByKey } from "./appSettings";
import { readPersistedUiState } from "./persistedUiState";

const QC_SETTINGS_KEY = "pcopylot.report.qcSettings.v1";
const VOLCANO_LOG_KEY = "pcopylot.report.volcanoLog.v1";
const REPORT_SCOPE_KEY = "pcopylot.report.datasetScope.v1";

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = globalThis.sessionStorage?.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as T;
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    globalThis.sessionStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage write failures (private mode, quota, etc.).
  }
}

function readRaw(key: string): string | null {
  try {
    return globalThis.sessionStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function writeRaw(key: string, value: string) {
  try {
    globalThis.sessionStorage?.setItem(key, value);
  } catch {
    // Ignore storage write failures (private mode, quota, etc.).
  }
}

function removeKey(key: string) {
  try {
    globalThis.sessionStorage?.removeItem(key);
  } catch {
    // Ignore storage write failures (private mode, quota, etc.).
  }
}

function datasetScopeToken(
  datasets: CurrentDatasetsResponse | null
): string {
  if (!datasets) return "none";
  const pkg = `package:${datasets.activePackage || "Data"}`;
  const metadataProfile = `metadata:${datasets.activeMetadataProfile || "Metadata"}`;
  const protein = datasets.protein
    ? `protein:${datasets.protein.filename}:${datasets.protein.rows}:${datasets.protein.columns}`
    : "protein:none";
  const phospho = datasets.phospho
    ? `phospho:${datasets.phospho.filename}:${datasets.phospho.rows}:${datasets.phospho.columns}`
    : "phospho:none";
  const phosprot = datasets.phosprot
    ? `phosprot:${datasets.phosprot.filename}:${datasets.phosprot.rows}:${datasets.phosprot.columns}`
    : "phosprot:none";
  const peptide = datasets.peptide
    ? `peptide:${datasets.peptide.filename}:${datasets.peptide.path}`
    : "peptide:none";
  return [pkg, metadataProfile, protein, phospho, phosprot, peptide].join("|");
}

export function clearSummaryReportState() {
  removeKey(VOLCANO_LOG_KEY);
  removeKey(QC_SETTINGS_KEY);
}

export function syncSummaryReportStateWithDatasets(
  datasets: CurrentDatasetsResponse | null
) {
  const token = datasetScopeToken(datasets);
  const previous = readRaw(REPORT_SCOPE_KEY);
  if (previous == null) {
    clearSummaryReportState();
    writeRaw(REPORT_SCOPE_KEY, token);
    return;
  }
  if (previous === token) return;
  clearSummaryReportState();
  writeRaw(REPORT_SCOPE_KEY, token);
}

export function saveQcReportSettings(
  kind: AnnotationKind | "peptide",
  settings: Record<string, unknown>
) {
  const all = readJson<Record<string, Record<string, unknown>>>(
    QC_SETTINGS_KEY,
    {}
  );
  all[kind] = { ...all[kind], ...settings };
  writeJson(QC_SETTINGS_KEY, all);
}

export function listVolcanoReportEntries(): SummaryVolcanoEntry[] {
  return readJson<SummaryVolcanoEntry[]>(VOLCANO_LOG_KEY, []);
}

function readAdvancedUiState(key: string): Record<string, AdvancedPlotSettings> {
  const state = readPersistedUiState<Record<string, unknown>>(key, {});
  const advanced = state.advanced;
  return advanced && typeof advanced === "object" && !Array.isArray(advanced)
    ? (advanced as Record<string, AdvancedPlotSettings>)
    : {};
}

function normalizeDataSource(value: unknown): "data" | "imputed" {
  if (String(value ?? "").trim().toLowerCase() === "data") return "data";
  return "imputed";
}

function normalizeEntry(entry: SummaryVolcanoEntry): SummaryVolcanoEntry {
  return {
    ...entry,
    dataSource: normalizeDataSource(entry.dataSource),
    highlightTerms: [...entry.highlightTerms].map((item) => item.trim()).filter(Boolean),
    condition1Control: entry.condition1Control ?? null,
    condition2Control: entry.condition2Control ?? null,
  };
}

function isSameVolcanoEntry(a: SummaryVolcanoEntry, b: SummaryVolcanoEntry): boolean {
  const left = normalizeEntry(a);
  const right = normalizeEntry(b);
  if (left.kind !== right.kind) return false;
  if (left.control !== right.control) return false;
  if (left.dataSource !== right.dataSource) return false;
  if (left.condition1 !== right.condition1) return false;
  if (left.condition2 !== right.condition2) return false;
  if ((left.condition1Control ?? "") !== (right.condition1Control ?? "")) return false;
  if ((left.condition2Control ?? "") !== (right.condition2Control ?? "")) return false;
  if (left.identifier !== right.identifier) return false;
  if (left.testType !== right.testType) return false;
  if (left.useUncorrected !== right.useUncorrected) return false;
  if (left.pValueThreshold !== right.pValueThreshold) return false;
  if (left.log2fcThreshold !== right.log2fcThreshold) return false;
  if (left.highlightTerms.length !== right.highlightTerms.length) return false;
  return left.highlightTerms.every((item, index) => item === right.highlightTerms[index]);
}

export function addVolcanoReportEntry(entry: SummaryVolcanoEntry): boolean {
  const normalized = normalizeEntry(entry);
  const current = listVolcanoReportEntries();
  if (current.some((existing) => isSameVolcanoEntry(existing, normalized))) {
    return false;
  }
  current.push(normalized);
  writeJson(VOLCANO_LOG_KEY, current);
  return true;
}

export function removeVolcanoReportEntry(entry: SummaryVolcanoEntry): number {
  const normalized = normalizeEntry(entry);
  const current = listVolcanoReportEntries();
  const next = current.filter((existing) => !isSameVolcanoEntry(existing, normalized));
  writeJson(VOLCANO_LOG_KEY, next);
  return current.length - next.length;
}

export function getSummaryReportContext(): SummaryReportContext {
  const qcSettings = readJson<Record<string, Record<string, unknown>>>(
    QC_SETTINGS_KEY,
    {}
  );
  const volcanoEntries = listVolcanoReportEntries();
  return {
    qcSettings,
    volcanoEntries,
    completenessSettings: readPersistedUiState<{ missingPlot?: Record<string, unknown> }>("completeness.v1", {}).missingPlot ?? {},
    advancedPlotMode: getAdvancedPlotMode(),
    advancedPlotSettingsByKey: getAdvancedPlotSettingsByKey(),
    qcAdvancedSettingsByTab: readAdvancedUiState("qc.pipeline.v1"),
    completenessAdvancedSettingsByTab: readAdvancedUiState("completeness.v1"),
  };
}
