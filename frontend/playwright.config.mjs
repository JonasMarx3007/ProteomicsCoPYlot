import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';

const localPython = '../backend/.venv/Scripts/python.exe';
const python = process.env.COPYLOT_TEST_PYTHON ?? (existsSync(localPython) ? localPython : 'python');

export default defineConfig({
  testDir: './tests/browser',
  outputDir: './test-results/analysis',
  testIgnore: '**/viewer.spec.mjs',
  fullyParallel: false,
  workers: 1, // Backend stores are process-global; never share across workers.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: 0,
  use: { baseURL: 'http://127.0.0.1:5187', browserName: process.env.COPYLOT_TEST_BROWSER ?? 'chromium', actionTimeout: 15_000,
    trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: [
    { command: `"${python}" ../tests/browser_server.py`, url: 'http://127.0.0.1:8187/api/health',
      reuseExistingServer: false, timeout: 120_000 },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5187', url: 'http://127.0.0.1:5187',
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:8187' }, reuseExistingServer: false },
  ],
});
