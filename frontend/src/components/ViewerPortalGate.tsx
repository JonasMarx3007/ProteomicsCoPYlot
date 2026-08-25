import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getViewerAuthStatus, loginViewer, loginViewerQr, logoutViewer } from "../lib/api";
import { fragmentCredential, removeCredentialQuery } from "../lib/accessTokens";
import { IS_AI_MODE, IS_VIEWER_MODE } from "../lib/appMode";
import type { ViewerAuthStatusResponse } from "../lib/types";
import AppBrand from "./AppBrand";
import PasswordField from "./PasswordField";

type Props = {
  children: ReactNode;
};

type GatePhase = "checking" | "ready" | "error";
let viewerPortalResetOnLoadAttempted = false;

function modeLabel() {
  return IS_AI_MODE ? "Viewer AI" : "Viewer";
}

export default function ViewerPortalGate({ children }: Props) {
  const [phase, setPhase] = useState<GatePhase>("checking");
  const [status, setStatus] = useState<ViewerAuthStatusResponse | null>(null);
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [qrToken] = useState(readQrToken);

  function readQrToken(): string {
    try {
      const names = ["qr", "qrToken"] as const;
      const next = removeCredentialQuery(window.location.href, names);
      const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      if (next !== current) {
        window.history.replaceState(null, document.title, next);
      }
      return fragmentCredential(window.location.hash, names);
    } catch {
      return "";
    }
  }

  function clearQrTokenFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("qr");
      url.searchParams.delete("qrToken");
      const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
      const hashParams = new URLSearchParams(hash);
      hashParams.delete("qr");
      hashParams.delete("qrToken");
      const nextHash = hashParams.toString();
      const next = `${url.pathname}${url.search}${nextHash ? `#${nextHash}` : ""}`;
      window.history.replaceState(null, document.title, next);
    } catch {
      // Keep the app usable if URL cleanup is unavailable.
    }
  }

  const refreshStatus = useCallback(async () => {
    if (!IS_VIEWER_MODE) {
      setPhase("ready");
      setStatus({
        enabled: false,
        authenticated: true,
        project: null,
        projectLabel: null,
      });
      return;
    }

    setPhase("checking");
    setStatusError(null);
    try {
      if (!viewerPortalResetOnLoadAttempted) {
        viewerPortalResetOnLoadAttempted = true;
        try {
          await logoutViewer();
        } catch {
          // Keep login page reachable even if logout endpoint is temporarily unavailable.
        }
      }
      const next = await getViewerAuthStatus();
      setStatus(next);
      setPhase("ready");
    } catch (error) {
      setStatus(null);
      setStatusError(error instanceof Error ? error.message : "Failed to reach viewer auth endpoint.");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    refreshStatus().catch(() => {});
  }, [refreshStatus]);

  useEffect(() => {
    if (phase !== "ready" || !status?.enabled) return;
    if (qrToken) {
      viewerPortalResetOnLoadAttempted = true;
      setPhase("checking");
      setStatusError(null);
      loginViewerQr(qrToken)
        .then(() => {
          clearQrTokenFromUrl();
          return refreshStatus();
        })
        .catch((error) => {
          clearQrTokenFromUrl();
          setStatus(null);
          setStatusError(error instanceof Error ? error.message : "Viewer QR login failed.");
          setPhase("error");
        });
    }
  }, [phase, qrToken, refreshStatus, status?.enabled]);

  const requiresLogin = useMemo(() => {
    if (!IS_VIEWER_MODE) return false;
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
      await loginViewer(password);
      setPassword("");
      await refreshStatus();
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "Viewer login failed.");
    } finally {
      setLoginBusy(false);
    }
  }

  if (phase === "checking") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <AppBrand title={modeLabel()} />
          <p className="mt-3 text-sm text-slate-600">Preparing secure project access...</p>
        </div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-3xl border border-red-200 bg-white p-8 shadow-sm">
          <AppBrand title={modeLabel()} />
          <p className="mt-3 text-sm text-red-700">
            {statusError || "Viewer auth endpoint is currently unavailable."}
          </p>
          <button
            type="button"
            onClick={() => {
              refreshStatus().catch(() => {
                // refreshStatus already sets visible error state.
              });
            }}
            className="mt-5 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
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
      <div className="mx-auto mt-20 max-w-xl rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <AppBrand title={`${modeLabel()} Login`} />
        <p className="mt-3 text-sm text-slate-600">
          Enter your project password to open the assigned viewer.
        </p>
        <form className="mt-6 space-y-4" onSubmit={handleLogin}>
          <div>
            <label htmlFor="viewer-password" className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              Password
            </label>
            <PasswordField
              id="viewer-password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={loginBusy}
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
              placeholder="Enter project password"
            />
          </div>
          {loginError ? <div className="text-sm text-red-700">{loginError}</div> : null}
          <button
            type="submit"
            disabled={loginBusy}
            className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loginBusy ? "Opening..." : "Open Viewer"}
          </button>
        </form>
      </div>
    </div>
  );
}
