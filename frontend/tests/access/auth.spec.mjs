import { test, expect } from '@playwright/test';

const viewer = process.env.COPYLOT_ACCESS_MODE === 'viewer';
const authPath = viewer ? '/api/viewer/auth' : '/api/tool/auth';
const fragment = viewer ? 'qr=synthetic-browser-qr-only' : 'tool=synthetic-browser-link-only';
test('fragment login completes once and reaches the app', async ({ page }) => {
  const path = viewer ? '/api/viewer/auth/qr-login' : '/api/tool/auth/link-login';
  let calls = 0;
  page.on('request', request => { if (new URL(request.url()).pathname === path) calls++; });
  const login = page.waitForResponse(response => new URL(response.url()).pathname === path);
  await page.goto(viewer ? '/#qr=synthetic-browser-qr-only' : '/#tool=synthetic-browser-link-only');
  expect((await login).ok()).toBeTruthy();
  const outcome = async () => calls > 1 ? 'repeated-login' :
    await page.getByRole('navigation', { name: 'Analysis modules' }).isVisible() ? 'ready' : 'waiting';
  await expect.poll(outcome).not.toBe('waiting');
  expect(await outcome()).toBe('ready');
  expect(calls).toBe(1);
  expect(new URL(page.url()).hash).toBe('');
  await page.getByRole('button', { name: 'Statistical Analysis', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Analysis modules' })).toBeVisible();
  expect((await (await page.request.get(`${authPath}/status`)).json()).authenticated).toBe(true);
  expect(calls).toBe(1);
});

test('invalid fragment is consumed and Retry permits password login', async ({ page }) => {
  let calls = 0;
  page.on('request', request => { if (/\/(qr|link)-login$/.test(new URL(request.url()).pathname)) calls++; });
  await page.goto(`/#${viewer ? 'qr' : 'tool'}=invalid-synthetic-token`);
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await page.getByLabel('Password', { exact: true }).fill(viewer ? 'synthetic-browser-test-only' : 'synthetic-tool-password');
  await page.getByRole('button', { name: viewer ? 'Open Viewer' : 'Open Tool', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Analysis modules' })).toBeVisible();
  expect(new URL(page.url()).hash).toBe('');
  expect(calls).toBe(1);
});

test('Retry after a status failure does not resubmit the successful fragment', async ({ page }) => {
  let statuses = 0;
  let logins = 0;
  page.on('request', request => { if (/\/(qr|link)-login$/.test(new URL(request.url()).pathname)) logins++; });
  await page.route(`**${authPath}/status`, async route => {
    if (++statuses === 2) await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Synthetic status outage"}' });
    else await route.continue();
  });
  await page.goto(`/#${fragment}`);
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('navigation', { name: 'Analysis modules' })).toBeVisible();
  expect(statuses).toBe(3);
  expect(logins).toBe(1);
  expect(new URL(page.url()).hash).toBe('');
});

test('viewer sessions retain separate project data', async ({ browser, baseURL }) => {
  test.skip(!viewer, 'Requires viewer portal fixtures');
  const first = await browser.newContext();
  const second = await browser.newContext();
  try {
    for (const [context, password, project] of [
      [first, 'synthetic-browser-test-only', 'Synthetic'],
      [second, 'synthetic-second-password', 'Second'],
    ]) {
      const login = await context.request.post(`${baseURL}/api/viewer/auth/login`, { data: { password } });
      expect(login.ok(), await login.text()).toBeTruthy();
      const status = await context.request.get(`${baseURL}/api/viewer/auth/status`);
      expect((await status.json()).project).toBe(project);
    }
    const getAnnotation = async context => {
      const response = await context.request.get(`${baseURL}/api/annotations/current/protein`);
      expect(response.ok(), await response.text()).toBeTruthy();
      return response.json();
    };
    const original = await getAnnotation(first);
    expect(original.filteredRows).toBe(12);
    expect((await getAnnotation(second)).filteredRows).toBe(6);
    await second.request.post(`${baseURL}/api/viewer/auth/logout`);
    expect((await second.request.get(`${baseURL}/api/annotations/current/protein`)).status()).toBe(401);
    expect(await getAnnotation(first)).toEqual(original);
  } finally { await first.close(); await second.close(); }
});
