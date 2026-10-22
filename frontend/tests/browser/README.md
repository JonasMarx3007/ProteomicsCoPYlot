# Browser workflow regressions

From `frontend`, run `npm ci`, `npx playwright install chromium`, then
`npm run test:browser`. Install the backend requirements first. Windows uses
`backend/.venv/Scripts/python.exe` when present; other environments use `python`.
Set `COPYLOT_TEST_PYTHON` to select a different interpreter.

The suite launches its own Vite server on loopback port 5187 and backend on
8187. It refuses to reuse running servers. Tests use one worker and independent
browser contexts; all uploads are synthetic. The backend redirects temporary
uploads/caches to a dedicated temporary directory. No production analysis or
external provider is required. CI installs Chromium and runs these tests in the
frontend job. Failure screenshots/traces go into ignored `test-results/`.

Coverage: upload, metadata, filtering, imputed/non-imputed phosphosite collapse,
original coverage preservation in CSV output, Welch request dispatch and result
display, unavailable direct phosphoprotein imputation, empty-filter errors, and
cancelled leave/confirmed reload. Save-download → fresh analysis → file-upload
restore checks full stored imputed matrices, collapse provenance, filtered tables
and restored statistical settings. A malformed restore must preserve the current
analysis exactly. Numeric round trips allow `1e-12 + 1e-12 * abs(expected)`;
identities/settings/missingness remain exact. Regenerated annotation notices are
excluded from snapshot equality. Responses come from the real API, not stubs.
The numeric comparison suite remains responsible for scientific equivalence.

Package/profile switching checks distinct conditions, filter counts and feature
IDs (including same-filename uploads). Delayed-response tests capture an actual
old-scope annotation response, switch again, then release that response unchanged
and verify that the active scope's settings and statistics remain selected.

Run `npm run test:viewer` for the separate authenticated viewer suite on loopback
ports 5188/8188. Its temporary project and PBKDF2 credential are synthetic; the
public test-only password has no use outside this test server. Project discovery,
password credentials and QR access configuration are isolated from local user
configuration. Checks cover wrong-password rejection, anonymous access denial,
hidden editing controls, server-rejected writes, permitted statistics, session
isolation and logout. CI runs this command after the analysis suite.

Save-file boundary checks simulate native-picker cancellation and verify no success
message or cleared unsaved-state warning. A real Chromium origin-private file
stream verifies aborted staged writes preserve previous bytes and successful writes
replace them; this is not a test of an OS-selected file or its permissions. Portable
save → missing-file response → replacement upload checks annotation numeric parity.
Unit tests additionally cover create/write/close/abort failures and explicit Save As.

Set `COPYLOT_TEST_BROWSER` to `firefox` or `webkit` after installing that Playwright
engine to run cross-browser checks. Windows WebKit's OPFS probe is explicitly
skipped because raw writes fail independently of the app; download/restore is tested.
Run `npx playwright test --config playwright.access.config.mjs` for tool-link login,
or set `COPYLOT_ACCESS_MODE=viewer` for QR login and two-project isolation.
These access suites are also run in CI. Actual OS save/open dialogs and permissions,
native Safari, live proxy deployment and exhaustive plot settings remain unverified.

Security regression: synthetic Kinase Library uploads contain closing-script tags and image
event handlers. The real plot must render with inert labels, preserve data markers,
support hover/zoom/SVG download, and deny parent DOM/local-storage access. All
generated-content feature frames and report-nested plots use an opaque-origin
sandbox; backend-served plot HTML also receives a sandbox CSP header. This is
containment, not a network-egress policy or exhaustive XSS proof. Analysis and viewer
artifacts use separate subdirectories so one suite cannot delete the other's traces.

Accessibility/handling: the workflow test verifies label clicks focus annotation
inputs, metadata-driven manual mapping starts collapsed, the manual opens as a
named modal and contains focus, Escape returns focus to its trigger, hidden main
navigation is absent from the accessibility tree, and the skip link focuses main
content. A 390px view checks content placement and page overflow. Desktop/narrow
screenshots stay in ignored test output for design review. These checks are not a
complete WCAG audit or a substitute for assistive-technology testing.
