// The advanced plot panel's per-plot rules: which plot it styles on a page, and
// which of its cards that plot's renderer actually reads. Kept out of App.tsx so
// they can be tested directly (tests/component/advanced-panel-rules.test.ts).
import type { AdvancedPlotVisibleControls } from "../components/plots/AdvancedPlotOptions";
import type { ContextModes } from "./contextModes";

/**
 * Which plot the advanced panel styles on the current page, or null where there
 * is no figure for it to act on.
 */
export function advancedPlotKey(nav: {
  activeSection: string;
  activeDataTab: string;
  activeStatsTab: string;
  activePeptideTab: string;
  activeSingleProteinTab: string;
  activePhosphoTab: string;
  activeComparisonTab: string;
}): string | null {
  const {
    activeSection, activeDataTab, activeStatsTab, activePeptideTab,
    activeSingleProteinTab, activePhosphoTab, activeComparisonTab,
  } = nav;
  if (activeSection === "data" && activeDataTab === "distribution") {
    return "data:distribution";
  }
  if (activeSection === "stats") {
    return activeStatsTab === "simulation" ? null : `stats:${activeStatsTab}`;
  }
  if (activeSection === "peptide") {
    // Sequence coverage is an HTML coverage map and a text download, not a
    // figure, so there is nothing for the plot panel to style.
    return activePeptideTab === "sequenceCoverage" ? null : `peptide:${activePeptideTab}`;
  }
  if (activeSection === "singleProtein") return `singleProtein:${activeSingleProteinTab}`;
  if (activeSection === "phospho") return `phospho:${activePhosphoTab}`;
  if (activeSection === "comparison") return `comparison:${activeComparisonTab}`;
  return null;
}

/** Which cards the advanced panel shows for a plot. */
export function advancedVisibleControls(
  activeAdvancedPlotKey: string | null,
  contextModes: ContextModes
): AdvancedPlotVisibleControls {
  switch (activeAdvancedPlotKey) {
    // A card is shown when the plot's renderer reads the keys it writes.
    // `conditionLabels`, `sampleLabels`, `conditionColors`, `legendControls`,
    // `backgroundControls` and `axisLineControls` default to shown, so a plot
    // that does not use them has to say so -- otherwise the panel offers, for
    // example, a legend card on a Venn diagram that draws no legend, and
    // sample-name rows on a figure with no samples on it. Checked against the
    // renderers in backend/app/services on 2026-09-17.
    case "stats:volcano":
      return {
        volcanoMarkers: true,
        referenceLineColor: true,
        // Both renderers build their title and fold-change axis label
        // through `_volcano_condition_texts`, so a rename reaches them (the
        // sign convention is still `comparison_contrast`'s).
        conditionLabels: true,
        sampleLabels: false,
        conditionColors: false,
      };
    case "singleProtein:boxplot":
      return {
        boxplotStyle: true,
        boxplotOutliers: true,
        boxplotPoints: true,
        // The jittered points are drawn one condition at a time.
        conditionMarkers: true,
        sampleLabels: false,
      };
    case "singleProtein:lineplot":
      // `single_protein_lineplot_plot` draws `marker="o"` on every line and
      // reads none of the marker keys, and its x axis is the sample list from
      // the annotation, which no condition rename passes through -- the
      // renaming there is the boxplot's, not this plot's.
      return { conditionLabels: false, sampleLabels: false, conditionColors: false };
    case "comparison:pearson":
      return {
        markerStyle: true,
        // Both renderers draw the regression fit under this setting (the
        // static PNG since 2026-09-25), so the card applies to either type.
        referenceLineColor: true,
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "comparison:venn":
      return {
        vennColors: true,
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "data:distribution":
    case "peptide:rtPlot":
      return {
        markerStyle: true,
        // The Q-Q fit and the retention-time identity line.
        referenceLineColor: true,
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "phospho:ksea":
      return {
        markerStyle: true,
        // `ksea_uploaded_volcano_html` draws the p-value line.
        referenceLineColor: true,
        // It draws one scatter per significance class, each handed its own
        // colour, and a colour passed by the plot wins over `markerColor`.
        markerColor: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "phospho:phosprotRegulation":
      // The tab is `phosprotRegulation` (lib/types.ts PhosphoTab), so the old
      // "phospho:regulation" label never matched: the phosphoprotein
      // regulation plot showed no Points card while its renderer reads
      // markerSize, markerAlpha and the outline keys.
      return {
        markerStyle: true,
        // Both renderers colour the points from `color_val` through a colour
        // scale and pass `use_color=False`, so a dot colour is read and
        // thrown away. Neither draws a threshold line over the figure.
        markerColor: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "singleProtein:heatmap":
      return {
        correlationGradient: true,
        legendControls: false,
        conditionColors: false,
      };
    case "stats:pathwayHeatmap":
      return {
        correlationGradient: true,
        legendControls: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "phospho:coverage":
      // `phospho_coverage_png` prints no number on any bar, in either mode.
      return { phosphoClassColors: true, sampleLabels: false };
    case "phospho:phosphositePlot":
    case "phospho:distribution":
      return {
        barColor: true,
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
        // The phosphosite plot clears its x ticks, so tick styling has
        // nothing to style.
        tickControls: activeAdvancedPlotKey !== "phospho:phosphositePlot",
      };
    case "peptide:missedCleavage":
      // The only one of the two that writes on its bars: the percentage of
      // sequences with at least one missed cleavage, at `advanced_label_size`.
      return {
        valueLabels: true,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "peptide:modification":
      // `peptide_modification_plot` draws its grouped bars and stops.
      return {
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "stats:anova":
      // The cluster heatmaps name their rows when "Show feature names" is on;
      // the Row labels card styles them and is only there while they are.
      return {
        rowLabels: contextModes["stats:anova"]?.showRowLabels === true,
      };
    case "stats:ora":
      return {
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    case "phospho:sty":
      // `phospho_sty_png` draws S, T and Y each in its own fixed colour and
      // never reads `barColor`; one bar colour would have to overwrite three.
      return {
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
      };
    default:
      return {};
  }
}
