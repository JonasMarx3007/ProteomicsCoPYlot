import type {
  AnnotationKind,
  SummaryReportContext,
  SummaryVolcanoEntry,
} from "./types";

const QC_SETTINGS_KEY = "pcopylot.report.qcSettings.v1";
const VOLCANO_LOG_KEY = "pcopylot.report.volcanoLog.v1";

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as T;
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    globalThis.localStorage?.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage write failures (private mode, quota, etc.).
  }
}

export function saveQcReportSettings(
  kind: AnnotationKind,
  settings: Record<string, unknown>
) {
  const all = readJson<Record<string, Record<string, unknown>>>(
    QC_SETTINGS_KEY,
    {}
  );
  all[kind] = settings;
  writeJson(QC_SETTINGS_KEY, all);
}

export function listVolcanoReportEntries(): SummaryVolcanoEntry[] {
  return readJson<SummaryVolcanoEntry[]>(VOLCANO_LOG_KEY, []);
}

function normalizeEntry(entry: SummaryVolcanoEntry): SummaryVolcanoEntry {
  return {
    ...entry,
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
  return { qcSettings, volcanoEntries };
}
