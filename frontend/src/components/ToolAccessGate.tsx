import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getToolAuthStatus, loginTool, loginToolLink, logoutTool } from "../lib/api";
import { IS_VIEWER_MODE } from "../lib/appMode";
import type { ToolAuthStatusResponse } from "../lib/types";
import AppBrand from "./AppBrand";
import PasswordField from "./PasswordField";

type Props = {
  children: ReactNode;
};

type GatePhase = "checking" | "ready" | "error";

const TOOL_ACCESS_AUTH_ENABLED = (() => {
  const raw = String(import.meta.env.VITE_TOOL_ACCESS_AUTH ?? "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
})();

let toolResetOnLoadAttempted = false;

function readToolToken(): string {
  try {
    const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
    const hashParams = new URLSearchParams(hash);
    const hashToken = hashParams.get("tool")?.trim() || hashParams.get("toolToken")?.trim() || "";
    if (hashToken) return hashToken;
    const params = new URLSearchParams(window.location.search);
    return params.get("tool")?.trim() || params.get("toolToken")?.trim() || "";
  } catch {
    return "";
  }
}

function clearToolTokenFromUrl() {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete("tool");
    url.searchParams.delete("toolToken");
    const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
    const hashParams = new URLSearchParams(hash);
    hashParams.delete("tool");
    hashParams.delete("toolToken");
    const nextHash = hashParams.toString();
    const next = `${url.pathname}${url.search}${nextHash ? `#${nextHash}` : ""}`;
    window.history.replaceState(null, document.title, next);
  } catch {
    // Keep the app usable if URL cleanup is unavailable.
  }
}

export default function ToolAccessGate({ children }: Props) {
  const [phase, setPhase] = useState<GatePhase>("checking");
  const [status, setStatus] = useState<ToolAuthStatusResponse | null>(null);
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    if (IS_VIEWER_MODE || !TOOL_ACCESS_AUTH_ENABLED) {
      setStatus({ enabled: false, authenticated: true });
      setPhase("ready");
      return;
    }

    setPhase("checking");
    setStatusError(null);
    try {
      if (!toolResetOnLoadAttempted) {
        toolResetOnLoadAttempted = true;
        try {
          await logoutTool();
        } catch {
          // Keep login reachable even if logout endpoint is temporarily unavailable.
        }
      }
      const next = await getToolAuthStatus();
      setStatus(next);
      setPhase("ready");
    } catch (error) {
      setStatus(null);
      setStatusError(error instanceof Error ? error.message : "Failed to reach tool auth endpoint.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    const token = readToolToken();
    if (!IS_VIEWER_MODE && TOOL_ACCESS_AUTH_ENABLED && token) {
      toolResetOnLoadAttempted = true;
      setPhase("checking");
      setStatusError(null);
      loginToolLink(token)
        .then(() => {
          clearToolTokenFromUrl();
          return refreshStatus();
        })
        .catch((error) => {
          clearToolTokenFromUrl();
          setStatus(null);
          setStatusError(error instanceof Error ? error.message : "Tool access link failed.");
          setPhase("error");
        });
      return;
    }

    refreshStatus().catch(() => {
      // refreshStatus already updates visible state.
    });
  }, [refreshStatus]);

  const requiresLogin = useMemo(() => {
    if (IS_VIEWER_MODE) return false;
    if (!status) return false;
    return status.enabled && !status.authenticated;
  }, [status]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password.trim()) {
      setLoginError("Please enter a password.");
      return;
    }
    setLoginBusy(true);
    setLoginError(null);
    try {
      await loginTool(password);
      setPassword("");
      await refreshStatus();
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Tool login failed.");
    } finally {
      setLoginBusy(false);
    }
  }

  if (phase === "checking") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <AppBrand title="CoPYlot Tool" />
          <p className="mt-3 text-sm text-slate-600">Preparing secure tool access...</p>
        </div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-2xl border border-red-200 bg-white p-8 shadow-sm">
          <AppBrand title="CoPYlot Tool" />
          <p className="mt-3 text-sm text-red-700">{statusError || "Tool auth endpoint is unavailable."}</p>
          <button
            type="button"
            onClick={() => {
              refreshStatus().catch(() => {
                // refreshStatus already sets visible error state.
              });
            }}
            className="mt-5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!requiresLogin) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen bg-slate-100 p-6">
      <div className="mx-auto mt-20 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <AppBrand title="CoPYlot Tool Login" />
        <form className="mt-6 space-y-4" onSubmit={handleLogin}>
          <div>
            <label htmlFor="tool-password" className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              Password
            </label>
            <PasswordField
              id="tool-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={loginBusy}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
              placeholder="Enter tool password"
            />
          </div>
          {loginError ? <div className="text-sm text-red-700">{loginError}</div> : null}
          <button
            type="submit"
            disabled={loginBusy}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loginBusy ? "Opening..." : "Open Tool"}
          </button>
        </form>
      </div>
    </div>
  );
}
