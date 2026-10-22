import { test, expect } from '@playwright/test';
import { verifyAuthStartup, tabRequest } from './authStartup.mjs';

test('viewer startup waits for logout before checking authentication', async ({ page }) => {
  await verifyAuthStartup(page, '/api/viewer/auth');
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-test-only');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Viewer mode is read-only.', { exact: false })).toBeVisible();
});

test('viewer tabs keep independent projects, plots and downloads across refresh', async ({ page, context, browser }) => {
  async function login(target, password) {
    await target.getByLabel('Password', { exact: true }).fill(password);
    await target.getByRole('button', { name: 'Open Viewer', exact: true }).click();
    await expect(target.getByText('Viewer mode is read-only.', { exact: false })).toBeVisible();
  }
  const rows = async target => (await (await tabRequest(target).get('/api/annotations/current/protein')).json()).filteredRows;
  await page.goto('/');
  await login(page, 'synthetic-browser-test-only');
  const tabA = await page.evaluate(() => sessionStorage.getItem('copylot.tab.id'));
  // A marker in a namespace a new tab clears but nothing else touches: the
  // report keys are reset once the dataset loads after login, which raced the test.
  await page.evaluate(() => sessionStorage.setItem('pcopylot.ui.viewerTabMarker.v1', 'tab-A-settings'));
  const opened = context.waitForEvent('page');
  await page.evaluate(() => window.open('/', '_blank'));
  const second = await opened;
  await expect(second.getByRole('button', { name: 'Open Viewer', exact: true })).toBeVisible();
  const tabB = await second.evaluate(() => sessionStorage.getItem('copylot.tab.id'));
  expect(tabB).not.toBe(tabA);
  expect(await second.evaluate(() => sessionStorage.getItem('pcopylot.ui.viewerTabMarker.v1'))).toBeNull();
  expect(await rows(page)).toBe(12);
  await login(second, 'synthetic-second-password');
  expect(await rows(second)).toBe(6);
  expect(await rows(page)).toBe(12);
  await second.evaluate(() => sessionStorage.setItem('pcopylot.ui.viewerTabMarker.v1', 'tab-B-settings'));
  expect(await page.evaluate(() => sessionStorage.getItem('pcopylot.ui.viewerTabMarker.v1'))).toBe('tab-A-settings');
  for (const [target, marker] of [[page, 'SYNTHETIC'], [second, 'SECOND']]) {
    await target.getByRole('button', { name: 'QC Pipeline', exact: true }).click();
    const plot = target.locator('main img').first();
    await expect(plot).toBeVisible();
    await expect.poll(() => plot.evaluate(image => image.complete && image.naturalWidth > 0)).toBe(true);
    const csv = await tabRequest(target).get('/api/annotations/current/protein/source/download');
    expect(csv.ok()).toBeTruthy();
    expect(await csv.text()).toContain(marker);
  }
  const isolated = await browser.newContext();
  try {
    expect((await isolated.request.get(`http://127.0.0.1:5188/api/tabs/${tabA}/api/datasets/current`)).status()).toBe(401);
  } finally { await isolated.close(); }
  await second.reload();
  await expect(second.getByRole('button', { name: 'Open Viewer', exact: true })).toBeVisible();
  expect(await second.evaluate(() => sessionStorage.getItem('copylot.tab.id'))).toBe(tabB);
  expect(await rows(page)).toBe(12);
  await login(second, 'synthetic-second-password');
  await tabRequest(second).post('/api/viewer/auth/logout');
  expect((await tabRequest(second).get('/api/datasets/current')).status()).toBe(401);
  expect(await rows(page)).toBe(12);
});

