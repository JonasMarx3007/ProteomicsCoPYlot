import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import Modal from "./Modal";
import type { SidebarSection } from "../lib/types";
import type {
  ChatMessage,
  ChatProvider,
  CloudAiConsentStatus,
  ModelCapabilityResponse,
  ModelContextTier,
  ModuleContextResponse,
} from "../lib/types";
import {
  CloudAiConsentRequiredError,
  getCloudAiConsentStatus,
  getAiModuleContext,
  getModelCapability,
  getOllamaGpuStatus,
  getOllamaModels,
  installOllamaModel,
  removeOllamaModel,
  grantCloudAiConsent,
  revokeCloudAiConsent,
  streamChatMessage,
} from "../lib/api";
import { subscribeDatasetStateChanged } from "../lib/datasetEvents";

type AppShellProps = {
  activeSection: SidebarSection;
  onSectionChange: (section: SidebarSection) => void;
  sections?: SidebarSection[];
  topBar?: ReactNode;
  activeModuleKey?: string;
  activeWorkflowScope?: string;
  activeContextMode?: string;
  aiEnabled?: boolean;
  rightPanel?: "none" | "list" | "chat";
  onRightPanelChange?: (panel: "none" | "list" | "chat") => void;
  children: ReactNode;
};


const CHAT_READY_MESSAGE = "AI chat is ready. Ask me about your data, plots, or next analysis steps.";
const MAX_MODEL_HISTORY_MESSAGES = 8;
const CHAT_INPUT_MAX_CHARS = 32_000;
const DEFAULT_DEV_OLLAMA_ENDPOINT = String(import.meta.env.VITE_AI_DEFAULT_OLLAMA_ENDPOINT ?? "").trim();
const DEFAULT_DEV_OLLAMA_MODEL = String(import.meta.env.VITE_AI_DEFAULT_OLLAMA_MODEL ?? "").trim();
const API_PROVIDER_DEFAULT_MODELS: Record<Exclude<ChatProvider, "ollama">, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-sonnet-latest",
  gemini: "gemini-2.0-flash",
};
function contextRequestKey(
  moduleKey: string,
  workflowScope: string,
  contextMode: string,
  contextTier: ModelContextTier = "compact"
): string {
  const moduleValue = String(moduleKey || "").trim();
  const workflowValue = String(workflowScope || "").trim().toLowerCase();
  const modeValue = String(contextMode || "").trim().toLowerCase();
  if (!moduleValue) {
    if (workflowValue && modeValue) return `workflow:${workflowValue}::mode:${modeValue}::${contextTier}`;
    if (workflowValue) return `workflow:${workflowValue}::${contextTier}`;
    if (modeValue) return `mode:${modeValue}::${contextTier}`;
    return "";
  }
  if (workflowValue && modeValue) return `${moduleValue}::${workflowValue}::${modeValue}::${contextTier}`;
  if (workflowValue) return `${moduleValue}::${workflowValue}::${contextTier}`;
  if (modeValue) return `${moduleValue}::${modeValue}::${contextTier}`;
  return `${moduleValue}::${contextTier}`;
}

