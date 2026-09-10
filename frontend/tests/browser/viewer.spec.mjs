import { test, expect } from '@playwright/test';
import { verifyAuthStartup } from './authStartup.mjs';

test('viewer startup waits for logout before checking authentication', async ({ page }) => {
  await verifyAuthStartup(page, '/api/viewer/auth');
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-test-only');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Viewer mode is read-only.', { exact: false })).toBeVisible();
});

test('authenticated viewer is read-only', async ({ page, browser }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Open Viewer', exact: true })).toBeVisible();
  expect((await page.request.get('/api/datasets/current')).status()).toBe(401);
  await page.getByLabel('Password', { exact: true }).fill('wrong-test-password');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Invalid viewer password.', { exact: true })).toBeVisible();
  expect((await page.request.get('/api/annotations/current/protein')).status()).toBe(401);
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-test-only');
  await page.getByRole('button', { name: 'Open Viewer', exact: true }).click();
  await expect(page.getByText('Viewer mode is read-only.', { exact: false })).toBeVisible();
  const before = await page.request.get('/api/annotations/current/protein');
  expect(before.ok()).toBeTruthy();
  const annotation = await before.json();
  expect(annotation.filteredRows).toBe(12);
  for (const name of ['Imputation', 'Restore', 'Show Dataset Manager']) {
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0);
  }
  await expect(page.locator('main input[type=file]')).toHaveCount(0);
  await expect(page.locator('main').getByRole('button', { name: 'Upload', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'KSEA', exact: true })).toHaveCount(0);
  // Bypass UI visibility with real HTTP writes: the server must enforce read-only.
  for (const [path, data] of [
    ['/api/annotations/generate', { kind: 'protein' }],
    ['/api/data-tools/imputation/run', { kind: 'protein' }],
    ['/api/datasets/packages/create', { packageName: 'Forbidden' }],
    ['/api/annotations/phosprot/aggregate', { source: 'non_imputed', mode: 'mean' }],
  ]) {
    const response = await page.request.post(path, { data });
    expect(response.status(), `${path}: ${await response.text()}`).toBe(403);
  }
  const upload = await page.request.post('/api/datasets/upload', { multipart: {
    kind: 'protein', file: { name: 'forbidden.csv', mimeType: 'text/csv', buffer: Buffer.from('ProteinNames,A1\nNO,1') },
  } });
  expect(upload.status()).toBe(403);
  expect(await (await page.request.get('/api/annotations/current/protein')).json()).toEqual(annotation);
  await page.getByRole('button', { name: 'Statistical Analysis', exact: true }).click();
  await page.locator('label').filter({ hasText: /^Condition 2$/ }).locator('..').locator('select').selectOption('B');
  await expect(page.getByText('Result Table', { exact: true })).toBeVisible();
  const isolated = await browser.newContext();
  try {
    expect((await isolated.request.get('http://127.0.0.1:5188/api/datasets/current')).status()).toBe(401);
  } finally { await isolated.close(); }
  const logout = await page.request.post('/api/viewer/auth/logout');
  expect(logout.ok()).toBeTruthy();
  expect((await page.request.get('/api/datasets/current')).status()).toBe(401);
});
