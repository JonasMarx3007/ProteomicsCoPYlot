import NumberField from "../../components/NumberField";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import OptionsLayout from "../../components/OptionsLayout";
import PlotImage from "../../components/PlotImage";
import InteractivePlot from "../../components/InteractivePlot";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import { restorePlotDimensionCm, restorePlotDpi, iframeHeightForPlot } from "../../lib/plotLimits";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  buildPlotUrl,
  getPeptideOverview,
  getPeptideSequenceCoverage,
  isAbortError,
} from "../../lib/api";
import { withoutStaticSize } from "../../lib/plotRenderType";
import { SizeRow } from "../../components/PlotFields";
import { saveQcReportSettings } from "../../lib/reportState";
import {
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
import SelectField from "../../components/SelectField";
import SectionCard from "../../components/SectionCard";
import CheckboxField from "../../components/CheckboxField";
import type { ContextMode } from "../../lib/types";

type Props = {
  activeTab: PeptideTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
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
    header: true,
    bins: Number(persistedRt.bins ?? 1000),
    randomSeed: Number(persistedRt.randomSeed ?? 69),
    widthCm: restorePlotDimensionCm(persistedRt.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedRt.heightCm, 15),
    dpi: restorePlotDpi(persistedRt.dpi, 100),
  });
  const [modification, setModification] = useState({
    includeId: Boolean(persistedModification.includeId ?? false),
    header: true,
    legend: true,
    widthCm: restorePlotDimensionCm(persistedModification.widthCm, 25),
    heightCm: restorePlotDimensionCm(persistedModification.heightCm, 15),
    dpi: restorePlotDpi(persistedModification.dpi, 100),
  });
  const [missedCleavage, setMissedCleavage] = useState({
    includeId: Boolean(persistedMissedCleavage.includeId ?? false),
    text: Boolean(persistedMissedCleavage.text ?? true),
    textSize: Number(persistedMissedCleavage.textSize ?? 8),
    header: true,
    // Determines whether K-P counts as a cleavage site: trypsin is blocked by
    // proline, a trypsin/Lys-C mix is not. Must match the digest actually used.
    protease: String(persistedMissedCleavage.protease ?? "trypsin"),
    widthCm: restorePlotDimensionCm(persistedMissedCleavage.widthCm, 25),
    heightCm: restorePlotDimensionCm(persistedMissedCleavage.heightCm, 15),
    dpi: restorePlotDpi(persistedMissedCleavage.dpi, 100),
  });
  const [coverage, setCoverage] = useState({
    species: (String(persistedCoverage.species ?? "human") === "mouse" ? "mouse" : "human") as PeptideSpecies,
    protein: String(persistedCoverage.protein ?? ""),
    chunkSize: Number(persistedCoverage.chunkSize ?? 100),
  });
  const [coverageResult, setCoverageResult] = useState<PeptideCoverageResponse | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageNotebook, setCoverageNotebook] = useState<RenderedNotebook | null>(null);
  const coverageRequestUrl = buildPlotUrl('/api/peptide/sequence-coverage', coverage);

  useEffect(() => {
    writePersistedUiState("peptide.level.v1", { rt, modification, missedCleavage, coverage });
  }, [rt, modification, missedCleavage, coverage]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (activeTab === "rtPlot") {
      onContextModeChange(
        {
          type: rt.type,
          method: rt.method,
          addLine: rt.addLine,
          header: rt.header,
          bins: rt.bins,
          randomSeed: rt.randomSeed,
          widthCm: rt.widthCm,
          heightCm: rt.heightCm,
          dpi: rt.dpi,
        }
      );
      return;
    }
    if (activeTab === "modification") {
      onContextModeChange(
        {
          includeId: modification.includeId,
          header: modification.header,
          legend: modification.legend,
          widthCm: modification.widthCm,
          heightCm: modification.heightCm,
          dpi: modification.dpi,
        }
      );
      return;
    }
    if (activeTab === "missedCleavage") {
      onContextModeChange(
        {
          includeId: missedCleavage.includeId,
          text: missedCleavage.text,
          textSize: missedCleavage.textSize,
          header: missedCleavage.header,
          protease: missedCleavage.protease,
          widthCm: missedCleavage.widthCm,
          heightCm: missedCleavage.heightCm,
          dpi: missedCleavage.dpi,
        }
      );
      return;
    }
    onContextModeChange(
      {
        species: coverage.species,
        protein: coverage.protein,
        chunkSize: coverage.chunkSize,
      }
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

  async function refresh(signal?: AbortSignal) {
    try {
      const nextOverview = await getPeptideOverview({ signal });
      setOverview(nextOverview);
      setError(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

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
        if (controller.signal.aborted) return;
        setCoverageResult(response);
        setCoverageNotebook({ url: coverageRequestUrl, token: response.notebookToken ?? null });
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
  }, [activeTab, coverage.chunkSize, coverage.protein, coverage.species, coverageRequestUrl, overview]);

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
  const [rtInteractiveSessionNonce] = useState(() => Date.now());

  const rtInteractive = String(rt.type).trim().toLowerCase() === "interactive";
  const rtPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      const rtParams = rtInteractive
        ? { ...withoutStaticSize(rt), _rtInteractiveV: rtInteractiveSessionNonce }
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
        <SectionCard as="h2" title="Peptide Level">
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
          <SectionCard as="h2" title="RT Plot Options">
            <OptionsLayout order="fields-size-toggles"
              fields={[
                // `peptide_rt_interactive_html` always draws a scatter and
                // reads neither Mode nor Bins, so neither is offered while the
                // interactive renderer is selected: a control that changes
                // nothing is worse than no control.
                <SelectField
                  key="method"
                  label="Mode"
                  value={rt.method}
                  onChange={(value) => setRt({ ...rt, method: value })}
                  options={["Scatter Plot", "Hexbin Plot", "Density Plot"]}
                  disabled={rtInteractive}
                  disabledHint="The interactive plot always draws a scatter."
                />,
                <SelectField
                  key="type"
                  label="Type"
                  value={rt.type}
                  onChange={(value) => setRt({ ...rt, type: value })}
                  options={["Normal", "Interactive"]}
                />,
                <NumberField
                  key="bins"
                  label="Bins"
                  value={rt.bins}
                  onChange={(value) => setRt({ ...rt, bins: Math.max(10, Math.round(value)) })}
                  disabled={rtInteractive}
                  disabledHint="Binning applies to the hexbin and density modes only."
                />,
                <NumberField
                  key="randomSeed"
                  label="Random Seed"
                  value={rt.randomSeed}
                  onChange={(value) => setRt({ ...rt, randomSeed: Math.max(0, Math.round(value)) })}
                />,
              ]}
              size={
                rtInteractive ? null : <SizeRow
                  widthCm={rt.widthCm}
                  heightCm={rt.heightCm}
                  dpi={rt.dpi}
                  onWidthChange={(value) => setRt({ ...rt, widthCm: value })}
                  onHeightChange={(value) => setRt({ ...rt, heightCm: value })}
                  onDpiChange={(value) => setRt({ ...rt, dpi: value })}
                />
              }
              toggles={[
                <CheckboxField key="line" label="Add Line" checked={rt.addLine} onChange={(value) => setRt({ ...rt, addLine: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          <ImagePlotCard
            title="Retention Time Plot"
            url={rtPlotUrl}
            downloadName="peptide_rt_plot.png"
            notebookEnabled
            renderMode={rtInteractive ? "html" : "image"}
          />
        </>
      ) : null}

      {activeTab === "modification" ? (
        <>
          <SectionCard as="h2" title="Modification Plot Options">
            <OptionsLayout order="fields-size-toggles"
              fields={[]}
              size={
                <SizeRow
                  widthCm={modification.widthCm}
                  heightCm={modification.heightCm}
                  dpi={modification.dpi}
                  onWidthChange={(value) => setModification({ ...modification, widthCm: value })}
                  onHeightChange={(value) => setModification({ ...modification, heightCm: value })}
                  onDpiChange={(value) => setModification({ ...modification, dpi: value })}
                />
              }
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={modification.includeId} onChange={(value) => setModification({ ...modification, includeId: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          {!hasMetadata ? (
            <InfoBanner message="Generate protein annotation in Data > Annotation to generate the modification plot." />
          ) : (
            <ImagePlotCard title="Modification Plot" url={modificationPlotUrl} downloadName="peptide_modification_plot.png" notebookEnabled />
          )}
        </>
      ) : null}

      {activeTab === "missedCleavage" ? (
        <>
          <SectionCard as="h2" title="Missed Cleavage Plot Options">
            <OptionsLayout order="fields-size-toggles"
              fields={[
                <SelectField
                  key="protease"
                  label="Cleavage Rule"
                  value={missedCleavage.protease}
                  onChange={(value) => setMissedCleavage({ ...missedCleavage, protease: value })}
                  options={["trypsin", "trypsin_lysc"]}
                  labels={{ trypsin: "Trypsin", trypsin_lysc: "Trypsin / Lys-C" }}
                />,
              ]}
              size={
                <SizeRow
                  widthCm={missedCleavage.widthCm}
                  heightCm={missedCleavage.heightCm}
                  dpi={missedCleavage.dpi}
                  onWidthChange={(value) => setMissedCleavage({ ...missedCleavage, widthCm: value })}
                  onHeightChange={(value) => setMissedCleavage({ ...missedCleavage, heightCm: value })}
                  onDpiChange={(value) => setMissedCleavage({ ...missedCleavage, dpi: value })}
                />
              }
              toggles={[
                <CheckboxField key="ids" label="Toggle IDs" checked={missedCleavage.includeId} onChange={(value) => setMissedCleavage({ ...missedCleavage, includeId: value })} />,
                <CheckboxField key="text" label="Toggle Text" checked={missedCleavage.text} onChange={(value) => setMissedCleavage({ ...missedCleavage, text: value })} />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}
          {!hasMetadata ? (
            <InfoBanner message="Generate protein annotation in Data > Annotation to generate the missed cleavage plot." />
          ) : (
            <ImagePlotCard title="Missed Cleavage Plot" url={missedCleavagePlotUrl} downloadName="peptide_missed_cleavage_plot.png" notebookEnabled />
          )}
        </>
      ) : null}

      {activeTab === "sequenceCoverage" ? (
        <>
          <SectionCard as="h2" title="Sequence Coverage Options">
            <OptionsLayout order="fields-size-toggles"
              fields={[
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
                <NumberField
                  key="chunk-size"
                  label="Chunk Size"
                  value={coverage.chunkSize}
                  onChange={(value) => setCoverage({ ...coverage, chunkSize: Math.max(10, Math.round(value)) })}
                />,
              ]}
            />
          </SectionCard>
          {advancedPlotOptions}

          {coverageLoading ? (
            <SectionCard as="h2" title="Sequence Coverage">
              <div className="text-sm text-slate-500">Calculating sequence coverage...</div>
            </SectionCard>
          ) : coverageError ? (
            <ErrorBanner message={coverageError} />
          ) : coverageResult ? (
            <>
              <SectionCard as="h2" title="Sequence Coverage Summary">
                <div className="grid gap-4 lg:grid-cols-3">
                  <SummaryCard label="Protein" value={coverageResult.protein} title={coverageResult.protein} />
                  <SummaryCard label="Coverage" value={`${coverageResult.coveragePercent}%`} />
                  <SummaryCard
                    label="Peptides mapped"
                    value={`${coverageResult.matchingPeptideCount} of ${coverageResult.assignedPeptideCount}`}
                  />
                </div>
                {coverageResult.warnings.length > 0 ? (
                  <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    {coverageResult.warnings.join(" ")}
                  </div>
                ) : null}
              </SectionCard>

              <SectionCard as="h2" title="Sequence Coverage">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-sm text-slate-600">Coverage map for the selected protein.</div>
                  {coverageDownloadUrl ? (
                    <div className="flex flex-wrap items-center gap-2">
                    <a
                      href={coverageDownloadUrl}
                      download={`${coverageResult.protein}_${coverageResult.species}_coverage.txt`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download TXT
                    </a>
                    <NotebookDownload plotUrl={coverageRequestUrl} rendered={coverageNotebook} />
                    </div>
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




function ImagePlotCard({
  title,
  url,
  downloadName,
  renderMode = "image",
  heightCm = 15,
  notebookEnabled = false,
}: {
  title: string;
  url: string;
  downloadName: string;
  renderMode?: "image" | "html";
  heightCm?: number;
  notebookEnabled?: boolean;
}) {
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>("png");
  const [notebook, setNotebook] = useState<RenderedNotebook | null>(null);

  const downloadUrl = withPlotDownloadFormat(url, downloadFormat);
  const downloadFilename = withPlotDownloadFilename(downloadName, downloadFormat);


  return (
    <SectionCard as="h2" title={title}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {renderMode === "image" ? (
          <div className="flex flex-wrap items-center gap-2">
            <PlotDownloadControls label="Plot" format={downloadFormat} onFormatChange={setDownloadFormat}
              href={downloadUrl} filename={downloadFilename} />
            {notebookEnabled ? <NotebookDownload plotUrl={url} rendered={notebook} /> : null}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
          >
            Open Interactive Plot
          </a>
          {notebookEnabled ? <NotebookDownload plotUrl={url} rendered={notebook} /> : null}
          </div>
        )}
      </div>
      {renderMode === "image" ? (
        <div className="mt-4">
          <PlotImage url={url} alt={title} onRendered={notebookEnabled ? (renderedUrl, token) => setNotebook({ url: renderedUrl, token }) : undefined} />
        </div>
      ) : notebookEnabled ? (
        <div className="mt-4">
          <InteractivePlot url={url} title={`${title} interactive`}
            height={`max(${cmToIframeHeight(heightCm)}px, 78vh)`}
            onRendered={(renderedUrl, token) => setNotebook({ url: renderedUrl, token })} />
        </div>
      ) : (
        <iframe
          sandbox="allow-scripts allow-downloads"
          key={url}
          src={url}
          title={`${title} interactive`}
          className="mt-4 block w-full rounded-xl border border-slate-200"
          style={{ height: `max(${cmToIframeHeight(heightCm)}px, 78vh)` }}
        />
      )}
    </SectionCard>
  );
}

function cmToIframeHeight(heightCm: number): number {
  return iframeHeightForPlot(heightCm, { fallbackCm: 15, minPx: 860, paddingPx: 280 });
}
