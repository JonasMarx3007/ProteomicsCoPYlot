import { useEffect, useMemo, useState } from "react";
import {
  getConditionPalette,
  getQcPlotOptions,
  setConditionPalette,
} from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { AnnotationKind } from "../../lib/types";

const DEFAULT_PALETTE = [
  "#1f77b4",
  "#ff7f0e",
  "#2ca02c",
  "#d62728",
  "#9467bd",
  "#8c564b",
  "#e377c2",
  "#7f7f7f",
  "#bcbd22",
  "#17becf",
];

type ColorMap = Record<string, string>;

function isHexColor(value: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(value.trim());
}

function fallbackColor(index: number): string {
  return DEFAULT_PALETTE[index % DEFAULT_PALETTE.length];
}

export default function ColorsPage() {
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [conditions, setConditions] = useState<string[]>([]);
  const [colors, setColors] = useState<ColorMap>({});
  const [copyTargetKind, setCopyTargetKind] = useState<AnnotationKind>("phospho");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    if (availableKinds.length === 0) return;
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    const others = availableKinds.filter((value) => value !== kind);
    if (others.length === 0) return;
    if (!others.includes(copyTargetKind)) {
      setCopyTargetKind(others[0]);
    }
  }, [availableKinds, kind, copyTargetKind]);

  useEffect(() => {
    if (!availableKinds.includes(kind)) {
      setConditions([]);
      setColors({});
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getQcPlotOptions(kind)
      .then(async (payload) => {
        if (cancelled) return;
        const unique = Array.from(
          new Set(payload.conditions.map((value) => value.trim()).filter(Boolean))
        );
        setConditions(unique);
        const saved = await getConditionPalette(kind);
        if (cancelled) return;
        const merged: ColorMap = {};
        unique.forEach((condition, index) => {
          const savedColor = saved.palette[condition];
          merged[condition] = isHexColor(savedColor ?? "")
            ? savedColor.toUpperCase()
            : fallbackColor(index);
        });
        setColors(merged);
      })
      .catch((err) => {
        if (cancelled) return;
        setConditions([]);
        setColors({});
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load conditions. Generate annotation first."
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [kind, availableKinds]);

  const rows = useMemo(
    () =>
      conditions.map((condition) => ({
        condition,
        color: colors[condition] ?? "#000000",
      })),
    [conditions, colors]
  );

  async function persistPalette(next: ColorMap) {
    await setConditionPalette(kind, next);
  }

  function handleColorChange(condition: string, value: string) {
    const normalized = value.toUpperCase();
    const next = { ...colors, [condition]: normalized };
    setColors(next);
    setInfo(null);
    setError(null);
    persistPalette(next).catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to save colors.");
    });
  }

  function handleHexChange(condition: string, value: string) {
    const normalized = value.trim().toUpperCase();
    if (normalized === "") {
      return;
    }
    const withHash = normalized.startsWith("#") ? normalized : `#${normalized}`;
    if (!isHexColor(withHash)) {
      return;
    }
    handleColorChange(condition, withHash);
  }

  function resetPalette() {
    const next: ColorMap = {};
    conditions.forEach((condition, index) => {
      next[condition] = fallbackColor(index);
    });
    setColors(next);
    setInfo(null);
    setError(null);
    persistPalette(next)
      .then(() => {
        setInfo("Default palette restored and saved.");
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to save colors.");
      });
  }

  async function copyPaletteToTarget() {
    if (!copyTargetKind || copyTargetKind === kind) return;
    try {
      setError(null);
      setInfo(null);
      const target = await getQcPlotOptions(copyTargetKind);
      const targetConditions = Array.from(
        new Set(target.conditions.map((value) => value.trim()).filter(Boolean))
      );
      if (targetConditions.length !== conditions.length) {
        setInfo(
          `Copy skipped because condition counts differ (${kind}: ${conditions.length}, ${copyTargetKind}: ${targetConditions.length}).`
        );
        return;
      }
      const sourceColors = conditions.map((condition, index) => {
        const current = colors[condition];
        return isHexColor(current ?? "") ? current.toUpperCase() : fallbackColor(index);
      });
      const copied: ColorMap = {};
      targetConditions.forEach((condition, index) => {
        copied[condition] = sourceColors[index];
      });
      await setConditionPalette(copyTargetKind, copied);
      setInfo(`Copied palette from ${kind} to ${copyTargetKind}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to copy colors.");
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Colors</h2>
        <p className="mt-2 text-sm text-slate-600">
          Define condition colors for the selected dataset level. Plot colors update from this palette.
        </p>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={kindOptions}
            disabled={kindOptions.length === 0}
          />
          <div className="self-end">
            <button
              type="button"
              onClick={resetPalette}
              disabled={rows.length === 0}
              className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Reset Default Palette
            </button>
          </div>
        </div>

        {kindOptions.length > 1 ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <SelectField
              label="Copy colors to dataset level"
              value={copyTargetKind}
              onChange={(value) => setCopyTargetKind(value as AnnotationKind)}
              options={kindOptions.filter((option) => option.value !== kind)}
              disabled={kindOptions.filter((option) => option.value !== kind).length === 0}
            />
            <div className="self-end">
              <button
                type="button"
                onClick={copyPaletteToTarget}
                disabled={rows.length === 0 || !copyTargetKind || copyTargetKind === kind}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Copy Colors
              </button>
            </div>
          </div>
        ) : null}

        {info ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
            {info}
          </div>
        ) : null}

        {error ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {error}
          </div>
        ) : null}
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable colors.
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Condition Colors</h3>
          {loading ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Loading conditions...
            </div>
          ) : rows.length === 0 ? (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              No conditions available. Generate annotation first.
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {rows.map((row) => (
                <div
                  key={row.condition}
                  className="grid items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 sm:grid-cols-[1fr_auto_10rem]"
                >
                  <div className="text-sm font-medium text-slate-800">{row.condition}</div>
                  <input
                    type="color"
                    value={row.color}
                    onChange={(event) => handleColorChange(row.condition, event.target.value)}
                    className="h-9 w-14 rounded-lg border border-slate-300 bg-white px-1 py-1"
                  />
                  <input
                    type="text"
                    value={row.color}
                    onChange={(event) => handleHexChange(row.condition, event.target.value)}
                    className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm outline-none focus:border-slate-900"
                  />
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
