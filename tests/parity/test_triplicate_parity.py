"""The web app, the pip package and the R package offer the same functions.

ProteomicsCoPYlot ships its analysis three times on purpose: the web app
(`backend/app/services`), the pip package (`proteomicscopylot/notebook_functions.py`)
and the R package (`proteomicscopylot/notebook_functions.R`). A function added
to one of them and forgotten in the others is how the pipelines drift apart, so
these tests compare what each implementation actually defines.

The inventory is taken at runtime, not by reading the source text: the Python
modules are imported and their functions listed with `inspect`, and the R file
is sourced into a fresh environment by Rscript, which reports every function it
defined together with its formal argument names. A function defined in an
unusual way (an `assign()` call, an alias, a factory) therefore counts exactly
as it does for a user who calls it.

Names are compared without their leading `.` or `_`, which is how each language
marks a helper as private. Differences that are deliberate are listed in the
allowlists below, each with its reason.
"""

from __future__ import annotations

import importlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
R_SOURCE = ROOT / "proteomicscopylot" / "notebook_functions.R"

BACKEND_MODULE = "app.services.functions"
STATS_TOOLS_MODULE = "app.services.stats_tools"
PIP_MODULE = "proteomicscopylot.notebook_functions"


def _normalise(name: str) -> str:
    return name.lstrip("._")


def _by_normalised_name(signatures: dict[str, list[str]]) -> dict[str, list[str]]:
    """Key the signatures by their normalised name.

    When a private helper and a public function share a normalised name (R has
    both `.phosprot_regulation_data` and `phosprot_regulation_data`), the public
    one is the function a user calls, so it is the one compared.
    """
    out: dict[str, list[str]] = {}
    for name in sorted(signatures, key=lambda raw: _normalise(raw) == raw):
        out[_normalise(name)] = signatures[name]
    return out


def _python_signatures(module_name: str) -> dict[str, list[str]]:
    """Every function the module itself defines, with its named parameters.

    Functions imported from elsewhere are left out, because they belong to the
    module that defines them. `*args` and `**kwargs` carry no name a caller
    could pass positionally, so they are left out of the parameter list.
    """
    module = importlib.import_module(module_name)
    signatures: dict[str, list[str]] = {}
    for name, value in vars(module).items():
        if inspect.isfunction(value) and value.__module__ == module.__name__:
            signatures[name] = [
                parameter.name
                for parameter in inspect.signature(value).parameters.values()
                if parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
            ]
    return _by_normalised_name(signatures)


# Sources the R package into an empty environment and prints, as JSON, every
# function it defined and the names of that function's formal arguments.
R_FORMALS_SCRIPT = """
env <- new.env()
sys.source(commandArgs(TRUE)[1], envir = env)
names <- ls(env, all.names = TRUE)
names <- Filter(function(name) is.function(get(name, envir = env)), names)
formals_of <- function(name) as.character(names(formals(get(name, envir = env))))
cat(jsonlite::toJSON(lapply(setNames(names, names), formals_of)))
"""


