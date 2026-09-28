from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app" / "services" / "functions.py"
PIP = ROOT / "proteomicscopylot" / "notebook_functions.py"
R = ROOT / "proteomicscopylot" / "notebook_functions.R"


def _normalise(name: str) -> str:
    return name.lstrip("._")


def _python_functions(path: Path) -> set[str]:
    return {
        _normalise(name)
        for name in re.findall(r"^def (\w+)", path.read_text(encoding="utf-8"), re.M)
    }


def _r_functions(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    assigned = re.findall(r"^([.\w]+)\s*<- function", source, re.M)
    assigned += re.findall(r'assign\("([^"]+)",\s*function', source)
    return {_normalise(name) for name in assigned}


_WEB_APP_RENDERING = re.compile(r"(_png|_html|_plot|_heatmap)$|^qc_")

BACKEND_ONLY_ANALYSIS = frozenset({
    "multipletests",  # statsmodels-shaped adapter over stats_core.bh_adjust; pip/R keep p.adjust / their own fallback.
    "comparison_contrast",  # UI contrast label, not a separate statistical method.
    "sample_label_frame",  # Plot/report display labels, not a statistical method.
    "condition_sample_labels",  # The "condition_N" axis label rule behind sample_label_frame.
    "entity_labels_for_kind",  # Entity nouns for report/UI prose, not a method.
    "intensity_unit_label",  # UI units for stored phosphoprotein provenance.
    "parse_selection_list",  # JSON/legacy HTTP selection transport.
    "select_matrix",
    "qc_matrix",
    "data_source_availability",
    "most_processed_data_source",
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
})

PIP_ONLY = frozenset({
    "adjust_finite_pvalues",  # R adjusts finite p-values inline in volcano calculations.
    "different_genes_column",
    "guarded_t_statistic",
    "negative_log10",
    "paired_t_test",
    "raw_zero_to_nan",
})

R_ONLY = frozenset({
    "numeric_matrix",
    "pivot_wide",
    "plot_colors",
    "plot_heatmap",
    "plot_result",
    "raw_zero_to_na",
    "require_pkg",
    "restore_layout",
    "set_notebook_plot_size",
    "set_plot_margins",
    "venn_base",
    "volcano_stats",
    "with_local_seed",
    "workflow_col",
})


@pytest.fixture(scope="module")
def functions() -> dict[str, set[str]]:
    for path in (BACKEND, PIP, R):
        assert path.exists(), f"pipeline file is missing: {path}"
    return {
        "backend": _python_functions(BACKEND),
        "pip": _python_functions(PIP),
        "r": _r_functions(R),
    }


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


def test_no_new_analysis_function_is_web_app_only(functions) -> None:
    backend_only = functions["backend"] - functions["pip"] - functions["r"]
    undeclared = {
        name
        for name in backend_only
        if not _WEB_APP_RENDERING.search(name)
    } - BACKEND_ONLY_ANALYSIS
    assert not undeclared, (
        f"analysis functions added to the web app only: {sorted(undeclared)}. "
        f"Add them to notebook_functions.py and notebook_functions.R, or to "
        f"BACKEND_ONLY_ANALYSIS here with a reason."
    )


@pytest.mark.parametrize(
    "name", ["anova_data_f", "anova_cluster_data", "anova_posthoc_data"]
)
def test_core_analysis_functions_are_in_every_pipeline(functions, name: str) -> None:
    missing = [key for key, names in functions.items() if name not in names]
    assert not missing, f"{name} is missing from: {missing}"


@pytest.mark.parametrize("name", ["volcano_data_f", "filter_data", "log2_transform_data"])
def test_core_package_functions_are_in_both_packages(functions, name: str) -> None:
    missing = [key for key in ("pip", "r") if name not in functions[key]]
    assert not missing, f"{name} is missing from: {missing}"


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


def test_allowlisted_names_still_exist_somewhere(functions) -> None:
    everything = functions["backend"] | functions["pip"] | functions["r"]
    for label, allowlist in (
        ("PIP_ONLY", PIP_ONLY),
        ("R_ONLY", R_ONLY),
        ("BACKEND_ONLY_ANALYSIS", BACKEND_ONLY_ANALYSIS),
    ):
        gone = allowlist - everything
        assert not gone, f"{label} lists names that no longer exist: {sorted(gone)}"


def test_the_parsers_find_a_plausible_number_of_functions(functions) -> None:
    for key, names in functions.items():
        assert len(names) > 40, f"{key} parser found only {len(names)} functions"


KNOWN_PARAMETER_RENAMES = {
    ("count_missed_cleavages", 0): ("sequence", "sequences"),
}


def _r_parameters() -> dict[str, list[str]]:
    source = R.read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    for match in re.finditer(r"^([.\w]+)\s*<- function\((.*?)\)\s*\{", source, re.S | re.M):
        name = _normalise(match.group(1))
        signature = "\n".join(
            re.sub(r"#.*", "", line) for line in match.group(2).splitlines()
        )
        params: list[str] = []
        depth = 0
        current = ""
        for char in signature:
            if char in "([": depth += 1
            elif char in ")]": depth -= 1
            if char == "," and depth == 0:
                params.append(current); current = ""
            else:
                current += char
        params.append(current)
        cleaned = []
        for raw in params:
            raw = re.sub(r"#.*", "", raw).strip()
            if not raw: continue
            cleaned.append(raw.split("=")[0].strip())
        out[name] = cleaned
    return out


def _pip_parameters() -> dict[str, list[str]]:
    import ast

    tree = ast.parse(PIP.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            args = node.args
            names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            out[_normalise(node.name)] = names
    return out


def test_positional_arguments_mean_the_same_thing_in_both_packages() -> None:
    pip_params = _pip_parameters()
    r_params = _r_parameters()
    problems: list[str] = []
    for name in sorted(set(pip_params) & set(r_params)):
        left, right = pip_params[name], r_params[name]
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