test('authenticated viewer is read-only', async ({ page, browser }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Open Viewer', exact: true })).toBeVisible();
  expect((await tabRequest(page).get('/api/datasets/current')).status()).toBe(401);
  await page.getByLabel('Password', { exact: true }).fill('wrong-test-password');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Invalid viewer password.', { exact: true })).toBeVisible();
  expect((await tabRequest(page).get('/api/annotations/current/protein')).status()).toBe(401);
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-test-only');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Viewer mode is read-only.', { exact: false })).toBeVisible();
  const before = await tabRequest(page).get('/api/annotations/current/protein');
  expect(before.ok()).toBeTruthy();
  const annotation = await before.json();
  expect(annotation.filteredRows).toBe(12);
  for (const name of ['Imputation', 'Restore', 'Show Dataset Manager']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  await expect(page.locator('main input[type=file]')).toHaveCount(0);
  await expect(page.locator('main').getByRole('button', { name: 'Upload', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Kinase Library', exact: true })).toHaveCount(0);
  // Bypass UI visibility with real HTTP writes: the server must enforce read-only.
  for (const [path, data] of [
    ['/api/annotations/generate', { kind: 'protein' }],
    ['/api/data-tools/imputation/run', { kind: 'protein' }],
    ['/api/datasets/packages/create', { packageName: 'Forbidden' }],
    ['/api/annotations/phosprot/aggregate', { source: 'non_imputed', mode: 'mean' }],
    // The whole session in one blob. Quick save is what used to call it; a
    // viewer has nothing to save and no business taking the matrices away.
    ['/api/restore/export', { uiState: {}, portable: false }],
    // Runs the same imputation as /run and returns the filled matrix as CSV.
    ['/api/data-tools/imputation/download', { kind: 'protein' }],
    // A write, and the page that offers it is not in the viewer's tab list.
    ['/api/data-tools/condition-colors/protein', { palette: { A: '#123456' } }],
  ]) {
    const response = await tabRequest(page).post(path, { data });
    expect(response.status(), `${path}: ${await response.text()}`).toBe(403);
  }
  const upload = await tabRequest(page).post('/api/datasets/upload', { multipart: {
    kind: 'protein', file: { name: 'forbidden.csv', mimeType: 'text/csv', buffer: Buffer.from('ProteinNames,A1\nNO,1') },
  } });
  expect(upload.status()).toBe(403);
  expect(await (await tabRequest(page).get('/api/annotations/current/protein')).json()).toEqual(annotation);
  const current = await (await tabRequest(page).get('/api/datasets/current')).json();
  const runtimeResponse = await tabRequest(page).get('/api/runtime/r');
  expect(runtimeResponse.ok()).toBeTruthy();
  const runtime = await runtimeResponse.json();
  expect(runtime.diagnosticsHidden).toBe(true);
  expect(runtime.executable).toBeNull();
  expect(runtime.versionOutput).toBeNull();
  expect(runtime.candidates).toEqual([]);
  for (const [path, data] of [
    ['/api/datasets/active', { packageName: current.activePackage }],
    ['/api/datasets/metadata/profiles/active', { profileName: current.activeMetadataProfile }],
    ['/api/data-tools/phospho-localization-cutoff', { cutoff: 0.75 }],
  ]) {
    const response = await tabRequest(page).post(path, { data });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  }
  expect((await (await tabRequest(page).get('/api/data-tools/phospho-localization-cutoff')).json()).cutoff).toBe(0.75);
  for (const path of ['/api/new-route', '/api/plots/new-plot.png', '/api/viewer/auth/new-action']) {
    expect((await tabRequest(page).get(path)).status()).toBe(403);
  }
  expect((await tabRequest(page).get('/api/plots/notebooks/abcdefghijklmnopqrstuvwxyz012345.zip')).status()).toBe(403);
  await page.getByRole('button', { name: 'Statistical Analysis', exact: true }).click();
  await page.locator('label').filter({ hasText: /^Condition 2$/ }).locator('..').locator('select').selectOption('B');
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  const isolated = await browser.newContext();
  try {
    expect((await isolated.request.get('http://127.0.0.1:5188/api/datasets/current')).status()).toBe(401);
  } finally { await isolated.close(); }
  const logout = await tabRequest(page).post('/api/viewer/auth/logout');
  expect(logout.ok()).toBeTruthy();
  expect((await tabRequest(page).get('/api/datasets/current')).status()).toBe(401);
});
