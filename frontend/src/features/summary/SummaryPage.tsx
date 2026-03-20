import { useEffect, useMemo, useState, type ReactNode } from "react";
import { downloadSummaryReport, getSummaryOverview } from "../../lib/api";
import type {
  SummaryOverviewResponse,
  SummaryReportRequest,
  SummarySectionInfo,
  SummarySectionNote,
  SummaryTab,
} from "../../lib/types";

type Props = {
  activeTab: SummaryTab;
};

type SummaryDraft = SummaryReportRequest;

const STORAGE_KEY = "proteomicscopylot-summary-draft-v1";

const defaultDraft: SummaryDraft = {
  title: "Proteomics CoPYlot Summary Report",
  author: "",
  introduction: "",
  notes: {},
  includeMetadataTables: true,
};

export default function SummaryPage({ activeTab }: Props) {
  const [overview, setOverview] = useState<SummaryOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<SummaryDraft>(() => loadDraft());
  const [selectedSection, setSelectedSection] = useState("");
  const [reportUrl, setReportUrl] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    getSummaryOverview()
      .then((data) => {
        setOverview(data);
        setError(null);
      })
      .catch((err) => {
        setOverview(null);
        setError(err instanceof Error ? err.message : "Failed to load summary overview");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    } catch {}
  }, [draft]);

  useEffect(() => {
    if (!overview?.availableSections.length) {
      setSelectedSection("");
      return;
    }
    setSelectedSection((current) =>
      overview.availableSections.some((section) => section.key === current)
        ? current
        : overview.availableSections[0].key
    );
  }, [overview]);

  useEffect(() => {
    return () => {
      if (reportUrl) {
        URL.revokeObjectURL(reportUrl);
      }
    };
  }, [reportUrl]);

  const selectedSectionInfo = useMemo(
    () => overview?.availableSections.find((section) => section.key === selectedSection) ?? null,
    [overview, selectedSection]
  );
  const selectedSectionNote = selectedSectionInfo
    ? draft.notes[selectedSectionInfo.key] ?? { above: "", below: "" }
    : { above: "", below: "" };

  if (loading) {
    return (
      <div className="space-y-6">
        <SectionCard title="Summary">
          <InfoSection message="Loading summary overview..." />
        </SectionCard>
      </div>
    );
  }

  if (activeTab === "tables") {
    return renderTablesTab();
  }

  if (activeTab === "text") {
    return renderTextTab();
  }

  return renderReportTab();

  function renderTablesTab() {
    return (
      <div className="space-y-6">
        <SectionCard title="Summary Tables">
          <InfoSection message="Metadata tables from the loaded protein, phospho, and peptide workflows." />
          <Notice error={error} warnings={overview?.warnings} />
        </SectionCard>

        {(overview?.tables ?? []).map((table) => (
          <SectionCard
            key={table.key}
            title={`${table.title}${table.available ? ` (${table.rowCount})` : ""}`}
          >
            {table.available ? (
              <PreviewTable rows={table.rows} emptyText="No rows available." />
            ) : (
              <InfoSection message={table.message ?? "No rows available yet."} />
            )}
          </SectionCard>
        ))}
      </div>
    );
  }

  function renderTextTab() {
    return (
      <div className="space-y-6">
        <SectionCard title="Introduction">
          <TextareaField
            label="Report Introduction"
            value={draft.introduction}
            onChange={(value) => setDraft((current) => ({ ...current, introduction: value }))}
            rows={8}
            placeholder="Add the introductory text for the report."
          />
        </SectionCard>

        <SectionCard title="Section Notes">
          {!overview?.availableSections.length ? (
            <InfoSection message="Load datasets to unlock report sections for notes." />
          ) : (
            <div className="space-y-4">
              <SelectField
                label="Report Section"
                value={selectedSection}
                onChange={setSelectedSection}
                options={(overview?.availableSections ?? []).map((section) => ({
                  value: section.key,
                  label: `${section.group} - ${section.title}`,
                }))}
              />

              {selectedSectionInfo ? (
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  {selectedSectionInfo.description}
                </div>
              ) : null}

              <TextareaField
                label="Text Above Plot"
                value={selectedSectionNote.above}
                onChange={(value) => updateSelectedNote("above", value, selectedSectionInfo)}
                rows={6}
                placeholder="Optional text that should appear above this report section."
              />

              <TextareaField
                label="Text Below Plot"
                value={selectedSectionNote.below}
                onChange={(value) => updateSelectedNote("below", value, selectedSectionInfo)}
                rows={6}
                placeholder="Optional text that should appear below this report section."
              />
            </div>
          )}
          <Notice error={error} warnings={overview?.warnings} />
        </SectionCard>
      </div>
    );
  }

  function renderReportTab() {
    const sectionCount = overview?.availableSections.length ?? 0;
    const availableTableCount = (overview?.tables ?? []).filter((table) => table.available).length;
    const filename = sanitizeFilename(draft.title || overview?.suggestedFilename || "summary_report");

    return (
      <div className="space-y-6">
        <SummaryStats
          items={[
            { label: "Report Sections", value: String(sectionCount) },
            { label: "Metadata Tables", value: String(availableTableCount) },
          ]}
        />

        <SectionCard title="Report Details">
          <div className="grid gap-4 lg:grid-cols-2">
            <TextField
              label="Report Title"
              value={draft.title}
              onChange={(value) => setDraft((current) => ({ ...current, title: value }))}
            />
            <TextField
              label="Author"
              value={draft.author}
              onChange={(value) => setDraft((current) => ({ ...current, author: value }))}
            />
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <CheckboxField
              label="Include metadata tables"
              checked={draft.includeMetadataTables}
              onChange={(checked) =>
                setDraft((current) => ({ ...current, includeMetadataTables: checked }))
              }
            />
          </div>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={async () => {
                try {
                  setGenerating(true);
                  setReportError(null);
                  const blob = await downloadSummaryReport(draft);
                  setReportUrl((current) => {
                    if (current) URL.revokeObjectURL(current);
                    return URL.createObjectURL(blob);
                  });
                } catch (err) {
                  setReportUrl((current) => {
                    if (current) URL.revokeObjectURL(current);
                    return null;
                  });
                  setReportError(
                    err instanceof Error ? err.message : "Failed to generate summary report"
                  );
                } finally {
                  setGenerating(false);
                }
              }}
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
              disabled={generating}
            >
              {generating ? "Generating HTML..." : "Generate HTML Report"}
            </button>

            {reportUrl ? (
              <a
                href={reportUrl}
                download={filename}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download HTML
              </a>
            ) : null}
          </div>

          <Notice error={error ?? reportError} warnings={overview?.warnings} />
        </SectionCard>

        <SectionCard title="HTML Preview">
          {reportUrl ? (
            <iframe
              src={reportUrl}
              title="Summary HTML Preview"
              className="w-full rounded-xl border border-slate-200"
              style={{ height: 900 }}
            />
          ) : (
            <InfoSection message="Generate the HTML report to preview it here." />
          )}
        </SectionCard>
      </div>
    );
  }

  function updateSelectedNote(
    field: keyof SummarySectionNote,
    value: string,
    section: SummarySectionInfo | null
  ) {
    if (!section) return;
    setDraft((current) => ({
      ...current,
      notes: {
        ...current.notes,
        [section.key]: {
          above: current.notes[section.key]?.above ?? "",
          below: current.notes[section.key]?.below ?? "",
          [field]: value,
        },
      },
    }));
  }
}

