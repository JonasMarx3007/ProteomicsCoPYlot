from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import warnings

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

SAMPLES = [f"s{i}" for i in range(6)]
OFFSETS = np.array([0.0, 1.2, -0.9, 0.6, -1.5, 0.3])


def _notebook():
    spec = importlib.util.spec_from_file_location(
        "_nb_guards", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["_nb_guards"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def notebook():
    return _notebook()


def _frame(n_features: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    values = rng.normal(20.0, 2.0, (n_features, len(SAMPLES))) + OFFSETS
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n_features)])
    return frame


def _meta() -> pd.DataFrame:
    return pd.DataFrame({"sample": SAMPLES, "condition": ["a"] * 3 + ["b"] * 3})


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalize_data_accepts_a_metadata_frame(notebook, method: str) -> None:
    frame = _frame()
    from_meta = notebook.normalize_data(frame.copy(), _meta(), method)[SAMPLES].to_numpy()
    from_list = notebook.normalize_data(frame.copy(), SAMPLES, method)[SAMPLES].to_numpy()
    assert np.allclose(from_meta, from_list, equal_nan=True), (
        "normalize_data is the only public function whose second argument is not a "
        "metadata frame; passing meta must normalize, not return the input unchanged"
    )


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalize_data_actually_changes_the_data(notebook, method: str) -> None:
    frame = _frame()
    before = frame[SAMPLES].median().to_numpy().std()
    after = notebook.normalize_data(frame.copy(), _meta(), method)[SAMPLES].median().to_numpy().std()
    assert before > 0.5, "fixture lost its loading offsets"
    assert after < before / 10, (
        f"sample-median spread went {before:.4f} -> {after:.4f}; the call returned "
        "something that was not normalized"
    )


def test_normalize_data_rejects_columns_that_match_nothing(notebook) -> None:
    with pytest.raises(ValueError, match="nothing would be normalized"):
        notebook.normalize_data(_frame(20), ["not_a_column"], "median")


def test_normalize_data_rejects_a_partial_match(notebook) -> None:
    with pytest.raises(ValueError, match="not in the data"):
        notebook.normalize_data(_frame(20), SAMPLES + ["not_a_column"], "median")


def test_normalize_data_says_so_when_metadata_has_no_sample_column(notebook) -> None:
    with pytest.raises(ValueError, match="'sample' column"):
        notebook.normalize_data(_frame(20), pd.DataFrame({"run": SAMPLES}), "median")


def test_requesting_no_normalization_is_still_a_no_op(notebook) -> None:
    frame = _frame(20)
    pd.testing.assert_frame_equal(
        notebook.normalize_data(frame.copy(), ["not_a_column"], "none"), frame
    )


def _dup_meta() -> pd.DataFrame:
    meta = _meta()
    return pd.concat([meta, meta[meta["condition"] == "b"]], ignore_index=True)


@pytest.mark.parametrize(
    "call",
    [
        "filter_data",
        "volcano_data_f",
        "anova_data_f",
        "impute_values",
    ],
)
def test_duplicated_metadata_samples_are_refused(notebook, call: str) -> None:
    frame = _frame()
    runners = {
        "filter_data": lambda m: notebook.filter_data(frame.copy(), m, 2),
        "volcano_data_f": lambda m: notebook.volcano_data_f(frame.copy(), m, "a", "b"),
        "anova_data_f": lambda m: notebook.anova_data_f(frame.copy(), m),
        "impute_values": lambda m: notebook.impute_values(frame.copy(), m),
    }
    runners[call](_meta())
    with pytest.raises(ValueError, match="more than once"):
        runners[call](_dup_meta())


def test_the_duplicate_message_names_the_offending_samples(notebook) -> None:
    with pytest.raises(ValueError) as excinfo:
        notebook.volcano_data_f(_frame().copy(), _dup_meta(), "a", "b")
    message = str(excinfo.value)
    assert "s3" in message or "s4" in message or "s5" in message
    assert "exactly once" in message


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"method": "percentage", "percentage": 500}, "between 0 and 100"),
        ({"method": "percentage", "percentage": -10}, "between 0 and 100"),
        ({"method": "percentage", "percentage": "many"}, "must be a number"),
        ({"num": -5}, "zero or greater"),
        ({"num": None}, "whole number"),
    ],
)
def test_filter_thresholds_that_cannot_describe_completeness_are_refused(
    notebook, kwargs: dict, match: str
) -> None:
    num = kwargs.pop("num", 1)
    with pytest.raises(ValueError, match=match):
        notebook.filter_data(_frame(20).copy(), _meta(), num, "overall", **kwargs)


