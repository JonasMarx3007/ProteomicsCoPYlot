import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import PaginatedTable from "../../src/components/PaginatedTable";
import PreviewTable from "../../src/components/PreviewTable";
import { displayLabel } from "../../src/lib/columnLabels";

afterEach(cleanup);

describe("user-provided table columns", () => {
  const rows = [{ x: 12, y: 13, color_val: 14, constructor: "sample", toString: "label" }];

  it.each([PreviewTable, PaginatedTable])("keeps every data column in %s", (Table) => {
    render(<Table rows={rows} emptyText="No data" />);
    for (const name of Object.keys(rows[0])) {
      expect(screen.getByRole("columnheader", { name })).toBeTruthy();
    }
  });

  it.each([PreviewTable, PaginatedTable])("hides drawing coordinates only in a plot summary in %s", (Table) => {
    render(<Table rows={rows} emptyText="No data" plotSummary />);
    for (const name of ["x", "y", "color_val"]) {
      expect(screen.queryByRole("columnheader", { name })).toBeNull();
    }
    expect(screen.getByRole("columnheader", { name: "constructor" })).toBeTruthy();
  });

  it("does not treat inherited object properties as header overrides", () => {
    expect(displayLabel("constructor", {})).toBe("constructor");
    expect(displayLabel("toString", {})).toBe("toString");
    expect(displayLabel("x", { x: "Coordinate" })).toBe("Coordinate");
  });
});