function ModelCapabilityIndicator({ capability }: { capability: ModelCapabilityResponse | null }) {
  const level = capability?.level ?? 0;
  const color = level === 3 ? "bg-emerald-500" : level === 2 ? "bg-amber-400" : "bg-red-500";
  const label = capability?.label ?? "Detecting";
  return (
    <div
      className="inline-flex items-end gap-1"
      title={capability ? `${capability.reason}. Evidence profile: ${capability.contextTier}.` : "Detecting model capabilities"}
      aria-label={`Model capability: ${label}`}
    >
      <span className="mr-1 text-[11px] text-slate-500">Capability: {label}</span>
      {[1, 2, 3].map((bar) => (
        <span
          key={bar}
          className={[
            "w-1.5 rounded-sm",
            bar <= level ? color : "bg-slate-200",
            bar === 1 ? "h-2" : bar === 2 ? "h-3" : "h-4",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

function normalizeThinkingMarkup(content: string): string {
  let text = String(content ?? "");
  if (!text) return "";
  text = text.replace(
    /```(?:thinking|reasoning|thought)\s*([\s\S]*?)```/gi,
    (_match, body: string) => `<think>${String(body ?? "")}</think>`
  );
  text = text.replace(/<\s*(thinking|reasoning|thought)(?:\s+[^>]*)?>/gi, "<think>");
  text = text.replace(/<\s*\/\s*(thinking|reasoning|thought)\s*>/gi, "</think>");
  text = text.replace(/<\s*think(?:\s+[^>]*)?>/gi, "<think>");
  text = text.replace(/<\s*\/\s*think\s*>/gi, "</think>");
  return text;
}

function splitAssistantContent(content: string): { thinking: string; answer: string } {
  const text = normalizeThinkingMarkup(content);
  if (!text) return { thinking: "", answer: "" };
  const tagRegex = /<\/?think>/gi;
  let cursor = 0;
  let inThinking = false;
  const thinkingParts: string[] = [];
  const answerParts: string[] = [];
  let match: RegExpExecArray | null;

  while ((match = tagRegex.exec(text)) !== null) {
    const index = match.index;
    if (index > cursor) {
      const chunk = text.slice(cursor, index);
      if (chunk) {
        if (inThinking) {
          thinkingParts.push(chunk);
        } else {
          answerParts.push(chunk);
        }
      }
    }
    inThinking = String(match[0]).toLowerCase() === "<think>";
    cursor = tagRegex.lastIndex;
  }

  if (cursor < text.length) {
    const tail = text.slice(cursor);
    if (tail) {
      if (inThinking) {
        thinkingParts.push(tail);
      } else {
        answerParts.push(tail);
      }
    }
  }

  const thinking = thinkingParts.join("").replace(/\n{3,}/g, "\n\n").trim();
  const answer = answerParts.join("").replace(/\n{3,}/g, "\n\n").trim();
  return { thinking, answer };
}

function stripThinkingBlocks(content: string): string {
  const text = normalizeThinkingMarkup(content);
  if (!text) return "";
  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<think>[\s\S]*$/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeMessageForModel(message: ChatMessage): ChatMessage {
  const role = message.role;
  const base = String(message.content ?? "");
  if (role === "assistant") {
    return { role, content: stripThinkingBlocks(base) };
  }
  return { role, content: base.trim() };
}

export default function AppShell({
  activeSection,
  onSectionChange,
  sections,
  topBar,
  activeModuleKey = "",
  activeWorkflowScope = "",
  activeContextMode = "",
  aiEnabled = false,
  rightPanel = "none",
  onRightPanelChange,
  children,
}: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content: CHAT_READY_MESSAGE,
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatProvider, setChatProvider] = useState<ChatProvider>("ollama");
  const [chatModel, setChatModel] = useState("");
  const [chatOllamaEndpoint, setChatOllamaEndpoint] = useState(DEFAULT_DEV_OLLAMA_ENDPOINT);
  const [chatOllamaEndpointActive, setChatOllamaEndpointActive] = useState(DEFAULT_DEV_OLLAMA_ENDPOINT);
  const [chatRemoteModel, setChatRemoteModel] = useState(API_PROVIDER_DEFAULT_MODELS.openai);
  const [chatApiKey, setChatApiKey] = useState("");
  const [chatApiTemperature, setChatApiTemperature] = useState("0.2");
  const [chatApiMaxTokens, setChatApiMaxTokens] = useState("512");
  const [chatModels, setChatModels] = useState<string[]>([]);
  const [chatModelsLoading, setChatModelsLoading] = useState(false);
  const [chatModelError, setChatModelError] = useState<string | null>(null);
  const [chatModelActionInput, setChatModelActionInput] = useState("");
  const [chatModelActionBusy, setChatModelActionBusy] = useState<"install" | "remove" | null>(null);
  const [chatModelActionError, setChatModelActionError] = useState<string | null>(null);
  const [chatModelActionSuccess, setChatModelActionSuccess] = useState<string | null>(null);
  const [modelCapability, setModelCapability] = useState<ModelCapabilityResponse | null>(null);
  const [modelCapabilityError, setModelCapabilityError] = useState<string | null>(null);
  const [aiSettingsExpanded, setAiSettingsExpanded] = useState(false);
  const [cloudConsentStatus, setCloudConsentStatus] = useState<CloudAiConsentStatus | null>(null);
  const [cloudConsentDialogOpen, setCloudConsentDialogOpen] = useState(false);
  const [cloudConsentBusy, setCloudConsentBusy] = useState(false);
  const [cloudConsentError, setCloudConsentError] = useState<string | null>(null);
  const [gpuEligible, setGpuEligible] = useState(false);
  const [gpuEnabled, setGpuEnabled] = useState(false);
  const [gpuDeviceName, setGpuDeviceName] = useState<string | null>(null);
  const [gpuStatusMessage, setGpuStatusMessage] = useState<string | null>(null);
  const [gpuRemoteEndpoint, setGpuRemoteEndpoint] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);
  const chatOllamaEndpointAppliedRef = useRef(DEFAULT_DEV_OLLAMA_ENDPOINT);
  const contextCacheRef = useRef<Record<string, ModuleContextResponse>>({});
  const contextPendingRef = useRef<Record<string, Promise<ModuleContextResponse | null>>>({});
  const chatOpen = aiEnabled && rightPanel === "chat";
  const moduleKey = activeModuleKey.trim();
  const workflowScope = String(activeWorkflowScope || "").trim().toLowerCase();
  const contextMode = String(activeContextMode || "").trim();
  const usingOllama = chatProvider === "ollama";
  const selectedChatModel = usingOllama ? chatModel.trim() : chatRemoteModel.trim();
  const selectedContextTier: ModelContextTier = modelCapability?.contextTier ?? "compact";
  const activeContextRequestKey = contextRequestKey(
    moduleKey,
    workflowScope,
    contextMode,
    selectedContextTier
  );

  const resetChatForModelChange = useCallback(() => {
    setChatMessages([{ role: "assistant", content: CHAT_READY_MESSAGE }]);
    setChatInput("");
    setChatError(null);
    setModelCapability(null);
    setModelCapabilityError(null);
    contextCacheRef.current = {};
    contextPendingRef.current = {};
  }, []);

  const applyChatModelList = useCallback((
    available: string[],
    selectedModel: string | null,
    warnings: string[],
    preferredModel = ""
  ) => {
    const preferred = preferredModel.trim();
    setChatModels(available);
    setChatModel((current) => {
      let next = "";
      if (preferred && available.includes(preferred)) {
        next = preferred;
      } else if (current && available.includes(current)) {
        next = current;
      } else if (selectedModel && available.includes(selectedModel)) {
        next = selectedModel;
      } else {
        next = available[0] ?? "";
      }
      if (current && current !== next) {
        window.setTimeout(() => {
          resetChatForModelChange();
        }, 0);
      }
      return next;
    });
    if (available.length === 0) {
      const warning = warnings[0] || "No Ollama models detected. Install/pull a model first.";
      setChatModelError(warning);
    } else if (warnings.length > 0) {
      setChatModelError(warnings[0]);
    } else {
      setChatModelError(null);
    }
  }, [resetChatForModelChange]);

  useEffect(() => {
    if (!chatOpen) return;
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, chatLoading, chatOpen]);

  useEffect(() => {
    if (!aiEnabled) {
      setChatModel("");
      setChatProvider("ollama");
      setChatRemoteModel(API_PROVIDER_DEFAULT_MODELS.openai);
      setChatOllamaEndpoint(DEFAULT_DEV_OLLAMA_ENDPOINT);
      setChatOllamaEndpointActive(DEFAULT_DEV_OLLAMA_ENDPOINT);
      chatOllamaEndpointAppliedRef.current = DEFAULT_DEV_OLLAMA_ENDPOINT;
      setChatApiKey("");
      setChatApiTemperature("0.2");
      setChatApiMaxTokens("512");
      setChatModels([]);
      setChatModelsLoading(false);
      setChatModelError(null);
      setChatModelActionInput("");
      setChatModelActionBusy(null);
      setChatModelActionError(null);
      setChatModelActionSuccess(null);
      setModelCapability(null);
      setModelCapabilityError(null);
      setAiSettingsExpanded(false);
      setCloudConsentStatus(null);
      setCloudConsentDialogOpen(false);
      setCloudConsentBusy(false);
      setCloudConsentError(null);
      return;
    }
    if (chatProvider !== "ollama") {
      setChatModel("");
      setChatModels([]);
      setChatModelsLoading(false);
      setChatModelError(null);
      setChatModelActionInput("");
      setChatModelActionBusy(null);
      setChatModelActionError(null);
      setChatModelActionSuccess(null);
      return;
    }
    let cancelled = false;
    const endpoint = chatOllamaEndpointActive.trim();
    setChatModelsLoading(true);
    setChatModelError(null);
    void getOllamaModels(endpoint)
      .then((result) => {
        if (cancelled) return;
        applyChatModelList(result.models, result.selectedModel, result.warnings, DEFAULT_DEV_OLLAMA_MODEL);
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
  }, [aiEnabled, chatProvider, chatOllamaEndpointActive, applyChatModelList]);

  useEffect(() => {
    if (!aiEnabled || usingOllama) {
      setCloudConsentStatus(null);
      setCloudConsentDialogOpen(false);
      setCloudConsentError(null);
      return;
    }
    let cancelled = false;
    void getCloudAiConsentStatus(chatProvider)
      .then((status) => {
        if (cancelled) return;
        setCloudConsentStatus(status);
        setCloudConsentError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setCloudConsentStatus(null);
        setCloudConsentError(err instanceof Error ? err.message : "Cloud consent status unavailable.");
      });
    return () => {
      cancelled = true;
    };
  }, [aiEnabled, chatProvider, usingOllama]);

  useEffect(() => {
    if (!aiEnabled || !selectedChatModel) {
      setModelCapability(null);
      setModelCapabilityError(null);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void getModelCapability(
        chatProvider,
        selectedChatModel,
        usingOllama ? chatOllamaEndpointActive.trim() || undefined : undefined
      )
        .then((capability) => {
          if (cancelled) return;
          setModelCapability(capability);
          setModelCapabilityError(null);
          contextCacheRef.current = {};
          contextPendingRef.current = {};
        })
        .catch((err) => {
          if (cancelled) return;
          setModelCapability(null);
          setModelCapabilityError(
            err instanceof Error ? err.message : "Model capability detection failed."
          );
        });
    }, usingOllama ? 0 : 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [aiEnabled, chatProvider, selectedChatModel, usingOllama, chatOllamaEndpointActive]);

  async function runChatModelAction(action: "install" | "remove") {
    const targetModel = (chatModelActionInput.trim() || chatModel.trim()).trim();
    if (!targetModel) {
      setChatModelActionError("Enter a model name or select one from the model list.");
      setChatModelActionSuccess(null);
      return;
    }
    setChatModelActionBusy(action);
    setChatModelActionError(null);
    setChatModelActionSuccess(null);
    try {
      const endpoint = chatOllamaEndpointActive.trim();
      const response =
        action === "install"
          ? await installOllamaModel(targetModel, endpoint)
          : await removeOllamaModel(targetModel, endpoint);
      applyChatModelList(
        response.models,
        response.selectedModel,
        response.warnings,
        action === "install" ? targetModel : ""
      );
      setChatModelActionInput(action === "install" ? targetModel : "");
      setChatModelActionSuccess(
        response.detail || `${action === "install" ? "Installed" : "Removed"} model '${targetModel}'.`
      );
    } catch (err) {
      setChatModelActionError(
        err instanceof Error ? err.message : `Failed to ${action === "install" ? "install" : "remove"} model.`
      );
    } finally {
      setChatModelActionBusy(null);
    }
  }

  useEffect(() => {
    if (!aiEnabled || chatProvider !== "ollama") {
      setGpuEligible(false);
      setGpuEnabled(false);
      setGpuDeviceName(null);
      setGpuStatusMessage(null);
      setGpuRemoteEndpoint(false);
      return;
    }
    let cancelled = false;
    const endpoint = chatOllamaEndpointActive.trim();
    void getOllamaGpuStatus(endpoint)
      .then((status) => {
        if (cancelled) return;
        const eligible = Boolean(status.gpuEligible);
        setGpuEligible(eligible);
        setGpuEnabled(eligible && Boolean(status.gpuEnabledDefault));
        setGpuDeviceName(status.deviceName ?? null);
        setGpuStatusMessage(status.reason ?? null);
        setGpuRemoteEndpoint(Boolean(status.remoteEndpoint));
      })
      .catch((err) => {
        if (cancelled) return;
        setGpuEligible(false);
        setGpuEnabled(false);
        setGpuDeviceName(null);
        setGpuStatusMessage(err instanceof Error ? err.message : "GPU status unavailable.");
        setGpuRemoteEndpoint(false);
      });
    return () => {
      cancelled = true;
    };
  }, [aiEnabled, chatProvider, chatOllamaEndpointActive]);

  const fetchModuleContext = useCallback(async (
    requestedModuleKey: string,
    requestedWorkflowScope: string,
    requestedContextMode: string,
    forceRefresh = false
  ): Promise<ModuleContextResponse | null> => {
    if (!aiEnabled || !requestedModuleKey) return null;
    const requestKey = contextRequestKey(
      requestedModuleKey,
      requestedWorkflowScope,
      requestedContextMode,
      selectedContextTier
    );
    if (!requestKey) return null;

    if (!forceRefresh) {
      const cached = contextCacheRef.current[requestKey];
      if (cached) return cached;
    }

    const pending = contextPendingRef.current[requestKey];
    if (pending) return pending;

    const nextPromise = getAiModuleContext(
      requestedModuleKey,
      requestedWorkflowScope || undefined,
      requestedContextMode || undefined,
      selectedContextTier
    )
      .then((context) => {
        contextCacheRef.current[requestKey] = context;
        return context;
      })
      .catch(() => null)
      .finally(() => {
        delete contextPendingRef.current[requestKey];
      });
    contextPendingRef.current[requestKey] = nextPromise;
    return nextPromise;
  }, [aiEnabled, selectedContextTier]);

  useEffect(() => {
    if (!aiEnabled || !moduleKey) {
      return;
    }

    let cancelled = false;
    void fetchModuleContext(moduleKey, workflowScope, contextMode).then((context) => {
      if (cancelled || !context) return;
    });

    return () => {
      cancelled = true;
    };
  }, [aiEnabled, moduleKey, workflowScope, contextMode, selectedContextTier, activeContextRequestKey, fetchModuleContext]);

  useEffect(() => {
    if (!aiEnabled) return undefined;
    return subscribeDatasetStateChanged(() => {
      contextCacheRef.current = {};
      if (!moduleKey) return;
      void fetchModuleContext(moduleKey, workflowScope, contextMode, true);
    });
  }, [aiEnabled, moduleKey, workflowScope, contextMode, selectedContextTier, fetchModuleContext]);

  async function sendChatMessage() {
    const message = chatInput.trim();
    if (!message || chatLoading) return;
    const selectedModel = selectedChatModel;
    if (!selectedModel) {
      setChatError(
        usingOllama
          ? "No chatbot model selected. Choose one from the model list first."
          : "No API model selected. Set a model name in AI settings first."
      );
      return;
    }
    if (!usingOllama && !chatApiKey.trim()) {
      setChatError("No API key provided. Add your API key in AI settings first.");
      return;
    }
    if (!usingOllama) {
      setCloudConsentBusy(true);
      try {
        const status = await getCloudAiConsentStatus(chatProvider);
        setCloudConsentStatus(status);
        if (!status.granted) {
          setCloudConsentDialogOpen(true);
          return;
        }
      } catch (err) {
        setChatError(err instanceof Error ? err.message : "Cloud consent status unavailable.");
        return;
      } finally {
        setCloudConsentBusy(false);
      }
    }

    const nextUserMessage: ChatMessage = { role: "user", content: message };
    const history = [...chatMessages, nextUserMessage];
    setChatMessages([...history, { role: "assistant", content: "" }]);
    const historyForModelBase = history
      .map(normalizeMessageForModel)
      .filter(
        (item) =>
          String(item.content ?? "").trim().length > 0 &&
          String(item.content ?? "").trim() !== CHAT_READY_MESSAGE
      )
      .slice(-MAX_MODEL_HISTORY_MESSAGES);
    setChatInput("");
    setChatError(null);
    setChatLoading(true);

    try {
      let contextPrompt = "";
      if (aiEnabled && moduleKey) {
        const cached = contextCacheRef.current[activeContextRequestKey];
        if (cached?.contextPrompt) {
          contextPrompt = cached.contextPrompt;
        } else {
          const contextOrNull = await Promise.race<ModuleContextResponse | null>([
            fetchModuleContext(moduleKey, workflowScope, contextMode),
            new Promise<null>((resolve) => {
              window.setTimeout(() => resolve(null), 300);
            }),
          ]);
          if (contextOrNull?.contextPrompt) {
            contextPrompt = contextOrNull.contextPrompt;
          }
        }
      }

      const historyForModel: ChatMessage[] = historyForModelBase;
      const parsedTemperature = Number(chatApiTemperature);
      const parsedMaxTokens = Number(chatApiMaxTokens);

      const response = await streamChatMessage(
        {
          message,
          messages: historyForModel,
          provider: chatProvider,
          model: selectedModel,
          gpuEnabled: usingOllama && gpuEligible && gpuEnabled,
          apiKey: usingOllama ? undefined : chatApiKey.trim(),
          temperature: usingOllama ? undefined : Number.isFinite(parsedTemperature) ? parsedTemperature : undefined,
          maxTokens: usingOllama ? undefined : Number.isFinite(parsedMaxTokens) ? parsedMaxTokens : undefined,
          ollamaUrl: usingOllama ? chatOllamaEndpointActive.trim() || undefined : undefined,
          analysisContext: contextPrompt || undefined,
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
      if (usingOllama) {
        setChatModel(response.model || chatModel);
      } else {
        setChatRemoteModel(response.model || chatRemoteModel);
      }
    } catch (err) {
      const consentRequired = err instanceof CloudAiConsentRequiredError;
      if (consentRequired) {
        setCloudConsentStatus(err.status);
        setCloudConsentDialogOpen(true);
        setChatInput(message);
      }
      setChatMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last && last.role === "assistant" && !String(last.content ?? "").trim()) {
          next.pop();
        }
        if (consentRequired) {
          const lastUser = next[next.length - 1];
          if (lastUser?.role === "user" && lastUser.content === message) {
            next.pop();
          }
        }
        return next;
      });
      if (!consentRequired) {
        setChatError(err instanceof Error ? err.message : "Failed to load chatbot response");
      }
    } finally {
      setChatLoading(false);
    }
  }

  async function confirmCloudConsent() {
    const status = cloudConsentStatus;
    if (!status || status.provider !== chatProvider || usingOllama) return;
    setCloudConsentBusy(true);
    setCloudConsentError(null);
    try {
      const granted = await grantCloudAiConsent(chatProvider, status.disclosureVersion);
      setCloudConsentStatus(granted);
      setCloudConsentDialogOpen(false);
      await sendChatMessage();
    } catch (err) {
      setCloudConsentError(err instanceof Error ? err.message : "Failed to confirm cloud AI consent.");
    } finally {
      setCloudConsentBusy(false);
    }
  }

  async function revokeCurrentCloudConsent() {
    if (usingOllama) return;
    setCloudConsentBusy(true);
    setCloudConsentError(null);
    try {
      const status = await revokeCloudAiConsent(chatProvider);
      setCloudConsentStatus(status);
    } catch (err) {
      setCloudConsentError(err instanceof Error ? err.message : "Failed to revoke cloud AI consent.");
    } finally {
      setCloudConsentBusy(false);
    }
  }

  return (
    <div className="relative min-h-screen w-full bg-slate-50 text-slate-900">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[80] focus:rounded-lg focus:bg-white focus:p-3">Skip to analysis content</a>
      <Sidebar
        activeSection={activeSection}
        onChange={onSectionChange}
        isOpen={sidebarOpen}
        onClose={() => {
          setSidebarOpen(false);
          requestAnimationFrame(() => {
            if (document.activeElement === document.body) {
              document.querySelector<HTMLButtonElement>('[aria-label="Open sidebar"]')?.focus();
            }
          });
        }}
        sections={sections}
      />

      {!sidebarOpen ? (
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="relative z-30 m-3 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition hover:bg-slate-50 md:fixed md:bottom-4 md:left-4 md:z-50 md:m-0"
          aria-label="Open sidebar"
        >
          Menu
        </button>
      ) : null}

      {aiEnabled ? (
        <>
          <aside
            inert={!chatOpen}
            aria-hidden={!chatOpen}
            aria-label="Chatbot"
            className={[
              "fixed inset-y-0 right-0 z-40 flex h-screen w-80 shrink-0 flex-col border-l border-slate-200 bg-white transition-transform duration-300",
              chatOpen ? "translate-x-0" : "translate-x-full",
            ].join(" ")}
          >
            <div className="flex items-start justify-between border-b border-slate-200 p-5">
              <div className="pr-4">
                <div className="text-xl font-bold tracking-tight text-slate-900">Chatbot</div>
                <div className="mt-1 text-xs text-slate-500">
                  Model: <span className="font-medium text-slate-700">{selectedChatModel || "Not selected"}</span>
                </div>
                {selectedChatModel ? (
                  <div className="mt-1">
                    <ModelCapabilityIndicator capability={modelCapability} />
                    {modelCapabilityError ? (
                      <div className="mt-0.5 text-[10px] text-amber-700">
                        Capability unavailable; compact evidence is used.
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={() => setAiSettingsExpanded((current) => !current)}
                    className="flex w-full items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
                    aria-expanded={aiSettingsExpanded}
                    aria-label="Toggle AI settings"
                  >
                    <span>AI Settings</span>
                    <span>{aiSettingsExpanded ? "Hide" : "Show"}</span>
                  </button>
                  {aiSettingsExpanded ? (
                    <div className="mt-2 space-y-2">
                      <div>
                        <select
                          value={chatProvider}
                          onChange={(event) => {
                            const nextProvider = event.target.value as ChatProvider;
                            if (!nextProvider || nextProvider === chatProvider) return;
                            setChatProvider(nextProvider);
                            if (nextProvider !== "ollama") {
                              setChatRemoteModel(API_PROVIDER_DEFAULT_MODELS[nextProvider]);
                            }
                            resetChatForModelChange();
                          }}
                          disabled={chatLoading}
                          className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                          aria-label="Select chatbot provider"
                        >
                          <option value="ollama">Local (Ollama)</option>
                          <option value="openai">OpenAI (ChatGPT)</option>
                          <option value="anthropic">Anthropic (Claude)</option>
                          <option value="gemini">Google (Gemini)</option>
                        </select>
                      </div>
                      {usingOllama ? (
                        <>
                          <div>
                            <input
                              type="text"
                              value={chatOllamaEndpoint}
                              onChange={(event) => {
                                setChatOllamaEndpoint(event.target.value);
                              }}
                              onBlur={() => {
                                const nextValue = chatOllamaEndpoint.trim();
                                if (nextValue !== chatOllamaEndpointAppliedRef.current) {
                                  chatOllamaEndpointAppliedRef.current = nextValue;
                                  setChatOllamaEndpointActive(nextValue);
                                  resetChatForModelChange();
                                }
                              }}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  (event.target as HTMLInputElement).blur();
                                }
                              }}
                              placeholder="Ollama endpoint (optional), e.g. http://100.101.102.103:11434"
                              disabled={chatLoading || chatModelActionBusy !== null}
                              className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                            />
                            <div className="mt-1 text-[11px] text-slate-500">
                              Leave empty for local Ollama on this machine.
                            </div>
                          </div>
                          <div>
                            <select
                              value={chatModel}
                              onChange={(event) => {
                                const nextModel = event.target.value;
                                if (!nextModel || nextModel === chatModel) return;
                                setChatModel(nextModel);
                                resetChatForModelChange();
                              }}
                              disabled={
                                chatModelsLoading ||
                                chatModels.length === 0 ||
                                chatLoading ||
                                chatModelActionBusy !== null
                              }
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
                            {chatModelError ? (
                              <div className="mt-1 text-[11px] text-amber-700">{chatModelError}</div>
                            ) : null}
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-2">
                            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                              Model Management
                            </div>
                            <input
                              type="text"
                              value={chatModelActionInput}
                              onChange={(event) => setChatModelActionInput(event.target.value)}
                              placeholder="e.g. deepseek-r1:1.5b"
                              disabled={chatLoading || chatModelActionBusy !== null}
                              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                            />
                            <div className="mt-2 flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => void runChatModelAction("install")}
                                disabled={chatLoading || chatModelActionBusy !== null}
                                className="flex-1 rounded-lg bg-slate-900 px-2 py-1.5 text-[11px] font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
                              >
                                {chatModelActionBusy === "install" ? "Installing..." : "Install"}
                              </button>
                              <button
                                type="button"
                                onClick={() => void runChatModelAction("remove")}
                                disabled={chatLoading || chatModelActionBusy !== null}
                                className="flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-[11px] font-semibold text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                              >
                                {chatModelActionBusy === "remove" ? "Removing..." : "Remove"}
                              </button>
                            </div>
                            {chatModelActionError ? (
                              <div className="mt-1 text-[11px] text-red-700">{chatModelActionError}</div>
                            ) : null}
                            {chatModelActionSuccess ? (
                              <div className="mt-1 text-[11px] text-emerald-700">{chatModelActionSuccess}</div>
                            ) : null}
                          </div>
                          <div className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5">
                            <div className="text-xs text-slate-600">GPU Acceleration</div>
                            {(() => {
                              const remoteLocked = Boolean(gpuRemoteEndpoint);
                              const checked = remoteLocked ? false : gpuEligible && gpuEnabled;
                              const disabled = remoteLocked || !gpuEligible;
                              return (
                            <button
                              type="button"
                              role="switch"
                              aria-checked={checked}
                              disabled={disabled}
                              onClick={() => {
                                if (disabled) return;
                                setGpuEnabled((current) => !current);
                              }}
                              className={[
                                "relative inline-flex h-5 w-9 items-center rounded-full transition",
                                checked ? "bg-slate-900" : "bg-slate-300",
                                disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
                              ].join(" ")}
                              aria-label="Toggle GPU acceleration"
                            >
                              <span
                                className={[
                                  "inline-block h-4 w-4 transform rounded-full bg-white transition",
                                  checked ? "translate-x-4" : "translate-x-1",
                                ].join(" ")}
                              />
                            </button>
                              );
                            })()}
                          </div>
                          <div className="text-[11px] text-slate-500">
                            {gpuRemoteEndpoint
                              ? "Remote acceleration status: Unknown. Toggle is locked (managed by remote host)."
                              : gpuEligible
                                ? `CUDA GPU detected${gpuDeviceName ? `: ${gpuDeviceName}` : "."}`
                                : gpuStatusMessage || "No eligible CUDA GPU detected."}
                          </div>
                        </>
                      ) : (
                        <>
                          <input
                            type="password"
                            value={chatApiKey}
                            onChange={(event) => setChatApiKey(event.target.value)}
                            placeholder="API key"
                            disabled={chatLoading}
                            className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                          />
                          <input
                            type="text"
                            value={chatRemoteModel}
                            onChange={(event) => setChatRemoteModel(event.target.value)}
                            placeholder="Model (e.g. gpt-4o-mini)"
                            disabled={chatLoading}
                            className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                          />
                          <div className="grid grid-cols-2 gap-2">
                            <input
                              type="number"
                              min={0}
                              max={2}
                              step={0.1}
                              value={chatApiTemperature}
                              onChange={(event) => setChatApiTemperature(event.target.value)}
                              placeholder="Temperature"
                              disabled={chatLoading}
                              className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                            />
                            <input
                              type="number"
                              min={64}
                              max={4096}
                              step={1}
                              value={chatApiMaxTokens}
                              onChange={(event) => setChatApiMaxTokens(event.target.value)}
                              placeholder="Max tokens"
                              disabled={chatLoading}
                              className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
                            />
                          </div>
                          <div className="text-[11px] text-slate-500">
                            API key is used only for this session request flow and is not saved as a local model.
                          </div>
                          <div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-600">
                            <div>
                              Cloud context consent: {cloudConsentStatus?.granted ? "granted" : "required before sending"}
                            </div>
                            {cloudConsentStatus?.granted ? (
                              <button
                                type="button"
                                onClick={() => void revokeCurrentCloudConsent()}
                                disabled={cloudConsentBusy || chatLoading}
                                className="mt-1 font-semibold text-slate-800 underline disabled:text-slate-400"
                              >
                                Revoke consent
                              </button>
                            ) : null}
                            {cloudConsentError ? <div className="mt-1 text-red-700">{cloudConsentError}</div> : null}
                          </div>
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRightPanelChange?.("none")}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 shadow-sm transition hover:border-slate-300 hover:bg-white hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
                aria-label="Close chatbot sidebar"
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  fill="none"
                  className="h-4 w-4"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                >
                  <path d="M6 6l12 12" />
                  <path d="M18 6L6 18" />
                </svg>
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
                      (() => {
                        const parsed = splitAssistantContent(item.content);
                        return (
                          <div className="space-y-2">
                            {parsed.thinking ? (
                              <details className="rounded-lg border border-amber-200 bg-amber-50 px-2 py-1.5">
                                <summary className="cursor-pointer select-none text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                                  Thinking
                                </summary>
                                <div className="mt-1 whitespace-pre-wrap break-words text-slate-800">
                                  {parsed.thinking}
                                </div>
                              </details>
                            ) : null}
                            {parsed.answer ? (
                              <div className="whitespace-pre-wrap break-words">{parsed.answer}</div>
                            ) : null}
                          </div>
                        );
                      })()
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
                maxLength={CHAT_INPUT_MAX_CHARS}
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
                disabled={
                  chatLoading ||
                  cloudConsentBusy ||
                  !chatInput.trim() ||
                  !selectedChatModel ||
                  (!usingOllama && !chatApiKey.trim())
                }
                className="mt-2 w-full rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
              >
                {chatLoading ? "Sending..." : "Send"}
              </button>
            </div>
          </aside>

          {rightPanel === "none" ? (
            <button
              type="button"
              onClick={() => onRightPanelChange?.("chat")}
              className="fixed bottom-4 right-4 z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition hover:bg-slate-50"
              aria-label="Open chatbot sidebar"
            >
              Chatbot
            </button>
          ) : null}
        </>
      ) : null}

      {cloudConsentDialogOpen && cloudConsentStatus ? (
        <Modal labelledBy="cloud-ai-consent-title" busy={cloudConsentBusy}
          onClose={() => setCloudConsentDialogOpen(false)} className="max-w-lg">
          <div className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl">
            <h2 id="cloud-ai-consent-title" className="text-lg font-bold text-slate-900">
              Send analysis context to {cloudConsentStatus.providerLabel}?
            </h2>
            <p className="mt-2 text-sm text-slate-700">{cloudConsentStatus.notice}</p>
            <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
                <div className="font-semibold text-amber-900">Sent</div>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-amber-900">
                  {cloudConsentStatus.transmitted.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
                <div className="font-semibold text-emerald-900">Not attached</div>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-emerald-900">
                  {cloudConsentStatus.excluded.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            </div>
            {cloudConsentError ? <div className="mt-3 text-sm text-red-700">{cloudConsentError}</div> : null}
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setCloudConsentDialogOpen(false);
                  setChatProvider("ollama");
                  resetChatForModelChange();
                }}
                disabled={cloudConsentBusy}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700"
              >
                Use Ollama
              </button>
              <button
                type="button"
                onClick={() => setCloudConsentDialogOpen(false)}
                disabled={cloudConsentBusy}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void confirmCloudConsent()}
                disabled={cloudConsentBusy}
                className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-400"
              >
                {cloudConsentBusy ? "Confirming..." : "Confirm and send"}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}

      <div
        className={[
          "min-h-screen min-w-0 transition-all duration-300",
          sidebarOpen ? "md:ml-72" : "ml-0",
          chatOpen ? "lg:pr-[20rem]" : "pr-0",
        ].join(" ")}
      >
        {topBar ? <div className="shrink-0">{topBar}</div> : null}

        <main id="main-content" tabIndex={-1} lang="en-US" className="min-w-0 p-4 sm:p-6">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}
