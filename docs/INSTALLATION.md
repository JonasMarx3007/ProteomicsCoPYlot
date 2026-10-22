# Installation, Running, and Packaging

Every environment variable, with its default, is listed in [Environment variables](ENVIRONMENT.md).

Run commands from the repository root unless a section says otherwise.

## Prerequisites

- Python 3.11 or newer (an exported notebook requires the Python minor version it was exported with, or newer)
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
- `backend/requirements-runtime-hashed.lock` contains the same versions plus SHA-256 hashes
  for their published PyPI artifacts. Docker and macOS release builds require these hashes
  for packages downloaded by pip. Intel macOS installs Numba and llvmlite through Conda;
  packages already installed by Conda are outside pip's hash verification. Source-archive
  hashes verify the archive, not dependencies fetched by an isolated build environment.
  After reviewing runtime version updates, run `python tools/hash_runtime_requirements.py`
  and commit both lockfiles together. This records hashes without changing versions.
  For macOS release dispatches, select a `source_commit` containing the hash lock;
  historical commits without it cannot use the hash-enforcing installation step.
- `backend/requirements.lock` is the exact Python 3.13 development and reference-test set. It contains the runtime set plus test and packaging tools.
- `backend/requirements.txt` and `backend/requirements-dev.txt` retain bounded ranges for supported-version compatibility testing, including Python 3.11–3.12.

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

### macOS and Linux

One set of launchers serves both systems; only the way the browser is opened differs (`open` on macOS, `xdg-open` on Linux).

```bash
bash packaging/unix/run_app.sh
bash packaging/unix/run_viewer.sh
bash packaging/unix/run_app_ai.sh [MODEL]
bash packaging/unix/run_viewer_ai.sh [MODEL] [--project NAME]
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
A dataset upload always stores the uploaded bytes on the server and uses that copy as the
dataset's source; it accepts no client-supplied path. Saved-state fingerprints are computed
for regular files only, never for devices, pipes or sockets.
When a reverse proxy is used, configure `COPYLOT_TRUSTED_PROXY_IPS` so the backend can enforce
this policy against the forwarded client address.

## API documentation

When neither `COPYLOT_TOOL_ACCESS_ENABLED` nor `COPYLOT_VIEWER_PORTAL_ENABLED` is set
(the local desktop run), the backend serves its OpenAPI description at `/openapi.json`
and the interactive pages at `/docs` (Swagger UI) and `/redoc`. Behind either access
gate these three routes are disabled, so a deployed server does not publish its route
list; the same description is committed as `frontend/src/lib/generated/openapi.json`
and regenerated with `npm run generate:api`.

## Request and upload limits

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

**Host header allowlist.** Localhost is allowed by default. For remote access,
add the hostname or address used in the browser to `COPYLOT_ALLOWED_HOSTS`:

```bash
COPYLOT_ALLOWED_HOSTS=proteomics.institute.example
```

**Large datasets.** Analysis runs in memory, so available RAM can limit dataset
size even when an upload is accepted. Upload, restore and notebook-export limits
are configurable in [Environment variables](ENVIRONMENT.md). Match your reverse
proxy's request limit to the upload limit, allowing for multipart overhead.

## Frontend modes

The analysis and viewer bundles are distinct builds:

```powershell
cd frontend
cmd /c "set VITE_APP_MODE=analysis&& npm run build"
cmd /c "set VITE_APP_MODE=viewer&& npm run build"
```

AI builds additionally set `VITE_AI_ENABLED=1`. Runtime AI mode requires
`COPYLOT_AI_MODE=1` and either an available Ollama endpoint, a local server with
the OpenAI-compatible API, or a configured cloud provider. Cloud requests require
consent.

AI timeouts and concurrency settings are listed in
[Environment variables](ENVIRONMENT.md#ai-assistant). Stopping a chat request
does not guarantee cancellation of work already accepted by the model provider.

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

### macOS release downloads

The **Build macOS release** workflow builds standard and AI analysis applications
for Apple Silicon (`arm64`, macOS 14 runner) and Intel (`x86_64`, macOS 15 runner).
After merging the workflow, open **Actions > Build macOS release > Run workflow**.
The default source commit matches the existing `v1.0.0-beta.1` Windows/Linux
builds. For a later release, enter its full merged `main` commit SHA.

Each job checks the bundle hashes, source revision, startup, frontend, version
and AI mode before uploading an artifact. Download all four artifacts within
**3 days**. Extract the outer GitHub artifact ZIP; keep the versioned release ZIP
inside intact, together with its checksum. The workflow does not create a tag or
publish a release. These builds are not Developer ID signed or notarized.

For local macOS builds, install the backend virtual environment and frontend
dependencies first, then run
`bash packaging/macos/build_all_macos_variants.sh --variant standard`
(or `--variant ai`). With no variant argument, the script also builds both viewer
editions.

## Python package

Install the notebook-facing package from a checkout of this repository:

```bash
python -m pip install ".[bio]"
```

Add `-e` for an editable development install. The `bio` extra adds Biopython for
FASTA parsing (sequence coverage). Install the packages the R functions use from an
R session:

```r
install.packages(c("arrow", "hexbin", "plotly", "readxl", "scatterplot3d", "VennDiagram"))
# VSN normalization and the moderated t-tests (optional) come from Bioconductor:
install.packages("BiocManager"); BiocManager::install(c("vsn", "limma"))
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
docker build --build-arg FRONTEND_RESET_ON_BROWSER_LOAD=1 -t copylot-runtime-check .
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

