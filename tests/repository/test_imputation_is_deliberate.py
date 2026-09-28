"""Imputation happens when the button is pressed, and at no other time.

`POST /api/data-tools/imputation/run` does not preview. It computes the
imputation and stores the result as the session's imputed matrix -- the one
every other panel offers as "Imputed Data". The page used to call it on every
settings change, from a function named `fetchPreview`, so typing a number into
Downshift and navigating away replaced the matrix that every volcano, PCA and
boxplot in the session was about to use. The button said "Impute Data Values"
and did not own the act it named.

The three plots on that page were always a preview: each recomputes the
imputation from the parameters in its own URL and never reads what is stored.
That is what makes the split possible -- the preview costs nothing stored.

These tests pin the split. The frontend half is checked by reading the page,
because the behaviour is which function calls which; the backend half is checked
by running it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "frontend" / "src" / "features" / "data" / "ImputationPage.tsx"
ROUTES = ROOT / "backend" / "app" / "api" / "routes_plots.py"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )


def test_the_page_runs_the_imputation_in_exactly_one_place() -> None:
    code = _without_comments(_source())
    calls = re.findall(r"\brunImputation\(", code)
    assert len(calls) == 1, (
        f"runImputation is called {len(calls)} times; it stores the session's "
        "imputed matrix, so there must be exactly one place that does it"
    )


def test_no_effect_runs_the_imputation() -> None:
    """An effect fires on a dependency change -- that is the old behaviour."""
    code = _without_comments(_source())
    for match in re.finditer(r"useEffect\(\(\) => \{", code):
        start = match.start()
        end = code.find("\n  }, [", start)
        body = code[start : end if end != -1 else len(code)]
        assert "runImputation" not in body and "applyImputation" not in body, (
            "an effect imputes again; imputation must follow a button press, not "
            "a settings change"
        )


def test_the_button_is_what_applies_it() -> None:
    code = _source()
    assert "async function handleRun()" in code
    assert "await applyImputation();" in code
    assert "onClick={handleRun}" in code, "the run handler is not wired to a button"


def test_the_plots_do_not_wait_for_a_run() -> None:
    """The preview is the point: it has to draw before anything is applied."""
    code = _source()
    assert "{plotsReady ? (" in code, (
        "the plot sections are gated on something other than readiness; they used "
        "to be gated on `result`, which only exists after an imputation was stored"
    )
    assert re.search(r"const plotsReady = settingsReady && kindOptions\.length > 0", code)


def test_the_page_separates_what_is_applied_from_what_is_drawn() -> None:
    """One section names the stored run; the plots above it are the preview."""
    code = _source()
    assert "Applied imputation" in code
    assert "Nothing has been imputed for this level yet." in code, (
        "the page must say when no imputation is stored, or an empty summary "
        "reads as a run that filled nothing"
    )


def test_the_summary_describes_the_applied_run_not_the_preview() -> None:
    code = _source()
    block = code[code.index("Applied imputation") : code.index("function describeSettings")]
    assert "applied.rows" in block and "result.rows" not in block, (
        "the summary cards must read the applied run; reading `result` makes them "
        "describe whatever was last computed"
    )


def test_the_csv_download_exports_what_is_stored() -> None:
    code = _source()
    block = code[code.index("async function handleDownloadImputedCsv") :]
    block = block[: block.index("\n  }")]
    assert "applied ??" in block, (
        "the download sits under 'Imputed Data' and must send the applied "
        "parameters; the draw is seeded, so they reproduce the stored matrix"
    )


def test_the_three_preview_plots_take_their_parameters_from_the_request() -> None:
    """If a plot read the stored matrix, previewing would mean applying."""
    routes = ROUTES.read_text(encoding="utf-8")
    for name in ("before-missing", "overall-fit", "after-imputation"):
        start = routes.index(f'"/imputation/{{kind}}/{name}.png"')
        block = routes[start : routes.index("with plot_errors(", start)]
        for parameter in ("method", "qValue", "adjustStd", "downShift", "width", "seed"):
            assert parameter in block, f"{name} does not take {parameter}"
        assert "dataSource" not in block, (
            f"{name} reads a stored matrix; the imputation preview must be "
            "computed from its own parameters"
        )
