args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
script_path <- if (length(file_arg)) sub("^--file=", "", file_arg[1]) else "tests/r/test_notebook_functions.R"
repo_root <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = TRUE)

functions_path <- file.path(repo_root, "proteomicscopylot", "notebook_functions.R")
example_path <- file.path(repo_root, "examples", "example.R")

source(functions_path)
stopifnot(identical(
  normalizePath(.copylot_source_dir, mustWork = TRUE),
  normalizePath(dirname(functions_path), mustWork = TRUE)
))
required <- c(
  "read_data",
  "coverage_plot",
  "volcano_plot",
  "missing_value_plot",
  "missing_value_heatmap"
)
stopifnot(all(vapply(required, exists, logical(1), mode = "function")))
stopifnot(identical(formals(coverage_plot_summary)$seed, 69))
stopifnot(identical(bool_to_str(TRUE), "TRUE"))
stopifnot(identical(bool_to_str(FALSE), "FALSE"))
cv_data <- data.frame(
  ProteinNames = c("P1", "P2"),
  sample_1 = c(100, 200),
  sample_2 = c(110, 220),
  check.names = FALSE
)
cv_meta <- data.frame(
  sample = c("sample_1", "sample_2"),
  condition = c("control", "control")
)
cv_missing_scale_error <- tryCatch(
  {
    cov_plot(cv_data, cv_meta)
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("requires data_scale='linear'", cv_missing_scale_error, fixed = TRUE))
cv_log2_error <- tryCatch(
  {
    cov_plot(cv_data, cv_meta, data_scale = "log2")
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("requires linear intensities", cv_log2_error, fixed = TRUE))
grDevices::pdf(tempfile(fileext = ".pdf"))
invisible(cov_plot(cv_data, cv_meta, data_scale = "linear"))
invisible(grDevices::dev.off())
sample_inputs <- c(
  "[1] 20250725_nElute_tims1_JM_Mrowka_WP_01_Slot1-61_1_11156.htrms.PG.Log2Quantity",
  "[1] 20250725_nElute_tims1_JM_Mrowka_WP_01_Slot1-61_1_11156.htrms",
  "Z:\\Mario\\example\\20250131_nElute_tims1_MMu_A1D_Slot1-01_1_9790.d",
  "sample_2.d.PG.Log2Quantity",
  "sample_2.htrms",
  "sample_00042.d.PG.AvgLog2Quantity",
  "sample_00042.d.PG.Quantity",
  "sample_00042.d.PG.Normalised",
  "sample_00042.d.EG.TotalQuantity",
  "sample_00042.d.PG.MaxLFQ",
  "sample_00042.htrms.Precursor.Normalised",
  "sample_00042 MaxLFQ Intensity",
  "sample_00042 MaxLFQ Unique Intensity",
  "sample_00042 Total Spectral Count",
  "sample_00042 MS2 Count",
  "Intensity 01",
  "LFQ intensity 0002",
  "sample_without_an_identifier.raw"
)
sample_expected <- c(
  "11156", "11156", "9790", "2", "2", "00042", "00042", "00042", "00042",
  "00042", "00042", "00042", "00042", "00042", "00042", "01", "0002",
  "sample_without_an_identifier.raw"
)
stopifnot(identical(unname(vapply(sample_inputs, extract_sample_id, character(1))), sample_expected))
stopifnot(identical(unname(vapply(sample_inputs, extract_id_or_number, character(1))), sample_expected))
original_working_directory <- getwd()
setwd(tempdir())
go_db <- load_go_db()
setwd(original_working_directory)
stopifnot(all(c("ontology", "term", "description", "genes") %in% names(go_db)))
stopifnot(all(c("background", "background_mode", "workflow") %in% names(formals(enrichment_analysis))))
ora_missing_background_error <- tryCatch(
  {
    enrichment_analysis("TP53", min_num = 1, max_num = 10000)
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("tested-gene background", ora_missing_background_error, fixed = TRUE))
anova_fixture <- data.frame(
  GeneNames = c("A", "B"),
  s1 = c(1, 2),
  s2 = c(1.1, 2.1),
  adj_pval = c(0.5, 0.8),
  check.names = FALSE
)
anova_meta <- data.frame(
  sample = c("s1", "s2"),
  condition = c("one", "two")
)
empty_clusters <- anova_cluster_data(anova_fixture, anova_meta)
stopifnot(nrow(empty_clusters) == 0, "cluster" %in% names(empty_clusters))
all_clusters <- anova_cluster_data(
  anova_fixture,
  anova_meta,
  only_significant = FALSE,
  n_clusters = 2
)
stopifnot(nrow(all_clusters) == 2)
anova_fixture$adj_pval[1] <- 0.01
one_cluster <- anova_cluster_data(anova_fixture, anova_meta)
stopifnot(nrow(one_cluster) == 1, identical(one_cluster$GeneNames, "A"), one_cluster$cluster == 1)
offsets <- seq(-0.05, 0.05, length.out = 20)
group_one <- cbind(offsets, offsets, offsets, 3 + offsets, 3 + offsets, 3 + offsets)
group_two <- cbind(3 + offsets, 3 + offsets, 3 + offsets, offsets, offsets, offsets)
singleton <- matrix(c(0, 3, 0, 3, 0, 3), nrow = 1)
cluster_matrix <- rbind(group_one, singleton, group_two)
colnames(cluster_matrix) <- paste0("cs", seq_len(ncol(cluster_matrix)))
small_cluster_fixture <- data.frame(
  GeneNames = paste0("G", seq_len(nrow(cluster_matrix))),
  cluster_matrix,
  adj_pval = 0.01,
  check.names = FALSE
)
small_cluster_meta <- data.frame(
  sample = colnames(cluster_matrix),
  condition = c(rep("one", 3), rep("two", 3))
)
small_clusters <- anova_cluster_data(small_cluster_fixture, small_cluster_meta, n_clusters = 3)
stopifnot(length(unique(small_clusters$cluster)) == 3)
stopifnot(identical(sort(as.integer(table(small_clusters$cluster))), c(1L, 20L, 20L)))
pathway_fixture <- data.frame(
  GeneNames = c("AKT1; MAPK1", "AKT1", "AKT1;AKT1", "AKT10", "ZERO"),
  s1 = c(2, 100, 4, -1000, 0),
  s2 = c(0, 4, NA, 10, 0),
  check.names = FALSE
)
pathway_aggregated <- .aggregate_pathway_gene_values(
  pathway_fixture,
  gene_column = "GeneNames",
  sample_columns = c("s1", "s2"),
  pathway_genes = c("AKT1", "akt1", "AKT10", "ZERO", "MISSING")
)
stopifnot(identical(rownames(pathway_aggregated$data), c("AKT1", "AKT10", "ZERO", "MISSING")))
stopifnot(identical(as.numeric(pathway_aggregated$data["AKT1", ]), c(4, 2)))
stopifnot(identical(as.numeric(pathway_aggregated$data["AKT10", ]), c(-1000, 10)))
stopifnot(identical(as.numeric(pathway_aggregated$data["ZERO", ]), c(0, 0)))
stopifnot(all(is.na(pathway_aggregated$data["MISSING", ])))
stopifnot(identical(
  unname(pathway_aggregated$source_feature_count),
  c(3L, 1L, 1L, 0L)
))
reordered_pathway <- .aggregate_pathway_gene_values(
  pathway_fixture[c(5, 3, 1, 4, 2), ],
  gene_column = "GeneNames",
  sample_columns = c("s1", "s2"),
  pathway_genes = c("AKT1", "akt1", "AKT10", "ZERO", "MISSING")
)
stopifnot(isTRUE(all.equal(pathway_aggregated$data, reordered_pathway$data, check.attributes = TRUE)))
stopifnot(identical(pathway_aggregated$source_feature_count, reordered_pathway$source_feature_count))
phosprot_meta <- data.frame(
  sample = c("a1", "a2", "b1", "b2"),
  condition = c("one", "one", "two", "two")
)
phosprot_data <- data.frame(
  Gene_group = c(" A ; B ; A ;;", "B; C", NA, "D;; E"),
  GeneNames = c("WRONG1", "WRONG2", "WRONG3", "WRONG4"),
  a1 = c(1, 10, 2, 1),
  a2 = c(1.2, 10.3, 2.2, 2),
  b1 = c(10, 1, 2, 1),
  b2 = c(10.3, 1.2, 2.2, 2),
  check.names = FALSE
)
phosprot_genes <- different_genes(
  phosprot_data,
  phosprot_meta,
  "one",
  "two",
  in_pval = 0.05,
  in_log2fc = 1,
  workflow = "Phosphoprotein",
  uncorrected = TRUE
)
stopifnot(
  identical(phosprot_genes$Upregulated, c("A", "B")),
  identical(phosprot_genes$Downregulated, c("B", "C")),
  identical(phosprot_genes$Background, c("A", "B", "C", "D", "E"))
)
fallback_data <- phosprot_data
fallback_data$Gene_group <- NULL
fallback_data$GeneNames <- c("A; B", "B; C", NA, "D; E")
fallback_genes <- different_genes(
  fallback_data,
  phosprot_meta,
  "one",
  "two",
  in_pval = 0.05,
  in_log2fc = 1,
  workflow = "Phosphoprotein",
  uncorrected = TRUE
)
stopifnot(
  identical(fallback_genes$Upregulated, c("A", "B")),
  identical(fallback_genes$Downregulated, c("B", "C")),
  identical(fallback_genes$Background, c("A", "B", "C", "D", "E"))
)
phosprot_data$Phosphoprotein <- c("P1", "P2", "P3", "P4")
phosprot_anova <- anova_data_f(
  phosprot_data,
  phosprot_meta,
  workflow = "Phosphoprotein",
  uncorrected = TRUE
)
stopifnot(
  "Gene_group" %in% names(phosprot_anova),
  identical(
    .different_gene_tokens(phosprot_anova$Gene_group, TRUE),
    c("A", "B", "C", "D", "E")
  )
)
regulation_meta <- data.frame(
  sample = c("a1", "a2", "a3", "b1", "b2", "b3"),
  condition = c("A", "A", "A", "B", "B", "B")
)
regulation_data <- data.frame(
  PTM_Collapse_key = c("up-1", "up-2", "down-1", "noise", "small"),
  Protein_group = c("P1", "P1", "P1", "P1", "P2"),
  a1 = c(10, 8, 15, 10, 10),
  a2 = c(10.1, 8.2, 15.2, 11, 10.1),
  a3 = c(9.9, 7.8, 14.8, 9, 9.9),
  b1 = c(12, 9.5, 12, 10.5, 10.5),
  b2 = c(12.1, 9.7, 12.2, 11.5, 10.6),
  b3 = c(11.9, 9.3, 11.8, 9.5, 10.4),
  check.names = FALSE
)
regulation_sites <- .volcano_stats(
  regulation_data,
  regulation_meta,
  "A",
  "B",
  "PTM_Collapse_key",
  "Unpaired",
  TRUE,
  "Protein_group"
)
regulation_summary <- .phosprot_regulation_data(
  regulation_sites,
  0.05,
  1,
  20,
  TRUE
)
stopifnot(
  identical(regulation_summary$Protein_group, "P1"),
  identical(regulation_summary$Upregulated_count, 2L),
  identical(regulation_summary$Downregulated_count, 1L),
  isTRUE(all.equal(regulation_summary$x, 3.5)),
  isTRUE(all.equal(regulation_summary$y, 3))
)
stricter_regulation <- .phosprot_regulation_data(
  regulation_sites,
  0.05,
  1.75,
  20,
  TRUE
)
stopifnot(
  identical(stricter_regulation$Upregulated_count, 1L),
  isTRUE(all.equal(stricter_regulation$x, 2)),
  isTRUE(all.equal(stricter_regulation$y, 3))
)
no_testable_data <- data.frame(
  ProteinNames = "P1",
  a1 = 1,
  a2 = NA,
  b1 = 2,
  b2 = NA,
  check.names = FALSE
)
no_testable_error <- tryCatch(
  {
    anova_data_f(no_testable_data, phosprot_meta)
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("No rows have enough replicate values for ANOVA", no_testable_error, fixed = TRUE))
filter_frame <- as.data.frame(rbind(
  c(1, 1, 1, NA, 1, 1, 1, 1, NA, NA),
  c(1, 1, NA, NA, 1, 1, 1, 1, NA, NA),
  c(1, 1, 1, NA, 1, 1, 1, 1, 1, NA)
))
names(filter_frame) <- paste0("s", seq_len(10))
filter_meta <- data.frame(
  sample = names(filter_frame),
  condition = c(rep("a", 4), rep("b", 6))
)
stopifnot(nrow(filter_data(filter_frame, filter_meta, 0, "overall", "percentage", 70)) == 2)
stopifnot(nrow(filter_data(filter_frame, filter_meta, 0, "per group", "percentage", 70)) == 1)
pair_meta <- data.frame(
  sample = c("before_c", "before_a", "before_d", "before_b",
             "after_d", "after_a", "after_c", "after_b"),
  condition = c(rep("before", 4), rep("after", 4)),
  pair_id = c("C", "A", "D", "B", "D", "A", "C", "B")
)
pair_data <- data.frame(
  ProteinNames = c("varied", "zero difference", "constant difference", "numeric zero"),
  before_a = c(1, 1, 1, 0),
  before_b = c(10, 2, 2, 1),
  before_c = c(100, 3, 3, 2),
  before_d = c(1000, 4, 4, 3),
  after_a = c(3, 1, 3, 1),
  after_b = c(14, 2, 4, 2),
  after_c = c(NA, 3, 5, 3),
  after_d = c(1009, 4, 6, 4),
  check.names = FALSE
)
pair_columns <- .paired_sample_columns(pair_meta, "before", "after")
stopifnot(identical(pair_columns$condition1, c("before_c", "before_a", "before_d", "before_b")))
stopifnot(identical(pair_columns$condition2, c("after_c", "after_a", "after_d", "after_b")))
partial_pair_meta <- data.frame(
  sample = c("before_c", "before_a", "before_b", "before_unpaired",
             "after_b", "after_d", "after_a"),
  condition = c(rep("before", 4), rep("after", 3)),
  pair_id = c("C", "A", "B", "", "B", "D", "A")
)
partial_pair_columns <- .paired_sample_columns(partial_pair_meta, "before", "after")
stopifnot(identical(partial_pair_columns$condition1, c("before_a", "before_b")))
stopifnot(identical(partial_pair_columns$condition2, c("after_a", "after_b")))
pair_result <- volcano_data_f(
  pair_data,
  pair_meta,
  "before",
  "after",
  workflow = "Protein",
  paired = "paired",
  uncorrected = TRUE
)
stopifnot(identical(pair_result$n_pairs, c(3L, 4L, 4L, 4L)))
stopifnot(isTRUE(all.equal(pair_result$log2FC, c(5, 0, 2, 1))))
stopifnot(identical(pair_result$pval[2:3], c(1, 0)))
reordered_result <- volcano_data_f(
  pair_data,
  pair_meta[c(8, 2, 5, 1, 6, 4, 7, 3), ],
  "before",
  "after",
  workflow = "Protein",
  paired = "Paired",
  uncorrected = TRUE
)
stopifnot(isTRUE(all.equal(
  pair_result[, c("log2FC", "pval", "n_pairs")],
  reordered_result[, c("log2FC", "pval", "n_pairs")]
)))
missing_pair_id_error <- tryCatch(
  {
    .paired_sample_columns(pair_meta[, c("sample", "condition")], "before", "after")
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("pair_id", missing_pair_id_error, fixed = TRUE))
pca_meta <- data.frame(
  sample = c("s1", "s2", "s3"),
  condition = c("A", "A", "B")
)
pca_missing <- data.frame(
  s1 = c(0, 7, NA),
  s2 = c(1, NA, 8),
  s3 = c(2, 9, 10)
)
pca_missingness_error <- tryCatch(
  {
    pca_plot(pca_missing, pca_meta)
    ""
  },
  error = function(error) conditionMessage(error)
)
stopifnot(grepl("missingness is too high", pca_missingness_error, fixed = TRUE))
stopifnot(grepl("Impute the data", pca_missingness_error, fixed = TRUE))

rng_meta <- data.frame(
  sample = c("s1", "s2"),
  condition = c("A", "A")
)
rng_frame <- data.frame(
  s1 = c(10, NA, 12, NA),
  s2 = c(11, 12, NA, 14)
)
imputed_seed_1 <- impute_values(rng_frame, rng_meta, seed = 123)
imputed_seed_1_repeat <- impute_values(rng_frame, rng_meta, seed = 123)
imputed_seed_2 <- impute_values(rng_frame, rng_meta, seed = 124)
stopifnot(identical(imputed_seed_1, imputed_seed_1_repeat))
stopifnot(!identical(imputed_seed_1, imputed_seed_2))

set.seed(20260805)
expected_rng_after <- runif(8)
set.seed(20260805)
invisible(impute_values(rng_frame, rng_meta, seed = 17))
observed_rng_after <- runif(8)
stopifnot(identical(observed_rng_after, expected_rng_after))
invisible(parse(file = example_path))


# A decimal comma turns every value in a sample into NA. The sample then reads as
# fully undetected, survives the completeness filter on the other replicates, and
# the analysis runs one replicate short with no sign anything went wrong.
comma_meta <- data.frame(
  sample = c("s1", "s2", "s3", "s4"),
  condition = c("a", "a", "b", "b"),
  stringsAsFactors = FALSE
)
set.seed(11)
comma_clean <- as.data.frame(matrix(rnorm(40 * 4, 20, 2), ncol = 4))
names(comma_clean) <- comma_meta$sample
comma_clean <- cbind(ProteinNames = paste0("P", seq_len(40)), comma_clean,
                     stringsAsFactors = FALSE)
stopifnot(nrow(filter_data(comma_clean, comma_meta, 2)) > 0)

comma_dirty <- comma_clean
comma_dirty$s2 <- sub(".", ",", as.character(round(comma_dirty$s2, 3)), fixed = TRUE)
comma_result <- try(filter_data(comma_dirty, comma_meta, 2), silent = TRUE)
stopifnot(inherits(comma_result, "try-error"))
stopifnot(grepl("do not parse as numbers", attr(comma_result, "condition")$message))
stopifnot(grepl("s2", attr(comma_result, "condition")$message))

# Blanks and documented placeholders really are missing, not unreadable.
comma_placeholder <- comma_clean
comma_placeholder$s2 <- as.character(comma_placeholder$s2)
comma_placeholder$s2[1:8] <- "NA"
comma_placeholder$s2[9:16] <- "Filtered"
stopifnot(nrow(filter_data(comma_placeholder, comma_meta, 2)) > 0)

# Only a column losing most of its values is a mangled export.
comma_label <- comma_clean
comma_label$s2 <- as.character(comma_label$s2)
comma_label$s2[1:2] <- "not detected"
stopifnot(nrow(filter_data(comma_label, comma_meta, 2)) > 0)


# The sum and mean modes aggregate original-scale intensities, so without a
# transform their fold changes are differences of raw intensities -- in the
# thousands -- under a column headed log2FC. Every mode must return log2.
scale_meta <- data.frame(
  sample = c(paste0("Ctrl_", 1:3), paste0("Treat_", 1:3)),
  condition = rep(c("Ctrl", "Treat"), each = 3),
  stringsAsFactors = FALSE
)
set.seed(3)
scale_rows <- list()
for (p_i in seq_len(40)) {
  base <- rlnorm(1, 11, 1)
  effect <- rnorm(1, 0, 1)
  for (s_i in seq_len(3)) {
    vals <- c(base * rlnorm(3, 0, 0.25), base * (2 ^ effect) * rlnorm(3, 0, 0.25))
    entry <- data.frame(
      UPD_seq = paste0("SEQ", p_i, "_", s_i),
      PTM_localization = "0.99",
      Protein_group = paste0("PROT", p_i),
      Gene_group = paste0("G", p_i),
      PTM_Collapse_key = paste0("K", p_i, "_", s_i),
      stringsAsFactors = FALSE
    )
    for (k in seq_along(scale_meta$sample)) entry[[scale_meta$sample[k]]] <- vals[k]
    scale_rows[[length(scale_rows) + 1L]] <- entry
  }
}
scale_data <- do.call(rbind, scale_rows)

for (scale_mode in c("robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na")) {
  aggregated <- suppressWarnings(
    transform_phosprot(scale_data, scale_meta, mode = scale_mode, data_scale = "linear")
  )
  observed <- as.matrix(aggregated[scale_meta$sample])
  observed <- observed[is.finite(observed)]
  stopifnot(length(observed) > 0)
  stopifnot(max(observed) < 60)
}

cat("R notebook helper smoke tests passed\n")
