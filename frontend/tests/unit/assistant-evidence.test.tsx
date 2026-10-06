/**
 * How the assistant's supporting evidence is shown.
 *
 * Numbers keep the spelling the backend gave them (4.01e-09 is not rounded),
 * limitations are shown rather than dropped, and evidence text is rendered as
 * text: a label that contains markup must never become markup. The preview
 * shows eight records and says so, while the source text stays available.
 *
 * Converted from a node --test file that compiled the component by hand.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import AssistantEvidence from "../../src/components/AssistantEvidence";

it("keeps numerical spelling, limitations and escaped content", () => {
  const text = "result_row|adjPValue=4.01e-09|mean=0|label=<img src=x onerror=alert(1)>\nMissing counts remain unknown.";
  const html = renderToStaticMarkup(<AssistantEvidence evidence={[{ tool: "canvas_tile", status: "partial", text }]} />);
  expect(html).toMatch(/Partial evidence/);
  expect(html).toMatch(/<dl/);
  expect(html).toMatch(/4.01e-09/);
  expect(html).toMatch(/mean: /);
  expect(html).toMatch(/Missing counts remain unknown/);
  expect(html).toMatch(/&lt;img/);
  expect(html).not.toMatch(/<img/);
  expect(html).toMatch(/Source details/);
});

it("states its own preview limit without removing source records", () => {
  const text = Array.from({ length: 10 }, (_, i) => `row|value=${i}`).join("\n");
  const html = renderToStaticMarkup(<AssistantEvidence evidence={[{ tool: "test", status: "available", text }]} />);
  expect((html.match(/<dl/g) ?? []).length).toBe(8);
  expect(html).toMatch(/Showing the first eight/);
  expect(html).toMatch(/row\|value=9/);
});
