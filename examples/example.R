.script_path <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg)) return(normalizePath(sub("^--file=", "", file_arg[1]), mustWork = FALSE))
  source_file <- tryCatch(sys.frame(1)$ofile, error = function(e) NULL)
  if (!is.null(source_file)) return(normalizePath(source_file, mustWork = FALSE))
  normalizePath("examples/example.R", mustWork = FALSE)
}

.parent_paths <- function(path) {
  path <- normalizePath(path, mustWork = FALSE)
  paths <- character()
  repeat {
    paths <- c(paths, path)
    parent <- dirname(path)
    if (identical(parent, path)) break
    path <- parent
  }
  paths
}

.find_functions_path <- function() {
  explicit_file <- Sys.getenv("PROTEOMICS_COPYLOT_FUNCTIONS", unset = "")
  if (nzchar(explicit_file) && file.exists(explicit_file)) return(normalizePath(explicit_file))

  explicit_root <- Sys.getenv("PROTEOMICS_COPYLOT_ROOT", unset = "")
  start_paths <- unique(c(
    if (nzchar(explicit_root)) explicit_root else character(),
    dirname(.script_path()),
    getwd()
  ))
  roots <- unique(unlist(lapply(start_paths, .parent_paths), use.names = FALSE))
  candidates <- unique(c(
    file.path(roots, "proteomicscopylot", "notebook_functions.R"),
    file.path(roots, "notebook_functions.R")
  ))
  found <- candidates[file.exists(candidates)]
  if (length(found)) return(normalizePath(found[1]))

  stop(
    "Could not find notebook_functions.R. Set PROTEOMICS_COPYLOT_ROOT to the ProteomicsCoPYlot project directory ",
    "or PROTEOMICS_COPYLOT_FUNCTIONS to the full notebook_functions.R path.",
    call. = FALSE
  )
}

functions_path <- .find_functions_path()
project_root <- dirname(dirname(functions_path))
source(functions_path)
cat("Functions source:", functions_path, "\n")

data_root <- file.path(project_root, "proteomicscopylot", "example_data")
data_paths <- c(
  data = file.path(data_root, "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv"),
  data3 = file.path(data_root, "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv"),
  data4 = file.path(data_root, "phosprot_filtered_data_full.csv"),
  meta = file.path(data_root, "protein_metadata_full.csv"),
  meta2 = file.path(data_root, "phospho_metadata_full.csv")
)

missing_files <- data_paths[!file.exists(data_paths)]
if (length(missing_files)) stop("Missing example data files: ", paste(missing_files, collapse = ", "), call. = FALSE)
cat("Data source:", data_root, "\n")

data <- read_data(data_paths[["data"]])
data3 <- read_data(data_paths[["data3"]])
data4 <- read_data(data_paths[["data4"]])
meta <- read_data(data_paths[["meta"]])
meta2 <- read_data(data_paths[["meta2"]])

org_data <- inverse_log2_transform_data(data, meta)
org_data3 <- inverse_log2_transform_data(data3, meta2)
org_data4 <- inverse_log2_transform_data(data4, meta2)

conditions <- c("WT", "GRK")

data_by_protein <- data
rownames(data_by_protein) <- data_by_protein$ProteinNames
data3_by_site <- data3
rownames(data3_by_site) <- data3_by_site$PTM_Collapse_key
data4_by_phosprot <- data4
rownames(data4_by_phosprot) <- data4_by_phosprot$Phosphoprotein

protein_id <- as.character(na.omit(data$ProteinNames)[1])
phosphosite_id <- as.character(na.omit(data3$PTM_Collapse_key)[1])
phospho_protein_id <- as.character(na.omit(data3$Protein_group)[1])
phosphoprotein_id <- as.character(na.omit(data4$Phosphoprotein)[1])

cat("Protein example:", protein_id, "\n")
cat("Phosphosite example:", phosphosite_id, "\n")
cat("Phospho protein example:", phospho_protein_id, "\n")

# Protein

# Completeness
fig <- missing_value_plot(data, meta, data_scale = "log2")
fig <- missing_value_heatmap(data, meta, id = FALSE, data_scale = "log2")
print(missing_protein_table(data, meta, id = FALSE, data_scale = "log2"))
print(missing_sample_table(data, meta, id = FALSE, data_scale = "log2"))

# QC Pipeline
fig <- coverage_plot(data, meta, id = FALSE, data_scale = "log2")
fig <- coverage_plot_summary(data, meta, data_scale = "log2")
fig <- histo_int(data, meta)
fig <- boxplot_int(data, meta)
fig <- cov_plot(org_data, meta, data_scale = "linear")
fig <- pca_plot(data, meta)
fig <- abundance_plot(org_data, meta, workflow = "Protein", data_scale = "linear")
fig <- corr_plot(org_data, meta, id = FALSE, data_scale = "linear")

