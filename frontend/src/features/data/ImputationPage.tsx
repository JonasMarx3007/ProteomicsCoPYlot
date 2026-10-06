import SummaryCard from "../../components/SummaryCard";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, downloadImputationCsv, getCurrentAnnotation, isAbortError, runImputation } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import type {
  AnnotationImputationInfo,
  AnnotationKind,
  ImputationResultResponse,
} from "../../lib/types";
import SelectField from "../../components/SelectField";
import PreviewTable from "../../components/PreviewTable";
import NumberField from "../../components/NumberField";

/** The imputation this session actually holds, however it was learned. */
type AppliedImputation = {
  method: "quantile" | "numerical";
  qValue: number;
  adjustStd: number;
  downShift: number;
  width: number;
  seed: number;
  sampleWise: boolean;
  rows: number | null;
  sampleCount: number | null;
  missingBefore: number | null;
  missingAfter: number | null;
};

function appliedFromAnnotation(info: AnnotationImputationInfo): AppliedImputation {
  const number = (value: number | null | undefined, fallback: number) =>
    typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return {
    method: String(info.mode).trim().toLowerCase() === "numerical" ? "numerical" : "quantile",
    qValue: number(info.qValue, 0.01),
    adjustStd: number(info.adjustStd, 0.3),
    downShift: number(info.downShift, 1.8),
    width: number(info.width, 0.3),
    seed: Math.round(number(info.seed, 1337)),
    sampleWise: Boolean(info.sampleWise),
    // `rowCount` is absent on a record written before it was stored; the
    // cards that need it are left out rather than filled with a guess.
    rows: typeof info.rowCount === "number" ? info.rowCount : null,
    sampleCount: typeof info.sampleCount === "number" ? info.sampleCount : null,
    missingBefore: typeof info.missingBefore === "number" ? info.missingBefore : null,
    missingAfter: typeof info.missingAfter === "number" ? info.missingAfter : null,
  };
}

