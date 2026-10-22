# ProteomicsCoPYlot R example: a complete workflow on the bundled HEK293 example
# (WT vs GRK, five replicates each), with the same analyses as the app and the
# Python example: completeness, normalization, filtering, imputation, QC,
# differential testing, ANOVA, GO over-representation, PCA scores, the
# phosphosite collapse and single-protein views.
#
# Run from the repository: Rscript examples/example.R
# Or set PROTEOMICS_COPYLOT_FUNCTIONS to the path of notebook_functions.R.

functions_path <- Sys.getenv("PROTEOMICS_COPYLOT_FUNCTIONS", unset = "")
if (!nzchar(functions_path)) {
  script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])
  start <- if (!is.na(script)) dirname(normalizePath(script)) else getwd()
  candidates <- file.path(c(start, dirname(start), getwd(), dirname(getwd())),
                          "proteomicscopylot", "notebook_functions.R")
  functions_path <- candidates[file.exists(candidates)][1]
}
if (is.na(functions_path) || !file.exists(functions_path)) {
  stop("Could not find notebook_functions.R; set PROTEOMICS_COPYLOT_FUNCTIONS.", call. = FALSE)
}
source(functions_path)

# Load the example ---------------------------------------------------------
# The protein and phosphosite tables are Spectronaut reports on the log2 scale.
data <- load_example_data("protein")
meta <- load_example_data("protein_metadata")
sites <- load_example_data("phospho")
meta_sites <- load_example_data("phospho_metadata")
conditions <- c("WT", "GRK")

# Protein: completeness ----------------------------------------------------
fig <- missing_value_plot(data, meta, data_scale = "log2")
fig <- missing_value_heatmap(data, meta, id = FALSE, data_scale = "log2")
print(missing_sample_table(data, meta, id = FALSE, data_scale = "log2"))

# Filtering and normalization ----------------------------------------------
# As in the app: the valid-value filter decides the rows, then the normalization
# is fitted on those rows and applied to every row, so rows with many missing
# values (mostly low-abundance, missing unevenly between groups) never set the
# reference. Here at least 3 valid values in each condition, then median
# centring. The app's default is no filter; choose your own.
kept <- filter_data(data, meta, 3, mode = "per_group")
normalized <- normalize_data(data, meta, "median", fit_rows = rownames(kept))
filtered <- normalized[rownames(kept), ]
cat(nrow(data), "proteins,", nrow(filtered), "after filtering\n")

# Imputation ---------------------------------------------------------------
# The default draws missing values around the 1% quantile of each sample's
# observed values with 0.3 times their standard deviation; method = "numerical"
# uses the Perseus downshift. R's random generator differs from numpy's, so the
# drawn values differ from Python's with the same seed.
imputed <- impute_values(filtered, meta, seed = 1337)

# QC -------------------------------------------------------------------------
# QC describes the normalized, unfiltered matrix. CV and abundance are defined on
# linear intensities; correlation uses log2.
linear <- inverse_log2_transform_data(normalized, meta)
fig <- coverage_plot(normalized, meta, id = FALSE, data_scale = "log2")
fig <- boxplot_int(normalized, meta)
fig <- histo_int(normalized, meta)
fig <- cov_plot(linear, meta, data_scale = "linear")
fig <- abundance_plot(linear, meta, workflow = "Protein", data_scale = "linear")
fig <- corr_plot(normalized, meta, id = FALSE, data_scale = "log2")
fig <- pca_plot(imputed, meta)
print(head(pca_scores(imputed, meta)))

