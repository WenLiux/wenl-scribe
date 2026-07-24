import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Home from "../app/page";
import "../app/globals.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("留文桌面界面缺少挂载节点");
}

createRoot(root).render(
  <StrictMode>
    <Home />
  </StrictMode>,
);
