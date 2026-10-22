# Deterministic reference workflow. Imputed inputs are supplied, never drawn here.
args <- commandArgs(trailingOnly = TRUE)
directory <- args[1]
method <- args[2]
source(file.path(args[3], "proteomicscopylot", "notebook_functions.R"))
options(digits = 17)
meta <- read.csv(file.path(directory, "meta.csv"), check.names = FALSE)
write_result <- function(name, frame) {
  # Record a stage failure without losing the remaining independent comparisons.
  # Python treats every error file as a failed assertion, never as a skip.
  tryCatch({
    write.csv(frame, file.path(directory, paste0("r_", name, ".csv")), row.names = FALSE, na = "NA")
  }, error = function(error) {
    writeLines(conditionMessage(error), file.path(directory, paste0("r_", name, ".error.txt")))
  })
}
for (kind in c("protein", "phospho")) {
  raw <- read.csv(file.path(directory, paste0(kind, ".csv")), check.names = FALSE)
  logged <- log2_transform_data(raw, meta)
  kept <- filter_data(logged, meta, 3, "per_group", "at_least_n", 70)
  normalized <- normalize_data(logged, as.character(meta$sample), method, fit_rows = rownames(kept))
  filtered <- normalized[rownames(kept), , drop = FALSE]
  write_result(paste0(kind, "_normalized"), normalized)
  write_result(paste0(kind, "_filtered"), filtered)
  for (input in c("observed", "fixed")) {
    frame <- if (input == "observed") filtered else read.csv(file.path(directory, paste0(kind, "_fixed.csv")), check.names = FALSE)
    workflow <- if (kind == "protein") "Protein" else "Phosphosite"
    for (test_type in c("unpaired", "unpaired_welch", "paired")) {
      write_result(paste(kind, input, test_type, sep = "_"), volcano_data_f(
        frame, meta, "A", "B", workflow = workflow, test_type = test_type))
      write_result(paste(kind, input, test_type, "control", sep = "_"), volcano_data_f_control(
        frame, meta, "A", "B", "C", "D", workflow = workflow, test_type = test_type))
    }
    if (kind == "phospho") {
      for (mode in c("robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na")) {
        collapsed <- transform_phosprot(frame, meta, mode = mode, data_scale = "log2", coverage_data = filtered)
        write_result(paste("aggregate", input, mode, sep = "_"), collapsed)
        collapsed_filtered <- filter_data(collapsed, meta, 3, "per_group", "at_least_n", 70)
        write_result(paste("aggregate_filtered", input, mode, sep = "_"), collapsed_filtered)
        write_result(paste("aggregate_stats", input, mode, sep = "_"), volcano_data_f(
          collapsed_filtered, meta, "A", "B", workflow = "Phosphoprotein", test_type = "unpaired_welch"))
      }
    }
  }
  empty <- filter_data(normalized, meta, 5, "per_group", "at_least_n", 70)
  write_result(paste0(kind, "_empty"), empty)
}
