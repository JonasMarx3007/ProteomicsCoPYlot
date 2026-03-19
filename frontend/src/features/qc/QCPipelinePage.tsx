import { useEffect, useMemo, useState } from "react";
import { buildPlotUrl, getQcPlotOptions } from "../../lib/api";
import type { AnnotationKind, QcTab } from "../../lib/types";

type Props = {
  activeTab: QcTab;
};

export default function QCPipelinePage({ activeTab }: Props) {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [imageError, setImageError] = useState<string | null>(null);
  const [conditionOptions, setConditionOptions] = useState<string[]>([]);

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
    widthCm: 10,
    heightCm: 8,
    dpi: 100,
  });

  useEffect(() => {
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
  }, [kind]);

  useEffect(() => {
    setAbundance((prev) => {
      if (prev.condition === "All Conditions") return prev;
      if (conditionOptions.includes(prev.condition)) return prev;
      return { ...prev, condition: "All Conditions" };
    });
  }, [conditionOptions]);

  const imageUrl = useMemo(() => {
    if (activeTab === "coverage") {
      return buildPlotUrl(`/api/plots/qc/${kind}/coverage.png`, coverage);
    }
    if (activeTab === "histogram") {
      return buildPlotUrl(`/api/plots/qc/${kind}/intensity-histogram.png`, hist);
    }
    if (activeTab === "boxplot") {
      return buildPlotUrl(`/api/plots/qc/${kind}/boxplot.png`, box);
    }
    if (activeTab === "cv") {
      return buildPlotUrl(`/api/plots/qc/${kind}/cv.png`, cv);
    }
    if (activeTab === "pca") {
      return buildPlotUrl(`/api/plots/qc/${kind}/pca.png`, pca);
    }
    if (activeTab === "abundance") {
      return buildPlotUrl(`/api/plots/qc/${kind}/abundance.png`, abundance);
    }
    return buildPlotUrl(`/api/plots/qc/${kind}/correlation.png`, correlation);
  }, [activeTab, kind, coverage, hist, box, cv, pca, abundance, correlation]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">QC Pipeline</h2>
        <div className="mt-4 max-w-xs">
          <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as AnnotationKind)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
          >
            <option value="protein">Protein</option>
            <option value="phospho">Phospho</option>
          </select>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        <div className="mt-4">{renderOptions()}</div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">{tabTitle(activeTab)}</h3>
        <div className="mt-4">
          <img
            key={imageUrl}
            src={imageUrl}
            alt={`${tabTitle(activeTab)} plot`}
            className="w-full rounded-xl border border-slate-200"
            onLoad={() => setImageError(null)}
            onError={() => setImageError("Failed to load plot image. Check backend logs for details.")}
          />
        </div>
        {imageError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {imageError}
          </div>
        ) : null}
      </section>
    </div>
  );

  function renderOptions() {
    if (activeTab === "coverage") {
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <Checkbox label="Toggle IDs" checked={coverage.includeId} onChange={(v) => setCoverage({ ...coverage, includeId: v })} />
          <Checkbox label="Toggle Header" checked={coverage.header} onChange={(v) => setCoverage({ ...coverage, header: v })} />
          <Checkbox label="Toggle Legend" checked={coverage.legend} onChange={(v) => setCoverage({ ...coverage, legend: v })} />
          <Checkbox label="Summary Type" checked={coverage.summary} onChange={(v) => setCoverage({ ...coverage, summary: v })} />
          <Checkbox label="Toggle Text" checked={coverage.text} onChange={(v) => setCoverage({ ...coverage, text: v })} />
          <NumericField label="Text Size" value={coverage.textSize} onChange={(v) => setCoverage({ ...coverage, textSize: Math.max(6, Math.min(20, Math.round(v))) })} />
          <NumericField label="Width (cm)" value={coverage.widthCm} onChange={(v) => setCoverage({ ...coverage, widthCm: v })} />
          <NumericField label="Height (cm)" value={coverage.heightCm} onChange={(v) => setCoverage({ ...coverage, heightCm: v })} />
          <NumericField label="DPI" value={coverage.dpi} onChange={(v) => setCoverage({ ...coverage, dpi: Math.round(v) })} />
        </div>
      );
    }

    if (activeTab === "histogram") {
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <Checkbox label="Toggle Header" checked={hist.header} onChange={(v) => setHist({ ...hist, header: v })} />
          <Checkbox label="Toggle Legend" checked={hist.legend} onChange={(v) => setHist({ ...hist, legend: v })} />
          <NumericField label="Width (cm)" value={hist.widthCm} onChange={(v) => setHist({ ...hist, widthCm: v })} />
          <NumericField label="Height (cm)" value={hist.heightCm} onChange={(v) => setHist({ ...hist, heightCm: v })} />
          <NumericField label="DPI" value={hist.dpi} onChange={(v) => setHist({ ...hist, dpi: Math.round(v) })} />
        </div>
      );
    }

    if (activeTab === "boxplot") {
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <SelectField
            label="Type"
            value={box.mode}
            onChange={(value) => setBox({ ...box, mode: value })}
            options={["Mean", "Single"]}
          />
          <Checkbox label="Toggle Outliers" checked={box.outliers} onChange={(v) => setBox({ ...box, outliers: v })} />
          <Checkbox label="Toggle IDs" checked={box.includeId} onChange={(v) => setBox({ ...box, includeId: v })} />
          <Checkbox label="Toggle Header" checked={box.header} onChange={(v) => setBox({ ...box, header: v })} />
          <Checkbox label="Toggle Legend" checked={box.legend} onChange={(v) => setBox({ ...box, legend: v })} />
          <Checkbox label="Toggle Text" checked={box.text} onChange={(v) => setBox({ ...box, text: v })} />
          <NumericField label="Text Size" value={box.textSize} onChange={(v) => setBox({ ...box, textSize: Math.max(6, Math.min(20, Math.round(v))) })} />
          <NumericField label="Width (cm)" value={box.widthCm} onChange={(v) => setBox({ ...box, widthCm: v })} />
          <NumericField label="Height (cm)" value={box.heightCm} onChange={(v) => setBox({ ...box, heightCm: v })} />
          <NumericField label="DPI" value={box.dpi} onChange={(v) => setBox({ ...box, dpi: Math.round(v) })} />
        </div>
      );
    }

    if (activeTab === "cv") {
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <Checkbox label="Toggle Outliers" checked={cv.outliers} onChange={(v) => setCv({ ...cv, outliers: v })} />
          <Checkbox label="Toggle Header" checked={cv.header} onChange={(v) => setCv({ ...cv, header: v })} />
          <Checkbox label="Toggle Legend" checked={cv.legend} onChange={(v) => setCv({ ...cv, legend: v })} />
          <Checkbox label="Toggle Text" checked={cv.text} onChange={(v) => setCv({ ...cv, text: v })} />
          <NumericField label="Text Size" value={cv.textSize} onChange={(v) => setCv({ ...cv, textSize: Math.max(6, Math.min(20, Math.round(v))) })} />
          <NumericField label="Width (cm)" value={cv.widthCm} onChange={(v) => setCv({ ...cv, widthCm: v })} />
          <NumericField label="Height (cm)" value={cv.heightCm} onChange={(v) => setCv({ ...cv, heightCm: v })} />
          <NumericField label="DPI" value={cv.dpi} onChange={(v) => setCv({ ...cv, dpi: Math.round(v) })} />
        </div>
      );
    }

    if (activeTab === "pca") {
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <Checkbox label="Toggle Header" checked={pca.header} onChange={(v) => setPca({ ...pca, header: v })} />
          <Checkbox label="Toggle Legend" checked={pca.legend} onChange={(v) => setPca({ ...pca, legend: v })} />
          <SelectField
            label="Dimensions"
            value={pca.plotDim}
            onChange={(value) => setPca({ ...pca, plotDim: value })}
            options={["2D", "3D"]}
          />
          <Checkbox label="Add Ellipses (2D)" checked={pca.addEllipses} onChange={(v) => setPca({ ...pca, addEllipses: v })} />
          <NumericField label="Dot Size" value={pca.dotSize} onChange={(v) => setPca({ ...pca, dotSize: Math.max(1, Math.min(50, Math.round(v))) })} />
          <NumericField label="Width (cm)" value={pca.widthCm} onChange={(v) => setPca({ ...pca, widthCm: v })} />
          <NumericField label="Height (cm)" value={pca.heightCm} onChange={(v) => setPca({ ...pca, heightCm: v })} />
          <NumericField label="DPI" value={pca.dpi} onChange={(v) => setPca({ ...pca, dpi: Math.round(v) })} />
        </div>
      );
    }

    if (activeTab === "abundance") {
      const abundanceConditions = ["All Conditions", ...conditionOptions];
      return (
        <div className="grid gap-4 lg:grid-cols-4">
          <Checkbox label="Toggle Header" checked={abundance.header} onChange={(v) => setAbundance({ ...abundance, header: v })} />
          <Checkbox label="Toggle Legend" checked={abundance.legend} onChange={(v) => setAbundance({ ...abundance, legend: v })} />
          <SelectField
            label="Condition"
            value={abundance.condition}
            onChange={(value) => setAbundance({ ...abundance, condition: value || "All Conditions" })}
            options={abundanceConditions}
          />
          <NumericField label="Width (cm)" value={abundance.widthCm} onChange={(v) => setAbundance({ ...abundance, widthCm: v })} />
          <NumericField label="Height (cm)" value={abundance.heightCm} onChange={(v) => setAbundance({ ...abundance, heightCm: v })} />
          <NumericField label="DPI" value={abundance.dpi} onChange={(v) => setAbundance({ ...abundance, dpi: Math.round(v) })} />
        </div>
      );
    }

    return (
      <div className="grid gap-4 lg:grid-cols-4">
        <SelectField
          label="Type"
          value={correlation.method}
          onChange={(value) => setCorrelation({ ...correlation, method: value })}
          options={["Matrix", "Ellipse"]}
        />
        <Checkbox label="Toggle IDs" checked={correlation.includeId} onChange={(v) => setCorrelation({ ...correlation, includeId: v })} />
        <Checkbox label="Use Full Range" checked={correlation.fullRange} onChange={(v) => setCorrelation({ ...correlation, fullRange: v })} />
        <NumericField label="Width (cm)" value={correlation.widthCm} onChange={(v) => setCorrelation({ ...correlation, widthCm: v })} />
        <NumericField label="Height (cm)" value={correlation.heightCm} onChange={(v) => setCorrelation({ ...correlation, heightCm: v })} />
        <NumericField label="DPI" value={correlation.dpi} onChange={(v) => setCorrelation({ ...correlation, dpi: Math.round(v) })} />
      </div>
    );
  }
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
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(globalThis.Number(e.target.value))}
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
