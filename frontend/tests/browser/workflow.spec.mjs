import { test, expect, webkit } from '@playwright/test';
import { verifyAuthStartup } from './authStartup.mjs';
import { readFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';

// Real UI + real API, no API response stubs. Synthetic log2 values only.
// Native-picker cancellation is simulated explicitly in its boundary test.
const samples = ['A1', 'A2', 'A3', 'A4', 'B1', 'B2', 'B3', 'B4'];
const metadata = 'sample,condition,pair_id\n' + samples.map(s => `${s},${s[0]},${s[1]}`).join('\n');
const sites = ['UPD_seq,PTM_localization,Protein_group,Gene_group,PTM_Collapse_key,' + samples.join(','),
  ...Array.from({ length: 24 }, (_, i) => [
    `SEQ${i}S`, `S${i}`, `P${Math.floor(i / 2)}`, `G${Math.floor(i / 2)}`, `K${i}`,
    ...samples.map((_, j) => (i < 2 && j === 0) ? '' :
      (12 + i * 0.3 + j * 0.12 + ((i * j) % 3) * 0.07 + (j >= 4 ? 1.2 : 0)).toFixed(4)),
  ].join(','))].join('\n');

// Existing form labels are adjacent rather than linked to controls. Scope to
// their immediate container instead of using brittle global control indices.
const field = (page, label, tag = 'select') => page.getByLabel(label, { exact: true }).or(
  page.locator('label:not(:has(input, select, textarea))').filter({ hasText: new RegExp(`^\\s*${label}\\s*$`) }).locator('..').locator(tag));
const tab = (page, name) => page.getByRole('button', { name, exact: true });

test('tool startup waits for logout before checking authentication', async ({ page }) => {
  await verifyAuthStartup(page, '/api/tool/auth');
  await expect(page.getByRole('navigation', { name: 'Module views' }).getByRole('button', { name: 'Upload', exact: true })).toBeVisible();
});

test('accessible workflow labels, modal focus and responsive navigation', async ({ page }, info) => {
  await annotated(page);
  await expect(page.getByLabel('Dataset level', { exact: true })).toHaveValue('phospho');
  await expect(page.getByLabel('Minimum valid values', { exact: true })).toHaveValue('3');
  await page.getByText('Minimum valid values', { exact: true }).click();
  await expect(page.getByLabel('Minimum valid values', { exact: true })).toBeFocused();
  await expect(page.getByText('Manual Condition Mapping', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Condition name', { exact: true })).not.toBeVisible();
  await page.screenshot({ path: info.outputPath('annotation-desktop.png'), fullPage: true });
  await tab(page, 'Statistical Analysis').click();
  await expect(page.getByLabel('Test type', { exact: true })).toBeVisible();
  const manual = tab(page, 'Manual');
  await manual.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
  await dialog.getByRole('button', { name: 'Close', exact: true }).focus();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(manual).toBeFocused();
  await page.getByRole('button', { name: 'Close sidebar', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Analysis modules' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Skip to analysis content' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  await page.screenshot({ path: info.outputPath('statistics-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator('main').evaluate(el => el.getBoundingClientRect().left)).toBeLessThan(20);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  await page.screenshot({ path: info.outputPath('statistics-narrow.png'), fullPage: true });
});

test('HTML report preview and download preserve the generated document', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Summary').click();
  await tab(page, 'Report').click();
  const title = 'Report <check> & preserved';
  await page.getByLabel('Report Title', { exact: true }).fill(title);
  await page.getByLabel('Author', { exact: true }).fill('Author <safe>');
  const generated = page.waitForResponse(r => r.url().endsWith('/api/summary/report') && r.request().method() === 'POST', { timeout: 60000 });
  await tab(page, 'Generate HTML Report').click();
  const response = await generated;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  const preview = page.locator('iframe[title="Summary Report"]');
  await expect(preview).toHaveAttribute('srcdoc', result.html);
  await expect(preview).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
  const frame = preview.contentFrame();
  await expect(frame.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(frame.getByRole('heading', { name: /PCA Plot$/ })).toBeVisible();
  await expect.poll(() => frame.locator('img').first().evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download HTML Report', exact: true }).click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toBe(result.fileName);
  expect(await readFile(await file.path(), 'utf8')).toBe(result.html);
});

for (const section of ['QC Pipeline', 'Completeness']) {
  test(`${section} retains linked numeric controls and plot updates`, async ({ page }) => {
    await annotated(page);
    await tab(page, section).click();
    const plot = page.locator('main img').first();
    const plotReady = () => expect.poll(() => plot.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    await expect(plot).toBeVisible();
    await plotReady();
    const width = page.getByLabel('Width (cm)', { exact: true });
    await page.getByText('Width (cm)', { exact: true }).click();
    await expect(width).toBeFocused();
    await width.fill('14,5');
    await width.press('Tab');
    await expect(width).toHaveValue('14.5');
    await plotReady();
    await expect(plot).toHaveAttribute('src', /widthCm=14\.5(?:&|$)/);
    await width.fill('invalid');
    await width.press('Enter');
    await expect(width).toHaveValue('14.5');
    const dpi = page.getByLabel('DPI', { exact: true });
    await dpi.fill('10');
    await dpi.press('Tab');
    await expect(dpi).toHaveValue('72');
    await plotReady();
    await page.getByLabel('Toggle Header', { exact: true }).uncheck();
    await plotReady();
    await expect(page.getByLabel('Toggle Header', { exact: true })).not.toBeChecked();
    if (section === 'QC Pipeline') {
      await tab(page, 'Boxplot Intensity').click();
      await page.getByLabel('Type', { exact: true }).selectOption('Single');
      await expect(page.getByLabel('Type', { exact: true })).toHaveValue('Single');
      await plotReady();
    }
  });
}

test('shared plot controls preserve numeric editing, bounds, toggles and multiple selection', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Single Protein').click();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toBeVisible();
  let tableRequests = 0;
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/boxplot-table')) tableRequests++;
  });
  const plotReady = () => expect.poll(() => page.getByRole('img', { name: 'Protein Boxplot', exact: true })
    .evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
  await plotReady();
  const width = page.getByLabel('Width (cm)', { exact: true });
  await expect(width).toBeVisible();
  await width.fill('12,5');
  await width.press('Tab');
  await expect(width).toHaveValue('12.5');
  await plotReady();
  await width.fill('invalid');
  await width.press('Tab');
  await expect(width).toHaveValue('12.5');
  const dpi = page.getByLabel('DPI', { exact: true });
  await dpi.fill('10');
  await dpi.press('Enter');
  await expect(dpi).toHaveValue('72');
  await plotReady();
  expect(tableRequests).toBe(0);
  const conditions = page.getByRole('listbox', { name: /^Conditions\b/ });
  await conditions.selectOption(['A', 'B']);
  await expect(conditions).toHaveValues(['A', 'B']);
  await conditions.selectOption(['B']);
  await expect(conditions).toHaveValues(['B']);
  await expect(page.getByRole('table').getByRole('cell', { name: 'B', exact: true })).toBeVisible();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toHaveCount(0);
  await plotReady();
  const requestsBeforeLegend = tableRequests;
  const legend = page.getByLabel('Toggle Legend', { exact: true });
  await legend.uncheck();
  await expect(legend).not.toBeChecked();
  await plotReady();
  await legend.check();
  await expect(legend).toBeChecked();
  await plotReady();
  expect(tableRequests).toBe(requestsBeforeLegend);
  await expect(page.getByRole('link', { name: 'Download Plot', exact: true })).toHaveAttribute('href', /conditions=B&/);
  await expect(page.getByRole('table').getByRole('cell', { name: 'B', exact: true })).toBeVisible();
  await expect(page.getByRole('table').getByRole('cell', { name: 'A', exact: true })).toHaveCount(0);
});

test('uploaded hostile kinase labels stay inert and interactive plots cannot access the app', async ({ page }) => {
  const attack = "</script><script>window.injected=1</script><img src=x onerror='window.injected=2'>";
  const table = `Kinase,Log2(Frequency Factor),Adjusted p-value\n${attack},2,0.01\nAKT1,-2,0.02\n`;
  await annotated(page);
  await tab(page, 'Phospho-specific').click();
  await tab(page, 'KSEA').click();
  await page.getByRole('combobox', { name: 'Condition 1', exact: true }).selectOption('A');
  await page.getByRole('combobox', { name: 'Condition 2', exact: true }).selectOption('B');
  for (const label of ['Serine/Threonine Result File', 'Tyrosine/Non-canonical Result File']) {
    await page.getByLabel(label).setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv', buffer: Buffer.from(table) });
  }
  await page.getByLabel('Annotate Hits', { exact: true }).check();
  const rendered = page.waitForResponse(r => r.url().endsWith('/api/plots/phospho/ksea-volcano.html'));
  await tab(page, 'Generate KSEA Volcano').click();
  const response = await rendered;
  expect(response.ok(), await response.text()).toBeTruthy();
  expect(response.headers()['content-security-policy']).toContain('sandbox allow-scripts allow-downloads');
  expect(response.headers()['content-security-policy']).toContain("connect-src 'none'");
  const iframe = page.locator('iframe[title="KSEA Volcano"]');
  await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts allow-downloads');
  const frame = iframe.contentFrame();
  await expect(frame.locator('.main-svg').first()).toBeVisible();
  const plot = frame.locator('.js-plotly-plot');
  const result = await plot.evaluate(async (element) => {
    window.Plotly.Fx.hover(element, [{ curveNumber: 0, pointNumber: 0 }]);
    await window.Plotly.relayout(element, { 'xaxis.range': [-5, 5] });
    let parentBlocked = false;
    let storageBlocked = false;
    try { void parent.document.body; } catch { parentBlocked = true; }
    try { void localStorage.length; } catch { storageBlocked = true; }
    return { parentBlocked, storageBlocked, injected: window.injected ?? null,
      range: element.layout.xaxis.range, points: element.calcdata.reduce((n, trace, index) =>
        n + (element._fullData[index].mode === 'markers' ? trace.length : 0), 0) };
  });
  expect(result).toEqual({ parentBlocked: true, storageBlocked: true, injected: null, range: [-5, 5], points: 4 });
  await expect(frame.locator('[onerror], img[src=x]')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected ?? null)).toBeNull();
  const download = page.waitForEvent('download');
  await plot.evaluate(element => window.Plotly.downloadImage(element, { format: 'svg', filename: 'security-regression' }));
  expect((await download).suggestedFilename()).toBe('security-regression.svg');
});

test('real browser file stream abort preserves previous bytes and success replaces them', async ({ page, browserName, baseURL }) => {
  test.skip(browserName === 'webkit' && process.platform === 'win32',
    'Windows Playwright WebKit OPFS returns empty files even for raw writes; real download/restore is tested separately.');
  // WebKit private contexts reject OPFS access; use a disposable persistent profile.
  const context = browserName === 'webkit' ? await webkit.launchPersistentContext('', { baseURL }) : null;
  try {
    if (context) page = await context.newPage();
    await page.goto('/');
    const result = await page.evaluate(async () => {
      const { saveRestoreStateBlob } = await import('/src/lib/saveStateFile.ts');
      const root = await navigator.storage.getDirectory();
      const handle = await root.getFileHandle('save-regression.copylotstate', { create: true });
      try {
        await saveRestoreStateBlob({ blob: new Blob(['previous']), existingHandle: handle });
        const interruptedHandle = {
          name: handle.name,
          async createWritable() {
            const stream = await handle.createWritable();
            return {
              async write(blob) { await stream.write(blob); throw new Error('Injected write failure'); },
              close: () => stream.close(),
              abort: () => stream.abort(),
            };
          },
        };
        let error;
        try {
          await saveRestoreStateBlob({ blob: new Blob(['incomplete']), existingHandle: interruptedHandle });
        } catch (failure) { error = failure.message; }
        const afterFailure = await (await handle.getFile()).text();
        await saveRestoreStateBlob({ blob: new Blob(['replacement']), existingHandle: handle });
        return { error, afterFailure, afterSuccess: await (await handle.getFile()).text() };
      } finally {
        await root.removeEntry('save-regression.copylotstate');
      }
    });
    expect(result).toEqual({ error: 'Injected write failure', afterFailure: 'previous', afterSuccess: 'replacement' });
  } finally { await context?.close(); }
});

test('cancelled native save and open dialogs never report success or clear unsaved state', async ({ page }) => {
  await page.addInitScript(() => {
    window.showSaveFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
    window.showOpenFilePicker = async () => { throw new DOMException('Cancelled', 'AbortError'); };
  });
  await annotated(page);
  const before = await (await page.request.get('/api/annotations/current/phospho')).json();
  await tab(page, 'Restore').click();
  for (const name of ['Save State...', 'Save State As...', 'Save Portable State...']) {
    await tab(page, name).click();
    await expect(tab(page, name)).toBeEnabled();
    await expect(page.getByText(/Save state written|Portable save state written|Current save target:/)).toHaveCount(0);
  }
  await tab(page, 'Open Save File...').click();
  await expect(tab(page, 'Open Save File...')).toBeEnabled();
  await expect(tab(page, 'Restore').last()).toBeDisabled();
  expect(await (await page.request.get('/api/annotations/current/phospho')).json()).toEqual(before);
  const leaving = page.waitForEvent('dialog');
  await page.close({ runBeforeUnload: true });
  const warning = await leaving;
  expect(warning.type()).toBe('beforeunload');
  await warning.dismiss();
  expect(page.isClosed()).toBe(false);
  await expect(tab(page, 'Save State...')).toBeVisible();
});

test('portable save restores through required replacement upload without changing numeric data', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'showSaveFilePicker', { value: undefined, configurable: true });
    Object.defineProperty(window, 'showOpenFilePicker', { value: undefined, configurable: true });
  });
  await annotated(page);
  const expected = await (await page.request.get('/api/annotations/current/phospho')).json();
  await tab(page, 'Restore').click();
  const downloaded = page.waitForEvent('download');
  page.once('dialog', dialog => dialog.accept());
  await tab(page, 'Save Portable State...').click();
  const download = await downloaded;
  const bytes = await readFile(await download.path());
  const payload = JSON.parse(gunzipSync(bytes).toString('utf8'));
  expect(payload.portable).toBe(true);
  for (const pkg of payload.backend.packages) {
    for (const dataset of Object.values(pkg.datasets).filter(Boolean)) expect(dataset.path).toBeNull();
  }
  await expect(page.getByText('Portable save state written without local dataset paths.', { exact: true })).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  await tab(page, 'Restore').click();
  await page.locator('input[type=file]').setInputFiles({ name: 'portable.copylotstate', mimeType: 'application/octet-stream', buffer: bytes });
  const missingResponse = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const missing = await missingResponse;
  expect(missing.status()).toBe(409);
  const missingBody = await missing.json();
  expect(missingBody.ok).toBe(false);
  expect(missingBody.missingFiles).toHaveLength(1);
  expect((await page.request.get('/api/annotations/current/phospho')).status()).toBe(404);
  await expect(tab(page, 'Restore').last()).toBeDisabled();
  const replacements = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Missing Files' }) });
  await replacements.locator('input[type=file]').setInputFiles({ name: 'synthetic-sites.csv', mimeType: 'text/csv', buffer: Buffer.from(sites) });
  const restored = await actionResponse(page, '/api/restore/import', () => tab(page, 'Restore').last().click());
  expect(restored.body.ok).toBe(true);
  await expect(page.getByText(/Restore complete\./)).toBeVisible();
  const actual = await (await page.request.get('/api/annotations/current/phospho')).json();
  delete actual.warnings;
  delete expected.warnings;
  expectRoundTrip(actual, expected);
});
async function actionResponse(page, path, action) {
  const pending = page.waitForResponse(r => new URL(r.url()).pathname === path && r.request().method() === 'POST');
  await action();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const request = response.request();
  const sent = request.headers()['content-type']?.includes('application/json') ? request.postDataJSON() : undefined;
  return { body: await response.json(), sent };
}

async function annotated(page, minimum = '3', { fresh = true, table = sites, meta = metadata } = {}) {
  if (fresh) await page.goto('/');
  await field(page, 'Dataset type').selectOption('phospho');
  await page.locator('input[type=file]').setInputFiles({ name: 'synthetic-sites.csv', mimeType: 'text/csv', buffer: Buffer.from(table) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload').last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await tab(page, 'Annotation').click();
  await field(page, 'Dataset level').selectOption('phospho');
  await field(page, 'Metadata file', 'input').setInputFiles({ name: 'synthetic-meta.csv', mimeType: 'text/csv', buffer: Buffer.from(meta) });
  const metadataResponse = page.waitForResponse(r => r.url().endsWith('/api/annotations/metadata/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload Metadata').click();
  expect((await metadataResponse).ok()).toBeTruthy();
  await page.getByLabel('Dataset is already log2 transformed').check();
  await field(page, 'Minimum valid values', 'input').fill(minimum);
  await field(page, 'Normalization').selectOption('none');
  const result = await actionResponse(page, '/api/annotations/generate', () => tab(page, 'Generate Annotation').click());
  expect(result.sent.kind).toBe('phospho');
  expect(result.sent.filter.minPresent).toBe(Number(minimum));
  expect(result.sent.isLog2Transformed).toBe(true);
  expect(result.body.filteredRows).toBe(minimum === '3' ? 24 : minimum === '4' ? 22 : 0);
  return result;
}

for (const source of ['non_imputed', 'imputed']) {
  test(`phosphosite upload to collapse and statistics: ${source}`, async ({ page }) => {
    await annotated(page);
    if (source === 'imputed') {
      await tab(page, 'Imputation').click();
      await expect(field(page, 'Dataset level')).toHaveValue('phospho');
      const result = await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
      expect(result.sent.kind).toBe('phospho');
      await tab(page, 'Annotation').click();
    }
    await field(page, 'Source data').selectOption(source);
    const aggregate = await actionResponse(page, '/api/annotations/phosprot/aggregate', () => tab(page, 'Aggregate to Phosphoprotein').click());
    expect(aggregate.sent).toMatchObject({ source, mode: 'robust_site_median' });
    // Download the actual result: the imputed path must preserve a value at A1
    // without inflating its original observation count.
    const csv = await page.request.get('/api/annotations/current/phosprot/source/download');
    expect(csv.ok()).toBeTruthy();
    const lines = (await csv.text()).trim().split(/\r?\n/).map(line => line.split(','));
    const headers = lines[0];
    const row = lines.slice(1).find(values => values[headers.indexOf('Phosphoprotein')] === 'P0');
    expect(row).toBeTruthy();
    expect(Number(row[headers.indexOf('site_observed__A1')])).toBe(0);
    expect(row[headers.indexOf('A1')] === '').toBe(source === 'non_imputed');
    await tab(page, 'Imputation').click();
    await expect(field(page, 'Dataset level').locator('option[value=phosprot]')).toHaveCount(0);
    await expect(page.getByText('Phosphoproteins cannot be imputed directly.', { exact: false })).toBeVisible();
    const statsResponse = page.waitForResponse(r => {
      if (!r.url().endsWith('/api/stats/volcano/run')) return false;
      const payload = r.request().postDataJSON();
      return payload?.kind === 'phosprot' && payload.testType === 'unpaired_welch';
    });
    await tab(page, 'Statistical Analysis').click();
    await field(page, 'Dataset level').selectOption('phosprot');
    await field(page, 'Condition 1').selectOption('A');
    await field(page, 'Condition 2').selectOption('B');
    await field(page, 'Test type').selectOption('unpaired_welch');
    const response = await statsResponse;
    expect(response.ok(), await response.text()).toBeTruthy();
    expect((await response.json()).totalRows).toBe(12);
    expect(response.request().postDataJSON()).toMatchObject({ condition1: 'A', condition2: 'B', dataSource: 'data' });
    await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  });
}

test('empty filtering stays empty and aggregation displays the API rejection', async ({ page }) => {
  await annotated(page, '5');
  const pending = page.waitForResponse(r => r.url().endsWith('/api/annotations/phosprot/aggregate') && r.request().method() === 'POST');
  await tab(page, 'Aggregate to Phosphoprotein').click();
  expect((await pending).status()).toBe(400);
  await expect(page.getByText(/No features passed/)).toBeVisible();
});

test('cancelled leave preserves analysis; confirmed reload starts a new one', async ({ page }) => {
  await annotated(page);
  const dialogEvent = page.waitForEvent('dialog');
  await page.close({ runBeforeUnload: true });
  const dialog = await dialogEvent;
  expect(dialog.type()).toBe('beforeunload');
  await dialog.dismiss();
  expect(page.isClosed()).toBe(false);
  await expect(tab(page, 'Generate Annotation')).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Dataset level')).toBeDisabled();
});

async function analysisSnapshot(page) {
  const snapshot = {};
  // Read-only export also exposes the full stored imputed matrix and collapse
  // provenance, which the annotation-preview endpoint does not return.
  const exported = await page.request.post('/api/restore/export', { data: { uiState: {} } });
  expect(exported.ok()).toBeTruthy();
  const state = JSON.parse(gunzipSync(await exported.body()).toString('utf8'));
  snapshot.storedAnnotations = state.backend.packages.flatMap(pkg => pkg.annotations.map(annotation => ({
    kind: annotation.kind, imputedFrame: annotation.imputedFrame,
    phosprotAggregation: annotation.phosprotAggregation,
  })));
  for (const kind of ['phospho', 'phosprot']) {
    const annotation = await page.request.get(`/api/annotations/current/${kind}`);
    expect(annotation.ok()).toBeTruthy();
    snapshot[kind] = await annotation.json();
    // Restore recomputes annotation notices (e.g. "using uploaded metadata")
    // instead of persisting the last operation's prose. Compare analysis state.
    delete snapshot[kind].warnings;
    const csv = await page.request.get(`/api/annotations/current/${kind}/filtered/download`);
    expect(csv.ok()).toBeTruthy();
    // This synthetic fixture has no quoted delimiters. Keep headers, identities
    // and empty cells exact; parse numeric cells for round-trip tolerance.
    snapshot[`${kind}Csv`] = (await csv.text()).trim().split(/\r?\n/).map(line =>
      line.split(',').map(cell => cell !== '' && Number.isFinite(Number(cell)) ? Number(cell) : cell));
  }
  return snapshot;
}

function expectRoundTrip(actual, expected) {
  if (typeof expected === 'number') {
    expect(typeof actual).toBe('number');
    expect(Math.abs(actual - expected)).toBeLessThanOrEqual(1e-12 + 1e-12 * Math.abs(expected));
  } else if (expected !== null && typeof expected === 'object') {
    expect(actual).not.toBeNull();
    expect(Array.isArray(actual)).toBe(Array.isArray(expected));
    expect(Object.keys(actual).sort()).toEqual(Object.keys(expected).sort());
    for (const key of Object.keys(expected)) expectRoundTrip(actual[key], expected[key]);
  } else {
    expect(actual).toEqual(expected);
  }
}

const alternateMetadata = metadata.replace(/,A,/g, ',X,').replace(/,B,/g, ',Y,');

async function showManager(page, name) {
  const show = tab(page, `Show ${name} Manager`);
  if (await show.count()) await show.click();
}

async function verifyScopeStatistics(page, first, second, rows) {
  const pending = page.waitForResponse(r => {
    if (!r.url().endsWith('/api/stats/volcano/run')) return false;
    const p = r.request().postDataJSON();
    return p?.condition1 === second && p.condition2 === first && p.testType === 'unpaired_welch';
  });
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Dataset level')).toHaveValue('phospho');
  await expect(field(page, 'Condition 1').locator('option')).toHaveText([first, second]);
  await field(page, 'Condition 1').selectOption(second);
  await field(page, 'Condition 2').selectOption(first);
  await field(page, 'Test type').selectOption('unpaired_welch');
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  expect(result.totalRows).toBe(rows);
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  await tab(page, 'Data').click();
  return result;
}

async function holdNextResponse(page, path) {
  let release;
  let captured;
  const gate = new Promise(resolve => { release = resolve; });
  const ready = new Promise(resolve => { captured = resolve; });
  let held = false;
  await page.route(`**${path}`, async route => {
    if (held) return route.continue();
    const response = await route.fetch(); // Real old-scope response, unchanged.
    const payload = await response.json();
    // A background request from the current profile may arrive first. Hold
    // only the distinguishable old-profile response this scenario targets.
    if (held || payload.filter?.minPresent !== 3) return route.fulfill({ response });
    held = true;
    captured(payload);
    await gate;
    await route.fulfill({ response });
  });
  return { ready, async release() {
    const received = page.waitForResponse(r => new URL(r.url()).pathname === path);
    release();
    await received;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.unroute(`**${path}`);
  } };
}

test('package switching keeps same-filename datasets and statistics separate', async ({ page }) => {
  await annotated(page);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  const originalPackage = await field(page, 'Selected dataset').inputValue();
  await field(page, 'New dataset', 'input').fill('Second');
  await actionResponse(page, '/api/datasets/packages/create', () => tab(page, 'Create').click());
  // Deliberately reuse filenames: scope cannot be inferred from filename alone.
  await annotated(page, '4', { fresh: false, meta: alternateMetadata,
    table: sites.replace(/SEQ/g, 'ALTSEQ').replace(/,K(\d+)/g, ',ALT$1') });
  const second = await verifyScopeStatistics(page, 'X', 'Y', 22);
  expect(second.rows.every(row => String(row.PTM_Collapse_key).startsWith('ALT'))).toBe(true);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  await field(page, 'Selected dataset').selectOption(originalPackage);
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  const first = await verifyScopeStatistics(page, 'A', 'B', 24);
  expect(first.rows.every(row => String(row.PTM_Collapse_key).startsWith('K'))).toBe(true);
  await tab(page, 'Upload').click();
  await showManager(page, 'Dataset');
  await field(page, 'Selected dataset').selectOption('Second');
  await tab(page, 'Annotation').click();
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  const delayed = await holdNextResponse(page, '/api/annotations/current/phospho');
  try {
    await tab(page, 'Upload').click();
    await showManager(page, 'Dataset');
    await field(page, 'Selected dataset').selectOption(originalPackage);
    await tab(page, 'Annotation').click();
    expect((await delayed.ready).filter.minPresent).toBe(3);
    await tab(page, 'Upload').click();
    await showManager(page, 'Dataset');
    await field(page, 'Selected dataset').selectOption('Second');
    await tab(page, 'Annotation').click();
    await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  } finally {
    await delayed.release();
  }
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  await verifyScopeStatistics(page, 'X', 'Y', 22);
});

test('metadata switching ignores a delayed previous-profile annotation', async ({ page }) => {
  await annotated(page);
  await showManager(page, 'Annotation');
  const originalProfile = await field(page, 'Selected metadata').inputValue();
  await field(page, 'New metadata profile', 'input').fill('Alternative');
  await actionResponse(page, '/api/datasets/metadata/profiles/create', () => tab(page, 'Create').click());
  await expect(field(page, 'Selected metadata')).toHaveValue('Alternative');
  await expect(field(page, 'Selected metadata')).toBeEnabled();
  await field(page, 'Metadata file', 'input').setInputFiles({ name: 'alternate.csv', mimeType: 'text/csv', buffer: Buffer.from(alternateMetadata) });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/annotations/metadata/upload') && r.request().method() === 'POST');
  await tab(page, 'Upload Metadata').click();
  expect((await uploaded).ok()).toBeTruthy();
  await field(page, 'Minimum valid values', 'input').fill('4');
  await actionResponse(page, '/api/annotations/generate', () => tab(page, 'Generate Annotation').click());
  const alternativeProfile = await field(page, 'Selected metadata').inputValue();
  expect(alternativeProfile).not.toBe(originalProfile);
  await verifyScopeStatistics(page, 'X', 'Y', 22);
  await tab(page, 'Annotation').click();
  await showManager(page, 'Annotation');
  const delayed = await holdNextResponse(page, '/api/annotations/current/phospho');
  try {
    await field(page, 'Selected metadata').selectOption(originalProfile);
    expect((await delayed.ready).filter.minPresent).toBe(3);
    // Switch again while the old annotation is still in flight.
    await field(page, 'Selected metadata').selectOption(alternativeProfile);
    await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  } finally {
    await delayed.release();
  }
  await expect(field(page, 'Selected metadata')).toHaveValue(alternativeProfile);
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('4');
  await verifyScopeStatistics(page, 'X', 'Y', 22);
  await tab(page, 'Annotation').click();
  await showManager(page, 'Annotation');
  await field(page, 'Selected metadata').selectOption(originalProfile);
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  await verifyScopeStatistics(page, 'A', 'B', 24);
});

test('save download and UI restore preserve analysis and settings; invalid restore is non-destructive', async ({ page }) => {
  // Exercise the supported browser download/upload path, not an OS picker stub.
  await page.addInitScript(() => {
    Object.defineProperty(window, 'showSaveFilePicker', { value: undefined, configurable: true });
    Object.defineProperty(window, 'showOpenFilePicker', { value: undefined, configurable: true });
  });
  await annotated(page);
  await tab(page, 'Imputation').click();
  await actionResponse(page, '/api/data-tools/imputation/run', () => tab(page, 'Impute Data Values').click());
  await tab(page, 'Annotation').click();
  await field(page, 'Source data').selectOption('imputed');
  await field(page, 'Aggregation mode').selectOption('mean');
  await actionResponse(page, '/api/annotations/phosprot/aggregate', () => tab(page, 'Aggregate to Phosphoprotein').click());
  await tab(page, 'Statistical Analysis').click();
  await field(page, 'Dataset level').selectOption('phosprot');
  await field(page, 'Condition 1').selectOption('B');
  await field(page, 'Condition 2').selectOption('A');
  const matchesSettings = r => {
    if (!r.url().endsWith('/api/stats/volcano/run')) return false;
    const p = r.request().postDataJSON();
    return p?.kind === 'phosprot' && p.testType === 'unpaired_welch' && p.condition1 === 'B' && p.condition2 === 'A';
  };
  const originalStats = page.waitForResponse(matchesSettings);
  await field(page, 'Test type').selectOption('unpaired_welch');
  const originalResponse = await originalStats;
  expect(originalResponse.ok()).toBeTruthy();
  const expectedStats = await originalResponse.json();
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  const expected = await analysisSnapshot(page);
  await tab(page, 'Data').click();
  await tab(page, 'Restore').click();
  const downloaded = page.waitForEvent('download');
  const confirmation = page.waitForEvent('dialog');
  await tab(page, 'Save State As...').click();
  const dialog = await confirmation;
  expect(dialog.type()).toBe('confirm');
  expect(dialog.message()).toContain('finished downloading');
  await dialog.accept();
  const download = await downloaded;
  const bytes = await readFile(await download.path());
  await expect(page.getByText('Save state written to the selected file.', { exact: true })).toBeVisible();
  expect(bytes.length).toBeGreaterThan(100);

  // A fresh load must actually empty the backend before import is attempted.
  page.once('dialog', dialog => dialog.accept());
  await page.reload();
  await expect(field(page, 'Dataset type')).toBeVisible();
  expect((await page.request.get('/api/annotations/current/phosprot')).status()).toBe(404);
  await tab(page, 'Restore').click();
  await page.locator('input[type=file]').setInputFiles({ name: download.suggestedFilename(), mimeType: 'application/octet-stream', buffer: bytes });
  const imported = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const restore = await imported;
  expect(restore.ok(), await restore.text()).toBeTruthy();
  expect((await restore.json()).ok).toBe(true);
  await expect(page.getByText(/Restore complete\./)).toBeVisible();
  expectRoundTrip(await analysisSnapshot(page), expected);

  const restoredStats = page.waitForResponse(matchesSettings);
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Dataset level')).toHaveValue('phosprot');
  await expect(field(page, 'Condition 1')).toHaveValue('B');
  await expect(field(page, 'Condition 2')).toHaveValue('A');
  await expect(field(page, 'Test type')).toHaveValue('unpaired_welch');
  expectRoundTrip(await (await restoredStats).json(), expectedStats);
  await tab(page, 'Data').click();
  await tab(page, 'Annotation').click();
  await field(page, 'Dataset level').selectOption('phospho');
  await expect(field(page, 'Minimum valid values', 'input')).toHaveValue('3');
  await expect(field(page, 'Normalization')).toHaveValue('none');
  await expect(field(page, 'Source data').locator('option[value=imputed]')).toHaveCount(1);

  await tab(page, 'Restore').click();
  const beforeRejectedRestore = await analysisSnapshot(page);
  await page.locator('input[type=file]').setInputFiles({ name: 'broken.copylotstate', mimeType: 'application/octet-stream', buffer: Buffer.from('not a save state') });
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/restore/import'));
  await tab(page, 'Restore').last().click();
  const rejection = await rejected;
  expect(rejection.status()).toBe(400);
  const error = await rejection.json();
  await expect(page.getByText(error.detail, { exact: true })).toBeVisible();
  expect(await analysisSnapshot(page)).toEqual(beforeRejectedRestore);
  await tab(page, 'Statistical Analysis').click();
  await expect(field(page, 'Test type')).toHaveValue('unpaired_welch');
  await expect(field(page, 'Condition 1')).toHaveValue('B');
});
