import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import ts from "typescript";

const here = dirname(fileURLToPath(import.meta.url));
const src = (relative) => readFileSync(join(here, "..", "src", relative), "utf8");

// Prose about `<img>` in a doc comment is not a rendered image.
const withoutComments = (text) =>
  text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

// Every page that shows a rendered plot had its own copy of the same handler,
// and every copy left the <img> on the page after the request failed -- so the
// browser's broken-image icon sat above the explanation. A refusal such as "no
// matching pathway genes were found in the current dataset" is the answer, and
// it has to replace the figure rather than accompany a broken one.
const PLOT_PAGES = [
  "features/qc/QCPipelinePage.tsx",
  "features/completeness/CompletenessPage.tsx",
  "features/single-protein/SingleProteinPage.tsx",
  "features/phospho/PhosphoSpecificPage.tsx",
  "features/peptide/PeptideLevelPage.tsx",
  "features/stats/statsShared.tsx",
];

test("the failure message replaces the image instead of sitting under it", () => {
  const component = withoutComments(src("components/PlotImage.tsx"));

  // The failure branch returns before any <img> is rendered.
  const failureBranch = component.indexOf("if (error)");
  const imageTag = component.indexOf("<img");
  assert.ok(failureBranch > 0, "PlotImage must have a failure branch");
  assert.ok(imageTag > failureBranch, "the image must come after the early return");
  const branchBody = component.slice(failureBranch, imageTag);
  assert.ok(branchBody.includes("return <div"), "the failure branch must return its own element");
  assert.ok(!branchBody.includes("<img"), "the failure branch must not render an image");
});

test("the state is keyed by url, so changing a control tries again", () => {
  const component = src("components/PlotImage.tsx");
  assert.match(component, /<LoadedPlotImage key=\{props.url\}/);
  assert.match(component, /controller.abort\(\)/);
  assert.match(component, /URL.revokeObjectURL\(image\)/);
});

test("the detail of a refused request is read out of the response", () => {
  const component = src("components/PlotImage.tsx");
  assert.equal((component.match(/await fetch\(/g) ?? []).length, 1);
  assert.match(component, /await fetch\(url, \{ signal: controller.signal \}\)/);
  assert.match(component, /plotErrorMessage\(payload\)/);
  assert.match(component, /PLOT_ERROR_FALLBACK/);
});

const compiled = ts.transpileModule(src("lib/plotError.ts"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { plotErrorMessage, PLOT_ERROR_FALLBACK } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("structured plot errors expose only readable messages, never input or arbitrary objects", () => {
  assert.equal(plotErrorMessage({ detail: "No matching features" }), "No matching features");
  assert.equal(plotErrorMessage({ detail: [{ msg: "Width must be positive", input: "private input" }, { msg: "Select a condition" }] }), "Width must be positive; Select a condition");
  assert.equal(plotErrorMessage({ detail: { msg: "Invalid selection", input: "private input" } }), "Invalid selection");
  assert.equal(plotErrorMessage({ detail: [" repeated ", { msg: "repeated" }] }), "repeated");
  for (const payload of [null, [], "error", {}, { detail: {} }, { detail: [{ msg: {} }] }, { detail: "  " }]) {
    assert.equal(plotErrorMessage(payload), PLOT_ERROR_FALLBACK);
  }
});

test("no plot page renders a plot image of its own any more", () => {
  for (const page of PLOT_PAGES) {
    const text = src(page);
    assert.ok(
      text.includes('from "../../components/PlotImage"'),
      `${page} must render plots through PlotImage`
    );
    // The only <img> tags left on these pages are not plots. A plot image is
    // one whose src is a plot URL built by the page.
    const plotImages = text.match(/<img[^>]*src=\{(?:plotView|url|heatmapUrl|plotUrl)[^}]*\}/g);
    assert.equal(
      plotImages,
      null,
      `${page} still renders a plot <img> directly: ${plotImages?.join(", ")}`
    );
  }
});

test("no page keeps a private copy of the old image-error handler", () => {
  for (const page of PLOT_PAGES) {
    const text = src(page);
    assert.ok(
      !text.includes("async function handleImageError"),
      `${page} still carries its own handleImageError`
    );
  }
});
