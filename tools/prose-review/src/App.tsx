import { useEffect, useState } from "react";
import { type AssemblySessionState, createAssemblySession } from "./assemblySession.ts";
import { CenterPane } from "./CenterPane.tsx";
import { comparisonRequest, type SelectedComparison } from "./comparison.ts";
import { type ComparisonLoadState, createComparisonLoader } from "./comparisonLoad.ts";
import { EditWorkspace, type WorkspaceSaveState } from "./editWorkspace.ts";
import { InspectorPane } from "./InspectorPane.tsx";
import { SearchBar } from "./SearchBar.tsx";
import { INDETERMINATE_DETAIL } from "./save.ts";
import {
  canonicalSourceSelection,
  comparisonOriginKey,
  type Selection,
  type SourceTarget,
} from "./selection.ts";
import { TreePane } from "./TreePane.tsx";
import { type CapabilityTree, parseTree } from "./tree.ts";
import {
  useAttentionFiles,
  useDirtyFiles,
  useWorkspace,
  WorkspaceProvider,
} from "./WorkspaceContext.tsx";

export type Mode = "edit" | "compare" | "assembly";

type TreeLoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; tree: CapabilityTree };

const SAVE_STATE_LABELS: Record<WorkspaceSaveState["status"], string | null> = {
  idle: null,
  saving: "Saving",
  "not-sent": "Save not sent",
  "validation-failed": "Validation failed",
  refused: "Save blocked",
  conflict: "Disk conflict",
  reconciling: "Checking save result",
  indeterminate: "Save result unknown",
  reloading: "Reloading from disk",
  saved: "Saved",
  "reconciled-saved": "Saved after reconciliation",
};

function selectedOriginKey(selection: Selection | null): string | null {
  return selection?.type === "unit" ? comparisonOriginKey(selection) : null;
}

function WorkspaceButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const attentionFiles = useAttentionFiles();
  return (
    <button type="button" className="workspace-button" aria-expanded={open} onClick={onToggle}>
      Workspace ({attentionFiles.length})
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
  const attentionFiles = useAttentionFiles();
  if (!open) {
    return null;
  }
  return (
    <section className="workspace-drawer" aria-label="Workspace">
      <h2>Workspace ({attentionFiles.length})</h2>
      {attentionFiles.length === 0 ? (
        <p>No files need attention.</p>
      ) : (
        <ul>
          {attentionFiles.map(({ path, target, dirty, saveState, canDiscard }) => {
            const saveStateLabel = SAVE_STATE_LABELS[saveState.status];
            return (
              <li key={path}>
                <span className="workspace-dirty-target">
                  <strong>{path}</strong> · {target.unit.id}
                  {dirty && <> · Unsaved edits</>}
                  {saveStateLabel !== null && <> · {saveStateLabel}</>}
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
                  {canDiscard && dirty && (
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
                  )}
                </span>
              </li>
            );
          })}
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
// comparison options and selected target exist only while Compare is active, and the
// assembly session only while Assembly is active. The optional workspace prop is the
// test injection seam; production (main.tsx) renders <App /> and owns a fresh one.
export function App({ workspace: injectedWorkspace }: { workspace?: EditWorkspace }) {
  const [workspace] = useState(() => injectedWorkspace ?? new EditWorkspace());
  const [treeState, setTreeState] = useState<TreeLoadState>({ status: "loading" });
  const [treeWarning, setTreeWarning] = useState<string | null>(null);
  const [writeState, setWriteState] = useState(() => workspace.writeState());
  const [mode, setMode] = useState<Mode>("edit");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [comparisonState, setComparisonState] = useState<ComparisonLoadState>({
    status: "idle",
  });
  const [selectedComparison, setSelectedComparison] = useState<SelectedComparison | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [comparisonLoader] = useState(() => createComparisonLoader(setComparisonState));
  const [assemblyState, setAssemblyState] = useState<AssemblySessionState>({ status: "idle" });
  const [assemblySession] = useState(() =>
    createAssemblySession({
      onState: setAssemblyState,
      buffersFn: () => workspace.exportBuffers(),
    }),
  );
  const originKey = selectedOriginKey(selection);
  const request = selection?.type === "unit" ? comparisonRequest(selection) : null;
  const assemblyShapeId = selection?.type === "shape" ? selection.shape.id : null;

  useEffect(
    () =>
      workspace.subscribeGlobal(() => {
        setWriteState(workspace.writeState());
        // Buffer edits re-render the assembly preview only when the exported
        // records actually changed (the session fingerprints them).
        assemblySession.refreshBuffers();
      }),
    [workspace, assemblySession],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: catalogEpoch is the explicit refresh trigger.
  useEffect(() => {
    let cancelled = false;
    const priorTree = treeState.status === "loaded" ? treeState : null;
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
          setTreeWarning(null);
        }
      } catch {
        if (!cancelled && priorTree === null) {
          setTreeState({ status: "failed" });
        } else if (!cancelled) {
          setTreeWarning(
            "Catalog refreshed, but the tree could not be reloaded. The prior tree remains available.",
          );
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [writeState.catalogEpoch]);

  // Fragment-only navigation preserves this effect because originKey is the exact
  // unit/shape/position transport identity returned by comparisonRequest.
  // biome-ignore lint/correctness/useExhaustiveDependencies: request and originKey are equivalent.
  useEffect(() => {
    if (mode !== "compare" || request === null) {
      return;
    }
    setSelectedComparison(null);
    comparisonLoader.select(request);
  }, [comparisonLoader, mode, originKey, writeState.catalogEpoch]);

  // The assembly subject: the selected shape names the assembly to fetch and render;
  // a catalog-epoch bump re-opens the session against the refreshed catalog.
  // biome-ignore lint/correctness/useExhaustiveDependencies: assemblyShapeId is the subject identity.
  useEffect(() => {
    if (mode !== "assembly" || selection?.type !== "shape") {
      return;
    }
    assemblySession.open(selection.shape.assembly);
  }, [assemblySession, mode, assemblyShapeId, writeState.catalogEpoch]);

  useEffect(() => () => comparisonLoader.dispose(), [comparisonLoader]);
  useEffect(() => () => assemblySession.dispose(), [assemblySession]);
  useEffect(() => () => workspace.dispose(), [workspace]);

  const select = (next: Selection): void => {
    if (mode === "compare" && selectedOriginKey(next) !== originKey) {
      comparisonLoader.clear();
      setSelectedComparison(null);
    }
    if (mode === "assembly") {
      const nextShapeId = next.type === "shape" ? next.shape.id : null;
      if (nextShapeId === null || nextShapeId !== assemblyShapeId) {
        assemblySession.clear();
      }
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
    if (mode === "assembly" && next !== "assembly") {
      assemblySession.clear();
    }
    setMode(next);
  };

  return (
    <WorkspaceProvider workspace={workspace}>
      <div className="app">
        <header className="app-header">
          <h1>Prose Review</h1>
          <SearchBar key={writeState.catalogEpoch} onSelect={selectSource} />
          <WorkspaceButton open={drawerOpen} onToggle={() => setDrawerOpen((open) => !open)} />
          {(writeState.frozen || writeState.suspended) && (
            <p className="write-state-warning">{writeState.detail ?? INDETERMINATE_DETAIL}</p>
          )}
        </header>
        <nav className="pane tree-pane" aria-label="Capability tree">
          {treeState.status === "loading" && <p className="pane-hint">Loading catalog tree…</p>}
          {treeState.status === "failed" && (
            <p className="pane-hint">Failed to load catalog tree.</p>
          )}
          {treeWarning !== null && <p className="catalog-warning">{treeWarning}</p>}
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
            assemblyState={assemblyState}
            assemblyCallbacks={{
              chooseScenario: assemblySession.chooseScenario,
              setOverride: assemblySession.setOverride,
              rerender: assemblySession.rerender,
            }}
          />
        </main>
        <aside className="pane inspector-pane" aria-label="Inspector">
          <InspectorPane
            key={writeState.catalogEpoch}
            mode={mode}
            selection={selection}
            comparisonState={comparisonState}
            selectedComparison={selectedComparison}
            assemblyState={assemblyState}
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
