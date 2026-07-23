.require_pkg <- function(package) {
  if (!requireNamespace(package, quietly = TRUE)) {
    stop(
      "Package '", package, "' is required for this function. Install it with ",
      "install.packages('", package, "').",
      call. = FALSE
    )
  }
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

.numeric_matrix <- function(data, columns) {
  m <- as.matrix(data[, columns, drop = FALSE])
  storage.mode(m) <- "numeric"
  m
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

.row_zscore <- function(m) {
  means <- rowMeans(m, na.rm = TRUE)
  sds <- apply(m, 1, sd, na.rm = TRUE)
  sds[!is.finite(sds) | sds == 0] <- 1
  sweep(sweep(m, 1, means, "-"), 1, sds, "/")
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
resource_path_manual <- function(relative_path) {
  file.path(getwd(), relative_path)
}

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
  if (is.numeric(value)) as.character(value) else ""
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

resource_path <- function(relative_path) {
  source_file <- sys.frame(1)$ofile %||% "."
  base_path <- dirname(normalizePath(source_file, mustWork = FALSE))
  file.path(base_path, relative_path)
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

strip_sample_measurement_suffix <- function(x) {
  text <- trimws(as.character(x))
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

extract_id_or_number <- function(x) {
  original <- trimws(as.character(x))
  sample_name <- strip_sample_measurement_suffix(original)
  m <- gregexpr("[0-9]+", sample_name)[[1]]
  if (m[1] < 0) original else tail(regmatches(sample_name, list(m))[[1]], 1)
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

filter_data <- function(data, meta, num, filterops = "per group", method = "at_least_n", percentage = 70) {
  method <- tolower(trimws(method))
  filterops <- gsub("_", " ", tolower(trimws(filterops)))
  if (!method %in% c("at_least_n", "percentage")) {
    stop("Filter method must be 'at_least_n' or 'percentage'.", call. = FALSE)
  }
  if (filterops == "overall") {
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
    rows_to_keep <- if (filterops == "per group") apply(keep, 1, all) else apply(keep, 1, any)
  }
  data[rows_to_keep, , drop = FALSE]
}

transform_phosprot <- function(data, meta, mode = "sum_mean_impute") {
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
  missing_samples <- setdiff(samples, names(data))
  if (length(missing_samples)) {
    stop("`meta.sample` contains names not found in data", call. = FALSE)
  }

  bad <- tapply(data$Gene_group, data$Protein_group, function(x) length(unique(na.omit(x)))) > 1
  if (any(bad)) {
    stop("Each Protein_group must map to exactly one Gene_group.", call. = FALSE)
  }

  working_data <- data
  if (mode == "sum_mean_impute") {
    for (condition in unique(meta$condition)) {
      columns <- samples[meta$condition == condition]
      for (column in columns) {
        mean_value <- mean(
          suppressWarnings(as.numeric(working_data[[column]])),
          na.rm = TRUE
        )
        working_data[[column]][is.na(working_data[[column]])] <- mean_value
      }
    }
  }

  sum_fun <- switch(mode,
    sum_mean_impute = function(x) sum(as.numeric(x), na.rm = TRUE),
    sum_propagate_na = function(x) if (any(is.na(as.numeric(x)))) NA_real_ else sum(as.numeric(x)),
    sum_ignore_na = function(x) sum(as.numeric(x), na.rm = TRUE),
    mean = function(x) mean(as.numeric(x), na.rm = TRUE),
    stop("mode must be 'sum_mean_impute', 'sum_propagate_na', 'sum_ignore_na', or 'mean'", call. = FALSE))

  groups <- split(seq_len(nrow(working_data)), working_data$Protein_group)
  rows <- lapply(names(groups), function(group_name) {
    indices <- groups[[group_name]]
    row <- list(
      Phosphoprotein = group_name,
      Gene_group = working_data$Gene_group[indices[1]],
      site_num = length(indices),
      PTM_Collapse_keys = paste(
        sort(unique(na.omit(as.character(working_data$PTM_Collapse_key[indices])))),
        collapse = ";"
      ),
      PTM_localization = paste(
        na.omit(as.character(working_data$PTM_localization[indices])),
        collapse = ";"
      ),
      UPD_seq = paste(
        sort(unique(na.omit(as.character(working_data$UPD_seq[indices])))),
        collapse = ";"
      )
    )

    for (sample in samples) {
      row[[sample]] <- sum_fun(working_data[[sample]][indices])
    }
    row
  })

  as.data.frame(do.call(rbind, lapply(rows, as.data.frame)), check.names = FALSE, stringsAsFactors = FALSE)
}

qqnorm_plot <- function(data, meta) {
  values <- as.vector(.numeric_matrix(data, meta$sample))
  values <- values[is.finite(values) & values > 0]

  if (length(values) > 100000) {
    set.seed(187)
    values <- sample(values, 100000)
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

impute_values <- function(data, meta, q=0.01, adj_std=0.3, ret=0, sample_wise=FALSE, seed=69, method="quantile", down_shift=1.8, width=0.3) {
  method <- tolower(trimws(method))
  if (method == "normal") method <- "quantile"
  if (!method %in% c("quantile", "numerical")) {
    stop("Imputation method must be 'quantile' or 'numerical'.", call. = FALSE)
  }
  set.seed(seed)
  samples <- as.character(meta$sample)
  output <- data
  values <- .numeric_matrix(data, samples)
  values[values == 0] <- NA_real_
  missing_mask <- is.na(values)

  complete_values <- as.vector(values[rowSums(missing_mask) == 0, , drop = FALSE])
  incomplete_values <- as.vector(values[rowSums(missing_mask) > 0, , drop = FALSE])
  incomplete_values <- incomplete_values[is.finite(incomplete_values)]

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
    curve(
      dnorm(x, mean = mean_value, sd = sd_value),
      add = TRUE,
      col = "red",
      lwd = 2
    )
    legend("topright", "Normal fit", col = "red", lwd = 2, bty = "n")
    return(.plot_result())
  }

  for (column_index in seq_along(samples)) {
    number_missing <- sum(missing_mask[, column_index])
    if (!number_missing) next

    if (sample_wise) {
      sample_sd <- sd(values[, column_index], na.rm = TRUE)
      if (method == "numerical") {
        draw_center <- mean(values[, column_index], na.rm = TRUE) - down_shift * sample_sd
        draw_sd <- sample_sd * width
      } else {
        draw_center <- quantile(values[, column_index], q, na.rm = TRUE)
        draw_sd <- sample_sd
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

  output[samples] <- values
  output
}

# QC FUNCTIONS
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
    text_size = 9
) {
  data[data == 0] <- NA
  meta <- .sample_meta(meta, id = id, newline = TRUE)
  renamed_data <- .rename_samples(data, meta)

  samples <- intersect(meta$new_sample, names(renamed_data))
  if (!length(samples)) {
    stop("None of the annotated columns exist in the data after renaming.", call. = FALSE)
  }

  counts <- colSums(!is.na(renamed_data[, samples, drop = FALSE]))
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
    redline <- length(data$Phosphoprotein)
    title <- "Phosphoproteins per sample"
    y_label <- "Number of phosphoproteins"
  } else if ("ProteinNames" %in% names(data)) {
    redline <- length(data$ProteinNames)
    title <- "Proteins per sample"
    y_label <- "Number of proteins"
  } else if ("PTM_Collapse_key" %in% names(data)) {
    redline <- length(data$PTM_Collapse_key)
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
    xlab = "Condition",
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
    text_size = 9
) {
  data[data == 0] <- NA
  meta <- .sample_meta(meta, id = TRUE, newline = TRUE)
  renamed_data <- .rename_samples(data, meta)

  counts <- colSums(!is.na(renamed_data[, meta$new_sample, drop = FALSE]))
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
    redline <- length(data$Phosphoprotein)
    title <- "Phosphoproteins per sample"
    y_label <- "Number of phosphoproteins"
  } else if ("ProteinNames" %in% names(data)) {
    redline <- length(data$ProteinNames)
    title <- "Proteins per sample"
    y_label <- "Number of proteins"
  } else if ("PTM_Collapse_key" %in% names(data)) {
    redline <- length(data$PTM_Collapse_key)
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

  set.seed(69)
  for (i in seq_along(condition_values)) {
    points(
      jitter(rep(mids[i], length(condition_values[[i]])), amount = 0.08),
      condition_values[[i]],
      pch = 16,
      col = rgb(0, 0, 0, 0.7),
      cex = 0.75
    )
  }

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

coverage_plot_pep <- function(
    data2_path,
    meta,
    id = TRUE,
    header = TRUE,
    legend = TRUE,
    plot_colors = NULL,
    width = 10,
    height = 6,
    dpi = 100
) {
  data <- if (is.data.frame(data2_path)) {
    data2_path
  } else {
    sanitize_dataframe(read_data(data2_path))
  }
  meta <- .sample_meta(meta, id = id, newline = TRUE)

  if ("File.Name" %in% names(data)) {
    wide_data <- .pivot_wide(
      data,
      "Stripped.Sequence",
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
    peptide_count <- nrow(wide_data)
  } else {
    wide_data <- .rename_samples(data, meta)
    peptide_count <- if ("Stripped.Sequence" %in% names(data)) {
      length(unique(data$Stripped.Sequence))
    } else {
      nrow(data)
    }
  }

  samples <- intersect(meta$new_sample, names(wide_data))
  counts <- colSums(
    !is.na(wide_data[, samples, drop = FALSE]) &
      wide_data[, samples, drop = FALSE] != 0
  )
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
    xlab = "Condition",
    ylab = "Number of peptides",
    main = if (header) "Peptides per sample" else ""
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
    main = if (header) "Distribution of measured intensity (log2)" else "",
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
    main = if (header) "Measured intensity values (log2)" else ""
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

cov_plot <- function(data, meta, outliers=FALSE, header=TRUE, legend=TRUE, plot_colors=NULL, width_cm=20, height_cm=10, dpi=100, text=FALSE, text_size=9) {
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

  while (error > tol) {
    x_matrix <- q_matrix %*% diag(weights) %*% t(q_matrix)
    distances <- diag(t(q_matrix) %*% solve(x_matrix) %*% q_matrix)
    index <- which.max(distances)
    step_size <- (distances[index] - dimensions - 1) /
      ((dimensions + 1) * (distances[index] - 1))

    new_weights <- (1 - step_size) * weights
    new_weights[index] <- new_weights[index] + step_size
    error <- sqrt(sum((new_weights - weights)^2))
    weights <- new_weights
  }

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

pca_plot <- function(data, meta, header=TRUE, legend=TRUE, dot_size=3, width_cm=20, height_cm=10, dpi=100, plot_colors=NULL, plot_3d=FALSE, add_ellipses=FALSE) {
  expression_matrix <- .numeric_matrix(data, meta$sample)
  complete_rows <- rowSums(!is.finite(expression_matrix)) == 0
  transposed_expression <- t(expression_matrix[complete_rows, , drop = FALSE])
  nonzero_variance <- apply(transposed_expression, 2, var) > 0
  transposed_expression <- transposed_expression[, nonzero_variance, drop = FALSE]

  n_components <- if (plot_3d) 3 else 2
  pca <- prcomp(transposed_expression, rank. = n_components)
  scores <- pca$x[, seq_len(n_components), drop = FALSE]
  explained_variance <- pca$sdev^2 / sum(pca$sdev^2) * 100

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
      for (condition in condition_levels) {
        condition_scores <- scores[conditions == condition, 1:2, drop = FALSE]
        if (nrow(condition_scores) <= 2) next

        ellipse <- minimum_enclosing_ellipse(condition_scores)
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

  expression_matrix <- .numeric_matrix(data, meta$sample)
  complete_rows <- rowSums(!is.finite(expression_matrix)) == 0
  transposed_expression <- t(expression_matrix[complete_rows, , drop = FALSE])
  nonzero_variance <- apply(transposed_expression, 2, var) > 0
  transposed_expression <- transposed_expression[, nonzero_variance, drop = FALSE]

  n_components <- if (plot_3d) 3 else 2
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
        zaxis = list(title = sprintf("PC3 - %.2f%%", explained_variance[3]))
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
    for (i in seq_along(condition_levels)) {
      condition <- condition_levels[i]
      subset <- scores[scores$condition == condition, c("PC1", "PC2"), drop = FALSE]
      if (nrow(subset) <= 2) next

      ellipse <- minimum_enclosing_ellipse(subset)
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

abundance_plot <- function(data, meta, workflow="Protein", plot_colors=NULL, width_cm=20, height_cm=10, dpi=300, legend=TRUE, header=TRUE) {
  data[data == 0] <- NA
  key_col <- .workflow_col(workflow)
  conditions <- unique(meta$condition)
  colors <- .plot_colors(length(conditions), plot_colors)

  ranked_values <- lapply(conditions, function(condition) {
    columns <- meta$sample[meta$condition == condition]
    values <- log10(rowMeans(.numeric_matrix(data, columns), na.rm = TRUE) + 1)
    sort(values[is.finite(values)], decreasing = TRUE)
  })

  x_max <- max(lengths(ranked_values))
  y_range <- range(unlist(ranked_values), na.rm = TRUE)

  .set_notebook_plot_size(width_cm, height_cm)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  plot(
    NA,
    xlim = c(1, x_max),
    ylim = y_range,
    xlab = paste(workflow, "Rank"),
    ylab = paste("log10", workflow, "Intensity"),
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
    max_ptms = 5
) {
  .require_pkg("plotly")

  data[data == 0] <- NA
  feature_col <- .workflow_col(workflow)
  sample_columns <- meta$sample[meta$condition == condition]
  condition_means <- log10(
    rowMeans(.numeric_matrix(data, sample_columns), na.rm = TRUE) + 1
  )

  plot_data <- data.frame(
    Feature = sub(";.*$", "", as.character(data[[feature_col]])),
    log10Intensity = condition_means,
    stringsAsFactors = FALSE
  )
  plot_data <- plot_data[is.finite(plot_data$log10Intensity), , drop = FALSE]

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
    yaxis = list(title = paste("log10", workflow, "Intensity")),
    hovermode = "closest"
  )
}

corr_plot <- function(data, meta, method="Matrix", id=TRUE, full_range=FALSE, width=10, height=8, dpi=100) {
  meta <- .sample_meta(meta, id = id)
  renamed_data <- .rename_samples(data, meta)
  correlation_matrix <- cor(
    .numeric_matrix(renamed_data, meta$new_sample),
    use = "pairwise.complete.obs",
    method = "pearson"
  )

  ordered_indices <- hclust(
    as.dist(1 - correlation_matrix),
    method = "complete"
  )$order
  ordered_correlation <- correlation_matrix[
    ordered_indices,
    ordered_indices,
    drop = FALSE
  ]

  color_range <- if (full_range) c(-1, 1) else range(ordered_correlation)
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

  .plot_result()
}

.volcano_stats <- function(
    data,
    meta,
    condition1,
    condition2,
    label_col,
    paired = "Unpaired",
    uncorrected = FALSE,
    extras = character()
) {
  condition1_columns <- as.character(meta$sample[meta$condition == condition1])
  condition2_columns <- as.character(meta$sample[meta$condition == condition2])
  columns <- unique(c(label_col, condition1_columns, condition2_columns, extras))
  filtered_data <- data[, columns, drop = FALSE]

  x_data <- .numeric_matrix(filtered_data, condition1_columns)
  y_data <- .numeric_matrix(filtered_data, condition2_columns)
  valid <- rowSums(!is.na(x_data)) >= 2 & rowSums(!is.na(y_data)) >= 2

  filtered_data <- filtered_data[valid, , drop = FALSE]
  x_data <- x_data[valid, , drop = FALSE]
  y_data <- y_data[valid, , drop = FALSE]
  log2fc <- rowMeans(y_data, na.rm = TRUE) - rowMeans(x_data, na.rm = TRUE)

  pvalues <- vapply(seq_len(nrow(filtered_data)), function(index) {
    values1 <- x_data[index, ]
    values2 <- y_data[index, ]
    values1 <- values1[is.finite(values1)]
    values2 <- values2[is.finite(values2)]

    if (paired == "Unpaired") {
      t.test(values2, values1, var.equal = TRUE)$p.value
    } else {
      n_pairs <- min(length(values1), length(values2))
      t.test(
        values2[seq_len(n_pairs)],
        values1[seq_len(n_pairs)],
        paired = TRUE
      )$p.value
    }
  }, numeric(1))

  adjusted_pvalues <- if (uncorrected) pvalues else p.adjust(pvalues, "BH")
  output_columns <- c(label_col, extras[extras %in% names(filtered_data)])
  output <- filtered_data[, output_columns, drop = FALSE]
  output$log2FC <- log2fc
  output$pval <- pvalues
  output$adj_pval <- adjusted_pvalues
  output
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
    uncorrected = FALSE
) {
  label_col <- .workflow_col(workflow)
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
    extra_columns
  )
  output$significance <- ifelse(
    output$adj_pval < in_pval & output$log2FC > in_log2fc,
    "Upregulated",
    ifelse(
      output$adj_pval < in_pval & output$log2FC < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )
  output$neg_log10_adj_pval <- -log10(output$adj_pval)
  output
}

volcano_data_f_control <- function(data, meta, condition1, condition2, condition1_control, condition2_control, in_pval=0.05, in_log2fc=1, workflow="Protein", paired="Unpaired", uncorrected=FALSE) {
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

  volcano_data_f(
    normalized_data,
    meta,
    condition1,
    condition2,
    in_pval,
    in_log2fc,
    workflow,
    paired,
    uncorrected
  )
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
  max_y <- max(y_threshold, volcano_df$neg_log10_adj_pval, na.rm = TRUE)
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
        y = ~neg_log10_adj_pval,
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
      title = paste0("log2 fold change (", condition2, " - ", condition1, ")")
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
    uncorrected = FALSE
) {
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
    intersect(c("site_num", "PTM_Collapse_keys"), names(data))
  } else {
    character()
  }
  output <- data[
    valid,
    unique(c(label_col, sample_columns, extra_columns)),
    drop = FALSE
  ]

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

  output$f_statistic <- f_statistics
  output$pval <- pvalues
  output$adj_pval <- if (uncorrected) pvalues else p.adjust(pvalues, "BH")
  output$significance <- ifelse(
    output$adj_pval < in_pval,
    "Significant",
    "Not significant"
  )
  output$neg_log10_adj_pval <- -log10(
    pmax(output$adj_pval, .Machine$double.xmin)
  )

  for (condition in conditions) {
    output[[paste0("mean_", condition)]] <- rowMeans(
      .numeric_matrix(output, condition_columns[[condition]]),
      na.rm = TRUE
    )
  }

  output[order(output$adj_pval), , drop = FALSE]
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
    cluster_col = "cluster",
    min_cluster_fraction = 0.05
) {
  if (n_clusters < 1) {
    stop("n_clusters must be at least 1.", call. = FALSE)
  }

  sample_columns <- intersect(as.character(meta$sample), names(anova_df))
  if (!length(sample_columns)) {
    stop("No sample columns from meta were found in anova_df.", call. = FALSE)
  }

  cluster_data <- if (only_significant && "adj_pval" %in% names(anova_df)) {
    anova_df[anova_df$adj_pval < in_pval, , drop = FALSE]
  } else {
    anova_df
  }
  if (!nrow(cluster_data)) cluster_data <- anova_df

  matrix <- .numeric_matrix(cluster_data, sample_columns)
  if (z_score) matrix <- .row_zscore(matrix)
  matrix[!is.finite(matrix)] <- 0

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

  if (min_cluster_fraction > 0) {
    minimum_size <- ceiling(length(relabeled_clusters) * min_cluster_fraction)
    cluster_counts <- table(relabeled_clusters)
    large_clusters <- as.integer(names(cluster_counts[cluster_counts >= minimum_size]))
    if (!length(large_clusters)) {
      large_clusters <- as.integer(names(cluster_counts)[which.max(cluster_counts)])
    }

    for (cluster in as.integer(names(cluster_counts))) {
      if (cluster_counts[as.character(cluster)] >= minimum_size) next
      target <- large_clusters[which.min(abs(large_clusters - cluster))]
      relabeled_clusters[relabeled_clusters == cluster] <- target
    }

    cluster_map <- setNames(
      seq_along(unique(relabeled_clusters)),
      unique(relabeled_clusters)
    )
    relabeled_clusters <- unname(cluster_map[as.character(relabeled_clusters)])
  }

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

  plot_data <- if ("adj_pval" %in% names(anova_df)) {
    anova_df[anova_df$adj_pval < in_pval, , drop = FALSE]
  } else {
    anova_df
  }
  if (!nrow(plot_data)) plot_data <- anova_df

  raw_matrix <- .numeric_matrix(plot_data, sample_columns)
  rownames(raw_matrix) <- as.character(plot_data[[label_col]])
  missing_mask <- !is.finite(raw_matrix)
  matrix <- if (z_score) .row_zscore(raw_matrix) else raw_matrix
  matrix[!is.finite(matrix)] <- NA
  cluster_matrix <- matrix
  cluster_matrix[!is.finite(cluster_matrix)] <- 0

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
  rownames(matrix) <- as.character(anova_cluster_df[[label_col]])
  missing_mask <- !is.finite(matrix)
  if (z_score) matrix <- .row_zscore(matrix)
  matrix[!is.finite(matrix)] <- NA
  cluster_matrix <- matrix
  cluster_matrix[!is.finite(cluster_matrix)] <- 0

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

different_genes <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, workflow="Gene", paired="Unpaired", uncorrected=FALSE) {
  output <- .volcano_stats(
    data,
    meta,
    condition1,
    condition2,
    "GeneNames",
    paired,
    uncorrected
  )

  list(
    Upregulated = sub(
      ";.*$",
      "",
      output$GeneNames[
        output$adj_pval < in_pval & output$log2FC > in_log2fc
      ]
    ),
    Downregulated = sub(
      ";.*$",
      "",
      output$GeneNames[
        output$adj_pval < in_pval & output$log2FC < -in_log2fc
      ]
    )
  )
}

enrichment_analysis <- function(gene_list, top_n=10, min_num=20, max_num=300) {
  .require_pkg("gprofiler2")
  genes <- gene_list[nzchar(gene_list)]
  if (!length(genes)) return(NULL)

  result <- gprofiler2::gost(
    genes,
    organism = "hsapiens",
    sources = c("GO:BP", "GO:CC", "GO:MF"),
    correction_method = "g_SCS"
  )$result
  result <- result[
    result$term_size >= min_num & result$term_size <= max_num,
    ,
    drop = FALSE
  ]
  result <- head(result[order(result$p_value), ], top_n)
  if (!nrow(result)) return(NULL)

  hits <- result$intersection_size / result$term_size * 100
  colors <- colorRampPalette(c("#2166ac", "white", "#b2182b"))(100)
  color_index <- cut(
    -log10(result$p_value),
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
    xlab = "Hits (%)",
    ylab = "",
    main = "Gene Set Enrichment Analysis"
  )
  axis(2, seq_len(nrow(result)), result$term_name, las = 2, cex.axis = 0.65)
  mtext("GO Term", side = 2, line = 10)

  .plot_result()
}

load_go_db <- function() {
  read.csv(
    file.path(getwd(), "data", "db", "all_go_terms_genes.csv"),
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
}

proteins_in_pathway <- function(data, meta, db, pathway, conditions=NULL, figsize=c(12,8), cmap_name="plasma", remove_empty=TRUE, cluster_rows=FALSE, cluster_cols=FALSE, value_type="z", header=TRUE, id=TRUE) {
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

  heatmap_data <- matrix(
    NA_real_,
    nrow = length(genes),
    ncol = nrow(meta_filtered),
    dimnames = list(genes, meta_filtered$new_sample)
  )
  lower_gene_names <- tolower(data$GeneNames)
  for (gene_index in seq_along(genes)) {
    matching_rows <- which(lower_gene_names == tolower(genes[gene_index]))
    if (!length(matching_rows)) next

    for (sample_index in seq_len(nrow(meta_filtered))) {
      sample <- meta_filtered$sample[sample_index]
      if (sample %in% names(data)) {
        heatmap_data[gene_index, sample_index] <- as.numeric(
          data[matching_rows[1], sample]
        )
      }
    }
  }

  if (remove_empty) {
    heatmap_data <- heatmap_data[
      rowSums(!is.na(heatmap_data)) > 0,
      ,
      drop = FALSE
    ]
  }
  if (!nrow(heatmap_data)) {
    stop("No matching gene data available for the selected pathway.", call. = FALSE)
  }

  value_type <- tolower(value_type)
  if (value_type == "z") {
    heatmap_data <- .row_zscore(heatmap_data)
    color_label <- "Z-score"
    zlim <- c(-2.5, 2.5)
  } else if (value_type == "log2") {
    color_label <- "log2 Intensity"
    zlim <- NULL
  } else {
    stop("value_type must be 'z' or 'log2'", call. = FALSE)
  }

  cluster_data <- heatmap_data
  cluster_data[!is.finite(cluster_data)] <- 0
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
      ")"
    ),
    ylab = if (header) "Protein / Gene" else "",
    labels = header,
    zlim = zlim,
    color_label = color_label,
    palette = colorRampPalette(c("#0d0887", "#cc4778", "#f0f921"))(100)
  )
}

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
  log2fc <- mean2 - mean1
  t_statistic <- log2fc / standard_error
  degrees_freedom <- n1 + n2 - 2
  pvals <- 2 * stats::pt(abs(t_statistic), degrees_freedom, lower.tail = FALSE)
  adjusted_pvals <- p.adjust(pvals, method = "BH")

  significance <- ifelse(
    adjusted_pvals < in_pval & log2fc > in_log2fc,
    "Upregulated",
    ifelse(
      adjusted_pvals < in_pval & log2fc < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )

  volcano_data <- data.frame(
    Feature = filtered_data[[label_col]],
    log2FC = log2fc,
    pval = pvals,
    adj_pval = adjusted_pvals,
    significance = significance,
    neg_log10_adj_pval = -log10(adjusted_pvals),
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

  left_tail <- if (nchar(left) >= 6) {
    substr(left, nchar(left) - 5, nchar(left))
  } else {
    paste0(strrep("_", 6 - nchar(left)), left)
  }
  right_tail <- if (nchar(right) >= 6) {
    substr(right, 1, 6)
  } else {
    paste0(right, strrep("_", 6 - nchar(right)))
  }

  paste0("_", left_tail, modified_residue, right_tail, "_")
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

  left_tail <- if (nchar(left) >= 6) {
    substr(left, nchar(left) - 5, nchar(left))
  } else {
    paste0(strrep("_", 6 - nchar(left)), left)
  }
  right_tail <- if (nchar(right) >= 6) {
    substr(right, 1, 6)
  } else {
    paste0(right, strrep("_", 6 - nchar(right)))
  }

  paste0("_", left_tail, modified_residue, right_tail, "_")
}

ksea_data_f <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE) {
  output <- .volcano_stats(
    data,
    meta,
    condition1,
    condition2,
    "UPD_seq",
    paired,
    uncorrected
  )
  output$UPD_seq <- vapply(output$UPD_seq, convert_to_centered, character(1))
  output$significance <- ifelse(
    output$adj_pval < in_pval & output$log2FC > in_log2fc,
    "Upregulated",
    ifelse(
      output$adj_pval < in_pval & output$log2FC < -in_log2fc,
      "Downregulated",
      "Not significant"
    )
  )
  output$neg_log10_adj_pval <- -log10(output$adj_pval)
  output
}

phosprot_regulation <- function(data, meta, condition1, condition2, in_pval=0.05, in_log2fc=1, paired="Unpaired", uncorrected=FALSE, max_hover_sites=20, show_phosphosites=TRUE) {
  .require_pkg("plotly")

  site_results <- .volcano_stats(
    data,
    meta,
    condition1,
    condition2,
    "PTM_Collapse_key",
    paired,
    uncorrected,
    "Protein_group"
  )

  all_samples <- c(
    meta$sample[meta$condition == condition1],
    meta$sample[meta$condition == condition2]
  )
  protein_groups <- split(seq_len(nrow(site_results)), site_results$Protein_group)

  truncate_sites <- function(sites) {
    if (!show_phosphosites) return("")
    if (length(sites) <= max_hover_sites) return(paste(sites, collapse = ";"))

    paste0(
      paste(head(sites, max_hover_sites), collapse = ";"),
      ";... (+", length(sites) - max_hover_sites, " more)"
    )
  }

  collapsed <- lapply(names(protein_groups), function(protein) {
    rows <- protein_groups[[protein]]
    group <- site_results[rows, , drop = FALSE]
    down_sites <- as.character(group$PTM_Collapse_key[group$log2FC < 0])
    up_sites <- as.character(group$PTM_Collapse_key[group$log2FC > 0])

    down_values <- data[
      data$PTM_Collapse_key %in% down_sites,
      all_samples,
      drop = FALSE
    ]
    up_values <- data[
      data$PTM_Collapse_key %in% up_sites,
      all_samples,
      drop = FALSE
    ]
    down_sum_raw <- sum(.numeric_matrix(down_values, all_samples), na.rm = TRUE)
    up_sum_raw <- sum(.numeric_matrix(up_values, all_samples), na.rm = TRUE)

    data.frame(
      Protein_group = protein,
      Downregulated_sites = truncate_sites(down_sites),
      Upregulated_sites = truncate_sites(up_sites),
      Downregulated_count = length(down_sites),
      Upregulated_count = length(up_sites),
      Downregulated_sum = if (down_sum_raw > 0) log2(down_sum_raw) else 0,
      Upregulated_sum = if (up_sum_raw > 0) log2(up_sum_raw) else 0,
      stringsAsFactors = FALSE
    )
  })
  collapsed <- do.call(rbind, collapsed)
  collapsed$x <- abs(collapsed$Upregulated_sum)
  collapsed$y <- abs(collapsed$Downregulated_sum)
  collapsed$color_val <- collapsed$x - collapsed$y

  hover_text <- paste0(
    "Protein group: ", collapsed$Protein_group,
    "<br>Upregulated count: ", collapsed$Upregulated_count,
    "<br>Downregulated count: ", collapsed$Downregulated_count,
    "<br>Upregulated sites: ", collapsed$Upregulated_sites,
    "<br>Downregulated sites: ", collapsed$Downregulated_sites
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
    title = "Protein-level Phosphosite Regulation",
    xaxis = list(title = "Absolute Upregulated Sum (log2)"),
    yaxis = list(title = "Absolute Downregulated Sum (log2)"),
    coloraxis = list(colorbar = list(title = "Up - Down")),
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
    dpi = 100
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
      set.seed(69)
      data <- data[sample(nrow(data), 100000), , drop = FALSE]
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
  modifications <- c(
    Carbamylation = "UniMod:4|Carbamidomethyl",
    Oxidation = "UniMod:35|Oxidation",
    Acetylation = "UniMod:1|Acetyl"
  )
  counts <- sapply(modifications, function(pattern) {
    rows <- grepl(pattern, rownames(wide_data))
    colSums(!is.na(wide_data[rows, samples, drop = FALSE]))
  })
  counts <- t(counts)
  keep <- rowSums(counts) > 0
  counts <- counts[keep, , drop = FALSE]
  modification_colors <- c(
    Carbamylation = "blue",
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

missed_cleavage_plot <- function(data2_path, meta, id=TRUE, text=TRUE, text_size=8, header=TRUE, width=10, height=6, dpi=100) {
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
  names(wide_data) <- vapply(names(wide_data), extract_id_or_number, character(1))

  meta <- .sample_meta(meta, id = id, newline = TRUE)
  id_map <- setNames(meta$new_sample, meta$id)
  names(wide_data) <- ifelse(
    names(wide_data) %in% names(id_map),
    id_map[names(wide_data)],
    names(wide_data)
  )

  samples <- intersect(meta$new_sample, names(wide_data))
  missed_cleavages <- pmax(
    0,
    nchar(gsub("[^RK]", "", rownames(wide_data))) - 1
  )
  cleavage_levels <- sort(unique(missed_cleavages))

  percentages <- sapply(samples, function(sample) {
    present <- !is.na(wide_data[[sample]])
    counts <- table(factor(missed_cleavages[present], levels = cleavage_levels))
    as.numeric(counts) / sum(counts) * 100
  })
  if (is.null(dim(percentages))) {
    percentages <- matrix(percentages, ncol = 1)
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
    ylab = "Percentage of peptides with missed cleavage (%)",
    main = if (header) "Missed cleavages per sample" else ""
  )

  if (text && "1" %in% rownames(percentages)) {
    text(
      mids,
      3,
      labels = sprintf("%.1f%%", percentages["1", ]),
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

calculate_coverage <- function(data_path, db, protein) {
  data <- read_data(data_path)
  peptides <- unique(data$Stripped.Sequence[
    grepl(paste0("\\b", protein, "\\b"), data$ProteinNames)
  ])
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
    starts <- gregexpr(peptide, sequence, fixed = TRUE)[[1]]
    starts <- starts[starts > 0]
    for (start in starts) {
      coverage_mask[start:(start + nchar(peptide) - 1)] <- TRUE
    }
  }

  round(mean(coverage_mask) * 100, 2)
}

vis_coverage <- function(data, db, protein, chunk_size=30) {
  peptides <- unique(data$Stripped.Sequence[
    grepl(paste0("\\b", protein, "\\b"), data$ProteinNames)
  ])
  sequence <- db$V1[match(protein, db$name)]
  if (is.na(sequence)) {
    return(paste0("No sequence found in the selected database for protein: ", protein))
  }

  sequence_length <- nchar(sequence)
  tracks <- strrep("-", sequence_length)
  for (peptide in peptides) {
    starts <- gregexpr(peptide, sequence, fixed = TRUE)[[1]]
    for (start in starts[starts > 0]) {
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
  if (workflow == "Protein") labels <- sub(";.*$", "", labels)
  colors <- .plot_colors(nrow(filtered_data), plot_colors)

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

boxplot_int_single_prot <- function(data, meta, protein, outliers=FALSE, dots=FALSE, header=TRUE, legend=TRUE, plot_colors=NULL, width=8, height=6, dpi=100) {
  protein_data <- if (protein %in% rownames(data)) {
    data[protein, , drop = FALSE]
  } else {
    data[data[[1]] == protein, , drop = FALSE]
  }
  if (!nrow(protein_data)) {
    stop("No data found for protein: ", protein, call. = FALSE)
  }

  conditions <- unique(meta$condition)
  intensities <- lapply(conditions, function(condition) {
    columns <- meta$sample[meta$condition == condition]
    values <- as.numeric(protein_data[1, columns])
    values[is.finite(values)]
  })
  keep <- lengths(intensities) >= 3
  intensities <- intensities[keep]
  conditions <- conditions[keep]

  .set_notebook_plot_size(width, height, units = "in")
  if (!length(intensities)) {
    plot.new()
    text(0.5, 0.5, "No conditions with >=3 samples")
    return(.plot_result())
  }

  colors <- .plot_colors(length(conditions), plot_colors)
  old_par <- .set_plot_margins(legend = legend)
  on.exit(par(old_par), add = TRUE)

  boxplot(
    intensities,
    names = conditions,
    col = colors,
    border = "black",
    outline = outliers,
    medcol = "firebrick",
    medlwd = 2,
    ylab = "log2 Intensity",
    main = if (header) {
      paste("Measured", sub(";.*$", "", protein), "intensity values (log2)")
    } else {
      ""
    }
  )

  if (dots) {
    set.seed(69)
    for (i in seq_along(intensities)) {
      values <- intensities[[i]]
      quartiles <- quantile(values, c(0.25, 0.75))
      iqr <- diff(quartiles)
      non_outliers <- values[
        values >= quartiles[1] - 1.5 * iqr &
          values <= quartiles[2] + 1.5 * iqr
      ]
      points(
        jitter(rep(i, length(non_outliers)), amount = 0.05),
        non_outliers,
        pch = 16,
        cex = 0.75,
        col = grDevices::adjustcolor(colors[i], alpha.f = 0.7)
      )
    }
  }

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

phossite_on_prot_regulation <- function(data, meta, protein, conditions=NULL, id=TRUE, figsize=c(12,8), cmap_name="plasma", filter_M2=FALSE, cluster_rows=FALSE, cluster_cols=FALSE, value_type="log2", header=TRUE) {
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
    heatmap_data <- .row_zscore(heatmap_data)
    color_label <- "Z-score"
    zlim <- c(-2.5, 2.5)
  } else if (value_type == "log2") {
    color_label <- "log2 Intensity"
    zlim <- NULL
  } else {
    stop("value_type must be 'log2' or 'z'", call. = FALSE)
  }

  cluster_data <- heatmap_data
  cluster_data[!is.finite(cluster_data)] <- 0
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
phossite_coverage_plot <- function(data, meta, id=FALSE, header=TRUE, legend=TRUE, width=20, height=10, dpi=300, color_classI="blue", color_notclassI="orange") {
  meta <- .sample_meta(meta, id = id, newline = TRUE, zero_based = TRUE)
  renamed_data <- .rename_samples(data, meta)
  samples <- meta$new_sample

  class_i <- colSums(!is.na(
    renamed_data[renamed_data$PTM_localization >= 0.75, samples, drop = FALSE]
  ))
  not_class_i <- colSums(!is.na(
    renamed_data[renamed_data$PTM_localization < 0.75, samples, drop = FALSE]
  ))

  .set_notebook_plot_size(width, height)
  old_par <- .set_plot_margins(legend = legend, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  barplot(
    rbind(class_i, not_class_i),
    names.arg = samples,
    las = 2,
    cex.names = 0.65,
    col = c(color_classI, color_notclassI),
    border = NA,
    xlab = "Sample",
    ylab = if (header) "Number of phosphosites" else "Number",
    main = if (header) "Phosphosites per sample" else ""
  )

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = c("Class I", "Not Class I"),
      fill = c(color_classI, color_notclassI),
      border = NA,
      bty = "n"
    )
  }

  .plot_result()
}

sty_plot <- function(data) {
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
  percentages <- counts / sum(counts) * 100
  colors <- c(S = "#4C78A8", T = "#F58518", Y = "#54A24B")

  old_par <- par(mar = c(4.5, 4.5, 3.5, 4.5))
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    counts,
    col = colors,
    border = "black",
    lwd = 0.6,
    ylim = c(0, max(counts) * 1.13),
    main = "Modified S/T/Y Peptide Counts",
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

  count_ticks <- pretty(c(0, max(counts)))
  axis(
    4,
    at = count_ticks,
    labels = sprintf("%.0f", count_ticks / sum(counts) * 100)
  )
  mtext("Percentage (%)", side = 4, line = 2.5)

  .plot_result()
}

phossite_coverage_plot_summary <- function(data, meta, header=TRUE, legend=TRUE, width=20, height=10, dpi=300, color_classI="blue", color_notclassI="orange") {
  meta <- .sample_meta(meta, id = FALSE)
  renamed_data <- .rename_samples(data, meta)

  class_i <- colSums(!is.na(
    renamed_data[renamed_data$PTM_localization >= 0.75, meta$new_sample, drop = FALSE]
  ))
  not_class_i <- colSums(!is.na(
    renamed_data[renamed_data$PTM_localization < 0.75, meta$new_sample, drop = FALSE]
  ))

  conditions <- unique(meta$condition)
  class_values <- split(class_i, meta$condition)
  not_class_values <- split(not_class_i, meta$condition)
  class_means <- vapply(class_values, mean, numeric(1))
  not_class_means <- vapply(not_class_values, mean, numeric(1))
  class_sd <- vapply(class_values, sd, numeric(1))
  not_class_sd <- vapply(not_class_values, sd, numeric(1))
  class_sd[!is.finite(class_sd)] <- 0
  not_class_sd[!is.finite(not_class_sd)] <- 0

  means <- rbind(class_means, not_class_means)
  sds <- rbind(class_sd, not_class_sd)
  ymax <- max(means + sds, na.rm = TRUE) * 1.1

  .set_notebook_plot_size(width, height)
  old_par <- .set_plot_margins(legend = legend, rotated_labels = TRUE)
  on.exit(par(old_par), add = TRUE)

  mids <- barplot(
    means,
    beside = TRUE,
    names.arg = conditions,
    las = 2,
    col = c(color_classI, color_notclassI),
    border = NA,
    ylim = c(0, ymax),
    ylab = if (header) "Number of phosphosites" else "Number",
    main = if (header) "Phosphosites per condition" else ""
  )

  arrows(
    mids,
    pmax(0, means - sds),
    mids,
    means + sds,
    angle = 90,
    code = 3,
    length = 0.04
  )

  set.seed(69)
  for (i in seq_along(conditions)) {
    points(
      jitter(rep(mids[1, i], length(class_values[[i]])), amount = 0.04),
      class_values[[i]],
      pch = 16,
      cex = 0.7,
      col = grDevices::adjustcolor("black", alpha.f = 0.7)
    )
    points(
      jitter(rep(mids[2, i], length(not_class_values[[i]])), amount = 0.04),
      not_class_values[[i]],
      pch = 16,
      cex = 0.7,
      col = grDevices::adjustcolor("black", alpha.f = 0.7)
    )
  }

  if (legend) {
    legend(
      "topright",
      inset = c(-0.28, 0),
      legend = c("Class I", "Not Class I"),
      fill = c(color_classI, color_notclassI),
      border = NA,
      bty = "n"
    )
  }

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

ksea_volcano <- function(data_st, data_tnc, pval_thresh=0.1, header=TRUE, condition1=NULL, condition2=NULL, GRK=FALSE) {
  .require_pkg("plotly")

  data <- rbind(data_st, data_tnc)
  frequency_col <- grep("Frequency Factor", names(data), value = TRUE)[1]
  pvalue_col <- grep("Adjusted p-value", names(data), fixed = TRUE, value = TRUE)[1]

  if (is.na(frequency_col) || is.na(pvalue_col)) {
    stop(
      "Input must contain 'Log2(Frequency Factor)' and 'Adjusted p-value' columns",
      call. = FALSE
    )
  }

  data$frequency_factor <- as.numeric(data[[frequency_col]])
  data$adjusted_pvalue <- as.numeric(data[[pvalue_col]])
  data$neg_log10_pval <- -log10(data$adjusted_pvalue)
  data$Regulation <- ifelse(
    data$adjusted_pvalue < pval_thresh & data$frequency_factor > 0,
    "Upregulated",
    ifelse(
      data$adjusted_pvalue < pval_thresh & data$frequency_factor < 0,
      "Downregulated",
      "Not significant"
    )
  )

  color_mapping <- c(
    Upregulated = "red",
    Downregulated = "blue",
    `Not significant` = "lightgrey"
  )
  is_grk <- grepl("\\bGRK[0-9]*\\b", data$Kinase, ignore.case = TRUE)

  fig <- plotly::plot_ly()
  for (regulation in unique(data$Regulation)) {
    normal_rows <- data$Regulation == regulation & (!is_grk | !GRK)
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

  if (GRK && any(is_grk)) {
    grk_data <- data[is_grk, , drop = FALSE]
    fig <- plotly::add_trace(
      fig,
      data = grk_data,
      x = ~frequency_factor,
      y = ~neg_log10_pval,
      type = "scatter",
      mode = "markers",
      name = "GRK",
      text = ~Kinase,
      hovertemplate = paste0(
        "Kinase: %{text}<br>",
        "Log2(Frequency Factor): %{x}<br>",
        "-log10(p-value): %{y}<extra></extra>"
      ),
      marker = list(
        color = unname(color_mapping[grk_data$Regulation]),
        size = 12,
        line = list(color = "yellow", width = 2)
      ),
      inherit = FALSE
    )
  }

  title <- if (header && !is.null(condition1) && !is.null(condition2)) {
    paste0("KSEA Volcano Plot: ", condition1, " vs. ", condition2)
  } else if (header) {
    "KSEA Volcano Plot"
  } else {
    NULL
  }
  x_label <- if (!is.null(condition1) && !is.null(condition2)) {
    paste0("log2(Frequency Factor) (", condition2, " - ", condition1, ")")
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
  adjusted_pvalue[adjusted_pvalue == 0] <- NA_real_

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

correlation_xy_intensity <- function(data, meta, condition1, condition2, alias1=NULL, alias2=NULL, color="blue", dot_size=60, width_cm=20, height_cm=12, dpi=300, show_header=TRUE) {
  condition1_samples <- meta$sample[meta$condition == condition1]
  condition2_samples <- meta$sample[meta$condition == condition2]
  if (!length(condition1_samples) || !length(condition2_samples)) {
    stop("One or both conditions have no associated samples.", call. = FALSE)
  }

  mean1 <- rowMeans(.numeric_matrix(data, condition1_samples), na.rm = TRUE)
  mean2 <- rowMeans(.numeric_matrix(data, condition2_samples), na.rm = TRUE)
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
  venn <- VennDiagram::venn.diagram(
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
    main.cex = 1.3
  )

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
    show_header = TRUE
) {
  .set_notebook_plot_size(width, height, units = "in")

  sets <- list(
    rownames(data)[!is.na(data[[sample1]]) & data[[sample1]] != 0],
    rownames(data)[!is.na(data[[sample2]]) & data[[sample2]] != 0]
  )
  default_labels <- c(sample1, sample2)

  if (!is.null(sample3)) {
    sets[[3]] <- rownames(data)[
      !is.na(data[[sample3]]) & data[[sample3]] != 0
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
    show_header = TRUE
) {
  get_set <- function(condition) {
    samples <- meta$sample[meta$condition == condition]
    present <- rowSums(
      !is.na(data[, samples, drop = FALSE]) &
        data[, samples, drop = FALSE] != 0
    ) > 0
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
    color = "blue"
) {
  intensity_matrix <- .numeric_matrix(data, meta$sample)
  intensity_matrix[intensity_matrix == 0] <- NA
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
    color = "blue"
) {
  precursor_data <- sanitize_dataframe(read_data(data_path))
  wide_data <- .pivot_wide(
    precursor_data,
    "Precursor.Id",
    "File.Name",
    "Precursor.Quantity",
    function(values) values[1]
  )
  names(wide_data) <- vapply(
    names(wide_data),
    extract_id_or_number,
    character(1)
  )
  samples <- vapply(meta$sample, extract_id_or_number, character(1))
  sample_columns <- intersect(samples, names(wide_data))
  missing_counts <- rowSums(is.na(wide_data[, sample_columns, drop = FALSE]))

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
    color = "blue"
) {
  peptide_data <- sanitize_dataframe(read_data(data_path))

  if ("File.Name" %in% names(peptide_data)) {
    wide_data <- .pivot_wide(
      peptide_data,
      "Stripped.Sequence",
      "File.Name",
      "Precursor.Quantity",
      max
    )
    names(wide_data) <- vapply(
      names(wide_data),
      extract_id_or_number,
      character(1)
    )
  } else {
    wide_data <- peptide_data
  }

  samples <- vapply(meta$sample, extract_id_or_number, character(1))
  sample_columns <- intersect(samples, names(wide_data))
  missing_counts <- rowSums(is.na(wide_data[, sample_columns, drop = FALSE]))

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

missing_value_heatmap <- function(
    data,
    meta,
    id = TRUE,
    header = TRUE,
    width = 20,
    height = 10,
    dpi = 300
) {
  data[data == 0] <- NA
  meta <- .sample_meta(meta, id = id)
  renamed_data <- .rename_samples(data, meta)
  samples <- intersect(meta$new_sample, names(renamed_data))
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
    ylab = "Protein Numbers",
    main = if (header) "Missing Values Heatmap" else ""
  )
  axis(1, seq_along(samples), samples, las = 2, cex.axis = 0.65)
  box()

  .plot_result()
}

missing_protein_table <- function(data, meta, id = TRUE) {
  data[data == 0] <- NA
  sample_meta <- .sample_meta(meta, id = id, newline = FALSE)
  renamed_data <- .rename_samples(data, sample_meta)
  sample_columns <- intersect(sample_meta$new_sample, names(renamed_data))
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

missing_sample_table <- function(data, meta, id = TRUE) {
  data[data == 0] <- NA
  sample_meta <- .sample_meta(meta, id = id, newline = FALSE)
  renamed_data <- .rename_samples(data, sample_meta)
  sample_columns <- intersect(sample_meta$new_sample, names(renamed_data))
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

all_miss_val <- function(data, meta) {
  intensity_matrix <- .numeric_matrix(data, meta$sample)
  intensity_matrix[intensity_matrix == 0] <- NA
  round(mean(is.na(intensity_matrix)) * 100, 2)
}
