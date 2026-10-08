import { useEffect, useMemo, useState } from "react";
import { runPeptideCollapseFile } from "../../lib/api";
import type { ExternalTab } from "../../lib/types";

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
            // The picture is a picture of the tool, so it opens the tool. It
            // used to open the PNG's page in the source repository.
            href={appUrl}
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
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [cutoff, setCutoff] = useState(0);
  const [downloadName, setDownloadName] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canRun = useMemo(() => Boolean(inputFile) && !running, [inputFile, running]);

  useEffect(() => {
    return () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl);
    };
  }, [downloadUrl]);

  async function handleRun() {
    if (!canRun || !inputFile) return;
    try {
      setRunning(true);
      setError(null);
      setDownloadName("");
      setDownloadUrl("");
      const payload = await runPeptideCollapseFile(inputFile, {
        cutoff,
      });
      const url = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = payload.filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setDownloadUrl(url);
      setDownloadName(payload.filename);
    } catch (err) {
      setDownloadName("");
      setDownloadUrl("");
      setError(err instanceof Error ? err.message : "Failed to run peptide collapse.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Peptide Collapse</h2>
        <p className="mt-2 text-sm text-slate-600">
          Upload a Spectronaut TSV file, collapse the phosphosite profiles, and download the
          collapsed TSV result.
        </p>
        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <p className="font-medium text-slate-700">How the collapse works</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            <li>
              A site&apos;s value in a run is the median of the log2 intensities
              (EG.TotalQuantity) of the precursors that carry that site in that run. It therefore
              depends on which precursors were measured in each run: a run that misses a
              site&apos;s most intense precursors gets a lower value for the site.
            </li>
            <li>
              A site&apos;s localization probability is the highest EG.PTMAssayProbability
              observed for it in any run and precursor; the cutoff is applied to that
              maximum, so a site kept by the cutoff was confidently localized in at least
              one run.
            </li>
            <li>
              Multiply phosphorylated precursors keep their own site rows (<code>_M2</code>,{" "}
              <code>_M3</code>); nothing is merged into the singly phosphorylated row.
            </li>
          </ul>
        </div>

        <div className="mt-5 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5">
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Spectronaut TSV file</span>
            <input
              type="file"
              accept=".tsv,.txt,text/tab-separated-values,text/plain"
              onChange={(event) => {
                setInputFile(event.target.files?.[0] ?? null);
                setDownloadName("");
                setDownloadUrl("");
                setError(null);
              }}
              className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white"
            />
          </label>
          {inputFile ? (
            <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
              Selected file: <span className="font-medium">{inputFile.name}</span>
            </div>
          ) : null}
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
        {downloadName ? (
          <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Download ready:{" "}
            {downloadUrl ? (
              <a href={downloadUrl} download={downloadName} className="font-medium underline">
                {downloadName}
              </a>
            ) : (
              <span className="font-medium">{downloadName}</span>
            )}
          </div>
        ) : null}
      </section>
    </div>
  );
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
