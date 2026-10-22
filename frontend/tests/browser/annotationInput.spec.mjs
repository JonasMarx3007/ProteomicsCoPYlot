import { test, expect } from '@playwright/test';
import { tabRequest } from './authStartup.mjs';

async function openMapping(page, waitForStored = true) {
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('protein');
  await page.locator('input[type=file]').setInputFiles({
    name: 'scale-fixture.csv', mimeType: 'text/csv',
    buffer: Buffer.from('ProteinNames,GeneNames,A1,A2\nP1,G1,10,12\nP2,G2,11,13\n'),
  });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload'));
  await page.getByRole('button', { name: 'Upload', exact: true }).last().click();
  expect((await uploaded).ok()).toBeTruthy();
  const stored = waitForStored
    ? page.waitForResponse(r => r.url().endsWith('/api/annotations/current/protein'))
    : page.waitForRequest(r => r.url().endsWith('/api/annotations/current/protein'));
  await page.getByRole('button', { name: 'Annotation', exact: true }).click();
  await stored;
  await page.getByLabel('Condition name', { exact: true }).fill('A');
}

test('a late missing stored annotation does not reset a newer scale detection', async ({ page }) => {
  const pending = [];
  await page.route('**/api/annotations/current/protein', route => { pending.push(route); });
  await page.route('**/api/annotations/log2-detect', route => route.fulfill({ json: { isLog2Transformed: false } }));
  await openMapping(page, false);
  await page.getByLabel('Sample columns', { exact: true }).selectOption(['A1', 'A2']);
  await expect(page.getByLabel('Dataset is already log2 transformed')).not.toBeChecked();
  for (const route of pending) await route.fulfill({ status: 404, json: { detail: 'No annotation' } });
  const generated = page.waitForResponse(r => r.url().endsWith('/api/annotations/generate'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  expect((await generated).request().postDataJSON().isLog2Transformed).toBe(false);
});

test('manual scale survives mapping edits and an in-flight detection', async ({ page }) => {
  await openMapping(page);
  let pending;
  await page.route('**/api/annotations/log2-detect', route => { pending = route; });
  await page.getByLabel('Sample columns', { exact: true }).selectOption(['A1']);
  await expect.poll(() => Boolean(pending)).toBe(true);
  const scale = page.getByLabel('Dataset is already log2 transformed');
  await scale.uncheck();
  const completed = page.waitForResponse(r => r.url().endsWith('/api/annotations/log2-detect'));
  await pending.fulfill({ json: { isLog2Transformed: true } });
  await completed;
  await page.getByLabel('Sample columns', { exact: true }).selectOption(['A1', 'A2']);
  await expect(scale).not.toBeChecked();
  // Wait for the response, not just the request: the backend stores are
  // process-global, and a generation still running when the next test
  // uploads its dataset races with that upload.
  const generated = page.waitForResponse(r => r.url().endsWith('/api/annotations/generate'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  expect((await generated).request().postDataJSON().isLog2Transformed).toBe(false);
});

test('a superseded automatic detection cannot overwrite the latest selection', async ({ page }) => {
  await openMapping(page);
  const pending = [];
  await page.route('**/api/annotations/log2-detect', route => { pending.push(route); });
  const samples = page.getByLabel('Sample columns', { exact: true });
  await samples.selectOption(['A1']);
  await expect.poll(() => pending.length).toBe(1);
  await samples.selectOption(['A1', 'A2']);
  await expect.poll(() => pending.length).toBe(2);
  await pending[1].fulfill({ json: { isLog2Transformed: false } });
  const scale = page.getByLabel('Dataset is already log2 transformed');
  await expect(scale).not.toBeChecked();
  const completed = page.waitForResponse(r => r.url().endsWith('/api/annotations/log2-detect'));
  await pending[0].fulfill({ json: { isLog2Transformed: true } });
  await completed;
  // Wait for the response, not just the request: the backend stores are
  // process-global, and a generation still running when the next test
  // uploads its dataset races with that upload.
  const generated = page.waitForResponse(r => r.url().endsWith('/api/annotations/generate'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  expect((await generated).request().postDataJSON().isLog2Transformed).toBe(false);
});

test('conflicting manual conditions show an error and preserve the previous annotation', async ({ page }) => {
  await openMapping(page);
  await page.getByLabel('Sample columns', { exact: true }).selectOption(['A1', 'A2']);
  await page.getByLabel('Minimum valid values', { exact: true }).fill('1');
  const generated = page.waitForResponse(r => r.url().endsWith('/api/annotations/generate'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  expect((await generated).ok()).toBeTruthy();
  const request = tabRequest(page);
  const before = await (await request.get('/api/annotations/current/protein')).json();
  await page.getByRole('button', { name: 'Add condition', exact: false }).click();
  await page.getByLabel('Condition name', { exact: true }).last().fill('B');
  await page.getByLabel('Sample columns', { exact: true }).last().selectOption(['A1']);
  const rejected = page.waitForResponse(r => r.url().endsWith('/api/annotations/generate'));
  await page.getByRole('button', { name: 'Apply filter', exact: true }).click();
  expect((await rejected).status()).toBe(400);
  await expect(page.getByText("Sample 'A1' is assigned more than once.", { exact: false })).toBeVisible();
  expect(await (await request.get('/api/annotations/current/protein')).json()).toEqual(before);
});

test('a scale hint under the log2 box flags values that look like log10', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Dataset type', { exact: true }).selectOption('protein');
  // Ten proteins around 4: plausible as log10 intensities, far below log2 ones.
  const rows = Array.from({ length: 10 }, (_, i) =>
    `P${i},G${i},${(3.6 + i * 0.07).toFixed(2)},${(3.7 + i * 0.07).toFixed(2)},${(3.65 + i * 0.07).toFixed(2)},${(3.75 + i * 0.07).toFixed(2)}`);
  await page.locator('input[type=file]').setInputFiles({
    name: 'log10-fixture.csv', mimeType: 'text/csv',
    buffer: Buffer.from(['ProteinNames,GeneNames,A1,A2,A3,A4', ...rows].join('\n') + '\n'),
  });
  const uploaded = page.waitForResponse(r => r.url().endsWith('/api/datasets/upload'));
  await page.getByRole('button', { name: 'Upload', exact: true }).last().click();
  expect((await uploaded).ok()).toBeTruthy();
  await page.getByRole('button', { name: 'Annotation', exact: true }).click();
  await page.getByLabel('Condition name', { exact: true }).fill('A');
  const detected = page.waitForResponse(r => r.url().endsWith('/api/annotations/log2-detect'));
  await page.getByLabel('Sample columns', { exact: true }).selectOption(['A1', 'A2', 'A3', 'A4']);
  await detected;
  const scale = page.getByLabel('Dataset is already log2 transformed');
  const hint = page.getByRole('note').filter({ hasText: 'These summaries cannot determine the data scale.' });
  await expect(scale).toBeChecked();
  await expect(hint).toContainText('The values have a median of 4.0');
  await expect(hint).toContainText('convert them to log2 before uploading');
  await scale.uncheck();
  await expect(hint).toHaveCount(0);
  await scale.check();
  await expect(hint).toBeVisible();
});
