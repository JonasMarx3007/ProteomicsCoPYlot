import { useId, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  buildPlotUrl,
  getPeptideOverview,
  getPeptideSequenceCoverage,
  isAbortError,
} from "../../lib/api";
import { clampPlotDimensionCm, clampPlotDpi } from "../../lib/plotLimits";
import { saveQcReportSettings } from "../../lib/reportState";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type {
  PeptideCoverageResponse,
  PeptideOverviewResponse,
  PeptideSpecies,
  PeptideTab,
} from "../../lib/types";

type Props = {
  activeTab: PeptideTab;
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

const MISSING_PEPTIDE_DATASET_MESSAGE =
  "No peptide dataset path is currently loaded. Upload a peptide dataset path first.";

export default function PeptideLevelPage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("peptide.level.v1", {}),
    []
  );
  const persistedRt = (persisted.rt as Record<string, unknown>) ?? {};
  const persistedModification = (persisted.modification as Record<string, unknown>) ?? {};
  const persistedMissedCleavage = (persisted.missedCleavage as Record<string, unknown>) ?? {};
  const persistedCoverage = (persisted.coverage as Record<string, unknown>) ?? {};
  const [overview, setOverview] = useState<PeptideOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [rt, setRt] = useState({
    type: String(persistedRt.type ?? "Normal"),
    method: String(persistedRt.method ?? "Hexbin Plot"),
    addLine: Boolean(persistedRt.addLine ?? false),
    header: Boolean(persistedRt.header ?? true),
    bins: Number(persistedRt.bins ?? 1000),
    randomSeed: Number(persistedRt.randomSeed ?? 69),
    widthCm: Number(persistedRt.widthCm ?? 20),
    heightCm: Number(persistedRt.heightCm ?? 15),
    dpi: Number(persistedRt.dpi ?? 100),
  });
  const [modification, setModification] = useState({
    includeId: Boolean(persistedModification.includeId ?? false),
    header: Boolean(persistedModification.header ?? true),
    legend: Boolean(persistedModification.legend ?? true),
    widthCm: Number(persistedModification.widthCm ?? 25),
    heightCm: Number(persistedModification.heightCm ?? 15),
    dpi: Number(persistedModification.dpi ?? 100),
  });
  const [missedCleavage, setMissedCleavage] = useState({
    includeId: Boolean(persistedMissedCleavage.includeId ?? false),
    text: Boolean(persistedMissedCleavage.text ?? true),
    textSize: Number(persistedMissedCleavage.textSize ?? 8),
    header: Boolean(persistedMissedCleavage.header ?? true),
    // Determines whether K-P counts as a cleavage site: trypsin is blocked by
    // proline, a trypsin/Lys-C mix is not. Must match the digest actually used.
    protease: String(persistedMissedCleavage.protease ?? "trypsin"),
    widthCm: Number(persistedMissedCleavage.widthCm ?? 25),
    heightCm: Number(persistedMissedCleavage.heightCm ?? 15),
    dpi: Number(persistedMissedCleavage.dpi ?? 100),
  });
  const [coverage, setCoverage] = useState({
    species: (String(persistedCoverage.species ?? "human") === "mouse" ? "mouse" : "human") as PeptideSpecies,
    protein: String(persistedCoverage.protein ?? ""),
    chunkSize: Number(persistedCoverage.chunkSize ?? 100),
  });
  const [coverageResult, setCoverageResult] = useState<PeptideCoverageResponse | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);

  useEffect(() => {
    writePersistedUiState("peptide.level.v1", { rt, modification, missedCleavage, coverage });
  }, [rt, modification, missedCleavage, coverage]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (activeTab === "rtPlot") {
      onContextModeChange(
        [
          `type=${rt.type}`,
          `method=${rt.method}`,
          `addLine=${String(rt.addLine)}`,
          `header=${String(rt.header)}`,
          `bins=${String(rt.bins)}`,
          `randomSeed=${String(rt.randomSeed)}`,
          `widthCm=${String(rt.widthCm)}`,
          `heightCm=${String(rt.heightCm)}`,
          `dpi=${String(rt.dpi)}`,
        ].join("|")
      );
      return;
    }
    if (activeTab === "modification") {
      onContextModeChange(
        [
          `includeId=${String(modification.includeId)}`,
          `header=${String(modification.header)}`,
          `legend=${String(modification.legend)}`,
          `widthCm=${String(modification.widthCm)}`,
          `heightCm=${String(modification.heightCm)}`,
          `dpi=${String(modification.dpi)}`,
        ].join("|")
      );
      return;
    }
    if (activeTab === "missedCleavage") {
      onContextModeChange(
        [
          `includeId=${String(missedCleavage.includeId)}`,
          `text=${String(missedCleavage.text)}`,
          `textSize=${String(missedCleavage.textSize)}`,
          `header=${String(missedCleavage.header)}`,
          `protease=${missedCleavage.protease}`,
          `widthCm=${String(missedCleavage.widthCm)}`,
          `heightCm=${String(missedCleavage.heightCm)}`,
          `dpi=${String(missedCleavage.dpi)}`,
        ].join("|")
      );
      return;
    }
    onContextModeChange(
      [
        `species=${coverage.species}`,
        `protein=${coverage.protein}`,
        `chunkSize=${String(coverage.chunkSize)}`,
      ].join("|")
    );
  }, [
    onContextModeChange,
    activeTab,
    rt.method,
    rt.type,
    rt.addLine,
    rt.header,
    rt.bins,
    rt.randomSeed,
    rt.widthCm,
    rt.heightCm,
    rt.dpi,
    modification.includeId,
    modification.header,
    modification.legend,
    modification.widthCm,
    modification.heightCm,
    modification.dpi,
    missedCleavage.includeId,
    missedCleavage.text,
    missedCleavage.textSize,
    missedCleavage.header,
    missedCleavage.protease,
    missedCleavage.widthCm,
    missedCleavage.heightCm,
    missedCleavage.dpi,
    coverage.species,
    coverage.protein,
    coverage.chunkSize,
  ]);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal).catch((err) => {
      if (!isAbortError(err)) {
        setError(err instanceof Error ? err.message : "Failed to load peptide module");
        setLoading(false);
      }
    });
    return () => controller.abort();
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

    const controller = new AbortController();
    setCoverageLoading(true);
    setCoverageError(null);

    getPeptideSequenceCoverage(
      coverage.species,
      coverage.protein,
      coverage.chunkSize,
      { signal: controller.signal }
    )
      .then((response) => {
        setCoverageResult(response);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setCoverageResult(null);
        setCoverageError(err instanceof Error ? err.message : "Failed to calculate sequence coverage");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setCoverageLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [activeTab, coverage.chunkSize, coverage.protein, coverage.species, overview]);

  useEffect(() => {
    saveQcReportSettings("peptide", {
      rtPlot: rt,
      modification,
      missedCleavage,
    });
  }, [rt, modification, missedCleavage]);

  const hasDataset = Boolean(overview);
  const hasMetadata = Boolean(overview?.metadataLoaded);
  const showMissingDatasetInfoOnly =
    !hasDataset && error?.trim() === MISSING_PEPTIDE_DATASET_MESSAGE;
  const rtInteractiveSessionNonce = useMemo(() => Date.now(), []);

  const rtInteractive = String(rt.type).trim().toLowerCase() === "interactive";
  const rtPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      const rtParams = rtInteractive
        ? { ...rt, _rtInteractiveV: rtInteractiveSessionNonce }
        : rt;
      return (
      buildPlotUrl(
        rtInteractive ? "/api/plots/peptide/rt-interactive.html" : "/api/plots/peptide/rt.png",
          rtParams
        )
      );
    },
    [rt, rtInteractive, rtInteractiveSessionNonce, advancedPlotSignal]
  );
  const modificationPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl("/api/plots/peptide/modification.png", modification);
    },
    [modification, advancedPlotSignal]
  );
  const missedCleavagePlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl("/api/plots/peptide/missed-cleavage.png", missedCleavage);
    },
    [missedCleavage, advancedPlotSignal]
  );

  const coverageDownloadUrl = useMemo(() => {
    if (!coverageResult) return null;
    return `data:text/plain;charset=utf-8,${encodeURIComponent(coverageResult.sequenceText)}`;
  }, [coverageResult]);

  async function refresh(signal?: AbortSignal) {
    try {
      const nextOverview = await getPeptideOverview({ signal });
      setOverview(nextOverview);
      setError(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
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
        {error && !showMissingDatasetInfoOnly ? <ErrorBanner message={error} /> : null}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error ? <ErrorBanner message={error} /> : null}
      {overview.warnings.length > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {overview.warnings.join(" ")}
        </div>
      ) : null}

      {activeTab === "rtPlot" ? (
        <>
          <SectionCard title="RT Plot Options">
            <OptionsLayout
              controls={[
                <SelectField
                  key="method"
                  label="Mode"
                  value={rt.method}
                  onChange={(value) => setRt({ ...rt, method: value })}
                  options={["Scatter Plot", "Hexbin Plot", "Density Plot"]}
                />,
                <SelectField
                  key="type"
                  label="Type"
                  value={rt.type}
                  onChange={(value) => setRt({ ...rt, type: value })}
                  options={["Normal", "Interactive"]}
                />,
                <CommittedNumberField
                  key="bins"
                  label="Bins"
                  value={rt.bins}
                  onCommit={(value) => setRt({ ...rt, bins: Math.max(10, Math.round(value)) })}
                />,
                <CommittedNumberField
                  key="randomSeed"
                  label="Random Seed"
                  value={rt.randomSeed}
                  onCommit={(value) => setRt({ ...rt, randomSeed: Math.max(0, Math.round(value)) })}
                />,
                <CommittedNumberField
                  key="width"
                  label="Width (cm)"
                  value={rt.widthCm}
                  onCommit={(value) => setRt({ ...rt, widthCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={rt.heightCm}
                  onCommit={(value) => setRt({ ...rt, heightCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={rt.dpi}
                  onCommit={(value) => setRt({ ...rt, dpi: clampPlotDpi(value) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="line" label="Add Line" checked={rt.addLine} onChange={(value) => setRt({ ...rt, addLine: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={rt.header} onChange={(value) => setRt({ ...rt, header: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          <ImagePlotCard
            title="Retention Time Plot"
            url={rtPlotUrl}
            downloadName="peptide_rt_plot.png"
            renderMode={rtInteractive ? "html" : "image"}
            heightCm={rt.heightCm}
          />
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
                  onCommit={(value) => setModification({ ...modification, widthCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={modification.heightCm}
                  onCommit={(value) => setModification({ ...modification, heightCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={modification.dpi}
                  onCommit={(value) => setModification({ ...modification, dpi: clampPlotDpi(value) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={modification.includeId} onChange={(value) => setModification({ ...modification, includeId: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={modification.header} onChange={(value) => setModification({ ...modification, header: value })} />,
                <CheckboxField key="legend" label="Toggle Legend" checked={modification.legend} onChange={(value) => setModification({ ...modification, legend: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          {!hasMetadata ? (
            <InfoBanner message="Generate protein annotation in Data > Annotation to generate the modification plot." />
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
                <SelectField
                  key="protease"
                  label="Cleavage Rule"
                  value={missedCleavage.protease}
                  onChange={(value) => setMissedCleavage({ ...missedCleavage, protease: value })}
                  options={["trypsin", "trypsin_lysc"]}
                  labels={{ trypsin: "Trypsin", trypsin_lysc: "Trypsin / Lys-C" }}
                />,
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
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, widthCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="height"
                  label="Height (cm)"
                  value={missedCleavage.heightCm}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, heightCm: clampPlotDimensionCm(Math.max(5, value)) })}
                />,
                <CommittedNumberField
                  key="dpi"
                  label="DPI"
                  value={missedCleavage.dpi}
                  onCommit={(value) => setMissedCleavage({ ...missedCleavage, dpi: clampPlotDpi(value) })}
                />,
              ]}
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={missedCleavage.includeId} onChange={(value) => setMissedCleavage({ ...missedCleavage, includeId: value })} />,
                <CheckboxField key="text" label="Toggle Text" checked={missedCleavage.text} onChange={(value) => setMissedCleavage({ ...missedCleavage, text: value })} />,
                <CheckboxField key="header" label="Toggle Header" checked={missedCleavage.header} onChange={(value) => setMissedCleavage({ ...missedCleavage, header: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          {!hasMetadata ? (
            <InfoBanner message="Generate protein annotation in Data > Annotation to generate the missed cleavage plot." />
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
          {advancedPlotOptions}

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
  const fieldId = useId();
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select id={fieldId}
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
  const fieldId = useId();
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
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input id={fieldId}
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
  renderMode = "image",
  heightCm = 15,
}: {
  title: string;
  url: string;
  downloadName: string;
  renderMode?: "image" | "html";
  heightCm?: number;
}) {
  const [errorState, setErrorState] = useState<{ url: string; message: string } | null>(null);
  const error = errorState?.url === url ? errorState.message : null;
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>("png");

  const downloadUrl = withPlotDownloadFormat(url, downloadFormat);
  const downloadFilename = withPlotDownloadFilename(downloadName, downloadFormat);

  async function handleError() {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed?.detail) {
            setErrorState({ url, message: parsed.detail });
            return;
          }
        } catch {}
      }
    } catch {}
    setErrorState({ url, message: "Failed to load plot image. Check backend logs for details." });
  }

  return (
    <SectionCard title={title}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {renderMode === "image" ? (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={downloadFormat}
              onChange={(e) => setDownloadFormat(e.target.value as PlotDownloadFormat)}
              className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
            >
              {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <a
              href={downloadUrl}
              download={downloadFilename}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Download Plot
            </a>
          </div>
        ) : (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
          >
            Open Interactive Plot
          </a>
        )}
      </div>
      {renderMode === "image" ? (
        <img
          key={url}
          src={url}
          alt={title}
          className="mt-4 w-full rounded-xl border border-slate-200"
          onLoad={() => setErrorState(null)}
          onError={() => {
            handleError();
          }}
        />
      ) : (
        <iframe
          sandbox="allow-scripts allow-downloads"
          key={url}
          src={url}
          title={`${title} interactive`}
          className="mt-4 block w-full rounded-xl border border-slate-200"
          style={{ height: `max(${cmToIframeHeight(heightCm)}px, 78vh)` }}
          onLoad={() => setErrorState(null)}
        />
      )}
      {error ? <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
    </SectionCard>
  );
}

function cmToIframeHeight(heightCm: number): number {
  const basePx = Number.isFinite(heightCm) ? (heightCm * 96) / 2.54 : (15 * 96) / 2.54;
  return Math.max(860, Math.round(basePx + 280));
}

