# The directory this file was sourced from, for the bundled GO table. source()
# records the path as `ofile` in its own frame; searching every frame, innermost
# first, also finds it when source() is called from inside another function.
.copylot_source_file <- tryCatch({
  sourced <- Filter(function(path) is.character(path) && length(path) == 1L && nzchar(path),
    lapply(rev(sys.frames()), function(frame) frame$ofile))
  if (length(sourced)) sourced[[1]] else ""
}, error = function(e) "")
.copylot_source_dir <- if (is.null(.copylot_source_file) || !nzchar(.copylot_source_file)) {
  ""
} else {
  dirname(normalizePath(.copylot_source_file, mustWork = FALSE))
}
rm(.copylot_source_file)

.require_pkg <- function(package) {
  if (!requireNamespace(package, quietly = TRUE)) {
    stop(
      "Package '", package, "' is required for this function. Install it with ",
      "install.packages('", package, "').",
      call. = FALSE
    )
  }
}

.with_local_seed <- function(seed, callback) {
  seed <- suppressWarnings(as.integer(seed))
  if (length(seed) != 1L || is.na(seed) || seed < 0L) {
    stop("Random seed must be one non-negative integer.", call. = FALSE)
  }

  old_kind <- RNGkind()
  had_seed <- exists(".Random.seed", envir = .GlobalEnv, inherits = FALSE)
  if (had_seed) old_seed <- get(".Random.seed", envir = .GlobalEnv, inherits = FALSE)
  on.exit({
    do.call(RNGkind, as.list(old_kind))
    if (had_seed) {
      assign(".Random.seed", old_seed, envir = .GlobalEnv)
    } else if (exists(".Random.seed", envir = .GlobalEnv, inherits = FALSE)) {
      rm(".Random.seed", envir = .GlobalEnv)
    }
  }, add = TRUE)

  set.seed(seed)
  callback()
}

.plot_result <- function() {
  tryCatch(recordPlot(), error = function(e) invisible(NULL))
}

.tab10 <- c(
  "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
  "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
)

.plot_colors <- function(n, plot_colors = NULL) {
  if (n < 1) return(character())

  colors <- plot_colors %||% .tab10
  rep(colors, length.out = n)
}

.set_notebook_plot_size <- function(width, height, units = "cm") {
  if (units == "cm") {
    width <- width / 2.54
    height <- height / 2.54
  }

  options(
    repr.plot.width = width,
    repr.plot.height = height
  )
}

.set_plot_margins <- function(legend = FALSE, rotated_labels = FALSE) {
  bottom <- if (rotated_labels) 8 else 4.1
  right <- if (legend) 8 else 2.1

  old_par <- par(
    mar = c(bottom, 4.5, 3.2, right),
    xpd = NA
  )
  invisible(old_par)
}

.restore_layout <- function(old_par) {
  layout(1)
  par(
    mar = old_par$mar,
    oma = old_par$oma,
    xpd = old_par$xpd
  )
}

.variance_and_count <- function(values) {
  # Per-row variance and observed count for one independent group.
  list(
    variance = apply(values, 1, stats::var, na.rm = TRUE),
    count = rowSums(!is.na(values))
  )
}

.numeric_matrix <- function(data, columns) {
  m <- as.matrix(data[, columns, drop = FALSE])
  storage.mode(m) <- "numeric"
  m
}

.drop_incomplete_features <- function(matrix, context = "heatmap", minimum_rows = 1) {
  # Hierarchical clustering is undefined for a feature missing in any sample.
  # Refusing the whole matrix over a handful of them denies the plot entirely;
  # dropping them silently hides that the figure rests on a subset. Drop them
  # and let .warn_dropped_features state the cost.
  matrix <- as.matrix(matrix)
  storage.mode(matrix) <- "numeric"
  rows <- nrow(matrix)
  columns <- ncol(matrix)
  complete <- rowSums(is.finite(matrix)) == columns
  kept <- sum(complete)
  if (kept < max(1L, as.integer(minimum_rows))) {
    stop(
      paste0(
        tools::toTitleCase(context),
        " cannot be computed because only ", kept, " of ", rows,
        " features are observed in all ", columns,
        " samples. Impute the matrix before calling this function. ",
        "The data was not changed automatically."
      ),
      call. = FALSE
    )
  }
  list(
    matrix = matrix[complete, , drop = FALSE],
    kept = complete,
    dropped = rows - kept,
    total = rows
  )
}

.dropped_features_message <- function(dropped, total, purpose = "clustering",
                                      noun = "features") {
  # The same sentence the web app shows beneath the plot.
  if (!length(dropped) || dropped <= 0 || !total) return(NULL)
  percent <- dropped / total * 100
  text <- if (percent < 0.1) {
    "<0.1%"
  } else if (percent < 10) {
    sprintf("%.1f%%", percent)
  } else {
    sprintf("%.0f%%", percent)
  }
  paste0(
    text, " of ", noun, " dropped for ", purpose,
    " (", format(dropped, big.mark = ","), " of ", format(total, big.mark = ","), ")",
    " \u2014 not observed in every sample"
  )
}

.warn_dropped_features <- function(dropped, total, purpose = "clustering") {
  # Report the drop where a notebook user sees it: under the cell.
  message_text <- .dropped_features_message(dropped, total, purpose = purpose)
  if (!is.null(message_text)) warning(message_text, call. = FALSE)
}

raw_zero_to_nan <- function(data, sample_columns) {
  # Read 0 (and +/-Inf) in raw, linear intensities as not measured. Only the
  # named sample columns change; annotation columns and values on a log2 scale,
  # where 0 is a real measurement, are left alone. Same name and rule in the app
  # and the pip package.
  output <- data
  for (column in intersect(as.character(sample_columns), names(output))) {
    values <- suppressWarnings(as.numeric(output[[column]]))
    values[!is.finite(values) | values == 0] <- NA_real_
    output[[column]] <- values
  }
  output
}

.prepare_intensity_data <- function(data, sample_columns, data_scale = "log2") {
  # Shared public missingness contract: transformed zero is observed (linear
  # abundance 1), whereas linear/raw zero is a non-detection. Annotation
  # sample_columns are copied without coercion.
  data_scale <- tolower(trimws(as.character(data_scale)))
  if (length(data_scale) != 1L || !data_scale %in% c("log2", "linear")) {
    stop("data_scale must be 'log2' or 'linear'.", call. = FALSE)
  }

  output <- data
  for (column in intersect(as.character(sample_columns), names(output))) {
    values <- suppressWarnings(as.numeric(output[[column]]))
    values[!is.finite(values)] <- NA_real_
    if (data_scale == "linear") values[values == 0] <- NA_real_
    output[[column]] <- values
  }
  output
}

.sample_meta <- function(meta, id = TRUE, newline = FALSE, zero_based = FALSE) {
  meta <- as.data.frame(meta, stringsAsFactors = FALSE)
  meta$sample <- as.character(meta$sample)
  meta$condition <- as.character(meta$condition)
  meta$id <- vapply(meta$sample, extract_id_or_number, character(1))
  n <- ave(seq_len(nrow(meta)), meta$condition, FUN = seq_along) - as.integer(zero_based)
  suffix <- if (id) paste0(if (newline) "\n" else " ", "(", meta$id, ")") else ""
  meta$new_sample <- paste0(meta$condition, "_", n, suffix)
  meta
}

.rename_samples <- function(data, meta) {
  names(data)[match(meta$sample, names(data), nomatch = 0L)] <- meta$new_sample[meta$sample %in% names(data)]
  data
}

.workflow_col <- function(workflow) {
  switch(workflow, Protein = "ProteinNames", Phosphosite = "PTM_Collapse_key",
         Phosphoprotein = "Phosphoprotein", stop("workflow must be 'Protein', 'Phosphosite', or 'Phosphoprotein'", call. = FALSE))
}

row_zscore <- function(matrix) {
  # Same convention as backend row_zscore(): sample sd (n - 1); rows with zero
  # or undefined sd map to 0.
  means <- rowMeans(matrix, na.rm = TRUE)
  sds <- apply(matrix, 1, sd, na.rm = TRUE)
  sds[!is.finite(sds) | sds == 0] <- 1
  sweep(sweep(matrix, 1, means, "-"), 1, sds, "/")
}

.plot_heatmap <- function(
    m,
    title = "",
    xlab = "Sample",
    ylab = "",
    labels = TRUE,
    zlim = NULL,
    color_label = "Value",
    palette = NULL
) {
  if (!nrow(m) || !ncol(m)) {
    stop("No data available for heatmap.", call. = FALSE)
  }

  z <- m[nrow(m):1, , drop = FALSE]
  finite_values <- z[is.finite(z)]

  if (is.null(zlim)) {
    zlim <- range(finite_values, na.rm = TRUE)
  }
  if (!all(is.finite(zlim)) || diff(zlim) == 0) {
    zlim <- c(0, 1)
  }
  # Clip to the colour limits, as matplotlib's vmin/vmax does; graphics::image()
  # refuses finite values outside zlim.
  z[is.finite(z)] <- pmax(pmin(z[is.finite(z)], zlim[2]), zlim[1])

  colors <- palette %||% colorRampPalette(c("#313695", "white", "#a50026"))(100)
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)

  layout(matrix(c(1, 2), nrow = 1), widths = c(16, 2))
  par(mar = c(8, if (labels) 8 else 4.5, 3.2, 1))

  graphics::image(
    x = seq_len(ncol(z)),
    y = seq_len(nrow(z)),
    z = t(z),
    col = colors,
    axes = FALSE,
    zlim = zlim,
    xlab = xlab,
    ylab = ylab,
    main = title
  )
  graphics::axis(
    1,
    at = seq_len(ncol(z)),
    labels = colnames(z),
    las = 2,
    cex.axis = 0.65
  )
  if (labels) {
    graphics::axis(
      2,
      at = seq_len(nrow(z)),
      labels = rev(rownames(z)),
      las = 2,
      cex.axis = 0.55
    )
  }
  box()

  par(mar = c(8, 0.2, 3.2, 2))
  color_values <- seq(zlim[1], zlim[2], length.out = length(colors))
  graphics::image(
    x = 1,
    y = color_values,
    z = matrix(color_values, nrow = 1),
    col = colors,
    axes = FALSE,
    xlab = "",
    ylab = ""
  )
  graphics::axis(4, las = 2, cex.axis = 0.7)
  graphics::mtext(color_label, side = 4, line = 1.2, cex = 0.8)

  .plot_result()
}

.pivot_wide <- function(data, row_col, column_col, value_col, fun = max) {
  d <- data[, c(row_col, column_col, value_col), drop = FALSE]
  d[[value_col]] <- suppressWarnings(as.numeric(d[[value_col]]))
  a <- aggregate(d[[value_col]], d[c(row_col, column_col)], function(x) if (all(is.na(x))) NA_real_ else fun(x, na.rm = TRUE))
  rows <- unique(as.character(a[[row_col]]))
  cols <- unique(as.character(a[[column_col]]))
  out <- matrix(NA_real_, length(rows), length(cols), dimnames = list(rows, cols))
  out[cbind(match(a[[row_col]], rows), match(a[[column_col]], cols))] <- a$x
  as.data.frame(out, check.names = FALSE)
}

# BASIC AND DATA
bool_to_str <- function(value) {
  if (isTRUE(value)) "TRUE" else if (identical(value, FALSE)) "FALSE" else ""
}

format_value <- function(val) {
  if (is.factor(val) && length(val) == 1) as.character(val) else if (is.logical(val) || is.null(val)) bool_to_str(val) else if (is.numeric(val)) number_to_str(val) else as.character(val)
}

extract_number <- function(s) {
  match <- regexpr("[0-9]+", as.character(s))
  if (match[1] < 0) {
    return(-1L)
  }

  as.integer(regmatches(as.character(s), match)[1])
}

number_to_str <- function(value) {
  # Render a number the same way in every pipeline. Both packages used to
  # delegate to the language's own conversion, and those disagree: `as.character`
  # drops a trailing `.0` and switches to scientific notation past a width
  # threshold, Python's `str` does neither, so `1.0` and `1000000.0` came out as
  # different text from the two products. The contract is now explicit -- whole
  # numbers carry no decimal point, and nothing below 1e15 is rendered in
  # scientific notation.
  if (!is.numeric(value) || length(value) != 1L) return("")
  number <- as.numeric(value)
  if (is.nan(number)) return("NaN")
  if (is.na(number)) return("")
  if (is.infinite(number)) return(if (number > 0) "Inf" else "-Inf")
  if (number == trunc(number) && abs(number) < 1e15) {
    return(format(number, scientific = FALSE, trim = TRUE))
  }
  # formatC pads to a fixed width; trim so the text matches Python's %.10g.
  trimws(formatC(number, format = "g", digits = 10))
}

make_columns_unique <- function(df) {
  names(df) <- make.unique(names(df), sep = "_")
  df
}

sanitize_dataframe <- function(df) {
  df <- make_columns_unique(as.data.frame(df, check.names = FALSE))
  for (nm in names(df)) if (!is.numeric(df[[nm]])) df[[nm]] <- as.character(df[[nm]])
  df
}

