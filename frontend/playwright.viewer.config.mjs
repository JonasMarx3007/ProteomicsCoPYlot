import base from './playwright.config.mjs';

export default {
  ...base,
  outputDir: './test-results/viewer',
  testIgnore: [],
  testMatch: '**/viewer.spec.mjs',
  use: { ...base.use, baseURL: 'http://127.0.0.1:5188' },
  webServer: [
    { ...base.webServer[0], url: 'http://127.0.0.1:8188/api/health',
      env: { COPYLOT_BROWSER_VIEWER: '1' } },
    { ...base.webServer[1], command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5188',
      url: 'http://127.0.0.1:5188',
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:8188', VITE_APP_MODE: 'viewer' } },
  ],
};
