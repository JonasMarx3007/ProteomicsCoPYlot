"""Read-only method descriptions; never inspect or mutate an uploaded dataset."""
from app.schemas.assistant import Evidence

# "What is the best order to go through the analysis?" (2026-10-09) had only page-level
# method texts to draw on and was answered with volcano settings alone.
WORKFLOW_GUIDE = "A typical path through Proteomics CoPYlot, as a suggestion; every setting stays the user's choice. 1. Data / Upload and Data / Annotation: load the matrix, assign samples to conditions, declare whether values are log2, and apply the valid-value filter, then (as a second step) a normalization fitted on the rows the filter kept; none are imposed. 2. QC Pipeline: Coverage Plot (identifications per sample), Histogram Intensity and Boxplot Intensity (are samples comparable in level and spread), CV Plot (replicate precision), Principal Component Analysis and Correlation Plot (do replicates group by condition; does a sample stand apart). 3. Completeness: Missing Value Plot and Heatmap, to see whether missingness differs between conditions before deciding whether to impute (Data / Imputation is optional). 4. Statistical Analysis: Volcano Plot for two conditions (choose the contrast, test and thresholds), ANOVA for more than two conditions (these are the tool's designs: two-group tests, control-corrected contrasts and a one-way ANOVA, with pairing as the only blocking; batches, covariates and repeated measures are not modelled), GO Enrichment (ORA) and Pathway Heatmap to interpret hit lists, Replicate & Variance Projection as a what-if view of the same comparison at other replicate counts (not a power calculation). 5. Single Protein for individual proteins or sites; Phospho-specific pages for phosphosite data (localization, STY, Kinase Library inputs); Comparison for two datasets; Summary for tables, text and the report. Downloads are the user's own (the assistant never presses them): every plot has a format choice and Download Plot; result tables (Volcano, ANOVA, GO Enrichment and others) have Download CSV above the table, which Excel opens; Export notebook gives a reproducible notebook of a plot; Summary / Report builds the report."