`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

rename_cols <- function(df) {
  rename_map <- c(Run="File.Name", PG.ProteinNames="ProteinNames", PG.ProteinGroups="ProteinNames",
    Protein.IDs="ProteinNames", PG.Genes="GeneNames", Protein.Names="ProteinNames",
    "Protein IDs"="ProteinNames", Genes="GeneNames", "Gene names"="GeneNames",
    PEP.StrippedSequence="Stripped.Sequence", Sequence="Stripped.Sequence",
    EG.ModifiedSequence="Modified.Sequence", R.FileName="File.Name",
    EG.iRTPredicted="Predicted.RT", EG.iRTEmpirical="RT")
  tq <- grep("^EG\\.TotalQuantity", names(df), value = TRUE)
  if (length(tq)) rename_map[tq[1]] <- "Precursor.Quantity"
  hit <- intersect(names(rename_map), names(df))
  names(df)[match(hit, names(df))] <- unname(rename_map[hit])
  if (all(c("GeneNames", "ProteinNames", "Raw file", "Intensity") %in% names(df))) {
    df$Intensity <- suppressWarnings(as.numeric(df$Intensity))
    df$Intensity[is.na(df$Intensity)] <- 0
    a <- aggregate(Intensity ~ GeneNames + ProteinNames + `Raw file`, df, sum)
    keys <- unique(a[c("GeneNames", "ProteinNames")])
    samples <- unique(a$`Raw file`)
    out <- keys
    for (sample in samples) {
      subset <- a[a$`Raw file` == sample, ]
      keys_subset <- paste(subset$GeneNames, subset$ProteinNames)
      keys_output <- paste(keys$GeneNames, keys$ProteinNames)
      out[[sample]] <- subset$Intensity[match(keys_output, keys_subset)]
    }
    df <- out
  }
  if ("Reverse" %in% names(df)) df <- df[!grepl("\\+", df$Reverse %||% ""), , drop = FALSE]
  if ("Only identified by site" %in% names(df)) df <- df[!grepl("\\+", df[["Only identified by site"]] %||% ""), , drop = FALSE]
  df
}

info <- function() {
  cat("Proteomics CoPYlot is a package/app to streamline the analysis of proteomics data. Have fun!\n")
}

# The bundled HEK293 example (WT vs GRK, five replicates each), by short name.
EXAMPLE_DATA_FILES <- c(
  protein = "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv",
  phospho = "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv",
  phosphoprotein = "phosprot_filtered_data_full.csv",
  protein_metadata = "protein_metadata_full.csv",
  phospho_metadata = "phospho_metadata_full.csv"
)

# Path of a bundled example file: one of the names of EXAMPLE_DATA_FILES. The
# files sit next to this script, in the repository and in the installed package.
example_data_path <- function(name) {
  if (!name %in% names(EXAMPLE_DATA_FILES)) {
    stop("Unknown example '", name, "'; choose one of: ",
      paste(names(EXAMPLE_DATA_FILES), collapse = ", "), ".", call. = FALSE)
  }
  if (!nzchar(.copylot_source_dir)) {
    stop("Source notebook_functions.R from its file to locate the bundled examples.", call. = FALSE)
  }
  path <- file.path(.copylot_source_dir, "example_data", EXAMPLE_DATA_FILES[[name]])
  if (!file.exists(path)) stop("The bundled example file is missing: ", path, call. = FALSE)
  normalizePath(path)
}

# Read a bundled example file with read_data(); see EXAMPLE_DATA_FILES for the names.
load_example_data <- function(name) {
  read_data(example_data_path(name))
}

read_data <- function(file) {
  filename <- if (is.character(file)) file else attr(file, "name") %||% as.character(file)
  ext <- tolower(tools::file_ext(filename))
  if (!ext %in% c("csv", "tsv", "txt", "xlsx", "parquet")) stop("Invalid file type", call. = FALSE)
  df <- switch(ext,
    csv = read.csv(file, check.names = FALSE, stringsAsFactors = FALSE),
    tsv = read.delim(file, check.names = FALSE, stringsAsFactors = FALSE),
    txt = read.delim(file, check.names = FALSE, stringsAsFactors = FALSE),
    xlsx = {
      .require_pkg("readxl")
      as.data.frame(readxl::read_excel(file), check.names = FALSE)
    },
    parquet = {
      .require_pkg("arrow")
      as.data.frame(arrow::read_parquet(file), check.names = FALSE)
    }
  )
  rename_cols(df)
}

strip_sample_measurement_suffix <- function(value) {
  text <- trimws(as.character(value))
  sample_name <- sub("^.*[\\\\/]", "", text, perl = TRUE)

  suffixes <- c(
    paste0(
      "(?i)(?:\\.(?:PG|GG|EG|FG|PEP|PR|Precursor|Protein|Peptide))?\\.",
      "(?:(?:Avg|Average)?Log[._[:space:]-]*2",
      "(?:Normal(?:i[sz]ed|isation|ization))?(?:Quantity|Intensity|Abundance)",
      "|Normal(?:i[sz]ed|isation|ization)(?:Quantity|Intensity|Abundance)?",
      "|Max[._[:space:]-]*LFQ(?:Quantity|Intensity|Abundance)?",
      "|TotalQuantity|Quantity|Intensity|Abundance)$"
    ),
    paste0(
      "(?i)[[:space:]_.-]+(?:",
      "(?:Max[[:space:]_.-]*LFQ[[:space:]_.-]+)?",
      "(?:Unique[[:space:]_.-]+|Total[[:space:]_.-]+|Razor[[:space:]_.-]+)?Intensity",
      "|(?:Unique[[:space:]_.-]+|Total[[:space:]_.-]+|Razor[[:space:]_.-]+)?",
      "Spectral[[:space:]_.-]+Count",
      "|PSMs?|Percent[[:space:]_.-]+PSMs?",
      "|LFQ[[:space:]_.-]+Intensity|iBAQ",
      "|MS[[:space:]]*/[[:space:]]*MS[[:space:]_.-]+Count",
      "|MS[12][[:space:]_.-]+(?:Intensity|Count)",
      "|Razor[[:space:]]*\\+[[:space:]]*Unique[[:space:]_.-]+Peptides",
      "|Unique[[:space:]_.-]+Peptides|Peptides",
      "|Sequence[[:space:]_.-]+Coverage(?:[[:space:]_.-]*\\[%\\])?",
      "|Log[._[:space:]-]*2[[:space:]_.-]*(?:Quantity|Intensity|Abundance|Ratio)",
      "|(?:Quantity|Abundance|Ratio))$"
    )
  )

  previous <- NULL
  while (!identical(sample_name, previous)) {
    previous <- sample_name
    for (suffix in suffixes) {
      sample_name <- trimws(sub(suffix, "", sample_name, perl = TRUE))
    }
  }

  trimws(sub(
    "(?i)\\.(?:d|htrms|raw|wiff2?|mzml|mzxml)$",
    "",
    sample_name,
    perl = TRUE
  ))
}

extract_sample_id <- function(value) {
  original <- trimws(as.character(value))
  sample_name <- strip_sample_measurement_suffix(original)
  m <- gregexpr("[0-9]+", sample_name)[[1]]
  if (m[1] < 0) original else tail(regmatches(sample_name, list(m))[[1]], 1)
}

extract_id_or_number <- function(x) {
  extract_sample_id(x)
}

paired_sample_columns <- function(meta, condition1, condition2) {
  if (identical(as.character(condition1), as.character(condition2))) {
    stop("Paired tests require two different conditions.", call. = FALSE)
  }
  if (!"pair_id" %in% names(meta)) {
    stop(
      "Paired tests require a 'pair_id' metadata column with one stable subject ",
      "identifier per sample.",
      call. = FALSE
    )
  }
  duplicate_samples <- unique(as.character(meta$sample[duplicated(as.character(meta$sample))]))
  if (length(duplicate_samples)) {
    stop(
      "Paired tests require each sample to appear once in metadata. Duplicates: ",
      paste(duplicate_samples, collapse = ", "), ".",
      call. = FALSE
    )
  }

  samples_by_id <- function(condition) {
    rows <- meta[as.character(meta$condition) == as.character(condition), c("sample", "pair_id")]
    if (!nrow(rows)) {
      stop("Condition '", condition, "' does not have any annotated samples.", call. = FALSE)
    }

    samples <- as.character(rows$sample)
    ids <- trimws(ifelse(is.na(rows$pair_id), "", as.character(rows$pair_id)))
    samples <- samples[nzchar(ids)]
    ids <- ids[nzchar(ids)]
    duplicate_ids <- unique(ids[duplicated(ids)])
    if (length(duplicate_ids)) {
      details <- vapply(sort(duplicate_ids), function(id) {
        paste0(id, ": ", paste(samples[ids == id], collapse = ", "))
      }, character(1))
      stop(
        "Paired tests require unique pair IDs within condition '", condition,
        "'. Duplicates: ", paste(details, collapse = "; "), ".",
        call. = FALSE
      )
    }
    stats::setNames(samples, ids)
  }

  left <- samples_by_id(condition1)
  right <- samples_by_id(condition2)
  ids <- names(left)[names(left) %in% names(right)]
  if (length(ids) < 2) {
    stop("Paired tests require at least two matched pair IDs.", call. = FALSE)
  }
  list(condition1 = unname(left[ids]), condition2 = unname(right[ids]))
}

paired_test_enabled <- function(value) {
  mode <- tolower(trimws(as.character(value)))
  if (!mode %in% c("paired", "unpaired")) {
    stop("paired must be 'Paired' or 'Unpaired'.", call. = FALSE)
  }
  mode == "paired"
}

log2_transform_data <- function(data, meta) {
  samples <- as.character(meta$sample)
  output <- data
  values <- .numeric_matrix(data, samples)
  values[values == 0] <- NA_real_
  output[samples] <- log2(values)
  output
}

inverse_log2_transform_data <- function(data, meta) {
  samples <- as.character(meta$sample)
  output <- data
  output[samples] <- 2 ^ .numeric_matrix(data, samples)
  output
}

# Refuse metadata that names a sample more than once. A sample listed twice is
# counted twice by every group-wise mean and variance, which roughly halves the
# standard error while leaving the fold change untouched -- so nothing looks
# wrong and only the p-values move, downward.
.validate_meta_samples <- function(meta) {
  if (!is.data.frame(meta) || !"sample" %in% names(meta)) {
    return(invisible(meta))
  }
  samples <- trimws(as.character(meta$sample))
  repeated <- unique(samples[duplicated(samples)])
  if (length(repeated)) {
    stop(sprintf(
      paste0("Metadata lists %d sample(s) more than once: %s%s. ",
             "Each sample must appear exactly once; a repeated sample is counted ",
             "twice and deflates every p-value."),
      length(repeated),
      paste(utils::head(repeated, 10), collapse = ", "),
      if (length(repeated) > 10) ", and more" else ""
    ))
  }
  invisible(meta)
}


.VALUE_PLACEHOLDERS <- c("", "na", "n/a", "nan", "-", "--", "null", "none",
                         "filtered", "#div/0!", "#n/a")

# Refuse sample columns whose values do not parse as numbers.
#
# as.numeric() turns unparseable text into NA, and NA reads as "not detected"
# from then on. A column exported from a locale that writes 19,436 for 19.436
# loses every value this way: the sample survives the completeness filter on the
# strength of the other replicates and the analysis quietly runs one replicate
# short. Blanks and documented placeholders really are missing, so they are
# ignored; only entries carrying a digit count as a lost measurement.
.validate_sample_values <- function(data, meta, threshold = 0.2) {
  if (!is.data.frame(data) || !is.data.frame(meta) || !"sample" %in% names(meta)) {
    return(invisible(data))
  }
  findings <- character(0)
  for (column in as.character(meta$sample)) {
    if (!column %in% names(data)) next
    raw <- data[[column]]
    if (is.numeric(raw) || is.logical(raw)) next
    text <- trimws(as.character(raw))
    considered <- text[!tolower(text) %in% .VALUE_PLACEHOLDERS]
    if (!length(considered)) next
    coerced <- suppressWarnings(as.numeric(considered))
    has_digit <- grepl("[0-9]", considered)
    lost <- sum(is.na(coerced) & has_digit)
    if (lost == 0) next
    example <- considered[is.na(coerced) & has_digit][1]
    if (lost / length(considered) > threshold) {
      findings <- c(findings, sprintf("%s lost %d of %d values (e.g. '%s')",
                                      column, lost, length(considered), example))
    } else {
      # Below the threshold this is more likely a few odd cells than a mangled
      # export, so it is not worth refusing the frame -- but it is still
      # measurements turning into NA, and saying nothing was the same silence the
      # threshold exists to break. A thousands separator applied by a spreadsheet
      # hits only the largest values, so a partial loss is a biased one.
      warning(sprintf(
        paste0("Sample column '%s' lost %d of %d values that carry digits but do ",
               "not parse as numbers (e.g. '%s'). They become NA and read as ",
               "'not detected' from here on."),
        column, lost, length(considered), example
      ), call. = FALSE)
    }
  }
  if (length(findings)) {
    stop(sprintf(
      paste0("%d sample column(s) carry values that do not parse as numbers: %s. ",
             "This usually means a decimal comma from a locale-specific export. ",
             "Every unparseable value becomes NA, so the sample would be treated ",
             "as fully undetected rather than unreadable."),
      length(findings), paste(findings, collapse = "; ")
    ))
  }
  invisible(data)
}


# Reject a threshold that is not a meaningful quantity. A filter that keeps
# nothing is a legitimate answer to a strict request, so only impossible values
# are refused: a percentage outside 0-100, or a negative count. Those cannot
# describe any completeness requirement, and used to pass silently -- a negative
# count returned the whole matrix unfiltered.
.validate_filter_thresholds <- function(num, method, percentage) {
  if (identical(method, "percentage")) {
    value <- suppressWarnings(as.numeric(percentage))
    if (length(value) != 1L || is.na(value)) {
      stop(sprintf("Minimum completeness percentage must be a number, got '%s'.",
                   paste(percentage, collapse = ", ")), call. = FALSE)
    }
    if (value < 0 || value > 100) {
      stop(sprintf("Minimum completeness percentage must be between 0 and 100, got %g.", value),
           call. = FALSE)
    }
    return(invisible(NULL))
  }

  value <- suppressWarnings(as.numeric(num))
  if (length(value) != 1L || is.na(value) || value != as.integer(value)) {
    stop(sprintf("Minimum valid values must be a whole number, got '%s'.",
                 paste(num, collapse = ", ")), call. = FALSE)
  }
  if (value < 0) {
    stop(sprintf("Minimum valid values must be zero or greater, got %d.", as.integer(value)),
         call. = FALSE)
  }
  invisible(NULL)
}

filter_data <- function(data, meta, num, mode = "per_group", method = "at_least_n", percentage = 70) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  method <- tolower(trimws(method))
  # One spelling everywhere since 2026-10-02 (per_group, as the app uses); the
  # older "per group" with a space is still read the same way.
  mode <- gsub(" ", "_", tolower(trimws(mode)))
  if (!method %in% c("at_least_n", "percentage")) {
    stop("Filter method must be 'at_least_n' or 'percentage'.", call. = FALSE)
  }
  # An unrecognised mode used to fall through to the `any` branch, silently
  # applying the most permissive filter of the three: a misspelling retained
  # features present in only one condition, which is what `per_group` exists to
  # exclude.
  if (!mode %in% c("per_group", "in_at_least_one_group", "overall")) {
    stop("Filter mode must be 'per_group', 'in_at_least_one_group', or 'overall'.", call. = FALSE)
  }
  .validate_filter_thresholds(num, method, percentage)
  if (mode == "overall") {
    valid <- rowSums(!is.na(data[, meta$sample, drop = FALSE]))
    rows_to_keep <- if (method == "percentage") valid / length(meta$sample) >= percentage / 100 else valid >= num
  } else {
    conditions <- unique(meta$condition)
    keep <- sapply(conditions, function(cond) {
      columns <- meta$sample[meta$condition == cond]
      valid <- rowSums(!is.na(data[, columns, drop = FALSE]))
      if (method == "percentage") valid / length(columns) >= percentage / 100 else valid >= num
    })
    if (is.null(dim(keep))) keep <- matrix(keep, ncol = 1)
    rows_to_keep <- if (mode == "per_group") apply(keep, 1, all) else apply(keep, 1, any)
  }
  data[rows_to_keep, , drop = FALSE]
}

# Phosphosite localization probability cutoff, mirrored from the backend and
# the pip package. 0 keeps every row; above 0 a row without a probability
# (missing, non-numeric or outside 0..1) is dropped. `.localization_keep`
# returns the row mask, so an aligned matrix (observed, coverage_data) can be
# narrowed to the same rows.
.localization_keep <- function(data, cutoff = 0, column = "PTM_localization") {
  cutoff <- suppressWarnings(as.numeric(cutoff))
  if (length(cutoff) != 1L || is.na(cutoff) || cutoff < 0 || cutoff > 1) {
    stop("The localization probability cutoff must be between 0 and 1.", call. = FALSE)
  }
  if (cutoff <= 0) return(rep(TRUE, nrow(data)))
  if (!column %in% names(data)) {
    stop(sprintf(
      "A localization probability cutoff of %.2f needs a '%s' column, which this phosphosite table does not have.",
      cutoff, column
    ), call. = FALSE)
  }
  probability <- suppressWarnings(as.numeric(as.character(data[[column]])))
  probability[!is.finite(probability) | probability < 0 | probability > 1] <- NA_real_
  !is.na(probability) & probability >= cutoff
}

filter_localization <- function(data, cutoff = 0, column = "PTM_localization") {
  data[.localization_keep(data, cutoff, column), , drop = FALSE]
}

# Modes as in the pip package; "mean" averages only the sites quantified in
# every sample, so all samples use the same sites.
transform_phosprot <- function(
    data,
    meta,
    mode = "robust_site_median",
    data_scale = "linear",
    coverage_data = NULL,
    localization_cutoff = 0
) {
  keep <- .localization_keep(data, localization_cutoff)
  data <- data[keep, , drop = FALSE]
  if (!is.null(coverage_data)) coverage_data <- coverage_data[keep, , drop = FALSE]
  required <- c("UPD_seq", "PTM_localization", "Protein_group", "Gene_group", "PTM_Collapse_key")
  missing <- setdiff(required, names(data))
  if (length(missing)) {
    stop(
      "Missing required columns in `data`: ",
      paste(missing, collapse = ", "),
      call. = FALSE
    )
  }
  if (!all(c("condition", "sample") %in% names(meta))) {
    stop("`meta` must contain columns: 'condition', 'sample'", call. = FALSE)
  }

  samples <- as.character(meta$sample)
  if (!length(samples)) {
    stop("`meta` must contain at least one sample", call. = FALSE)
  }
  duplicate_samples <- unique(samples[duplicated(samples)])
  if (length(duplicate_samples)) {
    stop(
      "`meta.sample` contains duplicate names: ",
      paste(duplicate_samples, collapse = ", "),
      call. = FALSE
    )
  }
  missing_samples <- setdiff(samples, names(data))
  if (length(missing_samples)) {
    stop("`meta.sample` contains names not found in data", call. = FALSE)
  }

  data_scale <- tolower(trimws(as.character(data_scale)))
  if (!data_scale %in% c("linear", "log2")) {
    stop("data_scale must be 'linear' or 'log2'.", call. = FALSE)
  }
  data$Protein_group <- as.character(data$Protein_group)

  bad <- tapply(data$Gene_group, data$Protein_group, function(x) length(unique(na.omit(x)))) > 1
  if (any(bad)) {
    stop("Each Protein_group must map to exactly one Gene_group.", call. = FALSE)
  }

  if (data_scale == "log2") {
    log2_data <- data
    log2_data[samples] <- lapply(log2_data[samples], function(x) suppressWarnings(as.numeric(x)))
    linear_data <- inverse_log2_transform_data(log2_data, meta)
  } else {
    linear_data <- raw_zero_to_nan(data, samples)
    log2_data <- log2_transform_data(linear_data, meta)
  }

  log2_matrix <- .numeric_matrix(log2_data, samples)
  linear_matrix <- .numeric_matrix(linear_data, samples)
  log2_matrix[!is.finite(log2_matrix)] <- NA_real_
  linear_matrix[!is.finite(linear_matrix)] <- NA_real_
  # Original observations determine diagnostics and eligibility; supplied
  # (possibly imputed) values determine per-sample aggregation availability.
  coverage_matrix <- log2_matrix
  if (!is.null(coverage_data)) {
    if (!identical(rownames(coverage_data), rownames(data)) ||
        !all(c("Protein_group", samples) %in% names(coverage_data))) {
      stop("coverage_data must have matching rows and required columns.", call. = FALSE)
    }
    if (!identical(as.character(coverage_data$Protein_group), data$Protein_group)) {
      stop("coverage_data Protein_group values must align exactly with data.", call. = FALSE)
    }
    if (data_scale == "linear") {
      coverage_data <- log2_transform_data(raw_zero_to_nan(coverage_data, samples), meta)
    }
    coverage_matrix <- .numeric_matrix(coverage_data, samples)
  }
  eligible <- rowSums(is.finite(coverage_matrix)) > 0
  group_names <- unique(data$Protein_group)
  groups <- split(seq_len(nrow(data)), factor(data$Protein_group, levels = group_names))
  rows <- lapply(names(groups), function(group_name) {
    indices <- groups[[group_name]]
    eligible_indices <- indices[eligible[indices]]
    eligible_count <- length(eligible_indices)
    observed <- if (eligible_count) {
      colSums(is.finite(coverage_matrix[eligible_indices, , drop = FALSE]))
    } else {
      setNames(rep(0, length(samples)), samples)
    }
    coverage <- if (eligible_count) observed / eligible_count else rep(NA_real_, length(samples))

    row <- list(
      Phosphoprotein = group_name,
      Gene_group = data$Gene_group[indices[1]],
      site_num = length(indices),
      site_num_eligible = eligible_count,
      PTM_Collapse_keys = paste(
        sort(unique(na.omit(as.character(data$PTM_Collapse_key[indices])))),
        collapse = ";"
      ),
      PTM_localization = paste(
        na.omit(as.character(data$PTM_localization[indices])),
        collapse = ";"
      ),
      UPD_seq = paste(
        sort(unique(na.omit(as.character(data$UPD_seq[indices])))),
        collapse = ";"
      )
    )

    used_indices <- eligible_indices
    if (mode == "robust_site_median") {
      values <- if (eligible_count) log2_matrix[eligible_indices, , drop = FALSE] else matrix(NA_real_, 0, length(samples))
      if (eligible_count) {
        centres <- apply(values, 1, median, na.rm = TRUE)
        values <- sweep(values, 1, centres, "-")
      }
      required <- max(1L, ceiling(eligible_count * 0.5))
      for (sample_index in seq_along(samples)) {
        sample_values <- values[, sample_index]
        row[[samples[sample_index]]] <- if (sum(is.finite(sample_values)) >= required) {
          median(sample_values, na.rm = TRUE)
        } else {
          NA_real_
        }
      }
    } else {
      sum_fun <- switch(mode,
        sum_propagate_na = function(x) if (any(is.na(x))) NA_real_ else sum(x),
        sum_ignore_na = function(x) if (all(is.na(x))) NA_real_ else sum(x, na.rm = TRUE),
        mean = function(x) if (all(is.na(x))) NA_real_ else mean(x, na.rm = TRUE),
        stop(
          "mode must be 'robust_site_median', 'sum_propagate_na', 'sum_ignore_na', or 'mean'",
          call. = FALSE
        )
      )
      # 'mean' and 'sum_ignore_na' use only sites quantified in every sample, so
      # all samples use the same sites and coverage cannot flip a fold change.
      used_indices <- if (mode %in% c("mean", "sum_ignore_na")) {
        eligible_indices[rowSums(!is.finite(linear_matrix[eligible_indices, , drop = FALSE])) == 0]
      } else {
        eligible_indices
      }
      for (sample_index in seq_along(samples)) {
        row[[samples[sample_index]]] <- if (length(used_indices)) {
          sum_fun(linear_matrix[used_indices, sample_index])
        } else {
          NA_real_
        }
      }
    }

    row$site_observed_min <- min(observed)
    row$site_observed_mean <- mean(observed)
    row$site_coverage_min <- if (all(is.na(coverage))) NA_real_ else min(coverage, na.rm = TRUE)
    row$site_coverage_mean <- if (all(is.na(coverage))) NA_real_ else mean(coverage, na.rm = TRUE)
    row$site_complete_samples <- if (eligible_count) sum(observed == eligible_count) else 0L
    for (sample_index in seq_along(samples)) {
      row[[paste0("site_observed__", samples[sample_index])]] <- observed[sample_index]
      row[[paste0("site_coverage__", samples[sample_index])]] <- coverage[sample_index]
    }
    for (sample_index in seq_along(samples)) {
      supplied_matrix <- if (mode == "robust_site_median") log2_matrix else linear_matrix
      supplied <- is.finite(supplied_matrix[used_indices, sample_index])
      row[[paste0("site_supplied__", samples[sample_index])]] <- sum(supplied)
      row[[paste0("site_measured__", samples[sample_index])]] <- sum(
        supplied & is.finite(coverage_matrix[used_indices, sample_index]))
    }
    row
  })

  output <- as.data.frame(
    # check.names = FALSE: real sample names (Spectronaut, DIA-NN) start with a
    # digit or contain "-", which as.data.frame would rewrite, breaking the
    # sample-column lookups below ("undefined columns selected").
    do.call(rbind, lapply(rows, as.data.frame, check.names = FALSE, stringsAsFactors = FALSE)),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
  numeric_columns <- c(
    "site_num", "site_num_eligible", samples,
    "site_observed_min", "site_observed_mean", "site_coverage_min",
    "site_coverage_mean", "site_complete_samples",
    paste0("site_observed__", samples), paste0("site_coverage__", samples),
    paste0("site_supplied__", samples), paste0("site_measured__", samples)
  )
  output[numeric_columns] <- lapply(output[numeric_columns], function(x) as.numeric(as.character(x)))

  # These modes aggregate original-scale intensities, so their result is linear
  # while robust_site_median returns log2. Everything downstream -- volcano_data_f
  # above all -- labels its output "log2FC" unconditionally, so a linear frame
  # yields a "log2FC" that is really a difference of raw intensities, in the
  # thousands. Transform here so every mode returns the same scale.
  if (mode != "robust_site_median") {
    aggregated <- as.matrix(output[samples])
    non_positive <- sum(aggregated <= 0, na.rm = TRUE)
    if (non_positive > 0) {
      aggregated[!is.na(aggregated) & aggregated <= 0] <- NA_real_
      warning(sprintf(
        paste0("%d aggregated value(s) were not positive and were set to missing ",
               "because they cannot be log2 transformed. This points at a scale or ",
               "imputation problem in the phosphosite input rather than at the ",
               "aggregation."),
        non_positive
      ), call. = FALSE)
    }
    output[samples] <- as.data.frame(log2(aggregated))
  }
  output
}

qqnorm_plot <- function(data, meta, seed = 187) {
  values <- as.vector(.numeric_matrix(data, meta$sample))
  values <- values[is.finite(values)]

  if (length(values) > 100000) {
    values <- .with_local_seed(seed, function() sample(values, 100000))
  }

  qqnorm(
    values,
    main = "QQ Plot",
    xlab = "Theoretical Quantiles",
    ylab = "Sample Quantiles",
    pch = 16,
    cex = 0.45,
    col = grDevices::adjustcolor(.tab10[1], alpha.f = 0.55)
  )
  qqline(values, col = "red", lwd = 1.5)

  .plot_result()
}

# Methods: "quantile" (default) draws around the q-quantile of the observed values
# with adj_std times their standard deviation, in the spirit of MinProb (Lazar et
# al. 2016, doi:10.1021/acs.jproteome.5b00981). "numerical" is the downshifted
# normal with Perseus defaults, mean - down_shift * SD and width * SD (Tyanova et
# al. 2016, doi:10.1038/nmeth.3901).
# Phosphoprotein workflows: impute phosphosites BEFORE transform_phosprot, never
# the collapsed matrix. Retain the non-imputed site matrix for coverage checks;
# aggregate imputed log2 values with data_scale="log2".
# This generic helper cannot infer biological dataset level from an arbitrary frame.
impute_values <- function(data, meta, q=0.01, adj_std=0.3, ret=0, sample_wise=TRUE, seed=1337, method="quantile", down_shift=1.8, width=0.3) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  method <- tolower(trimws(method))
  if (method == "normal") method <- "quantile"
  if (!method %in% c("quantile", "numerical")) {
    stop("Imputation method must be 'quantile' or 'numerical'.", call. = FALSE)
  }
  spread <- suppressWarnings(as.numeric(if (method == "quantile") adj_std else width))
  if (length(spread) != 1L || is.na(spread) || spread <= 0) {
    stop("Adjust standard deviation must be greater than 0.", call. = FALSE)
  }
  samples <- as.character(meta$sample)
  output <- data
  values <- .numeric_matrix(data, samples)
  missing_mask <- is.na(values)

  complete_values <- as.vector(values[rowSums(missing_mask) == 0, , drop = FALSE])
  incomplete_values <- as.vector(values[rowSums(missing_mask) > 0, , drop = FALSE])
  incomplete_values <- incomplete_values[is.finite(incomplete_values)]

  if (ret %in% c(1,2,3) && !any(is.finite(values))) {
    stop("No observed values available to plot an imputation distribution.", call. = FALSE)
  }

  if (ret == 1) {
    hist(
      complete_values,
      breaks = 50,
      probability = TRUE,
      col = grDevices::adjustcolor(.tab10[1], alpha.f = 0.45),
      border = NA,
      xlab = "log2 Intensity",
      ylab = "Density",
      main = "Overall distribution of data with and without missing values"
    )
    hist(
      incomplete_values,
      breaks = 50,
      probability = TRUE,
      col = grDevices::adjustcolor(.tab10[2], alpha.f = 0.45),
      border = NA,
      add = TRUE
    )
    legend(
      "topright",
      c("Without Missing Values", "With Missing Values"),
      fill = grDevices::adjustcolor(.tab10[1:2], alpha.f = 0.45),
      border = NA,
      bty = "n"
    )
    return(.plot_result())
  }

  mean_value <- mean(values, na.rm = TRUE)
  sd_value <- sd(values, na.rm = TRUE)
  quantile_value <- quantile(values, q, na.rm = TRUE)
  observed <- values[!is.na(values)]
  if (!sample_wise && (length(observed) < 2 || !is.finite(sd_value) || sd_value <= 0 || length(unique(observed)) == 1)) {
    stop("Global imputation requires at least two observed values with nonzero spread.", call. = FALSE)
  }

  if (ret == 2) {
    finite_values <- values[is.finite(values)]
    hist(
      finite_values,
      breaks = 50,
      probability = TRUE,
      col = grDevices::adjustcolor("blue", alpha.f = 0.45),
      border = NA,
      xlab = "log2 Intensity",
      ylab = "Density",
      main = "Overall data distribution and norm fit"
    )
    if (is.finite(sd_value) && sd_value > 0) {
      curve(dnorm(x, mean = mean_value, sd = sd_value), add = TRUE, col = "red", lwd = 2)
      legend("topright", "Normal fit", col = "red", lwd = 2, bty = "n")
    }
    return(.plot_result())
  }

  values <- .with_local_seed(seed, function() {
    for (column_index in seq_along(samples)) {
      number_missing <- sum(missing_mask[, column_index])
      if (!number_missing) next

      if (sample_wise) {
        observed_sample <- values[, column_index]
        observed_sample <- observed_sample[!is.na(observed_sample)]
        sample_sd <- sd(values[, column_index], na.rm = TRUE)
        if (length(observed_sample) < 2 || !is.finite(sample_sd) || sample_sd <= 0 || length(unique(observed_sample)) == 1) {
          warning(paste0("Missing values left unchanged: fewer than two observations or no usable spread in sample: ", samples[column_index]), call. = FALSE)
          next
        }
        if (method == "numerical") {
          draw_center <- mean(values[, column_index], na.rm = TRUE) - down_shift * sample_sd
          draw_sd <- sample_sd * width
        } else {
          draw_center <- quantile(values[, column_index], q, na.rm = TRUE)
          # adj_std must scale the draw here exactly as it does in the global
          # branch below; without it the setting is inert in sample-wise mode and
          # the spread is always the full SD.
          draw_sd <- sample_sd * adj_std
        }
      } else {
        if (method == "numerical") {
          draw_center <- mean_value - down_shift * sd_value
          draw_sd <- sd_value * width
        } else {
          draw_center <- quantile_value
          draw_sd <- sd_value * adj_std
        }
      }

      values[missing_mask[, column_index], column_index] <- rnorm(
        number_missing,
        mean = draw_center,
        sd = draw_sd
      )
    }
    values
  })

  if (ret == 3) {
    non_imputed <- values[!missing_mask]
    imputed <- values[missing_mask]
    hist(
      non_imputed,
      breaks = 50,
      probability = TRUE,
      col = grDevices::adjustcolor(.tab10[1], alpha.f = 0.45),
      border = NA,
      xlab = "log2 Intensity",
      ylab = "Density",
      main = "Distribution of data after imputation"
    )
    hist(
      imputed,
      breaks = 50,
      probability = TRUE,
      col = grDevices::adjustcolor(.tab10[2], alpha.f = 0.45),
      border = NA,
      add = TRUE
    )
    legend(
      "topright",
      c("Non-Imputed Values", "Imputed Values"),
      fill = grDevices::adjustcolor(.tab10[1:2], alpha.f = 0.45),
      border = NA,
      bty = "n"
    )
    return(.plot_result())
  }

  output[samples] <- as.data.frame(values)
  output
}

# QC FUNCTIONS
# A `seed` parameter used to sit before `data_scale` here, accepted but never
# read, in the positional slot the pip package uses for `data_scale`. A
# positional call therefore set a different parameter in each package.
coverage_plot <- function(
    data,
    meta,
    id = TRUE,
    header = TRUE,
    legend = TRUE,
    plot_colors = NULL,
    width = 20,
    height = 10,
    dpi = 300,
    text = FALSE,
    text_size = 9,
    data_scale = "log2"
) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  meta <- .sample_meta(meta, id = id, newline = TRUE)
  renamed_data <- .rename_samples(data, meta)

  samples <- intersect(meta$new_sample, names(renamed_data))
  if (!length(samples)) {
    stop("None of the annotated columns exist in the data after renaming.", call. = FALSE)
  }

  counts <- colSums(!is.na(renamed_data[, samples, drop = FALSE]))
  quantified <- sum(rowSums(!is.na(renamed_data[, samples, drop = FALSE])) > 0)
  conditions <- meta$condition[match(samples, meta$new_sample)]
  condition_levels <- unique(meta$condition)
  condition_colors <- setNames(
    .plot_colors(length(condition_levels), plot_colors),
    condition_levels
  )

  redline <- NULL
  title <- ""
  y_label <- "Number"

  if ("Phosphoprotein" %in% names(data)) {
    redline <- quantified
    title <- "Phosphoproteins per sample"
    y_label <- "Number of phosphoproteins"
  } else if ("ProteinNames" %in% names(data)) {
    redline <- quantified
    title <- "Proteins per sample"
    y_label <- "Number of proteins"
  } else if ("PTM_Collapse_key" %in% names(data)) {
    redline <- quantified
    title <- "Phosphosites per sample"
    y_label <- "Number of phosphosites"
  }

  ymax <- max(counts, redline %||% 0, na.rm = TRUE) * 1.1

  .set_notebook_plot_size(width, height)
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)

  if (legend) {
    layout(matrix(c(1, 2), nrow = 1), widths = c(5, 1.25))
  }
  par(mar = c(8, 5, 3.5, 1), xpd = FALSE)

  mids <- barplot(
    counts,
    names.arg = FALSE,
    col = unname(condition_colors[conditions]),
    border = NA,
    ylim = c(0, ymax),
    axes = FALSE,
    xlab = "Sample",
    ylab = y_label,
    main = if (header) title else ""
  )
  axis(1, at = mids, labels = samples, las = 2, cex.axis = 0.65, tick = FALSE)
  axis(2, las = 1)
  box(bty = "l")

  if (!is.null(redline)) {
    plot_range <- par("usr")
    segments(
      plot_range[1],
      redline,
      plot_range[2],
      redline,
      col = "red",
      lty = 2,
      lwd = 1.2,
      xpd = FALSE
    )
  }

  if (text) {
    text(
      mids,
      pmax(counts * 0.02, ymax * 0.01),
      labels = ceiling(counts),
      srt = 90,
      adj = c(0, 0.5),
      cex = text_size / 12,
      font = 2
    )
  }

  if (legend) {
    par(mar = c(0, 0.5, 1, 0), xpd = FALSE)
    plot.new()
    legend(
      "topleft",
      inset = c(0.02, 0.02),
      legend = condition_levels,
      fill = condition_colors,
      title = "Condition",
      border = NA,
      bty = "n",
      cex = min(0.9, 12 / max(12, length(condition_levels)))
    )
  }

  .plot_result()
}

coverage_plot_summary <- function(
    data,
    meta,
    header = TRUE,
    plot_colors = NULL,
    width = 20,
    height = 10,
    dpi = 300,
    text = FALSE,
    text_size = 9,
    seed = 69,
    data_scale = "log2"
) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  meta <- .sample_meta(meta, id = TRUE, newline = TRUE)
  renamed_data <- .rename_samples(data, meta)

  counts <- colSums(!is.na(renamed_data[, meta$new_sample, drop = FALSE]))
  quantified <- sum(rowSums(!is.na(renamed_data[, meta$new_sample, drop = FALSE])) > 0)
  condition_values <- split(counts, meta$condition)
  means <- vapply(condition_values, mean, numeric(1))
  sds <- vapply(condition_values, sd, numeric(1))
  sds[!is.finite(sds)] <- 0

  conditions <- names(condition_values)
  colors <- .plot_colors(length(conditions), plot_colors)

  redline <- NULL
  title <- ""
  y_label <- "Number"

  if ("Phosphoprotein" %in% names(data)) {
    redline <- quantified
    title <- "Phosphoproteins per sample"
    y_label <- "Number of phosphoproteins"
  } else if ("ProteinNames" %in% names(data)) {
    redline <- quantified
    title <- "Proteins per sample"
    y_label <- "Number of proteins"
  } else if ("PTM_Collapse_key" %in% names(data)) {
    redline <- quantified
    title <- "Phosphosites per sample"
    y_label <- "Number of phosphosites"
  }

  ymax <- max(means + sds, redline %||% 0, na.rm = TRUE) * 1.1

  .set_notebook_plot_size(width, height)
  old_par <- par(mar = c(8, 5, 3.5, 2), xpd = FALSE)
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    means,
    names.arg = FALSE,
    col = colors,
    border = "black",
    ylim = c(0, ymax),
    axes = FALSE,
    xlab = "Condition",
    ylab = y_label,
    main = if (header) title else ""
  )
  axis(1, at = mids, labels = conditions, las = 2, cex.axis = 0.75, tick = FALSE)
  axis(2, las = 1)
  box(bty = "l")

  arrows(
    mids,
    pmax(0, means - sds),
    mids,
    means + sds,
    angle = 90,
    code = 3,
    length = 0.05
  )

  .with_local_seed(seed, function() {
    for (i in seq_along(condition_values)) {
      points(
        jitter(rep(mids[i], length(condition_values[[i]])), amount = 0.08),
        condition_values[[i]],
        pch = 16,
        col = rgb(0, 0, 0, 0.7),
        cex = 0.75
      )
    }
  })

  if (!is.null(redline)) {
    plot_range <- par("usr")
    segments(
      plot_range[1],
      redline,
      plot_range[2],
      redline,
      col = "red",
      lty = 2,
      lwd = 1.2,
      xpd = FALSE
    )
  }

  if (text) {
    text(
      mids,
      pmax(means * 0.02, ymax * 0.01),
      labels = ceiling(means),
      srt = 90,
      adj = c(0, 0.5),
      cex = text_size / 12,
      font = 2
    )
  }

  .plot_result()
}

.peptide_sample_map <- function(columns, samples) {
  columns <- as.character(columns)
  samples <- as.character(samples)
  exact <- intersect(columns, samples)
  mapping <- setNames(exact, exact)
  remaining_columns <- setdiff(columns, exact)
  remaining_samples <- setdiff(samples, columns)
  if (length(remaining_columns) && length(remaining_samples)) {
    by_id <- sample_id_map(remaining_columns)
    sample_id_map(remaining_samples)
    for (sample in remaining_samples) {
      column <- by_id[[extract_sample_id(sample)]]
      if (!is.null(column)) mapping[column] <- sample
    }
  }
  if (length(samples) && !length(mapping)) stop("Peptide metadata does not match peptide sample columns.", call.=FALSE)
  mapping
}

coverage_plot_pep <- function(
    data2_path,
    meta,
    id = TRUE,
    header = TRUE,
    legend = TRUE,
    plot_colors = NULL,
    width = 10,
    height = 6,
    dpi = 100,
    quantity_column = "Precursor.Quantity",
    level = "peptide"
) {
  if (!level %in% c("peptide", "precursor")) stop("Coverage level must be peptide or precursor.", call.=FALSE)
  feature_column <- if (level == "precursor") "Precursor.Id" else "Stripped.Sequence"
  data <- if (is.data.frame(data2_path)) {
    data2_path
  } else {
    sanitize_dataframe(read_data(data2_path))
  }
  meta <- .sample_meta(meta, id = id, newline = TRUE)

  if ("File.Name" %in% names(data)) {
    wide_data <- .pivot_wide(
      data,
      feature_column,
      "File.Name",
      quantity_column,
      max
    )
  } else {
    wide_data <- data
  }

  mapping <- .peptide_sample_map(setdiff(names(wide_data), feature_column), meta$sample)
  matched <- match(names(mapping), names(wide_data))
  names(wide_data)[matched] <- meta$new_sample[match(unname(mapping), meta$sample)]
  samples <- intersect(meta$new_sample, names(wide_data))
  quantified <- !is.na(wide_data[, samples, drop = FALSE]) &
    wide_data[, samples, drop = FALSE] != 0
  counts <- colSums(quantified)
  # Reference line: features quantified in at least one annotated sample (the
  # union of the bars), as in coverage_plot; not the number of sequences in the file.
  peptide_count <- sum(rowSums(quantified) > 0)
  conditions <- meta$condition[match(samples, meta$new_sample)]
  condition_levels <- unique(meta$condition)
  condition_colors <- setNames(
    .plot_colors(length(condition_levels), plot_colors),
    condition_levels
  )

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)

  if (legend) {
    layout(matrix(c(1, 2), nrow = 1), widths = c(5, 1.25))
  }
  par(mar = c(8, 5, 3.5, 1), xpd = FALSE)

  mids <- barplot(
    counts,
    names.arg = FALSE,
    col = unname(condition_colors[conditions]),
    border = NA,
    ylim = c(0, max(counts, peptide_count) * 1.1),
    axes = FALSE,
    xlab = "Sample",
    ylab = paste("Number of", paste0(level, "s")),
    main = if (header) paste0(if (level == "precursor") "Precursors" else "Peptides", " per sample") else ""
  )
  axis(1, at = mids, labels = samples, las = 2, cex.axis = 0.7, tick = FALSE)
  axis(2, las = 1)
  box(bty = "l")

  plot_range <- par("usr")
  segments(
    plot_range[1],
    peptide_count,
    plot_range[2],
    peptide_count,
    col = "red",
    lty = 2,
    lwd = 1.2,
    xpd = FALSE
  )

  if (legend) {
    par(mar = c(0, 0.5, 1, 0), xpd = FALSE)
    plot.new()
    legend(
      "topleft",
      inset = c(0.02, 0.02),
      legend = condition_levels,
      fill = condition_colors,
      title = "Condition",
      border = NA,
      bty = "n",
      cex = min(0.9, 12 / max(12, length(condition_levels)))
    )
  }

  .plot_result()
}

histo_int <- function(data, meta, plot_colors=NULL, header=TRUE, legend=TRUE, width=20, height=10, dpi=300) {
  conditions <- unique(meta$condition)
  mean_intensities <- lapply(conditions, function(condition) {
    columns <- meta$sample[meta$condition == condition]
    values <- rowMeans(.numeric_matrix(data, columns), na.rm = TRUE)
    values[is.finite(values)]
  })

  densities <- lapply(mean_intensities, density)
  x_range <- range(unlist(lapply(densities, `[[`, "x")))
  y_range <- c(0, max(unlist(lapply(densities, `[[`, "y"))))
  colors <- .plot_colors(length(conditions), plot_colors)

  .set_notebook_plot_size(width, height)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  plot(
    NA,
    xlim = x_range,
    ylim = y_range,
    xlab = "log2 Intensity",
    ylab = "Density",
    main = if (header) "Distribution of mean intensity per condition (log2)" else "",
    bty = "l"
  )

  for (i in seq_along(densities)) {
    lines(densities[[i]], col = colors[i], lwd = 2)
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = conditions,
      col = colors,
      lty = 1,
      lwd = 2,
      title = "Condition",
      bty = "n"
    )
  }

  .plot_result()
}

boxplot_int <- function(data, meta, outliers=FALSE, header=TRUE, plot_colors=NULL, width_cm=20, height_cm=10, dpi=100, text=FALSE, text_size=9) {
  conditions <- unique(meta$condition)
  mean_intensities <- lapply(conditions, function(condition) {
    columns <- meta$sample[meta$condition == condition]
    values <- rowMeans(.numeric_matrix(data, columns), na.rm = TRUE)
    values[is.finite(values)]
  })
  medians <- vapply(mean_intensities, median, numeric(1))
  colors <- .plot_colors(length(conditions), plot_colors)

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins()
  on.exit(par(old_par), add = TRUE)

  boxplot(
    mean_intensities,
    names = conditions,
    col = colors,
    border = "black",
    outline = outliers,
    medcol = "firebrick",
    medlwd = 2.5,
    whisklwd = 1.5,
    staplelwd = 1.5,
    boxlwd = 1.5,
    xlab = "Condition",
    ylab = "log2 Intensity",
    main = if (header) "Mean intensity per condition (log2)" else ""
  )

  if (text) {
    text(
      seq_along(medians),
      medians,
      labels = sprintf("%.2f", medians),
      pos = 3,
      cex = text_size / 12,
      font = 2
    )
  }

  .plot_result()
}

boxplot_int_single <- function(data, meta, outliers=FALSE, id=TRUE, header=TRUE, legend=TRUE, plot_colors=NULL, width_cm=20, height_cm=10, dpi=100, text=FALSE, text_size=9) {
  meta <- .sample_meta(meta, id = id)
  renamed_data <- .rename_samples(data, meta)

  intensities <- lapply(meta$new_sample, function(sample) {
    values <- suppressWarnings(as.numeric(renamed_data[[sample]]))
    values[is.finite(values)]
  })
  medians <- vapply(intensities, median, numeric(1))

  conditions <- unique(meta$condition)
  condition_colors <- setNames(
    .plot_colors(length(conditions), plot_colors),
    conditions
  )
  sample_colors <- unname(condition_colors[meta$condition])

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins(legend = legend, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  boxplot(
    intensities,
    names = meta$new_sample,
    las = 2,
    cex.names = 0.65,
    col = sample_colors,
    border = "black",
    outline = outliers,
    medcol = "firebrick",
    medlwd = 2,
    ylab = "log2 Intensity",
    main = if (header) "Measured protein intensity values (log2)" else ""
  )

  if (text) {
    text(
      seq_along(medians),
      medians,
      labels = sprintf("%.2f", medians),
      pos = 3,
      cex = text_size / 12,
      font = 2
    )
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = conditions,
      fill = condition_colors,
      title = "Condition",
      border = "black",
      bty = "n"
    )
  }

  .plot_result()
}

cov_plot <- function(data, meta, outliers=FALSE, header=TRUE, legend=TRUE, plot_colors=NULL, width_cm=20, height_cm=10, dpi=100, text=FALSE, text_size=9, data_scale=NULL) {
  if (is.null(data_scale)) {
    stop(
      "cov_plot requires data_scale='linear'; coefficient of variation is not meaningful on log2-transformed intensities.",
      call. = FALSE
    )
  }
  if (length(data_scale) != 1L) {
    stop("data_scale must be 'linear' for cov_plot.", call. = FALSE)
  }
  normalized_scale <- tolower(trimws(as.character(data_scale)))
  if (!identical(normalized_scale, "linear")) {
    if (identical(normalized_scale, "log2")) {
      stop(
        "cov_plot requires linear intensities; inverse-transform log2 data before plotting and pass data_scale='linear'.",
        call. = FALSE
      )
    }
    stop("data_scale must be 'linear' for cov_plot.", call. = FALSE)
  }

  data <- .prepare_intensity_data(data, meta$sample, normalized_scale)
  valid_conditions <- character()
  cv_data <- list()

  for (condition in unique(meta$condition)) {
    columns <- meta$sample[meta$condition == condition]
    if (length(columns) < 2) next

    values <- .numeric_matrix(data, columns)
    cv <- apply(values, 1, sd, na.rm = TRUE) /
      rowMeans(values, na.rm = TRUE) * 100
    cv <- cv[is.finite(cv)]

    if (length(cv)) {
      valid_conditions <- c(valid_conditions, condition)
      cv_data[[length(cv_data) + 1]] <- cv
    }
  }

  colors <- .plot_colors(length(valid_conditions), plot_colors)
  medians <- vapply(cv_data, median, numeric(1))

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  boxplot(
    cv_data,
    names = valid_conditions,
    col = colors,
    border = "black",
    outline = outliers,
    medcol = "firebrick",
    medlwd = 2.5,
    whisklwd = 1.5,
    staplelwd = 1.5,
    boxlwd = 1.5,
    xlab = "Condition",
    ylab = "Coefficient of Variation (%)",
    main = if (header) "Coefficient of Variation" else ""
  )

  if (text) {
    text(
      seq_along(medians),
      medians,
      labels = sprintf("%.2f", medians),
      pos = 3,
      cex = text_size / 12,
      font = 2
    )
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = valid_conditions,
      fill = colors,
      title = "Condition",
      border = "black",
      bty = "n"
    )
  }

  .plot_result()
}

minimum_enclosing_ellipse <- function(points, tol=1e-3) {
  points <- as.matrix(points)
  n_points <- nrow(points)
  dimensions <- ncol(points)
  q_matrix <- rbind(t(points), rep(1, n_points))
  weights <- rep(1 / n_points, n_points)
  error <- tol + 1

  for (iteration in seq_len(10000L)) {
    x_matrix <- q_matrix %*% diag(weights) %*% t(q_matrix)
    distances <- diag(t(q_matrix) %*% solve(x_matrix) %*% q_matrix)
    index <- which.max(distances)
    step_size <- (distances[index] - dimensions - 1) /
      ((dimensions + 1) * (distances[index] - 1))

    new_weights <- (1 - step_size) * weights
    new_weights[index] <- new_weights[index] + step_size
    error <- sqrt(sum((new_weights - weights)^2))
    weights <- new_weights
    if (error <= tol) break
  }
  if (!is.finite(error) || error > tol) stop("Enclosing ellipse did not converge.")

  center <- as.vector(t(points) %*% weights)
  a_matrix <- solve(
    t(points) %*% diag(weights) %*% points - tcrossprod(center)
  ) / dimensions
  decomposition <- svd(a_matrix)

  list(
    center = center,
    axes = 1 / sqrt(decomposition$d),
    angle = atan2(decomposition$u[2, 1], decomposition$u[1, 1]) * 180 / pi
  )
}

# Fit an enclosing ellipse only when the group reliably spans the plane.
fitted_group_ellipse <- function(points) {
  points <- as.matrix(points)
  if (nrow(points) < 3 || ncol(points) != 2 || !all(is.finite(points))) {
    return(NULL)
  }
  origin <- colMeans(points)
  centered <- sweep(points, 2, origin, "-")
  scale <- max(abs(centered))
  if (!is.finite(scale) || scale == 0) return(NULL)
  normalized <- centered / scale
  fit <- tryCatch({
    singular <- svd(normalized, nu=0, nv=0)$d
    # The scatter matrix squares the coordinate condition number.
    if (min(singular) <= max(singular) * sqrt(.Machine$double.eps)) return(NULL)
    minimum_enclosing_ellipse(normalized)
  }, error = function(e) NULL)
  if (is.null(fit)) {
    return(NULL)
  }
  fit$center <- origin + fit$center * scale
  fit$axes <- fit$axes * scale
  if (!all(is.finite(fit$center)) || !all(is.finite(fit$axes)) || !is.finite(fit$angle)) {
    return(NULL)
  }
  if (min(fit$axes) <= 0) {
    return(NULL)
  }
  fit
}

# What to say about the groups that got no ellipse. Said out loud, never drawn
# into the figure: a plot that leaves the tool should carry no caption about
# how the tool drew it.
ellipse_skip_message <- function(groups) {
  names <- as.character(groups)
  names <- names[nzchar(trimws(names))]
  if (length(names) == 0) {
    return("")
  }
  one <- length(names) == 1
  sprintf(
    paste0(
      "No ellipse was drawn for %s %s: %s points have no spread in one direction ",
      "-- they fall on a line, or two samples share the same position -- so ",
      "there is no enclosing ellipse to fit. The points themselves are unaffected."
    ),
    if (one) "group" else "groups",
    paste(names, collapse = ", "),
    if (one) "its" else "their"
  )
}

.prepare_pca_matrix <- function(data, meta, plot_3d=FALSE) {
  expression_matrix <- .numeric_matrix(data, as.character(meta$sample))
  n_components <- if (plot_3d) 3 else 2
  if (ncol(expression_matrix) < n_components) {
    stop(sprintf("PCA needs at least %d samples for this projection.", n_components), call. = FALSE)
  }

  complete_rows <- rowSums(!is.finite(expression_matrix)) == 0
  complete_matrix <- expression_matrix[complete_rows, , drop = FALSE]
  if (nrow(complete_matrix) < n_components) {
    stop(
      sprintf(
        paste0(
          "PCA cannot be computed because only %d of %d features are complete across all samples; ",
          "the missingness is too high. Impute the data before calling the PCA function."
        ),
        nrow(complete_matrix),
        nrow(expression_matrix)
      ),
      call. = FALSE
    )
  }

  transposed_expression <- t(complete_matrix)
  feature_variance <- apply(transposed_expression, 2, var)
  variable_features <- is.finite(feature_variance) & feature_variance > 0
  transposed_expression <- transposed_expression[, variable_features, drop = FALSE]
  if (ncol(transposed_expression) < n_components) {
    stop(
      sprintf(
        "PCA needs at least %d complete, non-constant features; only %d remain after filtering.",
        n_components,
        ncol(transposed_expression)
      ),
      call. = FALSE
    )
  }
  list(matrix = transposed_expression, n_components = n_components)
}

resolve_feature_scaling <- function(scaling = "auto", method = "PCA") {
  # `centered` subtracts each feature's mean across samples and stops there, so a
  # feature contributes in proportion to its variance. `unit_variance` also
  # divides by the standard deviation, giving every feature equal weight.
  #
  # `auto` keeps each method's established default: PCA on the centred matrix,
  # UMAP and t-SNE on unit-variance features because both read distances and are
  # sensitive to feature scale. The two answer different questions, so a run that
  # mixes them without saying which was used is not reproducible.
  requested <- tolower(trimws(as.character(scaling %||% "auto")))
  if (requested %in% c("centered", "centred")) return("centered")
  if (requested %in% c("unit_variance", "scaled")) return("unit_variance")
  if (requested != "auto") {
    stop("Unsupported scaling. Choose 'auto', 'centered', or 'unit_variance'.", call. = FALSE)
  }
  if (tolower(trimws(as.character(method %||% "PCA"))) == "pca") "centered" else "unit_variance"
}

pca_scores <- function(data, meta, plot_3d=FALSE, scaling="auto") {
  # The PCA coordinates pca_plot draws, as a table: one row per sample with PC1,
  # PC2 (and PC3 with plot_3d), sample and condition. The explained variance of
  # each component, in percent of the total, is attr(, "explained_variance").
  # The sign of a component is arbitrary and may differ between implementations.
  prepared <- .prepare_pca_matrix(data, meta, plot_3d = plot_3d)
  n_components <- prepared$n_components
  unit_variance <- resolve_feature_scaling(scaling, method = "PCA") == "unit_variance"
  pca <- prcomp(prepared$matrix, rank. = n_components, scale. = unit_variance)
  coordinates <- pca$x[, seq_len(n_components), drop = FALSE]
  scores <- as.data.frame(coordinates, stringsAsFactors = FALSE)
  scores$sample <- rownames(coordinates)
  scores$condition <- as.character(meta$condition[match(scores$sample, as.character(meta$sample))])
  rownames(scores) <- NULL
  attr(scores, "explained_variance") <- (pca$sdev^2 / sum(pca$sdev^2) * 100)[seq_len(n_components)]
  scores
}

pca_plot <- function(data, meta, header=TRUE, legend=TRUE, dot_size=3, width_cm=20, height_cm=10, dpi=100, plot_colors=NULL, plot_3d=FALSE, add_ellipses=FALSE, scaling="auto") {
  table <- pca_scores(data, meta, plot_3d = plot_3d, scaling = scaling)
  n_components <- if (plot_3d) 3 else 2
  scores <- as.matrix(table[, paste0("PC", seq_len(n_components)), drop = FALSE])
  rownames(scores) <- table$sample
  explained_variance <- attr(table, "explained_variance")

  conditions <- as.character(meta$condition[match(rownames(scores), meta$sample)])
  condition_levels <- unique(conditions)
  condition_colors <- setNames(
    .plot_colors(length(condition_levels), plot_colors),
    condition_levels
  )
  point_colors <- unname(condition_colors[conditions])

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  if (plot_3d) {
    .require_pkg("scatterplot3d")
    scatterplot3d::scatterplot3d(
      scores[, 1],
      scores[, 2],
      scores[, 3],
      color = point_colors,
      pch = 16,
      cex.symbols = dot_size / 3,
      xlab = sprintf("PC1 - %.2f%%", explained_variance[1]),
      ylab = sprintf("PC2 - %.2f%%", explained_variance[2]),
      zlab = sprintf("PC3 - %.2f%%", explained_variance[3]),
      main = if (header) "3D PCA Plot" else ""
    )
  } else {
    plot(
      scores[, 1],
      scores[, 2],
      col = point_colors,
      pch = 16,
      cex = dot_size / 3,
      xlab = sprintf("PC1 - %.2f%% variance", explained_variance[1]),
      ylab = sprintf("PC2 - %.2f%% variance", explained_variance[2]),
      main = if (header) "PCA Plot" else "",
      bty = "l"
    )

    if (add_ellipses) {
      skipped_ellipses <- character(0)
      for (condition in condition_levels) {
        condition_scores <- scores[conditions == condition, 1:2, drop = FALSE]

        ellipse <- fitted_group_ellipse(condition_scores)
        if (is.null(ellipse)) {
          skipped_ellipses <- c(skipped_ellipses, condition)
          next
        }
        angles <- seq(0, 2 * pi, length.out = 200)
        rotation <- matrix(
          c(
            cos(ellipse$angle * pi / 180), -sin(ellipse$angle * pi / 180),
            sin(ellipse$angle * pi / 180), cos(ellipse$angle * pi / 180)
          ),
          nrow = 2,
          byrow = TRUE
        )
        outline <- rotation %*% rbind(
          ellipse$axes[1] * cos(angles),
          ellipse$axes[2] * sin(angles)
        )
        polygon(
          outline[1, ] + ellipse$center[1],
          outline[2, ] + ellipse$center[2],
          border = condition_colors[condition],
          col = grDevices::adjustcolor(condition_colors[condition], alpha.f = 0.15)
        )
        points(
          condition_scores[, 1],
          condition_scores[, 2],
          col = condition_colors[condition],
          pch = 16,
          cex = dot_size / 3
        )
      }
      if (length(skipped_ellipses) > 0) {
        warning(ellipse_skip_message(skipped_ellipses), call. = FALSE)
      }
    }
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = condition_levels,
      col = condition_colors,
      pch = 16,
      title = "Condition",
      bty = "n"
    )
  }

  .plot_result()
}

pca_plot_interactive <- function(data, meta, plot_colors=NULL, header=TRUE, legend=TRUE, dot_size=8, plot_3d=FALSE, add_ellipses=FALSE) {
  .require_pkg("plotly")

  prepared <- .prepare_pca_matrix(data, meta, plot_3d = plot_3d)
  transposed_expression <- prepared$matrix
  n_components <- prepared$n_components
  pca <- prcomp(transposed_expression, rank. = n_components)
  explained_variance <- pca$sdev^2 / sum(pca$sdev^2) * 100

  scores <- as.data.frame(pca$x[, seq_len(n_components), drop = FALSE])
  scores$sample <- rownames(scores)
  scores$condition <- meta$condition[match(scores$sample, meta$sample)]

  colors <- .plot_colors(length(unique(scores$condition)), plot_colors)
  hover_text <- paste0(
    "Sample: ", scores$sample,
    "<br>Condition: ", scores$condition
  )

  if (plot_3d) {
    fig <- plotly::plot_ly(
      scores,
      x = ~PC1,
      y = ~PC2,
      z = ~PC3,
      color = ~condition,
      colors = colors,
      text = hover_text,
      hoverinfo = "text",
      type = "scatter3d",
      mode = "markers",
      marker = list(size = dot_size, opacity = 0.8)
    )
    fig <- plotly::layout(
      fig,
      title = if (header) "3D PCA Plot" else NULL,
      showlegend = legend,
      legend = list(title = list(text = "Condition")),
      scene = list(
        xaxis = list(title = sprintf("PC1 - %.2f%%", explained_variance[1])),
        yaxis = list(title = sprintf("PC2 - %.2f%%", explained_variance[2])),
        zaxis = list(title = sprintf("PC3 - %.2f%%", explained_variance[3])),
        aspectmode = "cube"  # the same fixed box as the application (2026-10-09)
      )
    )
    return(fig)
  }

  fig <- plotly::plot_ly(
    scores,
    x = ~PC1,
    y = ~PC2,
    color = ~condition,
    colors = colors,
    text = hover_text,
    hoverinfo = "text",
    type = "scatter",
    mode = "markers",
    marker = list(size = dot_size, opacity = 0.8)
  )

  if (add_ellipses) {
    condition_levels <- unique(scores$condition)
    skipped_ellipses <- character(0)
    for (i in seq_along(condition_levels)) {
      condition <- condition_levels[i]
      subset <- scores[scores$condition == condition, c("PC1", "PC2"), drop = FALSE]

      ellipse <- fitted_group_ellipse(subset)
      if (is.null(ellipse)) {
        skipped_ellipses <- c(skipped_ellipses, condition)
        next
      }
      angles <- seq(0, 2 * pi, length.out = 200)
      angle <- ellipse$angle * pi / 180
      x <- ellipse$axes[1] * cos(angles)
      y <- ellipse$axes[2] * sin(angles)
      ellipse_x <- cos(angle) * x - sin(angle) * y + ellipse$center[1]
      ellipse_y <- sin(angle) * x + cos(angle) * y + ellipse$center[2]

      fig <- plotly::add_trace(
        fig,
        x = ellipse_x,
        y = ellipse_y,
        type = "scatter",
        mode = "lines",
        fill = "toself",
        fillcolor = grDevices::adjustcolor(colors[i], alpha.f = 0.15),
        line = list(color = colors[i], width = 1),
        hoverinfo = "skip",
        showlegend = FALSE,
        inherit = FALSE
      )
    }
    if (length(skipped_ellipses) > 0) {
      warning(ellipse_skip_message(skipped_ellipses), call. = FALSE)
    }
  }

  plotly::layout(
    fig,
    title = if (header) "PCA Plot" else NULL,
    xaxis = list(title = sprintf("PC1 - %.2f%% variance", explained_variance[1])),
    yaxis = list(title = sprintf("PC2 - %.2f%% variance", explained_variance[2])),
    showlegend = legend,
    legend = list(title = list(text = "Condition"))
  )
}

abundance_axis_label <- function(workflow, centered = FALSE) {
  # `robust_site_median` phosphoprotein aggregation centres every site on its own
  # across-sample median, so those values carry a ratio to that median rather
  # than an intensity. Every other phosprot mode, and both other workflows, hold
  # real abundances.
  if (isTRUE(centered)) {
    paste("log10", workflow, "Ratio to Site Median")
  } else {
    paste("log10", workflow, "Intensity")
  }
}

abundance_plot <- function(data, meta, workflow="Protein", plot_colors=NULL, width_cm=20, height_cm=10, dpi=300, legend=TRUE, header=TRUE, data_scale="log2", centered=FALSE) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  if (tolower(trimws(data_scale)) == "log2") {
    data <- inverse_log2_transform_data(data, meta)
  }
  key_col <- .workflow_col(workflow)
  conditions <- unique(meta$condition)
  colors <- .plot_colors(length(conditions), plot_colors)

  ranked_values <- lapply(conditions, function(condition) {
    columns <- meta$sample[meta$condition == condition]
    # log10 of the value, with no pseudocount: the axis names the quantity, so
    # log10(x + 1) would plot something else. Non-positive means have no
    # logarithm and are dropped by the is.finite filter below.
    means <- rowMeans(.numeric_matrix(data, columns), na.rm = TRUE)
    means[!is.na(means) & means <= 0] <- NA_real_
    values <- log10(means)
    sort(values[is.finite(values)], decreasing = TRUE)
  })

  x_max <- max(c(1L, lengths(ranked_values)))
  observed <- unlist(ranked_values)
  y_range <- if (length(observed)) range(observed) else c(0, 1)

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  plot(
    NA,
    xlim = c(1, x_max),
    ylim = y_range,
    xlab = paste(workflow, "Rank"),
    ylab = abundance_axis_label(workflow, centered),
    main = if (header) paste("Abundance plot -", workflow) else "",
    bty = "l"
  )

  for (i in seq_along(ranked_values)) {
    points(
      seq_along(ranked_values[[i]]),
      ranked_values[[i]],
      pch = 16,
      cex = 0.45,
      col = colors[i]
    )
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = conditions,
      col = colors,
      pch = 16,
      title = "Condition",
      bty = "n"
    )
  }

  invisible(key_col)
  .plot_result()
}

interactive_abundance_plot <- function(
    data,
    meta,
    condition,
    workflow = "Protein",
    search = NULL,
    max_ptms = 5,
    data_scale = "log2",
    centered = FALSE
) {
  .require_pkg("plotly")

  feature_col <- .workflow_col(workflow)
  sample_columns <- meta$sample[meta$condition == condition]
  data <- .prepare_intensity_data(data, sample_columns, data_scale)
  if (tolower(trimws(data_scale)) == "log2") {
    data <- inverse_log2_transform_data(data, meta[meta$condition == condition, , drop = FALSE])
  }
  # See plot_abundance: log10 of the value, no pseudocount.
  condition_means <- rowMeans(.numeric_matrix(data, sample_columns), na.rm = TRUE)
  condition_means[!is.na(condition_means) & condition_means <= 0] <- NA_real_
  condition_means <- log10(condition_means)

  plot_data <- data.frame(
    Feature = sub(";.*$", "", as.character(data[[feature_col]])),
    log10Intensity = condition_means,
    stringsAsFactors = FALSE
  )
  plot_data <- plot_data[is.finite(plot_data$log10Intensity), , drop = FALSE]

  if (!nrow(plot_data)) {
    return(plotly::layout(
      plotly::plot_ly(x = numeric(), y = numeric(), type = "scatter", mode = "markers"),
      title = paste0("Abundance plot - ", condition, " (", workflow, ")"),
      xaxis = list(title = paste(workflow, "Rank")),
      yaxis = list(title = abundance_axis_label(workflow, centered))
    ))
  }

  if (workflow == "Phosphoprotein") {
    plot_data$site_num <- if ("site_num" %in% names(data)) {
      data$site_num[match(plot_data$Feature, data$Phosphoprotein)]
    } else {
      1
    }

    ptm_values <- if ("PTM_Collapse_keys" %in% names(data)) {
      as.character(data$PTM_Collapse_keys[match(plot_data$Feature, data$Phosphoprotein)])
    } else {
      rep("", nrow(plot_data))
    }

    truncate_ptms <- function(value) {
      sites <- strsplit(value, ";", fixed = TRUE)[[1]]
      displayed <- paste(head(sites, max_ptms), collapse = ";")
      if (length(sites) > max_ptms) paste0(displayed, ";...") else displayed
    }

    plot_data$HoverLabel <- paste0(
      plot_data$Feature,
      " (", plot_data$site_num, " sites)<br>",
      vapply(ptm_values, truncate_ptms, character(1))
    )
  } else {
    plot_data$HoverLabel <- plot_data$Feature
  }

  plot_data <- plot_data[
    order(plot_data$log10Intensity, decreasing = TRUE),
    ,
    drop = FALSE
  ]
  plot_data$Rank <- seq_len(nrow(plot_data))
  search <- search %||% character()
  plot_data$highlight <- plot_data$Feature %in% search
  plot_data$TextLabel <- ifelse(plot_data$highlight, plot_data$Feature, "")

  hover_text <- paste0(
    plot_data$HoverLabel,
    "<br>Rank: ", plot_data$Rank,
    "<br>log10 intensity: ", signif(plot_data$log10Intensity, 4)
  )

  fig <- plotly::plot_ly()
  fig <- plotly::add_markers(
    fig,
    data = plot_data,
    x = ~Rank,
    y = ~log10Intensity,
    text = hover_text,
    hoverinfo = "text",
    marker = list(size = 6, color = "#1f77b4", opacity = 0.8),
    showlegend = FALSE
  )

  highlighted_data <- plot_data[plot_data$highlight, , drop = FALSE]
  if (nrow(highlighted_data)) {
    highlighted_hover <- hover_text[plot_data$highlight]
    fig <- plotly::add_trace(
      fig,
      data = highlighted_data,
      x = ~Rank,
      y = ~log10Intensity,
      text = ~Feature,
      hovertext = highlighted_hover,
      hoverinfo = "text",
      textposition = "top center",
      textfont = list(size = 10, color = "#d62728"),
      type = "scatter",
      mode = "markers+text",
      marker = list(
        size = 8,
        color = "#d62728",
        line = list(color = "black", width = 1)
      ),
      showlegend = FALSE
    )
  }

  plotly::layout(
    fig,
    title = paste0("Abundance plot - ", condition, " (", workflow, ")"),
    xaxis = list(title = paste(workflow, "Rank")),
    yaxis = list(title = abundance_axis_label(workflow, centered)),
    hovermode = "closest"
  )
}

sample_correlation_matrix <- function(data, meta, id=TRUE, data_scale="log2") {
  # The Pearson correlations between samples that corr_plot colours. Rows and
  # columns are the display names (condition_n, with the sample id when id=TRUE)
  # in metadata order; corr_plot then reorders them by clustering. Each pair uses
  # the features measured in both samples; a sample with no values is left out.
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  meta <- .sample_meta(meta, id = id)
  renamed_data <- .rename_samples(data, meta)
  values <- .numeric_matrix(renamed_data, meta$new_sample)
  values <- values[, colSums(!is.na(values)) > 0, drop=FALSE]
  if (ncol(values) < 2) stop("At least two non-empty sample columns are required for correlation plot.", call.=FALSE)
  correlation_matrix <- suppressWarnings(cor(
    values,
    use = "pairwise.complete.obs",
    method = "pearson"
  ))
  invalid_samples <- vapply(seq_len(ncol(values)), function(i) {
    observed <- values[, i][is.finite(values[, i])]
    length(observed) < 2 || length(unique(observed)) < 2
  }, logical(1))
  correlation_matrix[invalid_samples, ] <- NA_real_
  correlation_matrix[, invalid_samples] <- NA_real_
  correlation_matrix
}

corr_plot <- function(data, meta, method="Matrix", id=TRUE, full_range=FALSE, width=10, height=8, dpi=100, data_scale="log2") {
  correlation_matrix <- sample_correlation_matrix(data, meta, id = id, data_scale = data_scale)
  incomplete <- any(!is.finite(correlation_matrix))
  ordered_indices <- if (incomplete) seq_len(ncol(correlation_matrix)) else hclust(
    as.dist(1 - correlation_matrix), method = "complete"
  )$order
  ordered_correlation <- correlation_matrix[
    ordered_indices,
    ordered_indices,
    drop = FALSE
  ]

  finite <- ordered_correlation[is.finite(ordered_correlation)]
  color_range <- if (full_range || !length(finite)) c(-1, 1) else range(finite)
  if (diff(color_range) == 0) color_range <- c(-1, 1)
  colors <- colorRampPalette(c("#3b4cc0", "white", "#b40426"))(100)

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)

  if (tolower(method) == "matrix") {
    layout(matrix(c(1, 2), nrow = 1), widths = c(16, 2))
    par(mar = c(8, 8, 2, 1))

    image(
      seq_len(ncol(ordered_correlation)),
      seq_len(nrow(ordered_correlation)),
      t(ordered_correlation[nrow(ordered_correlation):1, , drop = FALSE]),
      col = colors,
      zlim = color_range,
      axes = FALSE,
      xlab = "",
      ylab = ""
    )
    axis(1, seq_len(ncol(ordered_correlation)), colnames(ordered_correlation), las = 2, cex.axis = 0.65)
    axis(2, seq_len(nrow(ordered_correlation)), rev(rownames(ordered_correlation)), las = 2, cex.axis = 0.65)
    missing <- which(!is.finite(ordered_correlation), arr.ind=TRUE)
    if (nrow(missing)) text(missing[,2], nrow(ordered_correlation) - missing[,1] + 1, "NA", cex=0.65, col="grey40")
    if (incomplete) mtext("NA: unavailable; clustering skipped (metadata order)", side=1, line=6, cex=0.7)
    box()

    par(mar = c(8, 0.2, 2, 2))
    scale_values <- seq(color_range[1], color_range[2], length.out = 100)
    image(1, scale_values, matrix(scale_values, nrow = 1), col = colors, axes = FALSE)
    axis(4, las = 2)
    mtext("Pearson correlation", side = 4, line = 1.2)
  } else if (tolower(method) == "ellipse") {
    par(mar = c(8, 8, 2, 2))
    n <- nrow(ordered_correlation)
    plot(
      NA,
      xlim = c(0, n),
      ylim = c(0, n),
      axes = FALSE,
      xlab = "",
      ylab = "",
      asp = 1
    )

    axis(1, seq_len(n) - 0.5, colnames(ordered_correlation), las = 2, cex.axis = 0.65)
    axis(2, seq_len(n) - 0.5, rev(rownames(ordered_correlation)), las = 2, cex.axis = 0.65)

    for (i in seq_len(n)) {
      for (j in seq_len(n)) {
        correlation <- ordered_correlation[i, j]
        if (!is.finite(correlation)) {
          text(j - 0.5, n - i + 0.5, "NA", cex=0.65, col="grey40")
          next
        }
        angle <- if (correlation > 0) pi / 4 else -pi / 4
        theta <- seq(0, 2 * pi, length.out = 80)
        x <- 0.45 * cos(theta)
        y <- 0.45 * (1 - abs(correlation)) * sin(theta)
        rotated_x <- cos(angle) * x - sin(angle) * y
        rotated_y <- sin(angle) * x + cos(angle) * y
        polygon(
          rotated_x + j - 0.5,
          rotated_y + n - i + 0.5,
          col = grDevices::adjustcolor(if (correlation > 0) "red" else "blue", alpha.f = 0.6),
          border = NA
        )
      }
    }
    box()
  } else {
    stop("method must be 'Matrix' or 'Ellipse'", call. = FALSE)
  }

  if (incomplete && tolower(method) == "ellipse") mtext("NA: unavailable; clustering skipped (metadata order)", side=1, line=6, cex=0.7)
  .plot_result()
}

# Imputed-value counts. Imputed values enter every test as if measured -- they
# count towards n and the degrees of freedom -- so results carry, per row, how
# many values in each group were imputed (`n_imputed__<group>`) and their total
# (`imputed_values`). `observed` is the matrix before impute_values(), with the
# same rows in the same order; a phosphoprotein table's own site-contribution
# columns are used without it. Mirrors the backend and pip package.

imputed_cell_mask <- function(values, observed) {
  present <- !is.na(.numeric_matrix(values, names(values)))
  before <- .numeric_matrix(observed, names(values))
  states <- matrix(as.integer(is.na(before)), nrow = nrow(values), dimnames = dimnames(before))
  states[!present] <- -1L
  states
}

site_observed_imputed_mask <- function(frame, sample_columns) {
  prefix <- if (any(startsWith(names(frame), "site_measured__"))) "site_measured__" else "site_observed__"
  columns <- paste0(prefix, sample_columns)
  supplied_columns <- paste0("site_supplied__", sample_columns)
  if (!all(c(columns, supplied_columns) %in% names(frame))) return(NULL)
  present <- !is.na(.numeric_matrix(frame, sample_columns))
  measured <- .numeric_matrix(frame, columns)
  supplied <- .numeric_matrix(frame, supplied_columns)
  known <- is.finite(measured) & is.finite(supplied) & supplied > 0 & measured >= 0 & measured <= supplied
  mask <- ifelse(measured == 0, 1L, ifelse(measured < supplied, 2L, 0L))
  mask[!present | !known] <- -1L
  colnames(mask) <- sample_columns
  mask
}

imputed_value_counts <- function(mask, groups) {
  counts <- data.frame(row.names = seq_len(nrow(mask)))
  total <- integer(nrow(mask))
  for (group in names(groups)) {
    values <- mask[, groups[[group]], drop = FALSE]
    for (state in 0:2) {
      category <- c("measured", "fully_imputed", "partially_imputed")[[state + 1]]
      counts[[paste0("n_", category, "__", group)]] <- as.integer(rowSums(values == state))
    }
    column_count <- as.integer(rowSums(values == 1 | values == 2))
    counts[[paste0("n_imputed__", group)]] <- column_count
    total <- total + column_count
  }
  counts$imputed_values <- total
  counts
}

.imputed_counts_for <- function(data, observed, groups) {
  samples <- unique(unlist(groups, use.names = FALSE))
  if (!is.null(observed)) {
    missing_columns <- setdiff(samples, names(observed))
    if (nrow(observed) != nrow(data) || length(missing_columns)) {
      stop(
        "observed must be the pre-imputation matrix of this data: same rows in the same order ",
        "and the sample columns (", length(missing_columns), " sample columns not found).",
        call. = FALSE
      )
    }
    mask <- imputed_cell_mask(data[, samples, drop = FALSE], observed)
  } else {
    mask <- site_observed_imputed_mask(data, samples)
  }
  if (is.null(mask)) return(NULL)
  imputed_value_counts(mask, groups)
}

.volcano_stats <- function(
    data,
    meta,
    condition1,
    condition2,
    label_col,
    paired = "Unpaired",
    uncorrected = FALSE,
    extras = character(),
    test_type = NULL,
    control1_columns = NULL,
    control2_columns = NULL,
    observed = NULL,
    control_names = NULL
) {
  condition1_columns <- as.character(meta$sample[meta$condition == condition1])
  condition2_columns <- as.character(meta$sample[meta$condition == condition2])
  if (is.null(test_type)) {
    is_paired <- paired_test_enabled(paired)
    variance <- "pooled"
  } else {
    resolved <- resolve_test_type(test_type)
    is_paired <- resolved$paired
    variance <- resolved$model
  }
  if (is_paired) {
    paired_columns <- paired_sample_columns(meta, condition1, condition2)
    condition1_columns <- paired_columns$condition1
    condition2_columns <- paired_columns$condition2
  }
  columns <- unique(c(label_col, condition1_columns, condition2_columns, extras))
  filtered_data <- data[, columns, drop = FALSE]
  count_groups <- list(condition1_columns, condition2_columns)
  names(count_groups) <- c(condition1, condition2)
  if (length(control_names) == 2 && length(control1_columns) && length(control2_columns)) {
    count_groups[[control_names[1]]] <- as.character(control1_columns)
    count_groups[[control_names[2]]] <- as.character(control2_columns)
  }
  imputed_counts <- .imputed_counts_for(data, observed, count_groups)

  x_data <- .numeric_matrix(filtered_data, condition1_columns)
  y_data <- .numeric_matrix(filtered_data, condition2_columns)
  if (is_paired) {
    pair_mask <- is.finite(x_data) & is.finite(y_data)
    valid <- rowSums(pair_mask) >= 2
  } else {
    valid <- rowSums(!is.na(x_data)) >= 2 & rowSums(!is.na(y_data)) >= 2
  }
  for (columns in list(control1_columns, control2_columns)) {
    if (is.null(columns) || !length(columns)) next
    valid <- valid & rowSums(is.finite(.numeric_matrix(data, as.character(columns)))) >= 2
  }
  if (!any(valid)) {
    stop(
      if (is_paired) {
        "No rows have enough paired values for the selected comparison."
      } else {
        "No rows have enough replicate values for the selected comparison."
      },
      call. = FALSE
    )
  }

  filtered_data <- filtered_data[valid, , drop = FALSE]
  if (!is.null(imputed_counts)) imputed_counts <- imputed_counts[valid, , drop = FALSE]
  x_data <- x_data[valid, , drop = FALSE]
  y_data <- y_data[valid, , drop = FALSE]
  if (is_paired) {
    pair_mask <- is.finite(x_data) & is.finite(y_data)
    differences <- x_data - y_data
    differences[!pair_mask] <- NA_real_
    n_pairs <- rowSums(pair_mask)
    log2fc <- rowMeans(differences, na.rm = TRUE)
  } else {
    log2fc <- rowMeans(x_data, na.rm = TRUE) - rowMeans(y_data, na.rm = TRUE)
  }

  # Welch needs whole-column arithmetic, so it is computed vectorised rather
  # than through the row-wise path below, which is kept byte-identical for the
  # pooled and paired cases it already served.
  # Control components: the control means carry their own uncertainty, which the
  # two-group standard error below cannot see once their means have been
  # subtracted. See volcano_data_f_control.
  control_components <- list()
  for (columns in list(control1_columns, control2_columns)) {
    if (is.null(columns) || !length(columns)) next
    values <- .numeric_matrix(data, as.character(columns))[valid, , drop = FALSE]
    control_components[[length(control_components) + 1]] <- .variance_and_count(values)
  }

  vectorised <- variance == "welch" || length(control_components)
  if (vectorised) {
    counts1 <- rowSums(!is.na(x_data))
    counts2 <- rowSums(!is.na(y_data))
    if (!is_paired) {
      variances1 <- apply(x_data, 1, stats::var, na.rm = TRUE)
      variances2 <- apply(y_data, 1, stats::var, na.rm = TRUE)
      if (variance == "welch" || length(control_components)) {
        components <- c(
          list(
            list(variance = variances1, count = counts1),
            list(variance = variances2, count = counts2)
          ),
          control_components
        )
        propagated <- .satterthwaite(components)
        standard_error <- propagated$se
        degrees <- propagated$dof
      }
      effect <- log2fc
    } else {
      counts <- rowSums(pair_mask)
      variance_differences <- apply(differences, 1, stats::var, na.rm = TRUE)
      residual_dof <- counts - 1
      paired_variance <- variance_differences
      prior_dof <- 0
      if (length(control_components)) {
        components <- c(
          list(list(variance = paired_variance, count = counts)),
          control_components
        )
        propagated <- .satterthwaite(components)
        standard_error <- propagated$se
        degrees <- propagated$dof + prior_dof
      } else {
        standard_error <- sqrt(paired_variance / counts)
        degrees <- residual_dof + prior_dof
      }
      effect <- log2fc
    }
    # Match SciPy's zero-SE arithmetic; 0/0 remains unavailable.
    statistic <- effect / standard_error
    pvalues <- 2 * stats::pt(abs(statistic), degrees, lower.tail = FALSE)
  } else {
  pvalues <- vapply(seq_len(nrow(filtered_data)), function(index) {
    values1 <- x_data[index, ]
    values2 <- y_data[index, ]

    if (!is_paired) {
      values1 <- values1[is.finite(values1)]
      values2 <- values2[is.finite(values2)]
      # Computed directly rather than via t.test(): t.test() aborts with
      # "data are essentially constant" on zero- or near-zero-variance rows,
      # which kills the whole comparison. The Python/backend implementations
      # return a p-value for those rows, so mirror their arithmetic exactly.
      n1 <- length(values1)
      n2 <- length(values2)
      pooled_var <- ((n1 - 1) * var(values1) + (n2 - 1) * var(values2)) / (n1 + n2 - 2)
      standard_error <- sqrt(pooled_var * (1 / n1 + 1 / n2))
      mean_difference <- mean(values2) - mean(values1)
      2 * pt(abs(mean_difference / standard_error), n1 + n2 - 2, lower.tail = FALSE)
    } else {
      complete <- is.finite(values1) & is.finite(values2)
      pair_differences <- values2[complete] - values1[complete]
      # Use the paired t statistic directly, as Python/backend do. t.test's
      # near-constant-data rejection would abort otherwise valid comparisons.
      mean_difference <- mean(pair_differences)
      difference_variance <- var(pair_differences)
      standard_error <- sqrt(difference_variance / length(pair_differences))
      2 * pt(abs(mean_difference / standard_error),
             length(pair_differences) - 1, lower.tail = FALSE)
    }
  }, numeric(1))
  }

  # Every variance component constant: the standard error is zero and the test
  # undefined, so the row gets no p-value ("Unavailable") instead of p = 0.
  variation_parts <- if (is_paired) list(round(differences, 9)) else list(x_data, y_data)
  for (columns in list(control1_columns, control2_columns)) {
    if (is.null(columns) || !length(columns)) next
    variation_parts[[length(variation_parts) + 1]] <-
      .numeric_matrix(data, as.character(columns))[valid, , drop = FALSE]
  }
  pvalues[without_variation(variation_parts)] <- NA_real_

  # `adj_pval` is always Benjamini-Hochberg; `selected_pval` is the one
  # significance is called on (raw when `uncorrected`), as in the web app.
  adjusted_pvalues <- pvalues
  finite <- is.finite(pvalues)
  adjusted_pvalues[finite] <- p.adjust(pvalues[finite], "BH")
  output_columns <- c(label_col, extras[extras %in% names(filtered_data)])
  output <- filtered_data[, output_columns, drop = FALSE]
  output$log2FC <- log2fc
  output$pval <- pvalues
  output$adj_pval <- adjusted_pvalues
  output$selected_pval <- if (uncorrected) pvalues else adjusted_pvalues
  # A variance warning is independent of whether the test has a finite p-value.
  # Paired tests: the variation that matters is that of the differences.
  output$zero_variance <- if (is_paired) {
    constant_differences(differences)
  } else {
    constant_within_group(x_data) | constant_within_group(y_data)
  }
  if (is_paired) output$n_pairs <- as.integer(n_pairs)
  attr(output, "imputed_counts") <- imputed_counts
  output
}

.resolve_volcano_label_column <- function(data, workflow, label_column = NULL) {
  if (!is.null(label_column)) {
    label_column <- as.character(label_column)
    if (length(label_column) != 1L || !label_column %in% names(data)) {
      stop(
        paste0("label_column '", paste(label_column, collapse = ""), "' was not found in data."),
        call. = FALSE
      )
    }
    return(label_column)
  }
  .workflow_col(workflow)
}

volcano_data_f <- function(
    data,
    meta,
    condition1,
    condition2,
    in_pval = 0.05,
    in_log2fc = 1,
    workflow = "Protein",
    paired = "Unpaired",
    uncorrected = FALSE,
    test_type = NULL,
    label_column = NULL,
    observed = NULL,
    # These follow `label_column` and `observed` so the first twelve positional
    # slots match the pip package, which reaches the same analysis through
    # `volcano_data_f_control`.
    control1_columns = NULL,
    control2_columns = NULL,
    control_names = NULL
) {
  if (identical(condition1, condition2)) {
    stop("Please select two different conditions.", call. = FALSE)
  }
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  label_col <- .resolve_volcano_label_column(data, workflow, label_column)
  extra_columns <- if (workflow == "Phosphoprotein") {
    intersect(c("site_num", "PTM_Collapse_keys"), names(data))
  } else {
    character()
  }

  output <- .volcano_stats(
    data,
    meta,
    condition1,
    condition2,
    label_col,
    paired,
    uncorrected,
    extra_columns,
    test_type,
    control1_columns,
    control2_columns,
    observed,
    control_names
  )
  imputed_counts <- attr(output, "imputed_counts")
  attr(output, "imputed_counts") <- NULL
  output$significance <- ifelse(
    output$selected_pval < in_pval & output$log2FC > in_log2fc,
    "Upregulated",
    ifelse(
      output$selected_pval < in_pval & output$log2FC < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )
  output$significance[!is.finite(output$pval)] <- "Unavailable"
  output$neg_log10_selected_pval <- -log10(pmax(output$selected_pval, 1e-300))
  if (!is.null(imputed_counts)) {
    for (column in names(imputed_counts)) output[[column]] <- imputed_counts[[column]]
  }
  output
}

volcano_data_f_control <- function(data, meta, condition1, condition2, condition1_control, condition2_control, in_pval=0.05, in_log2fc=1, workflow="Protein", paired="Unpaired", uncorrected=FALSE, test_type=NULL, label_column=NULL, observed=NULL) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  # The four conditions must be distinct, as in the web app: a control shared by
  # both sides would enter the standard error twice.
  named <- trimws(as.character(c(condition1, condition1_control, condition2, condition2_control)))
  if (length(unique(named)) != length(named)) {
    stop("Control-corrected volcano analysis requires four distinct conditions; ",
         "an experimental condition cannot be used as its own control.", call. = FALSE)
  }
  condition1_columns <- meta$sample[meta$condition == condition1]
  condition2_columns <- meta$sample[meta$condition == condition2]
  control1_columns <- meta$sample[meta$condition == condition1_control]
  control2_columns <- meta$sample[meta$condition == condition2_control]

  normalized_data <- data
  normalized_data[condition1_columns] <- sweep(
    .numeric_matrix(normalized_data, condition1_columns),
    1,
    rowMeans(.numeric_matrix(normalized_data, control1_columns), na.rm = TRUE),
    "-"
  )
  normalized_data[condition2_columns] <- sweep(
    .numeric_matrix(normalized_data, condition2_columns),
    1,
    rowMeans(.numeric_matrix(normalized_data, control2_columns), na.rm = TRUE),
    "-"
  )

  # Subtracting each control mean shifts a row by a constant, which leaves the
  # test groups' own variance untouched -- so the two-group standard error inside
  # volcano_data_f omits the uncertainty of the control means entirely. On a
  # complete null that produced a 12.75% false-positive rate against a nominal 5%.
  # The control groups are propagated as additional independent components.
  output <- volcano_data_f(
    normalized_data,
    meta,
    condition1,
    condition2,
    in_pval,
    in_log2fc,
    workflow,
    paired,
    uncorrected,
    test_type = test_type,
    control1_columns = control1_columns,
    control2_columns = control2_columns,
    label_column = label_column,
    observed = observed,
    control_names = c(condition1_control, condition2_control)
  )
  output
}

.volcano_label_col <- function(volcano_df) {
  if ("Phosphoprotein" %in% names(volcano_df)) return("Phosphoprotein")
  if ("ProteinNames" %in% names(volcano_df)) return("ProteinNames")
  "PTM_Collapse_key"
}

.volcano_hover_text <- function(volcano_df, label_col, max_chars = 100) {
  hover_text <- as.character(volcano_df[[label_col]])

  if (label_col == "Phosphoprotein") {
    if ("site_num" %in% names(volcano_df)) {
      hover_text <- paste0(
        hover_text,
        " (", volcano_df$site_num, " sites)"
      )
    }

    if ("PTM_Collapse_keys" %in% names(volcano_df)) {
      ptm_text <- as.character(volcano_df$PTM_Collapse_keys)
      too_long <- nchar(ptm_text) > max_chars
      ptm_text[too_long] <- paste0(
        substr(ptm_text[too_long], 1, max_chars),
        " ..."
      )
      hover_text <- paste0(hover_text, "<br>", ptm_text)
    }
  }

  hover_text
}

.volcano_plot_base <- function(
    volcano_df,
    condition1,
    condition2,
    in_pval,
    in_log2fc,
    uncorrected,
    highlight_terms = NULL,
    max_chars = 100
) {
  .require_pkg("plotly")

  label_col <- .volcano_label_col(volcano_df)
  color_mapping <- c(
    Downregulated = "blue",
    `Not significant` = "gray",
    Upregulated = "red"
  )

  y_threshold <- -log10(in_pval)
  max_y <- max(y_threshold, volcano_df$neg_log10_selected_pval, na.rm = TRUE)
  x_range <- range(volcano_df$log2FC, na.rm = TRUE)

  normalized_terms <- if (is.null(highlight_terms)) {
    character()
  } else {
    tolower(sub("_.*$", "", as.character(highlight_terms)))
  }

  normalized_labels <- vapply(
    strsplit(as.character(volcano_df[[label_col]]), ";", fixed = TRUE),
    function(values) {
      paste(tolower(sub("_.*$", "", values)), collapse = ";")
    },
    character(1)
  )
  highlighted <- vapply(
    strsplit(normalized_labels, ";", fixed = TRUE),
    function(values) any(values %in% normalized_terms),
    logical(1)
  )

  fig <- plotly::plot_ly()

  for (significance in names(color_mapping)) {
    significance_rows <- volcano_df$significance == significance

    for (highlight_state in c(FALSE, TRUE)) {
      rows <- significance_rows & highlighted == highlight_state
      if (!any(rows)) next

      subset <- volcano_df[rows, , drop = FALSE]
      hover_text <- .volcano_hover_text(subset, label_col, max_chars)
      trace_name <- if (highlight_state) {
        paste0(significance, " (highlighted)")
      } else {
        significance
      }

      fig <- plotly::add_trace(
        fig,
        data = subset,
        x = ~log2FC,
        y = ~neg_log10_selected_pval,
        type = "scatter",
        mode = "markers",
        text = hover_text,
        hoverinfo = "text",
        name = trace_name,
        marker = list(
          color = unname(color_mapping[significance]),
          size = if (highlight_state) 8 else 5,
          line = list(
            color = if (highlight_state) "lime" else unname(color_mapping[significance]),
            width = if (highlight_state) 3 else 0
          )
        ),
        inherit = FALSE
      )
    }
  }

  shapes <- list(
    list(
      type = "line",
      x0 = in_log2fc,
      x1 = in_log2fc,
      y0 = 0,
      y1 = max_y,
      line = list(color = "black", dash = "dash")
    ),
    list(
      type = "line",
      x0 = -in_log2fc,
      x1 = -in_log2fc,
      y0 = 0,
      y1 = max_y,
      line = list(color = "black", dash = "dash")
    ),
    list(
      type = "line",
      x0 = x_range[1],
      x1 = x_range[2],
      y0 = y_threshold,
      y1 = y_threshold,
      line = list(color = "black", dash = "dash")
    )
  )

  plotly::layout(
    fig,
    title = paste(condition1, "vs", condition2),
    xaxis = list(
      title = paste0("log2 fold change (", condition1, " - ", condition2, ")")
    ),
    yaxis = list(
      title = if (uncorrected) "-log10 p-value" else "-log10 adj. p-value"
    ),
    shapes = shapes,
    hovermode = "closest",
    legend = list(title = list(text = "Significance"))
  )
}

volcano_plot <- function(
    volcano_df,
    condition1,
    condition2,
    in_pval = 0.05,
    in_log2fc = 1,
    uncorrected = FALSE,
    max_chars = 100
) {
  .volcano_plot_base(
    volcano_df,
    condition1,
    condition2,
    in_pval,
    in_log2fc,
    uncorrected,
    max_chars = max_chars
  )
}

volcano_plot_h <- function(
    volcano_df,
    condition1,
    condition2,
    in_pval = 0.05,
    in_log2fc = 1,
    uncorrected = FALSE,
    highlight_terms = NULL,
    max_chars = 100
) {
  .volcano_plot_base(
    volcano_df,
    condition1,
    condition2,
    in_pval,
    in_log2fc,
    uncorrected,
    highlight_terms = highlight_terms,
    max_chars = max_chars
  )
}

anova_data_f <- function(
    data,
    meta,
    conditions = NULL,
    in_pval = 0.05,
    workflow = "Protein",
    uncorrected = FALSE,
    observed = NULL
) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  label_col <- .workflow_col(workflow)
  conditions <- conditions %||% unique(na.omit(meta$condition))
  if (length(conditions) < 2) {
    stop("ANOVA needs at least two conditions.", call. = FALSE)
  }

  condition_columns <- lapply(conditions, function(condition) {
    as.character(meta$sample[meta$condition == condition])
  })
  names(condition_columns) <- conditions
  if (any(lengths(condition_columns) < 2)) {
    stop("Each ANOVA condition needs at least two sample columns.", call. = FALSE)
  }

  sample_columns <- unlist(condition_columns, use.names = FALSE)
  valid <- Reduce(`&`, lapply(condition_columns, function(columns) {
    rowSums(!is.na(data[, columns, drop = FALSE])) >= 2
  }))

  extra_columns <- if (workflow == "Phosphoprotein") {
    c(
      head(intersect(c("Gene_group", "GeneNames"), names(data)), 1),
      intersect(c("site_num", "PTM_Collapse_keys"), names(data))
    )
  } else {
    character()
  }
  imputed_counts <- .imputed_counts_for(data, observed, condition_columns)
  if (!is.null(imputed_counts)) imputed_counts <- imputed_counts[valid, , drop = FALSE]
  output <- data[
    valid,
    unique(c(label_col, sample_columns, extra_columns)),
    drop = FALSE
  ]
  if (!nrow(output)) {
    stop("No rows have enough replicate values for ANOVA.", call. = FALSE)
  }

  f_statistics <- numeric(nrow(output))
  pvalues <- numeric(nrow(output))
  for (row_index in seq_len(nrow(output))) {
    values <- lapply(condition_columns, function(columns) {
      row_values <- as.numeric(output[row_index, columns])
      row_values[is.finite(row_values)]
    })
    means <- vapply(values, mean, numeric(1))
    sample_sizes <- lengths(values)
    grand_mean <- sum(means * sample_sizes) / sum(sample_sizes)
    between_sum_squares <- sum(sample_sizes * (means - grand_mean)^2)
    within_sum_squares <- sum(vapply(seq_along(values), function(index) {
      sum((values[[index]] - means[index])^2)
    }, numeric(1)))

    numerator_df <- length(values) - 1
    denominator_df <- sum(sample_sizes) - length(values)
    f_statistics[row_index] <-
      (between_sum_squares / numerator_df) /
      (within_sum_squares / denominator_df)
    pvalues[row_index] <- stats::pf(
      f_statistics[row_index],
      numerator_df,
      denominator_df,
      lower.tail = FALSE
    )
  }

  # A row constant throughout yields NaN: the F test is undefined. Drop those
  # rather than carrying all-NA rows into the result, so they do not count
  # towards the BH denominator. A row constant within every condition but
  # different between them gets F = Inf; it stays, flagged zero_variance below,
  # but gets no p-value -- the same rule the volcano applies to rows without
  # variation. Matches the Python implementations.
  computable <- is.finite(pvalues)
  output <- output[computable, , drop = FALSE]
  if (!is.null(imputed_counts)) imputed_counts <- imputed_counts[computable, , drop = FALSE]
  f_statistics <- f_statistics[computable]
  pvalues <- pvalues[computable]

  # No variation within any condition: an infinite F says only that the
  # variance is absent, not that the difference is large. No p-value, out of
  # the BH family, shown as Unavailable.
  zero_variance <- Reduce(`&`, lapply(condition_columns, function(columns) {
    constant_within_group(output[, columns, drop = FALSE])
  }))
  pvalues[zero_variance] <- NA_real_

  output$f_statistic <- f_statistics
  output$pval <- pvalues
  output$adj_pval <- p.adjust(pvalues, "BH")
  output$selected_pval <- if (uncorrected) pvalues else output$adj_pval
  output$significance <- ifelse(
    is.na(pvalues),
    "Unavailable",
    ifelse(output$selected_pval < in_pval, "Significant", "Not significant")
  )
  output$neg_log10_selected_pval <- -log10(
    pmax(output$selected_pval, .Machine$double.xmin)
  )
  output$zero_variance <- zero_variance

  for (condition in conditions) {
    output[[paste0("mean_", condition)]] <- rowMeans(
      .numeric_matrix(output, condition_columns[[condition]]),
      na.rm = TRUE
    )
  }
  if (!is.null(imputed_counts)) {
    for (column in names(imputed_counts)) output[[column]] <- imputed_counts[[column]]
  }

  # Benjamini-Hochberg ties many features to the same adjusted p, so ordering on
  # it alone leaves the order within those groups to whichever sort the language
  # happens to use -- the Python package returned a different one. Raw p then the
  # label makes the order identical across all three pipelines.
  label_col <- tryCatch(get("_auto_label_col")(output), error = function(e) NULL)
  if (is.null(label_col)) {
    output[order(output$selected_pval, output$pval), , drop = FALSE]
  } else {
    output[order(output$selected_pval, output$pval, output[[label_col]]), , drop = FALSE]
  }
}

# The p-value column significance is called on: `selected_pval`, or `adj_pval` in older tables.
.significance_pval_column <- function(table) {
  for (column in c("selected_pval", "adj_pval")) if (column %in% names(table)) return(column)
  NULL
}

anova_cluster_data <- function(
    anova_df,
    meta,
    n_clusters = 4,
    in_pval = 0.05,
    z_score = TRUE,
    only_significant = TRUE,
    cluster_method = "average",
    cluster_metric = "euclidean",
    cluster_col = "cluster"
) {
  if (n_clusters < 1) {
    stop("n_clusters must be at least 1.", call. = FALSE)
  }

  sample_columns <- intersect(as.character(meta$sample), names(anova_df))
  if (!length(sample_columns)) {
    stop("No sample columns from meta were found in anova_df.", call. = FALSE)
  }

  cluster_data <- if (only_significant && !is.null(.significance_pval_column(anova_df))) {
    anova_df[anova_df[[.significance_pval_column(anova_df)]] < in_pval, , drop = FALSE]
  } else {
    anova_df
  }
  if (!nrow(cluster_data)) {
    cluster_data[[cluster_col]] <- integer(0)
    first_column <- names(cluster_data)[1]
    return(cluster_data[
      ,
      c(first_column, cluster_col, setdiff(names(cluster_data), c(first_column, cluster_col))),
      drop = FALSE
    ])
  }

  matrix <- .numeric_matrix(cluster_data, sample_columns)
  if (nrow(matrix) > 1) {
    dropped_info <- .drop_incomplete_features(matrix, "ANOVA clustering")
    matrix <- dropped_info$matrix
    cluster_data <- cluster_data[dropped_info$kept, , drop = FALSE]
    .warn_dropped_features(dropped_info$dropped, dropped_info$total)
  }
  if (z_score) matrix <- row_zscore(matrix)

  if (nrow(matrix) <= 1) {
    cluster_data[[cluster_col]] <- 1
    return(cluster_data)
  }

  hierarchy <- hclust(
    dist(matrix, method = cluster_metric),
    method = cluster_method
  )
  row_order <- hierarchy$order
  raw_clusters <- cutree(hierarchy, k = min(n_clusters, nrow(matrix)))
  ordered_clusters <- raw_clusters[row_order]

  cluster_map <- setNames(
    seq_along(unique(ordered_clusters)),
    unique(ordered_clusters)
  )
  relabeled_clusters <- unname(cluster_map[as.character(ordered_clusters)])

  cluster_data <- cluster_data[row_order, , drop = FALSE]
  cluster_data[[cluster_col]] <- relabeled_clusters
  first_column <- names(cluster_data)[1]
  cluster_data <- cluster_data[
    ,
    c(first_column, cluster_col, setdiff(names(cluster_data), c(first_column, cluster_col))),
    drop = FALSE
  ]
  rownames(cluster_data) <- NULL
  cluster_data
}

# Tukey HSD for every condition pair, following a one-way ANOVA.
#
# A significant omnibus F says only that some condition differs; this supplies the
# pairwise comparisons. Gated on the ANOVA result the way Perseus does it: the BH
# adjustment on the ANOVA controls error across features, and Tukey controls the
# family-wise rate across the condition pairs within each feature.
#
# Tukey-Kramer is used throughout, so unequal group sizes arising from missing
# values are handled correctly. Returns one row per feature and condition pair; an
# empty data frame when fewer than three conditions are present, because with two
# the omnibus F and the single pairwise comparison test the same hypothesis.
.TEST_TYPES <- list(
  unpaired = list(paired = FALSE, model = "pooled"),
  unpaired_welch = list(paired = FALSE, model = "welch"),
  paired = list(paired = TRUE, model = "pooled")
)

# Return list(paired = , model = ) for a test_type string.
resolve_test_type <- function(value) {
  mode <- tolower(trimws(as.character(value)))
  if (!mode %in% names(.TEST_TYPES)) {
    stop(
      paste0("test_type must be one of: ", paste(sort(names(.TEST_TYPES)), collapse = ", "), "."),
      call. = FALSE
    )
  }
  .TEST_TYPES[[mode]]
}

variance_model <- function(value) {
  resolve_test_type(value)$model
}

# Standard error and Welch-Satterthwaite degrees of freedom for a sum of
# independent group means. Each component is list(variance = ..., count = ...).
.satterthwaite <- function(components) {
  ratios <- lapply(components, function(component) {
    as.numeric(component$variance) / as.numeric(component$count)
  })
  se_squared <- Reduce(`+`, ratios)
  denominator <- Reduce(
    `+`,
    Map(
      function(ratio, component) {
        ratio^2 / pmax(as.numeric(component$count) - 1, 1e-12)
      },
      ratios,
      components
    )
  )
  degrees <- se_squared^2 / denominator
  degrees[is.finite(se_squared) & se_squared == 0] <- 1
  list(se = sqrt(se_squared), dof = degrees)
}

# Shift each sample so all samples share a common median.
#
# Operates on log2 values, where a multiplicative loading difference is an
# additive offset. Samples are re-centred on the grand median rather than on zero
# so the result stays on a recognisable intensity scale; that choice is a constant
# shift and does not affect any fold change.
median_center <- function(values) {
  matrix_values <- as.matrix(values)
  storage.mode(matrix_values) <- "numeric"
  medians <- apply(matrix_values, 2, stats::median, na.rm = TRUE)
  grand_median <- stats::median(medians, na.rm = TRUE)
  for (index in seq_along(medians)) {
    matrix_values[, index] <- matrix_values[, index] - medians[[index]] + grand_median
  }
  as.data.frame(matrix_values, check.names = FALSE)
}

# Force every sample onto a common intensity distribution.
#
# Missing values are neither imputed nor allowed to shift a sample's ranks: each
# sample's observed values are mapped onto their own quantile positions, and the
# shared reference distribution is read off at those positions. This matches
# interpolates rather than dropping incomplete
# rows.
quantile_normalize <- function(values) {
  matrix_values <- as.matrix(values)
  storage.mode(matrix_values) <- "numeric"
  row_count <- nrow(matrix_values)
  if (!row_count) {
    return(as.data.frame(matrix_values, check.names = FALSE))
  }

  # Grid spans the full row count so columns with different
  # numbers of observed values still land on a common reference curve.
  grid <- seq(0, 1, length.out = row_count)
  curves <- list()
  for (index in seq_len(ncol(matrix_values))) {
    observed <- sort(matrix_values[, index][!is.na(matrix_values[, index])])
    if (!length(observed)) next
    positions <- if (length(observed) > 1) seq(0, 1, length.out = length(observed)) else 0
    curves[[length(curves) + 1]] <- if (length(observed) == 1) rep(observed, length(grid)) else stats::approx(
      positions, observed, xout = grid, rule = 2
    )$y
  }
  if (!length(curves)) {
    return(as.data.frame(matrix_values, check.names = FALSE))
  }
  reference <- colMeans(do.call(rbind, curves))

  for (index in seq_len(ncol(matrix_values))) {
    column <- matrix_values[, index]
    mask <- !is.na(column)
    observed <- column[mask]
    if (!length(observed)) next
    ranks <- rank(observed, ties.method = "average")
    positions <- if (length(observed) > 1) (ranks - 1) / (length(observed) - 1) else 0
    matrix_values[mask, index] <- if (length(reference) == 1) rep(reference, length(positions)) else stats::approx(
      grid, reference, xout = positions, rule = 2
    )$y
  }
  as.data.frame(matrix_values, check.names = FALSE)
}

# Apply a global normalization to the sample columns of a log2 matrix.
#
# Always global. Normalising within conditions would remove exactly the
# differences the downstream tests are looking for.
#
# VSN is delegated to Bioconductor vsn rather than reimplemented: a Python port
# matched the reference on well-conditioned data but diverged by up to 2.2 log2
# units on wide-dynamic-range input, because vsn's profile likelihood is flat and
# multimodal. `linear_source` supplies the untransformed intensities vsn models;
# without it they are reconstructed as 2^log2, which perturbs the input at machine
# epsilon and can shift the fit.
# References: quantile normalization follows the method of Bolstad et al. 2003, doi:10.1093/bioinformatics/19.2.185;
# VSN is delegated to Bioconductor vsn
# (Huber et al. 2002, doi:10.1093/bioinformatics/18.suppl_1.S96).
# Resolve the columns to normalize from a metadata frame or a column list.
# Every other public function takes a metadata frame as its second argument, so
# normalize_data(data, meta, ...) is the call people write. That used to resolve
# to no columns and return the input unchanged, which is indistinguishable from a
# successful normalization.
.normalization_sample_columns <- function(data, meta) {
  if (is.data.frame(meta)) {
    if (!"sample" %in% names(meta)) {
      stop("Metadata must contain a 'sample' column naming the columns to normalize.")
    }
    requested <- as.character(meta$sample)
  } else {
    requested <- as.character(meta)
  }

  present <- requested[requested %in% names(data)]
  missing <- requested[!requested %in% names(data)]
  if (!length(present)) {
    stop(sprintf(
      "None of the requested sample columns are in the data, so nothing would be normalized. Requested: %s.",
      if (length(requested)) paste(utils::head(requested, 6), collapse = ", ") else "(nothing)"
    ))
  }
  if (length(missing)) {
    stop(sprintf(
      paste0("%d requested sample column(s) are not in the data: %s. ",
             "Normalizing only the rest would silently change the reference distribution."),
      length(missing), paste(utils::head(missing, 6), collapse = ", ")
    ))
  }
  present
}

# Per-sample missingness, and how far each sample sits on the complete features.
#
# Median and quantile normalization use every observed value of a sample.
# Missing values are mostly low-abundance, so a sample with many more of them has
# a higher observed median and is shifted down. A sample is flagged when its
# share of missing values is at least `min_gap` above the most complete sample.
# `complete_offset` is the sample's median distance from the row median over the
# features measured in every sample: after normalization it shows the shift those
# features carry. It is NA when fewer than `min_complete` features are complete.
MISSINGNESS_GAP <- 0.10
MISSINGNESS_MIN_COMPLETE <- 20
.missingness_method_labels <- c(median = "Median centering", quantile = "Quantile normalization", vsn = "VSN")

missingness_imbalance <- function(data, meta, min_gap = MISSINGNESS_GAP,
                                  min_complete = MISSINGNESS_MIN_COMPLETE) {
  present <- .normalization_sample_columns(data, meta)
  values <- .numeric_matrix(data, present)
  values[!is.finite(values)] <- NA_real_
  missing <- if (nrow(values)) colMeans(is.na(values)) else stats::setNames(rep(0, length(present)), present)
  reference <- if (length(missing)) min(missing) else 0
  complete <- values[stats::complete.cases(values), , drop = FALSE]
  offsets <- if (nrow(complete) >= min_complete) {
    centred <- complete - apply(complete, 1, stats::median)
    apply(centred, 2, stats::median)
  } else {
    rep(NA_real_, length(present))
  }
  conditions <- rep(NA_character_, length(present))
  if (is.data.frame(meta) && "condition" %in% names(meta)) {
    conditions <- as.character(meta$condition)[match(present, as.character(meta$sample))]
  }
  data.frame(
    sample = present,
    condition = conditions,
    missing_fraction = as.numeric(missing),
    reference_missing_fraction = reference,
    flagged = (as.numeric(missing) - reference) >= min_gap - 1e-12,
    complete_features = nrow(complete),
    complete_offset = as.numeric(offsets),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
}

# The warning for missingness_imbalance(), or NULL when there is nothing to say.
# Median centering, quantile normalization and VSN are concerned: all are
# fitted on each sample's observed values.
missingness_imbalance_warning <- function(table, method, min_gap = MISSINGNESS_GAP) {
  key <- tolower(trimws(as.character(method %||% "none")))
  if (!key %in% names(.missingness_method_labels) || !nrow(table) || !any(table$flagged)) {
    return(NULL)
  }
  label <- .missingness_method_labels[[key]]
  flagged <- table[table$flagged, , drop = FALSE]
  flagged <- flagged[order(-flagged$missing_fraction, seq_len(nrow(flagged))), , drop = FALSE]
  others <- table[!table$flagged, , drop = FALSE]
  shown <- utils::head(flagged, 6)
  listed <- sprintf("%s (%.0f%%)", shown$sample, shown$missing_fraction * 100)
  if (nrow(flagged) > 6) listed <- c(listed, sprintf("and %d more", nrow(flagged) - 6))
  message <- sprintf(
    paste0(
      "Missing values differ strongly between samples: %d of %d samples have at least %.0f percentage ",
      "points more missing values than the most complete sample (%.0f%%): %s. %s uses each sample's ",
      "observed values, and missing values are mostly low-abundance, so these samples can be shifted down."
    ),
    nrow(flagged), nrow(table), min_gap * 100, table$reference_missing_fraction[1] * 100,
    paste(listed, collapse = ", "), label
  )
  if (all(!is.na(flagged$complete_offset)) && nrow(others) && all(!is.na(others$complete_offset))) {
    shift <- mean(flagged$complete_offset) - mean(others$complete_offset)
    message <- paste0(message, sprintf(
      " On the %s features measured in every sample, they sit %.2f log2 %s the other samples after normalization.",
      format(table$complete_features[1], big.mark = ",", scientific = FALSE, trim = TRUE),
      abs(shift), if (shift < 0) "below" else "above"
    ))
  }
  conditions <- unique(as.character(flagged$condition[!is.na(flagged$condition)]))
  if (length(conditions) == 1 && all(!is.na(flagged$condition))) {
    message <- paste0(message, sprintf(
      " All of them are in condition %s, so fold changes involving %s may carry this shift.",
      conditions, conditions
    ))
  }
  paste0(message, " Check these samples before interpreting fold changes.")
}

# Phosphoprotein workflows: normalize phosphosites BEFORE transform_phosprot,
# never the collapsed phosphoprotein matrix. The collapse carries the site-level
# normalization forward, and a second pass would normalize the same values twice;
# the app applies none at that level.
normalize_data <- function(data, meta, method = "none", linear_source = NULL) {
  resolved <- tolower(trimws(as.character(method %||% "none")))
  if (resolved %in% c("", "none")) {
    return(data)
  }
  present <- .normalization_sample_columns(data, meta)

  numeric_values <- .numeric_matrix(data, present)
  normalized <- if (resolved == "median") {
    median_center(numeric_values)
  } else if (resolved == "quantile") {
    quantile_normalize(numeric_values)
  } else if (resolved == "vsn") {
    .require_pkg("vsn")
    linear <- if (is.null(linear_source)) {
      2^numeric_values
    } else {
      raw <- .numeric_matrix(linear_source, present)
      raw[!is.na(raw) & raw == 0] <- NA_real_
      raw
    }
    fit <- vsn::vsn2(as.matrix(linear), verbose = FALSE)
    predicted <- vsn::predict(fit, newdata = as.matrix(linear))
    predicted[is.na(linear)] <- NA_real_
    as.data.frame(predicted, check.names = FALSE)
  } else {
    stop("method must be one of: none, median, quantile, vsn.", call. = FALSE)
  }

  output <- data
  for (column in present) {
    output[[column]] <- as.numeric(normalized[[column]])
  }
  message <- missingness_imbalance_warning(missingness_imbalance(output, meta), resolved)
  if (!is.null(message)) warning(message, call. = FALSE)
  output
}

# Map extracted id -> name, refusing to guess when two names share an id.
#
# The id is only the *last* number in a name, so a run set following the common
# date_cellline_condition_replicate convention collapses every condition onto the
# same handful of ids: 20240110_HeLa_ctrl_01.raw and 20240110_HeLa_treat_01.raw
# are both "01". Resolving that by first-wins drops one whole condition, and
# renaming data columns to the id produces duplicate column labels that later
# select silently as the wrong sample.
sample_id_map <- function(names) {
  mapping <- list()
  collisions <- list()
  for (name in names) {
    text <- as.character(name)
    sample_id <- extract_sample_id(text)
    if (!is.null(mapping[[sample_id]]) && mapping[[sample_id]] != text) {
      existing <- collisions[[sample_id]] %||% mapping[[sample_id]]
      collisions[[sample_id]] <- unique(c(existing, text))
      next
    }
    mapping[[sample_id]] <- text
  }
  if (length(collisions)) {
    detail <- vapply(
      sort(names(collisions)),
      function(key) {
        paste0(
          paste(sprintf("'%s'", sort(collisions[[key]])), collapse = " and "),
          " both reduce to '", key, "'"
        )
      },
      character(1)
    )
    stop(
      paste0(
        "Sample names cannot be matched by number because they are ambiguous: ",
        paste(detail, collapse = "; "),
        ". Sample matching falls back to the last number in a name, so names that ",
        "differ only before that number are indistinguishable. Either use sample ",
        "names in the annotation that match the run names exactly, or rename the ",
        "runs so the trailing number is unique."
      ),
      call. = FALSE
    )
  }
  mapping
}

# TRUE per row where every observed replicate in the group holds one value.
#
# Such a row has no measured within-group variation, so the standard error
# collapses and the t-statistic explodes: a fold change of 0.05 can reach
# p = 2e-54 and outrank every genuine effect at the top of a volcano. The p-value
# itself is correct; what the flag marks is that the significance comes from
# absent variation rather than effect size. Values reported at a detection floor,
# rounded exports and imputation filling one value across replicates all produce
# it.
#
# Tested with min == max rather than variance == 0, which is exact regardless of
# floating-point representation: 14.05 repeated three times has a variance of
# 4.7e-30, not 0, so a zero test would miss it.
constant_within_group <- function(values) {
  matrix_values <- as.matrix(values)
  storage.mode(matrix_values) <- "numeric"
  counts <- rowSums(is.finite(matrix_values))
  low <- suppressWarnings(apply(matrix_values, 1, min, na.rm = TRUE))
  high <- suppressWarnings(apply(matrix_values, 1, max, na.rm = TRUE))
  counts > 0 & is.finite(low) & is.finite(high) & low == high
}

# constant_within_group() for paired differences, ignoring float subtraction
# noise: differences are compared at nine decimals.
constant_differences <- function(differences) {
  constant_within_group(round(as.matrix(differences), 9))
}

# Rows where every variance component is constant: the standard error is zero,
# so the t statistic is undefined and the row gets no p-value ("Unavailable").
without_variation <- function(groups) {
  Reduce(`&`, lapply(groups, constant_within_group))
}

# Mean across a condition's replicates, blanked where too few were observed.
#
# rowMeans(na.rm = TRUE) skips missing values silently, so a condition mean
# resting on one replicate is plotted and correlated at the same weight as a
# fully observed one. Measured on 2000 features with 30% poor coverage, the
# single-replicate means were off by 0.28 log2 on average and 1.21 at worst
# against the same features' fully observed means.
#
# min_present is the smallest number of observations a mean may rest on. The
# default of 1 reports every mean, which is the long-standing behaviour and keeps
# previously generated results reproducible. Pass 2 or more to require that a mean
# rest on enough replicates to carry spread information.
#
# Returns list(mean = , count = ) so the caller can report how many features were
# excluded rather than dropping them silently.
condition_mean <- function(data, columns, min_present = 1) {
  values <- .numeric_matrix(data, as.character(columns))
  counts <- rowSums(!is.na(values))
  means <- rowMeans(values, na.rm = TRUE)
  means[counts < as.integer(min_present)] <- NA_real_
  list(mean = means, count = counts)
}

anova_posthoc_data <- function(
    anova_df,
    meta,
    in_pval = 0.05,
    only_significant = TRUE,
    label_col = NULL
) {
  if (is.null(label_col)) label_col <- get("_auto_label_col")(anova_df)

  conditions <- unique(na.omit(as.character(meta$condition)))
  condition_columns <- list()
  for (condition in conditions) {
    columns <- intersect(
      as.character(meta$sample[as.character(meta$condition) == condition]),
      names(anova_df)
    )
    if (length(columns)) condition_columns[[condition]] <- columns
  }
  if (length(condition_columns) < 3) {
    return(anova_df[0, c(label_col), drop = FALSE])
  }

  posthoc_data <- if (only_significant && !is.null(.significance_pval_column(anova_df))) {
    anova_df[anova_df[[.significance_pval_column(anova_df)]] < in_pval, , drop = FALSE]
  } else {
    anova_df
  }
  if (!nrow(posthoc_data)) {
    return(anova_df[0, c(label_col), drop = FALSE])
  }

  names_used <- names(condition_columns)
  group_values <- lapply(condition_columns, function(columns) {
    .numeric_matrix(posthoc_data, columns)
  })
  counts <- lapply(group_values, function(m) rowSums(!is.na(m)))
  means <- lapply(group_values, function(m) rowMeans(m, na.rm = TRUE))

  # Pooled within-group variance across every condition, as the ANOVA itself uses.
  sum_squares <- rep(0, nrow(posthoc_data))
  for (condition in names_used) {
    values <- group_values[[condition]]
    variances <- apply(values, 1, function(row) stats::var(row, na.rm = TRUE))
    variances[!is.finite(variances)] <- 0
    sum_squares <- sum_squares + ifelse(
      counts[[condition]] > 1,
      (counts[[condition]] - 1) * variances,
      0
    )
  }
  total_n <- Reduce(`+`, counts)
  df_resid <- total_n - length(names_used)
  mse <- ifelse(df_resid > 0, sum_squares / df_resid, NA_real_)

  labels <- as.character(posthoc_data[[label_col]])
  anova_adj <- if ("adj_pval" %in% names(posthoc_data)) {
    as.numeric(posthoc_data$adj_pval)
  } else {
    rep(NA_real_, nrow(posthoc_data))
  }

  frames <- list()
  for (first in seq_len(length(names_used) - 1)) {
    for (second in seq(first + 1, length(names_used))) {
      left <- names_used[[first]]
      right <- names_used[[second]]
      n_left <- counts[[left]]
      n_right <- counts[[right]]
      standard_error <- sqrt(mse / 2 * (1 / n_left + 1 / n_right))
      difference <- means[[left]] - means[[right]]
      q_statistic <- abs(difference) / standard_error
      pvalues <- stats::ptukey(
        q_statistic,
        nmeans = length(names_used),
        df = df_resid,
        lower.tail = FALSE
      )
      pvalues[!is.finite(q_statistic) | !(df_resid > 0)] <- NA_real_
      usable <- is.finite(pvalues) & n_left >= 2 & n_right >= 2
      if (!any(usable)) next
      frames[[length(frames) + 1]] <- data.frame(
        label = labels[usable],
        comparison = paste(left, "vs", right),
        group1 = left,
        group2 = right,
        log2FC = difference[usable],
        n_group1 = as.integer(n_left[usable]),
        n_group2 = as.integer(n_right[usable]),
        q_statistic = q_statistic[usable],
        tukey_pval = pvalues[usable],
        significance = ifelse(
          pvalues[usable] < in_pval,
          "Significant",
          "Not significant"
        ),
        anova_adj_pval = anova_adj[usable],
        stringsAsFactors = FALSE,
        check.names = FALSE
      )
    }
  }

  if (!length(frames)) {
    return(anova_df[0, c(label_col), drop = FALSE])
  }
  output <- do.call(rbind, frames)
  names(output)[1] <- label_col
  output <- output[order(output$tukey_pval, output[[label_col]], output$comparison), , drop = FALSE]
  rownames(output) <- NULL
  output
}

assign("_auto_label_col", function(frame) {
  for (column in c(
    "Phosphoprotein",
    "ProteinNames",
    "PTM_Collapse_key",
    "Gene_group",
    "GeneNames"
  )) {
    if (column %in% names(frame)) return(column)
  }

  stop("No supported label column was found.", call. = FALSE)
})

anova_plot <- function(
    anova_df,
    meta,
    in_pval = 0.05,
    z_score = TRUE,
    cluster_rows = TRUE,
    cluster_samples = TRUE,
    cluster_method = "average",
    cluster_metric = "euclidean",
    show_gene_names = FALSE,
    show_condition_legend = FALSE,
    show_dendrograms = TRUE,
    width = 12,
    height = 10,
    dpi = 150
) {
  if (!nrow(anova_df)) {
    plot.new()
    title("ANOVA heatmap")
    return(.plot_result())
  }

  label_col <- get("_auto_label_col")(anova_df)
  meta_plot <- meta
  meta_plot$sample <- as.character(meta_plot$sample)
  meta_plot$condition <- as.character(meta_plot$condition)
  meta_plot$plot_sample <- if ("new_sample" %in% names(meta_plot)) {
    as.character(meta_plot$new_sample)
  } else {
    paste0(
      meta_plot$condition,
      "_",
      ave(seq_len(nrow(meta_plot)), meta_plot$condition, FUN = seq_along)
    )
  }

  sample_columns <- intersect(meta_plot$sample, names(anova_df))
  if (!length(sample_columns)) {
    stop("No sample columns from meta were found in anova_df.", call. = FALSE)
  }

  plot_data <- if (!is.null(.significance_pval_column(anova_df))) {
    anova_df[anova_df[[.significance_pval_column(anova_df)]] < in_pval, , drop = FALSE]
  } else {
    anova_df
  }
  if (!nrow(plot_data)) {
    plot.new()
    title("ANOVA heatmap")
    text(0.5, 0.5, "No rows passed the ANOVA threshold.")
    return(.plot_result())
  }

  raw_matrix <- .numeric_matrix(plot_data, sample_columns)
  if ((cluster_rows && nrow(raw_matrix) > 1) ||
      (cluster_samples && ncol(raw_matrix) > 1)) {
    dropped_info <- .drop_incomplete_features(raw_matrix, "ANOVA heatmap")
    plot_data <- plot_data[dropped_info$kept, , drop = FALSE]
    raw_matrix <- raw_matrix[dropped_info$kept, , drop = FALSE]
    .warn_dropped_features(dropped_info$dropped, dropped_info$total)
  }
  rownames(raw_matrix) <- as.character(plot_data[[label_col]])
  missing_mask <- !is.finite(raw_matrix)
  matrix <- if (z_score) row_zscore(raw_matrix) else raw_matrix
  matrix[!is.finite(matrix)] <- NA
  cluster_matrix <- matrix

  row_hclust <- NULL
  column_hclust <- NULL
  if (cluster_rows && nrow(matrix) > 1) {
    row_hclust <- hclust(
      dist(cluster_matrix, method = cluster_metric),
      method = cluster_method
    )
    row_order <- row_hclust$order
    matrix <- matrix[row_order, , drop = FALSE]
    missing_mask <- missing_mask[row_order, , drop = FALSE]
    cluster_matrix <- cluster_matrix[row_order, , drop = FALSE]
  }

  if (cluster_samples && ncol(matrix) > 1) {
    column_hclust <- hclust(
      dist(t(cluster_matrix), method = cluster_metric),
      method = cluster_method
    )
    column_order <- column_hclust$order
    matrix <- matrix[, column_order, drop = FALSE]
    missing_mask <- missing_mask[, column_order, drop = FALSE]
    sample_columns <- sample_columns[column_order]
  }

  sample_conditions <- meta_plot$condition[match(sample_columns, meta_plot$sample)]
  sample_labels <- meta_plot$plot_sample[match(sample_columns, meta_plot$sample)]
  condition_levels <- unique(sample_conditions)
  condition_colors <- setNames(
    .plot_colors(length(condition_levels)),
    condition_levels
  )

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)
  par(oma = c(0, 0, 2.5, 0))

  layout(
    matrix(c(
      0, 1, 0,
      0, 2, 0,
      3, 4, 5
    ), nrow = 3, byrow = TRUE),
    widths = c(2.2, 12, 1.2),
    heights = c(2, 0.35, 10)
  )

  par(mar = c(0, 0, 0, 0))
  if (show_dendrograms && !is.null(column_hclust)) {
    plot(as.dendrogram(column_hclust), axes = FALSE, xaxs = "i", leaflab = "none")
  } else {
    plot.new()
  }

  par(mar = c(0, 0, 0, 0))
  condition_index <- match(sample_conditions, condition_levels)
  image(
    seq_along(sample_columns),
    1,
    matrix(condition_index, nrow = length(sample_columns)),
    col = condition_colors,
    axes = FALSE
  )

  par(mar = c(8, 0, 1, 0))
  if (show_dendrograms && !is.null(row_hclust)) {
    plot(
      as.dendrogram(row_hclust),
      horiz = TRUE,
      axes = FALSE,
      yaxs = "i",
      leaflab = "none"
    )
  } else {
    plot.new()
  }

  par(mar = c(8, if (show_gene_names) 8 else 2, 1, 1))
  display_matrix <- matrix
  display_matrix[missing_mask] <- NA
  palette <- colorRampPalette(c("#313695", "white", "#a50026"))(100)
  palette <- c("#d8d8d8", palette)
  zlim <- if (z_score) c(-2.5, 2.5) else range(display_matrix, na.rm = TRUE)
  image_matrix <- display_matrix
  image_matrix[is.na(image_matrix)] <- zlim[1] - diff(zlim) / 99
  image(
    seq_len(ncol(image_matrix)),
    seq_len(nrow(image_matrix)),
    t(image_matrix[nrow(image_matrix):1, , drop = FALSE]),
    col = palette,
    zlim = c(zlim[1] - diff(zlim) / 99, zlim[2]),
    axes = FALSE,
    xlab = "samples",
    ylab = ""
  )
  axis(1, seq_along(sample_labels), sample_labels, las = 2, cex.axis = 0.55)
  if (show_gene_names) {
    axis(2, seq_len(nrow(matrix)), rev(rownames(matrix)), las = 2, cex.axis = 0.45)
  }
  box()

  par(mar = c(8, 0.5, 1, 3.5))
  scale_values <- seq(zlim[1], zlim[2], length.out = 100)
  image(1, scale_values, matrix(scale_values, nrow = 1), col = palette[-1], axes = FALSE)
  axis(4, las = 2, cex.axis = 0.7)
  mtext(if (z_score) "row z-score" else "intensity", side = 4, line = 2.2)

  if (show_condition_legend) {
    par(xpd = NA)
    legend(
      "topright",
      inset = c(-0.15, -0.12),
      legend = condition_levels,
      fill = condition_colors,
      border = NA,
      bty = "n",
      cex = 0.75
    )
  }

  mtext(
    paste0("ANOVA heatmap (", nrow(plot_data), " rows)"),
    outer = TRUE,
    line = -1.2,
    cex = 1.1,
    font = 2
  )
  .plot_result()
}

anova_plot_cluster <- function(
    anova_cluster_df,
    meta,
    cluster_col = "cluster",
    z_score = TRUE,
    cluster_samples = TRUE,
    cluster_method = "average",
    cluster_metric = "euclidean",
    show_gene_names = FALSE,
    show_condition_legend = FALSE,
    show_cluster_legend = TRUE,
    max_cluster_legend = 12,
    show_dendrogram = TRUE,
    width = 12,
    height = 10,
    dpi = 150
) {
  if (!cluster_col %in% names(anova_cluster_df)) {
    stop(
      "anova_cluster_df must contain a cluster column from anova_cluster_data().",
      call. = FALSE
    )
  }
  if (!nrow(anova_cluster_df)) {
    plot.new()
    title("ANOVA cluster heatmap")
    return(.plot_result())
  }

  label_col <- get("_auto_label_col")(anova_cluster_df)
  meta_plot <- meta
  meta_plot$sample <- as.character(meta_plot$sample)
  meta_plot$condition <- as.character(meta_plot$condition)
  meta_plot$plot_sample <- if ("new_sample" %in% names(meta_plot)) {
    as.character(meta_plot$new_sample)
  } else {
    paste0(
      meta_plot$condition,
      "_",
      ave(seq_len(nrow(meta_plot)), meta_plot$condition, FUN = seq_along)
    )
  }

  sample_columns <- intersect(meta_plot$sample, names(anova_cluster_df))
  if (!length(sample_columns)) {
    stop("anova_cluster_df must contain the original sample columns.", call. = FALSE)
  }

  matrix <- .numeric_matrix(anova_cluster_df, sample_columns)
  if (cluster_samples && ncol(matrix) > 1) {
    dropped_info <- .drop_incomplete_features(matrix, "ANOVA cluster heatmap")
    anova_cluster_df <- anova_cluster_df[dropped_info$kept, , drop = FALSE]
    matrix <- matrix[dropped_info$kept, , drop = FALSE]
    .warn_dropped_features(dropped_info$dropped, dropped_info$total)
  }
  rownames(matrix) <- as.character(anova_cluster_df[[label_col]])
  missing_mask <- !is.finite(matrix)
  if (z_score) matrix <- row_zscore(matrix)
  matrix[!is.finite(matrix)] <- NA
  cluster_matrix <- matrix

  column_hclust <- NULL
  if (cluster_samples && ncol(matrix) > 1) {
    column_hclust <- hclust(
      dist(t(cluster_matrix), method = cluster_metric),
      method = cluster_method
    )
    column_order <- column_hclust$order
    matrix <- matrix[, column_order, drop = FALSE]
    missing_mask <- missing_mask[, column_order, drop = FALSE]
    sample_columns <- sample_columns[column_order]
  }

  sample_conditions <- meta_plot$condition[match(sample_columns, meta_plot$sample)]
  sample_labels <- meta_plot$plot_sample[match(sample_columns, meta_plot$sample)]
  condition_levels <- unique(sample_conditions)
  condition_colors <- setNames(
    .plot_colors(length(condition_levels)),
    condition_levels
  )

  cluster_values <- anova_cluster_df[[cluster_col]]
  cluster_levels <- unique(cluster_values)
  cluster_colors <- setNames(
    grDevices::hcl.colors(length(cluster_levels), "Dark 3"),
    cluster_levels
  )

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- par(no.readonly = TRUE)
  on.exit(.restore_layout(old_par), add = TRUE)
  par(oma = c(0, 0, 2.5, 0))

  layout(
    matrix(c(
      0, 1, 0, 0,
      0, 2, 0, 0,
      3, 4, 5, 6
    ), nrow = 3, byrow = TRUE),
    widths = c(0.5, 12, 1.2, 3),
    heights = c(2, 0.35, 10)
  )

  par(mar = c(0, 0, 0, 0))
  if (show_dendrogram && !is.null(column_hclust)) {
    plot(as.dendrogram(column_hclust), axes = FALSE, xaxs = "i", leaflab = "none")
  } else {
    plot.new()
  }

  par(mar = c(0, 0, 0, 0))
  condition_index <- match(sample_conditions, condition_levels)
  image(seq_along(sample_columns), 1, matrix(condition_index, nrow = length(sample_columns)), col = condition_colors, axes = FALSE)

  par(mar = c(8, 0, 1, 0))
  cluster_index <- match(cluster_values, cluster_levels)
  image(1, seq_along(cluster_values), matrix(rev(cluster_index), nrow = 1), col = cluster_colors, axes = FALSE)

  par(mar = c(8, if (show_gene_names) 8 else 2, 1, 1))
  palette <- colorRampPalette(c("#313695", "white", "#a50026"))(100)
  zlim <- if (z_score) c(-2.5, 2.5) else range(matrix, na.rm = TRUE)
  display_matrix <- matrix
  display_matrix[missing_mask] <- NA
  image(
    seq_len(ncol(display_matrix)),
    seq_len(nrow(display_matrix)),
    t(display_matrix[nrow(display_matrix):1, , drop = FALSE]),
    col = palette,
    zlim = zlim,
    axes = FALSE,
    xlab = "samples",
    ylab = ""
  )
  axis(1, seq_along(sample_labels), sample_labels, las = 2, cex.axis = 0.55)
  if (show_gene_names) {
    axis(2, seq_len(nrow(matrix)), rev(rownames(matrix)), las = 2, cex.axis = 0.45)
  }
  box()

  par(mar = c(8, 0.5, 1, 3.5))
  scale_values <- seq(zlim[1], zlim[2], length.out = 100)
  image(1, scale_values, matrix(scale_values, nrow = 1), col = palette, axes = FALSE)
  axis(4, las = 2, cex.axis = 0.7)
  mtext(if (z_score) "row z-score" else "intensity", side = 4, line = 2.2)

  par(mar = c(1, 0, 1, 0))
  plot.new()
  legend_items <- list()
  if (show_cluster_legend) {
    shown_clusters <- head(cluster_levels, max_cluster_legend)
    legend_items$labels <- paste("cluster", shown_clusters)
    legend_items$colors <- unname(cluster_colors[as.character(shown_clusters)])
  }
  if (show_condition_legend) {
    legend_items$labels <- c(legend_items$labels, condition_levels)
    legend_items$colors <- c(legend_items$colors, unname(condition_colors))
  }
  if (length(legend_items$labels)) {
    legend(
      "topleft",
      legend = legend_items$labels,
      fill = legend_items$colors,
      border = NA,
      bty = "n",
      cex = 0.7
    )
  }

  mtext(
    paste0("ANOVA cluster heatmap (", nrow(anova_cluster_df), " rows)"),
    outer = TRUE,
    line = -1.2,
    cex = 1.1,
    font = 2
  )
  .plot_result()
}

.is_phosphoprotein_workflow <- function(workflow) {
  workflow_key <- gsub("[^a-z0-9]", "", tolower(as.character(workflow)))
  workflow_key %in% c("phosprot", "phosphoprotein", "phosphoproteome")
}

.different_gene_tokens <- function(values, split_groups) {
  keep <- !is.na(values)
  if (is.numeric(values)) keep <- keep & is.finite(values)
  values <- trimws(as.character(values[keep]))
  values <- values[nzchar(values)]
  if (!length(values)) return(character())
  tokens <- if (split_groups) {
    unlist(strsplit(values, ";", fixed = TRUE), use.names = FALSE)
  } else {
    sub(";.*$", "", values)
  }
  sort(unique(trimws(tokens[nzchar(trimws(tokens))])))
}

.different_genes_from_volcano <- function(volcano_data, key_col, split_groups) {
  required <- c(key_col, "significance")
  missing <- setdiff(required, names(volcano_data))
  if (length(missing)) {
    stop(
      paste0(
        "Volcano output is missing required ORA columns: ",
        paste(sort(missing), collapse = ", ")
      ),
      call. = FALSE
    )
  }

  list(
    Upregulated = .different_gene_tokens(
      volcano_data[[key_col]][volcano_data$significance == "Upregulated"],
      split_groups
    ),
    Downregulated = .different_gene_tokens(
      volcano_data[[key_col]][volcano_data$significance == "Downregulated"],
      split_groups
    ),
    Background = .different_gene_tokens(volcano_data[[key_col]], split_groups)
  )
}

different_genes <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, workflow="Gene", paired="Unpaired", uncorrected=FALSE, test_type=NULL) {
  prefer_group <- .is_phosphoprotein_workflow(workflow)
  candidates <- if (prefer_group) c("Gene_group", "GeneNames") else "GeneNames"
  key_col <- candidates[candidates %in% names(data)][1]
  if (is.na(key_col)) {
    stop("different_genes requires GeneNames or Gene_group.", call. = FALSE)
  }
  split_groups <- prefer_group

  output <- volcano_data_f(
    data,
    meta,
    condition1,
    condition2,
    in_pval = in_pval,
    in_log2fc = in_log2fc,
    workflow = workflow,
    paired = paired,
    uncorrected = uncorrected,
    test_type = test_type,
    label_column = key_col
  )
  .different_genes_from_volcano(output, key_col, split_groups)
}

different_genes_control <- function(
    data,
    meta,
    condition1,
    condition2,
    condition1_control,
    condition2_control,
    in_pval = 0.05,
    in_log2fc = 1,
    workflow = "Gene",
    paired = "Unpaired",
    uncorrected = FALSE,
    test_type = NULL
) {
  prefer_group <- .is_phosphoprotein_workflow(workflow)
  candidates <- if (prefer_group) c("Gene_group", "GeneNames") else "GeneNames"
  key_col <- candidates[candidates %in% names(data)][1]
  if (is.na(key_col)) {
    stop("different_genes_control requires GeneNames or Gene_group.", call. = FALSE)
  }
  output <- volcano_data_f_control(
    data,
    meta,
    condition1,
    condition2,
    condition1_control,
    condition2_control,
    in_pval = in_pval,
    in_log2fc = in_log2fc,
    workflow = workflow,
    paired = paired,
    uncorrected = uncorrected,
    test_type = test_type,
    label_column = key_col
  )
  .different_genes_from_volcano(output, key_col, prefer_group)
}

.empty_enrichment_frame <- function() {
  data.frame(
    source = character(0), term_id = character(0), term_name = character(0),
    term_size = integer(0), intersection_size = integer(0),
    query_size = integer(0), gene_ratio = numeric(0),
    p_value = numeric(0), adj_p_value = numeric(0), stringsAsFactors = FALSE
  )
}

enrichment_data <- function(
  gene_list,
  top_n=10,
  min_num=20,
  max_num=300,
  background=NULL,
  background_mode="experiment",
  adj_p_value_cutoff=0.05,
  workflow="Protein"
) {
  # The over-representation table behind `enrichment_analysis`. Split out so the
  # numbers can be read, exported and compared across the three pipelines;
  # `enrichment_analysis` draws exactly this frame, so the figure and the table
  # cannot drift apart. Returns a zero-row frame rather than NULL when nothing
  # passes, so callers can treat the result as a table unconditionally.
  background_mode <- match.arg(background_mode, c("experiment", "global"))
  split_groups <- .is_phosphoprotein_workflow(workflow)
  genes <- .different_gene_tokens(gene_list, split_groups)
  if (!length(genes)) return(.empty_enrichment_frame())
  if (min_num > max_num) {
    stop("min_num cannot be larger than max_num.", call. = FALSE)
  }

  db <- load_go_db()
  term_genes <- strsplit(as.character(db$genes), ";", fixed = TRUE)
  term_genes <- lapply(term_genes, function(values) {
    sort(unique(trimws(values[nzchar(trimws(values))])))
  })
  annotated <- sort(unique(unlist(term_genes, use.names = FALSE)))
  if (background_mode == "experiment") {
    if (is.null(background)) {
      stop(
        "Provide the tested-gene background, or set background_mode='global'.",
        call. = FALSE
      )
    }
    submitted_background <- .different_gene_tokens(background, split_groups)
    missing <- setdiff(genes, submitted_background)
    if (length(missing)) {
      stop(
        paste0(
          "Every query gene must be included in the experiment background. Missing: ",
          paste(head(missing, 10), collapse = ", "),
          "."
        ),
        call. = FALSE
      )
    }
    effective_background <- intersect(submitted_background, annotated)
  } else {
    effective_background <- annotated
  }
  if (!length(effective_background)) return(.empty_enrichment_frame())

  query <- intersect(genes, effective_background)
  if (!length(query)) return(.empty_enrichment_frame())
  effective_terms <- lapply(term_genes, intersect, y = effective_background)
  term_sizes <- lengths(effective_terms)
  eligible <- which(term_sizes >= min_num & term_sizes <= max_num)
  if (!length(eligible)) return(.empty_enrichment_frame())

  intersection_sizes <- vapply(
    effective_terms[eligible],
    function(term) length(intersect(query, term)),
    integer(1)
  )
  # A term sharing no gene with the query has p = 1 by construction and is never
  # reported, so it is not a test. Counting it in the Benjamini-Hochberg
  # denominator inflated every reported adjusted p -- by 3.4x on a 4000-gene
  # background -- and made the packages disagree with the web app, which corrects
  # over tested terms only.
  tested <- intersection_sizes > 0
  eligible <- eligible[tested]
  intersection_sizes <- intersection_sizes[tested]
  if (!length(eligible)) return(.empty_enrichment_frame())
  p_values <- stats::phyper(
    intersection_sizes - 1,
    term_sizes[eligible],
    length(effective_background) - term_sizes[eligible],
    length(query),
    lower.tail = FALSE
  )
  result <- data.frame(
    source = db$ontology[eligible],
    term_id = db$term[eligible],
    term_name = db$description[eligible],
    term_size = term_sizes[eligible],
    intersection_size = intersection_sizes,
    query_size = length(query),
    gene_ratio = intersection_sizes / length(query),
    p_value = p_values,
    adj_p_value = stats::p.adjust(p_values, method = "BH"),
    stringsAsFactors = FALSE
  )
  # intersection_size > 0 holds for every row now; only the cutoff remains.
  result <- result[result$adj_p_value <= adj_p_value_cutoff, , drop = FALSE]
  result <- head(result[order(result$adj_p_value, result$p_value), ], top_n)
  result
}

enrichment_analysis <- function(
  gene_list,
  top_n=10,
  min_num=20,
  max_num=300,
  background=NULL,
  background_mode="experiment",
  adj_p_value_cutoff=0.05,
  workflow="Protein"
) {
  result <- enrichment_data(
    gene_list = gene_list,
    top_n = top_n,
    min_num = min_num,
    max_num = max_num,
    background = background,
    background_mode = background_mode,
    adj_p_value_cutoff = adj_p_value_cutoff,
    workflow = workflow
  )
  if (!nrow(result)) return(NULL)

  # GeneRatio (overlap / query genes), as in clusterProfiler's dot plot.
  hits <- result$gene_ratio
  colors <- colorRampPalette(c("#2166ac", "white", "#b2182b"))(100)
  color_index <- cut(
    -log10(pmax(result$adj_p_value, .Machine$double.xmin)),
    breaks = 100,
    include.lowest = TRUE,
    labels = FALSE
  )

  old_par <- par(mar = c(5, 12, 3, 5))
  on.exit(par(old_par), add = TRUE)
  plot(
    hits,
    seq_len(nrow(result)),
    pch = 16,
    cex = sqrt(result$intersection_size),
    col = colors[color_index],
    yaxt = "n",
    xlab = "GeneRatio (overlap / query genes)",
    ylab = "",
    main = paste0(
      "GO Enrichment (ORA)\n",
      if (background_mode == "experiment") {
        "tested-gene background"
      } else {
        "global annotated background"
      }
    )
  )
  # BP, CC and MF terms share one plot and one BH correction, so each label
  # names its ontology, as in the web app.
  ontology <- ifelse(is.na(result$source) | result$source == "", "", paste0(" (", result$source, ")"))
  axis(2, seq_len(nrow(result)), paste0(result$term_name, ontology), las = 2, cex.axis = 0.65)
  mtext("GO Term", side = 2, line = 10)

  .plot_result()
}

load_go_db <- function() {
  configured <- trimws(Sys.getenv("COPYLOT_GO_DB", unset = ""))
  candidates <- c(
    if (nzchar(configured)) configured else character(),
    if (nzchar(.copylot_source_dir)) {
      file.path(.copylot_source_dir, "data", "all_go_terms_genes.csv")
    } else {
      character()
    },
    if (nzchar(.copylot_source_dir)) {
      file.path(.copylot_source_dir, "..", "data", "db", "all_go_terms_genes.csv")
    } else {
      character()
    },
    file.path(getwd(), "data", "db", "all_go_terms_genes.csv")
  )
  existing <- candidates[file.exists(candidates)]
  if (!length(existing)) {
    stop(
      "Could not find all_go_terms_genes.csv. Set COPYLOT_GO_DB or install the packaged database.",
      call. = FALSE
    )
  }
  read.csv(
    existing[1],
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
}

.aggregate_pathway_gene_values <- function(data, gene_column, sample_columns, pathway_genes) {
  genes <- trimws(as.character(pathway_genes))
  genes <- genes[nzchar(genes) & !duplicated(tolower(genes))]
  gene_tokens <- lapply(as.character(data[[gene_column]]), function(value) {
    if (is.na(value) || !nzchar(trimws(value))) return(character())
    unique(tolower(trimws(strsplit(value, ";", fixed = TRUE)[[1]])))
  })

  heatmap_data <- matrix(
    NA_real_,
    nrow = length(genes),
    ncol = length(sample_columns),
    dimnames = list(genes, sample_columns)
  )
  source_counts <- integer(length(genes))
  names(source_counts) <- genes

  for (gene_index in seq_along(genes)) {
    matching_rows <- which(vapply(
      gene_tokens,
      function(tokens) tolower(genes[gene_index]) %in% tokens,
      logical(1)
    ))
    source_counts[gene_index] <- length(matching_rows)
    if (!length(matching_rows)) next

    for (sample_index in seq_along(sample_columns)) {
      sample <- sample_columns[sample_index]
      if (!sample %in% names(data)) next
      values <- suppressWarnings(as.numeric(data[[sample]][matching_rows]))
      values[!is.finite(values)] <- NA_real_
      if (any(!is.na(values))) {
        heatmap_data[gene_index, sample_index] <- median(values, na.rm = TRUE)
      }
    }
  }

  list(data = heatmap_data, source_feature_count = source_counts)
}

proteins_in_pathway <- function(data, meta, db, pathway, conditions=NULL, figsize=c(12,8), cmap_name="plasma", remove_empty=TRUE, cluster_rows=FALSE, cluster_cols=FALSE, value_type="z", header=TRUE, id=TRUE, show_source_count=FALSE, gene_column=NULL) {
  if (is.null(gene_column)) {
    candidates <- intersect(c("GeneNames", "Gene_group"), names(data))
    if (length(candidates) != 1) stop("Specify gene_column when gene labels are missing or ambiguous.", call.=FALSE)
    gene_column <- candidates[1]
  }
  if (!gene_column %in% names(data)) stop("Selected gene_column is missing.", call.=FALSE)
  pathway_row <- db[
    tolower(db$description) == tolower(pathway),
    ,
    drop = FALSE
  ]
  if (!nrow(pathway_row)) {
    stop("No pathway found exactly matching '", pathway, "' in db", call. = FALSE)
  }

  genes <- trimws(strsplit(as.character(pathway_row$genes[1]), ";", fixed = TRUE)[[1]])
  meta_filtered <- if (is.null(conditions)) {
    meta
  } else {
    meta[meta$condition %in% conditions, , drop = FALSE]
  }
  meta_filtered <- .sample_meta(meta_filtered, id = id, newline = TRUE)

  aggregated <- .aggregate_pathway_gene_values(
    data,
    gene_column = gene_column,
    sample_columns = as.character(meta_filtered$sample),
    pathway_genes = genes
  )
  heatmap_data <- aggregated$data
  colnames(heatmap_data) <- meta_filtered$new_sample
  source_feature_counts <- aggregated$source_feature_count

  if (remove_empty) {
    heatmap_data <- heatmap_data[
      rowSums(!is.na(heatmap_data)) > 0,
      ,
      drop = FALSE
    ]
    source_feature_counts <- source_feature_counts[rownames(heatmap_data)]
  }
  if (!nrow(heatmap_data)) {
    stop("No matching gene data available for the selected pathway.", call. = FALSE)
  }

  value_type <- tolower(value_type)
  if (value_type == "z") {
    heatmap_data <- row_zscore(heatmap_data)
    color_label <- "Z-score"
    # Symmetric limits on a diverging map, as on the ANOVA heatmaps.
    zlim <- c(-2.5, 2.5)
  } else if (value_type == "log2") {
    color_label <- "log2 Intensity"
    zlim <- NULL
  } else {
    stop("value_type must be 'z' or 'log2'", call. = FALSE)
  }

  if (value_type == "z") {
    informative <- rowSums(is.finite(heatmap_data)) > 0
    heatmap_data <- heatmap_data[informative, , drop = FALSE]
    source_feature_counts <- source_feature_counts[rownames(heatmap_data)]
  }
  if (!nrow(heatmap_data)) {
    stop("No informative pathway rows remain after heatmap transformation.", call. = FALSE)
  }

  # How many dataset rows collapsed onto each gene. Off by default: on a pathway
  # of forty genes it is forty parentheticals down the side of the figure, and
  # most of them read 1.
  if (isTRUE(show_source_count)) {
    rownames(heatmap_data) <- paste0(
      rownames(heatmap_data),
      " (n=",
      as.integer(source_feature_counts[rownames(heatmap_data)]),
      ")"
    )
  }

  cluster_data <- NULL
  if ((cluster_rows && nrow(heatmap_data) > 1) ||
      (cluster_cols && ncol(heatmap_data) > 1)) {
    dropped_info <- .drop_incomplete_features(heatmap_data, "pathway heatmap")
    cluster_data <- dropped_info$matrix
    heatmap_data <- heatmap_data[dropped_info$kept, , drop = FALSE]
    .warn_dropped_features(dropped_info$dropped, dropped_info$total)
  }
  if (cluster_rows && nrow(heatmap_data) > 1) {
    order <- hclust(dist(cluster_data), method = "average")$order
    heatmap_data <- heatmap_data[order, , drop = FALSE]
    cluster_data <- cluster_data[order, , drop = FALSE]
  }
  if (cluster_cols && ncol(heatmap_data) > 1) {
    order <- hclust(dist(t(cluster_data)), method = "average")$order
    heatmap_data <- heatmap_data[, order, drop = FALSE]
  }

  .set_notebook_plot_size(figsize[1], figsize[2], units = "in")
  .plot_heatmap(
    heatmap_data,
    title = paste0(
      pathway,
      " (",
      if (value_type == "z") "Z-transformed" else "log2 Intensities",
      "; median across mapped features)"
    ),
    ylab = if (header) "Protein / Gene" else "",
    labels = header,
    zlim = zlim,
    color_label = color_label,
    palette = if (value_type == "z") {
      colorRampPalette(c("#2166ac", "#f7f7f7", "#b2182b"))(100)
    } else {
      colorRampPalette(c("#0d0887", "#cc4778", "#f0f921"))(100)
    }
  )
}

# A what-if projection of the volcano, not a power calculation: the observed mean
# fold changes are held fixed and the pooled t-test is recomputed with the
# variance multiplied by `mod_var` and, when `mod_n` > 1, `mod_n` replicates per
# group. Nothing is drawn at random. The observed fold changes include noise, so
# the projection is optimistic for effects that look large, and it does not
# estimate the probability of detecting a true effect.
volcano_plot_sim <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, workflow="Protein", mod_var=1, mod_n=0) {
  condition1_columns <- meta$sample[meta$condition == condition1]
  condition2_columns <- meta$sample[meta$condition == condition2]
  label_col <- if (workflow == "Protein") "ProteinNames" else "PTM_Collapse_key"

  filtered_data <- data[
    ,
    c(label_col, condition1_columns, condition2_columns),
    drop = FALSE
  ]
  threshold <- length(condition1_columns) + length(condition2_columns) - 2
  keep <- rowSums(is.na(filtered_data[, -1, drop = FALSE])) < threshold
  filtered_data <- filtered_data[keep, , drop = FALSE]

  x_data <- .numeric_matrix(filtered_data, condition1_columns)
  y_data <- .numeric_matrix(filtered_data, condition2_columns)
  n1_real <- rowSums(!is.na(x_data))
  n2_real <- rowSums(!is.na(y_data))
  valid <- n1_real >= 2 & n2_real >= 2

  if (!any(valid)) {
    stop("No rows have enough replicate values for the selected simulation.", call. = FALSE)
  }

  filtered_data <- filtered_data[valid, , drop = FALSE]
  x_data <- x_data[valid, , drop = FALSE]
  y_data <- y_data[valid, , drop = FALSE]
  n1_real <- n1_real[valid]
  n2_real <- n2_real[valid]

  mean1 <- rowMeans(x_data, na.rm = TRUE)
  mean2 <- rowMeans(y_data, na.rm = TRUE)
  variance1 <- apply(x_data, 1, var, na.rm = TRUE)
  variance2 <- apply(y_data, 1, var, na.rm = TRUE)
  n1 <- if (mod_n %in% c(0, 1)) n1_real else rep(mod_n, length(n1_real))
  n2 <- if (mod_n %in% c(0, 1)) n2_real else rep(mod_n, length(n2_real))

  pooled_variance <- (
    (n1 - 1) * variance1 + (n2 - 1) * variance2
  ) / (n1 + n2 - 2)
  pooled_variance <- pooled_variance * mod_var
  standard_error <- sqrt(pooled_variance * (1 / n1 + 1 / n2))
  log2fc <- mean1 - mean2
  t_statistic <- log2fc / standard_error
  degrees_freedom <- n1 + n2 - 2
  pvals <- 2 * stats::pt(abs(t_statistic), degrees_freedom, lower.tail = FALSE)
  # Rows without variation in either group: no p-value at any projected n,
  # out of the BH family -- the volcano's rule, so the projection at the
  # observed n reproduces the volcano table.
  pvals[without_variation(list(x_data, y_data))] <- NA_real_
  adjusted_pvals <- pvals
  finite <- is.finite(pvals)
  adjusted_pvals[finite] <- p.adjust(pvals[finite], method = "BH")

  significance <- ifelse(
    adjusted_pvals < in_pval & log2fc > in_log2fc,
    "Upregulated",
    ifelse(
      adjusted_pvals < in_pval & log2fc < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )

  significance[!is.finite(pvals)] <- "Unavailable"
  volcano_data <- data.frame(
    Feature = filtered_data[[label_col]],
    log2FC = log2fc,
    pval = pvals,
    adj_pval = adjusted_pvals,
    selected_pval = adjusted_pvals,
    significance = significance,
    neg_log10_selected_pval = -log10(pmax(adjusted_pvals, 1e-300)),
    stringsAsFactors = FALSE
  )
  names(volcano_data)[1] <- label_col

  volcano_plot(
    volcano_data,
    condition1,
    condition2,
    in_pval = in_pval,
    in_log2fc = in_log2fc
  )
}

convert_to_centered <- function(seq) {
  if (!is.character(seq) || !grepl("*", seq, fixed = TRUE)) return(seq)

  star_index <- regexpr("*", seq, fixed = TRUE)[1]
  if (star_index == 1) return(seq)

  modified_residue <- toupper(substr(seq, star_index - 1, star_index - 1))
  clean_sequence <- paste0(
    substr(seq, 1, star_index - 2),
    modified_residue,
    substr(seq, star_index + 1, nchar(seq))
  )
  modified_position <- star_index - 1
  left <- substr(clean_sequence, 1, modified_position - 1)
  right <- substr(clean_sequence, modified_position + 1, nchar(clean_sequence))

  left_tail <- if (nchar(left) >= 7) {
    substr(left, nchar(left) - 6, nchar(left))
  } else {
    paste0(strrep("_", 7 - nchar(left)), left)
  }
  right_tail <- if (nchar(right) >= 7) {
    substr(right, 1, 7)
  } else {
    paste0(right, strrep("_", 7 - nchar(right)))
  }

  paste0(left_tail, modified_residue, right_tail)
}

# Kinase motif windows. The Kinase Library reads "_" as "beyond the protein
# terminus", so a window cut from the peptide alone presents real flanking
# residues as absent. With a FASTA the window is read from the protein at the
# site position named in PTM_Collapse_key; the peptide window is only a
# fallback and `window_source` says which one each row uses. Mirrors
# phospho_tools.site_motif_window and the pip package.

read_fasta <- function(path) {
  lines <- readLines(path, warn = FALSE, encoding = "UTF-8")
  lines <- trimws(lines)
  lines <- lines[nzchar(lines)]
  is_header <- startsWith(lines, ">")
  if (!any(is_header)) return(character(0))
  record <- cumsum(is_header)
  headers <- sub("^>", "", lines[is_header])
  tokens <- vapply(strsplit(headers, "[[:space:]]+"), function(x) if (length(x)) x[1] else "", character(1))
  keys <- vapply(strsplit(tokens, "|", fixed = TRUE), function(parts) {
    if (length(parts) >= 3) parts[2] else paste(parts, collapse = "|")
  }, character(1))
  sequences <- vapply(split(lines, record), function(chunk) paste(chunk[-1], collapse = ""), character(1))
  names(sequences) <- keys
  sequences[!duplicated(keys)]
}

.resolve_fasta <- function(fasta) {
  if (is.null(fasta)) return(NULL)
  if (is.character(fasta) && length(fasta) == 1 && is.null(names(fasta))) return(read_fasta(fasta))
  sequences <- as.character(unlist(fasta))
  names(sequences) <- names(unlist(fasta))
  sequences
}

.parse_site_key <- function(key) {
  if (is.na(key) || !is.character(key)) return(NULL)
  pattern <- "^([^~]*)~(.*)_([A-Za-z])([0-9]+)_M[0-9]+$"
  key <- trimws(key)
  if (!grepl(pattern, key, perl = TRUE)) return(NULL)
  parts <- regmatches(key, regexec(pattern, key, perl = TRUE))[[1]]
  accessions <- trimws(strsplit(parts[2], ";", fixed = TRUE)[[1]])
  accessions <- accessions[nzchar(accessions)]
  if (!length(accessions)) return(NULL)
  list(accessions = accessions, gene = parts[3], residue = toupper(parts[4]), position = as.integer(parts[5]))
}

.protein_window <- function(sequence, position, flank = 7L) {
  centre <- position - 1L
  start <- centre - flank
  end <- centre + flank + 1L
  n <- nchar(sequence)
  core <- toupper(substr(sequence, max(start, 0L) + 1L, min(end, n)))
  paste0(strrep("_", max(0L, -start)), core, strrep("_", max(0L, end - n)))
}

.windows_agree <- function(protein_window, peptide_window) {
  if (!is.character(peptide_window) || nchar(peptide_window) != nchar(protein_window)) return(TRUE)
  pep <- strsplit(peptide_window, "", fixed = TRUE)[[1]]
  prot <- strsplit(protein_window, "", fixed = TRUE)[[1]]
  all(pep == "_" | pep == prot)
}

site_motif_window <- function(key, peptide_sequence, sequences = NULL) {
  peptide_window <- convert_to_centered(peptide_sequence)
  parsed <- .parse_site_key(key)
  protein <- ""; gene <- ""; site <- ""
  if (!is.null(parsed)) {
    protein <- parsed$accessions[1]
    gene <- parsed$gene
    site <- paste0(parsed$residue, parsed$position)
    if (length(sequences)) {
      for (accession in parsed$accessions) {
        if (!accession %in% names(sequences)) next
        sequence <- sequences[[accession]]
        if (is.na(sequence) || parsed$position < 1L || parsed$position > nchar(sequence)) next
        if (toupper(substr(sequence, parsed$position, parsed$position)) != parsed$residue) next
        window <- .protein_window(sequence, parsed$position)
        if (.windows_agree(window, peptide_window)) {
          return(list(UPD_seq = window, Protein = accession, Gene = gene, Site = site, window_source = "protein"))
        }
      }
    }
  }
  list(UPD_seq = as.character(peptide_window), Protein = protein, Gene = gene, Site = site, window_source = "peptide")
}

.ksea_prepare <- function(data, meta) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  if (!"UPD_seq" %in% names(data)) {
    stop("Phosphosite data must contain UPD_seq for Kinase Library.", call. = FALSE)
  }
  working <- data
  # A unique row label keeps the site key and peptide of every row, even when
  # two sites share a peptide window; the volcano keeps row order.
  working$PTM_Collapse_key <- as.character(seq_len(nrow(working)))
  working
}

.ksea_format_volcano <- function(volcano_df, data, fasta) {
  sequences <- .resolve_fasta(fasta)
  if (is.null(sequences)) {
    warning(
      "No FASTA given: Kinase Library motif windows are cut from the peptide sequence only, and flanks ",
      "the peptide does not cover are padded with '_' (read as the protein end by the Kinase ",
      "Library). Pass fasta= with the searched proteome to read windows from the protein.",
      call. = FALSE
    )
  }
  rows <- as.integer(volcano_df$PTM_Collapse_key)
  keys <- if ("PTM_Collapse_key" %in% names(data)) as.character(data$PTM_Collapse_key[rows]) else rep(NA_character_, length(rows))
  peptides <- as.character(data$UPD_seq[rows])
  windows <- lapply(seq_along(rows), function(i) site_motif_window(keys[i], peptides[i], sequences))
  column <- function(name) vapply(windows, function(w) as.character(w[[name]]), character(1))
  columns <- c("log2FC", "pval", "adj_pval", "selected_pval", "significance")
  if ("n_pairs" %in% names(volcano_df)) columns <- c(columns, "n_pairs")
  columns <- c(columns, "neg_log10_selected_pval")
  result <- data.frame(UPD_seq = column("UPD_seq"), stringsAsFactors = FALSE)
  result <- cbind(result, volcano_df[, columns, drop = FALSE])
  result$PTM_Collapse_key <- keys
  result$Protein <- column("Protein")
  result$Gene <- column("Gene")
  result$Site <- column("Site")
  result$window_source <- column("window_source")
  for (name in names(volcano_df)) {
    if (grepl("^n_(imputed|measured|fully_imputed|partially_imputed)__", name) || name == "imputed_values") result[[name]] <- volcano_df[[name]]
  }
  rownames(result) <- NULL
  result
}

kinase_library_data_f <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE, test_type=NULL, fasta=NULL, observed=NULL, localization_cutoff=0) {
  keep <- .localization_keep(data, localization_cutoff)
  data <- data[keep, , drop = FALSE]
  if (!is.null(observed)) observed <- observed[keep, , drop = FALSE]
  working <- .ksea_prepare(data, meta)
  output <- volcano_data_f(
    working, meta, condition1, condition2,
    in_pval, in_log2fc, "Phosphosite", paired, uncorrected, test_type,
    observed = observed
  )
  .ksea_format_volcano(output, data, fasta)
}

kinase_library_data_f_control <- function(data, meta, condition1, condition2, condition1_control, condition2_control, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE, test_type=NULL, fasta=NULL, observed=NULL, localization_cutoff=0) {
  keep <- .localization_keep(data, localization_cutoff)
  data <- data[keep, , drop = FALSE]
  if (!is.null(observed)) observed <- observed[keep, , drop = FALSE]
  working <- .ksea_prepare(data, meta)
  output <- volcano_data_f_control(
    working, meta, condition1, condition2,
    condition1_control, condition2_control,
    in_pval, in_log2fc, "Phosphosite", paired, uncorrected, test_type,
    observed = observed
  )
  .ksea_format_volcano(output, data, fasta)
}

.phosprot_regulation_data <- function(site_results, in_pval, in_log2fc, max_hover_sites, show_phosphosites) {
  site_results$significance <- ifelse(
    site_results$selected_pval < in_pval & site_results$log2FC > in_log2fc,
    "Upregulated",
    ifelse(
      site_results$selected_pval < in_pval & site_results$log2FC < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )
  significant_results <- site_results[
    site_results$significance != "Not significant",
    ,
    drop = FALSE
  ]
  protein_groups <- split(
    seq_len(nrow(significant_results)),
    significant_results$Protein_group,
    drop = TRUE
  )

  truncate_items <- function(items) {
    if (!show_phosphosites) return("")
    if (length(items) <= max_hover_sites) return(paste(items, collapse = ";"))

    paste0(
      paste(head(items, max_hover_sites), collapse = ";"),
      ";... (+", length(items) - max_hover_sites, " more)"
    )
  }

  collapsed <- lapply(names(protein_groups), function(protein) {
    rows <- protein_groups[[protein]]
    group <- significant_results[rows, , drop = FALSE]
    down <- group[group$significance == "Downregulated", , drop = FALSE]
    up <- group[group$significance == "Upregulated", , drop = FALSE]
    down_sites <- as.character(down$PTM_Collapse_key)
    up_sites <- as.character(up$PTM_Collapse_key)
    # paste0 recycles its scalar parts against a zero-length vector, so an empty
    # site list produced the string " ()" rather than nothing. The pip package
    # yields an empty character vector here.
    down_effects <- if (length(down_sites)) {
      paste0(down_sites, " (", sprintf("%.4g", down$log2FC), ")")
    } else {
      character(0)
    }
    up_effects <- if (length(up_sites)) {
      paste0(up_sites, " (", sprintf("%+.4g", up$log2FC), ")")
    } else {
      character(0)
    }

    data.frame(
      Protein_group = protein,
      Downregulated_sites = truncate_items(down_sites),
      Upregulated_sites = truncate_items(up_sites),
      Downregulated_site_effects = truncate_items(down_effects),
      Upregulated_site_effects = truncate_items(up_effects),
      Downregulated_count = length(down_sites),
      Upregulated_count = length(up_sites),
      Downregulated_log2FC_sum = -sum(down$log2FC),
      Upregulated_log2FC_sum = sum(up$log2FC),
      stringsAsFactors = FALSE
    )
  })
  if (length(collapsed)) {
    collapsed <- do.call(rbind, collapsed)
  } else {
    collapsed <- data.frame(
      Protein_group = character(),
      Downregulated_sites = character(),
      Upregulated_sites = character(),
      Downregulated_site_effects = character(),
      Upregulated_site_effects = character(),
      Downregulated_count = integer(),
      Upregulated_count = integer(),
      Downregulated_log2FC_sum = numeric(),
      Upregulated_log2FC_sum = numeric(),
      stringsAsFactors = FALSE
    )
  }
  collapsed$x <- collapsed$Upregulated_log2FC_sum
  collapsed$y <- collapsed$Downregulated_log2FC_sum
  collapsed$color_val <- collapsed$x - collapsed$y
  collapsed
}

phosprot_regulation_data <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE, max_hover_sites=20, show_phosphosites=TRUE, test_type=NULL, localization_cutoff=0) {
  .validate_meta_samples(meta)
  .validate_sample_values(data, meta)
  data <- filter_localization(data, localization_cutoff)
  # The per-protein table behind `phosprot_regulation`, with the same signature
  # as the pip package's function of this name. Split out so the numbers can be
  # read, exported and compared across the three pipelines; `phosprot_regulation`
  # plots exactly this frame. `x` is the cumulative log2FC of significant
  # up-sites, `y` the absolute cumulative log2FC of significant down-sites, and
  # proteins with no significant site are absent.
  site_results <- .volcano_stats(
    data, meta, condition1, condition2, "PTM_Collapse_key",
    paired, uncorrected, "Protein_group", test_type
  )
  collapsed <- .phosprot_regulation_data(
    site_results, in_pval, in_log2fc, max_hover_sites, show_phosphosites
  )
  collapsed
}

phosprot_regulation <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE, max_hover_sites=20, show_phosphosites=TRUE, test_type=NULL, localization_cutoff=0) {
  .require_pkg("plotly")
  collapsed <- phosprot_regulation_data(
    data, meta, condition1, condition2, in_pval, in_log2fc,
    paired, uncorrected, max_hover_sites, show_phosphosites, test_type,
    localization_cutoff = localization_cutoff
  )

  hover_text <- paste0(
    "Protein group: ", collapsed$Protein_group,
    "<br>Upregulated count: ", collapsed$Upregulated_count,
    "<br>Downregulated count: ", collapsed$Downregulated_count,
    "<br>Upregulated site effects: ", collapsed$Upregulated_site_effects,
    "<br>Downregulated site effects: ", collapsed$Downregulated_site_effects
  )

  fig <- plotly::plot_ly(
    collapsed,
    x = ~x,
    y = ~y,
    color = ~color_val,
    colors = c("blue", "grey", "red"),
    text = hover_text,
    hoverinfo = "text",
    type = "scatter",
    mode = "markers",
    marker = list(
      size = 8,
      opacity = 0.7,
      line = list(width = 0.5, color = "DarkSlateGrey")
    )
  )

  plotly::layout(
    fig,
    title = "Cumulative Significant Phosphosite Regulation by Protein",
    xaxis = list(title = "Cumulative Significant Up-Site log2FC"),
    yaxis = list(title = "Cumulative Significant Down-Site |log2FC|"),
    coloraxis = list(colorbar = list(title = "Up score - Down score")),
    template = "plotly_white"
  )
}

rt_vs_pred_rt_plot <- function(
    data_path,
    method = "Hexbin Plot",
    add_line = FALSE,
    bins = 1000,
    header = TRUE,
    width = 8,
    height = 6,
    dpi = 100,
    seed = 69
) {
  data <- read_data(data_path)
  if (!all(c("Predicted.RT", "RT") %in% names(data))) {
    stop("Data must contain 'Predicted.RT' and 'RT' columns.", call. = FALSE)
  }

  finite_rows <- is.finite(data$Predicted.RT) & is.finite(data$RT)
  data <- data[finite_rows, , drop = FALSE]
  if (!nrow(data)) {
    stop("No finite retention-time pairs are available for plotting.", call. = FALSE)
  }

  .set_notebook_plot_size(width, height, units = "in")

  if (method == "Scatter Plot") {
    if (nrow(data) > 100000) {
      selected <- .with_local_seed(seed, function() sample(nrow(data), 100000))
      data <- data[selected, , drop = FALSE]
    }
    plot(
      data$Predicted.RT,
      data$RT,
      pch = 16,
      cex = 0.2,
      col = grDevices::adjustcolor("black", alpha.f = 0.2),
      xlab = "Predicted RT",
      ylab = "Actual RT",
      main = if (header) "Retention Time Plot" else ""
    )
  } else if (method == "Density Plot") {
    smoothScatter(
      data$Predicted.RT,
      data$RT,
      nbin = 200,
      nrpoints = 0,
      colramp = colorRampPalette(c("white", "#6baed6", "#08306b")),
      xlab = "Predicted RT",
      ylab = "Actual RT",
      main = if (header) "Retention Time Plot" else ""
    )
  } else if (method == "Hexbin Plot") {
    .require_pkg("hexbin")
    effective_bins <- min(
      as.integer(bins),
      max(10L, ceiling(sqrt(nrow(data))))
    )
    hexbin::plot(
      hexbin::hexbin(
        data$Predicted.RT,
        data$RT,
        xbins = effective_bins
      ),
      colramp = colorRampPalette(c("white", "#6baed6", "#08306b")),
      xlab = "Predicted RT",
      ylab = "Actual RT",
      main = if (header) "Retention Time Plot" else ""
    )
  } else {
    stop("method must be 'Scatter Plot', 'Density Plot', or 'Hexbin Plot'", call. = FALSE)
  }

  if (add_line) {
    abline(0, 1, col = "red", lty = 2, lwd = 1.5)
  }

  .plot_result()
}

modification_plot <- function(data2_path, meta, id=TRUE, header=TRUE, legend=TRUE, width=10, height=6, dpi=100) {
  data <- if (is.data.frame(data2_path)) {
    data2_path
  } else {
    sanitize_dataframe(read_data(data2_path))
  }
  meta <- .sample_meta(meta, id = id, newline = TRUE)

  wide_data <- .pivot_wide(
    data,
    "Modified.Sequence",
    "File.Name",
    "Precursor.Quantity",
    max
  )
  names(wide_data) <- vapply(names(wide_data), extract_id_or_number, character(1))
  id_map <- setNames(meta$new_sample, meta$id)
  names(wide_data) <- ifelse(
    names(wide_data) %in% names(id_map),
    id_map[names(wide_data)],
    names(wide_data)
  )

  samples <- intersect(meta$new_sample, names(wide_data))
  # UniMod ids must not match longer ids by prefix: "UniMod:4" would otherwise
  # also count UniMod:40-49 and UniMod:4xx. The lookahead needs perl = TRUE.
  modifications <- c(
    Carbamidomethylation = "(?i)UniMod:4(?!\\d)|(?<![A-Za-z])Carbamidomethyl(?:ation)?(?![A-Za-z])",
    Oxidation = "(?i)UniMod:35(?!\\d)|(?<![A-Za-z])Oxidation(?![A-Za-z])",
    Acetylation = "(?i)UniMod:1(?!\\d)|(?<![A-Za-z])Acetyl(?:ation)?(?![A-Za-z])"
  )
  counts <- sapply(modifications, function(pattern) {
    rows <- grepl(pattern, rownames(wide_data), perl = TRUE)
    values <- as.matrix(wide_data[rows, samples, drop = FALSE])
    suppressWarnings(storage.mode(values) <- "numeric")
    colSums(is.finite(values) & values != 0)
  })
  counts <- t(counts)
  keep <- rowSums(counts) > 0
  counts <- counts[keep, , drop = FALSE]
  modification_colors <- c(
    Carbamidomethylation = "blue",
    Oxidation = "red",
    Acetylation = "green"
  )

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- .set_plot_margins(legend = legend, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  barplot(
    counts,
    beside = TRUE,
    names.arg = samples,
    las = 2,
    cex.names = 0.65,
    col = modification_colors[rownames(counts)],
    border = NA,
    xlab = "Sample",
    ylab = "Number of modified peptides",
    main = if (header) "Modifications per sample" else ""
  )

  if (legend && nrow(counts)) {
    legend(
      "topright",
      inset = c(-0.3, 0),
      legend = rownames(counts),
      fill = modification_colors[rownames(counts)],
      title = "Modification",
      border = NA,
      bty = "n"
    )
  }

  .plot_result()
}

.PROTEASE_LABELS <- c(trypsin = "Trypsin", trypsin_lysc = "Trypsin / Lys-C")

normalize_protease <- function(value = "trypsin") {
  key <- tolower(trimws(as.character(value)[1]))
  key <- gsub("[-/]", "_", key)
  key <- gsub("__", "_", key)
  if (key %in% c("trypsin_lysc", "trypsin_lys_c", "trypsinlysc")) return("trypsin_lysc")
  if (identical(key, "trypsin")) return("trypsin")
  stop("Protease must be 'trypsin' or 'trypsin_lysc'.", call. = FALSE)
}

# A missed cleavage is a cleavable residue that is neither the C-terminal
# residue -- that one is the expected cut site -- nor blocked by a following
# proline. Trypsin is blocked at both K-P and R-P; a trypsin/Lys-C mix still
# cleaves K-P because Lys-C is not proline-inhibited, while R-P stays blocked
# because trypsin is the only activity cutting R. The lookaheads need perl=TRUE
# and are equivalent to the Python implementations.
count_missed_cleavages <- function(sequence, protease = "trypsin") {
  pattern <- if (normalize_protease(protease) == "trypsin_lysc") {
    "K(?=.)|R(?=[^P])"
  } else {
    "[KR](?=[^P])"
  }
  matches <- gregexpr(pattern, toupper(as.character(sequence)), perl = TRUE)
  vapply(matches, function(m) if (m[1] == -1L) 0L else length(m), integer(1))
}

missed_cleavage_plot <- function(data2_path, meta, id=TRUE, text=TRUE, text_size=8, header=TRUE, protease="trypsin", width=10, height=6, dpi=100) {
  resolved_protease <- normalize_protease(protease)
  data <- sanitize_dataframe(read_data(data2_path))
  file_col <- grep("file", names(data), ignore.case = TRUE, value = TRUE)[1]
  sequence_col <- grep(
    "stripped.*sequence",
    names(data),
    ignore.case = TRUE,
    value = TRUE
  )[1]

  wide_data <- .pivot_wide(
    data,
    sequence_col,
    file_col,
    "Precursor.Quantity",
    max
  )
  sample_map <- .peptide_sample_map(names(wide_data), meta$sample)
  meta <- .sample_meta(meta, id = id, newline = TRUE)
  labels <- setNames(meta$new_sample, meta$sample)
  id_map <- setNames(labels[unname(sample_map)], names(sample_map))
  names(wide_data) <- ifelse(
    names(wide_data) %in% names(id_map),
    id_map[names(wide_data)],
    names(wide_data)
  )

  samples <- intersect(meta$new_sample, names(wide_data))
  missed_cleavages <- count_missed_cleavages(rownames(wide_data), resolved_protease)
  cleavage_levels <- sort(unique(missed_cleavages))

  percentages <- sapply(samples, function(sample) {
    present <- !is.na(wide_data[[sample]])
    counts <- table(factor(missed_cleavages[present], levels = cleavage_levels))
    as.numeric(counts) / sum(counts) * 100
  })
  if (is.null(dim(percentages))) {
    percentages <- matrix(percentages, nrow = length(cleavage_levels), ncol = length(samples))
  }
  rownames(percentages) <- cleavage_levels
  colnames(percentages) <- samples
  colors <- grDevices::hcl.colors(length(cleavage_levels), "Set 2")

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- .set_plot_margins(legend = TRUE, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    percentages,
    names.arg = samples,
    las = 2,
    cex.names = 0.65,
    col = colors,
    border = NA,
    ylim = c(0, 100),
    ylab = "Peptides by missed cleavages (%)",
    main = if (header) {
      paste0("Missed cleavages per sample (", .PROTEASE_LABELS[[resolved_protease]], ")")
    } else {
      ""
    }
  )

  if (text) {
    with_missed <- colSums(percentages[cleavage_levels > 0, , drop = FALSE])
    text(
      mids,
      3,
      labels = sprintf("%.1f%%", with_missed),
      cex = text_size / 10,
      adj = c(0.5, 0)
    )
  }

  legend(
    "topright",
    inset = c(-0.28, 0),
    legend = cleavage_levels,
    fill = colors,
    title = "Number",
    border = NA,
    bty = "n"
  )

  .plot_result()
}

.peptide_starts <- function(sequence, peptide) {
  width <- nchar(peptide)
  if (width == 0L || width > nchar(sequence)) return(integer(0))
  starts <- seq_len(nchar(sequence) - width + 1L)
  starts[substring(sequence, starts, starts + width - 1L) == peptide]
}

# Peptides of the protein with at least one quantity above 0, as in the web app:
# a precursor listed without a quantity anywhere was not observed.
.protein_peptides <- function(data, protein) {
  members <- strsplit(as.character(data$ProteinNames), ";", fixed = TRUE)
  selected <- vapply(members, function(names) protein %in% trimws(names), logical(1))
  if ("Precursor.Quantity" %in% names(data)) {
    quantity <- suppressWarnings(as.numeric(data[["Precursor.Quantity"]]))
    selected <- selected & is.finite(quantity) & quantity > 0
  }
  unique(as.character(na.omit(data$Stripped.Sequence[selected])))
}

calculate_coverage <- function(data_path, db, protein) {
  data <- read_data(data_path)
  peptides <- .protein_peptides(data, protein)
  sequence <- db$V1[match(protein, db$name)]
  if (is.na(sequence)) {
    stop(
      "No sequence found in the selected database for protein: ",
      protein,
      call. = FALSE
    )
  }

  coverage_mask <- rep(FALSE, nchar(sequence))
  for (peptide in peptides) {
    for (start in .peptide_starts(sequence, peptide)) {
      coverage_mask[start:(start + nchar(peptide) - 1)] <- TRUE
    }
  }

  round(mean(coverage_mask) * 100, 2)
}

vis_coverage <- function(data, db, protein, chunk_size=30) {
  peptides <- .protein_peptides(data, protein)
  sequence <- db$V1[match(protein, db$name)]
  if (is.na(sequence)) {
    return(paste0("No sequence found in the selected database for protein: ", protein))
  }

  sequence_length <- nchar(sequence)
  tracks <- strrep("-", sequence_length)
  for (peptide in peptides) {
    for (start in .peptide_starts(sequence, peptide)) {
      placed <- FALSE
      for (track_index in seq_along(tracks)) {
        region <- substr(
          tracks[track_index],
          start,
          start + nchar(peptide) - 1
        )
        if (region == strrep("-", nchar(peptide))) {
          substr(
            tracks[track_index],
            start,
            start + nchar(peptide) - 1
          ) <- peptide
          placed <- TRUE
          break
        }
      }

      if (!placed) {
        new_track <- strrep("-", sequence_length)
        substr(new_track, start, start + nchar(peptide) - 1) <- peptide
        tracks <- c(tracks, new_track)
      }
    }
  }

  starts <- seq(1, sequence_length, by = chunk_size)
  blocks <- lapply(starts, function(start) {
    end <- min(sequence_length, start + chunk_size - 1)
    c(
      as.character(start),
      rev(substr(tracks, start, end)),
      substr(sequence, start, end),
      ""
    )
  })
  paste(unlist(blocks), collapse = "\n")
}

fasta_to_dataframe <- function(fasta_path) {
  lines <- readLines(fasta_path, warn = FALSE)
  header_indices <- which(startsWith(lines, ">"))
  sequence_ends <- c(header_indices[-1] - 1, length(lines))
  headers <- sub("^>", "", lines[header_indices])
  sequences <- vapply(seq_along(header_indices), function(index) {
    paste(lines[(header_indices[index] + 1):sequence_ends[index]], collapse = "")
  }, character(1))

  header_parts <- strsplit(headers, "|", fixed = TRUE)
  data.frame(
    full_header = headers,
    V1 = sequences,
    name = vapply(header_parts, tail, character(1), 1),
    accession = vapply(header_parts, function(parts) {
      if (length(parts) > 1) parts[2] else parts[1]
    }, character(1)),
    stringsAsFactors = FALSE
  )
}

# SINGLE PROTEIN
compare_prot_line <- function(data, meta, conditions, inputs, id=TRUE, header=TRUE, legend=TRUE, workflow="Protein", plot_colors=NULL, width=10, height=6, dpi=100) {
  meta <- .sample_meta(meta, id = id, newline = TRUE)
  renamed_data <- .rename_samples(data, meta)
  key_col <- .workflow_col(workflow)

  ordered_samples <- unlist(lapply(conditions, function(condition) {
    meta$new_sample[meta$condition == condition]
  }))
  filtered_data <- renamed_data[
    renamed_data[[key_col]] %in% inputs,
    c(key_col, ordered_samples),
    drop = FALSE
  ]
  if (!nrow(filtered_data)) {
    stop("No matching features were found.", call. = FALSE)
  }

  values <- .numeric_matrix(filtered_data, ordered_samples)
  labels <- as.character(filtered_data[[key_col]])
  unique_labels <- unique(labels)
  aggregated_values <- matrix(
    NA_real_,
    nrow = length(unique_labels),
    ncol = ncol(values),
    dimnames = list(unique_labels, colnames(values))
  )
  for (label_index in seq_along(unique_labels)) {
    matching <- labels == unique_labels[label_index]
    for (sample_index in seq_len(ncol(values))) {
      observed <- values[matching, sample_index]
      observed <- observed[is.finite(observed)]
      if (length(observed)) {
        aggregated_values[label_index, sample_index] <- median(observed)
      }
    }
  }
  values <- aggregated_values
  labels <- unique_labels
  colors <- .plot_colors(length(labels), plot_colors)

  .set_notebook_plot_size(width, height, units = "in")
  old_par <- .set_plot_margins(legend = legend, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  matplot(
    t(values),
    type = "o",
    pch = 16,
    lty = 1,
    lwd = 1.5,
    col = colors,
    xaxt = "n",
    xlab = "Sample",
    ylab = "Log2 intensity",
    main = if (header) paste(workflow, "Expression Across Samples") else ""
  )
  axis(1, seq_along(ordered_samples), ordered_samples, las = 2, cex.axis = 0.65)
  grid(col = "#d9d9d9", lty = 1)

  if (legend) {
    legend(
      "topright",
      inset = c(-0.32, 0),
      legend = labels,
      col = colors,
      lty = 1,
      lwd = 1.5,
      pch = 16,
      title = workflow,
      bty = "n"
    )
  }

  .plot_result()
}

single_protein_values <- function(data, meta, protein) {
  # The values boxplot_int_single_prot draws for one protein, as a table. The
  # protein is looked up in the row names, or else in the first column. When
  # several rows match, each sample gets the median of its measured values.
  # Returns condition, sample and value in metadata order; samples without a
  # value are left out.
  protein_data <- if (protein %in% rownames(data)) {
    data[which(rownames(data) == protein), , drop = FALSE]
  } else {
    data[as.character(data[[1]]) == as.character(protein), , drop = FALSE]
  }
  if (!nrow(protein_data)) {
    stop("No data found for protein: ", protein, call. = FALSE)
  }
  samples <- as.character(meta$sample)
  present <- samples %in% colnames(protein_data)
  samples <- samples[present]
  conditions <- as.character(meta$condition)[present]
  sample_matrix <- .numeric_matrix(protein_data, samples)
  values <- vapply(seq_along(samples), function(sample_index) {
    observed <- sample_matrix[, sample_index]
    observed <- observed[is.finite(observed)]
    if (length(observed)) median(observed) else NA_real_
  }, numeric(1))
  keep <- is.finite(values)
  table <- data.frame(condition = conditions[keep], sample = samples[keep], value = values[keep], stringsAsFactors = FALSE)
  attr(table, "source_rows") <- nrow(protein_data)
  table
}

boxplot_int_single_prot <- function(data, meta, protein, outliers=FALSE, dots=FALSE, header=TRUE, legend=TRUE, plot_colors=NULL, width=8, height=6, dpi=100, seed=69) {
  table <- single_protein_values(data, meta, protein)
  conditions <- unique(meta$condition)
  intensities <- lapply(conditions, function(condition) {
    table$value[table$condition == as.character(condition)]
  })
  keep <- lengths(intensities) > 0
  intensities <- intensities[keep]
  conditions <- conditions[keep]

  .set_notebook_plot_size(width, height, units = "in")
  if (!length(intensities)) {
    plot.new()
    text(0.5, 0.5, "No measured values in the selected conditions")
    return(.plot_result())
  }

  colors <- .plot_colors(length(conditions), plot_colors)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  all_values <- unlist(intensities, use.names = FALSE)
  y_limits <- range(all_values, finite = TRUE)
  if (diff(y_limits) == 0) y_limits <- y_limits + c(-0.5, 0.5)
  plot(
    NA,
    xlim = c(0.5, length(conditions) + 0.5),
    ylim = y_limits,
    xaxt = "n",
    xlab = "Condition",
    ylab = "log2 Intensity",
    main = if (header) {
      source_rows <- attr(table, "source_rows")
      source_suffix <- if (source_rows > 1) {
        paste0("\none median per sample across ", source_rows, " matching source row(s)")
      } else {
        ""
      }
      paste0("Measured ", protein, " intensity values (log2)", source_suffix)
    } else {
      ""
    }
  )
  axis(
    1,
    seq_along(conditions),
    paste0(conditions, "\n(n=", lengths(intensities), ")"),
    las = 2
  )

  box_positions <- which(lengths(intensities) >= 3)
  if (length(box_positions)) {
    boxplot(
      intensities[box_positions],
      at = box_positions,
      add = TRUE,
      axes = FALSE,
      col = colors[box_positions],
      border = "black",
      outline = outliers,
      medcol = "firebrick",
      medlwd = 2
    )
  }

  .with_local_seed(seed, function() {
    for (i in seq_along(intensities)) {
      values <- intensities[[i]]
      if (length(values) < 3) {
        visible_values <- values
      } else if (dots) {
        values <- intensities[[i]]
        quartiles <- quantile(values, c(0.25, 0.75))
        iqr <- diff(quartiles)
        visible_values <- values[
          values >= quartiles[1] - 1.5 * iqr &
            values <= quartiles[2] + 1.5 * iqr
        ]
      } else {
        next
      }
      points(
        jitter(rep(i, length(visible_values)), amount = 0.05),
        visible_values,
        pch = 16,
        cex = 0.8,
        col = grDevices::adjustcolor(colors[i], alpha.f = 0.8)
      )
    }
  })

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = conditions,
      fill = colors,
      border = "black",
      bty = "n"
    )
  }

  .plot_result()
}

phossite_on_prot_regulation <- function(data, meta, protein, conditions=NULL, id=TRUE, figsize=c(12,8), cmap_name="plasma", filter_M2=FALSE, cluster_rows=FALSE, cluster_cols=FALSE, value_type="log2", header=TRUE, localization_cutoff=0) {
  data <- filter_localization(data, localization_cutoff)
  protein_data <- data[
    grepl(protein, data$Protein_group, ignore.case = TRUE),
    ,
    drop = FALSE
  ]
  if (!nrow(protein_data)) {
    stop("No data found for protein '", protein, "'", call. = FALSE)
  }

  meta_filtered <- if (is.null(conditions)) {
    meta
  } else {
    meta[meta$condition %in% conditions, , drop = FALSE]
  }
  meta_filtered <- .sample_meta(meta_filtered, id = id, newline = TRUE)

  if (filter_M2) {
    protein_data <- protein_data[
      endsWith(protein_data$PTM_Collapse_key, "_M1"),
      ,
      drop = FALSE
    ]
  }

  heatmap_data <- .numeric_matrix(protein_data, meta_filtered$sample)
  colnames(heatmap_data) <- meta_filtered$new_sample
  rownames(heatmap_data) <- sub("^.*~", "", protein_data$PTM_Collapse_key)
  if (filter_M2) rownames(heatmap_data) <- sub("_M1$", "", rownames(heatmap_data))

  value_type <- tolower(value_type)
  if (value_type == "z") {
    heatmap_data <- row_zscore(heatmap_data)
    color_label <- "Z-score"
    zlim <- c(-2.5, 2.5)
  } else if (value_type == "log2") {
    color_label <- "log2 Intensity"
    zlim <- NULL
  } else {
    stop("value_type must be 'log2' or 'z'", call. = FALSE)
  }

  heatmap_data[!is.finite(heatmap_data)] <- NA_real_
  heatmap_data <- heatmap_data[rowSums(is.finite(heatmap_data)) > 0, , drop = FALSE]
  if (!nrow(heatmap_data)) {
    stop("No informative phosphosite rows remain after heatmap transformation.", call. = FALSE)
  }

  cluster_data <- NULL
  if ((cluster_rows && nrow(heatmap_data) > 1) ||
      (cluster_cols && ncol(heatmap_data) > 1)) {
    dropped_info <- .drop_incomplete_features(heatmap_data, "phosphosite heatmap")
    cluster_data <- dropped_info$matrix
    heatmap_data <- heatmap_data[dropped_info$kept, , drop = FALSE]
    .warn_dropped_features(dropped_info$dropped, dropped_info$total)
  }
  if (cluster_rows && nrow(heatmap_data) > 1) {
    row_order <- hclust(dist(cluster_data), method = "average")$order
    heatmap_data <- heatmap_data[row_order, , drop = FALSE]
    cluster_data <- cluster_data[row_order, , drop = FALSE]
  }
  if (cluster_cols && ncol(heatmap_data) > 1) {
    column_order <- hclust(dist(t(cluster_data)), method = "average")$order
    heatmap_data <- heatmap_data[, column_order, drop = FALSE]
  }

  .set_notebook_plot_size(figsize[1], figsize[2], units = "in")
  .plot_heatmap(
    heatmap_data,
    title = if (header) {
      paste0(
        protein,
        " (",
        if (value_type == "z") "Z-transformed" else "log2 Intensities",
        ")"
      )
    } else {
      ""
    },
    ylab = "PTM site",
    color_label = color_label,
    zlim = zlim,
    palette = colorRampPalette(c("#0d0887", "#cc4778", "#f0f921"))(100)
  )
}

# PHOSPHO-SPECIFIC
.phossite_coverage_counts <- function(data, meta, is_log2=TRUE) {
  values <- as.matrix(data[as.character(meta$sample)])
  storage.mode(values) <- "numeric"
  observed <- is.finite(values)
  if (!is_log2) observed <- observed & values != 0
  localization <- suppressWarnings(as.numeric(data$PTM_localization))
  if (!length(localization)) localization <- rep(NA_real_, nrow(data))
  localization[!is.finite(localization) | localization < 0 | localization > 1] <- NA_real_
  rbind(
    "Class I" = colSums(observed[which(localization >= .75), , drop=FALSE]),
    "Not Class I" = colSums(observed[which(localization < .75), , drop=FALSE]),
    "Unclassified" = colSums(observed[which(is.na(localization)), , drop=FALSE])
  )
}

phossite_coverage_plot <- function(data, meta, id=FALSE, header=TRUE, legend=TRUE, width=20, height=10, dpi=300, color_classI="blue", color_notclassI="orange", is_log2=TRUE, localization_cutoff=0) {
  data <- filter_localization(data, localization_cutoff)
  counts <- .phossite_coverage_counts(data, meta, is_log2)
  meta <- .sample_meta(meta, id=id, newline=TRUE, zero_based=TRUE)
  if (!any(counts["Unclassified", ] > 0)) counts <- counts[1:2, , drop=FALSE]
  colors <- c(color_classI, color_notclassI, "#94a3b8")[seq_len(nrow(counts))]
  .set_notebook_plot_size(width, height)
  old_par <- .set_plot_margins(legend=legend, rotated_labels=TRUE)
  on.exit(par(old_par), add=TRUE)
  barplot(counts, names.arg=meta$new_sample, las=2, cex.names=.65, col=colors,
    border=NA, xlab="Sample", ylab=if (header) "Number of phosphosites" else "Number",
    main=if (header) "Phosphosites per sample" else "")
  if (legend) legend("topright", inset=c(-.28, 0), legend=rownames(counts), fill=colors, border=NA, bty="n")
  .plot_result()
}

sty_plot <- function(data, localization_cutoff=0) {
  data <- filter_localization(data, localization_cutoff)
  matches <- regexec(
    "~[^_]+_([STY])[0-9]+_",
    as.character(data$PTM_Collapse_key)
  )
  residues <- vapply(
    regmatches(as.character(data$PTM_Collapse_key), matches),
    function(value) if (length(value) > 1) value[2] else NA_character_,
    character(1)
  )

  counts <- table(factor(residues, levels = c("S", "T", "Y")))
  short_matches <- regexec("(^|_)([STY])[0-9]+(_|$)", as.character(data$PTM_Collapse_key))
  short_residues <- vapply(regmatches(as.character(data$PTM_Collapse_key), short_matches),
    function(value) if (length(value) > 2) value[3] else NA_character_, character(1))
  residues[is.na(residues)] <- short_residues[is.na(residues)]
  counts <- table(factor(residues, levels = c("S", "T", "Y")))
  if (anyNA(residues)) counts <- c(counts, Unparsed = sum(is.na(residues)))
  total <- sum(counts)
  percentages <- if (total > 0) counts / total * 100 else counts * 0
  colors <- c(S = "#4C78A8", T = "#F58518", Y = "#54A24B")

  old_par <- par(mar = c(4.5, 4.5, 3.5, 4.5))
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    counts,
    col = c(colors, Unparsed = "#64748b")[names(counts)],
    border = "black",
    lwd = 0.6,
    ylim = c(0, max(1, max(counts) * 1.13)),
    main = "Modified S/T/Y Site Counts",
    xlab = "Peptide",
    ylab = "Count"
  )
  grid(nx = NA, ny = NULL, col = grDevices::adjustcolor("grey", alpha.f = 0.25))
  text(
    mids,
    counts,
    labels = sprintf("%.1f%%", percentages),
    pos = 3,
    font = 2,
    cex = 0.9
  )

  if (total > 0) {
    count_ticks <- pretty(c(0, max(counts)))
    axis(4, at = count_ticks, labels = sprintf("%.0f", count_ticks / total * 100))
    mtext("Share of sites (%)", side = 4, line = 2.5)
  }

  .plot_result()
}

phossite_coverage_plot_summary <- function(data, meta, header=TRUE, legend=TRUE, width=20, height=10, dpi=300, color_classI="blue", color_notclassI="orange", seed=69, is_log2=TRUE, localization_cutoff=0) {
  data <- filter_localization(data, localization_cutoff)
  counts <- .phossite_coverage_counts(data, meta, is_log2)
  if (!any(counts["Unclassified", ] > 0)) counts <- counts[1:2, , drop=FALSE]
  conditions <- unique(as.character(meta$condition))
  groups <- lapply(conditions, function(condition) counts[, meta$condition == condition, drop=FALSE])
  means <- do.call(cbind, lapply(groups, rowMeans))
  sds <- do.call(cbind, lapply(groups, function(group) apply(group, 1, sd)))
  sds[!is.finite(sds)] <- 0
  colors <- c(color_classI, color_notclassI, "#94a3b8")[seq_len(nrow(counts))]
  .set_notebook_plot_size(width, height)
  old_par <- .set_plot_margins(legend=legend, rotated_labels=TRUE)
  on.exit(par(old_par), add=TRUE)
  mids <- barplot(means, beside=TRUE, names.arg=conditions, las=2, col=colors,
    border=NA, ylim=c(0, max(1, max(means + sds) * 1.1)),
    ylab=if (header) "Number of phosphosites" else "Number",
    main=if (header) "Phosphosites per condition" else "")
  nonzero <- sds > 0
  if (any(nonzero)) arrows(mids[nonzero], pmax(0, means - sds)[nonzero],
    mids[nonzero], (means + sds)[nonzero], angle=90, code=3, length=.04)
  .with_local_seed(seed, function() {
    for (i in seq_along(groups)) for (j in seq_len(nrow(counts))) {
      values <- groups[[i]][j, ]
      points(jitter(rep(mids[j, i], length(values)), amount=.04), values,
        pch=16, cex=.7, col=grDevices::adjustcolor("black", alpha.f=.7))
    }
  })
  if (legend) legend("topright", inset=c(-.28, 0), legend=rownames(counts), fill=colors, border=NA, bty="n")
  .plot_result()
}

simple_phos_site_plot <- function(data, filter_value=0, width_cm=15, height_cm=10, dpi=100, color="skyblue") {
  filtered_data <- data[data$PTM_localization >= filter_value, , drop = FALSE]
  cleaned_sequences <- toupper(gsub("[^[:alnum:]_]", "", filtered_data$UPD_seq))
  counts <- c(
    Phosphoproteins = length(unique(filtered_data$Protein_group)),
    Phosphopeptides = length(unique(cleaned_sequences)),
    Phosphosites = length(unique(filtered_data$PTM_Collapse_key))
  )
  counts <- sort(counts)

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- par(mar = c(4, 9, 2, 3))
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    counts,
    horiz = TRUE,
    col = color,
    border = NA,
    axes = FALSE,
    xlim = c(0, max(counts) * 1.12),
    xlab = "",
    ylab = ""
  )
  axis(2, at = mids, labels = names(counts), las = 2)
  text(counts + max(counts) * 0.01, mids, counts, pos = 4, font = 2)
  box(bty = "l")

  .plot_result()
}

.normalize_ksea_results <- function(data) {
  if (anyDuplicated(names(data))) stop("Kinase Library result column names must be unique.", call.=FALSE)
  keys <- gsub("[^a-z0-9]", "", tolower(gsub("\u2082", "2", names(data), fixed=TRUE)))
  numeric_field <- function(aliases, effect=FALSE) {
    result <- rep(NA_real_, nrow(data))
    columns <- which(keys %in% aliases)
    if (!length(columns)) stop("Each Kinase Library row requires a frequency factor and adjusted p-value.", call.=FALSE)
    for (column in columns) {
      text <- as.character(data[[column]])
      supplied <- !is.na(text) & nzchar(trimws(text))
      values <- suppressWarnings(as.numeric(text))
      if (any(supplied & !is.finite(values))) stop("Kinase Library values must be finite numeric values.", call.=FALSE)
      if (effect && keys[column] == "frequencyfactor") {
        if (any(supplied & values <= 0)) stop("Raw Frequency Factor values must be positive.", call.=FALSE)
        values <- log2(values)
      } else if (!effect && any(supplied & (values < 0 | values > 1))) {
        stop("Adjusted p-values must be between 0 and 1.", call.=FALSE)
      }
      overlap <- supplied & !is.na(result)
      if (any(abs(result[overlap] - values[overlap]) > 1e-12 + 1e-10 * abs(values[overlap]))) {
        stop("Conflicting Kinase Library result columns; provide consistent values.", call.=FALSE)
      }
      take <- supplied & is.na(result)
      result[take] <- values[take]
    }
    if (anyNA(result)) stop("Each Kinase Library row requires a frequency factor and adjusted p-value.", call.=FALSE)
    result
  }
  if (!nrow(data)) return(data.frame(Kinase=character(), frequency_factor=numeric(), adjusted_pvalue=numeric()))
  effect <- numeric_field(c("log2frequencyfactor", "frequencyfactor"), TRUE)
  probability <- numeric_field(c("adjustedpvalue", "adjustedp"))
  labels <- rep(NA_character_, nrow(data))
  for (alias in c("kinase", "genename", "gene")) {
    for (column in which(keys == alias)) {
      values <- as.character(data[[column]])
      take <- is.na(labels) & !is.na(values) & nzchar(trimws(values))
      labels[take] <- values[take]
    }
  }
  labels[is.na(labels)] <- as.character(effect[is.na(labels)])
  data.frame(Kinase=labels, frequency_factor=effect, adjusted_pvalue=probability)
}

kinase_library_volcano <- function(data_st, data_tnc, pval_thresh=0.1, header=TRUE, condition1=NULL, condition2=NULL) {
  .require_pkg("plotly")

  data <- rbind(.normalize_ksea_results(data_st), .normalize_ksea_results(data_tnc))
  if (!nrow(data)) stop("Uploaded Kinase Library result files are empty.", call.=FALSE)
  data$neg_log10_pval <- -log10(pmax(data$adjusted_pvalue, 1e-300))
  # A significant frequency factor is motif enrichment among up- or
  # down-regulated sites, not kinase activity; the classes say so.
  data$Regulation <- ifelse(
    data$adjusted_pvalue < pval_thresh & data$frequency_factor > 0,
    "Enriched in up-regulated sites",
    ifelse(
      data$adjusted_pvalue < pval_thresh & data$frequency_factor < 0,
      "Enriched in down-regulated sites",
      "Not significant"
    )
  )

  color_mapping <- c(
    "Enriched in up-regulated sites" = "red",
    "Enriched in down-regulated sites" = "blue",
    `Not significant` = "lightgrey"
  )

  fig <- plotly::plot_ly()
  for (regulation in unique(data$Regulation)) {
    normal_rows <- data$Regulation == regulation
    if (any(normal_rows)) {
      subset <- data[normal_rows, , drop = FALSE]
      fig <- plotly::add_trace(
        fig,
        data = subset,
        x = ~frequency_factor,
        y = ~neg_log10_pval,
        type = "scatter",
        mode = "markers",
        name = regulation,
        text = ~Kinase,
        hovertemplate = paste0(
          "Kinase: %{text}<br>",
          "Log2(Frequency Factor): %{x}<br>",
          "-log10(p-value): %{y}<br>",
          "Regulation: ", regulation,
          "<extra></extra>"
        ),
        marker = list(
          color = unname(color_mapping[regulation]),
          size = 10,
          line = list(color = "black", width = 0.5)
        ),
        inherit = FALSE
      )
    }
  }

  title <- if (header && !is.null(condition1) && !is.null(condition2)) {
    paste0("Kinase Library Motif Enrichment: ", condition1, " vs. ", condition2)
  } else if (header) {
    "Kinase Library Motif Enrichment"
  } else {
    NULL
  }
  x_label <- if (!is.null(condition1) && !is.null(condition2)) {
    paste0("log2(Frequency Factor) (", condition1, " - ", condition2, ")")
  } else {
    "log2(Frequency Factor)"
  }

  plotly::layout(
    fig,
    title = title,
    xaxis = list(title = x_label),
    yaxis = list(title = "-log10(Adjusted p-value)"),
    hovermode = "closest",
    height = 600,
    shapes = list(
      list(
        type = "line",
        x0 = min(data$frequency_factor, na.rm = TRUE),
        x1 = max(data$frequency_factor, na.rm = TRUE),
        y0 = -log10(pval_thresh),
        y1 = -log10(pval_thresh),
        line = list(color = "green", dash = "dash")
      )
    )
  )
}

kinase_tree_data_pval <- function(data_st, data_tnc) {
  combined_data <- rbind(data_st, data_tnc)
  required_columns <- c("Gene Name", "Adjusted p-value")

  if (!all(required_columns %in% names(combined_data))) {
    stop(
      "Input must contain 'Gene Name' and 'Adjusted p-value' columns.",
      call. = FALSE
    )
  }

  adjusted_pvalue <- as.numeric(combined_data[["Adjusted p-value"]])
  adjusted_pvalue[is.finite(adjusted_pvalue)] <- pmax(
    adjusted_pvalue[is.finite(adjusted_pvalue)],
    1e-300
  )

  data.frame(
    `Gene Name` = combined_data[["Gene Name"]],
    `-log10(adj_pval)` = -log10(adjusted_pvalue),
    check.names = FALSE
  )
}

kinase_tree_data_fc <- function(data_st, data_tnc) {
  combined_data <- rbind(data_st, data_tnc)
  frequency_factor_column <- grep(
    "Frequency Factor",
    names(combined_data),
    value = TRUE
  )[1]

  if (!"Gene Name" %in% names(combined_data) ||
      is.na(frequency_factor_column)) {
    stop(
      "Input must contain 'Gene Name' and Frequency Factor columns.",
      call. = FALSE
    )
  }

  combined_data[
    ,
    c("Gene Name", frequency_factor_column),
    drop = FALSE
  ]
}

phossite_dist <- function(data, cutoff=0, width=20, height=15, dpi=300, header=TRUE) {
  if (!all(c("Phosphoprotein", "site_num") %in% names(data))) {
    stop("Data must contain 'Phosphoprotein' and 'site_num' columns.", call. = FALSE)
  }

  site_numbers <- suppressWarnings(as.numeric(data$site_num))
  site_numbers <- site_numbers[is.finite(site_numbers)]
  if (cutoff > 0) {
    threshold <- quantile(site_numbers, 1 - cutoff)
    site_numbers <- site_numbers[site_numbers <= threshold]
  }

  counts <- table(site_numbers)
  x_values <- as.integer(names(counts))

  .set_notebook_plot_size(width, height)
  old_par <- par(mar = c(5, 5, 3, 2))
  on.exit(par(old_par), add = TRUE)

  barplot(
    as.numeric(counts),
    names.arg = x_values,
    col = .tab10[1],
    border = NA,
    xlab = "Number of phosphosites per phosphoprotein",
    ylab = "Frequency",
    main = if (header) "Distribution of phosphosite counts per protein" else "",
    las = 1,
    cex.names = 0.7
  )

  .plot_result()
}

# COMPARISON
correlation_xy_intensity_single <- function(data, sample1, sample2, alias1=NULL, alias2=NULL, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=TRUE) {
  valid_data <- data[, c(sample1, sample2), drop = FALSE]
  valid_data <- valid_data[complete.cases(valid_data), , drop = FALSE]
  if (!nrow(valid_data)) {
    stop("No overlapping proteins with intensity in both samples.", call. = FALSE)
  }

  x <- as.numeric(valid_data[[sample1]])
  y <- as.numeric(valid_data[[sample2]])
  correlation <- cor.test(x, y, method = "pearson")
  label1 <- if (!is.null(alias1) && nzchar(trimws(alias1))) trimws(alias1) else sample1
  label2 <- if (!is.null(alias2) && nzchar(trimws(alias2))) trimws(alias2) else sample2
  fit <- lm(y ~ x)
  coefficients <- coef(fit)

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- par(mar = c(5, 5, 4, 2))
  on.exit(par(old_par), add = TRUE)

  plot(
    x,
    y,
    pch = 21,
    bg = grDevices::adjustcolor(color, alpha.f = 0.7),
    col = "black",
    cex = sqrt(dot_size) / 4,
    xlab = paste(label1, "(log2 intensity)"),
    ylab = paste(label2, "(log2 intensity)"),
    main = if (show_header) {
      sprintf(
        "%s vs %s\nPearson r=%.3f, p=%.2e",
        label1,
        label2,
        unname(correlation$estimate),
        correlation$p.value
      )
    } else {
      ""
    }
  )
  abline(fit, col = "red", lwd = 2)
  grid(col = "#d9d9d9", lty = 2)
  legend(
    "topleft",
    legend = sprintf("Fit: y=%.2fx%+.2f", coefficients[2], coefficients[1]),
    col = "red",
    lwd = 2,
    bty = "n"
  )

  .plot_result()
}

correlation_xy_intensity <- function(data, meta, condition1, condition2, alias1=NULL, alias2=NULL, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=TRUE, min_present=1) {
  condition1_samples <- meta$sample[meta$condition == condition1]
  condition2_samples <- meta$sample[meta$condition == condition2]
  if (!length(condition1_samples) || !length(condition2_samples)) {
    stop("One or both conditions have no associated samples.", call. = FALSE)
  }

  # min_present = 1 (the default) reports every mean. Raise it to drop means that
  # rest on fewer replicates than that, which would otherwise be plotted at the
  # same weight as a fully observed one.
  mean1 <- condition_mean(data, condition1_samples, min_present = min_present)$mean
  mean2 <- condition_mean(data, condition2_samples, min_present = min_present)$mean
  valid <- is.finite(mean1) & is.finite(mean2)
  if (!any(valid)) {
    stop("No overlapping proteins with intensity in both conditions.", call. = FALSE)
  }

  plot_data <- data.frame(condition1 = mean1[valid], condition2 = mean2[valid])
  label1 <- alias1 %||% condition1
  label2 <- alias2 %||% condition2

  correlation_xy_intensity_single(
    plot_data,
    "condition1",
    "condition2",
    alias1 = paste(label1, "mean"),
    alias2 = paste(label2, "mean"),
    color = color,
    dot_size = dot_size,
    width_cm = width_cm,
    height_cm = height_cm,
    dpi = dpi,
    show_header = FALSE
  )

  if (show_header) {
    correlation <- cor.test(mean1[valid], mean2[valid], method = "pearson")
    title(
      main = sprintf(
        "%s vs %s\nPearson r=%.3f, p=%.2e",
        label1,
        label2,
        unname(correlation$estimate),
        correlation$p.value
      )
    )
  }

  .plot_result()
}

.venn_base <- function(sets, labels, colors=NULL, show_header=TRUE) {
  .require_pkg("VennDiagram")

  colors <- colors %||% .tab10[seq_along(sets)]
  # With file logging off, VennDiagram logs every argument to the console as
  # INFO messages instead; they say nothing about the result.
  venn <- suppressMessages(VennDiagram::venn.diagram(
    x = sets,
    category.names = labels,
    filename = NULL,
    output = TRUE,
    fill = colors,
    alpha = rep(0.5, length(sets)),
    col = colors,
    lwd = 2,
    cex = 1.1,
    cat.cex = 1,
    cat.col = colors,
    main = if (show_header) "Overlap" else NULL,
    main.cex = 1.3,
    # Without this the package writes a futile.logger file into the user's
    # working directory on every call, one per venn drawn.
    disable.logging = TRUE
  ))

  grid::grid.newpage()
  grid::grid.draw(grid::grobTree(children = do.call(grid::gList, venn)))
  invisible(venn)
}

overlap_plot_single <- function(
    data,
    sample1,
    sample2,
    sample3 = NULL,
    width = 7,
    height = 7,
    dpi = 300,
    labels = NULL,
    colors = NULL,
    show_header = TRUE,
    data_scale = "log2"
) {
  .set_notebook_plot_size(width, height, units = "in")

  samples <- c(sample1, sample2, sample3)
  data <- .prepare_intensity_data(data, samples[!is.na(samples)], data_scale)

  sets <- list(
    rownames(data)[!is.na(data[[sample1]])],
    rownames(data)[!is.na(data[[sample2]])]
  )
  default_labels <- c(sample1, sample2)

  if (!is.null(sample3)) {
    sets[[3]] <- rownames(data)[
      !is.na(data[[sample3]])
    ]
    default_labels <- c(default_labels, sample3)
  }

  names(sets) <- labels %||% default_labels
  .venn_base(
    sets,
    labels = names(sets),
    colors = colors,
    show_header = show_header
  )
}

overlap_plot_condition <- function(
    data,
    meta,
    condition1,
    condition2,
    condition3 = NULL,
    width = 7,
    height = 7,
    dpi = 300,
    labels = NULL,
    colors = NULL,
    show_header = TRUE,
    data_scale = "log2",
    min_present = 1
) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  if (length(min_present) != 1 || !is.finite(min_present) || min_present < 1 || min_present != floor(min_present)) {
    stop("min_present must be a positive integer.", call. = FALSE)
  }

  get_set <- function(condition) {
    samples <- meta$sample[meta$condition == condition]
    if (length(samples) < min_present) stop("Condition has fewer samples than min_present.", call. = FALSE)
    present <- rowSums(!is.na(data[, samples, drop = FALSE])) >= min_present
    rownames(data)[present]
  }

  sets <- list(get_set(condition1), get_set(condition2))
  default_labels <- c(condition1, condition2)
  if (!is.null(condition3)) {
    sets[[3]] <- get_set(condition3)
    default_labels <- c(default_labels, condition3)
  }

  names(sets) <- labels %||% default_labels
  .set_notebook_plot_size(width, height, units = "in")
  .venn_base(
    sets,
    labels = names(sets),
    colors = colors,
    show_header = show_header
  )
}

# DATA COMPLETENESS
.missing_bar <- function(counts, bin, title, header, text, text_size, color) {
  if (!length(counts)) counts <- 0

  if (bin > 0) {
    labels <- ifelse(counts > bin, paste0(">", bin), as.character(counts))
    levels <- c(as.character(0:bin), paste0(">", bin))
  } else {
    labels <- as.character(counts)
    levels <- as.character(0:max(counts))
  }

  frequencies <- table(factor(labels, levels = levels))
  ymax <- max(frequencies) * 1.1

  mids <- barplot(
    frequencies,
    col = color,
    border = NA,
    ylim = c(0, ymax),
    xlab = "Number of Missing Values",
    ylab = "Frequency",
    main = if (header) title else ""
  )
  grid(nx = NA, ny = NULL, col = grDevices::adjustcolor("grey", alpha.f = 0.35), lty = 2)

  if (text) {
    text(
      mids,
      frequencies,
      labels = frequencies,
      pos = 3,
      cex = text_size / 10
    )
  }

  .plot_result()
}

missing_value_plot <- function(
    data,
    meta,
    bin = 0,
    header = TRUE,
    text = TRUE,
    text_size = 3.88,
    width = 7.87,
    height = 3.94,
    dpi = 300,
    color = "blue",
    data_scale = "log2"
) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  intensity_matrix <- .numeric_matrix(data, meta$sample)
  missing_counts <- rowSums(is.na(intensity_matrix))
  missing_counts <- missing_counts[missing_counts < length(meta$sample)]

  title <- if ("Phosphoprotein" %in% names(data)) {
    "Missing Value Plot - Phosphoprotein Level"
  } else if ("ProteinNames" %in% names(data)) {
    "Missing Value Plot - Protein Level"
  } else if ("PTM_Collapse_key" %in% names(data)) {
    "Missing Value Plot - Phosphosite Level"
  } else {
    "Missing Value Plot"
  }

  .set_notebook_plot_size(width, height, units = "in")
  .missing_bar(
    missing_counts,
    bin,
    title,
    header,
    text,
    text_size,
    color
  )
}

missing_value_plot_prec <- function(
    data_path,
    meta,
    bin = 0,
    header = TRUE,
    text = TRUE,
    text_size = 8,
    width = 10,
    height = 6,
    dpi = 100,
    color = "blue",
    quantity_column = "Precursor.Quantity"
) {
  precursor_data <- sanitize_dataframe(read_data(data_path))
  wide_data <- .pivot_wide(
    precursor_data,
    "Precursor.Id",
    "File.Name",
    quantity_column,
    # max matches missing_value_plot_pep below. Taking the first value depended
    # on input row order, and the raw-zero conversion runs immediately after, so
    # which duplicate won decided whether a precursor read as detected.
    max
  )
  sample_columns <- names(.peptide_sample_map(names(wide_data), meta$sample))
  wide_data <- raw_zero_to_nan(wide_data, sample_columns)
  observed <- wide_data[, sample_columns, drop = FALSE]
  observed <- observed[rowSums(!is.na(observed)) > 0, , drop = FALSE]
  missing_counts <- rowSums(is.na(observed))

  .set_notebook_plot_size(width, height, units = "in")
  .missing_bar(
    missing_counts,
    bin,
    "Missing Value Plot - Precursor Level",
    header,
    text,
    text_size,
    color
  )
}

missing_value_plot_pep <- function(
    data_path,
    meta,
    bin = 0,
    header = TRUE,
    text = TRUE,
    text_size = 8,
    width = 10,
    height = 6,
    dpi = 100,
    color = "blue",
    quantity_column = "Precursor.Quantity"
) {
  peptide_data <- sanitize_dataframe(read_data(data_path))

  if ("File.Name" %in% names(peptide_data)) {
    wide_data <- .pivot_wide(
      peptide_data,
      "Stripped.Sequence",
      "File.Name",
      quantity_column,
      max
    )
  } else {
    wide_data <- peptide_data
  }

  sample_columns <- names(.peptide_sample_map(setdiff(names(wide_data), "Stripped.Sequence"), meta$sample))
  wide_data <- raw_zero_to_nan(wide_data, sample_columns)
  observed <- wide_data[, sample_columns, drop = FALSE]
  observed <- observed[rowSums(!is.na(observed)) > 0, , drop = FALSE]
  missing_counts <- rowSums(is.na(observed))

  .set_notebook_plot_size(width, height, units = "in")
  .missing_bar(
    missing_counts,
    bin,
    "Missing Value Plot - Peptide Level",
    header,
    text,
    text_size,
    color
  )
}

.feature_axis_label <- function(data) {
  # What one row of the matrix is, for an axis label.
  columns <- names(data)
  if ("Phosphoprotein" %in% columns) return("Phosphoproteins")
  if ("PTM_Collapse_key" %in% columns) return("Phosphosites")
  if ("ProteinNames" %in% columns) return("Proteins")
  "Features"
}

# The sample columns without features that have no value in any of them. A
# feature missing in every selected sample says nothing about how complete those
# samples are -- identified elsewhere, or never quantified -- so the completeness
# heatmap, tables and overall percentage leave it out, as the web app and the
# Python package do. missing_value_plot already drops its bar.
.quantified_rows <- function(frame, samples) {
  values <- frame[, samples, drop = FALSE]
  frame[rowSums(!is.na(values)) > 0, , drop = FALSE]
}

missing_value_heatmap <- function(
    data,
    meta,
    id = TRUE,
    header = TRUE,
    width = 20,
    height = 10,
    dpi = 300,
    data_scale = "log2"
) {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  meta <- .sample_meta(meta, id = id)
  renamed_data <- .rename_samples(data, meta)
  samples <- intersect(meta$new_sample, names(renamed_data))
  renamed_data <- .quantified_rows(renamed_data, samples)
  missing_matrix <- is.na(as.matrix(renamed_data[, samples, drop = FALSE])) * 1

  .set_notebook_plot_size(width, height)
  old_par <- par(mar = c(8, 5, 3, 2))
  on.exit(par(old_par), add = TRUE)

  image(
    seq_len(ncol(missing_matrix)),
    seq_len(nrow(missing_matrix)),
    t(missing_matrix[nrow(missing_matrix):1, , drop = FALSE]),
    col = c("#440154", "#FDE725"),
    zlim = c(0, 1),
    axes = FALSE,
    xlab = "Sample",
    ylab = .feature_axis_label(data),
    main = if (header) "Missing Values Heatmap" else ""
  )
  axis(1, seq_along(samples), samples, las = 2, cex.axis = 0.65)
  box()

  .plot_result()
}

missing_protein_table <- function(data, meta, id = TRUE, data_scale = "log2") {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  sample_meta <- .sample_meta(meta, id = id, newline = FALSE)
  renamed_data <- .rename_samples(data, sample_meta)
  sample_columns <- intersect(sample_meta$new_sample, names(renamed_data))
  renamed_data <- .quantified_rows(renamed_data, sample_columns)
  missing_counts <- rowSums(
    is.na(renamed_data[, sample_columns, drop = FALSE])
  )

  output <- as.data.frame(table(missing_counts), stringsAsFactors = FALSE)
  names(output) <- c("n_MissingProteinValues", "Counts")
  output$n_MissingProteinValues <- as.integer(
    as.character(output$n_MissingProteinValues)
  )
  output$`%_missing_values` <- output$Counts / sum(output$Counts) * 100
  output
}

missing_sample_table <- function(data, meta, id = TRUE, data_scale = "log2") {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  sample_meta <- .sample_meta(meta, id = id, newline = FALSE)
  renamed_data <- .rename_samples(data, sample_meta)
  sample_columns <- intersect(sample_meta$new_sample, names(renamed_data))
  renamed_data <- .quantified_rows(renamed_data, sample_columns)
  missing_counts <- colSums(
    is.na(renamed_data[, sample_columns, drop = FALSE])
  )

  data.frame(
    Sample = names(missing_counts),
    Counts = as.integer(missing_counts),
    `%_missing_values` = as.integer(missing_counts) / nrow(renamed_data) * 100,
    check.names = FALSE
  )
}

missing_value_outlier <- function(df, thld = 50) {
  as.character(df$Sample[df$`%_missing_values` > thld])
}

all_miss_val <- function(data, meta, data_scale = "log2") {
  data <- .prepare_intensity_data(data, meta$sample, data_scale)
  intensity_matrix <- .numeric_matrix(data, meta$sample)
  intensity_matrix <- intensity_matrix[rowSums(!is.na(intensity_matrix)) > 0, , drop = FALSE]
  round(mean(is.na(intensity_matrix)) * 100, 2)
}

# The workflow is Kinase Library motif enrichment (Johnson et al., Nature 2023),
# not KSEA (Casado et al., 2013). The ksea_* names are kept as aliases so
# existing scripts keep working.
ksea_data_f <- kinase_library_data_f
ksea_data_f_control <- kinase_library_data_f_control
ksea_volcano <- kinase_library_volcano