def test_a_filter_that_keeps_nothing_is_allowed(notebook) -> None:
    kept = notebook.filter_data(_frame(20).copy(), _meta(), 99, "overall")
    assert len(kept) == 0, "an unreachable-but-meaningful threshold should filter, not raise"


def test_the_strictest_legitimate_percentage_is_allowed(notebook) -> None:
    kept = notebook.filter_data(
        _frame(20).copy(), _meta(), 1, "overall", method="percentage", percentage=100
    )
    assert len(kept) == 20


@pytest.mark.parametrize("mode", ["per group", "per_group", "PER_GROUP"])
def test_mode_spellings_agree_with_the_backend(notebook, mode: str) -> None:
    import sys

    from app.services.functions import filter_data as backend_filter

    frame, meta = _frame(20), _meta()
    from_pip = len(notebook.filter_data(frame.copy(), meta, 2, mode))
    from_backend = len(backend_filter(frame.copy(), meta, 2, mode))
    assert from_pip == from_backend, (
        f"mode {mode!r} kept {from_pip} rows in the package and {from_backend} in the "
        "backend; the same spelling must mean the same thing in both"
    )


def _comma_frame(column: str = "s2") -> pd.DataFrame:
    frame = _frame()
    frame[column] = [str(round(v, 3)).replace(".", ",") for v in frame[column]]
    return frame


@pytest.mark.parametrize(
    "call",
    ["filter_data", "volcano_data_f", "anova_data_f", "impute_values"],
)
def test_a_locale_mangled_column_is_refused_not_silently_emptied(notebook, call) -> None:
    """A decimal comma turns every value in a sample into NaN.

    The sample then reads as fully undetected, survives the completeness filter
    on the other replicates, and the analysis runs one replicate short with no
    sign that anything went wrong.
    """
    meta = _meta()
    runners = {
        "filter_data": lambda f: notebook.filter_data(f, meta, 2),
        "volcano_data_f": lambda f: notebook.volcano_data_f(f, meta, "a", "b"),
        "anova_data_f": lambda f: notebook.anova_data_f(f, meta),
        "impute_values": lambda f: notebook.impute_values(f, meta),
    }
    runners[call](_frame())
    with pytest.raises(ValueError, match="do not parse as numbers"):
        runners[call](_comma_frame())


def test_the_message_names_the_column_and_shows_a_value(notebook) -> None:
    with pytest.raises(ValueError) as excinfo:
        notebook.filter_data(_comma_frame(), _meta(), 2)
    message = str(excinfo.value)
    assert "s2" in message and "," in message


def test_documented_placeholders_are_not_mistaken_for_lost_values(notebook) -> None:
    frame = _frame()
    frame["s2"] = frame["s2"].astype(object)
    frame.loc[:19, "s2"] = "NA"
    frame.loc[20:39, "s2"] = "Filtered"
    assert len(notebook.filter_data(frame, _meta(), 2)) > 0


def test_a_few_stray_labels_do_not_trip_the_guard(notebook) -> None:
    """Only a column losing most of its values is a mangled export."""
    frame = _frame()
    frame["s2"] = frame["s2"].astype(object)
    frame.loc[:3, "s2"] = "not detected"
    assert len(notebook.filter_data(frame, _meta(), 2)) > 0


def _partly_comma_frame(fraction: float, column: str = "s2") -> pd.DataFrame:
    """Mangle only a fraction of one column, as a spreadsheet round-trip would."""
    frame = _frame(200)
    values = frame[column].tolist()
    frame[column] = frame[column].astype(object)
    for index in range(int(200 * fraction)):
        frame.loc[index, column] = str(round(values[index], 3)).replace(".", ",")
    return frame


def test_a_partial_loss_is_reported_even_though_it_is_tolerated(notebook) -> None:
    """The threshold decides whether to refuse, not whether to mention it.

    A thousands separator applied by a spreadsheet mangles only the largest
    values, so a partial loss deletes a biased sample of the measurements and
    shifts the comparison. Tolerating it quietly is the silence the guard exists
    to break.
    """
    with pytest.warns(UserWarning, match="do not parse as numbers"):
        notebook.filter_data(_partly_comma_frame(0.10), _meta(), 2)


def test_clean_data_says_nothing(notebook) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        notebook.filter_data(_frame(200), _meta(), 2)


