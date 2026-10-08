# Environment variables

Every setting the server, the launchers and the frontend build read from the
environment. None is needed for a local desktop run; the defaults are chosen for
it. [Installation](INSTALLATION.md) explains the deployment settings in context.

Flags accept `1`, `true`, `yes` or `on` (any case) as on; anything else is off.
Sizes in `..._MB` are MiB; `..._BYTES` are bytes.

## Deployment and access

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_TOOL_ACCESS_ENABLED` | off | Puts the analysis app behind the tool password. |
| `COPYLOT_TOOL_ACCESS_FILE` | `local/tool_access.local.json`, then `tool_access.local.json` or `tool_access.json` in the root | The tool password hash and link tokens. |
| `COPYLOT_ALLOW_LOCAL_PATH_APIS` | off | With tool access on, still allow the routes that read paths on the server's disk (off by default there; always allowed without tool access). |
| `COPYLOT_VIEWER_MODE` | off | Runs the read-only viewer instead of the analysis app. |
| `COPYLOT_VIEWER_CONFIG` | `local/viewer_config.local.json`, else `viewer_config.json` | The viewer configuration file. Set by the launchers. |
| `COPYLOT_VIEWER_PROJECT` | none | The viewer project to open. Set by `--project`. |
| `COPYLOT_VIEWER_PORTAL_ENABLED` | off | Viewer portal: a password (or QR link) chooses the project. Needs `COPYLOT_VIEWER_MODE=1`. |
| `COPYLOT_VIEWER_ACCESS_FILE` | `local/viewer_access.local.json`, then the same name in the root | Portal passwords per project. |
| `COPYLOT_VIEWER_QR_ACCESS_FILE` | `local/viewer_qr_access.local.json`, then `viewer_qr_access.local.json` or `viewer_qr_access.json` in the root | Portal QR link tokens per project. |
| `COPYLOT_ALLOWED_HOSTS` | loopback names | Extra `Host` header values the server answers to, comma separated. |
| `COPYLOT_TRUSTED_PROXY_IPS` | `127.0.0.1` | Reverse proxies whose forwarded client address is trusted (addresses or CIDR ranges, comma separated). |
| `COPYLOT_CORS_ORIGINS` | none | Browser origins allowed to call the API from another origin, comma separated. Not needed when the frontend is served by the backend. |
| `COPYLOT_FRONTEND_DIST` | found by the launcher | The built frontend the backend serves. |
| `COPYLOT_RESET_ON_BROWSER_LOAD` | on (off in viewer mode) | A full page load starts a fresh session (analysis app). |
| `COPYLOT_WAIT_FOR_BACKEND_SECONDS` | `20` | Windows viewer launchers: how long to wait for the backend before starting the frontend. |

## Sessions and memory

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_SESSION_ISOLATION` | on | Each browser session has its own data. Required with any password. |
| `COPYLOT_SESSION_COOKIE_NAME` | `copylot_session_id` | Session cookie name. |
| `COPYLOT_SESSION_COOKIE_SECURE` | off | Mark the session cookie `Secure` (set it behind HTTPS). |
| `COPYLOT_SESSION_HEADER_NAME` | `X-CoPYlot-Session` | Header carrying the per-tab session. |
| `COPYLOT_SESSION_IDLE_SECONDS` | `86400` | A session unused this long is removed. |
| `COPYLOT_MAX_SESSIONS` | `128` | Above this, sessions are removed for room: empty ones first, then the stalest. |
| `COPYLOT_SERVER_MEMORY_MB` | 60 % of RAM | Budget for all sessions' data; above it, stale sessions are removed. |
| `COPYLOT_SESSION_PROTECT_SECONDS` | `1800` | A session active within this time is never removed for room. |
| `COPYLOT_NOTEBOOK_MEMORY_MB` | 25 % of RAM (1 GiB if unknown) | Memory for all notebook-export snapshots. |
| `COPYLOT_NOTEBOOK_SESSION_MEMORY_MB` | half the total | Per-session share of that memory; must not exceed the total. |
| `COPYLOT_TEMP_FILE_MAX_AGE_SECONDS` | `604800` | Managed temporary files older than this are deleted. |

