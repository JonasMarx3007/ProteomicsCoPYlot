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
# Backend and repository tests
pytest tests/backend tests/repository -q

# Cross-implementation parity: Python, R and the backend must agree
pytest tests/package -q

# Lint (Python)
ruff check .

# Types (Python) -- see "Type checking" below
mypy

# Coverage, when you want to know
pytest tests/backend --cov --cov-report=term-missing
```

```bash
cd frontend
npm run build     # tsc -b && vite build -- this is the type check
npm run lint
npm test          # node --test
npm run test:browser
```

The R parity tests need `Rscript` with the packages the R helper imports. If
`Rscript` is missing they skip rather than fail; CI runs them for real, so a
change to `notebook_functions.R` is not verified locally unless you have R.

### Pre-commit

```bash
pip install pre-commit
pre-commit install
```

The hooks are whitespace and file hygiene plus `ruff check --fix`. They are fast
and they do not reformat your code. Run them over everything once with
`pre-commit run --all-files`.

## The three invariants

These are the things that are easy to break and expensive to notice later.

1. **The triplicate pipeline.** Every analysis function must exist in all three
   implementations — `backend/app/services/functions.py`,
   `proteomicscopylot/notebook_functions.py` and
   `proteomicscopylot/notebook_functions.R` — and return the same numbers.
   `tests/package/test_triplicate_parity.py` enforces this. Backend-only
   endpoints belong in its `BACKEND_ONLY_ANALYSIS` allowlist, with a reason.

2. **One data-source vocabulary.** A request names exactly one of
   `data | filtered | imputed`, defined once in `app.schemas.annotation` and
   resolved once by `functions.select_matrix`. `"data"` is the annotated,
   unfiltered matrix. Nothing falls back to another matrix. QC and the
   comparison pipeline have no selector at all; PCA, the statistics modules,
   ORA and the single-protein plots do, defaulting to the most processed matrix
   available. `tests/backend/test_one_data_source_vocabulary.py` is the
   statement of this rule in executable form — read it before adding a selector.

3. **Fold-change orientation.** `log2FC = mean(condition1) − mean(condition2)`,
   always. The first selected condition is the minuend, everywhere, including
   the axis labels and the text the AI assistant produces.

## Tests

A bug fix comes with a test that fails before it and passes after. Please check
that yourself by reverting the fix and watching the test fail — a test that
passes against the broken code is worse than no test, because it is a claim that
the bug is gone.

Prefer tests that load a real project and assert on real numbers over tests that
grep source files. Source scans are useful as a guard against a rule being
re-broken (`this unit must not be hardcoded again`), not as evidence that
something works.

Report output is fingerprinted: `tests/backend/test_report_preservation.py`
holds SHA-256 hashes for 24 cases. If your change alters a report on purpose,
update the fingerprints in the same change and say in the pull request what
moved and why.

## Style

- Python: ruff with Pyflakes rules (`select = ["F"]`). Style and modernisation
  rules are deliberately off for now; adding them means working through roughly
  200 findings, which is its own change, not a drive-by.
- Formatting: `ruff format` is configured but **not** enforced. Reformatting the
  repository today would touch 147 files, so please do not run it across the
  tree as part of an unrelated change. `ruff format --diff path/to/file.py`
  shows what it would do if you want to match the house style in new code.
- Frontend: ESLint and TypeScript, both gating in CI.

### Type checking

`mypy` is configured leniently and is **not** gating. It reports around 75
pre-existing findings on a clean tree, so treat it as a tool you point at the
code you touched rather than a build step:

```bash
mypy backend/app/services/your_module.py
```

Please do not add to the count. Tightening a module is welcome as its own
change, via a `[[tool.mypy.overrides]]` block.

## Pull requests

- One concern per pull request.
- Say what a reviewer should check to believe the change works.
- Leave `CHANGELOG.md` as a placeholder until the first official release.
  After that, record changes under `## [Unreleased]`, marking changes to
  previously released numbers or labels as **Changed (breaking)**.
- Do not edit the plot manuals (`frontend/public/manuals/`) or their build
  copies. They are maintained separately, and a user-facing rename that
  desynchronises them is a coordinated change, not an incidental one.

## Reporting a bug

Open an issue with the dataset shape (kinds, number of samples, conditions), the
exact steps, what you expected and what you got. A screenshot of the plot and
the numbers in the table beside it is usually enough. For anything that looks
like a security problem, see [SECURITY.md](SECURITY.md) instead.
