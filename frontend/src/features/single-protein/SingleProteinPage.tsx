import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getSingleProteinOptions, getSingleProteinTable } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import type {
  AnnotationKind,
  SingleProteinIdentifier,
  SingleProteinOptionsResponse,
  SingleProteinTab,
} from "../../lib/types";

type Props = {
  activeTab: SingleProteinTab;
};

type PlotView = {
  title: string;
  url: string;
  filename: string;
} | null;

type TableRequest = {
  kind: AnnotationKind;
  tab: "boxplot" | "lineplot" | "heatmap";
  params: Record<string, string | number | boolean>;
};

export default function SingleProteinPage({ activeTab }: Props) {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [options, setOptions] = useState<SingleProteinOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>("png");

  const [box, setBox] = useState({
    identifier: "workflow" as SingleProteinIdentifier,
    protein: "",
    conditions: [] as string[],
    outliers: false,
    dots: false,
    header: true,
    legend: true,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [line, setLine] = useState({
    identifier: "workflow" as SingleProteinIdentifier,
    proteins: [] as string[],
    conditions: [] as string[],
    includeId: false,
    header: true,
    legend: true,
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [heatmap, setHeatmap] = useState({
    identifier: "workflow" as SingleProteinIdentifier,
    protein: "",
    conditions: [] as string[],
    includeId: false,
    header: true,
    filterM1: true,
    clusterRows: false,
    clusterCols: false,
    valueType: "log2",
    cmap: "plasma",
    widthCm: 20,
    heightCm: 12,
    dpi: 300,
  });

  const effectiveKind: AnnotationKind = activeTab === "heatmap" ? "phospho" : kind;
  const activeIdentifier: SingleProteinIdentifier =
    activeTab === "boxplot" ? box.identifier : activeTab === "lineplot" ? line.identifier : heatmap.identifier;
  const hasPhospho = availableKinds.includes("phospho");
  const hasRequiredDataset = activeTab === "heatmap" ? hasPhospho : availableKinds.includes(effectiveKind);

  useEffect(() => {
    if (activeTab === "heatmap") return;
    if (availableKinds.length === 0) return;
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [activeTab, availableKinds, kind]);

  useEffect(() => {
    if (!hasRequiredDataset) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError(
        activeTab === "heatmap"
          ? "Upload a phospho dataset to use this tab."
          : "Upload a protein, phospho, or phosphoprotein dataset to use this tab."
      );
      return;
    }

    let cancelled = false;
    setOptionsLoading(true);
    setOptionsError(null);
    getSingleProteinOptions(effectiveKind, activeTab, activeIdentifier)
      .then((data) => {
        if (cancelled) return;
        setOptions(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load options");
      })
      .finally(() => {
        if (cancelled) return;
        setOptionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeTab, effectiveKind, hasRequiredDataset, activeIdentifier]);

  useEffect(() => {
    if (!options) return;
    const proteinChoices = options.proteins ?? [];
    const conditionChoices = options.conditions ?? [];

    if (activeTab === "boxplot") {
      setBox((prev) => {
        const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
        const nextIdentifier = validIdentifiers.has(prev.identifier)
          ? prev.identifier
          : (options.identifier ?? "workflow");
        const nextProtein =
          prev.protein && proteinChoices.includes(prev.protein) ? prev.protein : proteinChoices[0] ?? "";
        const filtered = prev.conditions.filter((value) => conditionChoices.includes(value));
        const nextConditions = filtered.length > 0 ? filtered : [...conditionChoices];
        return { ...prev, identifier: nextIdentifier, protein: nextProtein, conditions: nextConditions };
      });
      return;
    }

    if (activeTab === "lineplot") {
      setLine((prev) => {
        const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
        const nextIdentifier = validIdentifiers.has(prev.identifier)
          ? prev.identifier
          : (options.identifier ?? "workflow");
        const filteredProteins = prev.proteins.filter((value) => proteinChoices.includes(value));
        const nextProteins =
          filteredProteins.length > 0 ? filteredProteins : proteinChoices.slice(0, Math.min(3, proteinChoices.length));
        const filteredConditions = prev.conditions.filter((value) => conditionChoices.includes(value));
        const nextConditions = filteredConditions.length > 0 ? filteredConditions : [...conditionChoices];
        return { ...prev, identifier: nextIdentifier, proteins: nextProteins, conditions: nextConditions };
      });
      return;
    }

    setHeatmap((prev) => {
      const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
      const nextIdentifier = validIdentifiers.has(prev.identifier)
        ? prev.identifier
        : (options.identifier ?? "workflow");
      const nextProtein =
        prev.protein && proteinChoices.includes(prev.protein) ? prev.protein : proteinChoices[0] ?? "";
      const filtered = prev.conditions.filter((value) => conditionChoices.includes(value));
      const nextConditions = filtered.length > 0 ? filtered : [...conditionChoices];
      return { ...prev, identifier: nextIdentifier, protein: nextProtein, conditions: nextConditions };
    });
  }, [activeTab, options]);

  const plotView = useMemo<PlotView>(() => {
    if (activeTab === "boxplot") {
      if (!box.protein || box.conditions.length === 0) return null;
      return {
        title: "Protein Boxplot",
        filename: `single_protein_boxplot_${effectiveKind}.png`,
        url: buildPlotUrl(`/api/plots/single-protein/${effectiveKind}/boxplot.png`, {
          identifier: box.identifier,
          protein: box.protein,
          conditions: box.conditions.join(","),
          outliers: box.outliers,
          dots: box.dots,
          header: box.header,
          legend: box.legend,
          widthCm: box.widthCm,
          heightCm: box.heightCm,
          dpi: box.dpi,
        }),
      };
    }

    if (activeTab === "lineplot") {
      if (line.proteins.length === 0 || line.conditions.length === 0) return null;
      return {
        title: "Protein Lineplot",
        filename: `single_protein_lineplot_${effectiveKind}.png`,
        url: buildPlotUrl(`/api/plots/single-protein/${effectiveKind}/lineplot.png`, {
          identifier: line.identifier,
          proteins: line.proteins.join(","),
          conditions: line.conditions.join(","),
          includeId: line.includeId,
          header: line.header,
          legend: line.legend,
          widthCm: line.widthCm,
          heightCm: line.heightCm,
          dpi: line.dpi,
        }),
      };
    }

    if (!heatmap.protein || heatmap.conditions.length === 0) return null;
    return {
      title: "Phosphosites on Protein Heatmap",
      filename: "single_protein_heatmap_phospho.png",
      url: buildPlotUrl("/api/plots/single-protein/phospho/heatmap.png", {
        identifier: heatmap.identifier,
        protein: heatmap.protein,
        conditions: heatmap.conditions.join(","),
        includeId: heatmap.includeId,
        header: heatmap.header,
        filterM1: heatmap.filterM1,
        clusterRows: heatmap.clusterRows,
        clusterCols: heatmap.clusterCols,
        valueType: heatmap.valueType,
        cmap: heatmap.cmap,
        widthCm: heatmap.widthCm,
        heightCm: heatmap.heightCm,
        dpi: heatmap.dpi,
      }),
    };
  }, [activeTab, box, line, heatmap, effectiveKind]);
  const plotDownloadUrl = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFilename(plotView.filename, downloadFormat);
  }, [plotView, downloadFormat]);

  const tableRequest = useMemo<TableRequest | null>(() => {
    if (activeTab === "boxplot") {
      if (!box.protein || box.conditions.length === 0) return null;
      const params: Record<string, string | number | boolean> = {
        identifier: box.identifier,
        protein: box.protein,
        conditions: box.conditions.join(","),
      };
      return {
        kind: effectiveKind,
        tab: "boxplot" as const,
        params,
      };
    }

    if (activeTab === "lineplot") {
      if (line.proteins.length === 0 || line.conditions.length === 0) return null;
      const params: Record<string, string | number | boolean> = {
        identifier: line.identifier,
        proteins: line.proteins.join(","),
        conditions: line.conditions.join(","),
        includeId: line.includeId,
      };
      return {
        kind: effectiveKind,
        tab: "lineplot" as const,
        params,
      };
    }

    if (!heatmap.protein || heatmap.conditions.length === 0) return null;
    const params: Record<string, string | number | boolean> = {
      identifier: heatmap.identifier,
      protein: heatmap.protein,
      conditions: heatmap.conditions.join(","),
      includeId: heatmap.includeId,
      filterM1: heatmap.filterM1,
      clusterRows: heatmap.clusterRows,
      clusterCols: heatmap.clusterCols,
      valueType: heatmap.valueType,
    };
    return {
      kind: "phospho" as AnnotationKind,
      tab: "heatmap" as const,
      params,
    };
  }, [activeTab, box, line, heatmap, effectiveKind]);

  useEffect(() => {
    if (!tableRequest) {
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }
    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    getSingleProteinTable(tableRequest.kind, tableRequest.tab, tableRequest.params)
      .then((payload) => {
        if (cancelled) return;
        setTableRows(payload.rows ?? []);
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
  }, [tableRequest]);

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

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Single Protein Pipeline</h2>
        <div className="mt-4 max-w-xs">
          <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
          <select
            value={activeTab === "heatmap" ? (hasPhospho ? "phospho" : "") : kind}
            disabled={activeTab === "heatmap" || kindOptions.length === 0}
            onChange={(e) => setKind(e.target.value as AnnotationKind)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:bg-slate-100 disabled:text-slate-500"
          >
            {activeTab === "heatmap" ? (
              hasPhospho ? (
                <option value="phospho">Phospho</option>
              ) : (
                <option value="">No phospho dataset available</option>
              )
            ) : kindOptions.length === 0 ? (
              <option value="">No dataset available</option>
            ) : (
              kindOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </select>
          {activeTab === "heatmap" ? (
            <p className="mt-2 text-xs text-slate-500">
              Heatmap uses phospho dataset level.
            </p>
          ) : null}
        </div>
      </section>

      {!hasRequiredDataset ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          {activeTab === "heatmap"
            ? "Upload a phospho dataset in the Data tab to render this heatmap."
            : "Upload a protein, phospho, or phosphoprotein dataset in the Data tab to render single-protein plots."}
        </section>
      ) : null}

      {hasRequiredDataset ? (
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

      {hasRequiredDataset ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{plotTitle(activeTab)}</h3>
          {plotView ? (
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
                href={plotDownloadUrl}
                download={plotDownloadFilename}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
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
            Select required options to render the plot.
          </div>
        )}

        {imageError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {imageError}
          </div>
        ) : null}
      </section>
      ) : null}

      {hasRequiredDataset ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
          {tableCsvUrl ? (
            <a
              href={tableCsvUrl}
              download={`single_protein_${activeTab}_${effectiveKind}.csv`}
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
    const proteinOptions = options?.proteins ?? [];
    const conditionOptions = options?.conditions ?? [];
    const identifierEntries = options?.availableIdentifiers ?? [{ key: "workflow", label: "Workflow Names" }];
    const identifierOptions = identifierEntries.map((entry) => entry.key);
    const identifierLabels = Object.fromEntries(identifierEntries.map((entry) => [entry.key, entry.label]));

    if (activeTab === "boxplot") {
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="identifier"
              label="Identifier"
              value={box.identifier}
              options={identifierOptions}
              labels={identifierLabels}
              onChange={(value) =>
                setBox({ ...box, identifier: value as SingleProteinIdentifier, protein: "" })
              }
            />,
            <SelectField
              key="protein"
              label={box.identifier === "genes" ? "Gene" : "Protein / Site"}
              value={box.protein}
              options={proteinOptions}
              onChange={(value) => setBox({ ...box, protein: value })}
            />,
            <MultiSelectField
              key="conditions"
              label="Conditions"
              value={box.conditions}
              options={conditionOptions}
              onChange={(value) => setBox({ ...box, conditions: value })}
            />,
          ]}
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={box.header} onChange={(value) => setBox({ ...box, header: value })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={box.legend} onChange={(value) => setBox({ ...box, legend: value })} />,
            <Checkbox key="dots" label="Toggle Dots" checked={box.dots} onChange={(value) => setBox({ ...box, dots: value })} />,
            <Checkbox key="outliers" label="Toggle Outliers" checked={box.outliers} onChange={(value) => setBox({ ...box, outliers: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={box.widthCm}
              heightCm={box.heightCm}
              dpi={box.dpi}
              onWidthChange={(value) => setBox({ ...box, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setBox({ ...box, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setBox({ ...box, dpi: Math.max(72, Math.round(value)) })}
            />
          }
        />
      );
    }

    if (activeTab === "lineplot") {
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="identifier"
              label="Identifier"
              value={line.identifier}
              options={identifierOptions}
              labels={identifierLabels}
              onChange={(value) =>
                setLine({ ...line, identifier: value as SingleProteinIdentifier, proteins: [] })
              }
            />,
            <MultiSelectField
              key="proteins"
              label={line.identifier === "genes" ? "Genes" : "Proteins / Sites"}
              value={line.proteins}
              options={proteinOptions}
              onChange={(value) => setLine({ ...line, proteins: value })}
            />,
            <MultiSelectField
              key="conditions"
              label="Conditions"
              value={line.conditions}
              options={conditionOptions}
              onChange={(value) => setLine({ ...line, conditions: value })}
            />,
          ]}
          toggles={[
            <Checkbox key="id" label="Toggle ID" checked={line.includeId} onChange={(value) => setLine({ ...line, includeId: value })} />,
            <Checkbox key="header" label="Toggle Header" checked={line.header} onChange={(value) => setLine({ ...line, header: value })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={line.legend} onChange={(value) => setLine({ ...line, legend: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={line.widthCm}
              heightCm={line.heightCm}
              dpi={line.dpi}
              onWidthChange={(value) => setLine({ ...line, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setLine({ ...line, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setLine({ ...line, dpi: Math.max(72, Math.round(value)) })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        fields={[
          <SelectField
            key="identifier"
            label="Identifier"
            value={heatmap.identifier}
            options={identifierOptions}
            labels={identifierLabels}
            onChange={(value) =>
              setHeatmap({ ...heatmap, identifier: value as SingleProteinIdentifier, protein: "" })
            }
          />,
          <SelectField
            key="protein"
            label={heatmap.identifier === "genes" ? "Gene" : "Protein Group"}
            value={heatmap.protein}
            options={proteinOptions}
            onChange={(value) => setHeatmap({ ...heatmap, protein: value })}
          />,
          <MultiSelectField
            key="conditions"
            label="Conditions"
            value={heatmap.conditions}
            options={conditionOptions}
            onChange={(value) => setHeatmap({ ...heatmap, conditions: value })}
          />,
          <SelectField
            key="valueType"
            label="Value Type"
            value={heatmap.valueType}
            options={["log2", "z"]}
            onChange={(value) => setHeatmap({ ...heatmap, valueType: value })}
          />,
          <SelectField
            key="cmap"
            label="Color Map"
            value={heatmap.cmap}
            options={["plasma", "viridis", "magma", "inferno", "coolwarm"]}
            onChange={(value) => setHeatmap({ ...heatmap, cmap: value })}
          />,
        ]}
        toggles={[
          <Checkbox key="id" label="Toggle ID" checked={heatmap.includeId} onChange={(value) => setHeatmap({ ...heatmap, includeId: value })} />,
          <Checkbox key="header" label="Toggle Header" checked={heatmap.header} onChange={(value) => setHeatmap({ ...heatmap, header: value })} />,
          <Checkbox key="filter" label="Filter *_M1" checked={heatmap.filterM1} onChange={(value) => setHeatmap({ ...heatmap, filterM1: value })} />,
          <Checkbox key="rows" label="Cluster Rows" checked={heatmap.clusterRows} onChange={(value) => setHeatmap({ ...heatmap, clusterRows: value })} />,
          <Checkbox key="cols" label="Cluster Columns" checked={heatmap.clusterCols} onChange={(value) => setHeatmap({ ...heatmap, clusterCols: value })} />,
        ]}
        sizeRow={
          <SizeRow
            widthCm={heatmap.widthCm}
            heightCm={heatmap.heightCm}
            dpi={heatmap.dpi}
            onWidthChange={(value) => setHeatmap({ ...heatmap, widthCm: Math.max(1, value) })}
            onHeightChange={(value) => setHeatmap({ ...heatmap, heightCm: Math.max(1, value) })}
            onDpiChange={(value) => setHeatmap({ ...heatmap, dpi: Math.max(72, Math.round(value)) })}
          />
        }
      />
    );
  }
}

function plotTitle(tab: SingleProteinTab): string {
  if (tab === "boxplot") return "Protein Boxplot";
  if (tab === "lineplot") return "Protein Lineplot";
  return "Phosphosites on Protein Heatmap";
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
      <NumericField label="DPI" value={dpi} onChange={onDpiChange} />
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  labels,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  labels?: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {labels?.[option] ?? option}
          </option>
        ))}
      </select>
    </label>
  );
}

function MultiSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
}) {
  const visibleRows = Math.max(4, Math.min(8, options.length || 4));
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <select
        multiple
        size={visibleRows}
        value={value}
        onChange={(event) => {
          const selected = Array.from(event.currentTarget.selectedOptions).map((option) => option.value);
          onChange(selected);
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-xs text-slate-500">Use Ctrl/Cmd-click for multi-select.</span>
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
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(event) => {
          const normalized = event.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
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
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
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
