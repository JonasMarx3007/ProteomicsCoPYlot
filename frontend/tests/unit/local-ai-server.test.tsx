/**
 * A local server that speaks the OpenAI-compatible API (llama.cpp, vLLM, LM
 * Studio) as an AI provider: its own address field, models from the server,
 * and Ollama's trust -- no cloud consent, the address sent with every request.
 * The backend side is tests/unit/assistant/test_local_openai_server.py.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "../../src/components/AppShell";
import * as api from "../../src/lib/api";
import * as assistant from "../../src/lib/runAssistant";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));
vi.mock("../../src/lib/runAssistant", () => ({ runAssistant: vi.fn(), ShownAssistantError: class extends Error {} }));

const PRESET = "http://10.0.0.5:8084/v1";
const POLICY = { providers: ["ollama", "openai_compatible", "openai"], models: {}, modelManagement: false };

beforeEach(() => {
  Element.prototype.scrollTo = vi.fn();
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getProviderDefaults).mockResolvedValue({ models: {}, policy: POLICY, localServerUrl: PRESET });
  vi.mocked(api.getLocalServerModels).mockResolvedValue({ models: ["glm5"], selectedModel: "glm5", warnings: [] });
  vi.mocked(assistant.runAssistant).mockResolvedValue({ answer: "fine", evidence: [] } as never);
});

async function chooseLocalServer() {
  render(<AppShell activeSection="data" onSectionChange={() => {}} aiEnabled rightPanel="chat" onRightPanelChange={() => {}}><p>Page</p></AppShell>);
  fireEvent.click(screen.getByLabelText("Toggle AI settings"));
  await act(async () => {});
  fireEvent.change(screen.getByLabelText("Select chatbot provider"), { target: { value: "openai_compatible" } });
  await act(async () => {});
}

describe("a local OpenAI-compatible server", () => {
  it("is offered, starts from the operator's address and lists the server's models", async () => {
    await chooseLocalServer();
    expect((screen.getByLabelText("Local AI server address") as HTMLInputElement).value).toBe(PRESET);
    expect(api.getLocalServerModels).toHaveBeenLastCalledWith(PRESET, "");
    expect((screen.getByLabelText("Select chatbot model") as HTMLSelectElement).value).toBe("glm5");
    // Ollama's own controls do not apply to it.
    expect(screen.queryByLabelText("Toggle GPU acceleration")).toBeNull();
    expect(screen.queryByText("Model Management")).toBeNull();
  });

  it("lists the models again for a new address", async () => {
    await chooseLocalServer();
    const address = screen.getByLabelText("Local AI server address");
    fireEvent.change(address, { target: { value: "http://127.0.0.1:8080/v1" } });
    fireEvent.blur(address);
    await act(async () => {});
    expect(api.getLocalServerModels).toHaveBeenLastCalledWith("http://127.0.0.1:8080/v1", "");
  });

  it("sends its address and model without asking for cloud consent", async () => {
    await chooseLocalServer();
    fireEvent.change(screen.getByPlaceholderText("Ask about this analysis..."), { target: { value: "What is shown?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => {});
    expect(api.getCloudAiConsentStatus).not.toHaveBeenCalled();
    const payload = vi.mocked(assistant.runAssistant).mock.calls[0][0];
    expect(payload).toMatchObject({ provider: "openai_compatible", model: "glm5", localServerUrl: PRESET });
    expect(payload.ollamaUrl).toBeUndefined();
  });

  it("sends the assistant level the user chooses and offers images to an Advanced model that reads them", async () => {
    vi.mocked(api.getModelCapability).mockResolvedValue({
      provider: "openai_compatible", model: "glm5", level: 3, label: "High", assessment: "observed", contextTier: "extended",
      contextWindow: 131072, parameterCountB: 320.76, supportsTools: null, supportsVision: true, source: "metadata",
      reason: "Observed", levelName: "Advanced", reasoning: true, outputTokens: 10240,
    });
    await chooseLocalServer();
    await act(async () => {});
    expect(screen.getByLabelText(/Assistant level: Advanced \(observed\)/)).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Ask about this analysis..."), { target: { value: "Make it look its best" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => {});
    const [payload, , , , , , options] = vi.mocked(assistant.runAssistant).mock.calls.at(-1)!;
    expect(payload.assistantLevel).toBe("auto");
    expect(options?.slow).toBe(true);
    expect(typeof options?.plotImage).toBe("function");
    fireEvent.change(screen.getByLabelText("Assistant level"), { target: { value: "basic" } });
    fireEvent.change(screen.getByPlaceholderText("Ask about this analysis..."), { target: { value: "Make it look its best" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => {});
    const [basicPayload, , , , , , basicOptions] = vi.mocked(assistant.runAssistant).mock.calls.at(-1)!;
    expect(basicPayload.assistantLevel).toBe("basic");
    expect(basicOptions?.plotImage).toBeUndefined();
  });
});
