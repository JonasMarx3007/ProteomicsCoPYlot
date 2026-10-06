/**
 * Every choice the UI offers is one the backend accepts, and every value the
 * backend accepts is offered. The backend side comes from the generated OpenAPI
 * schema (src/lib/generated/openapi.json), so this needs no source parsing.
 */
import { describe, expect, it } from "vitest";
import schema from "../../src/lib/generated/openapi.json";
import { CONTROL_TEST_TYPE_OPTIONS, SIMULATION_TEST_TYPE_OPTIONS, TEST_TYPE_OPTIONS } from "../../src/lib/statisticalTests";
import { ANOVA_CLUSTER_METHOD_OPTIONS } from "../../src/features/stats/statsHelpers";
import { normalizationOptions } from "../../src/lib/types";

type Property = { enum?: string[] };
const schemas = schema.components.schemas as unknown as Record<string, { properties: Record<string, Property> }>;
const allowed = (model: string, field: string) => [...(schemas[model].properties[field].enum ?? [])].sort();
const values = (options: { value: string }[]) => options.map((option) => option.value).sort();

describe("option lists match the backend", () => {
  it("offers exactly the volcano test types", () => {
    expect(values(TEST_TYPE_OPTIONS)).toEqual(allowed("VolcanoRequest", "testType"));
  });
  it("offers only control-volcano test types the backend accepts", () => {
    const accepted = allowed("VolcanoControlRequest", "testType");
    expect(values(CONTROL_TEST_TYPE_OPTIONS).every((value) => accepted.includes(value))).toBe(true);
  });
  it("offers exactly the simulation test types", () => {
    expect(values(SIMULATION_TEST_TYPE_OPTIONS)).toEqual(allowed("SimulationRequest", "testType"));
  });
  it("offers exactly the ANOVA cluster linkages", () => {
    expect(values(ANOVA_CLUSTER_METHOD_OPTIONS)).toEqual(allowed("AnovaRequest", "clusterMethod"));
  });
  it("offers exactly the normalization methods, VSN only where it can run", () => {
    expect([...normalizationOptions(true)].sort()).toEqual(allowed("AnnotationFilterConfig", "normalization"));
    expect(normalizationOptions(false)).not.toContain("vsn");
  });
});
