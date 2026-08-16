import { useEffect, useState } from "react";
import { CenterPane } from "./CenterPane.tsx";
import type { ComparisonRequest, SelectedComparison } from "./comparison.ts";
import { type ComparisonLoadState, createComparisonLoader } from "./comparisonLoad.ts";
import { InspectorPane } from "./InspectorPane.tsx";
import { SearchBar } from "./SearchBar.tsx";
import {
  canonicalSourceSelection,
  comparisonOriginKey,
  type Selection,
  type SourceTarget,
} from "./selection.ts";
import { TreePane } from "./TreePane.tsx";
import { type CapabilityTree, parseTree } from "./tree.ts";

export type Mode = "edit" | "compare" | "assembly";
export type { Selection } from "./selection.ts";

type TreeLoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; tree: CapabilityTree };

function selectedOriginKey(selection: Selection | null): string | null {
  return selection?.type === "unit" ? comparisonOriginKey(selection) : null;
}

// The three-pane workbench shell. Global mode/selection remain independent; the
// comparison options and selected target exist only while Compare is active.
export function App() {
  const [treeState, setTreeState] = useState<TreeLoadState>({ status: "loading" });
  const [mode, setMode] = useState<Mode>("edit");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [comparisonState, setComparisonState] = useState<ComparisonLoadState>({
    status: "idle",
  });
  const [selectedComparison, setSelectedComparison] = useState<SelectedComparison | null>(null);
  const [comparisonLoader] = useState(() => createComparisonLoader(setComparisonState));
  const originKey = selectedOriginKey(selection);
  const selectedUnitId = selection?.type === "unit" ? selection.target.unit.id : null;
  const selectedShapeId =
    selection?.type === "unit" ? (selection.placement?.shape.id ?? null) : null;
  const selectedPosition =
    selection?.type === "unit" ? (selection.placement?.position ?? null) : null;

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

  useEffect(() => {
    if (mode !== "compare" || selectedUnitId === null) {
      return;
    }
    const request: ComparisonRequest =
      selectedShapeId === null || selectedPosition === null
        ? { unit: selectedUnitId, shape: null, position: null }
        : { unit: selectedUnitId, shape: selectedShapeId, position: selectedPosition };
    setSelectedComparison(null);
    comparisonLoader.select(request);
  }, [comparisonLoader, mode, selectedPosition, selectedShapeId, selectedUnitId]);

  useEffect(() => () => comparisonLoader.dispose(), [comparisonLoader]);

  const select = (next: Selection): void => {
    if (mode === "compare" && selectedOriginKey(next) !== originKey) {
      comparisonLoader.clear();
      setSelectedComparison(null);
    }
    setSelection(next);
  };

  // Search and concern-member navigation create canonical selections and never
  // change the persistent center-pane mode.
  const selectSource = (target: SourceTarget): void => select(canonicalSourceSelection(target));

  const changeMode = (next: Mode): void => {
    if (mode === "compare" && next !== "compare") {
      comparisonLoader.clear();
      setSelectedComparison(null);
    }
    setMode(next);
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Prose Review</h1>
        <SearchBar onSelect={selectSource} />
      </header>
      <nav className="pane tree-pane" aria-label="Capability tree">
        {treeState.status === "loading" && <p className="pane-hint">Loading catalog tree…</p>}
        {treeState.status === "failed" && <p className="pane-hint">Failed to load catalog tree.</p>}
        {treeState.status === "loaded" && (
          <TreePane tree={treeState.tree} selection={selection} onSelect={select} />
        )}
      </nav>
      <main className="pane center-pane">
        <CenterPane
          mode={mode}
          onModeChange={changeMode}
          selection={selection}
          comparisonState={comparisonState}
          selectedComparison={selectedComparison}
        />
      </main>
      <aside className="pane inspector-pane" aria-label="Inspector">
        <InspectorPane
          mode={mode}
          selection={selection}
          comparisonState={comparisonState}
          selectedComparison={selectedComparison}
          onComparisonSelect={setSelectedComparison}
          onSelection={select}
          onSelect={selectSource}
        />
      </aside>
    </div>
  );
}
