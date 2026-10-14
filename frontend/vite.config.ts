import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";
const basePathRaw = process.env.VITE_BASE_PATH ?? "/";
const basePath = basePathRaw.endsWith("/") ? basePathRaw : `${basePathRaw}/`;

// The analysis and viewer bundles differ only by VITE_APP_MODE, which is baked
// in at build time and is invisible once built. A viewer backend serving an
// analysis bundle looks like a viewer with no gating at all -- every
// data-processing module on screen over read-only data -- and nothing says so.
// Writing the mode into the bundle lets the launcher refuse that combination
// instead of serving it. Keep the values in step with lib/appMode.ts.
const appMode = process.env.VITE_APP_MODE?.trim().toLowerCase() === "viewer" ? "viewer" : "analysis";
const aiEnabled = ["1", "true", "yes", "on"].includes(
  (process.env.VITE_AI_ENABLED ?? "").trim().toLowerCase()
);

// The licences page. The production build writes it as a file next to the bundle;
// the dev server (run_app.bat, Vite on port 5173) serves the same page from memory,
// because a build-only asset does not exist there and the Licences link fell
// through to the app. Only the frontend third-party list is build-only: Vite
// writes THIRD_PARTY_LICENSES.md while bundling.
function licensesHtml(dev: boolean): string {
  const escape = (text: string) => text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  const notice = readFileSync(new URL("../NOTICE", import.meta.url), "utf8");
  const license = readFileSync(new URL("../LICENSE", import.meta.url), "utf8");
  const thirdParty = dev
    ? "Frontend third-party licences (listed in the production build)"
    : '<a href="THIRD_PARTY_LICENSES.md">Frontend third-party licences</a>';
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>CoPYlot licences</title><body><h1>CoPYlot licences</h1><p>${thirdParty} | <a href="https://github.com/JonasMarx3007/ProteomicsCoPYlot">Source code</a></p><pre style="white-space:pre-wrap">${escape(notice)}\n${escape(license)}</pre></body></html>`;
}

function licensesOnDevServer(): Plugin {
  return {
    name: "copylot-licenses-dev",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if ((request.url ?? "").split("?")[0].endsWith("/licenses.html")) {
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(licensesHtml(true));
          return;
        }
        next();
      });
    },
  };
}

function buildModeManifest(): Plugin {
  return {
    name: "copylot-build-mode",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "licenses.html", source: licensesHtml(false) });
      this.emitFile({
        type: "asset",
        fileName: "build-mode.json",
        source: `${JSON.stringify({ appMode, aiEnabled }, null, 2)}\n`,
      });
    },
  };
}

export default defineConfig({
  base: basePath,
  plugins: [react(), tailwindcss(), buildModeManifest(), licensesOnDevServer()],
  build: { license: { fileName: "THIRD_PARTY_LICENSES.md" } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
