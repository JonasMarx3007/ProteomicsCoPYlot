import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ToolAccessGate from "./components/ToolAccessGate";
import ViewerPortalGate from "./components/ViewerPortalGate";
import { initializeAdvancedPlotState, initializeSessionTheme } from "./lib/appSettings";
import "./index.css";

initializeSessionTheme();
initializeAdvancedPlotState();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ToolAccessGate>
      <ViewerPortalGate>
        <App />
      </ViewerPortalGate>
    </ToolAccessGate>
  </React.StrictMode>
);