Regular save states retain absolute dataset paths so they can reopen data on the same machine.
App-created temporary files are released when their last dataset is replaced or its session
is discarded. Shared datasets, active file readers, and restore rollback snapshots retain
their files. Original files opened by local path are not deleted. A regular save state that
references a released upload will ask for that original file again; derived tables remain
embedded in the save state. Startup cleanup removes crash leftovers older than seven days
(configurable with `COPYLOT_TEMP_FILE_MAX_AGE_SECONDS`).
Before sharing a state file or moving it to another system, use **Save Portable State**. Portable
states omit those paths and prompt the user to supply the referenced dataset files during restore.

For busy servers, tune the [work queues](ENVIRONMENT.md#work-queues) alongside
container resources. Higher concurrency requires more memory.

Viewer passwords have a server-wide budget:
at most two password checks at once and 30 admitted attempts per rolling minute by default.
Excess attempts receive HTTP 429 with a `Retry-After` hint instead of waiting for a worker.
Successful password checks also count toward this budget. Existing sessions and QR logins
do not spend it. The three `COPYLOT_VIEWER_PASSWORD_*` settings in
[Environment variables](ENVIRONMENT.md#deployment-and-access) tune these limits.

The per-client login limiter trusts forwarded addresses only from the reverse-proxy peers
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

## Distributing executable releases

CoPYlot is distributed under GPL-3.0-only. Build from a clean, reviewed Git
checkout. The Windows and macOS builders collect the actual dependency licences,
the CPython licence, native-library notices and the frontend licence file. They
stop if required notices are missing, and produce a `*-release.zip` alongside
the executable. Distribute that ZIP, not just the executable: it also contains
the matching application source, build scripts, dependency versions and licence
texts. Source and executable checksums are recorded in `release-manifest.json`.
The source archive contains only committed files, never ignored `local/` content.

For reproduction, extract `CoPYlot-source.zip`, follow these installation
instructions and use the release's `build-requirements.txt` for the Python
environment. Preserve the dependency notices when repackaging. Review the native
libraries in each newly built platform artifact; automatic collection cannot
establish rights to privately supplied code or data. Existing executables must
be rebuilt before distribution under this release process.

## Local servers with the OpenAI-compatible API (llama.cpp, vLLM, LM Studio)

Many local model servers speak only the OpenAI-compatible API (`/v1/models`,
`/v1/chat/completions`) and not Ollama's (`/api/tags`, `/api/chat`); entering
such a server as an Ollama endpoint fails. Choose **Local server
(OpenAI-compatible)** in the AI settings instead:

1. Check the server from the machine running CoPYlot: `GET http://HOST:PORT/v1/models`
   lists its models.
2. On a deployment, or when using a server-stored API key, allow the endpoint on
   the CoPYlot server: `COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS=http://HOST:PORT`,
   or preset it with `COPYLOT_LOCAL_AI_URL=http://HOST:PORT/v1` (which also pre-fills it).
3. In the AI settings enter `http://HOST:PORT/v1` and pick the model the server lists.
   Enter an API key only if the server requires one (or set `COPYLOT_LOCAL_AI_API_KEY`).

Such a server is treated like Ollama: it receives the full analysis context and no
cloud consent is asked. On a desktop run the user is the operator; a deployment only
reaches the addresses its operator allowed, so visitors cannot send its data elsewhere. Its context
size is fixed when it starts (`llama-server -c 16384`, for example); CoPYlot reads it
from llama.cpp's `/props` and otherwise uses `COPYLOT_LOCAL_AI_CONTEXT_TOKENS`.
Manage model installation and GPU settings on the model server itself.

### Assistant levels

CoPYlot automatically selects Basic, Standard or Advanced to adapt the assistant
to the model. Basic and Standard use more constrained steps and answers;
Advanced allows more flexible explanations and combined visual changes.
Override the choice with **Assistant level** in AI settings, or set defaults
with `COPYLOT_AI_MODEL_LEVELS`.

The assistant can explain results, navigate views and adjust plot appearance.
It cannot change filtering, normalization, imputation, transformation or the
phosphosite localization cutoff. Changing a plot's data source requires your
approval. Review scientific interpretations regardless of the selected level.


Python 3.10 is no longer supported: Pillow 13 security fixes require Python 3.11 or newer. The locked deployment reference remains Python 3.13.
