import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { GitDiffView } from "./GitDiffView.tsx";
import "./app.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("missing #root element");
}
// The production composition root injects the real @pierre/diffs renderer; App's
// default stays the built-in text view so jsdom never loads the library.
createRoot(root).render(<App gitDiffView={GitDiffView} />);
