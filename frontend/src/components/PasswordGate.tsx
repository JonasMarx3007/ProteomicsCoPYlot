import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";

import { fragmentCredential, removeCredentialQuery } from "../lib/accessTokens";
import AppBrand from "./AppBrand";
import PasswordField from "./PasswordField";

type AuthStatus = { enabled: boolean; authenticated: boolean };

/** What differs between the tool login and the viewer login; the flow is shared. */
export type PasswordGateConfig = {
  /** False when this gate does not apply in the current mode (it then renders its children). */
  active: boolean;
  /** URL query and fragment names that may carry a one-time access link token. */
  credentialNames: readonly [string, string];
  title: string;
  loginTitle: string;
  intro?: string;
  inputId: string;
  placeholder: string;
  submitLabel: string;
  checkingText: string;
  unavailableText: string;
  statusErrorText: string;
  linkErrorText: string;
  loginErrorText: string;
  resetOnLoad: () => Promise<void>;
  getStatus: () => Promise<AuthStatus>;
  login: (password: string) => Promise<unknown>;
  loginLink: (token: string) => Promise<unknown>;
};

type GatePhase = "checking" | "ready" | "error";

function readLinkToken(names: readonly string[]): string {
  try {
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

function clearLinkTokenFromUrl(names: readonly string[]) {
  try {
    const url = new URL(window.location.href);
    const hash = url.hash.startsWith("#") ? url.hash.slice(1) : url.hash;
    const hashParams = new URLSearchParams(hash);
    for (const name of names) {
      url.searchParams.delete(name);
      hashParams.delete(name);
    }
    const nextHash = hashParams.toString();
    const next = `${url.pathname}${url.search}${nextHash ? `#${nextHash}` : ""}`;
    window.history.replaceState(null, document.title, next);
  } catch {
    // Keep the app usable if URL cleanup is unavailable.
  }
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default function PasswordGate({ config, children }: { config: PasswordGateConfig; children: ReactNode }) {
  const { active, credentialNames, getStatus, resetOnLoad, statusErrorText } = config;
  const [phase, setPhase] = useState<GatePhase>(active ? "checking" : "ready");
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [linkToken, setLinkToken] = useState(() => (active ? readLinkToken(credentialNames) : ""));

  const refreshStatus = useCallback(async (isCurrent: () => boolean = () => true) => {
    if (!active) {
      setStatus({ enabled: false, authenticated: true });
      setPhase("ready");
      return;
    }
    setPhase("checking");
    setStatusError(null);
    try {
      await resetOnLoad();
      if (!isCurrent()) return;
      const next = await getStatus();
      if (!isCurrent()) return;
      setStatus(next);
      setPhase("ready");
    } catch (error) {
      if (!isCurrent()) return;
      setStatus(null);
      setStatusError(errorText(error, statusErrorText));
      setPhase("error");
    }
  }, [active, getStatus, resetOnLoad, statusErrorText]);

  useEffect(() => {
    let current = true;
    refreshStatus(() => current).catch(() => {});
    return () => { current = false; };
  }, [refreshStatus]);

  useEffect(() => {
    if (phase !== "ready" || !status?.enabled || !linkToken) return;
    setLinkToken("");
    clearLinkTokenFromUrl(credentialNames);
    setPhase("checking");
    setStatusError(null);
    config.loginLink(linkToken)
      .then(() => refreshStatus())
      .catch((error) => {
        setStatus(null);
        setStatusError(errorText(error, config.linkErrorText));
        setPhase("error");
      });
  }, [config, credentialNames, linkToken, phase, refreshStatus, status?.enabled]);

  const requiresLogin = active && !!status && status.enabled && !status.authenticated;

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password.trim()) {
      setLoginError("Please enter a password.");
      return;
    }
    setLoginBusy(true);
    setLoginError(null);
    try {
      await config.login(password);
      setPassword("");
      await refreshStatus();
    } catch (error) {
      setLoginError(errorText(error, config.loginErrorText));
    } finally {
      setLoginBusy(false);
    }
  }

  if (phase === "checking") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <AppBrand title={config.title} />
          <p className="mt-3 text-sm text-slate-600">{config.checkingText}</p>
        </div>
      </div>
    );
  }

  if (phase === "error") {
    return (
      <div className="min-h-screen bg-slate-100 p-6">
        <div className="mx-auto mt-28 max-w-xl rounded-2xl border border-red-200 bg-white p-8 shadow-sm">
          <AppBrand title={config.title} />
          <p className="mt-3 text-sm text-red-700">{statusError || config.unavailableText}</p>
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
        <AppBrand title={config.loginTitle} />
        {config.intro ? <p className="mt-3 text-sm text-slate-600">{config.intro}</p> : null}
        <form className="mt-6 space-y-4" onSubmit={handleLogin}>
          <div>
            <label htmlFor={config.inputId} className="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              Password
            </label>
            <PasswordField
              id={config.inputId}
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={loginBusy}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
              placeholder={config.placeholder}
            />
          </div>
          {loginError ? <div className="text-sm text-red-700">{loginError}</div> : null}
          <button
            type="submit"
            disabled={loginBusy}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loginBusy ? "Opening..." : config.submitLabel}
          </button>
        </form>
      </div>
    </div>
  );
}