def _r_signatures(rscript: str) -> dict[str, list[str]]:
    result = subprocess.run(
        [rscript, "-e", R_FORMALS_SCRIPT, str(R_SOURCE)],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return _by_normalised_name({name: list(params) for name, params in json.loads(result.stdout).items()})


# Backend functions whose names mark them as web-app rendering (images, HTML,
# Plotly figures, QC panels) rather than analysis.
def _is_web_app_rendering(name: str) -> bool:
    return name.endswith(("_png", "_html", "_plot", "_heatmap")) or name.startswith("qc_")


# The allowlists are written as tuples so that a name listed twice can be
# detected; the sets the tests use are built from them.
BACKEND_ONLY_ANALYSIS_NAMES = (
    "comparison_contrast",  # UI contrast label, not a separate statistical method.
    "sample_label_frame",  # Plot/report display labels, not a statistical method.
    "condition_sample_labels",  # The "condition_N" axis label rule behind sample_label_frame.
    "entity_labels_for_kind",  # Entity nouns for report/UI prose, not a method.
    "intensity_unit_label",  # UI units for stored phosphoprotein provenance.
    "parse_selection_list",  # JSON/legacy HTTP selection transport.
    "select_matrix",
    "select_matrix_all_rows",  # select_matrix before the session's localization cutoff; store plumbing.
    "qc_matrix",
    "build_metadata_from_conditions",
    "choose_best_source",
    "imputed_data_available",
    "use_existing_log2_data",
    # Plumbing that answers "which matrices does this level have"; the
    # notebooks hand their own frame in and never ask.
    "data_source_availability",
    "data_source_options",
    "most_processed_data_source",
    "phosprot_values_are_centred",
    "impute_values_with_diagnostics",
    "comparative_histogram",
    "histogram",
    "normal_fit_curve",
    "qqnorm_plot_data",
)

PIP_ONLY_NAMES = (
    "adjust_finite_pvalues",  # R adjusts finite p-values inline in volcano calculations.
    "correlation_matrix_mesh",  # matplotlib needs a mesh for vector cells; R's image() draws rectangles itself.
    "different_genes_column",
    "guarded_t_statistic",
    "negative_log10",
    "paired_t_test",
)

R_ONLY_NAMES = (
    "%||%",  # R's null-default operator; Python spells it `x if x is not None else y`.
    "localization_keep",  # row mask behind filter_localization, so R can narrow an aligned matrix by position.
    "numeric_matrix",
    "pivot_wide",
    "plot_colors",
    "plot_heatmap",
    "plot_result",
    "require_pkg",
    "restore_layout",
    "set_notebook_plot_size",
    "set_plot_margins",
    "venn_base",
    "volcano_stats",
    "with_local_seed",
    "workflow_col",
)

BACKEND_ONLY_ANALYSIS = frozenset(BACKEND_ONLY_ANALYSIS_NAMES)
PIP_ONLY = frozenset(PIP_ONLY_NAMES)
R_ONLY = frozenset(R_ONLY_NAMES)


@pytest.fixture(scope="module")
def python_signatures() -> dict[str, dict[str, list[str]]]:
    return {
        "backend": _python_signatures(BACKEND_MODULE),
        "pip": _python_signatures(PIP_MODULE),
    }


@pytest.fixture(scope="module")
def r_signatures(require_r) -> dict[str, list[str]]:
    return _r_signatures(require_r("jsonlite"))


@pytest.fixture(scope="module")
def functions(python_signatures, r_signatures) -> dict[str, set[str]]:
    return {
        "backend": set(python_signatures["backend"]),
        "pip": set(python_signatures["pip"]),
        "r": set(r_signatures),
    }


def test_the_allowlists_name_each_function_once() -> None:
    for label, names in (
        ("BACKEND_ONLY_ANALYSIS", BACKEND_ONLY_ANALYSIS_NAMES),
        ("PIP_ONLY", PIP_ONLY_NAMES),
        ("R_ONLY", R_ONLY_NAMES),
    ):
        repeated = sorted({name for name in names if names.count(name) > 1})
        assert not repeated, f"{label} lists {repeated} more than once"


@pytest.mark.requires_r("jsonlite")
def test_the_two_shipped_packages_expose_the_same_functions(functions) -> None:
    pip_only = functions["pip"] - functions["r"] - PIP_ONLY
    r_only = functions["r"] - functions["pip"] - R_ONLY
    assert not pip_only, (
        f"in the pip package but not in R: {sorted(pip_only)}. Add it to "
        f"notebook_functions.R, or to PIP_ONLY here with a reason."
    )
    assert not r_only, (
        f"in R but not in the pip package: {sorted(r_only)}. Add it to "
        f"notebook_functions.py, or to R_ONLY here with a reason."
    )


@pytest.mark.requires_r("jsonlite")
def test_no_new_analysis_function_is_web_app_only(functions) -> None:
    backend_only = functions["backend"] - functions["pip"] - functions["r"]
    undeclared = {
        name for name in backend_only if not _is_web_app_rendering(name)
    } - BACKEND_ONLY_ANALYSIS
    assert not undeclared, (
        f"analysis functions added to the web app only: {sorted(undeclared)}. "
        f"Add them to notebook_functions.py and notebook_functions.R, or to "
        f"BACKEND_ONLY_ANALYSIS here with a reason."
    )


# Where the web app's version of each core function lives, when it is not
# functions.py under the same name. 2026-10-02: the unused functions.py copies
# of anova_data_f / anova_cluster_data were removed; the app runs these.
WEB_APP_EQUIVALENT = {
    "anova_data_f": (STATS_TOOLS_MODULE, "anova_dataframe"),
    "anova_cluster_data": (STATS_TOOLS_MODULE, "anova_cluster_dataframe"),
}


@pytest.mark.requires_r("jsonlite")
@pytest.mark.parametrize(
    "name", ["anova_data_f", "anova_cluster_data", "anova_posthoc_data"]
)
def test_core_analysis_functions_are_in_every_pipeline(functions, name: str) -> None:
    present = dict(functions)
    web_name = name
    if name in WEB_APP_EQUIVALENT:
        module_name, web_name = WEB_APP_EQUIVALENT[name]
        present["backend"] = set(_python_signatures(module_name))
    missing = [
        key for key, names in present.items()
        if (web_name if key == "backend" else name) not in names
    ]
    assert not missing, f"{name} is missing from: {missing}"


@pytest.mark.requires_r("jsonlite")
@pytest.mark.parametrize("name", ["volcano_data_f", "filter_data", "log2_transform_data"])
def test_core_package_functions_are_in_both_packages(functions, name: str) -> None:
    missing = [key for key in ("pip", "r") if name not in functions[key]]
    assert not missing, f"{name} is missing from: {missing}"


@pytest.mark.requires_r("jsonlite")
def test_allowlists_do_not_list_functions_that_are_actually_shared(functions) -> None:
    stale_pip = PIP_ONLY & functions["r"]
    stale_r = R_ONLY & functions["pip"]
    stale_backend = BACKEND_ONLY_ANALYSIS & (functions["pip"] | functions["r"])
    assert not stale_pip, f"PIP_ONLY lists functions R actually has: {sorted(stale_pip)}"
    assert not stale_r, f"R_ONLY lists functions pip actually has: {sorted(stale_r)}"
    assert not stale_backend, (
        f"BACKEND_ONLY_ANALYSIS lists functions a package actually has: "
        f"{sorted(stale_backend)}"
    )


@pytest.mark.requires_r("jsonlite")
def test_allowlisted_names_still_exist_somewhere(functions) -> None:
    everything = functions["backend"] | functions["pip"] | functions["r"]
    for label, allowlist in (
        ("PIP_ONLY", PIP_ONLY),
        ("R_ONLY", R_ONLY),
        ("BACKEND_ONLY_ANALYSIS", BACKEND_ONLY_ANALYSIS),
    ):
        gone = allowlist - everything
        assert not gone, f"{label} lists names that no longer exist: {sorted(gone)}"


@pytest.mark.requires_r("jsonlite")
def test_the_inventories_find_a_plausible_number_of_functions(functions) -> None:
    # A broken import filter or an R environment that came back empty would
    # make every comparison above pass vacuously.
    for key, names in functions.items():
        assert len(names) > 40, f"the {key} inventory found only {len(names)} functions"


KNOWN_PARAMETER_RENAMES = {
    ("count_missed_cleavages", 0): ("sequence", "sequences"),
}


@pytest.mark.requires_r("jsonlite")
def test_positional_arguments_mean_the_same_thing_in_both_packages(
    python_signatures, r_signatures
) -> None:
    pip_params = python_signatures["pip"]
    problems: list[str] = []
    for name in sorted(set(pip_params) & set(r_signatures)):
        left, right = pip_params[name], r_signatures[name]
        for index in range(min(len(left), len(right))):
            if left[index] == right[index]:
                continue
            known = KNOWN_PARAMETER_RENAMES.get((name, index))
            if known == (left[index], right[index]):
                continue
            problems.append(
                f"{name} slot {index + 1}: pip {left[index]!r} vs R {right[index]!r}"
            )
            break
    assert not problems, (
        "a positional argument means something different in the two packages:\n  "
        + "\n  ".join(problems)
    )
