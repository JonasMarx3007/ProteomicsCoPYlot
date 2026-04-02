import { useEffect, useRef, useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import type { SidebarSection } from "../lib/types";
import type { ChatMessage, ModuleContextResponse } from "../lib/types";
import {
  getAiModuleContext,
  getOllamaGpuStatus,
  getOllamaModels,
  streamOllamaChatMessage,
} from "../lib/api";
import { subscribeDatasetStateChanged } from "../lib/datasetEvents";

type AppShellProps = {
  activeSection: SidebarSection;
  onSectionChange: (section: SidebarSection) => void;
  sections?: SidebarSection[];
  topBar?: ReactNode;
  activeModuleKey?: string;
  aiEnabled?: boolean;
  rightPanel?: "none" | "list" | "chat";
  onRightPanelChange?: (panel: "none" | "list" | "chat") => void;
  children: ReactNode;
};

type AssistantSegmentKind = "thinking" | "answer";

const CHAT_READY_MESSAGE = "Local AI chat is ready. Ask me about your data, plots, or next analysis steps.";

function moduleKeyToLabel(value: string): string {
  const key = String(value || "").trim();
  if (!key) return "";
  return key
    .split(".")
    .filter(Boolean)
    .map((part) =>
      part
        .replace(/([a-z])([A-Z])/g, "$1 $2")
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (match) => match.toUpperCase())
    )
    .join(" / ");
}

function parseAssistantSegments(content: string): Array<{ kind: AssistantSegmentKind; text: string }> {
  const text = String(content ?? "");
  if (!text) return [];
  const segments: Array<{ kind: AssistantSegmentKind; text: string }> = [];
  const tagRegex = /<\/?think>/gi;
  let cursor = 0;
  let mode: AssistantSegmentKind = "answer";
  let match: RegExpExecArray | null;

  while ((match = tagRegex.exec(text)) !== null) {
    const index = match.index;
    if (index > cursor) {
      const chunk = text.slice(cursor, index);
      if (chunk) segments.push({ kind: mode, text: chunk });
    }
    mode = String(match[0]).toLowerCase() === "<think>" ? "thinking" : "answer";
    cursor = tagRegex.lastIndex;
  }

  if (cursor < text.length) {
    const tail = text.slice(cursor);
    if (tail) segments.push({ kind: mode, text: tail });
  }

  if (segments.length === 0) {
    return [{ kind: "answer", text }];
  }
  return segments;
}

