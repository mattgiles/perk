import { useEffect, useState } from "react";
import { CenterPane } from "./CenterPane.tsx";
import { comparisonRequest, type SelectedComparison } from "./comparison.ts";
import { type ComparisonLoadState, createComparisonLoader } from "./comparisonLoad.ts";
import { EditWorkspace } from "./editWorkspace.ts";
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
import { useDirtyFiles, useWorkspace, WorkspaceProvider } from "./WorkspaceContext.tsx";

export type Mode = "edit" | "compare" | "assembly";

type TreeLoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; tree: CapabilityTree };

function selectedOriginKey(selection: Selection | null): string | null {
  return selection?.type === "unit" ? comparisonOriginKey(selection) : null;
}

function WorkspaceButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const dirtyFiles = useDirtyFiles();
  return (
    <button type="button" className="workspace-button" aria-expanded={open} onClick={onToggle}>
      Workspace ({dirtyFiles.length})
    </button>
  );
}

function WorkspaceDrawer({
  open,
  onOpen,
}: {
  open: boolean;
  onOpen: (target: SourceTarget) => void;
}) {
  const workspace = useWorkspace();
  const dirtyFiles = useDirtyFiles();
  if (!open) {
    return null;
  }
  return (
    <section className="workspace-drawer" aria-label="Workspace">
      <h2>Workspace ({dirtyFiles.length})</h2>
      {dirtyFiles.length === 0 ? (
        <p>No unsaved files.</p>
      ) : (
        <ul>
          {dirtyFiles.map(({ path, target }) => (
            <li key={path}>
              <span className="workspace-dirty-target">
                <strong>{path}</strong> · {target.unit.id}
                {target.fragment !== null && (
                  <>
                    {" "}
                    · {target.fragment.label} ({target.fragment.id})
                  </>
                )}
              </span>
              <span className="workspace-drawer-actions">
                <button type="button" onClick={() => onOpen(target)}>
                  Open
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm(`Discard unsaved changes to ${path}?`)) {
                      workspace.discard(path);
                    }
                  }}
                >
                  Discard file
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function WorkspaceBeforeUnload() {
  const hasDirtyFiles = useDirtyFiles().length > 0;
  useEffect(() => {
    if (!hasDirtyFiles) {
      return;
    }
    const beforeUnload = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
      event.returnValue = true;
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [hasDirtyFiles]);
  return null;
}

// The three-pane workbench shell. Global mode/selection remain independent; the
// comparison options and selected target exist only while Compare is active.
export function App() {
  const [workspace] = useState(() => new EditWorkspace());
  const [treeState, setTreeState] = useState<TreeLoadState>({ status: "loading" });
  const [mode, setMode] = useState<Mode>("edit");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [comparisonState, setComparisonState] = useState<ComparisonLoadState>({
    status: "idle",
  });
  const [selectedComparison, setSelectedComparison] = useState<SelectedComparison | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [comparisonLoader] = useState(() => createComparisonLoader(setComparisonState));
  const originKey = selectedOriginKey(selection);
  const request = selection?.type === "unit" ? comparisonRequest(selection) : null;

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

  // Fragment-only navigation preserves this effect because originKey is the exact
  // unit/shape/position transport identity returned by comparisonRequest.
  // biome-ignore lint/correctness/useExhaustiveDependencies: request and originKey are equivalent.
  useEffect(() => {
    if (mode !== "compare" || request === null) {
      return;
    }
    setSelectedComparison(null);
    comparisonLoader.select(request);
  }, [comparisonLoader, mode, originKey]);

  useEffect(() => () => comparisonLoader.dispose(), [comparisonLoader]);
  useEffect(() => () => workspace.dispose(), [workspace]);

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
    <WorkspaceProvider workspace={workspace}>
      <div className="app">
        <header className="app-header">
          <h1>Prose Review</h1>
          <SearchBar onSelect={selectSource} />
          <WorkspaceButton open={drawerOpen} onToggle={() => setDrawerOpen((open) => !open)} />
        </header>
        <nav className="pane tree-pane" aria-label="Capability tree">
          {treeState.status === "loading" && <p className="pane-hint">Loading catalog tree…</p>}
          {treeState.status === "failed" && (
            <p className="pane-hint">Failed to load catalog tree.</p>
          )}
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
        <WorkspaceDrawer
          open={drawerOpen}
          onOpen={(target) => {
            selectSource(target);
            setDrawerOpen(false);
          }}
        />
        <WorkspaceBeforeUnload />
      </div>
    </WorkspaceProvider>
  );
}
