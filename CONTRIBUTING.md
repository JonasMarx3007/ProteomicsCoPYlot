# Contributing

Thanks for taking an interest in Proteomics CoPYlot. This file covers how to set
up a development environment, what the checks are, and what a change is expected
to come with.

## Getting set up

Backend and package (Python 3.10–3.13):

```bash
python -m venv backend/.venv
# Windows: backend\.venv\Scripts\activate
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
pip install -e ".[dev]"
```

Frontend (Node 24):

```bash
cd frontend
npm ci
```

`backend/requirements.lock` pins the exact versions CI runs against;
`backend/requirements.txt` is the compatible range. Use the lock file when you
need to reproduce a CI result exactly.

## Running the checks

Everything below is what CI runs, so a green local run should mean a green pull
request.

```bash
# All Python tests (CI: every Python 3.10-3.13, plus Windows; the package
# and parity tests also on macOS). See tests/README.md for the layout.
# Runs in two workers (pytest-xdist); `pytest -q -n 0` for a serial run.
pytest -q

# Lint (Python) -- CI pins ruff 0.15.11, the version the pre-commit hook uses
ruff check .
python tools/check_backend_rules.py   # backend code-shape rules ruff lacks

# Types (Python) -- CI pins mypy 2.3.1; see "Type checking" below
mypy

# Coverage -- CI fails below `fail_under` in pyproject.toml
pytest --cov --cov-report=term-missing

# The R functions' own tests (testthat)
Rscript tests/r/test_notebook_functions.R
```

```bash
cd frontend
npm run build     # tsc -b && vite build -- this is the type check
npm run lint
npm test          # vitest: tests/unit and tests/component
npm run generate:api   # after changing a route, schema or plot limit
npm run test:browser
```

### R

The tests that run R are marked `@pytest.mark.requires_r("pkg", ...)` with the R
packages they need. If `Rscript` or one of those packages is missing they skip
and say what is missing; with `COPYLOT_REQUIRE_R=1` (set in CI) they fail
instead. `tests/r/renv.lock` pins the R version and packages CI uses (R 4.4.2,
a dated CRAN snapshot, Bioconductor 3.20). To reproduce it:

```r
install.packages("renv")
renv::restore(lockfile = "tests/r/renv.lock", library = Sys.getenv("R_LIBS_USER"))
```

Besides the packages the R helper uses, the tests need `testthat` and
`jsonlite`. A change to `notebook_functions.R` is not verified locally unless you
have R.

### Pre-commit

```bash
pip install pre-commit
pre-commit install
```

The hooks are whitespace and file hygiene plus `ruff check --fix`. They are fast
and they do not reformat your code. Run them over everything once with
`pre-commit run --all-files`.

## Tests

A bug fix comes with a test that fails before it and passes after. Please check
that yourself by reverting the fix and watching the test fail; a test that
passes against the broken code is worse than no test, because it is a claim that
the bug is gone.

Prefer tests that load a real project and assert on real numbers. Do not write
tests that read source files for a string: a rule about behaviour is tested by
running it (a component test mounts the page with the API mocked), a value both
sides must agree on comes from the generated API files, and a rule about how
code is written is a lint rule (`frontend/eslint.config.js`,
`tools/check_backend_rules.py`). `tests/README.md` says which goes where.

Report output is fingerprinted: `tests/unit/report/test_report_preservation.py`
holds SHA-256 hashes for 24 cases. If your change alters a report on purpose,
update the fingerprints in the same change and say in the pull request what
moved and why.

## Style

- Python: ruff with Pyflakes rules (`select = ["F"]`), gating in CI. Test files
  may import a pytest fixture from another test module, which Pyflakes reports as
  an unused import and a redefinition, so F401 and F811 are off under `tests/`.
  Style and modernisation rules are deliberately off for now; adding them means
  working through roughly 200 findings, which is its own change, not a drive-by.
- Formatting: `ruff format` is configured but **not** enforced. Reformatting the
  repository today would touch 147 files, so please do not run it across the
  tree as part of an unrelated change. `ruff format --diff path/to/file.py`
  shows what it would do if you want to match the house style in new code.
- Frontend: ESLint and TypeScript, both gating in CI.

### Type checking

`mypy` is configured leniently and runs in CI. It is being adopted module by
module: the modules that had findings when it entered CI (October 2026) are
listed in `pyproject.toml` under `[[tool.mypy.overrides]]` with
`ignore_errors = true`, and every other module must stay clean. To adopt a
module, delete its line from that list and fix what `mypy` then reports, as a
change of its own. Never add a module to the list.

## Pull requests

- One concern per pull request.
- Say what a reviewer should check to believe the change works.
- Leave `CHANGELOG.md` as a placeholder until the first official release.
  After that, record changes under `## [Unreleased]`, marking changes to
  previously released numbers or labels as **Changed (breaking)**.
- Do not edit the manual PDFs (`frontend/public/manuals/`) by hand. They are
  built from the manual's LaTeX sources, which are maintained separately: one
  PDF per page of the app (mapped in `frontend/src/lib/manualChapters.ts`) and
  the complete book. A user-facing rename that desynchronises them is a
  coordinated change, not an incidental one.

## Reporting a bug

Open an issue with the dataset shape (kinds, number of samples, conditions), the
exact steps, what you expected and what you got. A screenshot of the plot and
the numbers in the table beside it is usually enough. For anything that looks
like a security problem, see [SECURITY.md](SECURITY.md) instead.
