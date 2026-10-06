import { existsSync, readdirSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

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

function buildModeManifest(): Plugin {
  return {
    name: "copylot-build-mode",
    apply: "build",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "build-mode.json",
        source: `${JSON.stringify({ appMode, aiEnabled }, null, 2)}\n`,
      });
    },
  };
}

// public/manuals also holds the editable .docx sources (about 6 MB) and PDFs
// no page links to. Vite copies public/ as it is, so without this every build
// shipped them. Only the PDFs App.tsx opens through `manualPath(...)` are kept;
// linking another one there is all it takes to ship it.
function linkedManualsOnly(): Plugin {
  let outDir = "dist";
  let root = process.cwd();
  return {
    name: "copylot-linked-manuals-only",
    apply: "build",
    configResolved(config) {
      root = config.root;
      outDir = path.resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      const manuals = path.join(outDir, "manuals");
      if (!existsSync(manuals)) return;
      const app = readFileSync(path.join(root, "src", "App.tsx"), "utf-8");
      const linked = new Set([...app.matchAll(/manualPath\("([^"]+)"\)/g)].map((match) => match[1]));
      for (const entry of readdirSync(manuals)) {
        if (!linked.has(entry)) rmSync(path.join(manuals, entry), { recursive: true, force: true });
      }
    },
  };
}

export default defineConfig({
  base: basePath,
  plugins: [react(), tailwindcss(), buildModeManifest(), linkedManualsOnly()],
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
