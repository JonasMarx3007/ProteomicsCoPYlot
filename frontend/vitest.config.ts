import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Every frontend test that is not a browser test: unit tests of the modules in
// src/lib (tests/unit) and component and contract tests that mount pages in
// jsdom (tests/component). `npm test` runs them all; the Playwright suites are
// separate (`npm run test:browser`, `npm run test:viewer`).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.test.{ts,tsx}", "tests/component/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/component/setup.ts"],
    restoreMocks: true,
  },
});