function loadDraft(): SummaryDraft {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultDraft;
    const parsed = JSON.parse(raw) as Partial<SummaryDraft>;
    const title = typeof parsed.title === "string" ? parsed.title : defaultDraft.title;
    const author = typeof parsed.author === "string" ? parsed.author : defaultDraft.author;
    const introduction =
      typeof parsed.introduction === "string" ? parsed.introduction : defaultDraft.introduction;
    const includeMetadataTables =
      typeof parsed.includeMetadataTables === "boolean"
        ? parsed.includeMetadataTables
        : defaultDraft.includeMetadataTables;
    return {
      title,
      author,
      introduction,
      notes: parsed.notes ?? {},
      includeMetadataTables,
    };
  } catch {
    return defaultDraft;
  }
}

function sanitizeFilename(value: string) {
  const cleaned = value.trim().replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  const base = cleaned || "proteomicscopylot_summary_report";
  return base.toLowerCase().endsWith(".html") ? base : `${base}.html`;
}

function collectColumns(rows: Record<string, unknown>[]) {
  return Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>())
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Notice({ error, warnings }: { error: string | null; warnings?: string[] }) {
  if (!error && (!warnings || warnings.length === 0)) return null;
  return (
    <div className="mt-4 space-y-3">
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {warnings && warnings.length > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {warnings.join(" ")}
        </div>
      ) : null}
    </div>
  );
}

function InfoSection({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-sky-200 bg-sky-50 p-6 shadow-sm">
      <div className="text-sm text-sky-800">{message}</div>
    </div>
  );
}

function SummaryStats({
  items,
}: {
  items: { label: string; value: string }[];
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {item.label}
            </div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{item.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

function TextareaField({
  label,
  value,
  onChange,
  rows,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows: number;
  placeholder?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  if (!rows.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const columns = collectColumns(rows);
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="max-h-[40rem] overflow-auto">
        <table className="min-w-full table-fixed divide-y divide-slate-200 text-left text-sm">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className="overflow-hidden px-4 py-3 font-medium text-slate-700 text-ellipsis whitespace-nowrap"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <td
                    key={column}
                    title={String(row[column] ?? "")}
                    className="max-w-xs overflow-hidden px-4 py-3 align-top text-ellipsis whitespace-nowrap text-slate-600"
                  >
                    {String(row[column] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
