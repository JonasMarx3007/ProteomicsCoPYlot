// @vitest-environment node
/**
 * The statistical tests the UI offers are the ones the backend runs.
 *
 * The option lists are compared with the request enums in the generated
 * OpenAPI schema (src/lib/generated/openapi.json, kept current by
 * tests/contracts/test_generated_api_is_current.py) rather than with a regular
 * expression over backend/app/schemas/stats.py, as the node --test version of
 * this file did. That a page uses these shared lists rather than a two-test
 * subset of its own is an ESLint rule (eslint.config.js, STATS_TEST_RULES).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CONTROL_TEST_TYPE_OPTIONS,
  controlTestType,
  restoreTestType,
  SIMULATION_TEST_TYPE_OPTIONS,
  TEST_TYPE_OPTIONS,
} from "../../src/lib/statisticalTests";

const openapi = JSON.parse(readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8"));

function testTypeEnum(schema: string): string[] {
  return openapi.components.schemas[schema].properties.testType.enum;
}

describe("the statistical test choices", () => {
  it.each(["VolcanoRequest", "EnrichmentRequest", "AnalysisVolcanoRequest"])(
    "match the test types %s accepts exactly", (schema) => {
      expect(TEST_TYPE_OPTIONS.map(({ value }) => value)).toEqual(testTypeEnum(schema));
    });

  it("offer the simulation only its supported independent-sample tests", () => {
    expect(SIMULATION_TEST_TYPE_OPTIONS.map(({ value }) => value)).toEqual(testTypeEnum("SimulationRequest"));
  });

  it.each(TEST_TYPE_OPTIONS.map(({ value }) => value))("restore a saved %s as itself", (value) => {
    expect(restoreTestType(value)).toBe(value);
  });

  it("restore an unknown saved test as the unpaired default", () => {
    expect(restoreTestType("anova")).toBe("unpaired");
    expect(restoreTestType(undefined)).toBe("unpaired");
  });

  it("name the variance assumption and the matched samples in their labels", () => {
    expect(TEST_TYPE_OPTIONS[0].label).toMatch(/Student.*equal variance/);
    expect(TEST_TYPE_OPTIONS[1].label).toMatch(/Welch.*unequal variance/);
    expect(TEST_TYPE_OPTIONS[2].label).toMatch(/Paired.*matched samples/);
  });

  it("offer control comparisons only distinct methods and restore a legacy unpaired setting", () => {
    expect(CONTROL_TEST_TYPE_OPTIONS.map(({ value }) => value)).toEqual(["unpaired_welch", "paired"]);
    for (const { value } of CONTROL_TEST_TYPE_OPTIONS) expect(testTypeEnum("VolcanoControlRequest")).toContain(value);
    expect(controlTestType("unpaired")).toBe("unpaired_welch");
    expect(controlTestType("unpaired_welch")).toBe("unpaired_welch");
    expect(controlTestType("paired")).toBe("paired");
    expect(TEST_TYPE_OPTIONS.length).toBe(3);
  });
});
