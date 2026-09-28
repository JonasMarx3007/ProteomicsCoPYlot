import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/statisticalTests.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { TEST_TYPE_OPTIONS, SIMULATION_TEST_TYPE_OPTIONS, restoreTestType } =
  await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const schema = await readFile(new URL("../../backend/app/schemas/stats.py", import.meta.url), "utf8");
function backendValues(name) {
  const match = schema.match(new RegExp(`^${name} = Literal\\[([^\\]]+)\\]`, "m"));
  assert.ok(match, `${name} contract must be found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]);
}

test("UI test choices match the backend contract exactly", () => {
  assert.deepEqual(TEST_TYPE_OPTIONS.map(({ value }) => value), backendValues("StatsTestType"));
});
test("simulation exposes only its supported independent-sample tests", () => {
  assert.deepEqual(SIMULATION_TEST_TYPE_OPTIONS.map(({ value }) => value), backendValues("SimulationTestType"));
});
for (const { value } of TEST_TYPE_OPTIONS) {
  test(`supported selection ${value} survives UI restoration`, () => assert.equal(restoreTestType(value), value));
}
test("labels distinguish variance assumptions and matched samples", () => {
  assert.match(TEST_TYPE_OPTIONS[0].label, /Student.*equal variance/);
  assert.match(TEST_TYPE_OPTIONS[1].label, /Welch.*unequal variance/);
  assert.match(TEST_TYPE_OPTIONS[2].label, /Paired.*matched samples/);
});
for (const name of ["analysis/AnalysisPage", "stats/VolcanoPanel", "stats/OraPanel", "stats/SimulationPanel", "phospho/KseaPage", "phospho/PhosphoSpecificPage"]) {
  test(`${name} uses the shared options rather than a two-test subset`, async () => {
    const page = await readFile(new URL(`../src/features/${name}.tsx`, import.meta.url), "utf8");
    assert.match(page, /from "\.\.\/\.\.\/lib\/statisticalTests"/);
    assert.doesNotMatch(page, /options=\{\["unpaired", "paired"\]\}/);
  });
}
