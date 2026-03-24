import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getQcPlotOptions, getQcTable } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import { saveQcReportSettings } from "../../lib/reportState";
import type { AnnotationKind, QcTab } from "../../lib/types";

type Props = {
  activeTab: QcTab;
};

type QcTableRequest = {
  tab: "coverage" | "boxplot" | "cv";
  params?: Record<string, string | number | boolean>;
};

export default function QCPipelinePage({ activeTab }: Props) {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [imageError, setImageError] = useState<string | null>(null);
  const [conditionOptions, setConditionOptions] = useState<string[]>([]);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);

  const [coverage, setCoverage] = useState({
    includeId: false,
    header: true,
    legend: true,
    summary: false,
    text: false,
    textSize: 9,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [hist, setHist] = useState({
    header: true,
    legend: true,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [box, setBox] = useState({
    mode: "Mean",
    outliers: false,
    includeId: false,
    header: true,
    legend: true,
    text: false,
    textSize: 9,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [cv, setCv] = useState({
    outliers: false,
    header: true,
    legend: true,
    text: false,
    textSize: 9,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [pca, setPca] = useState({
    type: "Normal",
    header: true,
    legend: true,
    plotDim: "2D",
    addEllipses: false,
    dotSize: 5,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [abundance, setAbundance] = useState({
    type: "Normal",
    header: true,
    legend: true,
    condition: "All Conditions",
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [correlation, setCorrelation] = useState({
    method: "Matrix",
    includeId: false,
    fullRange: false,
    widthCm: 20,
    heightCm: 16,
    dpi: 400,
  });

  useEffect(() => {
    if (!availableKinds.includes(kind)) return;
    saveQcReportSettings(kind, {
      coverage,
      hist,
      box,
      cv,
      pca,
      abundance,
      correlation,
    });
  }, [kind, availableKinds, coverage, hist, box, cv, pca, abundance, correlation]);

  useEffect(() => {
    if (availableKinds.length === 0) {
      setConditionOptions([]);
      return;
    }
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    if (!availableKinds.includes(kind)) {
      setConditionOptions([]);
      return;
    }
    let cancelled = false;
    getQcPlotOptions(kind)
      .then((payload) => {
        if (cancelled) return;
        const unique = Array.from(new Set(payload.conditions.map((value) => value.trim()).filter(Boolean)));
        setConditionOptions(unique);
      })
      .catch(() => {
        if (cancelled) return;
        setConditionOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [kind, availableKinds]);

  useEffect(() => {
    setAbundance((prev) => {
      if (prev.condition === "All Conditions") return prev;
      if (conditionOptions.includes(prev.condition)) return prev;
      return { ...prev, condition: "All Conditions" };
    });
  }, [conditionOptions]);

  const tableRequest = useMemo<QcTableRequest | null>(() => {
    if (activeTab === "coverage") {
      const params: Record<string, string | number | boolean> = {
        summary: coverage.summary,
      };
      return {
        tab: "coverage",
        params,
      };
    }
    if (activeTab === "boxplot") {
      const params: Record<string, string | number | boolean> = {
        mode: box.mode,
      };
      return {
        tab: "boxplot",
        params,
      };
    }
    if (activeTab === "cv") {
      return {
        tab: "cv",
        params: undefined,
      };
    }
    return null;
  }, [activeTab, coverage.summary, box.mode]);

  useEffect(() => {
    if (!availableKinds.includes(kind)) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }
    if (!tableRequest) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }

    let cancelled = false;
    setTableLoading(true);
    setTableError(null);

    getQcTable(kind, tableRequest.tab, tableRequest.params)
      .then((response) => {
        if (cancelled) return;
        setTableRows(response.rows ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load table");
      })
      .finally(() => {
        if (cancelled) return;
        setTableLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [kind, tableRequest, availableKinds]);

  const plotView = useMemo(() => {
    if (!availableKinds.includes(kind)) return null;
    if (activeTab === "coverage") {
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/coverage.png`, coverage) };
    }
    if (activeTab === "histogram") {
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/intensity-histogram.png`, hist) };
    }
    if (activeTab === "boxplot") {
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/boxplot.png`, box) };
    }
    if (activeTab === "cv") {
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/cv.png`, cv) };
    }
    if (activeTab === "pca") {
      const { type, ...params } = pca;
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/pca-interactive.html`, params),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/pca.png`, params) };
    }
    if (activeTab === "abundance") {
      const { type, ...params } = abundance;
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/abundance-interactive.html`, params),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/abundance.png`, params) };
    }
    return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/correlation.png`, correlation) };
  }, [activeTab, kind, coverage, hist, box, cv, pca, abundance, correlation, availableKinds]);

  const interactiveHeightPx = useMemo(() => {
    if (activeTab === "pca" && pca.type === "Interactive") {
      return cmToIframeHeight(pca.heightCm);
    }
    if (activeTab === "abundance" && abundance.type === "Interactive") {
      return cmToIframeHeight(abundance.heightCm);
    }
    return 760;
  }, [activeTab, pca.type, pca.heightCm, abundance.type, abundance.heightCm]);

  const tableCsvUrl = useMemo(() => {
    if (!tableRequest || tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableRows, columns))}`;
  }, [tableRequest, tableRows]);

  async function handleImageError(url: string) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed?.detail) {
            setImageError(parsed.detail);
            return;
          }
        } catch {}
      }
    } catch {}
    setImageError("Failed to load plot image. Check backend logs for details.");
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">QC Pipeline</h2>
        <div className="mt-4 max-w-xs">
          <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
          <select
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(e) => setKind(e.target.value as AnnotationKind)}
            disabled={kindOptions.length === 0}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
          >
            {kindOptions.length === 0 ? (
              <option value="">No dataset available</option>
            ) : (
              kindOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </select>
        </div>
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable QC plotting.
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        <div className="mt-4">{renderOptions()}</div>
      </section>
      ) : null}

      {kindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{tabTitle(activeTab)}</h3>
          {plotView?.mode === "image" ? (
            <a
              href={plotView?.url}
              download={`qc_${activeTab}_${kind}.png`}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Download Plot
            </a>
          ) : plotView ? (
            <a
              href={plotView.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Open Interactive Plot
            </a>
          ) : null}
        </div>
        <div className="mt-4">
          {plotView?.mode === "image" ? (
            <img
              key={plotView?.url}
              src={plotView?.url}
              alt={`${tabTitle(activeTab)} plot`}
              className="w-full rounded-xl border border-slate-200"
              onLoad={() => setImageError(null)}
              onError={() => {
                if (plotView?.url) handleImageError(plotView.url);
              }}
            />
          ) : plotView ? (
            <iframe
              key={plotView.url}
              src={plotView.url}
              title={`${tabTitle(activeTab)} interactive plot`}
              className="w-full rounded-xl border border-slate-200"
              style={{ height: `${interactiveHeightPx}px` }}
              onLoad={() => setImageError(null)}
            />
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              No plot available for the selected dataset.
            </div>
          )}
        </div>
        {imageError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {imageError}
          </div>
        ) : null}
      </section>
      ) : null}

      {kindOptions.length > 0 && tableRequest ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            {tableCsvUrl ? (
              <a
                href={tableCsvUrl}
                download={`qc_${activeTab}_${kind}_summary.csv`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download CSV
              </a>
            ) : null}
          </div>
          <div className="mt-4">
            {tableLoading ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                Loading table...
              </div>
            ) : tableError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {tableError}
              </div>
            ) : (
              <PreviewTable rows={tableRows} emptyText="No summary rows available." />
            )}
          </div>
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    if (activeTab === "coverage") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="id" label="Toggle IDs" checked={coverage.includeId} onChange={(v) => setCoverage({ ...coverage, includeId: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={coverage.header} onChange={(v) => setCoverage({ ...coverage, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={coverage.legend} onChange={(v) => setCoverage({ ...coverage, legend: v })} />,
            <Checkbox key="summary" label="Summary Type" checked={coverage.summary} onChange={(v) => setCoverage({ ...coverage, summary: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={coverage.text} onChange={(v) => setCoverage({ ...coverage, text: v })} />,
          ]}
          inputs={[
            <NumericField
              key="text-size"
              label="Text Size"
              value={coverage.textSize}
              onChange={(v) => setCoverage({ ...coverage, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={coverage.dpi}
              heightCm={coverage.heightCm}
              widthCm={coverage.widthCm}
              onDpiChange={(v) => setCoverage({ ...coverage, dpi: Math.round(v) })}
              onHeightChange={(v) => setCoverage({ ...coverage, heightCm: v })}
              onWidthChange={(v) => setCoverage({ ...coverage, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "histogram") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={hist.header} onChange={(v) => setHist({ ...hist, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={hist.legend} onChange={(v) => setHist({ ...hist, legend: v })} />,
          ]}
          sizeRow={
            <SizeRow
              dpi={hist.dpi}
              heightCm={hist.heightCm}
              widthCm={hist.widthCm}
              onDpiChange={(v) => setHist({ ...hist, dpi: Math.round(v) })}
              onHeightChange={(v) => setHist({ ...hist, heightCm: v })}
              onWidthChange={(v) => setHist({ ...hist, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "boxplot") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="outliers" label="Toggle Outliers" checked={box.outliers} onChange={(v) => setBox({ ...box, outliers: v })} />,
            <Checkbox key="id" label="Toggle IDs" checked={box.includeId} onChange={(v) => setBox({ ...box, includeId: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={box.header} onChange={(v) => setBox({ ...box, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={box.legend} onChange={(v) => setBox({ ...box, legend: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={box.text} onChange={(v) => setBox({ ...box, text: v })} />,
          ]}
          inputs={[
            <SelectField
              key="type"
              label="Type"
              value={box.mode}
              onChange={(value) => setBox({ ...box, mode: value })}
              options={["Mean", "Single"]}
            />,
            <NumericField
              key="text-size"
              label="Text Size"
              value={box.textSize}
              onChange={(v) => setBox({ ...box, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={box.dpi}
              heightCm={box.heightCm}
              widthCm={box.widthCm}
              onDpiChange={(v) => setBox({ ...box, dpi: Math.round(v) })}
              onHeightChange={(v) => setBox({ ...box, heightCm: v })}
              onWidthChange={(v) => setBox({ ...box, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "cv") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="outliers" label="Toggle Outliers" checked={cv.outliers} onChange={(v) => setCv({ ...cv, outliers: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={cv.header} onChange={(v) => setCv({ ...cv, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={cv.legend} onChange={(v) => setCv({ ...cv, legend: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={cv.text} onChange={(v) => setCv({ ...cv, text: v })} />,
          ]}
          inputs={[
            <NumericField
              key="text-size"
              label="Text Size"
              value={cv.textSize}
              onChange={(v) => setCv({ ...cv, textSize: Math.max(6, Math.min(20, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={cv.dpi}
              heightCm={cv.heightCm}
              widthCm={cv.widthCm}
              onDpiChange={(v) => setCv({ ...cv, dpi: Math.round(v) })}
              onHeightChange={(v) => setCv({ ...cv, heightCm: v })}
              onWidthChange={(v) => setCv({ ...cv, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "pca") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={pca.header} onChange={(v) => setPca({ ...pca, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={pca.legend} onChange={(v) => setPca({ ...pca, legend: v })} />,
            <Checkbox key="ellipses" label="Add Ellipses (2D)" checked={pca.addEllipses} onChange={(v) => setPca({ ...pca, addEllipses: v })} />,
          ]}
          inputs={[
            <SelectField
              key="type"
              label="Type"
              value={pca.type}
              onChange={(value) => setPca({ ...pca, type: value })}
              options={["Normal", "Interactive"]}
            />,
            <SelectField
              key="dim"
              label="Dimensions"
              value={pca.plotDim}
              onChange={(value) => setPca({ ...pca, plotDim: value })}
              options={["2D", "3D"]}
            />,
            <NumericField
              key="dot-size"
              label="Dot Size"
              value={pca.dotSize}
              onChange={(v) => setPca({ ...pca, dotSize: Math.max(1, Math.min(50, Math.round(v))) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={pca.dpi}
              heightCm={pca.heightCm}
              widthCm={pca.widthCm}
              onDpiChange={(v) => setPca({ ...pca, dpi: Math.round(v) })}
              onHeightChange={(v) => setPca({ ...pca, heightCm: v })}
              onWidthChange={(v) => setPca({ ...pca, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "abundance") {
      const abundanceConditions = ["All Conditions", ...conditionOptions];
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={abundance.header} onChange={(v) => setAbundance({ ...abundance, header: v })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={abundance.legend} onChange={(v) => setAbundance({ ...abundance, legend: v })} />,
          ]}
          inputs={[
            <SelectField
              key="type"
              label="Type"
              value={abundance.type}
              onChange={(value) => setAbundance({ ...abundance, type: value })}
              options={["Normal", "Interactive"]}
            />,
            <SelectField
              key="condition"
              label="Condition"
              value={abundance.condition}
              onChange={(value) => setAbundance({ ...abundance, condition: value || "All Conditions" })}
              options={abundanceConditions}
            />,
          ]}
          sizeRow={
            <SizeRow
              dpi={abundance.dpi}
              heightCm={abundance.heightCm}
              widthCm={abundance.widthCm}
              onDpiChange={(v) => setAbundance({ ...abundance, dpi: Math.round(v) })}
              onHeightChange={(v) => setAbundance({ ...abundance, heightCm: v })}
              onWidthChange={(v) => setAbundance({ ...abundance, widthCm: v })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        toggles={[
          <Checkbox key="id" label="Toggle IDs" checked={correlation.includeId} onChange={(v) => setCorrelation({ ...correlation, includeId: v })} />,
          <Checkbox key="full-range" label="Use Full Range" checked={correlation.fullRange} onChange={(v) => setCorrelation({ ...correlation, fullRange: v })} />,
        ]}
        inputs={[
          <SelectField
            key="method"
            label="Type"
            value={correlation.method}
            onChange={(value) => setCorrelation({ ...correlation, method: value })}
            options={["Matrix", "Ellipse"]}
          />,
        ]}
        sizeRow={
          <SizeRow
            dpi={correlation.dpi}
            heightCm={correlation.heightCm}
            widthCm={correlation.widthCm}
            onDpiChange={(v) => setCorrelation({ ...correlation, dpi: Math.round(v) })}
            onHeightChange={(v) => setCorrelation({ ...correlation, heightCm: v })}
            onWidthChange={(v) => setCorrelation({ ...correlation, widthCm: v })}
          />
        }
      />
    );
  }
}

function OptionsLayout({
  toggles,
  inputs,
  sizeRow,
}: {
  toggles: ReactNode[];
  inputs?: ReactNode[];
  sizeRow: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">{toggles}</div>
      {inputs && inputs.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-3">{inputs}</div>
      ) : null}
      <div>{sizeRow}</div>
    </div>
  );
}

function SizeRow({
  dpi,
  heightCm,
  widthCm,
  onDpiChange,
  onHeightChange,
  onWidthChange,
}: {
  dpi: number;
  heightCm: number;
  widthCm: number;
  onDpiChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onWidthChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="DPI" value={dpi} onChange={onDpiChange} />
      <NumericField label="Height (cm)" value={heightCm} onChange={onHeightChange} />
      <NumericField label="Width (cm)" value={widthCm} onChange={onWidthChange} />
    </div>
  );
}

function tabTitle(tab: QcTab): string {
  switch (tab) {
    case "coverage":
      return "Coverage Plot";
    case "histogram":
      return "Histogram Intensity";
    case "boxplot":
      return "Boxplot Intensity";
    case "cv":
      return "Cov Plot";
    case "pca":
      return "Principal Component Analysis";
    case "abundance":
      return "Abundance Plot";
    case "correlation":
      return "Correlation Plot";
  }
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function NumericField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(() => (Number.isFinite(value) ? String(value) : ""));

  useEffect(() => {
    setDraft(Number.isFinite(value) ? String(value) : "");
  }, [value]);

  const commit = () => {
    const normalized = draft.trim().replace(",", ".");
    if (!normalized) {
      setDraft(Number.isFinite(value) ? String(value) : "");
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed)) {
      setDraft(Number.isFinite(value) ? String(value) : "");
      return;
    }
    onChange(parsed);
    setDraft(String(parsed));
  };

  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(e) => {
          const normalized = e.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
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

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
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
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  const columns = useMemo(() => collectColumns(rows), [rows]);

  if (rows.length === 0 || columns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
              {columns.map((column) => {
                const value = row[column];
                const text = value == null ? "" : String(value);
                return (
                  <td
                    key={`${rowIndex}-${column}`}
                    className="border-b border-slate-100 px-3 py-2 text-slate-600"
                    title={text}
                  >
                    <div className="max-w-[28ch] overflow-hidden text-ellipsis whitespace-nowrap">
                      {text}
                    </div>
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

function collectColumns(rows: Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => seen.add(key));
  });
  return Array.from(seen);
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]): string {
  if (rows.length === 0 || columns.length === 0) return "";
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ];
  return lines.join("\n");
}

function cmToIframeHeight(heightCm: number): number {
  const basePx = Number.isFinite(heightCm) ? (heightCm * 96) / 2.54 : (10 * 96) / 2.54;
  return Math.max(760, Math.round(basePx + 220));
}
