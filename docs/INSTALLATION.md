# Installation, Running, and Packaging

Run commands from the repository root unless a section says otherwise.

## Notebook export memory

Notebook exports default to one eighth of physical RAM per session and one
quarter across the server, constrained by a detected container memory limit.
A 32 GiB machine therefore allows about 4 GiB per session and 8 GiB total.
Override these with `COPYLOT_NOTEBOOK_SESSION_MEMORY_MB` and
`COPYLOT_NOTEBOOK_MEMORY_MB` (MiB); the session limit must not exceed the total.
Budgets include retained source tables, counted once when shared between exports,
and are rechecked after deferred preparation. Archive resources use the same
session budget rather than a separate 128 MiB ceiling. Other application data
and transient ZIP-building allocations need additional RAM.

## Prerequisites

- Python 3.10 or newer
- Node.js 24 LTS and npm
- Optional: [Ollama](https://ollama.com) for AI mode
- Optional: R with `Rscript` for the R notebook-compatible helpers

## Install

### Windows

```powershell
py -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
```

For development and tests, also install:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

### macOS and Linux

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend install
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

### Reproducible dependency sets

- `backend/requirements-runtime.lock` is the exact Python 3.13 production set used by the Docker image and audited by security CI.
- `backend/requirements.lock` is the exact Python 3.13 development and reference-test set. It contains the runtime set plus test and packaging tools.
- `backend/requirements.txt` and `backend/requirements-dev.txt` retain bounded ranges for supported-version compatibility testing, including Python 3.10–3.12.

Install an exact local reference environment with:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
.\backend\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

## Development launchers

Platform launchers are grouped under `packaging/` and resolve the repository root automatically.
Viewer launchers keep session isolation enabled. Windows launchers check both required
ports before starting anything and stop with a message if either is occupied; they never
terminate an existing process to free a port.

### Windows

```powershell
.\packaging\windows\run_app.bat
.\packaging\windows\run_viewer.bat
.\packaging\windows\run_app_ai.bat [MODEL]
.\packaging\windows\run_viewer_ai.bat [MODEL] [--project NAME]
```

AI launchers accept an optional model name. Select the Ollama endpoint in AI settings; remote origins must be allowed with `COPYLOT_OLLAMA_ALLOWED_ENDPOINTS` in the backend environment.

### macOS

```bash
bash packaging/macos/run_app_macos.sh
bash packaging/macos/run_viewer_macos.sh
bash packaging/macos/run_app_ai_macos.sh [MODEL]
bash packaging/macos/run_viewer_ai_macos.sh [MODEL] [--project NAME]
```

### Linux

```bash
bash packaging/linux/run_app_linux.sh
bash packaging/linux/run_viewer_linux.sh
bash packaging/linux/run_app_ai_linux.sh [MODEL]
bash packaging/linux/run_viewer_ai_linux.sh [MODEL] [--project NAME]
```

Viewer projects can be selected with `--project NAME`, `--project=NAME`, or the existing shorthand `--NAME`.

## Production launch

Build the frontend and let the shared launcher serve it through FastAPI:

```powershell
npm.cmd --prefix frontend run build
.\backend\.venv\Scripts\python.exe launch.py
.\backend\.venv\Scripts\python.exe launch.py --viewer --port 8001
```

On macOS/Linux, use `backend/.venv/bin/python` instead.

The launcher binds to loopback by default. A non-loopback host such as `0.0.0.0` is refused
unless tool/viewer authentication and session isolation are both enabled. For example, set
`COPYLOT_TOOL_ACCESS_ENABLED=1`, configure `COPYLOT_TOOL_ACCESS_FILE`, and set
`COPYLOT_SESSION_ISOLATION=1` before using `--host 0.0.0.0`. The launcher validates the
authentication files when the application starts and fails closed when they are missing or
invalid.

`--allow-unsafe-public` is an explicit emergency/development override for an unauthenticated
non-loopback bind. It prints a warning and must not be used for sensitive data. Even with this
override, remote clients cannot call server-local path operations such as `table-path`,
`peptide-path`, peptide-collapse-by-path, or restore-by-path; use file-upload endpoints instead.
Restore uploads from remote or protected sessions ignore saved dataset paths and replacement
`sourcePath` values and require the dataset files to be uploaded. No server path is probed or
opened. Ordinary local desktop restoration keeps its existing path-based behavior.
When a reverse proxy is used, configure `COPYLOT_TRUSTED_PROXY_IPS` so the backend can enforce
this policy against the forwarded client address.

## Request and upload limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPYLOT_SESSION_ISOLATION` | `1` | Each browser session gets its own datasets, annotations and caches. |
| `COPYLOT_ALLOWED_HOSTS` | loopback names | Extra `Host` header values the server will answer to, comma separated. |
| `COPYLOT_UPLOAD_MAX_BYTES` | 64 GiB | Size limit applied to the upload as it arrives. |
| `COPYLOT_UPLOAD_MAX_CELLS` | 10,000,000,000 | Row x column limit applied to the parsed table. |
| `COPYLOT_UPLOAD_MAX_FRAME_BYTES` | 25% of physical/container RAM, at most 128 GiB | Parsed-table memory budget; explicit byte values override automatic sizing. If RAM cannot be detected, the fallback is 1 GiB. |
| `COPYLOT_UPLOAD_MAX_COLUMNS` | 20,000 | Protects against malformed or accidentally transposed files. |

**Session isolation is on by default and required by the browser UI.** Each tab
has its own API namespace and path-scoped HttpOnly cookie, so tabs can open
different projects. Refresh resets only that tab. The routing ID in a plot or
download URL is not a login credential; another browser still needs authentication.
Cookies and routing IDs are not included in saved analysis state.

When a reverse proxy strips a URL prefix, rewrite the scoped cookie path too.
The supplied nginx `/viewer/` location uses
`proxy_cookie_path /api/tabs/ /viewer/api/tabs/;`. Adapt that prefix for other
subpath deployments; do not flatten all tab cookies to a shared root path.

`COPYLOT_SESSION_ISOLATION=0` retains shared-state behavior only for legacy,
single-user API clients; the tab-scoped browser UI refuses it. Password-protected
deployments also refuse this configuration. Existing direct `/api/` clients
continue to use their original cookie/header session behavior.

**Host header allowlist.** The server answers only to `localhost`, `127.0.0.1`
and `::1` (written `[::1]` in a URL), with or without a port. This is the standard
defence against DNS rebinding, where a page you visit re-points its own hostname
at `127.0.0.1` and then talks to this server from your browser: the request
genuinely originates from loopback and is same-origin, so neither the peer-address
check nor CORS applies, and the hostname is the only thing left to test.
`0.0.0.0` is not on the list: it is an address to listen on, not a name a browser
sends, so `http://0.0.0.0:...` is refused. When serving under a real name, or
reaching the server from another machine, add the name or address you type in
the browser:

```bash
COPYLOT_ALLOWED_HOSTS=proteomics.institute.example
```

**Upload limits.** The byte limit measures the upload as received, which is
compressed for parquet and xlsx — a 0.28 MB parquet can expand past 1 GB once
parsed. `COPYLOT_UPLOAD_MAX_CELLS` bounds the parsed shape instead. For parquet
the check reads the file's own metadata, so an oversized table is refused before
it is materialised.

These defaults admit large precursor reports: 500 samples × 100,000 precursors
× 70 columns represent 3.5 billion cells. File size and cell count are not a
promise that the data fits in RAM. The current analysis engine materializes
tables and creates processing copies; it is not an out-of-core engine. On a
32 GiB machine the automatic parsed-table budget is about 8 GiB, while a
256 GiB server permits about 64 GiB. Multiple sessions also share that RAM.
Raise the explicit memory budget only with sufficient memory for parsing and
analysis copies. For files beyond one Excel worksheet's row limit, use TSV or
Parquet. Keep the reverse proxy's request limit aligned with the file limit,
including multipart overhead; the supplied nginx example allows 65 GiB requests.
Existing deployed proxy settings must be updated separately. Save-state and
notebook-export limits remain separate from data-upload limits.

## Frontend modes

The analysis and viewer bundles are distinct builds:

```powershell
cd frontend
cmd /c "set VITE_APP_MODE=analysis&& npm run build"
cmd /c "set VITE_APP_MODE=viewer&& npm run build"
```

AI builds additionally set `VITE_AI_ENABLED=1`. Runtime AI mode requires
`COPYLOT_AI_MODE=1` and either an available Ollama endpoint or a configured cloud
provider. Cloud requests require consent.

Provider responses are limited by `COPYLOT_PROVIDER_RESPONSE_MAX_BYTES` (default
8 MiB). This applies to each buffered HTTP response and accepts positive byte
counts. Oversized responses fail rather than being silently
truncated. These are output-size limits, not total request deadlines or a promise
that disconnecting cancels work already accepted by a provider.

Provider routes have a separate per-process concurrency budget:
`COPYLOT_PROVIDER_MAX_CONCURRENCY` (default 4), `COPYLOT_PROVIDER_MAX_QUEUE`
(default 8, 0 disables waiting), and `COPYLOT_PROVIDER_QUEUE_TIMEOUT_SECONDS`
(default 20). A slot remains occupied through the assistant step and cleanup. Saturation
returns HTTP 503 with a retry hint; scientific analysis uses its own budget.
Chat's Stop button aborts the browser request, but cannot guarantee cancellation
of work already accepted by an external model service.

`COPYLOT_PROVIDER_TIMEOUT_SECONDS` (default 180) sets the admitted provider
operation's time budget, shared across metadata lookups, planning and explanation
within one assistant step. A multi-step UI request uses separate admitted steps.
Model installation/removal instead uses `COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT`
(default 1800). Queue waiting has its own timeout. Connected HTTP responses have
a deadline watchdog that shuts down stalled/trickling connections. The response
lifecycle is also timed. System DNS resolution and external provider cancellation are not
guaranteed to obey this application deadline.

Model-management command output is collected incrementally using the response
byte limit above. Commands are killed and reaped on timeout or excessive output;
failed command diagnostics are not exposed verbatim to clients. This terminates
the CLI process, not necessarily work already accepted by the Ollama daemon.

Static Matplotlib PDF downloads are serialized directly from the figure, with
embedded TrueType fonts and vector drawing objects. Browser previews remain PNG;
image-based plot elements (such as image-rendered heatmaps) can still contain
pixels inside a native PDF. The notebook and interactive Plotly export paths are
unchanged. Static exports preserve their figure canvas dimensions (bitmap output
is rounded to whole pixels). Layout is fitted within that canvas, without
silently shrinking fonts. If labels cannot fit, increase the figure dimensions
or reduce text size; the export fails explicitly rather than clipping content.

## Windows one-file builds

```powershell
.\packaging\windows\build_exe_windows.ps1 -Target Tool
.\packaging\windows\build_exe_windows.ps1 -Target Viewer
.\packaging\windows\build_exe_windows.ps1 -Target Viewer -ViewerProject HEK293
```

Each build automatically embeds Windows File/Product Version metadata derived from
`pyproject.toml`. The build fails before compilation if that version differs from
`backend/app/app_version.py` or `proteomicscopylot/_version.py`. Variant builds pass
`-ExecutableName` so `OriginalFilename`, `InternalName`, and the output filename agree.

The default bundles use the checked-in root viewer configuration and canonical package example
data. `-ViewerProject` accepts only Git-tracked projects directly under `viewer_data/`; private
`local/`, `projects/`, local configs, credentials, and untracked files are never bundled.

Outputs:

- `dist/ProteomicsCoPYlot.exe`
- `dist/DataViewer.exe`

Build all configured Windows variants with:

```powershell
.\packaging\windows\build_all_windows_variants.cmd
```

Validate all four variant names and generated version resources without compiling:

```powershell
.\packaging\windows\build_all_windows_variants.cmd --validate-only
```

For a signed release, install a trusted code-signing certificate in the Windows
certificate store and install `signtool.exe` from the Windows SDK. Configure the
certificate by thumbprint outside the repository, then explicitly request signing:

```powershell
$env:COPYLOT_SIGNING_CERT_THUMBPRINT = "0123456789ABCDEF0123456789ABCDEF01234567"
# Only when the certificate is in the LocalMachine rather than CurrentUser store:
$env:COPYLOT_SIGNING_CERT_MACHINE_STORE = "1"
# Optional when signtool.exe is not on PATH:
$env:COPYLOT_SIGNTOOL_PATH = "C:\Program Files (x86)\Windows Kits\10\bin\<sdk-version>\x64\signtool.exe"

# Check the certificate, private key, code-signing purpose, validity dates, and SignTool first:
.\packaging\windows\build_all_windows_variants.cmd --validate-only --sign
# Compile and sign only after that preflight succeeds:
.\packaging\windows\build_all_windows_variants.cmd --sign
```

Signing uses SHA-256, an RFC 3161 timestamp, and verifies every signature immediately.
Never commit a PFX file, private key, or certificate password. Confirm release files with:

```powershell
Get-AuthenticodeSignature .\dist\*.exe | Format-Table Path, Status, StatusMessage
```

macOS variant builds are under `packaging/macos/`.

## Python package

Install the notebook-facing package locally:

```bash
python -m pip install -e ".[bio]"
```

The `bio` extra enables enrichment and FASTA parsing. Install the packages used by
the complete R helper from an R session:

```r
install.packages(c("arrow", "hexbin", "plotly", "readxl", "scatterplot3d", "VennDiagram"))
# VSN normalization (optional) comes from Bioconductor:
install.packages("BiocManager"); BiocManager::install("vsn")
```

The exact versions the tests run against are in `tests/r/renv.lock`.

Build source and wheel distributions:

```bash
python packaging/python/build_pip_package.py
```

The builder cleans only the managed `release/python/` directory, creates one versioned wheel
and one versioned source archive under `release/python/<version>/`, and fails if that exact
artifact set is not produced. Upload
those two verified paths explicitly; do not publish with a wildcard from the shared `dist/`
directory, which is also used by executable builds.

Every PyPI upload requires a new version in both `pyproject.toml` and
`proteomicscopylot/_version.py`.

## Validation

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
docker compose config -q
docker compose -f docker-compose.viewer.yml config -q
```

The frontend lint command must complete with zero errors. Hook dependency advisories are
reported as warnings and should be reduced when their owning components are changed.

## Viewer portal

For password-to-project routing, set:

- `COPYLOT_VIEWER_MODE=1`
- `COPYLOT_VIEWER_PORTAL_ENABLED=1`
- `COPYLOT_VIEWER_ACCESS_FILE=/app/local/viewer_access.local.json`
- `COPYLOT_SESSION_ISOLATION=1`

Use `viewer_access.example.json` as the public template. Keep real credentials under ignored `local/` files.

Project data belongs in `viewer_data/<ProjectName>/`. Private local-only projects may use `viewer_data/local/<ProjectName>/`.

## Docker

For an isolated runtime check (Docker running; backend development environment active):

```bash
docker build --build-arg FRONTEND_TOOL_ACCESS_AUTH=1 --build-arg FRONTEND_RESET_ON_BROWSER_LOAD=1 -t copylot-runtime-check .
python tests/docker_runtime_check.py copylot-runtime-check
```

This uses the Python 3.13 runtime lock, disposable synthetic data/credentials, loopback-only
ports and a temporary locally trusted TLS certificate. It checks the hardened analysis
container, R/VSN, authentication, isolation and portable save/restore, then removes its test
container and temporary files. It does not validate the live nginx host or viewer deployment.

Create the ignored local credential files before starting either Compose stack:

```bash
mkdir -p local
cp tool_access.example.json local/tool_access.local.json
cp viewer_access.example.json local/viewer_access.local.json
cp viewer_qr_access.example.json local/viewer_qr_access.local.json
```

Replace every zero digest before deployment. Generate the preferred salted PBKDF2 value
without placing the password directly in shell history:

```bash
python -c "import getpass,sys; sys.path.insert(0,'backend'); from app.services.password_hashing import hash_password; print(hash_password(getpass.getpass()))"
```

Store the result as `password_pbkdf2_sha256`. This is the only accepted form: access files
that still carry a plaintext `password`, an unsalted `password_sha256`, or the old
`passwords` object are refused at startup with a message naming the entry, so every
deployment re-hashes once and the weak forms are gone.

Access-link and QR secrets are reusable bearer credentials. Put them only in named URL
fragments such as `#tool=SECRET` or `#qr=SECRET`; query-string credentials are ignored.
Links made for older versions with `?tool=` or `?qr=` must be rewritten, and any token
previously exposed in a query string should be rotated.

General deployment:

```bash
docker compose up -d --build
```

Viewer portals:

```bash
docker compose -f docker-compose.viewer.yml up -d --build
```

The nginx example is `deploy/nginx/copylot.conf.example`. Replace its example
hostnames and certificate paths with your own. Set `COPYLOT_ALLOWED_HOSTS` in
your deployment environment or `.env` to your public hostname(s), comma separated;
the Compose defaults allow only localhost and 127.0.0.1.

The Compose services use a read-only root filesystem, a writable temporary filesystem, and
generous CPU/memory limits. Override them in `.env` for unusually large projects without
editing the Compose files:

- analysis service: `COPYLOT_CONTAINER_MEMORY_LIMIT` (default `12g`),
  `COPYLOT_CONTAINER_CPUS` (default `4.0`), and `COPYLOT_CONTAINER_TMPFS_SIZE` (default `2g`);
- viewer services: `COPYLOT_VIEWER_MEMORY_LIMIT` (default `6g`),
  `COPYLOT_VIEWER_CPUS` (default `2.0`), and `COPYLOT_VIEWER_TMPFS_SIZE` (default `1g`).

Request limits are also configurable. Defaults allow 64 GiB per ordinary/replacement upload,
128 GiB across restore replacements, 64 MiB compressed and 256 MiB expanded restore state, and
128 MiB for plot conversion. The corresponding variables are `COPYLOT_UPLOAD_MAX_BYTES`,
`COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES`, `COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES`,
`COPYLOT_RESTORE_UPLOAD_MAX_BYTES`, `COPYLOT_RESTORE_EXPANDED_MAX_BYTES`, and
`COPYLOT_PLOT_CONVERSION_MAX_BYTES`. Embedded restore tables additionally default to five
million rows, 50,000 columns, and 50 million cells; adjust
`COPYLOT_RESTORE_TABLE_MAX_ROWS`, `COPYLOT_RESTORE_TABLE_MAX_COLUMNS`, and
`COPYLOT_RESTORE_TABLE_MAX_CELLS` only when a legitimate saved project requires it.

Regular save states retain absolute dataset paths so they can reopen data on the same machine.
Before sharing a state file or moving it to another system, use **Save Portable State**. Portable
states omit those paths and prompt the user to supply the referenced dataset files during restore.

Heavy parsing, analysis, and plot requests are admitted through a bounded queue before FastAPI
dispatches their synchronous calculation code to worker threads. Defaults allow two simultaneous
heavy jobs, eight waiting jobs, a 20-second queue wait, and 16 total synchronous worker threads.
Tune `COPYLOT_HEAVY_MAX_CONCURRENCY`, `COPYLOT_HEAVY_MAX_QUEUE`,
`COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS`, and `COPYLOT_THREAD_WORKERS` together with the container
CPU/memory limits. Raising concurrency can increase throughput on a large host but also multiplies
peak DataFrame and plot memory. A full or timed-out queue returns HTTP 503 with `Retry-After` rather
than allowing unbounded requests to exhaust the service.

The login limiter ignores forwarded client addresses unless the direct reverse-proxy peer is
listed in `COPYLOT_TRUSTED_PROXY_IPS` (single addresses or CIDR ranges, comma-separated). The
Compose files default it to the Docker bridge range `172.16.0.0/12`, which is where a reverse
proxy on the host appears from inside the container; without a trusted proxy every client
shares the proxy's address and twelve failed logins from anyone lock everyone out. Override it
in the Compose `.env` file when the proxy runs elsewhere. The nginx example replaces
client-supplied `X-Forwarded-For` values before proxying. A successful login clears that
client's failed-attempt count.

Authentication and analysis state are held in process memory. Run one application worker and
one replica per deployed service unless session and dataset stores are replaced with shared
storage.

## Remote Ollama over Tailscale

1. Install Ollama and Tailscale on the host.
2. Bind Ollama to the tailnet-accessible interface, for example `OLLAMA_HOST=0.0.0.0:11434`.
3. Pull the intended model with `ollama pull MODEL`.
4. Allow TCP port `11434` through the host firewall when needed.
5. From the client, verify `http://TAILSCALE_HOST:11434/api/tags`.
6. Add that exact origin to `COPYLOT_OLLAMA_ALLOWED_ENDPOINTS`, then enter it in the
   application's AI settings.

Do not commit private endpoints, credentials, or machine-specific configuration.
