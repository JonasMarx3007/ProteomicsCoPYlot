import { useEffect, useState } from "react";
import type { AdvancedPlotSettings, AdvancedTextElementSettings } from "../../lib/types";

type ElementKey = "titleElement" | "xLabelElement" | "yLabelElement";

export type AdvancedPlotVisibleControls = {
  textElements?: boolean;
  tickControls?: boolean;
  legendControls?: boolean;
  referenceLineColor?: boolean;
  conditionLabels?: boolean;
  sampleLabels?: boolean;
  conditionColors?: boolean;
  boxplotStyle?: boolean;
  boxplotOutliers?: boolean;
  correlationGradient?: boolean;
  backgroundControls?: boolean;
  axisLineControls?: boolean;
};

export type AdvancedPlotControlDefaults = Partial<
  Pick<
    AdvancedPlotSettings,
    | "axisLineTop"
    | "axisLineRight"
    | "axisLineBottom"
    | "axisLineLeft"
    | "axisLineColor"
    | "axisLineWidth"
    | "axisLineStyle"
    | "gridLineVisible"
    | "gridLineAxis"
    | "gridLineColor"
    | "gridLineWidth"
    | "gridLineStyle"
  >
>;

type Props = {
  value: AdvancedPlotSettings;
  onChange: (next: AdvancedPlotSettings) => void;
  conditionOptions?: string[];
  conditionDisplayLabels?: Record<string, string>;
  sampleOptions?: string[];
  sampleDisplayLabels?: Record<string, string>;
  visibleControls?: AdvancedPlotVisibleControls;
  controlDefaults?: AdvancedPlotControlDefaults;
};

const REFERENCE_VALUES = {
  titleSize: 12,
  axisLabelSize: 10,
  xTickLabelSize: 10,
  yTickLabelSize: 10,
  tickRotation: 0,
  legendFontSize: 10,
  offset: 0,
};

const inputClass =
  "mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-sky-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500";

const PLOT_THEME_OPTIONS = [
  { value: "default", label: "Default" },
  { value: "white", label: "White" },
  { value: "minimal", label: "Minimal" },
  { value: "soft_gray", label: "Soft gray" },
  { value: "presentation", label: "Presentation" },
  { value: "dark", label: "Dark" },
];

const AXIS_LINE_STYLE_OPTIONS = [
  { value: "solid", label: "Solid" },
  { value: "dashed", label: "Dashed" },
  { value: "dotted", label: "Dotted" },
  { value: "dashdot", label: "Dash dot" },
];

const GRID_LINE_AXIS_OPTIONS = [
  { value: "both", label: "Both" },
  { value: "x", label: "Vertical" },
  { value: "y", label: "Horizontal" },
];

