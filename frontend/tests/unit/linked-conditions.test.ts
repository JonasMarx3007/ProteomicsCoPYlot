import { describe, expect, it } from "vitest";
import { linkedConditionsParam } from "../../src/features/analysis/linkedConditions";

describe("the analysis tiles' conditions", () => {
  it("keep a condition that contains a comma whole", () => {
    expect(JSON.parse(linkedConditionsParam({ condition1: "Drug, high", condition2: "B" }))).toEqual(["Drug, high", "B"]);
  });

  it("are an empty list with no linked volcano", () => {
    expect(linkedConditionsParam(null)).toBe("[]");
  });
});
