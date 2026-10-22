# Converted from a single stopifnot script on 2026-10-02 so one failure no
# longer stops the rest. The runner (tests/r/test_notebook_functions.R) sources
# notebook_functions.R into the global environment first, so its functions,
# `repo_root`, `functions_path` and `example_path` are visible here.

test_that("the package sources from its own folder and exposes the documented API", {
  expect_no_error({
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
  })
})

test_that("CV refuses log2 input and asks for linear intensities", {
  expect_no_error({
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
  })
})

test_that("sample IDs are read the same way as in Python", {
  expect_no_error({
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
  })
})

test_that("the GO database loads from any working directory and ORA takes a background", {
  expect_no_error({
    original_working_directory <- getwd()
    setwd(tempdir())
    go_db <- load_go_db()
    setwd(original_working_directory)
    stopifnot(all(c("ontology", "term", "description", "genes") %in% names(go_db)))
    stopifnot(all(c("background", "background_mode", "workflow") %in% names(formals(enrichment_analysis))))
  })
})

test_that("ORA refuses to run without a tested-gene background", {
  expect_no_error({
    ora_missing_background_error <- tryCatch(
      {
        enrichment_analysis("TP53", min_num = 1, max_num = 10000)
        ""
      },
      error = function(error) conditionMessage(error)
    )
    stopifnot(grepl("tested-gene background", ora_missing_background_error, fixed = TRUE))
  })
})

test_that("ANOVA clustering handles empty, all-row and single-row results", {
  expect_no_error({
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
  })
})

test_that("ANOVA clustering keeps a singleton cluster", {
  expect_no_error({
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
  })
})

test_that("pathway gene values aggregate by gene and ignore row order", {
  expect_no_error({
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
  })
})

test_that("phosphoprotein genes, ANOVA and regulation summaries", {
  expect_no_error({
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
      identical(phosprot_genes$Upregulated, c("B", "C")),
      identical(phosprot_genes$Downregulated, c("A", "B")),
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
      identical(fallback_genes$Upregulated, c("B", "C")),
      identical(fallback_genes$Downregulated, c("A", "B")),
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
        .different_gene_tokens(phosprot_anova$Gene_group),
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
      identical(regulation_summary$Upregulated_count, 1L),
      identical(regulation_summary$Downregulated_count, 2L),
      isTRUE(all.equal(regulation_summary$x, 3)),
      isTRUE(all.equal(regulation_summary$y, 3.5))
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
      isTRUE(all.equal(stricter_regulation$x, 3)),
      isTRUE(all.equal(stricter_regulation$y, 2))
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
  })
})

test_that("filter modes keep the expected rows", {
  expect_no_error({
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
    stopifnot(nrow(filter_data(filter_frame, filter_meta, 0, "per_group", "percentage", 70)) == 1)
  })
})

test_that("paired volcano matches samples by pair_id", {
  expect_no_error({
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
    pair_columns <- paired_sample_columns(pair_meta, "before", "after")
    stopifnot(identical(pair_columns$condition1, c("before_c", "before_a", "before_d", "before_b")))
    stopifnot(identical(pair_columns$condition2, c("after_c", "after_a", "after_d", "after_b")))
    partial_pair_meta <- data.frame(
      sample = c("before_c", "before_a", "before_b", "before_unpaired",
                 "after_b", "after_d", "after_a"),
      condition = c(rep("before", 4), rep("after", 3)),
      pair_id = c("C", "A", "B", "", "B", "D", "A")
    )
    partial_pair_columns <- paired_sample_columns(partial_pair_meta, "before", "after")
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
    stopifnot(isTRUE(all.equal(pair_result$log2FC, c(-5, 0, -2, -1))))
    # Identical pair differences: no variation, so no p-value (not p = 0).
    stopifnot(is.na(pair_result$pval[2]), is.na(pair_result$pval[3]),
      pair_result$significance[3] == "Unavailable")
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
        paired_sample_columns(pair_meta[, c("sample", "condition")], "before", "after")
        ""
      },
      error = function(error) conditionMessage(error)
    )
    stopifnot(grepl("pair_id", missing_pair_id_error, fixed = TRUE))
  })
})

