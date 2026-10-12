// @vitest-environment node
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

const template = readFileSync(new URL("../../../tools/architecture_map.html", import.meta.url), "utf8");
const hostile = '<img src=x onerror="window.injected=true">';

function map() {
  const model = {
    fingerprint: hostile, counts: { files: hostile },
    nodes: [
      { id: "page:example", label: hostile, col: 0, doc: hostile, files: [hostile] },
      { id: "api:example", label: "Example API", col: 1, file: hostile, usedBy: hostile },
    ],
    links: [{ s: "page:example", t: "api:example", n: 1 }],
    endpoints: [{ group: "api:example", method: hostile, path: "/api/" + hostile,
      handler: hostile, where: hostile, pages: ["example"], calls: [hostile], services: [] }],
  };
  return new JSDOM(template.replace("__MODEL__", JSON.stringify(model).replace(/</g, "\\u003c")), {
    runScripts: "dangerously",
  });
}

describe("architecture map", () => {
  it("renders source labels and endpoint details as text, never markup", () => {
    const dom = map();
    try {
      const doc = dom.window.document;
      doc.querySelector(".node")!.dispatchEvent(new dom.window.MouseEvent("click"));
      expect(doc.querySelector("#panel h2")!.textContent).toBe(hostile);
      expect(doc.querySelector(".ep .m")!.textContent).toBe(hostile);
      expect(doc.querySelector("#meta")!.textContent).toContain(hostile);
      expect(doc.querySelector("img")).toBeNull();
      doc.querySelector(".chip")!.dispatchEvent(new dom.window.MouseEvent("click"));
      expect(doc.querySelector("#panel h2")!.textContent).toBe("Example API");
      expect(doc.querySelector("img")).toBeNull();
    } finally { dom.window.close(); }
  });

  it("searches safely, opens collapsed details and restores the introduction", () => {
    const dom = map();
    try {
      const doc = dom.window.document;
      const intro = doc.querySelector("#panel")!.textContent;
      expect(doc.querySelector(".wrap")!.classList.contains("collapsed")).toBe(true);
      doc.querySelector<HTMLButtonElement>("#panelbtn")!.click();
      expect(doc.querySelector(".wrap")!.classList.contains("collapsed")).toBe(false);
      doc.querySelector<HTMLButtonElement>("#panelbtn")!.click();
      expect(doc.querySelector(".wrap")!.classList.contains("collapsed")).toBe(true);
      const input = doc.querySelector<HTMLInputElement>("#q")!;
      input.value = hostile;
      input.dispatchEvent(new dom.window.Event("input"));
      expect(doc.querySelector("#panel h2")!.textContent).toContain(hostile);
      expect(doc.querySelector(".wrap")!.classList.contains("collapsed")).toBe(false);
      expect(doc.querySelector("img")).toBeNull();
      doc.querySelector<HTMLButtonElement>("#clear")!.click();
      expect(doc.querySelector("#panel")!.textContent).toBe(intro);
      expect(doc.querySelector(".pinned")).toBeNull();
      expect(input.value).toBe("");
    } finally { dom.window.close(); }
  });
});
