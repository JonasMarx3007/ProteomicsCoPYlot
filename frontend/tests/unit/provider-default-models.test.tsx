/**
 * The browser keeps no list of default cloud models; the server does.
 *
 * The browser pre-filled `claude-3-5-sonnet-latest` and `gemini-2.0-flash`
 * (shut down on 2026-06-01) while the backend defaulted to other models. The
 * backend now keeps the only list and serves it (/api/chat/provider-defaults,
 * tests/unit/assistant/test_provider_default_models.py); the AI settings offer
 * whatever it serves, and until it has answered they offer the server's
 * default rather than a guess.
 *
 * The shell is mounted in AI mode and a cloud provider chosen. This replaced a
 * Python check that searched AppShell.tsx for the retired model names; that no
 * model name is written into the frontend at all is an ESLint rule
 * (eslint.config.js, GLOBAL_RULES).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "../../src/components/AppShell";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const SERVED = { openai: "served-openai-model", anthropic: "served-anthropic-model", gemini: "served-gemini-model" };
const OPEN = { providers: ["ollama", "openai", "anthropic", "gemini"], models: {}, modelManagement: true };

beforeEach(() => {
  // jsdom does not scroll.
  Element.prototype.scrollTo = vi.fn();
  silenceNetwork();
  serveDatasets(api);
});

function mount() {
  render(<AppShell activeSection="data" onSectionChange={() => {}} aiEnabled rightPanel="chat" onRightPanelChange={() => {}}><p>Page</p></AppShell>);
  fireEvent.click(screen.getByLabelText("Toggle AI settings"));
}

function choose(provider: string) {
  fireEvent.change(screen.getByLabelText("Select chatbot provider"), { target: { value: provider } });
  return screen.getByPlaceholderText(/^Model \(/) as HTMLInputElement;
}

describe("the cloud model field", () => {
  it.each(Object.entries(SERVED))("pre-fills the model the server serves for %s", async (provider, model) => {
    vi.mocked(api.getProviderDefaults).mockResolvedValue({ models: SERVED, policy: OPEN });
    mount();
    // Let the served list arrive before the provider is chosen.
    await act(async () => {});
    const field = choose(provider);
    expect(field.value).toBe(model);
    expect(field.placeholder).toBe(`Model (default ${model})`);
  });

  it("offers the server's default, not a model of its own, before the server has answered", () => {
    mount();
    const field = choose("gemini");
    expect(field.value).toBe("");
    expect(field.placeholder).toBe("Model (server default)");
  });
});

describe("the operator's AI policy", () => {
  it("offers only the allowed providers and hides model management", async () => {
    vi.mocked(api.getProviderDefaults).mockResolvedValue({
      models: SERVED, policy: { providers: ["ollama", "anthropic"], models: {}, modelManagement: false },
    });
    mount();
    await act(async () => {});
    const options = Array.from((screen.getByLabelText("Select chatbot provider") as HTMLSelectElement).options).map((option) => option.value);
    expect(options).toEqual(["ollama", "anthropic"]);
    expect(screen.queryByText("Model Management")).toBeNull();
  });

  it("keeps model management on a local run", async () => {
    vi.mocked(api.getProviderDefaults).mockResolvedValue({ models: SERVED, policy: OPEN });
    mount();
    await act(async () => {});
    expect(screen.getByText("Model Management")).toBeTruthy();
  });
});
