import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  buildPlotUrl,
  clearCurrentPeptideMetadata,
  getCurrentPeptideMetadata,
  getPeptideOverview,
  getPeptideSequenceCoverage,
  uploadPeptideMetadata,
} from "../../lib/api";
import type {
  PeptideCoverageResponse,
  PeptideMetadataResponse,
  PeptideOverviewResponse,
  PeptideSpecies,
  PeptideTab,
} from "../../lib/types";

type Props = {
  activeTab: PeptideTab;
};

export default function PeptideLevelPage({ activeTab }: Props) {
  const [overview, setOverview] = useState<PeptideOverviewResponse | null>(null);
  const [metadata, setMetadata] = useState<PeptideMetadataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadataFile, setMetadataFile] = useState<File | null>(null);
  const [uploadingMetadata, setUploadingMetadata] = useState(false);
  const [clearingMetadata, setClearingMetadata] = useState(false);

  const [rt, setRt] = useState({
    method: "Hexbin Plot",
    addLine: false,
    header: true,
    bins: 1000,
    widthCm: 20,
    heightCm: 15,
    dpi: 100,
  });
  const [modification, setModification] = useState({
    includeId: false,
    header: true,
    legend: true,
    widthCm: 25,
    heightCm: 15,
    dpi: 100,
  });
  const [missedCleavage, setMissedCleavage] = useState({
    includeId: false,
    text: true,
    textSize: 8,
    header: true,
    widthCm: 25,
    heightCm: 15,
    dpi: 100,
  });
  const [coverage, setCoverage] = useState({
    species: "human" as PeptideSpecies,
    protein: "",
    chunkSize: 100,
  });
  const [coverageResult, setCoverageResult] = useState<PeptideCoverageResponse | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);

  useEffect(() => {
    refresh().catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load peptide module");
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    setCoverage((current) => {
      if (!overview?.availableProteins.length) {
        return { ...current, protein: "" };
      }
      if (overview.availableProteins.includes(current.protein)) {
        return current;
      }
      return { ...current, protein: overview.availableProteins[0] ?? "" };
    });
  }, [overview]);

  useEffect(() => {
    if (activeTab !== "sequenceCoverage") return;
    if (!overview?.availableProteins.length || !coverage.protein) {
      setCoverageResult(null);
      setCoverageError(null);
      setCoverageLoading(false);
      return;
    }

    let cancelled = false;
    setCoverageLoading(true);
    setCoverageError(null);

    getPeptideSequenceCoverage(coverage.species, coverage.protein, coverage.chunkSize)
      .then((response) => {
        if (cancelled) return;
        setCoverageResult(response);
      })
      .catch((err) => {
        if (cancelled) return;
        setCoverageResult(null);
        setCoverageError(err instanceof Error ? err.message : "Failed to calculate sequence coverage");
      })
      .finally(() => {
        if (cancelled) return;
        setCoverageLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, coverage.chunkSize, coverage.protein, coverage.species, overview]);

  const hasDataset = Boolean(overview);
  const hasMetadata = Boolean(metadata);

  const rtPlotUrl = useMemo(() => buildPlotUrl("/api/plots/peptide/rt.png", rt), [rt]);
  const modificationPlotUrl = useMemo(
    () => buildPlotUrl("/api/plots/peptide/modification.png", modification),
    [modification]
  );
  const missedCleavagePlotUrl = useMemo(
    () => buildPlotUrl("/api/plots/peptide/missed-cleavage.png", missedCleavage),
    [missedCleavage]
  );

  const coverageDownloadUrl = useMemo(() => {
    if (!coverageResult) return null;
    return `data:text/plain;charset=utf-8,${encodeURIComponent(coverageResult.sequenceText)}`;
  }, [coverageResult]);

  async function refresh() {
    setRefreshing(true);
    try {
      const [nextOverview, nextMetadata] = await Promise.all([
        getPeptideOverview(),
        getCurrentPeptideMetadata().catch(() => null),
      ]);
      setOverview(nextOverview);
      setMetadata(nextMetadata);
      setError(null);
    } finally {
      setRefreshing(false);
      setLoading(false);
    }
  }

  async function handleMetadataUpload() {
    if (!metadataFile) {
      setError("Please choose a peptide metadata file first.");
      return;
    }

    try {
      setUploadingMetadata(true);
      setError(null);
      const uploaded = await uploadPeptideMetadata(metadataFile);
      setMetadata(uploaded);
      setMetadataFile(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload peptide metadata");
    } finally {
      setUploadingMetadata(false);
    }
  }

  async function handleMetadataClear() {
    try {
      setClearingMetadata(true);
      setError(null);
      await clearCurrentPeptideMetadata();
      setMetadata(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear peptide metadata");
    } finally {
      setClearingMetadata(false);
    }
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="text-sm text-slate-500">Loading peptide pipeline...</div>
      </div>
    );
  }

  if (!hasDataset || !overview) {
    return (
      <div className="space-y-6">
        <SectionCard title="Peptide Level">
          <InfoBanner message="Load a peptide dataset path in the Upload section before using the peptide pipeline." />
        </SectionCard>
        {error ? <ErrorBanner message={error} /> : null}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionCard title="Peptide Dataset">
        <div className="grid gap-4 lg:grid-cols-3">
          <SummaryCard label="File" value={overview.filename} title={overview.filename} />
          <SummaryCard label="Rows" value={String(overview.rows)} />
          <SummaryCard label="Proteins" value={String(overview.availableProteins.length)} />
        </div>
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
          <div className="font-medium text-slate-700">Dataset path</div>
          <div className="mt-1 break-all">{overview.path}</div>
        </div>
        {overview.warnings.length > 0 ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {overview.warnings.join(" ")}
          </div>
        ) : null}
      </SectionCard>

      <SectionCard title="Peptide Metadata">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div className="space-y-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <div className="font-medium text-slate-700">Current metadata</div>
              <div className="mt-2">
                {metadata ? `${metadata.filename} (${metadata.rows} rows)` : "No peptide metadata uploaded"}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Upload metadata file</label>
              <input
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.parquet"
                onChange={(e) => setMetadataFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-slate-600"
              />
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleMetadataUpload}
                disabled={!metadataFile || uploadingMetadata}
                className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {uploadingMetadata ? "Uploading..." : "Upload Metadata"}
              </button>
              <button
                type="button"
                onClick={handleMetadataClear}
                disabled={!metadata || clearingMetadata}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                {clearingMetadata ? "Clearing..." : "Clear Metadata"}
              </button>
              <button
                type="button"
                onClick={() => refresh().catch(() => {})}
                disabled={refreshing}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
              >
                {refreshing ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
              Modification Plot and Missed Cleavage Plot require a metadata file with `sample` and `condition` columns.
            </div>
          </div>

          <div>
            {metadata ? (
              <PreviewTable rows={metadata.preview} emptyText="No peptide metadata preview available." />
            ) : (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                No peptide metadata preview available.
              </div>
            )}
          </div>
        </div>
      </SectionCard>

      {error ? <ErrorBanner message={error} /> : null}

      {activeTab === "rtPlot" ? (
        <>
          <SectionCard title="RT Plot Options">
            <OptionsLayout
              controls={[
                <SelectField
                  key="method"
                  label="Type"
                  value={rt.method}
                  onChange={(value) => setRt({ ...rt, method: value })}
                  options={["Scatter Plot", "Hexbin Plot", "Density Plot"]}
                />,
                <CommittedNumberField
                  key="bins"
                  label="Bins"
                  value={rt.bins}
                  onCommit={(value) => setRt({ ...rt, bins: Math.max(10, Math.round(value)) })}
                />,
                <CommittedNumberField
                  key="width"
                  label="Width (cm)"
                  value={rt.widthCm}
                  onCommit={(value) => setRt({ ...rt, widthCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={rt.heightCm}
                  onCommit={(value) => setRt({ ...rt, heightCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={rt.dpi}
                  onCommit={(value) => setRt({ ...rt, dpi: Math.max(72, Math.round(value)) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="line" label="Add Line" checked={rt.addLine} onChange={(value) => setRt({ ...rt, addLine: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={rt.header} onChange={(value) => setRt({ ...rt, header: value })} />,
              ]}
            />
          </SectionCard>
          <ImagePlotCard title="Retention Time Plot" url={rtPlotUrl} downloadName="peptide_rt_plot.png" />
        </>
      ) : null}

      {activeTab === "modification" ? (
        <>
          <SectionCard title="Modification Plot Options">
            <OptionsLayout
              controls={[
                <CommittedNumberField
                  key="width"
                  label="Width (cm)"
                  value={modification.widthCm}
                  onCommit={(value) => setModification({ ...modification, widthCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={modification.heightCm}
                  onCommit={(value) => setModification({ ...modification, heightCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={modification.dpi}
                  onCommit={(value) => setModification({ ...modification, dpi: Math.max(72, Math.round(value)) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={modification.includeId} onChange={(value) => setModification({ ...modification, includeId: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={modification.header} onChange={(value) => setModification({ ...modification, header: value })} />,
                <CheckboxField key="legend" label="Toggle Legend" checked={modification.legend} onChange={(value) => setModification({ ...modification, legend: value })} />,
              ]}
            />
          </SectionCard>
          {!hasMetadata ? (
            <InfoBanner message="Upload peptide metadata to generate the modification plot." />
          ) : (
            <ImagePlotCard title="Modification Plot" url={modificationPlotUrl} downloadName="peptide_modification_plot.png" />
          )}
        </>
      ) : null}

      {activeTab === "missedCleavage" ? (
        <>
          <SectionCard title="Missed Cleavage Plot Options">
            <OptionsLayout
              controls={[
                <CommittedNumberField
                  key="text-size"
                  label="Text Size"
                  value={missedCleavage.textSize}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, textSize: Math.max(6, Math.round(value)) })}
                />,
                <CommittedNumberField
                  key="width"
                  label="Width (cm)"
                  value={missedCleavage.widthCm}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, widthCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={missedCleavage.heightCm}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, heightCm: Math.max(5, value) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={missedCleavage.dpi}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, dpi: Math.max(72, Math.round(value)) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={missedCleavage.includeId} onChange={(value) => setMissedCleavage({ ...missedCleavage, includeId: value })} />,
                <CheckboxField key="text" label="Toggle Text" checked={missedCleavage.text} onChange={(value) => setMissedCleavage({ ...missedCleavage, text: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={missedCleavage.header} onChange={(value) => setMissedCleavage({ ...missedCleavage, header: value })} />,
              ]}
            />
          </SectionCard>
          {!hasMetadata ? (
            <InfoBanner message="Upload peptide metadata to generate the missed cleavage plot." />
          ) : (
            <ImagePlotCard title="Missed Cleavage Plot" url={missedCleavagePlotUrl} downloadName="peptide_missed_cleavage_plot.png" />
          )}
        </>
      ) : null}

      {activeTab === "sequenceCoverage" ? (
        <>
          <SectionCard title="Sequence Coverage Options">
            <OptionsLayout
              controls={[
                <SelectField
                  key="species"
                  label="Database"
                  value={coverage.species}
                  onChange={(value) => setCoverage({ ...coverage, species: value as PeptideSpecies })}
                  options={["human", "mouse"]}
                  labels={{ human: "Human", mouse: "Mouse" }}
                />,
                <SelectField
                  key="protein"
                  label="Protein"
                  value={coverage.protein}
                  onChange={(value) => setCoverage({ ...coverage, protein: value })}
                  options={overview.availableProteins}
                />,
                <CommittedNumberField
                  key="chunk-size"
                  label="Chunk Size"
                  value={coverage.chunkSize}
                  onCommit={(value) => setCoverage({ ...coverage, chunkSize: Math.max(10, Math.round(value)) })}
                />,
              ]}
            />
          </SectionCard>

          {coverageLoading ? (
            <SectionCard title="Sequence Coverage">
              <div className="text-sm text-slate-500">Calculating sequence coverage...</div>
            </SectionCard>
          ) : coverageError ? (
            <ErrorBanner message={coverageError} />
          ) : coverageResult ? (
            <>
              <SectionCard title="Sequence Coverage Summary">
                <div className="grid gap-4 lg:grid-cols-3">
                  <SummaryCard label="Protein" value={coverageResult.protein} title={coverageResult.protein} />
                  <SummaryCard label="Coverage" value={`${coverageResult.coveragePercent}%`} />
                  <SummaryCard label="Peptides" value={String(coverageResult.matchingPeptideCount)} />
                </div>
              </SectionCard>

              <SectionCard title="Sequence Coverage">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm text-slate-600">Coverage map for the selected protein.</div>
                  {coverageDownloadUrl ? (
                    <a
                      href={coverageDownloadUrl}
                      download={`${coverageResult.protein}_${coverageResult.species}_coverage.txt`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download TXT
                    </a>
                  ) : null}
                </div>
                <pre className="mt-4 max-h-[28rem] overflow-auto rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-700">
                  {coverageResult.sequenceText}
                </pre>
              </SectionCard>
            </>
          ) : (
            <InfoBanner message="Select a protein to calculate sequence coverage." />
          )}
        </>
      ) : null}
    </div>
  );
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SummaryCard({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-900" title={title ?? value}>
        {value}
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

function InfoBanner({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
      {message}
    </div>
  );
}

function CheckboxField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  labels,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
  labels?: Record<string, string>;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {labels?.[option] ?? option}
          </option>
        ))}
      </select>
    </div>
  );
}

function formatNumberValue(value: number) {
  return Number.isFinite(value) ? String(value) : "";
}

function CommittedNumberField({
  label,
  value,
  onCommit,
}: {
  label: string;
  value: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(() => formatNumberValue(value));

  useEffect(() => {
    setDraft(formatNumberValue(value));
  }, [value]);

  const commit = () => {
    const normalized = draft.trim().replace(",", ".");
    if (!normalized) {
      setDraft(formatNumberValue(value));
      return;
    }
    const nextValue = Number(normalized);
    if (!Number.isFinite(nextValue)) {
      setDraft(formatNumberValue(value));
      return;
    }
    onCommit(nextValue);
    setDraft(formatNumberValue(nextValue));
  };

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(",", "."))}
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

function OptionsLayout({
  controls,
  toggles,
}: {
  controls: ReactNode[];
  toggles?: ReactNode[];
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">{controls}</div>
      {toggles && toggles.length > 0 ? <div className="flex flex-wrap gap-3">{toggles}</div> : null}
    </div>
  );
}

function ImagePlotCard({
  title,
  url,
  downloadName,
}: {
  title: string;
  url: string;
  downloadName: string;
}) {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
  }, [url]);

  async function handleError() {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed?.detail) {
            setError(parsed.detail);
            return;
          }
        } catch {}
      }
    } catch {}
    setError("Failed to load plot image. Check backend logs for details.");
  }

  return (
    <SectionCard title={title}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a
          href={url}
          download={downloadName}
          className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
        >
          Download Plot
        </a>
      </div>
      <img
        key={url}
        src={url}
        alt={title}
        className="mt-4 w-full rounded-xl border border-slate-200"
        onLoad={() => setError(null)}
        onError={() => {
          handleError();
        }}
      />
      {error ? <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
    </SectionCard>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  const columns = useMemo(() => {
    const seen = new Set<string>();
    rows.forEach((row) => {
      Object.keys(row).forEach((key) => seen.add(key));
    });
    return Array.from(seen);
  }, [rows]);

  if (!rows.length || !columns.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full table-fixed text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th key={column} className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
              {columns.map((column) => {
                const text = row[column] == null ? "" : String(row[column]);
                return (
                  <td key={`${rowIndex}-${column}`} className="border-b border-slate-100 px-3 py-2 text-slate-600" title={text}>
                    <div className="max-w-[28ch] overflow-hidden text-ellipsis whitespace-nowrap">{text}</div>
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
