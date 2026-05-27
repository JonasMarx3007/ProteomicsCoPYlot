import { useMemo, useState } from "react";
import { runPeptideCollapse } from "../../lib/api";
import type { ExternalTab, PeptideCollapseResponse } from "../../lib/types";

type Props = {
  activeTab: ExternalTab;
};

export default function ExternalToolsPage({ activeTab }: Props) {
  if (activeTab === "gonetView") {
    return <GONetViewTool />;
  }

  if (activeTab !== "peptideCollapse") {
    return (
      <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <div className="text-lg font-semibold text-slate-900">External Tools</div>
        <div className="mt-2 text-sm text-slate-500">This tab is not built yet.</div>
      </section>
    );
  }

  return <PeptideCollapseTool />;
}

function GONetViewTool() {
  const appUrl = "https://jonasmarx3007.github.io/GONetView/";
  const githubUrl = "https://github.com/JonasMarx3007/GONetView";
  const doiUrl = "https://doi.org/10.5281/zenodo.20271711";
  const imageUrl =
    "https://raw.githubusercontent.com/JonasMarx3007/GONetView/main/docs/assets/gonetview-overview.png";
  const imagePageUrl =
    "https://github.com/JonasMarx3007/GONetView/blob/main/docs/assets/gonetview-overview.png";

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="grid gap-6 lg:grid-cols-[minmax(20rem,0.75fr)_minmax(34rem,1.25fr)] lg:items-start">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              External Web Tool
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">GONetView</h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
              Visualize Gene Ontology term networks and explore how genes connect to biological
              processes, molecular functions, and cellular components.
            </p>

            <ul className="mt-5 space-y-2 text-sm leading-6 text-slate-700">
              <li>Map GO terms into interpretable networks.</li>
              <li>Inspect genes associated with selected GO terms.</li>
              <li>Export GO network figures for reports and publications.</li>
            </ul>

            <div className="mt-5 flex flex-wrap gap-2">
              <ExternalLinkButton href={appUrl}>Open GONetView</ExternalLinkButton>
              <ExternalLinkButton href={doiUrl}>DOI</ExternalLinkButton>
              <ExternalLinkButton href={githubUrl}>GitHub</ExternalLinkButton>
            </div>

            <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Citation
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-700">
                Marx, J. (2026). GONetView (v0.1.0) [Computer software]. Zenodo.
                https://doi.org/10.5281/zenodo.20271711
              </p>
            </div>
          </div>

          <a
            href={imagePageUrl}
            target="_blank"
            rel="noreferrer"
            className="block overflow-hidden rounded-2xl border border-slate-200 bg-slate-50"
          >
            <img
              src={imageUrl}
              alt="GONetView overview"
              className="h-auto min-h-[24rem] w-full object-cover"
            />
          </a>
        </div>
      </section>
    </div>
  );
}

function ExternalLinkButton({ href, children }: { href: string; children: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
    >
      {children}
    </a>
  );
}

function PeptideCollapseTool() {
  const [inputPath, setInputPath] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [cutoff, setCutoff] = useState(0);
  const [collapseVersion, setCollapseVersion] = useState<"newest" | "legacy">("newest");
  const [result, setResult] = useState<PeptideCollapseResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canRun = useMemo(() => Boolean(inputPath.trim()) && !running, [inputPath, running]);

  async function handleRun() {
    if (!canRun) return;
    try {
      setRunning(true);
      setError(null);
      const payload = await runPeptideCollapse({
        inputPath: inputPath.trim(),
        outputPath: outputPath.trim() ? outputPath.trim() : null,
        cutoff,
        collapseVersion,
      });
      setResult(payload);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Failed to run peptide collapse.");
    } finally {
      setRunning(false);
    }
  }

  const previewColumns = collectColumns(result?.preview ?? []);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Peptide Collapse</h2>
        <p className="mt-2 text-sm text-slate-600">
          Run peptide collapse on a Spectronaut TSV file path.
        </p>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <TextField
            label="Input file path"
            value={inputPath}
            onChange={setInputPath}
            placeholder="C:\\data\\input.tsv"
          />
          <TextField
            label="Output file path (optional)"
            value={outputPath}
            onChange={setOutputPath}
            placeholder="C:\\data\\output_collapsed.tsv"
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Localization cutoff</span>
            <input
              type="text"
              lang="en-US"
              inputMode="decimal"
              value={Number.isFinite(cutoff) ? cutoff : 0}
              onChange={(event) =>
                setCutoff(clampCutoff(parseDecimalInput(event.target.value, cutoff)))
              }
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
            />
          </label>

          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Collapse version</span>
            <select
              value={collapseVersion}
              onChange={(event) => setCollapseVersion(event.target.value as "newest" | "legacy")}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
            >
              <option value="newest">Newest (Yue Yang)</option>
              <option value="legacy">Legacy (Denis Oleynik)</option>
            </select>
          </label>
        </div>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleRun}
            disabled={!canRun}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? "Running..." : "Run Peptide Collapse"}
          </button>
        </div>

        {error ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
      </section>

      {result ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Run Result</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryCard label="Status" value={result.success ? "Success" : "Failed"} />
            <SummaryCard
              label="Collapse Version"
              value={result.collapseVersion === "newest" ? "Newest (Yue Yang)" : "Legacy (Denis Oleynik)"}
            />
            <SummaryCard label="Rows" value={result.rows == null ? "-" : String(result.rows)} />
            <SummaryCard label="Columns" value={result.columns == null ? "-" : String(result.columns)} />
          </div>
          {result.outputPath ? (
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              Output file: <span className="font-mono text-xs">{result.outputPath}</span>
            </div>
          ) : null}
          {result.error ? (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {result.error}
            </div>
          ) : null}
        </section>
      ) : null}

      {result ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Execution Log</h3>
          <textarea
            readOnly
            value={result.logs}
            className="mt-4 h-72 w-full rounded-xl border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-700"
          />
        </section>
      ) : null}

      {result ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Preview</h3>
          <div className="mt-4">
            {!result.preview.length ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                No preview available.
              </div>
            ) : (
              <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
                <table className="min-w-full divide-y divide-slate-200">
                  <thead className="bg-slate-50">
                    <tr>
                      {previewColumns.map((column) => (
                        <th
                          key={column}
                          className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-600"
                        >
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 bg-white">
                    {result.preview.map((row, index) => (
                      <tr key={index} className={index % 2 ? "bg-slate-50/40" : "bg-white"}>
                        {previewColumns.map((column) => (
                          <td key={column} className="max-w-xs px-4 py-2 align-top text-sm text-slate-700">
                            {formatCell(row[column])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      ) : null}
    </div>
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
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function collectColumns(rows: Record<string, unknown>[]) {
  const set = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => set.add(key));
  });
  return Array.from(set);
}

function formatCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function clampCutoff(value: number) {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function parseDecimalInput(raw: string, fallback: number) {
  const normalized = raw.trim().replace(",", ".");
  if (!normalized) return fallback;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : fallback;
}
