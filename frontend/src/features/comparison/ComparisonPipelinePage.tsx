import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getComparisonOptions, getComparisonTable } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { AnnotationKind, ComparisonOptionsResponse, ComparisonTab } from "../../lib/types";

type Props = {
  activeTab: ComparisonTab;
};

type PlotView = {
  title: string;
  url: string;
  filename: string;
} | null;

type TableRequest = {
  tab: ComparisonTab;
  params: Record<string, string | number | boolean>;
} | null;

export default function ComparisonPipelinePage({ activeTab }: Props) {
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [options, setOptions] = useState<ComparisonOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);

  const [pearson, setPearson] = useState({
    mode: "Single",
    sample1: "",
    sample2: "",
    condition1: "",
    condition2: "",
    alias1: "",
    alias2: "",
    color: "#1f77b4",
    dotSize: 60,
    header: true,
    widthCm: 20,
    heightCm: 12,
    dpi: 300,
  });

  const [venn, setVenn] = useState({
    mode: "Single",
    first: "",
    second: "",
    third: "",
    alias1: "",
    alias2: "",
    alias3: "",
    color1: "#1f77b4",
    color2: "#ff7f0e",
    color3: "#2ca02c",
    header: true,
    widthCm: 15,
    heightCm: 12,
    dpi: 300,
  });

  const hasKind = availableKinds.includes(kind);

  useEffect(() => {
    if (availableKinds.length === 0) {
      setOptions(null);
      return;
    }
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    if (!hasKind) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError(null);
      return;
    }

    let cancelled = false;
    setOptionsLoading(true);
    setOptionsError(null);
    getComparisonOptions(kind)
      .then((payload) => {
        if (cancelled) return;
        setOptions(payload);
      })
      .catch((err) => {
        if (cancelled) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load comparison options");
      })
      .finally(() => {
        if (cancelled) return;
        setOptionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hasKind, kind]);

  useEffect(() => {
    if (!options) return;
    const samples = options.samples ?? [];
    const conditions = options.conditions ?? [];

    setPearson((prev) => {
      const sample1 = samples.includes(prev.sample1) ? prev.sample1 : samples[0] ?? "";
      const sample2 =
        samples.includes(prev.sample2) && prev.sample2 !== sample1
          ? prev.sample2
          : samples.find((value) => value !== sample1) ?? "";
      const condition1 = conditions.includes(prev.condition1) ? prev.condition1 : conditions[0] ?? "";
      const condition2 =
        conditions.includes(prev.condition2) && prev.condition2 !== condition1
          ? prev.condition2
          : conditions.find((value) => value !== condition1) ?? "";
      return { ...prev, sample1, sample2, condition1, condition2 };
    });
  }, [options]);

  useEffect(() => {
    if (!options) return;
    const pool = venn.mode === "Single" ? options.samples ?? [] : options.conditions ?? [];

    setVenn((prev) => {
      const first = pool.includes(prev.first) ? prev.first : pool[0] ?? "";
      const second =
        pool.includes(prev.second) && prev.second !== first
          ? prev.second
          : pool.find((value) => value !== first) ?? "";
      const third =
        prev.third && pool.includes(prev.third) && prev.third !== first && prev.third !== second
          ? prev.third
          : "";
      return { ...prev, first, second, third };
    });
  }, [options, venn.mode]);

  const pearsonReady = useMemo(() => {
    if (pearson.mode === "Single") {
      return Boolean(pearson.sample1 && pearson.sample2 && pearson.sample1 !== pearson.sample2);
    }
    return Boolean(
      pearson.condition1 && pearson.condition2 && pearson.condition1 !== pearson.condition2
    );
  }, [pearson]);

  const vennReady = useMemo(() => {
    if (!venn.first || !venn.second || venn.first === venn.second) return false;
    if (!venn.third) return true;
    return venn.third !== venn.first && venn.third !== venn.second;
  }, [venn]);

  const plotView = useMemo<PlotView>(() => {
    if (!hasKind) return null;

    if (activeTab === "pearson") {
      if (!pearsonReady) return null;
      const params: Record<string, string | number | boolean> = {
        mode: pearson.mode,
        sample1: pearson.sample1,
        sample2: pearson.sample2,
        condition1: pearson.condition1,
        condition2: pearson.condition2,
        alias1: pearson.alias1,
        alias2: pearson.alias2,
        color: pearson.color,
        dotSize: pearson.dotSize,
        header: pearson.header,
        widthCm: pearson.widthCm,
        heightCm: pearson.heightCm,
        dpi: pearson.dpi,
      };
      return {
        title: "Pearson Correlation",
        filename: `comparison_pearson_${kind}.png`,
        url: buildPlotUrl(`/api/plots/comparison/${kind}/pearson.png`, params),
      };
    }

    if (!vennReady) return null;
    const params: Record<string, string | number | boolean> = {
      mode: venn.mode,
      first: venn.first,
      second: venn.second,
      third: venn.third,
      alias1: venn.alias1,
      alias2: venn.alias2,
      alias3: venn.alias3,
      color1: venn.color1,
      color2: venn.color2,
      color3: venn.color3,
      header: venn.header,
      widthCm: venn.widthCm,
      heightCm: venn.heightCm,
      dpi: venn.dpi,
    };
    return {
      title: "Venn Diagram",
      filename: `comparison_venn_${kind}.png`,
      url: buildPlotUrl(`/api/plots/comparison/${kind}/venn.png`, params),
    };
  }, [activeTab, hasKind, kind, pearson, pearsonReady, venn, vennReady]);

  const tableRequest = useMemo<TableRequest>(() => {
    if (!hasKind) return null;
    if (activeTab === "pearson") {
      if (!pearsonReady) return null;
      const params: Record<string, string | number | boolean> = {
        mode: pearson.mode,
        sample1: pearson.sample1,
        sample2: pearson.sample2,
        condition1: pearson.condition1,
        condition2: pearson.condition2,
        alias1: pearson.alias1,
        alias2: pearson.alias2,
      };
      return {
        tab: "pearson",
        params,
      };
    }
    if (!vennReady) return null;
    const params: Record<string, string | number | boolean> = {
      mode: venn.mode,
      first: venn.first,
      second: venn.second,
      third: venn.third,
      alias1: venn.alias1,
      alias2: venn.alias2,
      alias3: venn.alias3,
    };
    return {
      tab: "venn",
      params,
    };
  }, [activeTab, hasKind, pearson, pearsonReady, venn, vennReady]);

  useEffect(() => {
    if (!tableRequest || !hasKind) {
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }

    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    getComparisonTable(kind, tableRequest.tab, tableRequest.params)
      .then((payload) => {
        if (cancelled) return;
        setTableRows(payload.rows ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load comparison table");
      })
      .finally(() => {
        if (cancelled) return;
        setTableLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hasKind, kind, tableRequest]);

  const tableCsvUrl = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableRows, columns))}`;
  }, [tableRows]);

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

  const modePool = activeTab === "pearson"
    ? (pearson.mode === "Single" ? options?.samples ?? [] : options?.conditions ?? [])
    : (venn.mode === "Single" ? options?.samples ?? [] : options?.conditions ?? []);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Comparison Pipeline</h2>
        <div className="mt-4 max-w-xs">
          <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
          <select
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(event) => setKind(event.target.value as AnnotationKind)}
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
          Upload a protein or phospho dataset in the Data tab to enable comparison plots.
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Options</h3>
          {optionsLoading ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Loading options...
            </div>
          ) : optionsError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {optionsError}
            </div>
          ) : (
            <div className="mt-4">{renderOptions()}</div>
          )}
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">{activeTab === "pearson" ? "Pearson Correlation" : "Venn Diagram"}</h3>
            {plotView ? (
              <a
                href={plotView.url}
                download={plotView.filename}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            ) : null}
          </div>

          {plotView ? (
            <div className="mt-4">
              <img
                key={plotView.url}
                src={plotView.url}
                alt={plotView.title}
                className="w-full rounded-xl border border-slate-200"
                onLoad={() => setImageError(null)}
                onError={() => {
                  handleImageError(plotView.url);
                }}
              />
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              {modePool.length === 0
                ? "No selectable samples/conditions are available for this dataset."
                : "Select valid entries to render the plot."}
            </div>
          )}

          {imageError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {imageError}
            </div>
          ) : null}
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            {tableCsvUrl ? (
              <a
                href={tableCsvUrl}
                download={`comparison_${activeTab}_${kind}.csv`}
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
              <PreviewTable rows={tableRows} emptyText="No table rows available for the current selection." />
            )}
          </div>
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    const samples = options?.samples ?? [];
    const conditions = options?.conditions ?? [];

    if (activeTab === "pearson") {
      const pool = pearson.mode === "Single" ? samples : conditions;
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="mode"
              label="Mode"
              value={pearson.mode}
              options={["Single", "Condition"]}
              onChange={(value) => setPearson({ ...pearson, mode: value })}
            />,
            <SelectField
              key="first"
              label={pearson.mode === "Single" ? "Sample 1" : "Condition 1"}
              value={pearson.mode === "Single" ? pearson.sample1 : pearson.condition1}
              options={pool}
              onChange={(value) =>
                pearson.mode === "Single"
                  ? setPearson({ ...pearson, sample1: value })
                  : setPearson({ ...pearson, condition1: value })
              }
            />,
            <SelectField
              key="second"
              label={pearson.mode === "Single" ? "Sample 2" : "Condition 2"}
              value={pearson.mode === "Single" ? pearson.sample2 : pearson.condition2}
              options={pool}
              onChange={(value) =>
                pearson.mode === "Single"
                  ? setPearson({ ...pearson, sample2: value })
                  : setPearson({ ...pearson, condition2: value })
              }
            />,
            <TextField key="alias1" label="Alias 1 (optional)" value={pearson.alias1} onChange={(value) => setPearson({ ...pearson, alias1: value })} />,
            <TextField key="alias2" label="Alias 2 (optional)" value={pearson.alias2} onChange={(value) => setPearson({ ...pearson, alias2: value })} />,
            <ColorField key="color" label="Dot Color" value={pearson.color} onChange={(value) => setPearson({ ...pearson, color: value })} />,
            <NumericField key="dotSize" label="Dot Size" value={pearson.dotSize} onChange={(value) => setPearson({ ...pearson, dotSize: Math.max(1, value) })} step={1} />,
          ]}
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={pearson.header} onChange={(value) => setPearson({ ...pearson, header: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={pearson.widthCm}
              heightCm={pearson.heightCm}
              dpi={pearson.dpi}
              onWidthChange={(value) => setPearson({ ...pearson, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setPearson({ ...pearson, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setPearson({ ...pearson, dpi: Math.max(72, Math.round(value)) })}
            />
          }
        />
      );
    }

    const vennPool = venn.mode === "Single" ? samples : conditions;
    return (
      <OptionsLayout
        fields={[
          <SelectField
            key="mode"
            label="Mode"
            value={venn.mode}
            options={["Single", "Condition"]}
            onChange={(value) => setVenn({ ...venn, mode: value })}
          />,
          <SelectField
            key="first"
            label={venn.mode === "Single" ? "Sample 1" : "Condition 1"}
            value={venn.first}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, first: value })}
          />,
          <SelectField
            key="second"
            label={venn.mode === "Single" ? "Sample 2" : "Condition 2"}
            value={venn.second}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, second: value })}
          />,
          <SelectField
            key="third"
            label={venn.mode === "Single" ? "Sample 3 (optional)" : "Condition 3 (optional)"}
            value={venn.third}
            options={["", ...vennPool]}
            onChange={(value) => setVenn({ ...venn, third: value })}
          />,
          <TextField key="alias1" label="Alias 1 (optional)" value={venn.alias1} onChange={(value) => setVenn({ ...venn, alias1: value })} />,
          <TextField key="alias2" label="Alias 2 (optional)" value={venn.alias2} onChange={(value) => setVenn({ ...venn, alias2: value })} />,
          <TextField key="alias3" label="Alias 3 (optional)" value={venn.alias3} onChange={(value) => setVenn({ ...venn, alias3: value })} />,
          <ColorField key="color1" label="Color 1" value={venn.color1} onChange={(value) => setVenn({ ...venn, color1: value })} />,
          <ColorField key="color2" label="Color 2" value={venn.color2} onChange={(value) => setVenn({ ...venn, color2: value })} />,
          <ColorField key="color3" label="Color 3" value={venn.color3} onChange={(value) => setVenn({ ...venn, color3: value })} />,
        ]}
        toggles={[
          <Checkbox key="header" label="Toggle Header" checked={venn.header} onChange={(value) => setVenn({ ...venn, header: value })} />,
        ]}
        sizeRow={
          <SizeRow
            widthCm={venn.widthCm}
            heightCm={venn.heightCm}
            dpi={venn.dpi}
            onWidthChange={(value) => setVenn({ ...venn, widthCm: Math.max(1, value) })}
            onHeightChange={(value) => setVenn({ ...venn, heightCm: Math.max(1, value) })}
            onDpiChange={(value) => setVenn({ ...venn, dpi: Math.max(72, Math.round(value)) })}
          />
        }
      />
    );
  }
}

function OptionsLayout({
  fields,
  toggles,
  sizeRow,
}: {
  fields: ReactNode[];
  toggles: ReactNode[];
  sizeRow: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">{fields}</div>
      <div className="flex flex-wrap gap-3">{toggles}</div>
      <div>{sizeRow}</div>
    </div>
  );
}

function SizeRow({
  widthCm,
  heightCm,
  dpi,
  onWidthChange,
  onHeightChange,
  onDpiChange,
}: {
  widthCm: number;
  heightCm: number;
  dpi: number;
  onWidthChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onDpiChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="Width (cm)" value={widthCm} onChange={onWidthChange} />
      <NumericField label="Height (cm)" value={heightCm} onChange={onHeightChange} />
      <NumericField label="DPI" value={dpi} onChange={onDpiChange} step={1} />
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
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
          <option key={option} value={option}>
            {option || "None"}
          </option>
        ))}
      </select>
    </label>
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

function NumericField({
  label,
  value,
  onChange,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="number"
        lang="en-US"
        inputMode="decimal"
        step={step}
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

function ColorField({
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
        type="color"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1"
      />
    </label>
  );
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
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
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
  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const columns = collectColumns(rows);
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
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
          {rows.map((row, index) => (
            <tr key={index} className={index % 2 ? "bg-slate-50/40" : "bg-white"}>
              {columns.map((column) => (
                <td key={column} className="px-4 py-2 align-top text-sm text-slate-700">
                  {formatValue(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function collectColumns(rows: Record<string, unknown>[]) {
  const keys = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => keys.add(key));
  });
  return Array.from(keys);
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]) {
  const header = columns.join(",");
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const raw = row[column];
        const text = raw == null ? "" : String(raw);
        if (text.includes(",") || text.includes('"') || text.includes("\n")) {
          return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
      })
      .join(",")
  );
  return [header, ...body].join("\n");
}

function formatValue(value: unknown) {
  if (value == null) return "";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
