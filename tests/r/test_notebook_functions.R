# Runs the R package's unit tests (tests/r/testthat/) with testthat, so every
# test reports instead of the first failure stopping the rest.
#
#   Rscript tests/r/test_notebook_functions.R
#
# notebook_functions.R is sourced here, at top level, because it locates its own
# folder from the sourcing frame; the tests then see its functions.
args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
script_path <- if (length(file_arg)) sub("^--file=", "", file_arg[1]) else "tests/r/test_notebook_functions.R"
repo_root <- normalizePath(file.path(dirname(script_path), "..", ".."), mustWork = TRUE)

functions_path <- file.path(repo_root, "proteomicscopylot", "notebook_functions.R")
example_path <- file.path(repo_root, "examples", "example.R")

source(functions_path)

if (!requireNamespace("testthat", quietly = TRUE)) {
  stop("The R tests need the testthat package: install.packages('testthat').", call. = FALSE)
}
testthat::test_dir(
  file.path(repo_root, "tests", "r", "testthat"),
  reporter = testthat::ProgressReporter$new(show_praise = FALSE),
  stop_on_failure = TRUE,
  stop_on_warning = FALSE
)
