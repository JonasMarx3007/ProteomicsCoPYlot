import type { AdvancedPlotControlDefaults } from "../components/plots/AdvancedPlotOptions";

/**
 * What the frame and grid controls show before anything is changed: the plot
 * as it is actually drawn.
 *
 * These are not settings -- nothing here is ever sent. They are what an
 * untouched control displays, so they have to describe the native figure, or
 * the panel tells the user the plot has a dashed grey grid and a navy frame it
 * does not have. Every value was read off the renderers: matplotlib draws all
 * four spines in black at 0.8 pt and no grid, unless the plot says otherwise;
 * Plotly draws no frame and the grid of its template -- white on the default
 * template, pale grey on `plotly_white`.
 *
 * There used to be a copy of these in App.tsx, one on the QC page and one on
 * the Completeness page, and they disagreed with each other and with the plots.
 */

// A grid that is off still shows a colour, width and style: the ones it will be
// drawn in when switched on, which for matplotlib are its own.
const MATPLOTLIB_GRID_WHEN_ON = {
  gridLineColor: "#b0b0b0",
  gridLineWidth: 0.8,
  gridLineStyle: "solid",
} as const;

export const MATPLOTLIB_CONTROLS: AdvancedPlotControlDefaults = {
  axisLineLeft: true,
  axisLineRight: true,
  axisLineBottom: true,
  axisLineTop: true,
  axisLineColor: "#000000",
  axisLineWidth: 0.8,
  axisLineStyle: "solid",
  gridLineVisible: false,
  gridLineAxis: "y",
  ...MATPLOTLIB_GRID_WHEN_ON,
};

/** Left and bottom spines only: the static volcano, the phosphosite plot. */
export const MATPLOTLIB_LEFT_BOTTOM_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_CONTROLS,
  axisLineRight: false,
  axisLineTop: false,
};

/** No frame: the heatmaps and the Venn diagram. */
export const MATPLOTLIB_NO_FRAME_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_CONTROLS,
  axisLineLeft: false,
  axisLineRight: false,
  axisLineBottom: false,
  axisLineTop: false,
};

/** A grid on both axes: the single-protein line plot, the static Pearson plot. */
export const MATPLOTLIB_BOTH_GRID_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_CONTROLS,
  gridLineVisible: true,
  gridLineAxis: "both",
};

/** Left and bottom spines and a y grid: the S/T/Y counts. */
export const MATPLOTLIB_LEFT_BOTTOM_Y_GRID_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_LEFT_BOTTOM_CONTROLS,
  gridLineVisible: true,
  gridLineAxis: "y",
};

/** A dashed y grid: the missing value plot. */
export const MATPLOTLIB_Y_DASHED_GRID_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_CONTROLS,
  gridLineVisible: true,
  gridLineAxis: "y",
  gridLineStyle: "dashed",
};

// Plotly draws no axis line. The colour shown is the one a line is drawn in
// when a side is switched on -- the template's own would be white or pale grey,
// which on these backgrounds is a line nobody can see.
const PLOTLY_FRAME_OFF = {
  axisLineLeft: false,
  axisLineRight: false,
  axisLineBottom: false,
  axisLineTop: false,
  axisLineColor: "#111827",
  axisLineWidth: 1,
  axisLineStyle: "solid",
} as const;

/** Plotly's default template: white grid on a blue-grey plot area. */
export const PLOTLY_DEFAULT_TEMPLATE_CONTROLS: AdvancedPlotControlDefaults = {
  ...PLOTLY_FRAME_OFF,
  gridLineVisible: true,
  gridLineAxis: "both",
  gridLineColor: "#ffffff",
  gridLineWidth: 1,
  gridLineStyle: "solid",
};

/** `plotly_white`: pale grey grid on white. */
export const PLOTLY_WHITE_TEMPLATE_CONTROLS: AdvancedPlotControlDefaults = {
  ...PLOTLY_DEFAULT_TEMPLATE_CONTROLS,
  gridLineColor: "#ebf0f8",
};