## Uploads, restore files and plots

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_UPLOAD_MAX_BYTES` | 64 GiB | Upload size, checked as it arrives. |
| `COPYLOT_UPLOAD_MAX_CELLS` | 10,000,000,000 | Rows × columns of a parsed table. |
| `COPYLOT_UPLOAD_MAX_FRAME_BYTES` | 25 % of RAM, at most 128 GiB | Memory of a parsed table. |
| `COPYLOT_UPLOAD_MAX_COLUMNS` | 20,000 | Columns of a parsed table. |
| `COPYLOT_RESTORE_UPLOAD_MAX_BYTES` | 64 MiB | A session (restore) file. |
| `COPYLOT_RESTORE_EXPANDED_MAX_BYTES` | 256 MiB | A restore file after decompression. |
| `COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES` | the upload limit | One replacement data file during a restore. |
| `COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES` | twice the per-file limit | All replacement files of one restore. |
| `COPYLOT_RESTORE_REPLACEMENT_MAX_FILES` | 256 | Replacement files per restore. |
| `COPYLOT_RESTORE_MANIFEST_MAX_CHARS` | 1,000,000 | Size of a restore file's manifest. |
| `COPYLOT_RESTORE_TABLE_MAX_ROWS` / `_COLUMNS` / `_CELLS` | 5,000,000 / 50,000 / 50,000,000 | Tables embedded in a restore file. |
| `COPYLOT_PLOT_CONVERSION_MAX_BYTES` | 128 MiB | A figure converted to another download format. |

## Work queues

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_HEAVY_MAX_CONCURRENCY` | min(2, CPUs) | Heavy analyses running at once. |
| `COPYLOT_HEAVY_MAX_QUEUE` | 4 × concurrency (at least 4) | Heavy analyses waiting; 0 refuses instead of waiting. |
| `COPYLOT_HEAVY_QUEUE_TIMEOUT_SECONDS` | `20` | How long a heavy analysis waits for a slot. |
| `COPYLOT_THREAD_WORKERS` | max(16, concurrency + 8) | Worker threads for blocking work. |

## R

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_RSCRIPT`, `COPYLOT_R_BINARY`, `RSCRIPT` | `Rscript` on the `PATH` | The R used for VSN normalization (first one set wins). |

## AI assistant

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_AI_MODE` | off (on in the AI launchers) | Enables the assistant. |
| `COPYLOT_AI_ALLOWED_PROVIDERS` | all | Providers this server allows, comma separated (`ollama`, `openai_compatible`, `openai`, `anthropic`, `gemini`). The settings show only these. |
| `COPYLOT_AI_ALLOWED_MODELS` | unrestricted | `provider:model` entries, comma separated. A provider listed here may use only its listed models; others stay unrestricted. |
| `COPYLOT_AI_MODEL_LEVELS` | none | Comma-separated `model=level` entries, where level is `basic`, `standard` or `advanced`. Overrides automatic classification; the user's choice in AI settings takes priority. |
| `COPYLOT_AI_NATIVE_TOOLS` | on | Advanced models on servers that support tool calls (llama.cpp with a tool template, Ollama models with tools, OpenAI) use the assistant as native tools; off uses the JSON plan for every model. Either way the same checks apply. |
| `COPYLOT_AI_CALL_TIMEOUT` | `300` | Seconds one model reply may take (Ollama and cloud providers; at least 30). |
| `COPYLOT_DEFAULT_OPENAI_MODEL`, `COPYLOT_DEFAULT_ANTHROPIC_MODEL`, `COPYLOT_DEFAULT_GEMINI_MODEL` | built in | Default model per cloud provider. |
| `COPYLOT_OLLAMA_URL` | `http://127.0.0.1:11434/api/chat` | The default Ollama endpoint. |
| `COPYLOT_OLLAMA_ALLOWED_ENDPOINTS` | the default endpoint | Further Ollama origins a user may select, comma separated. |
| `COPYLOT_LOCAL_AI_URL` | none | A local server with the OpenAI-compatible API (llama.cpp, vLLM, LM Studio), e.g. `http://192.168.1.20:8080/v1`. Preset in the AI settings for "Local server (OpenAI-compatible)" and allowed. |
| `COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS` | none | Additional allowed server origins (`http://host:port`), comma separated. Required on deployments and desktop runs with a server-stored API key; otherwise desktop users may enter their own endpoint. |
| `COPYLOT_LOCAL_AI_API_KEY` | none | Key sent to that server, if it needs one. Wins over a key typed in the settings. Requires the destination in `COPYLOT_LOCAL_AI_URL` or `COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS`, including desktop runs. |
| `COPYLOT_LOCAL_AI_MODEL` | the server's first model | Preselected model of that server. |
| `COPYLOT_LOCAL_AI_CONTEXT_TOKENS` | read from llama.cpp's `/props`, else 8192 | Context window of that server; set it for servers that do not report it. |
| `COPYLOT_LOCAL_AI_TIMEOUT` | `300` | Seconds one reply from that server may take (at least 30). Large models that think first need over a minute. |
| `COPYLOT_LOCAL_AI_REASONING_EFFORT` | `high` for styling requests of Advanced models, otherwise the server's own | `low`, `medium` or `high` for every request, or `server` to leave the server default. Sent only to servers whose chat template supports `reasoning_effort`. |
| `COPYLOT_OLLAMA_MODEL_MANAGEMENT` | on for a local run; off with tool access, viewer or portal | Whether users may install or remove Ollama models (a server-wide change). |
| `COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT` | `1800` | Seconds for a model installation or removal (at least 30). |
| `COPYLOT_OLLAMA_GPU_DEFAULT` | on | Whether the GPU switch starts on. |
| `COPYLOT_OLLAMA_NUM_GPU` | `-1` (Ollama decides) | Layers offloaded to the GPU. |
| `COPYLOT_OLLAMA_NUM_CTX` | `8192` (at least 2048) | Context window. |
| `COPYLOT_OLLAMA_MAX_CTX` | `16384` | Upper limit for the context window. |
| `COPYLOT_OLLAMA_LARGE_MODEL_B` | `20` | Models with at least this many billion parameters count as large. |
| `COPYLOT_OLLAMA_LARGE_NUM_CTX` | `12288` | Minimum context window for large models. |
| `COPYLOT_OLLAMA_TOP_P` | `0.9` | Sampling `top_p`. |
| `COPYLOT_OLLAMA_REPEAT_PENALTY` | `1.1` | Sampling repeat penalty. |
| `COPYLOT_OLLAMA_THINK` | off | Ask reasoning models to think before answering. |
| `COPYLOT_PROVIDER_TIMEOUT_SECONDS` | `600` | Time one assistant step may take in total (planning, lookups and the answer). |
| `COPYLOT_PROVIDER_MAX_CONCURRENCY` | `4` | Provider calls running at once. |
| `COPYLOT_PROVIDER_MAX_QUEUE` | `8` | Provider calls waiting; 0 refuses instead of waiting. |
| `COPYLOT_PROVIDER_QUEUE_TIMEOUT_SECONDS` | `20` | How long a provider call waits for a slot. |
| `COPYLOT_PROVIDER_RESPONSE_MAX_BYTES` | 8 MiB | Size of one provider response. |

