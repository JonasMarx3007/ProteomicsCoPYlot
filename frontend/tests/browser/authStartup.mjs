import { expect } from '@playwright/test';

export async function verifyAuthStartup(page, authPath) {
  await page.addInitScript((authPath) => {
    const original = window.fetch;
    window.authOrder = [];
    window.fetch = async (...args) => {
      const path = new URL(args[0] instanceof Request ? args[0].url : args[0], location.href).pathname;
      const tracked = path.startsWith(authPath + '/');
      if (tracked) window.authOrder.push(`${path}:start`);
      const response = await original(...args);
      if (tracked) window.authOrder.push(`${path}:finish`);
      return response;
    };
  }, authPath);
  let release;
  let captured;
  const gate = new Promise(resolve => { release = resolve; });
  const pending = new Promise(resolve => { captured = resolve; });
  await page.route(`**${authPath}/logout`, async route => {
    captured();
    await gate;
    await route.continue();
  });
  try {
    await page.goto('/');
    await pending;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    expect(await page.evaluate(() => window.authOrder)).toEqual([`${authPath}/logout:start`]);
  } finally { release(); }
  await expect.poll(() => page.evaluate(path => window.authOrder.includes(`${path}/status:finish`), authPath)).toBe(true);
  const order = await page.evaluate(() => window.authOrder);
  expect(order.indexOf(`${authPath}/status:start`)).toBeGreaterThan(order.indexOf(`${authPath}/logout:finish`));
  expect(order.filter(event => event === `${authPath}/status:start`)).toHaveLength(1);
}
