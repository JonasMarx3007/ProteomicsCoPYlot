# Runs the R notebook package over a fixture supplied by
# tests/parity/test_cross_implementation.py and writes results for comparison
# against the Python package.
#
# The two packages are maintained by hand as separate implementations of the
# same analyses. They have silently diverged before: R's volcano aborted on
# constant rows where Python returned results, and ANOVA p-values differed by up
# to 0.54 because the packages disagreed about transformed zero. This script is
# the R half of the guard against that recurring. See finding B5.
#
# Usage: Rscript cross_implementation.R <fixture_dir>

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1L) stop("usage: cross_implementation.R <fixture_dir>")
fixture_dir <- args[1]

script_args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", script_args, value = TRUE)
script_path <- if (length(file_arg)) {
  sub("^--file=", "", file_arg[1])
} else {
  "tests/parity/r/cross_implementation.R"
}
repo_root <- normalizePath(file.path(dirname(script_path), "..", "..", ".."), mustWork = TRUE)
source(file.path(repo_root, "proteomicscopylot", "notebook_functions.R"))

data <- read.csv(file.path(fixture_dir, "data.csv"), check.names = FALSE)
meta <- read.csv(file.path(fixture_dir, "meta.csv"), check.names = FALSE)

write_result <- function(name, value) {
  write.csv(value, file.path(fixture_dir, paste0("r_", name, ".csv")), row.names = FALSE)
}

# Any error here must fail the test rather than be silently skipped: "R could not
# produce a result at all" is exactly the divergence this guard exists to catch.
filtered <- filter_data(data, meta, 3, "per_group", "at_least_n", 70)
write_result("filter", data.frame(ProteinNames = as.character(filtered$ProteinNames), stringsAsFactors = FALSE))

volcano <- volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein")
write_result("volcano", volcano[, c("ProteinNames", "log2FC", "pval", "adj_pval")])

# Ported 2026-08-05: normalization (A1) previously existed only in the web app,
# so it was not covered here.
for (method in c("median", "quantile")) {
  normalized <- normalize_data(data, as.character(meta$sample), method)
  write_result(
    paste0("normalize_", method),
    normalized[, c("ProteinNames", as.character(meta$sample))]
  )
}

for (test_type in c("unpaired_welch")) {
  variant <- volcano_data_f(
    data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = test_type
  )
  write_result(
    paste0("volcano_", test_type),
    variant[, c("ProteinNames", "log2FC", "pval", "adj_pval")]
  )
}

control <- volcano_data_f_control(
  data, meta, "Ctrl", "Treat", "Third", "Fourth",
  workflow = "Protein", uncorrected = TRUE, in_log2fc = 0
)
write_result(
  "volcano_control",
  control[, c("ProteinNames", "log2FC", "pval", "adj_pval")]
)

test_types <- c(
  "unpaired", "unpaired_welch", "paired"
)
for (test_type in test_types) {
  control_variant <- volcano_data_f_control(
    data, meta, "Ctrl", "Treat", "Third", "Fourth",
    workflow = "Protein", uncorrected = TRUE, in_log2fc = 0,
    test_type = test_type
  )
  write_result(
    paste0("volcano_control_", test_type),
    control_variant[, c("ProteinNames", "log2FC", "pval", "adj_pval")]
  )

  ksea_input <- data
  ksea_input$UPD_seq <- ksea_input$ProteinNames
  ksea_variant <- ksea_data_f(
    ksea_input, meta, "Ctrl", "Treat", test_type = test_type
  )
  write_result(
    paste0("ksea_", test_type),
    ksea_variant[, c("UPD_seq", "log2FC", "pval", "adj_pval")]
  )
}

posthoc <- anova_posthoc_data(
  anova_data_f(data, meta, conditions = c("Ctrl", "Treat", "Third", "Fourth"), workflow = "Protein"),
  meta
)
write_result(
  "anova_posthoc",
  posthoc[, c("ProteinNames", "comparison", "log2FC", "q_statistic", "tukey_pval")]
)

anova <- anova_data_f(
  data,
  meta,
  conditions = c("Ctrl", "Treat", "Third", "Fourth"),
  workflow = "Protein"
)
# The natural order, before the comparison re-sort below. Both sides used to
# normalise on ProteinNames, which is why the ordering difference (F2) was
# invisible to this harness.
write_result("anova_order", anova[, c("ProteinNames", "pval", "adj_pval")])
anova <- anova[order(anova$ProteinNames), ]
write_result("anova", anova[, c("ProteinNames", "f_statistic", "pval", "adj_pval")])

zero_meta <- data.frame(sample = c("z1", "z2"), condition = c("A", "A"))
raw_zero_fixture <- data.frame(
  label = c(0, 1, 2),
  z1 = c(0, 1, 2),
  z2 = c(1, 2, 4),
  check.names = FALSE
)
transformed <- log2_transform_data(raw_zero_fixture, zero_meta)
imputation_fixture <- data.frame(
  label = c(0, 1, 2),
  z1 = c(0, NA, 2),
  z2 = c(1, 2, 3),
  check.names = FALSE
)
imputed <- impute_values(imputation_fixture, zero_meta, seed = 7)
write_result("zero_contract", data.frame(
  raw_zero_missing = as.integer(is.na(transformed$z1[1])),
  raw_one_becomes_log2_zero = as.integer(transformed$z1[2] == 0),
  transformed_zero_preserved_by_imputation = as.integer(imputed$z1[1] == 0),
  actual_missing_value_imputed = as.integer(!is.na(imputed$z1[2])),
  annotation_zero_preserved = as.integer(imputed$label[1] == 0)
))

phospho <- read.csv(file.path(fixture_dir, "phospho.csv"), check.names = FALSE)
phospho_meta <- read.csv(file.path(fixture_dir, "phospho_meta.csv"), check.names = FALSE)
for (mode in c("robust_site_median", "sum_propagate_na", "sum_ignore_na", "mean")) {
  collapsed <- transform_phosprot(phospho, phospho_meta, mode = mode, data_scale = "log2")
  collapsed <- collapsed[order(collapsed$Phosphoprotein), ]
  write_result(paste0("phosprot_", mode), collapsed)
}

# Enrichment was figure-only in both packages until `enrichment_data` was split
# out, so a divergence here could not be seen at all (F4).
enrich_query <- read.csv(file.path(fixture_dir, "enrichment_query.csv"), check.names = FALSE)$gene
enrich_background <- read.csv(file.path(fixture_dir, "enrichment_background.csv"), check.names = FALSE)$gene
enrichment <- enrichment_data(
  as.character(enrich_query),
  top_n = 10, min_num = 5, max_num = 500,
  background = as.character(enrich_background),
  background_mode = "experiment",
  adj_p_value_cutoff = 1.0
)
write_result("enrichment", enrichment)

phospho_reg <- read.csv(file.path(fixture_dir, "phosreg.csv"), check.names = FALSE)
phospho_reg_meta <- read.csv(file.path(fixture_dir, "phosreg_meta.csv"), check.names = FALSE)
# Phosphoprotein regulation was figure-only in both packages until
# `phosprot_regulation_data` was split out (F4).
phosreg <- phosprot_regulation_data(
  phospho_reg, phospho_reg_meta, "A", "B", in_pval = 0.05, in_log2fc = 1.0
)
write_result("phosprot_regulation", phosreg[order(phosreg$Protein_group), ])

cat("ok\n")