## Containers (docker compose)

| Variable | Default | Effect |
|---|---|---|
| `COPYLOT_CONTAINER_MEMORY_LIMIT`, `COPYLOT_CONTAINER_CPUS`, `COPYLOT_CONTAINER_TMPFS_SIZE` | `12g`, `4.0`, `2g` | Analysis service limits. |
| `COPYLOT_VIEWER_MEMORY_LIMIT`, `COPYLOT_VIEWER_CPUS`, `COPYLOT_VIEWER_TMPFS_SIZE` | `6g`, `2.0`, `1g` | Viewer service limits. |

## Windows code signing (build only)

| Variable | Effect |
|---|---|
| `COPYLOT_SIGNING_CERT_THUMBPRINT` | Certificate used to sign the executables. |
| `COPYLOT_SIGNING_CERT_MACHINE_STORE` | `1` to look in the machine certificate store. |
| `COPYLOT_SIGNTOOL_PATH` | Path to `signtool.exe`. |

## Frontend build (Vite)

Read when the frontend is built or the development server starts; the Docker
image takes them as `FRONTEND_*` build arguments.

| Variable | Default | Effect |
|---|---|---|
| `VITE_APP_MODE` | `analysis` | `viewer` builds the viewer frontend. |
| `VITE_AI_ENABLED` | off | Builds the assistant into the frontend. |
| `VITE_AI_DEFAULT_OLLAMA_ENDPOINT`, `VITE_AI_DEFAULT_OLLAMA_MODEL` | none | Preselected Ollama endpoint and model. |
| `VITE_BASE_PATH` | `/` | URL prefix the app is served under. |
| `VITE_API_BASE_URL` | empty (same origin) | Prefix for API calls. |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Development server: where API calls are proxied. |
| `VITE_RESET_ON_BROWSER_LOAD` | on (off in viewer mode) | Frontend side of `COPYLOT_RESET_ON_BROWSER_LOAD`. |

## Response headers

Not variables, but part of the same contract: `X-CoPYlot-Notice` carries a note
about a figure (URL-encoded text, shown under the plot), and
`X-CoPYlot-Notebook` / `X-CoPYlot-Notebook-Unavailable` say whether a notebook
export exists for it.