@pytest.mark.parametrize("protein", ["P", "P.1", "P+1"])
@pytest.mark.parametrize("shared", [False, True])
def test_sequence_coverage_uses_exact_protein_members(notebook, monkeypatch, protein, shared):
    from app.services import peptide_tools

    frame = pd.DataFrame({
        "ProteinNames": [
            protein, f"{protein}-2", f"{protein}X", f"X{protein}",
            f"OTHER; {protein} " if shared else "OTHER", None, protein,
        ],
        "Stripped.Sequence": ["AAA", "CCC", "CCC", "CCC", "CCC", "CCC", None],
    })
    db = pd.DataFrame({"name": [protein], "accession": [protein], "V1": ["AAACCC"]})
    monkeypatch.setattr(notebook, "read_data", lambda _: frame)
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame)
    monkeypatch.setattr(peptide_tools, "_load_fasta_dataframe", lambda _: db)
    expected = 100.0 if shared else 50.0
    result = peptide_tools.peptide_sequence_coverage(species="human", protein=protein)
    assert result["coveragePercent"] == notebook.calculate_coverage(None, db, protein) == expected
    assert result["matchingPeptideCount"] == (2 if shared else 1)
    expected_text = "\nAAACCC\nAAACCC\n" if shared else "\nAAA---\nAAACCC\n"
    assert result["sequenceText"] == notebook.vis_coverage(frame, db, protein) == expected_text


@pytest.mark.parametrize("sequence,peptide,starts,expected", [
    ("AAAA", "AAA", [0, 1], 100.0),
    ("AAACAAA", "AAA", [0, 4], 85.71),
    ("CAAAC", "AAA", [1], 60.0),
    ("AAAA", "WWW", [], 0.0),
    ("AAAA", "AAAAA", [], 0.0),
])
def test_sequence_coverage_includes_overlapping_matches(notebook, monkeypatch, sequence, peptide, starts, expected):
    from app.services import peptide_tools

    frame = pd.DataFrame({"ProteinNames": ["P"], "Stripped.Sequence": [peptide]})
    db = pd.DataFrame({"name": ["P"], "accession": ["P"], "V1": [sequence]})
    monkeypatch.setattr(notebook, "read_data", lambda _: frame)
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame)
    monkeypatch.setattr(peptide_tools, "_load_fasta_dataframe", lambda _: db)
    for module in (notebook, peptide_tools):
        assert list(module._peptide_starts(sequence, peptide)) == starts
        assert list(module._peptide_starts(sequence, "")) == []
    result = peptide_tools.peptide_sequence_coverage(species="human", protein="P")
    assert result["coveragePercent"] == notebook.calculate_coverage(None, db, "P") == expected
    assert result["sequenceText"] == notebook.vis_coverage(frame, db, "P")
    tracks = result["sequenceText"].strip().splitlines()[:-1]
    covered = sum(any(track[i] != "-" for track in tracks) for i in range(len(sequence)))
    assert round(100 * covered / len(sequence), 2) == expected
    if starts == [0, 1]:
        assert tracks == ["-AAA", "AAA-"]


def test_a_wholesale_loss_is_still_refused_not_merely_reported(notebook) -> None:
    with pytest.raises(ValueError, match="do not parse as numbers"):
        notebook.filter_data(_partly_comma_frame(0.60), _meta(), 2)


def test_pathway_accepts_native_phosprot_labels(notebook):
    import matplotlib.pyplot as plt
    frame = pd.DataFrame({"Gene_group": ["A", "B"], "s1": [1., 2.], "s2": [3., 4.]})
    meta = pd.DataFrame({"sample": ["s1", "s2"], "condition": ["C", "D"]})
    db = pd.DataFrame({"description": ["path"], "genes": ["A;B"]})
    fig = notebook.proteins_in_pathway(frame, meta, db, "path", value_type="log2")
    try:
        np.testing.assert_allclose(np.asarray(fig.axes[0].collections[0].get_array()).reshape(2, 2), [[1, 3], [2, 4]])
    finally:
        plt.close(fig)
    frame["GeneNames"] = ["wrong", "wrong"]
    with pytest.raises(ValueError, match="gene_column"):
        notebook.proteins_in_pathway(frame, meta, db, "path")
    plt.close(notebook.proteins_in_pathway(frame, meta, db, "path", gene_column="Gene_group", value_type="log2"))


