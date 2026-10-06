/**
 * A viewer sees the published project, not the tools that change it.
 *
 * The ID Translator writes its translated table into the session as a dataset
 * of its own, so it is not offered in viewer mode, and the backend refuses its
 * two routes to a viewer (tests/integration/viewer/test_viewer_write_surface.py).
 */
import { describe, expect, it } from "vitest";
import { viewerDataTabs } from "../../src/lib/navigationTabs";

describe("the viewer's data tabs", () => {
  it("offer the upload and annotation views and nothing that writes data", () => {
    expect(viewerDataTabs.map((tab) => tab.key)).toEqual(["upload", "annotation"]);
    expect(viewerDataTabs.map((tab) => tab.key)).not.toContain("translator");
  });
});
