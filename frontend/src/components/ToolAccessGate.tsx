import type { ReactNode } from "react";

import { getToolAuthStatus, loginTool, loginToolLink, logoutTool } from "../lib/api";
import { IS_VIEWER_MODE } from "../lib/appMode";
import { onceAsync } from "../lib/onceAsync";
import PasswordGate, { type PasswordGateConfig } from "./PasswordGate";

const TOOL_GATE: PasswordGateConfig = {
  active: !IS_VIEWER_MODE,
  credentialNames: ["tool", "toolToken"],
  title: "CoPYlot Tool",
  loginTitle: "CoPYlot Tool Login",
  inputId: "tool-password",
  placeholder: "Enter tool password",
  submitLabel: "Open Tool",
  checkingText: "Preparing secure tool access...",
  unavailableText: "Tool auth endpoint is unavailable.",
  statusErrorText: "Failed to reach tool auth endpoint.",
  linkErrorText: "Tool access link failed.",
  loginErrorText: "Tool login failed.",
  resetOnLoad: onceAsync(async () => {
    try {
      await logoutTool();
    } catch {
      // Keep login reachable if logout is unavailable, but wait for it to settle.
    }
  }),
  getStatus: getToolAuthStatus,
  login: loginTool,
  loginLink: loginToolLink,
};

export default function ToolAccessGate({ children }: { children: ReactNode }) {
  return <PasswordGate config={TOOL_GATE}>{children}</PasswordGate>;
}