@pytest.mark.parametrize("level", ["pep", "prec"])
@pytest.mark.parametrize("bin_size", [0, 1])
@pytest.mark.parametrize("samples", [["r1", "r2"], []])
def test_peptide_missingness_excludes_never_observed(notebook, monkeypatch, level, bin_size, samples):
    import matplotlib.pyplot as plt
    frame = pd.DataFrame({"File.Name": ["r1", "r2"] * 3,
        "Stripped.Sequence": ["AAA"] * 2 + ["BBB"] * 2 + ["CCC"] * 2,
        "Precursor.Id": ["AAA2"] * 2 + ["BBB2"] * 2 + ["CCC2"] * 2,
        "Precursor.Quantity": [1, 1, 0, 0, 1, 0]})
    monkeypatch.setattr(notebook, "read_data", lambda path: frame)
    meta = pd.DataFrame({"sample": samples})
    fig = getattr(notebook, "missing_value_plot_" + level)("unused", meta, bin=bin_size)
    try:
        heights = [bar.get_height() for bar in fig.axes[0].patches]
        assert sum(heights) == (2 if samples else 0)
        if samples:
            assert heights[:2] == [1, 1]
    finally:
        plt.close(fig)


@pytest.mark.parametrize('plot_name', ['coverage_plot_pep', 'missing_value_plot_pep', 'missing_value_plot_prec'])
@pytest.mark.parametrize('reverse', [False, True])
def test_notebook_exact_run_matching(notebook, monkeypatch, plot_name, reverse):
    import matplotlib.pyplot as plt
    frame = pd.DataFrame({'File.Name': ['ctrl_01.raw', 'treat_01.raw'] * 2,
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB', 'BBB'], 'Precursor.Id': ['AAA2', 'AAA2', 'BBB2', 'BBB2'],
        'Precursor.Quantity': [1., 1., 0., 1.]})
    if reverse:
        frame = frame.iloc[::-1]
    monkeypatch.setattr(notebook, 'read_data', lambda _: frame)
    meta = pd.DataFrame({'sample': ['ctrl_01.raw'], 'condition': ['C']})
    plot = getattr(notebook, plot_name)
    fig = plot('unused', meta)
    try:
        assert [bar.get_height() for bar in fig.axes[0].patches] == [1]
    finally:
        plt.close(fig)
    with pytest.raises(ValueError, match='ambiguous'):
        plot('unused', meta.assign(sample='sample_01'))
    with pytest.raises(ValueError, match='does not match'):
        notebook._peptide_sample_map(['run1'], ['missing9'])
    assert notebook._peptide_sample_map(['run1', 'run2'], ['sample2']) == {'run2': 'sample2'}


@pytest.mark.parametrize('level,quantity,expected', [('peptide', 'Precursor.Quantity', 1),
    ('precursor', 'Precursor.Quantity', 2), ('peptide', 'LFQ intensity', 1), ('precursor', 'LFQ intensity', 1)])
def test_notebook_selected_quantity_and_level(notebook, monkeypatch, level, quantity, expected):
    import matplotlib.pyplot as plt
    frame = pd.DataFrame({'File.Name': ['ctrl_01.raw'] * 3 + ['treat_01.raw'] * 3,
        'Stripped.Sequence': ['AAA', 'AAA', 'BBB'] * 2, 'Precursor.Id': ['AAA2', 'AAA3', 'BBB2'] * 2,
        'Precursor.Quantity': [1, 1, 0, 1, 1, 1], 'LFQ intensity': [0, 0, 1, 1, 1, 1]})
    meta = pd.DataFrame({'sample': ['ctrl_01.raw'], 'condition': ['C']})
    monkeypatch.setattr(notebook, 'read_data', lambda _: frame)
    missing = notebook.missing_value_plot_prec if level == 'precursor' else notebook.missing_value_plot_pep
    for fig in [notebook.coverage_plot_pep(frame, meta, quantity_column=quantity, level=level),
                missing('unused', meta, quantity_column=quantity)]:
        try:
            assert [bar.get_height() for bar in fig.axes[0].patches] == [expected]
        finally:
            plt.close(fig)
    with pytest.raises(KeyError):
        missing('unused', meta, quantity_column='removed')