export default function ImputationPage() {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const [kind, setKind] = useState<Exclude<AnnotationKind, "phosprot">>("protein");
  const datasets = useCurrentDatasetsSnapshot();
  const availableKinds = useMemo(
    () => datasets.availableKinds.filter((value) => value !== "phosprot"),
    [datasets.availableKinds]
  );
  const kindOptions = useMemo(
    () => datasets.kindOptions.filter((option) => option.value !== "phosprot"),
    [datasets.kindOptions]
  );
  const availableKindsKey = useMemo(() => availableKinds.join("|"), [availableKinds]);
  const [method, setMethod] = useState<"quantile" | "numerical">("quantile");
  const [qValue, setQValue] = useState(0.01);
  const [adjustStd, setAdjustStd] = useState(0.3);
  const [downShift, setDownShift] = useState(1.8);
  const [width, setWidth] = useState(0.3);
  const [seed, setSeed] = useState(1337);
  const [sampleWise, setSampleWise] = useState(true);
  const [showImputationDraw, setShowImputationDraw] = useState(true);
  const [afterNormalization, setAfterNormalization] = useState<"together" | "separate">("separate");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImputationResultResponse | null>(null);
  // What is actually stored for this level, as opposed to what the controls
  // currently say. Read back from the annotation on load, so it survives a
  // reload, and replaced when the button runs.
  const [applied, setApplied] = useState<AppliedImputation | null>(null);
  const [downloadingCsv, setDownloadingCsv] = useState(false);
  const [settingsReady, setSettingsReady] = useState(false);

  // Applying is a deliberate act. This call does not preview: it imputes and
  // stores the result as the session's imputed matrix, which every other panel
  // then reads. The page used to call it on every settings change, from a
  // function called `fetchPreview`, so typing a number into Downshift and
  // walking away replaced the matrix every volcano and PCA in the session was
  // about to use. The plots below are the preview -- they recompute from the
  // parameters in their own URLs and never touch what is stored.
  const applyImputation = useCallback(async (signal?: AbortSignal) => {
    if (!availableKinds.includes(kind)) {
      setResult(null);
      setError("Please upload a protein or phosphosite dataset first.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const response = await runImputation({
        kind,
        method,
        qValue,
        adjustStd,
        downShift,
        width,
        seed,
        sampleWise,
      }, { signal });
      setResult(response);
      setApplied({
        method: response.method,
        qValue: response.qValue,
        adjustStd: response.adjustStd,
        downShift: response.downShift,
        width: response.width,
        seed: response.seed,
        sampleWise: response.sampleWise,
        rows: response.rows,
        sampleCount: response.sampleColumns.length,
        missingBefore: response.missingBefore,
        missingAfter: response.missingAfter,
      });
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof Error ? err.message : "Imputation failed");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [adjustStd, availableKinds, downShift, kind, method, qValue, sampleWise, seed, width]);
  async function handleRun() {
    await applyImputation();
  }

  useEffect(() => {
    const controller = new AbortController();

    async function initializeKindSettings() {
      if (availableKinds.length === 0) {
        setResult(null);
        setApplied(null);
        setSettingsReady(false);
        return;
      }
      if (!availableKinds.includes(kind)) {
        setKind(availableKinds[0]);
        return;
      }

      setSettingsReady(false);
      try {
        const annotation = await getCurrentAnnotation(kind, { signal: controller.signal });
        const info = annotation.imputation;
        const mode = String(info?.mode ?? "").trim().toLowerCase();
        if (info && mode && mode !== "none") {
          setApplied(appliedFromAnnotation(info));
          setMethod(mode === "numerical" ? "numerical" : "quantile");
          setQValue(typeof info.qValue === "number" && Number.isFinite(info.qValue) ? info.qValue : 0.01);
          setAdjustStd(
            typeof info.adjustStd === "number" && Number.isFinite(info.adjustStd) ? info.adjustStd : 0.3
          );
          setDownShift(
            typeof info.downShift === "number" && Number.isFinite(info.downShift) ? info.downShift : 1.8
          );
          setWidth(typeof info.width === "number" && Number.isFinite(info.width) ? info.width : 0.3);
          setSeed(typeof info.seed === "number" && Number.isFinite(info.seed) ? Math.round(info.seed) : 1337);
          setSampleWise(Boolean(info.sampleWise));
        } else {
          setApplied(null);
          setMethod("quantile");
          setQValue(0.01);
          setAdjustStd(0.3);
          setDownShift(1.8);
          setWidth(0.3);
          setSeed(1337);
          setSampleWise(true);
        }
      } catch (error) {
        if (isAbortError(error)) return;
        setApplied(null);
        setMethod("quantile");
        setQValue(0.01);
        setAdjustStd(0.3);
        setDownShift(1.8);
        setWidth(0.3);
        setSeed(1337);
        setSampleWise(true);
      } finally {
        if (!controller.signal.aborted) {
          setSettingsReady(true);
        }
      }
    }

    setResult(null);
    void initializeKindSettings();
    return () => {
      controller.abort();
    };
  }, [kind, availableKinds, availableKindsKey]);

  const plotParams = useMemo(
    () => ({
      method,
      qValue,
      adjustStd,
      downShift,
      width,
      seed,
      sampleWise,
    }),
    [method, qValue, adjustStd, downShift, width, seed, sampleWise]
  );

  const beforePlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl(`/api/plots/imputation/${kind}/before-missing.png`, plotParams);
    },
    [kind, plotParams, advancedPlotSignal]
  );
  const overallPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl(`/api/plots/imputation/${kind}/overall-fit.png`, {
        ...plotParams,
        showImputationDraw,
        _plotVersion: 6,
      });
    },
    [kind, plotParams, showImputationDraw, advancedPlotSignal]
  );
  const afterPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl(`/api/plots/imputation/${kind}/after-imputation.png`, {
        ...plotParams,
        normalization: afterNormalization,
        _plotVersion: 6,
      });
    },
    [kind, plotParams, afterNormalization, advancedPlotSignal]
  );

  async function handleDownloadImputedCsv() {
    try {
      setDownloadingCsv(true);
      // The applied parameters, not the ones on screen. The draw is seeded, so
      // the same parameters reproduce the stored matrix exactly -- and this
      // button sits under "Imputed Data", which is what is stored.
      const source = applied ?? { method, qValue, adjustStd, downShift, width, seed, sampleWise };
      const blob = await downloadImputationCsv({
        kind,
        method: source.method,
        qValue: source.qValue,
        adjustStd: source.adjustStd,
        downShift: source.downShift,
        width: source.width,
        seed: source.seed,
        sampleWise: source.sampleWise,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `imputed_${kind}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download imputed CSV");
    } finally {
      setDownloadingCsv(false);
    }
  }

  const totalValueCount =
    applied && applied.rows !== null && applied.sampleCount !== null
      ? applied.rows * applied.sampleCount
      : null;
  const imputedValueCount =
    applied && applied.missingBefore !== null && applied.missingAfter !== null
      ? Math.max(0, applied.missingBefore - applied.missingAfter)
      : null;
  const imputedPercent =
    totalValueCount !== null && totalValueCount > 0 && imputedValueCount !== null
      ? `${((imputedValueCount / totalValueCount) * 100).toFixed(2)}%`
      : null;

  const plotsReady = settingsReady && kindOptions.length > 0 && availableKinds.includes(kind);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Impute Data</h2>
        <p className="mt-2 text-sm text-slate-600">
          Phosphoproteins cannot be imputed directly. Impute phosphosite data here first,
          then aggregate phosphoproteins using the imputed phosphosite source.
        </p>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(value) => {
              if (value === "protein" || value === "phospho") setKind(value);
            }}
            options={kindOptions}
          />
          <SelectField
            label="Method"
            value={method}
            onChange={(value) => setMethod(value === "numerical" ? "numerical" : "quantile")}
            options={[
              { value: "quantile", label: "Quantile" },
              { value: "numerical", label: "Numerical" },
            ]}
          />
        </div>

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <label className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={sampleWise}
              onChange={(e) => setSampleWise(e.target.checked)}
            />
            Sample-wise imputation
          </label>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {method === "quantile" ? (
            <>
              <NumberField assistant={false} label="Quantile" value={qValue} onChange={setQValue} step={0.001} />
              <NumberField assistant={false}
                label="Adjust standard deviation"
                value={adjustStd}
                onChange={setAdjustStd}
                step={0.1}
              />
            </>
          ) : (
            <>
              <NumberField assistant={false}
                label="Downshift"
                value={downShift}
                onChange={setDownShift}
                step={0.1}
              />
              <NumberField assistant={false}
                label="Adjust standard deviation"
                value={width}
                onChange={setWidth}
                step={0.1}
              />
            </>
          )}
          <NumberField assistant={false}
            label="Random seed"
            value={seed}
            onChange={(value) => setSeed(Math.round(value))}
          />
        </div>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleRun}
            disabled={loading || !availableKinds.includes(kind)}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Updating..." : "Impute Data Values"}
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein or phosphosite dataset in the Data tab to enable imputation plots.
        </section>
      ) : null}

      {plotsReady ? (
        <>
          <PlotSection
            alt="Before: With vs Without Missing Values"
            imageUrl={beforePlotUrl}
          />

          <PlotSection
            alt="Overall Distribution with Normal Fit"
            imageUrl={overallPlotUrl}
            controls={
              <label className="inline-flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={showImputationDraw}
                  onChange={(e) => setShowImputationDraw(e.target.checked)}
                />
                Show imputation draw distribution
              </label>
            }
          />

          <PlotSection
            alt="After: Non-Imputed vs Imputed Values"
            imageUrl={afterPlotUrl}
            controls={
              <div className="min-w-56">
                <select
                  aria-label="After-plot normalization"
                  value={afterNormalization}
                  onChange={(e) =>
                    setAfterNormalization(e.target.value as "together" | "separate")
                  }
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                >
                  <option value="separate">Separately</option>
                  <option value="together">Together</option>
                </select>
              </div>
            }
          />

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Applied imputation</h3>
            {applied ? (
              <>
                <p className="mt-2 text-sm text-slate-600">
                  The imputation this session is using: {describeSettings(applied)}. These
                  numbers describe that run, not the preview above, and change only when
                  you press <em>Impute Data Values</em> again.
                </p>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <SummaryCard label="Rows" value={applied.rows === null ? "--" : String(applied.rows)} />
                  <SummaryCard
                    label="Number of values"
                    value={totalValueCount === null ? "--" : String(totalValueCount)}
                  />
                  <SummaryCard
                    label="Number imputed"
                    value={imputedValueCount === null ? "--" : String(imputedValueCount)}
                  />
                  <SummaryCard label="Imputed %" value={imputedPercent ?? "--"} />
                </div>
              </>
            ) : (
              <p className="mt-2 text-sm text-slate-600">
                Nothing has been imputed for this level yet. The plots above are a preview;
                press <em>Impute Data Values</em> to run the imputation and store it.
              </p>
            )}
            {result && result.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {result.warnings.join(" ")}
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">Imputed Data</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleDownloadImputedCsv}
                  disabled={downloadingCsv || !applied}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {downloadingCsv ? "Downloading..." : "Download Full Imputed CSV"}
                </button>
              </div>
            </div>
            <div className="mt-4">
              {result ? (
                <PreviewTable rows={result.preview} emptyText="No imputed rows available." />
              ) : (
                <p className="text-sm text-slate-600">
                  {applied
                    ? "An imputation is applied. Run it again to show its first rows here, or download the full matrix."
                    : "Nothing has been imputed for this level yet."}
                </p>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

/** The parameters of a run, in one readable clause. */
function describeSettings(settings: {
  method: string;
  qValue: number;
  adjustStd: number;
  downShift: number;
  width: number;
  seed: number;
  sampleWise: boolean;
}): string {
  const shape =
    settings.method === "numerical"
      ? `downshift ${settings.downShift}, width ${settings.width}`
      : `quantile ${settings.qValue}, adjusted sd ${settings.adjustStd}`;
  const scope = settings.sampleWise ? "sample-wise" : "global";
  return `${settings.method}, ${shape}, ${scope}, seed ${settings.seed}`;
}

function PlotSection({
  alt,
  imageUrl,
  controls,
}: {
  alt: string;
  imageUrl: string;
  controls?: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      {controls ? <div className="mb-4">{controls}</div> : null}
      <div>
        <img key={imageUrl} src={imageUrl} alt={alt} className="w-full rounded-xl border border-slate-200" />
      </div>
    </section>
  );
}
