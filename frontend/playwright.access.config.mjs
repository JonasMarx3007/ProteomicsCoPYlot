import analysis from './playwright.config.mjs';
import viewer from './playwright.viewer.config.mjs';

const base = process.env.COPYLOT_ACCESS_MODE === 'viewer' ? viewer : analysis;
export default {
  ...base,
  testDir: './tests/access',
  testMatch: '**/*.spec.mjs',
  testIgnore: [],
  outputDir: `./test-results/access-${process.env.COPYLOT_ACCESS_MODE ?? 'tool'}`,
  webServer: [
    { ...base.webServer[0], env: { ...base.webServer[0].env, COPYLOT_BROWSER_TOOL_AUTH: '1' } },
    base.webServer[1],
  ],
};
