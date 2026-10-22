import { useEffect, useState, type ReactNode } from "react";
import { getRRuntimeStatus } from "../../lib/api";
import {
  getAdvancedPlotMode,
  getSessionTheme,
  setAdvancedPlotMode,
  setSessionTheme,
  type AppTheme,
} from "../../lib/appSettings";
import type { RRuntimeStatusResponse } from "../../lib/types";

function SettingsCard({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">
        {eyebrow}
      </div>
      <h2 className="mt-2 text-xl font-bold text-slate-950 dark:text-slate-50">{title}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 transition hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800/80 dark:hover:border-slate-600">
      <span>
        <span className="block text-sm font-semibold text-slate-900 dark:text-slate-100">{label}</span>
        <span className="mt-1 block text-sm text-slate-500 dark:text-slate-400">{description}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-5 w-5 accent-slate-900 dark:accent-sky-400"
      />
    </label>
  );
}

function RuntimeRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 border-t border-slate-200 py-3 first:border-t-0 dark:border-slate-700 sm:grid-cols-[10rem_1fr]">
      <div className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</div>
      <div className="break-words text-sm text-slate-900 dark:text-slate-100">{value}</div>
    </div>
  );
}

export default function SettingsPage() {
  const [theme, setTheme] = useState<AppTheme>(() => getSessionTheme());
  const [advancedPlots, setAdvancedPlots] = useState(() => getAdvancedPlotMode());
  const [rRuntime, setRRuntime] = useState<RRuntimeStatusResponse | null>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  function updateTheme(nextTheme: AppTheme) {
    setTheme(nextTheme);
    setSessionTheme(nextTheme);
  }

  function updateAdvancedPlots(enabled: boolean) {
    setAdvancedPlots(enabled);
    setAdvancedPlotMode(enabled);
  }

  function refreshRuntime(refresh = false) {
    setRuntimeLoading(true);
    setRuntimeError(null);
    getRRuntimeStatus(refresh)
      .then((status) => {
        setRRuntime(status);
      })
      .catch((error) => {
        setRuntimeError(error instanceof Error ? error.message : "Failed to detect R runtime.");
      })
      .finally(() => {
        setRuntimeLoading(false);
      });
  }

  useEffect(() => {
    // The mode can also be toggled with Ctrl/Cmd+Shift+E while this page is
    // open; without this the switch would keep showing the old position.
    const refresh = () => setAdvancedPlots(getAdvancedPlotMode());
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    return () => window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
  }, []);

  useEffect(() => {
    let active = true;
    getRRuntimeStatus()
      .then((status) => {
        if (active) setRRuntime(status);
      })
      .catch((error) => {
        if (active) {
          setRuntimeError(error instanceof Error ? error.message : "Failed to detect R runtime.");
        }
      })
      .finally(() => {
        if (active) setRuntimeLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="overflow-hidden rounded-[2rem] border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-slate-100 p-8 shadow-sm dark:border-slate-700 dark:from-slate-950 dark:via-slate-900 dark:to-slate-800">
        <div className="text-sm font-semibold uppercase tracking-[0.28em] text-slate-500 dark:text-slate-400">
          App Settings
        </div>
        <h1 className="mt-3 text-3xl font-black tracking-tight text-slate-950 dark:text-white">
          Settings
        </h1>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <SettingsCard eyebrow="Appearance" title="Theme">
          <div className="grid grid-cols-2 gap-3">
            {(["light", "dark"] as AppTheme[]).map((option) => {
              const active = theme === option;
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => updateTheme(option)}
                  className={[
                    "rounded-2xl border px-4 py-4 text-left transition",
                    active
                      ? "border-slate-950 bg-slate-950 text-white shadow-sm dark:!border-sky-400 dark:!bg-sky-400 dark:!text-slate-950"
                      : "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200",
                  ].join(" ")}
                >
                  <span className="block text-sm font-bold capitalize">{option}</span>
                  <span className="mt-1 block text-xs opacity-75">
                    {option === "light" ? "Bright workspace" : "Low-light workspace"}
                  </span>
                </button>
              );
            })}
          </div>
        </SettingsCard>

        <SettingsCard eyebrow="Features" title="Plot Options">
          <Toggle
            checked={advancedPlots}
            onChange={updateAdvancedPlots}
            label="Advanced plot option mode"
            description="Show the full styling panel under every plot: title, axes, legend, points, colors. Toggle it from anywhere with Ctrl/Cmd + Shift + E."
          />
        </SettingsCard>

        <div className="lg:col-span-2">
          <SettingsCard eyebrow="Runtime" title="R Compatibility">
            <div className="flex items-center justify-between gap-3">
              <div
                className={[
                  "inline-flex items-center rounded-full px-3 py-1 text-xs font-bold",
                  rRuntime?.available
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                    : "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
                ].join(" ")}
              >
                {runtimeLoading ? "Checking..." : rRuntime?.available ? "R available" : "R not found"}
              </div>
              <button
                type="button"
                onClick={() => refreshRuntime(true)}
                disabled={runtimeLoading}
                className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Refresh
              </button>
            </div>

            <div className="mt-4 rounded-2xl bg-slate-50 px-4 dark:bg-slate-800/80">
              <RuntimeRow label="Version" value={rRuntime?.version || "Unknown"} />
              <RuntimeRow label="Executable" value={rRuntime?.diagnosticsHidden ? "Hidden on this deployment" : rRuntime?.executable || "Not detected"} />
              <RuntimeRow label="Detected from" value={rRuntime?.diagnosticsHidden ? "Hidden on this deployment" : rRuntime?.detectedFrom || "None"} />
              <RuntimeRow label="Version output" value={rRuntime?.diagnosticsHidden ? "Hidden on this deployment" : rRuntime?.versionOutput || "Unavailable"} />
            </div>

            {runtimeError || rRuntime?.error ? (
              <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                {runtimeError || rRuntime?.error}
              </div>
            ) : null}
          </SettingsCard>
        </div>
      </div>
    </div>
  );
}
