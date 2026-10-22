import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../../vendor/triage/tokens/tokens.css";
import "../../vendor/triage/core/base.css";
import "../../vendor/triage/core/patterns.css";
import "./workbench.css";

import { App } from "./App";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("ClinicPilot root element #root is missing from index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