function numberOrUndefined(value: string): number | undefined {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return undefined;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export default function AdvancedPlotOptions({
  value,
  onChange,
  conditionOptions = [],
  conditionDisplayLabels = {},
  sampleOptions = [],
  sampleDisplayLabels = {},
  visibleControls = {},
  controlDefaults = {},
}: Props) {
  const showTextElements = visibleControls.textElements !== false;
  const showTickControls = visibleControls.tickControls !== false;
  const showLegendControls = visibleControls.legendControls !== false;
  const showReferenceLineColor = visibleControls.referenceLineColor === true;
  const showConditionLabels = visibleControls.conditionLabels !== false;
  const showSampleLabels = visibleControls.sampleLabels !== false;
  const showConditionColors = visibleControls.conditionColors !== false;
  const showBoxplotStyle = visibleControls.boxplotStyle === true;
  const showBoxplotOutliers = visibleControls.boxplotOutliers === true;
  const showCorrelationGradient = visibleControls.correlationGradient === true;
  const showBackgroundControls = visibleControls.backgroundControls !== false;
  const showAxisLineControls = visibleControls.axisLineControls !== false;
  const axisLineLeft = value.axisLineLeft ?? controlDefaults.axisLineLeft ?? true;
  const axisLineRight = value.axisLineRight ?? controlDefaults.axisLineRight ?? true;
  const axisLineBottom = value.axisLineBottom ?? controlDefaults.axisLineBottom ?? true;
  const axisLineTop = value.axisLineTop ?? controlDefaults.axisLineTop ?? true;
  const axisLineColor = value.axisLineColor ?? controlDefaults.axisLineColor ?? "#111827";
  const axisLineWidth = value.axisLineWidth ?? controlDefaults.axisLineWidth ?? 1;
  const axisLineStyle = value.axisLineStyle ?? controlDefaults.axisLineStyle ?? "solid";
  const gridLineVisible = value.gridLineVisible ?? controlDefaults.gridLineVisible ?? false;
  const gridLineAxis = value.gridLineAxis ?? controlDefaults.gridLineAxis ?? "y";
  const gridLineColor = value.gridLineColor ?? controlDefaults.gridLineColor ?? "#d1d5db";
  const gridLineWidth = value.gridLineWidth ?? controlDefaults.gridLineWidth ?? 0.8;
  const gridLineStyle = value.gridLineStyle ?? controlDefaults.gridLineStyle ?? "dashed";

  function defaultControlPayload(): Partial<AdvancedPlotSettings> {
    if (!showAxisLineControls) return {};
    return {
      axisLineLeft,
      axisLineRight,
      axisLineBottom,
      axisLineTop,
      axisLineColor,
      axisLineWidth,
      axisLineStyle,
      gridLineVisible,
      gridLineAxis,
      gridLineColor,
      gridLineWidth,
      gridLineStyle,
    };
  }

  function patch(next: Partial<AdvancedPlotSettings>) {
    onChange({ ...value, ...defaultControlPayload(), ...next });
  }

  function patchAxisFrame(next: Partial<AdvancedPlotSettings>) {
    patch({
      axisLineVisible: true,
      axisLineLeft,
      axisLineRight,
      axisLineBottom,
      axisLineTop,
      axisLineColor,
      axisLineWidth,
      axisLineStyle,
      ...next,
    });
  }

  function patchGridLines(next: Partial<AdvancedPlotSettings>) {
    patch({
      gridLineVisible,
      gridLineAxis,
      gridLineColor,
      gridLineWidth,
      gridLineStyle,
      ...next,
    });
  }

  function patchElement(key: ElementKey, next: Partial<AdvancedTextElementSettings>) {
    const current = value[key] ?? {};
    const merged = { ...current, ...next };
    const legacy: Partial<AdvancedPlotSettings> = {};
    if (key === "titleElement") {
      legacy.title = merged.text ?? "";
      legacy.titleSize = merged.size;
    }
    if (key === "xLabelElement") {
      legacy.xLabel = merged.text ?? "";
    }
    if (key === "yLabelElement") {
      legacy.yLabel = merged.text ?? "";
    }
    patch({ [key]: merged, ...legacy } as Partial<AdvancedPlotSettings>);
  }

  function patchMap(
    key: "conditionLabels" | "sampleLabels" | "conditionColors",
    mapKey: string,
    mapValue: string,
  ) {
    const current = value[key] ?? {};
    const next = { ...current };
    if (mapValue.trim()) {
      next[mapKey] = mapValue;
    } else {
      delete next[mapKey];
    }
    patch({ [key]: next } as Partial<AdvancedPlotSettings>);
  }

  return (
    <section className="rounded-2xl border border-sky-200 bg-sky-50/70 p-5 shadow-sm dark:border-sky-500/30 dark:bg-sky-500/10">
      <div>
        <div className="text-xs font-semibold uppercase tracking-[0.22em] text-sky-700 dark:text-sky-300">
          Advanced Plot Options
        </div>
      </div>

      {showBackgroundControls || showAxisLineControls ? (
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          {showBackgroundControls ? (
            <div className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Background</div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <label className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Theme</span>
                  <select
                    value={value.plotTheme || "default"}
                    onChange={(event) => patch({ plotTheme: event.target.value })}
                    className={inputClass}
                  >
                    {PLOT_THEME_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                  <input
                    type="color"
                    value={isHexColor(value.backgroundColor || "") ? value.backgroundColor : "#ffffff"}
                    onChange={(event) => patch({ backgroundColor: event.target.value })}
                    className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                </label>
                <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={Boolean(value.transparentBackground)}
                    onChange={(event) => patch({ transparentBackground: event.target.checked })}
                    className="h-4 w-4 accent-sky-600"
                  />
                  Transparent
                </label>
              </div>
            </div>
          ) : null}

          {showAxisLineControls ? (
            <div className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
              <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Axis frame</div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <div>
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Sides</span>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <input
                        type="checkbox"
                        checked={axisLineLeft}
                        onChange={(event) => patchAxisFrame({ axisLineLeft: event.target.checked })}
                        className="h-4 w-4 accent-sky-600"
                      />
                      Left
                    </label>
                    <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <input
                        type="checkbox"
                        checked={axisLineRight}
                        onChange={(event) => patchAxisFrame({ axisLineRight: event.target.checked })}
                        className="h-4 w-4 accent-sky-600"
                      />
                      Right
                    </label>
                    <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <input
                        type="checkbox"
                        checked={axisLineBottom}
                        onChange={(event) => patchAxisFrame({ axisLineBottom: event.target.checked })}
                        className="h-4 w-4 accent-sky-600"
                      />
                      Bottom
                    </label>
                    <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <input
                        type="checkbox"
                        checked={axisLineTop}
                        onChange={(event) => patchAxisFrame({ axisLineTop: event.target.checked })}
                        className="h-4 w-4 accent-sky-600"
                      />
                      Top
                    </label>
                  </div>
                </div>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                  <input
                    type="color"
                    value={isHexColor(axisLineColor) ? axisLineColor : "#111827"}
                    onChange={(event) => patchAxisFrame({ axisLineColor: event.target.value })}
                    className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Width</span>
                  <NumberInput
                    min="0"
                    step="0.5"
                    value={axisLineWidth}
                    fallback={1}
                    onValidChange={(next) => patchAxisFrame({ axisLineWidth: next })}
                  />
                  <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                    Reference: 1
                  </span>
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Style</span>
                  <select
                    value={axisLineStyle}
                    onChange={(event) => patchAxisFrame({ axisLineStyle: event.target.value })}
                    className={inputClass}
                  >
                    {AXIS_LINE_STYLE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {showAxisLineControls ? (
        <div className="mt-4 rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
          <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Grid lines</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-5">
            <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <input
                type="checkbox"
                checked={gridLineVisible}
                onChange={(event) => patchGridLines({ gridLineVisible: event.target.checked })}
                className="h-4 w-4 accent-sky-600"
              />
              Show
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Direction</span>
              <select
                value={gridLineAxis}
                onChange={(event) => patchGridLines({ gridLineAxis: event.target.value, gridLineVisible: true })}
                className={inputClass}
              >
                {GRID_LINE_AXIS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
              <input
                type="color"
                value={isHexColor(gridLineColor) ? gridLineColor : "#d1d5db"}
                onChange={(event) => patchGridLines({ gridLineColor: event.target.value, gridLineVisible: true })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Width</span>
              <NumberInput
                min="0"
                step="0.5"
                value={gridLineWidth}
                fallback={0.8}
                onValidChange={(next) => patchGridLines({ gridLineWidth: next, gridLineVisible: true })}
              />
              <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                Reference: 0.8
              </span>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Style</span>
              <select
                value={gridLineStyle}
                onChange={(event) => patchGridLines({ gridLineStyle: event.target.value, gridLineVisible: true })}
                className={inputClass}
              >
                {AXIS_LINE_STYLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
      ) : null}

      {showTextElements ? (
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <TextElementCard
            title="Title"
            placeholder="Overwrite plot title"
            referenceSize={REFERENCE_VALUES.titleSize}
            value={value.titleElement ?? { text: value.title, size: value.titleSize }}
            onChange={(next) => patchElement("titleElement", next)}
          />
          <TextElementCard
            title="X axis label"
            placeholder="Overwrite x-axis label"
            referenceSize={REFERENCE_VALUES.axisLabelSize}
            value={value.xLabelElement ?? { text: value.xLabel, size: value.axisLabelSize }}
            onChange={(next) => patchElement("xLabelElement", next)}
          />
          <TextElementCard
            title="Y axis label"
            placeholder="Overwrite y-axis label"
            referenceSize={REFERENCE_VALUES.axisLabelSize}
            value={value.yLabelElement ?? { text: value.yLabel, size: value.axisLabelSize }}
            onChange={(next) => patchElement("yLabelElement", next)}
          />
        </div>
      ) : null}

      {showTickControls || showLegendControls || showReferenceLineColor ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-5">
          {showTickControls ? (
            <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">X tick label size</span>
                <NumberInput
                  value={value.xTickLabelSize ?? value.tickLabelSize ?? REFERENCE_VALUES.xTickLabelSize}
                  fallback={REFERENCE_VALUES.xTickLabelSize}
                  onValidChange={(next) => patch({ xTickLabelSize: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: {REFERENCE_VALUES.xTickLabelSize}
                </span>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Y tick label size</span>
                <NumberInput
                  value={value.yTickLabelSize ?? value.tickLabelSize ?? REFERENCE_VALUES.yTickLabelSize}
                  fallback={REFERENCE_VALUES.yTickLabelSize}
                  onValidChange={(next) => patch({ yTickLabelSize: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: {REFERENCE_VALUES.yTickLabelSize}
                </span>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">X tick rotation (deg)</span>
                <NumberInput
                  step="1"
                  value={value.xTickLabelRotation ?? REFERENCE_VALUES.tickRotation}
                  fallback={REFERENCE_VALUES.tickRotation}
                  onValidChange={(next) => patch({ xTickLabelRotation: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: {REFERENCE_VALUES.tickRotation}
                </span>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Y tick rotation (deg)</span>
                <NumberInput
                  step="1"
                  value={value.yTickLabelRotation ?? REFERENCE_VALUES.tickRotation}
                  fallback={REFERENCE_VALUES.tickRotation}
                  onValidChange={(next) => patch({ yTickLabelRotation: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: {REFERENCE_VALUES.tickRotation}
                </span>
              </label>
            </>
          ) : null}
          {showLegendControls ? (
            <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Legend size</span>
                <NumberInput
                  value={value.legendFontSize ?? REFERENCE_VALUES.legendFontSize}
                  fallback={REFERENCE_VALUES.legendFontSize}
                  onValidChange={(next) => patch({ legendFontSize: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: {REFERENCE_VALUES.legendFontSize}
                </span>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Legend x / y offset (px)</span>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  <NumberInput
                    step="1"
                    value={value.legendXOffset ?? REFERENCE_VALUES.offset}
                    fallback={REFERENCE_VALUES.offset}
                    className={inputClass.replace("mt-1 ", "")}
                    onValidChange={(next) => patch({ legendXOffset: next })}
                  />
                  <NumberInput
                    step="1"
                    value={value.legendYOffset ?? REFERENCE_VALUES.offset}
                    fallback={REFERENCE_VALUES.offset}
                    className={inputClass.replace("mt-1 ", "")}
                    onValidChange={(next) => patch({ legendYOffset: next })}
                  />
                </div>
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: x {REFERENCE_VALUES.offset}, y {REFERENCE_VALUES.offset}
                </span>
              </label>
            </>
          ) : null}
          {showReferenceLineColor ? (
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Reference line color</span>
              <input
                type="color"
                value={value.referenceLineColor || "#ff0000"}
                onChange={(event) => patch({ referenceLineColor: event.target.value })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
          ) : null}
        </div>
      ) : null}

      {showBoxplotStyle ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Box border color</span>
            <input
              type="color"
              value={value.boxBorderColor || "#000000"}
              onChange={(event) => patch({ boxBorderColor: event.target.value })}
              className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Median color</span>
            <input
              type="color"
              value={value.boxMedianColor || "#b22222"}
              onChange={(event) => patch({ boxMedianColor: event.target.value })}
              className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          {showBoxplotOutliers ? (
            <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier dot color</span>
                <input
                  type="color"
                  value={value.boxOutlierColor || "#ff0000"}
                  onChange={(event) => patch({ boxOutlierColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier outline color</span>
                <input
                  type="color"
                  value={value.boxOutlierEdgeColor || "#000000"}
                  onChange={(event) => patch({ boxOutlierEdgeColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier size</span>
                <NumberInput
                  min="1"
                  step="1"
                  value={value.boxOutlierSize ?? 5}
                  fallback={5}
                  onValidChange={(next) => patch({ boxOutlierSize: next })}
                />
                <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
                  Reference: 5
                </span>
              </label>
            </>
          ) : null}
        </div>
      ) : null}

      {showCorrelationGradient ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Correlation gradient</span>
            <select
              value={value.correlationColorMap || "coolwarm"}
              onChange={(event) => patch({ correlationColorMap: event.target.value })}
              className={inputClass}
            >
              <option value="coolwarm">Coolwarm</option>
              <option value="RdBu_r">Red/blue</option>
              <option value="Spectral">Spectral</option>
              <option value="PiYG">Pink/green</option>
              <option value="PRGn">Purple/green</option>
              <option value="BrBG">Brown/teal</option>
              <option value="viridis">Viridis</option>
              <option value="cividis">Cividis</option>
            </select>
          </label>
        </div>
      ) : null}

      {showConditionLabels || showSampleLabels || showConditionColors ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {showConditionLabels && conditionOptions.length ? (
            <KnownOverrideRows
              title="Condition names"
              items={conditionOptions}
              values={value.conditionLabels}
              placeholderSuffix="display name"
              displayLabels={conditionDisplayLabels}
              onChange={(key, nextValue) => patchMap("conditionLabels", key, nextValue)}
            />
          ) : null}
          {showSampleLabels && sampleOptions.length ? (
            <KnownOverrideRows
              title="Sample names"
              items={sampleOptions}
              values={value.sampleLabels}
              placeholderSuffix="new display name"
              displayLabels={sampleDisplayLabels}
              onChange={(key, nextValue) => patchMap("sampleLabels", key, nextValue)}
            />
          ) : null}
          {showConditionColors && conditionOptions.length ? (
            <KnownOverrideRows
              title="Condition colors"
              items={conditionOptions}
              values={value.conditionColors}
              placeholderSuffix="#hex color"
              inputType="colorText"
              onChange={(key, nextValue) => patchMap("conditionColors", key, nextValue)}
            />
          ) : null}
        </div>
      ) : null}

    </section>
  );
}

function KnownOverrideRows({
  title,
  items,
  values,
  placeholderSuffix,
  displayLabels,
  inputType = "text",
  onChange,
}: {
  title: string;
  items: string[];
  values: Record<string, string> | undefined;
  placeholderSuffix: string;
  displayLabels?: Record<string, string>;
  inputType?: "text" | "colorText";
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</div>
      <div className="mt-3 max-h-64 space-y-2 overflow-auto pr-1">
        {items.map((item) => {
          const current = values?.[item] ?? "";
          const displayLabel = displayLabels?.[item]?.trim();
          const placeholder = displayLabel || `${item} ${placeholderSuffix}`;
          return (
            <label key={item} className="grid gap-2 rounded-xl bg-slate-50 p-2 dark:bg-slate-800/80">
              <span className="break-words text-xs font-semibold text-slate-600 dark:text-slate-300">
                {item}
              </span>
              <div className="flex gap-2">
                {inputType === "colorText" ? (
                  <input
                    type="color"
                    value={isHexColor(current) ? current : "#64748b"}
                    onChange={(event) => onChange(item, event.target.value)}
                    className="h-10 w-12 rounded-lg border border-slate-300 bg-white px-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                ) : null}
                <input
                  value={current}
                  onChange={(event) => onChange(item, event.target.value)}
                  placeholder={placeholder}
                  className={inputClass.replace("mt-1 ", "")}
                />
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function isHexColor(value: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(value.trim());
}

function TextElementCard({
  title,
  placeholder,
  referenceSize,
  value,
  onChange,
}: {
  title: string;
  placeholder: string;
  referenceSize: number;
  value: AdvancedTextElementSettings;
  onChange: (next: Partial<AdvancedTextElementSettings>) => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</div>
      <label className="mt-3 block">
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Text</span>
        <input
          value={value.text ?? ""}
          onChange={(event) => onChange({ text: event.target.value })}
          placeholder={placeholder}
          className={inputClass}
        />
      </label>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size</span>
          <NumberInput
            value={value.size ?? referenceSize}
            fallback={referenceSize}
            onValidChange={(next) => onChange({ size: next })}
          />
          <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
            Ref: {referenceSize}
          </span>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">X offset (px)</span>
          <NumberInput
            step="1"
            value={value.xOffset ?? REFERENCE_VALUES.offset}
            fallback={REFERENCE_VALUES.offset}
            onValidChange={(next) => onChange({ xOffset: next })}
          />
          <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
            Ref: {REFERENCE_VALUES.offset}
          </span>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Y offset (px)</span>
          <NumberInput
            step="1"
            value={value.yOffset ?? REFERENCE_VALUES.offset}
            fallback={REFERENCE_VALUES.offset}
            onValidChange={(next) => onChange({ yOffset: next })}
          />
          <span className="mt-1 block text-[11px] text-slate-500 dark:text-slate-400">
            Ref: {REFERENCE_VALUES.offset}
          </span>
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            checked={Boolean(value.bold)}
            onChange={(event) => onChange({ bold: event.target.checked })}
            className="h-4 w-4 accent-sky-600"
          />
          Bold
        </label>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            checked={Boolean(value.italic)}
            onChange={(event) => onChange({ italic: event.target.checked })}
            className="h-4 w-4 accent-sky-600"
          />
          Italic
        </label>
      </div>
    </div>
  );
}

function numberToDraft(value: number | undefined, fallback: number): string {
  const source = Number.isFinite(value) ? value : fallback;
  return Number.isFinite(source) ? String(source) : "";
}

function NumberInput({
  value,
  fallback,
  onValidChange,
  className = inputClass,
  min,
  step,
}: {
  value: number | undefined;
  fallback: number;
  onValidChange: (value: number | undefined) => void;
  className?: string;
  min?: string;
  step?: string;
}) {
  const [draft, setDraft] = useState(() => numberToDraft(value, fallback));

  useEffect(() => {
    setDraft(numberToDraft(value, fallback));
  }, [fallback, value]);

  function commit(nextDraft: string) {
    setDraft(nextDraft);
    const trimmed = nextDraft.trim();
    if (!trimmed || trimmed === "-" || trimmed === "." || trimmed === ",") {
      return;
    }
    const next = numberOrUndefined(trimmed);
    if (next !== undefined) {
      onValidChange(next);
    }
  }

  return (
    <input
      type="number"
      min={min}
      step={step}
      value={draft}
      onChange={(event) => commit(event.target.value)}
      onBlur={() => {
        if (!draft.trim()) {
          setDraft(numberToDraft(value, fallback));
        }
      }}
      className={className}
    />
  );
}