METHODS = {
    "data.distribution": "Pools sample values from the distribution service's selected source and reports descriptive statistics, with population standard deviation. A QQ plot compares a distribution with a normal reference; numerical summaries alone do not establish normality, batch effects or an imputation mechanism.",
    "stats.simulation": "A what-if projection, not a power calculation: the observed mean fold changes are held fixed and the independent-sample t-test is recomputed for an assumed variance factor and number of replicates per group. Nothing is drawn at random. The observed fold changes include noise, so the projection is optimistic for effects that look large, and it does not estimate the probability of detecting a true effect. Interpret the selected pooled-variance/Welch test and raw/BH-adjusted p-values explicitly.",
    "phospho.ksea": "Prepares testable phosphosite fold changes and p-values for an external Kinase Library tool. These are inputs, not calculated kinase activity. Uploaded external kinase plots have separate provenance and are not evidence of activity from the export table; substrate counts and kinase-level scores require the external result data.",
    "analysis.canvas": "The canvas composes multiple analysis tiles and reusable entity selections. It is not a single statistical test. Interpret each tile using its own source, contrast and method; the composition itself does not supply a combined scientific conclusion.",
    "stats.anova": "One-way independent-groups ANOVA tests whether all condition means are equal, assuming equal population variances. Rows need sufficient replicates in every condition; undefined tests are excluded. The selected metric is raw p or BH-adjusted p across finite tests. Omnibus significance does not identify a particular condition pair or direction. Optional Tukey HSD provides pairwise follow-up; clustering of significant rows describes patterns and is not an additional significance test. Scope: one factor (the condition) only; no covariates, batch terms, blocking or repeated measures, and no interaction tests.",
    "qc.cv": "CV = 100 * sample standard deviation / mean, within each condition, on linear intensities before imputation (log2 values are back-transformed first; when a normalization was applied, the normalized values are used, except after VSN). Sample SD uses ddof=1. Missing observations are excluded, not zero-filled; nonfinite CVs are excluded. This is descriptive variability, not a statistical significance test or a universal quality threshold.",
    "stats.volcano": "The x-axis is the selected contrast's log2 fold change; the first selected condition minus the second for the ordinary comparison, so a positive value means higher in condition 1. The control variant is (condition 1 - its control) minus (condition 2 - its control). The y-axis is -log10 of the selected p-metric, adjusted unless uncorrected values were selected. BH adjustment controls false discovery rate across the applicable test family. The selected test, pairing and thresholds determine inference; inspect results for their actual values. Log2FC=1 corresponds to a twofold ratio. Statistical significance does not prove biological importance or causality. Moderated test types (limma) shrink each row's variance towards a prior fitted to all rows and run in R; the robust variants fit that prior robustly. Fold changes and BH correction are unchanged; only the p-values differ. Scope: two-group comparisons and control-corrected contrasts only; pairing is the only blocking modelled, so there is no adjustment for batches, covariates or other factors.",
    "qc.coverage": "Counts observed entities in the selected workflow and samples. Peptide and precursor counts are different quantities. Detection depends on the declared scale: zero is non-detection on linear intensity but a valid value on log2 intensity. Missing values remain missing.",
    "qc.histogram": "Displays an intensity distribution. The selected aggregation and data source determine what each observation represents; do not infer individual-sample behavior from condition averages.",
    "qc.boxplot": "Summarizes intensity distributions with medians, quartiles and whiskers. A boxplot is descriptive and cannot establish batch effects or biological differences on its own.",
    "qc.pca": "Projects the selected matrix into fewer dimensions. PCA variance percentages apply to PCA, not arbitrary projections. Scaling, source and selected method affect the geometry. Separation alone does not establish significance or causality.",
    "qc.abundance": "Ranks abundance values. The selected condition and source determine the represented entities; a rank curve is not a differential-expression test.",
    "qc.correlation": "Summarizes sample correlations. Constant or insufficiently overlapping data can yield undefined correlations, which must not be invented or silently replaced with similarity.",
    "completeness.missingPlot": "Summarizes missing observations for the selected workflow and aggregation. Missingness does not establish biological absence or a missing-data mechanism.",
    "completeness.heatmap": "Displays missingness patterns. Aggregate missingness counts do not establish a particular row-level or block pattern without the corresponding matrix evidence.",
    "completeness.tables": "Reports completeness under the selected sample/condition rules. Totals and thresholds describe the chosen definition, not an automatic recommendation to filter or impute.",
    "stats.ora": "Tests over-representation using a one-sided hypergeometric test and BH adjustment within each query's size-eligible, nonzero-overlap term family. The query and background must be appropriate. Display limits do not change adjusted p-values.",
    "stats.pathwayHeatmap": "Displays selected pathway-associated entities on the selected scale. A heatmap pattern alone is not evidence of pathway activation or an enrichment test.",
    "singleProtein.boxplot": "Displays a selected protein or site's values by condition. Check identifier, source and any selected statistical test before interpreting a difference.",
    "singleProtein.lineplot": "Displays the selected entity across samples, retaining samples with missing measurements. Lines connect consecutive observed points. Show NA as low optionally draws missing positions at log2 0 (linear 1) without markers; these are display-only vertices, not measured or imputed values. Connecting points does not by itself establish a time course or paired design.",
    "singleProtein.heatmap": "Displays phosphorylation sites associated with the selected protein. Site-level abundance and protein-level abundance are distinct measurements.",
    "comparison.pearson": "Compares paired numerical observations using Pearson correlation. Correlation measures linear association, not agreement or causality; undefined coefficients require explicit reporting.",
    "comparison.venn": "Displays overlaps between selected entity sets. Set membership and identifier rules determine the counts; overlap alone is not an enrichment significance test.",
    "phospho.phosphositePlot": "Counts the phosphoproteins, phosphopeptides and phosphosites in the dataset after the localization cutoff (a bar per count; no single site is selected here, one site's values are on the Single Protein pages). Localization and abundance are different quantities; site regulation does not alone establish kinase activity.",
    "phospho.coverage": "Counts sites using the application's localization categories. Unknown localization is unclassified rather than assigned an invented quality class.",
    "phospho.distribution": "Summarizes the selected phosphosite distribution. Interpret the actual aggregation and localization selections from results rather than assuming defaults.",
    "phospho.sty": "Summarizes serine, threonine and tyrosine site composition. Composition reflects measured sites and experimental coverage, not unbiased proteome-wide phosphorylation prevalence.",
    "phospho.phosprotRegulation": "Tests every phosphosite with the selected volcano test and thresholds, then plots each protein with at least one significant site: the x-axis is the sum of its upregulated sites' log2 fold changes, the y-axis the absolute sum of its downregulated sites' log2 fold changes. It uses site-level data only; protein abundance is not included or corrected for. Inspect source and contrast direction; do not equate site abundance with occupancy.",
    "peptide.rtPlot": "Displays peptide retention-time information. Observed differences do not alone establish chromatography failure; check source, units and aggregation.",
    "peptide.modification": "Summarizes observed peptide modifications. Counts depend on peptide/precursor identity and selected quantity; they do not directly establish modification occupancy.",
    "peptide.missedCleavage": "Summarizes missed-cleavage information under the selected peptide processing rules. A descriptive distribution alone does not determine digestion quality without a stated criterion.",
    "peptide.sequenceCoverage": "Maps observed peptide sequences onto a protein sequence. Sequence coverage is not intensity coverage and does not prove absence of unobserved sequence regions.",
}