test_that("PCA refuses data with too much missingness", {
  expect_no_error({
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
  })
})

test_that("imputation is reproducible and leaves the global RNG alone", {
  expect_no_error({
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
  })
})

test_that("the published R example parses", {
  expect_no_error({
    invisible(parse(file = example_path))
  })
})

test_that("a decimal comma in a sample column is refused, placeholders are not", {
  expect_no_error({
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
  })
})

test_that("phosphoprotein aggregation modes report log2 fold changes", {
  expect_no_error({
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
  })
})

test_that("protein names with punctuation are matched literally", {
  expect_no_error({
    for (protein in c("P", "P.1", "P+1")) {
      for (shared in c(FALSE, TRUE)) {
        coverage_data <- data.frame(
          ProteinNames = c(
            protein, paste0(protein, "-2"), paste0(protein, "X"), paste0("X", protein),
            if (shared) paste0("OTHER; ", protein, " ") else "OTHER", NA, protein
          ),
          Stripped.Sequence = c("AAA", "CCC", "CCC", "CCC", "CCC", "CCC", NA)
        )
        coverage_db <- data.frame(name = protein, V1 = "AAACCC")
        coverage_path <- tempfile(fileext = ".tsv")
        write.table(coverage_data, coverage_path, sep = "\t", row.names = FALSE, quote = FALSE)
        coverage_value <- tryCatch(
          calculate_coverage(coverage_path, coverage_db, protein),
          finally = unlink(coverage_path)
        )
        stopifnot(coverage_value == if (shared) 100 else 50)
        coverage_text <- vis_coverage(coverage_data, coverage_db, protein)
        stopifnot(grepl(if (shared) "AAACCC\nAAACCC" else "AAA---\nAAACCC", coverage_text, fixed = TRUE))
      }
    }
  })
})

test_that("sequence coverage cases", {
  expect_no_error({
    coverage_cases <- list(
      list("AAAA", "AAA", c(1L, 2L), 100),
      list("AAACAAA", "AAA", c(1L, 5L), 85.71),
      list("CAAAC", "AAA", 2L, 60),
      list("AAAA", "WWW", integer(0), 0),
      list("AAAA", "AAAAA", integer(0), 0)
    )
    for (case in coverage_cases) {
      sequence <- case[[1]]
      peptide <- case[[2]]
      stopifnot(identical(.peptide_starts(sequence, peptide), case[[3]]))
      stopifnot(length(.peptide_starts(sequence, "")) == 0)
      coverage_data <- data.frame(ProteinNames = "P", Stripped.Sequence = peptide)
      coverage_db <- data.frame(name = "P", V1 = sequence)
      coverage_path <- tempfile(fileext = ".tsv")
      write.table(coverage_data, coverage_path, sep = "\t", row.names = FALSE, quote = FALSE)
      coverage_value <- tryCatch(
        calculate_coverage(coverage_path, coverage_db, "P"),
        finally = unlink(coverage_path)
      )
      stopifnot(coverage_value == case[[4]])
      lines <- strsplit(vis_coverage(coverage_data, coverage_db, "P"), "\n")[[1]]
      tracks <- lines[2:(length(lines) - 1L)]
      covered <- vapply(seq_len(nchar(sequence)), function(i) {
        any(substring(tracks, i, i) != "-")
      }, logical(1))
      stopifnot(round(mean(covered) * 100, 2) == case[[4]])
      if (identical(case[[3]], c(1L, 2L))) stopifnot(identical(tracks, c("-AAA", "AAA-")))
    }
  })
})

test_that("volcano refuses two identical conditions", {
  expect_no_error({
    for (method in c("unpaired", "unpaired_welch", "paired", "moderated", "moderated_robust_paired")) {
      message <- tryCatch({
        volcano_data_f(data.frame(), data.frame(), "A", "A", test_type = method)
        ""
      }, error = function(e) conditionMessage(e))
      stopifnot(identical(message, "Please select two different conditions."))
    }
  })
})

