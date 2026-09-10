import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ToolAccessGate from "./components/ToolAccessGate";
import ViewerPortalGate from "./components/ViewerPortalGate";
import AnalysisSessionGate from "./components/AnalysisSessionGate";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ToolAccessGate>
      <ViewerPortalGate>
        <AnalysisSessionGate><App /></AnalysisSessionGate>
      </ViewerPortalGate>
    </ToolAccessGate>
  </React.StrictMode>
);