_CV_SOURCE_SENTENCES = {
    "none": "Use original uploaded linear intensities before application of imputation; back-transform log2 uploads first.",
    "vsn": "After VSN the unnormalized intensities of the same rows are used, because VSN's glog output back-transformed is not a linear intensity; imputation is not applied.",
}


def cv_method_text(normalization: str | None) -> str:
    """The CV method sentence for the normalization the session applied.

    With no normalization the original wording stands (uploaded linear
    intensities before imputation); a normalization is mentioned only when one
    was applied, VSN with its exception.
    """
    mode = str(normalization or "none").strip().lower()
    source = _CV_SOURCE_SENTENCES.get(mode) or (
        f"Computed on the {mode}-normalized values back-transformed to linear intensities, before imputation."
    )
    return (
        "CV = 100 * sample standard deviation / mean, within each condition. " + source
        + " Sample SD uses ddof=1. Missing observations are excluded, not zero-filled; nonfinite CVs are excluded."
        " This is descriptive variability, not a statistical significance test or a universal quality threshold."
    )


def method_evidence(module: str) -> Evidence:
    if module == "workflow.overview":
        return Evidence(tool="method:workflow.overview", status="available", text=WORKFLOW_GUIDE)
    text = METHODS.get(module)
    return Evidence(tool=f"method:{module}", status="available" if text else "unavailable",
                    text=text or "No reviewed standalone method description exists for this module.")


def canvas_workflow_guidance() -> Evidence:
    return Evidence(tool="workflow:analysis.canvas", status="available", text=(
        "To build a focused canvas, ask for a protein or an exact phosphosite identifier—for example, "
        "‘Show everything on the canvas for phosphosite YOUR_SITE’. To expand a protein into sites, "
        "explicitly ask ‘Show all phosphosites on protein YOUR_PROTEIN on the canvas’. "
        "Protein, phosphosite and phosphoprotein data stay separate; the requested level must be loaded.\n\n"
        "You can specify the reference and target conditions. Otherwise the linked comparison is used, "
        "or the two available conditions; ambiguous choices require clarification. The app creates a "
        "highlighted volcano, an individual boxplot per feature and a shared lineplot. It keeps unrelated "
        "tiles and reuses the same focused group on repeated requests. To change an existing canvas's "
        "data level, save any work you need, then use an empty canvas.\n\n"
        "For manual setup, open Analysis, select a plot type and use + Add Plot. Each tile has its own "
        "controls and Plot styling section. Focus does not run enrichment or change preprocessing. "
        "Wait for plots to load before interpreting them; a feature excluded from the volcano comparison "
        "can still appear in its boxplot and lineplot. This is guidance only; nothing was changed."
    ))