test_that("moderated tests change only the p-value, and need limma", {
  skip_if_not_installed("limma")
  set.seed(5)
  values <- matrix(rnorm(600, 20, 1), ncol = 6)
  values[1:20, 1:3] <- values[1:20, 1:3] + 1.5
  data <- data.frame(ProteinNames = paste0("P", seq_len(100)), values, check.names = FALSE)
  names(data)[-1] <- c("C1", "C2", "C3", "T1", "T2", "T3")
  meta <- data.frame(sample = names(data)[-1], condition = rep(c("Ctrl", "Treat"), each = 3),
                     pair_id = rep(c("a", "b", "c"), 2), stringsAsFactors = FALSE)
  for (design in list(c("unpaired", "moderated"), c("paired", "moderated_paired"))) {
    plain <- volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = design[1])
    moderated <- volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = design[2])
    expect_equal(plain$log2FC, moderated$log2FC)
    expect_false(isTRUE(all.equal(plain$pval, moderated$pval)))
    expect_true(all(is.finite(moderated$pval)))
  }
  robust <- volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = "moderated_robust")
  expect_false(isTRUE(all.equal(robust$pval, volcano_data_f(data, meta, "Ctrl", "Treat", workflow = "Protein", test_type = "moderated")$pval)))
})

test_that("kinase motif windows match the backend", {
  expect_no_error({
    # Kinase motif windows come from the protein when a FASTA is given, and match
    # the backend and pip package case for case (tests/unit/phospho/test_ksea_motif_windows.py).
    motif_protein <- c(P1 = "MKRRASLDEFGHIKLMNPQRSTVWY", P2 = "MSTY")
    motif_cases <- list(
      list("P1~GENE_S6_M1", "As*LDEFGHIK", "__MKRRASLDEFGHI", "protein"),
      list("P2~G2_S2_M1", "Ms*TY", "______MSTY_____", "protein"),
      list("P9~G9_S6_M1", "As*LDE", "______ASLDE____", "peptide"),
      list("P1~GENE_T6_M1", "At*LDE", "______ATLDE____", "peptide"),
      list("P1~GENE_S6_M1", "Xs*LDE", "______XSLDE____", "peptide"),
      list("P9;P1~GENE_S6_M2", "As*LDE", "__MKRRASLDEFGHI", "protein"),
      list("site-0", "As*LDE", "______ASLDE____", "peptide")
    )
    for (case in motif_cases) {
      window <- site_motif_window(case[[1]], case[[2]], motif_protein)
      stopifnot(identical(window$UPD_seq, case[[3]]), identical(window$window_source, case[[4]]))
    }
    stopifnot(identical(site_motif_window("P9;P1~GENE_S6_M2", "As*LDE", motif_protein)$Site, "S6"))
    motif_fasta <- tempfile(fileext = ".fasta")
    writeLines(c(">sp|P1|ONE_HUMAN test", "MKRRASLDEF", "GHIKLMNPQRSTVWY", ">tr|P2|TWO", "MSTY"), motif_fasta)
    stopifnot(identical(read_fasta(motif_fasta), motif_protein))
    unlink(motif_fasta)
  })
})

