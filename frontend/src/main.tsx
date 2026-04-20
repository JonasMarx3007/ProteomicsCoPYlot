import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ViewerPortalGate from "./components/ViewerPortalGate";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ViewerPortalGate>
      <App />
    </ViewerPortalGate>
  </React.StrictMode>
);
