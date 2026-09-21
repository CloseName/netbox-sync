import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import {AuthGate,installAuthBoundary} from "./AuthGate";
import { App } from "./App";
import { BootstrapGate } from "./BootstrapGate";
import { applyTheme, readTheme } from "./ui/theme";
import "./ui/tokens.css";
import "./styles.css";
import "./ui/foundation.css";
applyTheme(readTheme());
installAuthBoundary();
const router = createBrowserRouter([{path:"*",element:<AuthGate><BootstrapGate><App /></BootstrapGate></AuthGate>}]);
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