test_that("imputed-value counts match the backend", {
  expect_no_error({
    # Imputed-value counts: same cases as tests/unit/data/test_imputed_value_counts.py.
    imp_samples <- c("a1", "a2", "a3", "b1", "b2", "b3")
    imp_observed <- data.frame(
      a1 = c(1, NA, 1), a2 = c(NA, NA, 1.1), a3 = c(1.2, 1, 0.9),
      b1 = c(2, 1, 1), b2 = c(2.1, 1.1, 1.1), b3 = c(NA, 0.9, 0.9)
    )
    imp_data <- imp_observed
    imp_data[is.na(imp_data)] <- -3
    imp_data <- cbind(ProteinNames = c("P1", "P2", "P3"), imp_data)
    imp_meta <- data.frame(sample = imp_samples, condition = rep(c("A", "B"), each = 3))
    imp_plain <- volcano_data_f(imp_data, imp_meta, "A", "B", in_log2fc = 0)
    stopifnot(!"imputed_values" %in% names(imp_plain))
    imp_counted <- volcano_data_f(imp_data, imp_meta, "A", "B", in_log2fc = 0, observed = imp_observed)
    stopifnot(identical(imp_counted$n_imputed__A, c(1L, 2L, 0L)))
    stopifnot(identical(imp_counted$n_imputed__B, c(1L, 0L, 0L)))
    stopifnot(identical(imp_counted$imputed_values, c(2L, 2L, 0L)))
    stopifnot(isTRUE(all.equal(imp_counted$pval, imp_plain$pval)))
    imp_anova <- anova_data_f(imp_data, imp_meta, observed = imp_observed)
    stopifnot(identical(imp_anova$imputed_values[match(c("P1", "P2", "P3"), imp_anova$ProteinNames)], c(2L, 2L, 0L)))
  })
})

test_that("phosphoprotein contributions distinguish measured, full, partial and unknown", {
  expect_no_error({
    imp_phosprot <- data.frame(s1 = c(1, 2, NA), s2 = c(1, 2, 3),
      site_observed__s1 = c(0, 2, 0), site_observed__s2 = c(1, 0, 1),
      site_supplied__s1 = c(2, 2, 0), site_supplied__s2 = c(2, 2, 1), check.names = FALSE)
    stopifnot(identical(unname(site_observed_imputed_mask(imp_phosprot, c("s1", "s2"))),
      matrix(c(1L, 0L, -1L, 2L, 1L, 0L), ncol = 2)))
    stopifnot(is.null(site_observed_imputed_mask(imp_phosprot[, 1:4], c("s1", "s2"))))
  })
})

test_that("localization probability cutoff", {
  expect_no_error({
    # Localization probability cutoff: same cases as tests/unit/phospho/test_phospho_localization_cutoff.py.
    loc_sites <- data.frame(PTM_Collapse_key = c("a", "b", "c", "d", "e", "f"),
      PTM_localization = c("0.99", "0.75", "0.74", NA, "bad", "1.5"), s1 = 1:6, stringsAsFactors = FALSE)
    for (case in list(list(0, c("a", "b", "c", "d", "e", "f")), list(0.75, c("a", "b")),
                      list(0.99, "a"), list(1, character(0)))) {
      stopifnot(identical(filter_localization(loc_sites, case[[1]])$PTM_Collapse_key, case[[2]]))
    }
    stopifnot(inherits(tryCatch(filter_localization(loc_sites, 1.2), error = function(e) e), "error"))
    stopifnot(inherits(tryCatch(filter_localization(loc_sites[, -2], 0.5), error = function(e) e), "error"))
    stopifnot(nrow(filter_localization(loc_sites[, -2], 0)) == 6L)
  })
})

test_that("transform_phosprot keeps Spectronaut-style sample names", {
  expect_no_error({
    # transform_phosprot keeps sample names that start with a digit or contain "-"
    # (Spectronaut/DIA-NN style); as.data.frame used to rewrite them.
    real_names <- c("20240822_A-1", "20240822_A-2", "20240822_B-1", "20240822_B-2")
    real_sites <- data.frame(UPD_seq = c("As*K", "Bs*K", "Cs*K"), PTM_localization = c(1, 1, 1),
      Protein_group = c("P1", "P1", "P2"), Gene_group = c("G1", "G1", "G2"),
      PTM_Collapse_key = c("P1~G1_S1_M1", "P1~G1_S2_M1", "P2~G2_S1_M1"), stringsAsFactors = FALSE)
    for (i in seq_along(real_names)) real_sites[[real_names[i]]] <- c(10, 11, 12) + i
    real_meta <- data.frame(sample = real_names, condition = c("A", "A", "B", "B"))
    real_out <- transform_phosprot(real_sites, real_meta, mode = "mean", data_scale = "log2", coverage_data = real_sites)
    stopifnot(all(real_names %in% names(real_out)), nrow(real_out) == 2L)
  })
})