@pytest.mark.requires_r()
def test_r_correlation_unavailable_cells_and_order():
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      grDevices::pdf(NULL)
      hclust <- function(...) stop("Clustering must not run for undefined correlations")
      meta <- data.frame(sample=c("a","b"),condition=c("C","C"))
      trace("image.default", where=asNamespace("graphics"), print=FALSE, tracer=quote({
        if (!missing(z) && length(z)==4) {
          stopifnot(sum(is.na(z))==expected_na, all(is.finite(zlim)))
          stopifnot(all(z[is.finite(z)]==1))
          seen_image <<- TRUE
        }
      }))
      text <- function(x, y=NULL, labels, ...) {
        if (all(labels=="NA")) seen_na <<- seen_na + length(x)
        graphics::text(x, y, labels, ...)
      }
      fixtures <- list(data.frame(a=c(1,1,1), b=c(1,2,3)),
                       data.frame(a=c(1,1,1), b=c(2,2,2)),
                       data.frame(a=c(1,2,NA), b=c(NA,3,4)))
      for (index in seq_along(fixtures)) for (method in c("Matrix","Ellipse")) for (full in c(FALSE,TRUE)) {
        expected_na <- c(3,4,2)[index]
        seen_na <- 0
        seen_image <- FALSE
        corr_plot(fixtures[[index]],meta,method=method,id=FALSE,full_range=full)
        stopifnot(seen_na==expected_na)
        if (method=="Matrix") stopifnot(seen_image)
      }
      untrace("image.default", where=asNamespace("graphics"))
      stopifnot(inherits(try(corr_plot(data.frame(a=c(NA_real_,NA_real_),b=c(NA_real_,NA_real_)),meta),silent=TRUE),"try-error"))
      grDevices::dev.off()
    '''
    result = subprocess.run([runtime['executable'], '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("include_id", [False, True])
def test_missed_cleavage_keeps_runs_with_the_same_number_distinct(notebook, monkeypatch, include_id):
    runs = ["ctrl_01.raw", "ctrl_02.raw", "treat_01.raw", "treat_02.raw"]
    data = pd.DataFrame({"File.Name": runs, "Stripped.Sequence": ["AAAA", "AKAA", "AAAA", "AKAA"],
                         "Precursor.Quantity": [1.0] * 4})
    meta = pd.DataFrame({"sample": runs, "condition": ["ctrl", "ctrl", "treat", "treat"]})
    original = meta.copy(deep=True)
    monkeypatch.setattr(notebook, "read_data", lambda _: data.copy())
    fig = notebook.missed_cleavage_plot("unused", meta, id=include_id, text=False)
    try:
        bars = fig.axes[0].containers
        np.testing.assert_allclose(bars[0].datavalues, [100, 0, 100, 0])
        np.testing.assert_allclose(bars[1].datavalues, [0, 100, 0, 100])
        pd.testing.assert_frame_equal(meta, original)
    finally:
        notebook.plt.close(fig)


@pytest.mark.requires_r()
def test_r_missed_cleavage_keeps_runs_with_the_same_number_distinct():
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      runs <- c("ctrl_01.raw", "ctrl_02.raw", "treat_01.raw", "treat_02.raw")
      data <- data.frame(File.Name=runs, Stripped.Sequence=c("AAAA","AKAA","AAAA","AKAA"),
                         Precursor.Quantity=rep(1,4))
      meta <- data.frame(sample=runs, condition=c("ctrl","ctrl","treat","treat"))
      read_data <- function(...) data
      seen <- 0L
      barplot <- function(height, ...) {
        stopifnot(isTRUE(all.equal(unname(height), rbind(c(100,0,100,0), c(0,100,0,100)))))
        seen <<- seen + 1L
        graphics::barplot(height, ...)
      }
      grDevices::pdf(NULL)
      missed_cleavage_plot("unused", meta, id=FALSE, text=FALSE)
      missed_cleavage_plot("unused", meta, id=TRUE, text=FALSE)
      stopifnot(seen==2L, identical(meta$sample, runs), ncol(meta)==2L)
      grDevices::dev.off()
    '''
    result = subprocess.run([runtime["executable"], "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.requires_r()
def test_r_notebook_sparse_and_pathway_edges():
    import subprocess
    from app.services.r_runtime import detect_r_runtime
    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      stopifnot(identical(.peptide_sample_map(c("ctrl_01.raw", "treat_01.raw"), "ctrl_01.raw"), c("ctrl_01.raw"="ctrl_01.raw")))
      stopifnot(inherits(try(.peptide_sample_map(c("ctrl_01.raw", "treat_01.raw"), "sample_01"), silent=TRUE), "try-error"))
      stopifnot(identical(.peptide_sample_map(c("run1", "run2"), "sample2"), c(run2="sample2")))
      stopifnot(inherits(try(.peptide_sample_map("run1", "missing9"), silent=TRUE), "try-error"))
      q <- quantile_normalize(data.frame(A=c(10, NA, NA), B=c(20,21,22)))
      stopifnot(isTRUE(all.equal(q$A, c(15, NA, NA))), isTRUE(all.equal(q$B, c(15,15.5,16))))
      one <- quantile_normalize(data.frame(A=10, B=20))
      stopifnot(all(as.matrix(one) == 15))
      empty <- quantile_normalize(data.frame(A=c(NA_real_, NA_real_)))
      stopifnot(all(is.na(empty)))
      grDevices::pdf(NULL)
      collision <- data.frame(File.Name=rep(c("ctrl_01.raw", "treat_01.raw"),2),
        Stripped.Sequence=rep(c("AAA","BBB"),each=2), Precursor.Id=rep(c("AAA2","BBB2"),each=2),
        Precursor.Quantity=c(1,1,0,1))
      original_read <- read_data
      read_data <- function(...) collision
      selection <- data.frame(sample="ctrl_01.raw",condition="C")
      expected_height <- 1
      trace("barplot.default", where=asNamespace("graphics"), print=FALSE,
        tracer=quote(stopifnot(identical(as.numeric(height), expected_height))))
      for (reverse in c(FALSE,TRUE)) {
        if (reverse) collision <- collision[nrow(collision):1,]
        coverage_plot_pep(collision, selection, legend=FALSE)
        missing_value_plot_pep("unused", selection)
        missing_value_plot_prec("unused", selection)
      }
      collision <- data.frame(File.Name=rep(c("ctrl_01.raw", "treat_01.raw"),each=3),
        Stripped.Sequence=rep(c("AAA","AAA","BBB"),2), Precursor.Id=rep(c("AAA2","AAA3","BBB2"),2),
        Precursor.Quantity=c(1,1,0,1,1,1), check.names=FALSE)
      collision[["LFQ intensity"]] <- c(0,0,1,1,1,1)
      for (level in c("peptide","precursor")) for (quantity in c("Precursor.Quantity","LFQ intensity")) {
        expected_height <- if (level=="precursor" && quantity=="Precursor.Quantity") 2 else 1
        coverage_plot_pep(collision, selection, legend=FALSE, level=level, quantity_column=quantity)
        missing <- if (level=="precursor") missing_value_plot_prec else missing_value_plot_pep
        missing("unused", selection, quantity_column=quantity)
      }
      stopifnot(inherits(try(missing_value_plot_pep("unused",selection,quantity_column="removed"),silent=TRUE),"try-error"))
      untrace("barplot.default", where=asNamespace("graphics"))
      read_data <- original_read
      db <- data.frame(description="path", genes="A;B")
      meta <- data.frame(sample=paste0("s", 1:11), condition="C")
      d <- data.frame(Gene_group=c("A","B"))
      for (i in 1:11) d[[paste0("s",i)]] <- c(if(i==10) 10 else if(i==11) NA else 0,
                                               if(i==10) -10 else if(i==11) NA else 0)
      trace("image.default", where=asNamespace("graphics"), print=FALSE,
        tracer=quote({
          if (!missing(z) && !missing(zlim)) {
            finite <- z[is.finite(z)]
            stopifnot(all(finite >= zlim[1]), all(finite <= zlim[2]))
            if (length(z)==22) stopifnot(sum(is.na(z))==2)
          }
        }))
      proteins_in_pathway(d, meta, db, "path", value_type="z")
      untrace("image.default", where=asNamespace("graphics"))
      d$GeneNames <- "wrong"
      stopifnot(inherits(try(proteins_in_pathway(d, meta, db, "path"), silent=TRUE), "try-error"))
      proteins_in_pathway(d, meta, db, "path", gene_column="Gene_group")
      fixture <- data.frame(File.Name=rep(c("r1","r2"),3),
        Stripped.Sequence=rep(c("AAA","BBB","CCC"),each=2),
        Precursor.Id=rep(c("AAA2","BBB2","CCC2"),each=2),
        Precursor.Quantity=c(1,1,0,0,1,0))
      read_data <- function(...) fixture
      .missing_bar <- function(counts, bin, ...) {
        stopifnot(identical(as.numeric(counts), if (empty_selection) numeric() else c(0,1)))
      }
      for (empty_selection in c(FALSE,TRUE)) for (b in c(0,1)) {
        m <- data.frame(sample=if(empty_selection) character() else c("r1","r2"))
        missing_value_plot_pep("unused",m,bin=b)
        missing_value_plot_prec("unused",m,bin=b)
      }
      grDevices::dev.off()
    '''
    result = subprocess.run([runtime["executable"], "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