# Differential abundance -----------------------------------------------------
# log2 fold changes are condition 1 minus condition 2: positive is higher in WT.
# test_type: "unpaired" (Student), "unpaired_welch" (Welch) or "paired".
volcano <- volcano_data_f(filtered, meta, "WT", "GRK", workflow = "Protein", test_type = "unpaired")
print(table(volcano$significance))
fig <- volcano_plot(volcano, "WT", "GRK")
welch <- volcano_data_f(filtered, meta, "WT", "GRK", workflow = "Protein", test_type = "unpaired_welch")
print(table(welch$significance))
# With imputed values, pass the non-imputed matrix as `observed` to count them.
volcano_imputed <- volcano_data_f(imputed, meta, "WT", "GRK", workflow = "Protein", observed = filtered)
print(summary(volcano_imputed$imputed_values))
# A paired test needs a pair_id column linking each sample to its partner in the
# other condition. This example is not paired, so the call is only shown:
#   paired_meta <- transform(meta, pair_id = rep(as.character(1:5), 2))
#   paired <- volcano_data_f(filtered, paired_meta, "WT", "GRK", test_type = "paired")

# ANOVA ------------------------------------------------------------------------
# One-way ANOVA across all conditions; with two it matches the Student t-test.
anova <- anova_data_f(filtered, meta)
fig <- anova_plot(anova, meta)

# GO over-representation -----------------------------------------------------
genes <- different_genes(filtered, meta, "WT", "GRK", workflow = "Protein")
significant <- c(genes$Upregulated, genes$Downregulated)
print(head(enrichment_data(significant, background = genes$Background)))
fig <- enrichment_analysis(significant, background = genes$Background)

# Single protein and comparison --------------------------------------------
protein_id <- as.character(na.omit(filtered$ProteinNames)[1])
by_protein <- filtered
rownames(by_protein) <- by_protein$ProteinNames
fig <- boxplot_int_single_prot(by_protein, meta, protein_id, dots = TRUE)
fig <- compare_prot_line(filtered, meta, conditions, c(protein_id), workflow = "Protein", id = FALSE)
fig <- correlation_xy_intensity(normalized, meta, "WT", "GRK")
fig <- overlap_plot_condition(normalized, meta, "WT", "GRK", data_scale = "log2")

# Phosphosites ---------------------------------------------------------------
fig <- simple_phos_site_plot(sites)
fig <- phossite_coverage_plot(sites, meta_sites, id = FALSE)
fig <- sty_plot(sites)
fig <- missing_value_plot(sites, meta_sites, data_scale = "log2")
sites_filtered <- filter_data(sites, meta_sites, 3, mode = "per_group")
site_volcano <- volcano_data_f(sites_filtered, meta_sites, "WT", "GRK", workflow = "Phosphosite")
fig <- volcano_plot(site_volcano, "WT", "GRK")
site_id <- as.character(na.omit(sites_filtered$PTM_Collapse_key)[1])
by_site <- sites_filtered
rownames(by_site) <- by_site$PTM_Collapse_key
fig <- boxplot_int_single_prot(by_site, meta_sites, site_id, dots = TRUE)
protein_of_site <- as.character(na.omit(sites_filtered$Protein_group)[1])
fig <- phossite_on_prot_regulation(sites_filtered, meta_sites, protein_of_site, conditions = conditions, id = FALSE)
# filter_localization(sites, 0.75) keeps only Class I sites (localization
# probability of at least 0.75); transform_phosprot takes it as localization_cutoff.

# Phosphoproteins ------------------------------------------------------------
# Sites are collapsed per protein. The default robust_site_median centres every
# site on log2 and takes the protein median, keeping per-sample site coverage.
phosprot <- transform_phosprot(sites, meta_sites, mode = "robust_site_median", data_scale = "log2")
phosprot_filtered <- filter_data(phosprot, meta_sites, 3, mode = "per_group")
cat(nrow(phosprot), "phosphoproteins,", nrow(phosprot_filtered), "after filtering\n")
fig <- phossite_dist(phosprot, cutoff = 0.01)
phosprot_volcano <- volcano_data_f(phosprot_filtered, meta_sites, "WT", "GRK", workflow = "Phosphoprotein")
fig <- volcano_plot(phosprot_volcano, "WT", "GRK")
phosprot_id <- as.character(na.omit(phosprot_filtered$Phosphoprotein)[1])
fig <- compare_prot_line(phosprot_filtered, meta_sites, conditions, c(phosprot_id), workflow = "Phosphoprotein", id = FALSE)
