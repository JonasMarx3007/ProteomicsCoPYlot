// In-memory only: never persist credentials, data or dirty markers across reset.
export function stableSnapshot(value: unknown): string {
  return JSON.stringify(value, (_key, item) => {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]]));
    }
    return item;
  });
}

export class UnsavedAnalysis {
  private revision = 0;
  private pending = 0;
  private saved: { revision: number; ui: string } | null = null;

  beginMutation(): () => void {
    this.revision += 1;
    this.pending += 1;
    let finished = false;
    return () => {
      if (finished) return;
      finished = true;
      this.pending -= 1;
      this.revision += 1;
    };
  }

  capture(ui: unknown) {
    return { revision: this.revision, ui: stableSnapshot(ui), pending: this.pending };
  }

  markSaved(snapshot: ReturnType<UnsavedAnalysis["capture"]>): void {
    // Never mark edits made during export/write as saved, nor a partial mutation.
    if (snapshot.pending === 0 && this.pending === 0 && snapshot.revision === this.revision) {
      this.saved = snapshot;
    }
  }

  initialize(ui: unknown): void {
    if (this.saved === null) this.saved = { revision: 0, ui: stableSnapshot(ui) };
  }

  isDirty(ui: unknown): boolean {
    return this.pending > 0 || this.saved === null ||
      this.revision !== this.saved.revision || stableSnapshot(ui) !== this.saved.ui;
  }
}

export const unsavedAnalysis = new UnsavedAnalysis();

export function isAnalysisMutation(url: string, method = "GET"): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) return false;
  const path = new URL(url, "http://localhost").pathname;
  return /\/api\/datasets\//.test(path) ||
    (/\/api\/annotations\//.test(path) && !path.endsWith("/log2-detect")) ||
    /\/api\/peptide\/metadata\//.test(path) ||
    /\/api\/data-tools\/condition-colors\//.test(path) ||
    path.endsWith("/api/data-tools/imputation/run") ||
    path.endsWith("/api/data-tools/id-translation/run") ||
    path.endsWith("/api/data-tools/phospho-localization-cutoff") ||
    path.endsWith("/api/restore/import");
}

export function warnBeforeUnload(event: BeforeUnloadEvent, dirty: boolean): void {
  if (!dirty) return;
  event.preventDefault();
  event.returnValue = true; // Legacy browser support; wording is browser-controlled.
}
