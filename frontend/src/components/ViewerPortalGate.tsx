import type { ReactNode } from "react";

import { getViewerAuthStatus, loginViewer, loginViewerQr, logoutViewer } from "../lib/api";
import { IS_AI_MODE, IS_VIEWER_MODE } from "../lib/appMode";
import { onceAsync } from "../lib/onceAsync";
import PasswordGate, { type PasswordGateConfig } from "./PasswordGate";

const MODE_LABEL = IS_AI_MODE ? "Viewer AI" : "Viewer";

const VIEWER_GATE: PasswordGateConfig = {
  active: IS_VIEWER_MODE,
  credentialNames: ["qr", "qrToken"],
  title: MODE_LABEL,
  loginTitle: `${MODE_LABEL} Login`,
  intro: "Enter your project password to open the assigned viewer.",
  inputId: "viewer-password",
  placeholder: "Enter project password",
  submitLabel: "Open Viewer",
  checkingText: "Preparing secure project access...",
  unavailableText: "Viewer auth endpoint is currently unavailable.",
  statusErrorText: "Failed to reach viewer auth endpoint.",
  linkErrorText: "Viewer QR login failed.",
  loginErrorText: "Viewer login failed.",
  resetOnLoad: onceAsync(async () => {
    try {
      await logoutViewer();
    } catch {
      // Keep login reachable if logout is unavailable, but wait for it to settle.
    }
  }),
  getStatus: getViewerAuthStatus,
  login: loginViewer,
  loginLink: loginViewerQr,
};

export default function ViewerPortalGate({ children }: { children: ReactNode }) {
  return <PasswordGate config={VIEWER_GATE}>{children}</PasswordGate>;
}
