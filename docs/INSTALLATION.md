# Installation, Running, and Packaging

Run commands from the repository root unless a section says otherwise.

## Prerequisites

- Python 3.10 or newer
- Node.js and npm
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

## Development launchers

Platform launchers are grouped under `packaging/` and resolve the repository root automatically.

### Windows

```powershell
.\packaging\windows\run_app.bat
.\packaging\windows\run_viewer.bat
.\packaging\windows\run_app_ai.bat [model-or-dev-flag]
.\packaging\windows\run_viewer_ai.bat [model-or-dev-flag] [--project NAME]
```

Supported development flags include `--dev`, `--dev0`, `--dev2`, and `--dev20`.

### macOS

```bash
bash packaging/macos/run_app_macos.sh
bash packaging/macos/run_viewer_macos.sh
bash packaging/macos/run_app_ai_macos.sh [model-or-dev-flag]
bash packaging/macos/run_viewer_ai_macos.sh [model-or-dev-flag] [--project NAME]
```

### Linux

```bash
bash packaging/linux/run_app_linux.sh
bash packaging/linux/run_viewer_linux.sh
bash packaging/linux/run_app_ai_linux.sh [model-or-dev-flag]
bash packaging/linux/run_viewer_ai_linux.sh [model-or-dev-flag] [--project NAME]
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
When a reverse proxy is used, configure `COPYLOT_TRUSTED_PROXY_IPS` so the backend can enforce
this policy against the forwarded client address.

## Request and upload limits

| Variable | Default | Purpose |
| --- | --- | --- |
| `COPYLOT_SESSION_ISOLATION` | `1` | Each browser session gets its own datasets, annotations and caches. |
| `COPYLOT_ALLOWED_HOSTS` | loopback names | Extra `Host` header values the server will answer to, comma separated. |
| `COPYLOT_UPLOAD_MAX_BYTES` | 512 MiB | Size limit applied to the upload as it arrives. |
| `COPYLOT_UPLOAD_MAX_CELLS` | 50,000,000 | Row x column limit applied to the parsed table. |

**Session isolation is on by default.** With it off, every request resolves to the
session id `global`, so two browsers on the same machine share one state and the
second one reads and can overwrite the first one's uploaded data. Set
`COPYLOT_SESSION_ISOLATION=0` only for a genuinely single-user desktop run — for
instance if you rely on opening the same dataset in two tabs. A
password-protected deployment refuses to start with it disabled.

**Host header allowlist.** The server answers only to `localhost`, `127.0.0.1`,
`::1` and `0.0.0.0`, with or without a port. This is the standard defence against
DNS rebinding, where a page you visit re-points its own hostname at `127.0.0.1`
and then talks to this server from your browser: the request genuinely originates
from loopback and is same-origin, so neither the peer-address check nor CORS
applies, and the hostname is the only thing left to test. When serving under a
real name, add it:

```bash
COPYLOT_ALLOWED_HOSTS=proteomics.institute.example
```

**Upload limits.** The byte limit measures the upload as received, which is
compressed for parquet and xlsx — a 0.28 MB parquet can expand past 1 GB once
parsed. `COPYLOT_UPLOAD_MAX_CELLS` bounds the parsed shape instead. For parquet
the check reads the file's own metadata, so an oversized table is refused before
it is materialised.

## Frontend modes

The analysis and viewer bundles are distinct builds:

```powershell
cd frontend
cmd /c "set VITE_APP_MODE=analysis&& npm run build"
cmd /c "set VITE_APP_MODE=viewer&& npm run build"
```

AI builds additionally set `VITE_AI_ENABLED=1`. Runtime AI mode requires `COPYLOT_AI_MODE=1` and an available Ollama endpoint.

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

Validate all six variant names and generated version resources without compiling:

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
```

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

Store the result as `password_pbkdf2_sha256`. Existing `password` and `password_sha256`
entries remain compatible, but PBKDF2 is recommended for published deployments.

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

The nginx example is `deploy/nginx/proteomics-data.de.conf.example`.

The Compose services use a read-only root filesystem, a writable temporary filesystem, and
generous CPU/memory limits. Override them in `.env` for unusually large projects without
editing the Compose files:

- analysis service: `COPYLOT_CONTAINER_MEMORY_LIMIT` (default `12g`),
  `COPYLOT_CONTAINER_CPUS` (default `4.0`), and `COPYLOT_CONTAINER_TMPFS_SIZE` (default `2g`);
- viewer services: `COPYLOT_VIEWER_MEMORY_LIMIT` (default `6g`),
  `COPYLOT_VIEWER_CPUS` (default `2.0`), and `COPYLOT_VIEWER_TMPFS_SIZE` (default `1g`).

Request limits are also configurable. Defaults allow 512 MiB per ordinary/replacement upload,
1 GiB across restore replacements, 64 MiB compressed and 256 MiB expanded restore state, and
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
listed in `COPYLOT_TRUSTED_PROXY_IPS`. Set that variable in the Compose `.env` file to the
exact peer address seen by the container. The nginx example replaces client-supplied
`X-Forwarded-For` values before proxying.

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
