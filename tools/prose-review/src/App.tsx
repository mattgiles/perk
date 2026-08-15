import { useEffect, useState } from "react";
import { CenterPane } from "./CenterPane.tsx";
import { InspectorPane } from "./InspectorPane.tsx";
import { SearchBar } from "./SearchBar.tsx";
import { TreePane } from "./TreePane.tsx";
import { type CapabilityTree, parseTree, type UnitRef } from "./tree.ts";
import type { BoundaryKind } from "./wire.ts";

export type Mode = "edit" | "compare" | "assembly";

// A selection is a canonical unit or a boundary layer (select-to-explain). Boundary
// selections carry the layer's display label so the panes can echo the authored name.
export type Selection =
  | { type: "unit"; unit: UnitRef }
  | { type: "boundary"; boundary: BoundaryKind; label: string };

type TreeLoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; tree: CapabilityTree };

// The three-pane workbench shell. Two independent pieces of UI state:
// `mode` (the persistent center-pane mode) and `selection` (the tree selection) —
// navigation never touches `mode`, and mode switches never touch `selection`.
export function App() {
  const [treeState, setTreeState] = useState<TreeLoadState>({ status: "loading" });
  const [mode, setMode] = useState<Mode>("edit");
  const [selection, setSelection] = useState<Selection | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const response = await fetch("/api/catalog/tree");
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const tree = parseTree(await response.json());
        if (tree === null) {
          throw new Error("ill-shaped tree payload");
        }
        if (!cancelled) {
          setTreeState({ status: "loaded", tree });
        }
      } catch {
        // One fixed failure message for every arm: non-ok, network, JSON parse,
        // and a parseTree rejection.
        if (!cancelled) {
          setTreeState({ status: "failed" });
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Search and concern-member navigation only ever change `selection` — never
  // `mode` (the shell invariant).
  const selectUnit = (unit: UnitRef): void => setSelection({ type: "unit", unit });

  return (
    <div className="app">
      <header className="app-header">
        <h1>Prose Review</h1>
        <SearchBar onSelect={selectUnit} />
      </header>
      <nav className="pane tree-pane" aria-label="Capability tree">
        {treeState.status === "loading" && <p className="pane-hint">Loading catalog tree…</p>}
        {treeState.status === "failed" && <p className="pane-hint">Failed to load catalog tree.</p>}
        {treeState.status === "loaded" && (
          <TreePane tree={treeState.tree} selection={selection} onSelect={setSelection} />
        )}
      </nav>
      <main className="pane center-pane">
        <CenterPane mode={mode} onModeChange={setMode} selection={selection} />
      </main>
      <aside className="pane inspector-pane" aria-label="Inspector">
        <InspectorPane selection={selection} onSelect={selectUnit} />
      </aside>
    </div>
  );
}