export default function AppShell({
  activeSection,
  onSectionChange,
  sections,
  topBar,
  activeModuleKey = "",
  aiEnabled = false,
  rightPanel = "none",
  onRightPanelChange,
  children,
}: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: CHAT_READY_MESSAGE,
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatModel, setChatModel] = useState("");
  const [chatModels, setChatModels] = useState<string[]>([]);
  const [chatModelsLoading, setChatModelsLoading] = useState(false);
  const [chatModelError, setChatModelError] = useState<string | null>(null);
  const [contextModuleLabel, setContextModuleLabel] = useState("");
  const [gpuEligible, setGpuEligible] = useState(false);
  const [gpuEnabled, setGpuEnabled] = useState(false);
  const [gpuDeviceName, setGpuDeviceName] = useState<string | null>(null);
  const [gpuStatusMessage, setGpuStatusMessage] = useState<string | null>(null);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  const contextCacheRef = useRef<Record<string, ModuleContextResponse>>({});
  const contextPendingRef = useRef<Record<string, Promise<ModuleContextResponse | null>>>({});
  const chatOpen = aiEnabled && rightPanel === "chat";
  const moduleKey = activeModuleKey.trim();

  function resetChatForModelChange() {
    setChatMessages([{ role: "assistant", content: CHAT_READY_MESSAGE }]);
    setChatInput("");
    setChatError(null);
    contextCacheRef.current = {};
    contextPendingRef.current = {};
    setContextModuleLabel(moduleKey ? moduleKeyToLabel(moduleKey) : "");
  }

  useEffect(() => {
    if (!chatOpen) return;
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, chatLoading, chatOpen]);

  useEffect(() => {
    if (!aiEnabled) {
      setChatModel("");
      setChatModels([]);
      setChatModelsLoading(false);
      setChatModelError(null);
      return;
    }
    let cancelled = false;
    setChatModelsLoading(true);
    setChatModelError(null);
    void getOllamaModels()
      .then((result) => {
        if (cancelled) return;
        const available = result.models;
        setChatModels(available);
        setChatModel((current) => {
          if (current && available.includes(current)) return current;
          if (result.selectedModel && available.includes(result.selectedModel)) return result.selectedModel;
          return available[0] ?? "";
        });
        if (available.length === 0) {
          const warning = result.warnings[0] || "No Ollama models detected. Install/pull a model first.";
          setChatModelError(warning);
        } else if (result.warnings.length > 0) {
          setChatModelError(result.warnings[0]);
        } else {
          setChatModelError(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setChatModels([]);
        setChatModel("");
        setChatModelError(err instanceof Error ? err.message : "Failed to load Ollama models.");
      })
      .finally(() => {
        if (cancelled) return;
        setChatModelsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [aiEnabled]);

  useEffect(() => {
    if (!aiEnabled) {
      setGpuEligible(false);
      setGpuEnabled(false);
      setGpuDeviceName(null);
      setGpuStatusMessage(null);
      return;
    }
    let cancelled = false;
    void getOllamaGpuStatus()
      .then((status) => {
        if (cancelled) return;
        const eligible = Boolean(status.gpuEligible);
        setGpuEligible(eligible);
        setGpuEnabled(eligible && Boolean(status.gpuEnabledDefault));
        setGpuDeviceName(status.deviceName ?? null);
        setGpuStatusMessage(status.reason ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setGpuEligible(false);
        setGpuEnabled(false);
        setGpuDeviceName(null);
        setGpuStatusMessage(err instanceof Error ? err.message : "GPU status unavailable.");
      });
    return () => {
      cancelled = true;
    };
  }, [aiEnabled]);

  async function fetchModuleContext(
    requestedModuleKey: string,
    forceRefresh = false
  ): Promise<ModuleContextResponse | null> {
    if (!aiEnabled || !requestedModuleKey) return null;

    if (!forceRefresh) {
      const cached = contextCacheRef.current[requestedModuleKey];
      if (cached) return cached;
    }

    const pending = contextPendingRef.current[requestedModuleKey];
    if (pending) return pending;

    const nextPromise = getAiModuleContext(requestedModuleKey)
      .then((context) => {
        contextCacheRef.current[requestedModuleKey] = context;
        return context;
      })
      .catch(() => null)
      .finally(() => {
        delete contextPendingRef.current[requestedModuleKey];
      });
    contextPendingRef.current[requestedModuleKey] = nextPromise;
    return nextPromise;
  }

  useEffect(() => {
    if (!aiEnabled || !moduleKey) {
      setContextModuleLabel("");
      return;
    }

    let cancelled = false;
    const cached = contextCacheRef.current[moduleKey];
    setContextModuleLabel(cached?.moduleTitle || moduleKeyToLabel(moduleKey));

    void fetchModuleContext(moduleKey).then((context) => {
      if (cancelled || !context) return;
      setContextModuleLabel(context.moduleTitle || moduleKeyToLabel(moduleKey));
    });

    return () => {
      cancelled = true;
    };
  }, [aiEnabled, moduleKey]);

  useEffect(() => {
    if (!aiEnabled) return undefined;
    return subscribeDatasetStateChanged(() => {
      contextCacheRef.current = {};
      if (!moduleKey) return;
      void fetchModuleContext(moduleKey, true).then((context) => {
        if (!context) return;
        setContextModuleLabel(context.moduleTitle || moduleKeyToLabel(moduleKey));
      });
    });
  }, [aiEnabled, moduleKey]);

  async function sendChatMessage() {
    const message = chatInput.trim();
    if (!message || chatLoading) return;
    const selectedModel = chatModel.trim();
    if (!selectedModel) {
      setChatError("No chatbot model selected. Choose one from the model list first.");
      return;
    }

    const nextUserMessage: ChatMessage = { role: "user", content: message };
    const history = [...chatMessages, nextUserMessage];
    setChatMessages([...history, { role: "assistant", content: "" }]);
    setChatInput("");
    setChatError(null);
    setChatLoading(true);

    try {
      let contextPrompt = "";
      if (aiEnabled && moduleKey) {
        const cached = contextCacheRef.current[moduleKey];
        if (cached?.contextPrompt) {
          contextPrompt = cached.contextPrompt;
        } else {
          const contextOrNull = await Promise.race<ModuleContextResponse | null>([
            fetchModuleContext(moduleKey),
            new Promise<null>((resolve) => {
              window.setTimeout(() => resolve(null), 300);
            }),
          ]);
          if (contextOrNull?.contextPrompt) {
            contextPrompt = contextOrNull.contextPrompt;
          }
        }
      }

      const historyForModel: ChatMessage[] = contextPrompt
        ? [{ role: "system", content: contextPrompt }, ...history]
        : history;

      const response = await streamOllamaChatMessage(
        {
          message,
          messages: historyForModel,
          model: selectedModel,
          gpuEnabled: gpuEligible && gpuEnabled,
        },
        (chunk) => {
          setChatMessages((current) => {
            if (current.length === 0) return current;
            const next = [...current];
            const last = next[next.length - 1];
            if (last && last.role === "assistant") {
              next[next.length - 1] = {
                ...last,
                content: `${last.content}${chunk}`,
              };
            }
            return next;
          });
        }
      );
      setChatModel(response.model || chatModel);
    } catch (err) {
      setChatMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last && last.role === "assistant" && !String(last.content ?? "").trim()) {
          next.pop();
        }
        return next;
      });
      setChatError(err instanceof Error ? err.message : "Failed to load chatbot response");
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen w-full bg-slate-50 text-slate-900">
      <Sidebar
        activeSection={activeSection}
        onChange={onSectionChange}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        sections={sections}
      />

      <button
        type="button"
        onClick={() => setSidebarOpen((prev) => !prev)}
        className="fixed bottom-4 left-4 z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition hover:bg-slate-50"
        aria-label="Toggle sidebar"
      >
        Menu
      </button>

      {aiEnabled ? (
        <>
          <aside
            className={[
              "fixed inset-y-0 right-0 z-40 flex h-screen w-80 shrink-0 flex-col border-l border-slate-200 bg-white transition-transform duration-300",
              chatOpen ? "translate-x-0" : "translate-x-full",
            ].join(" ")}
          >
            <div className="flex items-start justify-between border-b border-slate-200 p-5">
              <div className="pr-4">
                <div className="text-xl font-bold tracking-tight text-slate-900">Chatbot</div>
                <div className="mt-1 text-xs text-slate-500">
                  Model: <span className="font-medium text-slate-700">{chatModel || "Not selected"}</span>
                </div>
                <div className="mt-1">
                  <select
                    value={chatModel}
                    onChange={(event) => {
                      const nextModel = event.target.value;
                      if (!nextModel || nextModel === chatModel) return;
                      setChatModel(nextModel);
                      resetChatForModelChange();
                    }}
                    disabled={chatModelsLoading || chatModels.length === 0 || chatLoading}
                    className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                    aria-label="Select chatbot model"
                  >
                    {chatModels.length === 0 ? (
                      <option value="">
                        {chatModelsLoading ? "Loading models..." : "No models detected"}
                      </option>
                    ) : null}
                    {chatModels.map((modelName) => (
                      <option key={modelName} value={modelName}>
                        {modelName}
                      </option>
                    ))}
                  </select>
                </div>
                {chatModelError ? (
                  <div className="mt-1 text-[11px] text-amber-700">{chatModelError}</div>
                ) : null}
                <div className="mt-2 flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
                  <div className="text-xs text-slate-600">GPU Acceleration</div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={gpuEligible && gpuEnabled}
                    disabled={!gpuEligible}
                    onClick={() => {
                      if (!gpuEligible) return;
                      setGpuEnabled((current) => !current);
                    }}
                    className={[
                      "relative inline-flex h-5 w-9 items-center rounded-full transition",
                      gpuEligible && gpuEnabled ? "bg-slate-900" : "bg-slate-300",
                      !gpuEligible ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                    ].join(" ")}
                    aria-label="Toggle GPU acceleration"
                  >
                    <span
                      className={[
                        "inline-block h-4 w-4 transform rounded-full bg-white transition",
                        gpuEligible && gpuEnabled ? "translate-x-4" : "translate-x-1",
                      ].join(" ")}
                    />
                  </button>
                </div>
                <div className="mt-1 text-[11px] text-slate-500">
                  {gpuEligible
                    ? `CUDA GPU detected${gpuDeviceName ? `: ${gpuDeviceName}` : "."}`
                    : gpuStatusMessage || "No eligible CUDA GPU detected."}
                </div>
                {activeModuleKey ? (
                  <div className="mt-1 text-xs text-slate-500">
                    Context Module:{" "}
                    <span className="font-medium text-slate-700">
                      {contextModuleLabel || moduleKeyToLabel(activeModuleKey)}
                    </span>
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => onRightPanelChange?.("none")}
                className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
                aria-label="Close chatbot sidebar"
              >
                X
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <div className="space-y-3">
                {chatMessages.map((item, index) => (
                  <div
                    key={`${item.role}-${index}`}
                    className={[
                      "max-w-[92%] rounded-xl px-3 py-2 text-sm",
                      item.role === "user"
                        ? "ml-auto bg-slate-900 text-white"
                        : "mr-auto border border-slate-200 bg-slate-50 text-slate-800",
                    ].join(" ")}
                  >
                    {item.role === "assistant" ? (
                      <div className="space-y-2">
                        {parseAssistantSegments(item.content).map((segment, segmentIndex) => (
                          <div
                            key={`${index}-${segmentIndex}-${segment.kind}`}
                            className={
                              segment.kind === "thinking"
                                ? "rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5"
                                : ""
                            }
                          >
                            <div
                              className={
                                segment.kind === "thinking"
                                  ? "mb-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700"
                                  : "mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500"
                              }
                            >
                              {segment.kind === "thinking" ? "Thinking" : "Answer"}
                            </div>
                            <div className="whitespace-pre-wrap break-words">
                              {segment.text}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="whitespace-pre-wrap break-words">{item.content}</div>
                    )}
                  </div>
                ))}
                <div ref={chatBottomRef} />
              </div>
            </div>
            <div className="border-t border-slate-200 p-4">
              {chatError ? (
                <div className="mb-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {chatError}
                </div>
              ) : null}
              <textarea
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                rows={4}
                placeholder="Ask about this analysis..."
                className="w-full resize-none rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendChatMessage();
                  }
                }}
              />
              <button
                type="button"
                onClick={() => void sendChatMessage()}
                disabled={chatLoading || !chatInput.trim() || !chatModel.trim()}
                className="mt-2 w-full rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {chatLoading ? "Sending..." : "Send"}
              </button>
            </div>
          </aside>

          <button
            type="button"
            onClick={() => onRightPanelChange?.(chatOpen ? "none" : "chat")}
            className={[
              "fixed bottom-4 z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition-all duration-300 hover:bg-slate-50",
              chatOpen ? "right-[21rem]" : "right-4",
            ].join(" ")}
            aria-label="Toggle chatbot sidebar"
          >
            Chatbot
          </button>
        </>
      ) : null}

      <div
        className={[
          "min-h-screen min-w-0 transition-all duration-300",
          sidebarOpen ? "ml-72" : "ml-0",
          chatOpen ? "pr-[20rem]" : "pr-0",
        ].join(" ")}
      >
        {topBar ? <div className="shrink-0">{topBar}</div> : null}

        <main lang="en-US" className="min-w-0 p-4 sm:p-6">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}