# Volcano Plot
volcano_data <- volcano_data_f(data, meta, "WT", "GRK", workflow = "Protein")
print(head(volcano_data))
fig <- volcano_plot(volcano_data, "WT", "GRK")
print(fig)

# Single Protein
fig <- boxplot_int_single_prot(data_by_protein, meta, protein_id, dots = TRUE)
fig <- compare_prot_line(data, meta, conditions, c(protein_id), workflow = "Protein", id = FALSE)

# Comparison
fig <- correlation_xy_intensity(data, meta, "WT", "GRK")
fig <- overlap_plot_condition(data_by_protein, meta, "WT", "GRK", data_scale = "log2")

# Phospho

# Phospho-Specific
fig <- simple_phos_site_plot(data3)
fig <- phossite_coverage_plot(data3, meta2, id = FALSE)
fig <- sty_plot(data3)
fig <- phossite_dist(data4, cutoff = 0.01)

# Completeness
fig <- missing_value_plot(data3, meta2, data_scale = "log2")
fig <- missing_value_heatmap(data3, meta2, id = FALSE, data_scale = "log2")
print(missing_protein_table(data3, meta2, id = FALSE, data_scale = "log2"))
print(missing_sample_table(data3, meta2, id = FALSE, data_scale = "log2"))

# QC Pipeline
fig <- coverage_plot(data3, meta2, id = FALSE, data_scale = "log2")
fig <- coverage_plot_summary(data3, meta2, data_scale = "log2")
fig <- histo_int(data3, meta2)
fig <- boxplot_int(data3, meta2)
fig <- cov_plot(org_data3, meta2, data_scale = "linear")
fig <- pca_plot(data3, meta2)
fig <- abundance_plot(org_data3, meta2, workflow = "Phosphosite", data_scale = "linear")
fig <- corr_plot(org_data3, meta2, id = FALSE, data_scale = "linear")

# Volcano Plot
volcano_data <- volcano_data_f(data3, meta2, "WT", "GRK", workflow = "Phosphosite")
print(head(volcano_data))
fig <- volcano_plot(volcano_data, "WT", "GRK")
print(fig)

# Single Protein
fig <- boxplot_int_single_prot(data3_by_site, meta2, phosphosite_id, dots = TRUE)
fig <- compare_prot_line(data3, meta2, conditions, c(phosphosite_id), workflow = "Phosphosite", id = FALSE)
fig <- phossite_on_prot_regulation(data3, meta2, phospho_protein_id, conditions = conditions, id = FALSE)

# Comparison
fig <- correlation_xy_intensity(data3, meta2, "WT", "GRK")
fig <- overlap_plot_condition(data3_by_site, meta2, "WT", "GRK", data_scale = "log2")

# Phosphoprotein

# Completeness
fig <- missing_value_plot(data4, meta2, data_scale = "log2")
fig <- missing_value_heatmap(data4, meta2, id = FALSE, data_scale = "log2")
print(missing_protein_table(data4, meta2, id = FALSE, data_scale = "log2"))
print(missing_sample_table(data4, meta2, id = FALSE, data_scale = "log2"))

# QC Pipeline
fig <- coverage_plot(data4, meta2, id = FALSE, data_scale = "log2")
fig <- coverage_plot_summary(data4, meta2, data_scale = "log2")
fig <- histo_int(data4, meta2)
fig <- boxplot_int(data4, meta2)
fig <- cov_plot(org_data4, meta2, data_scale = "linear")
fig <- pca_plot(data4, meta2)
fig <- abundance_plot(org_data4, meta2, workflow = "Phosphoprotein", data_scale = "linear")
fig <- corr_plot(org_data4, meta2, id = FALSE, data_scale = "linear")

# Volcano Plot
volcano_data <- volcano_data_f(data4, meta2, "WT", "GRK", workflow = "Phosphoprotein")
print(head(volcano_data))
fig <- volcano_plot(volcano_data, "WT", "GRK")
print(fig)

# Single Protein
fig <- boxplot_int_single_prot(data4_by_phosprot, meta2, phosphoprotein_id, dots = TRUE)
fig <- compare_prot_line(data4, meta2, conditions, c(phosphoprotein_id), workflow = "Phosphoprotein", id = FALSE)

# Comparison
fig <- correlation_xy_intensity(data4, meta2, "WT", "GRK")
fig <- overlap_plot_condition(data4_by_phosprot, meta2, "WT", "GRK", data_scale = "log2")
