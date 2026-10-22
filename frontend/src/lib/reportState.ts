import type {
  AnnotationKind,
  AdvancedPlotSettings,
  CurrentDatasetsResponse,
  DataSource,
  SummaryReportContext,
  SummaryVolcanoEntry,
} from "./types";
import { DATA_SOURCE_LABELS, restoreVolcanoRenderType } from "./types";
import { getAdvancedPlotMode, getAdvancedPlotSettingsByKey } from "./appSettings";
import { readPersistedUiState } from "./persistedUiState";
import { IS_VIEWER_MODE } from "./appMode";

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

function clearSummaryReportState() {
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
  // `advancedV2` since the panel stopped storing its displayed defaults; the
  // QC and Completeness pages write nothing under the old name any more.
  const advanced = state.advancedV2;
  return advanced && typeof advanced === "object" && !Array.isArray(advanced)
    ? (advanced as Record<string, AdvancedPlotSettings>)
    : {};
}

function normalizeDataSource(value: unknown): DataSource {
  // Anything-but-"data" used to mean "imputed" here, from when those were the
  // only two matrices. A volcano built on the filtered matrix was therefore
  // logged as imputed, and the report then described a matrix the figure had
  // not used. An unrecognised value falls back to the least processed one
  // rather than inventing the most processed one.
  const text = String(value ?? "").trim().toLowerCase();
  return text in DATA_SOURCE_LABELS ? (text as DataSource) : "data";
}

function normalizeLabelCount(value: unknown): number {
  const count = Number(value ?? 0);
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

function normalizeEntry(entry: SummaryVolcanoEntry): SummaryVolcanoEntry {
  const renderType = restoreVolcanoRenderType(entry.renderType);
  return {
    ...entry,
    dataSource: normalizeDataSource(entry.dataSource),
    highlightTerms: [...entry.highlightTerms].map((item) => item.trim()).filter(Boolean),
    condition1Control: entry.condition1Control ?? null,
    condition2Control: entry.condition2Control ?? null,
    proteinCorrection: Boolean(entry.proteinCorrection),
    renderType,
    // The label counts only reach the static renderer, so an interactive entry
    // stores zeros and two entries that differ only in a setting neither of
    // them uses stay one entry.
    labelTopUp: renderType === "Normal" ? normalizeLabelCount(entry.labelTopUp) : 0,
    labelTopDown: renderType === "Normal" ? normalizeLabelCount(entry.labelTopDown) : 0,
    // Without highlight terms neither switch draws anything, so two entries
    // that differ only there stay one entry; labels are a static-only choice.
    highlightOutline: entry.highlightTerms.length ? entry.highlightOutline !== false : true,
    highlightLabels: entry.highlightTerms.length && renderType === "Normal" ? Boolean(entry.highlightLabels) : false,
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
  if (Boolean(left.proteinCorrection) !== Boolean(right.proteinCorrection)) return false;
  if (left.highlightOutline !== right.highlightOutline) return false;
  if (left.highlightLabels !== right.highlightLabels) return false;
  if (left.pValueThreshold !== right.pValueThreshold) return false;
  if (left.log2fcThreshold !== right.log2fcThreshold) return false;
  if (left.renderType !== right.renderType) return false;
  if (left.labelTopUp !== right.labelTopUp) return false;
  if (left.labelTopDown !== right.labelTopDown) return false;
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
    // In viewer mode the QC page writes its advanced settings to their own
    // session key instead of into the persisted page state, so reading only
    // "qc.pipeline.v1" produced a report whose QC plots carried none of the
    // styling -- renamed conditions included -- that the viewer was looking at.
    qcAdvancedSettingsByTab: IS_VIEWER_MODE
      ? readPersistedUiState<Record<string, AdvancedPlotSettings>>("qc.advanced.v2", {})
      : readAdvancedUiState("qc.pipeline.v1"),
    completenessAdvancedSettingsByTab: readAdvancedUiState("completeness.v1"),
  };
}
