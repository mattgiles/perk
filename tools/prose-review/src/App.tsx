import {
  type ComponentType,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { type AssemblySessionState, createAssemblySession } from "./assemblySession.ts";
import { CenterPane } from "./CenterPane.tsx";
import { type CheckRunView, type CheckSessionState, createCheckSession } from "./checkSession.ts";
import { CHECK_NOTICE_DETAILS, type CheckId } from "./checks.ts";
import { comparisonRequest, type SelectedComparison } from "./comparison.ts";
import { type ComparisonLoadState, createComparisonLoader } from "./comparisonLoad.ts";
import { EditWorkspace, type WorkspaceSaveState } from "./editWorkspace.ts";
import {
  fetchGitDiff,
  fetchGitStatus,
  GIT_DIFF_EMPTY_COPY,
  GIT_DIFF_LOADING_COPY,
  GIT_DIFF_TRUNCATED_COPY,
  GIT_STATE_LABELS,
  GIT_STATUS_CLEAN_COPY,
  GIT_STATUS_FAILED_COPY,
  GIT_STATUS_LOADING_COPY,
  GIT_STATUS_UNAVAILABLE_COPY,
  type GitFileState,
  type GitStatusOutcome,
  gitOtherChangesNote,
} from "./git.ts";
import {
  createGitDiffCache,
  GIT_DIFF_IDLE_ROW,
  type GitDiffCache,
  type GitDiffRowState,
} from "./gitDiffCache.ts";
import { InspectorPane } from "./InspectorPane.tsx";
import { cyclePane, moveFocusInList } from "./keyboardNav.ts";
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

// Status is always a text label (never color-only).
const CHECK_STATUS_LABELS: Record<CheckRunView["status"], string> = {
  running: "Running",
  passed: "Passed",
  failed: "Failed",
  cancelled: "Cancelled",
  timeout: "Timed out",
  "spawn-failed": "Spawn failed",
  lost: "Lost",
};

function CheckRunRow({
  run,
  onCancel,
  onRunAgain,
}: {
  run: CheckRunView;
  onCancel: () => void;
  onRunAgain: (check: CheckId) => void;
}) {
  // The <pre> body mounts only once opened, so the drawer stays light with up to
  // 20 retained outputs; captured output renders strictly as JSX text interpolation
  // (hostile process output stays literal text).
  const [outputOpen, setOutputOpen] = useState(false);
  return (
    <li className="check-run">
      <span className="check-run-summary">
        <strong>{run.label}</strong> · <code>{run.command}</code> ·{" "}
        {CHECK_STATUS_LABELS[run.status]}
        {run.exitCode !== null && <> · exit {run.exitCode}</>}
        {run.truncated && <> · Output truncated.</>}
      </span>
      <span className="check-run-actions">
        {run.status === "running" ? (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : (
          <button type="button" onClick={() => onRunAgain(run.check)}>
            Run again
          </button>
        )}
      </span>
      <details
        className="check-run-details"
        onToggle={(event) => setOutputOpen(event.currentTarget.open)}
      >
        <summary>Output</summary>
        {outputOpen && <pre className="check-run-output">{run.output}</pre>}
      </details>
    </li>
  );
}

// The component contract for the injected diff renderer: main.tsx (the production
// composition root) passes the real @pierre/diffs-backed GitDiffView; the default
// below keeps jsdom suites library-free. One composition shape, no conditional
// fallback — the truncated-row presentation also renders this text view.
export type GitDiffViewComponent = ComponentType<{ patch: string }>;

export function GitDiffTextView({ patch }: { patch: string }) {
  return <pre className="git-diff-raw">{patch}</pre>;
}

function GitDiffRowBody({
  row,
  diffView: DiffView,
}: {
  row: GitDiffRowState;
  diffView: GitDiffViewComponent;
}) {
  if (row.status === "idle" || row.status === "loading") {
    return <p className="pane-hint">{GIT_DIFF_LOADING_COPY}</p>;
  }
  if (row.status === "failed") {
    return <p className="pane-hint">{row.copy}</p>;
  }
  // Empty and truncated patches never reach the injected view: PatchDiff rejects an
  // empty patch, and a capped patch is no longer parseable — both render built-ins.
  if (row.diff.trim() === "") {
    return <p className="pane-hint">{GIT_DIFF_EMPTY_COPY}</p>;
  }
  if (row.truncated) {
    return (
      <>
        <p className="pane-hint">{GIT_DIFF_TRUNCATED_COPY}</p>
        <GitDiffTextView patch={row.diff} />
      </>
    );
  }
  return <DiffView patch={row.diff} />;
}

function GitChangeRow({
  path,
  state,
  diffCache,
  row,
  diffView,
}: {
  path: string;
  state: GitFileState;
  diffCache: GitDiffCache;
  row: GitDiffRowState;
  diffView: GitDiffViewComponent;
}) {
  // The lazily-mounted body (the CheckRunRow pattern): the diff body exists only
  // while the details element is open.
  const [open, setOpen] = useState(false);
  useEffect(() => {
    // First open starts the fetch; a cache invalidation (a new status outcome)
    // resets the row to idle, so a still-open row refetches against the new
    // snapshot. `open` is idempotent for any non-idle row.
    if (open && row.status === "idle") {
      diffCache.open(path);
    }
  }, [open, row.status, diffCache, path]);
  return (
    <li className="git-change">
      <span className="git-change-summary">
        <strong>{path}</strong> · {GIT_STATE_LABELS[state]}
      </span>
      <details
        className="git-change-details"
        onToggle={(event) => setOpen(event.currentTarget.open)}
      >
        <summary>Diff</summary>
        {open && <GitDiffRowBody row={row} diffView={diffView} />}
      </details>
    </li>
  );
}

function GitChangesSection({
  status,
  pending,
  onRefresh,
  diffCache,
  diffView,
}: {
  status: GitStatusOutcome | null;
  pending: boolean;
  onRefresh: () => void;
  diffCache: GitDiffCache;
  diffView: GitDiffViewComponent;
}) {
  const rows = useSyncExternalStore(diffCache.subscribe, diffCache.state);
  // During a refresh the prior loaded view stays visible (badges and rows
  // retained); only the Refresh button locks until the new outcome lands.
  return (
    <section className="workspace-git" aria-label="Git changes">
      <h3>
        Git changes{" "}
        <button type="button" onClick={onRefresh} disabled={pending}>
          Refresh
        </button>
      </h3>
      {status === null && <p className="pane-hint">{GIT_STATUS_LOADING_COPY}</p>}
      {status?.status === "failed" && <p className="pane-hint">{GIT_STATUS_FAILED_COPY}</p>}
      {status?.status === "loaded" && status.result.status === "unavailable" && (
        <p className="pane-hint">{GIT_STATUS_UNAVAILABLE_COPY[status.result.reason]}</p>
      )}
      {status?.status === "loaded" && status.result.status === "available" && (
        <>
          {status.result.entries.length === 0 ? (
            <p className="pane-hint">{GIT_STATUS_CLEAN_COPY}</p>
          ) : (
            <ul>
              {[...status.result.entries]
                .sort((left, right) => (left.path < right.path ? -1 : 1))
                .map((entry) => (
                  <GitChangeRow
                    key={entry.path}
                    path={entry.path}
                    state={entry.state}
                    diffCache={diffCache}
                    row={rows.get(entry.path) ?? GIT_DIFF_IDLE_ROW}
                    diffView={diffView}
                  />
                ))}
            </ul>
          )}
          {status.result.otherChangeCount > 0 && (
            <p className="pane-hint">{gitOtherChangesNote(status.result.otherChangeCount)}</p>
          )}
        </>
      )}
    </section>
  );
}

function WorkspaceButton({
  open,
  onToggle,
  buttonRef,
}: {
  open: boolean;
  onToggle: () => void;
  buttonRef: RefObject<HTMLButtonElement | null>;
}) {
  const attentionFiles = useAttentionFiles();
  return (
    <button
      ref={buttonRef}
      type="button"
      className="workspace-button"
      aria-expanded={open}
      onClick={onToggle}
    >
      Workspace ({attentionFiles.length})
    </button>
  );
}

function WorkspaceDrawer({
  open,
  onOpen,
  onClose,
  sectionRef,
  checks,
  onRunCheck,
  onCancelCheck,
  gitStatus,
  gitStatusPending,
  onRefreshGit,
  gitDiffCache,
  gitDiffView,
}: {
  open: boolean;
  onOpen: (target: SourceTarget) => void;
  onClose: () => void;
  sectionRef: RefObject<HTMLElement | null>;
  checks: CheckSessionState;
  onRunCheck: (check: CheckId) => void;
  onCancelCheck: () => void;
  gitStatus: GitStatusOutcome | null;
  gitStatusPending: boolean;
  onRefreshGit: () => void;
  gitDiffCache: GitDiffCache;
  gitDiffView: GitDiffViewComponent;
}) {
  const workspace = useWorkspace();
  const attentionFiles = useAttentionFiles();
  if (!open) {
    return null;
  }
  // The record surface: a failed first start is always visible, so the section
  // renders whenever a run, a retained record, or a notice exists.
  const showChecks = checks.active !== null || checks.history.length > 0 || checks.notice !== null;
  return (
    <section
      ref={sectionRef}
      className="workspace-drawer"
      aria-label="Workspace"
      tabIndex={-1}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
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
      <GitChangesSection
        status={gitStatus}
        pending={gitStatusPending}
        onRefresh={onRefreshGit}
        diffCache={gitDiffCache}
        diffView={gitDiffView}
      />
      {showChecks && (
        <section className="workspace-checks" aria-label="Checks">
          <h3>Checks</h3>
          {checks.notice !== null && (
            <p className="check-notice">{CHECK_NOTICE_DETAILS[checks.notice]}</p>
          )}
          <ul>
            {checks.active !== null && (
              <CheckRunRow
                key={checks.active.run}
                run={checks.active}
                onCancel={onCancelCheck}
                onRunAgain={onRunCheck}
              />
            )}
            {checks.history.map((run) => (
              <CheckRunRow
                key={run.run}
                run={run}
                onCancel={onCancelCheck}
                onRunAgain={onRunCheck}
              />
            ))}
          </ul>
        </section>
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
// `gitDiffView` is the one library seam: main.tsx passes the @pierre/diffs-backed
// renderer while the default keeps every jsdom mount library-free.
export function App({
  workspace: injectedWorkspace,
  gitDiffView = GitDiffTextView,
}: {
  workspace?: EditWorkspace;
  gitDiffView?: GitDiffViewComponent;
}) {
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
  const [checkState, setCheckState] = useState<CheckSessionState>({
    active: null,
    history: [],
    notice: null,
  });
  const [checkSession] = useState(() => createCheckSession({ onState: setCheckState }));
  const [gitStatus, setGitStatus] = useState<GitStatusOutcome | null>(null);
  const [gitStatusPending, setGitStatusPending] = useState(true);
  const [gitRefreshCount, setGitRefreshCount] = useState(0);
  const [gitDiffCache] = useState(() => createGitDiffCache({ fetchDiff: fetchGitDiff }));
  const originKey = selectedOriginKey(selection);
  const request = selection?.type === "unit" ? comparisonRequest(selection) : null;
  const assemblyShapeId = selection?.type === "shape" ? selection.shape.id : null;

  // The F6 pane-cycle targets (tabIndex={-1} containers). The drawer ref is null
  // while the drawer is unmounted, so the cycle skips it; the Workspace button ref
  // is the drawer's Esc focus-return target.
  const headerRef = useRef<HTMLElement | null>(null);
  const treeRef = useRef<HTMLElement | null>(null);
  const centerRef = useRef<HTMLElement | null>(null);
  const inspectorRef = useRef<HTMLElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const workspaceButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "F6") {
        const next = cyclePane(
          [
            headerRef.current,
            treeRef.current,
            centerRef.current,
            inspectorRef.current,
            drawerRef.current,
          ],
          document.activeElement,
          event.shiftKey ? -1 : 1,
        );
        next?.focus();
        event.preventDefault();
        return;
      }
      // Suppress the browser's save-page dialog app-wide; the acting Mod+S
      // listener lives in the Edit-mode source presentation (review-gated).
      if (
        (event.key === "s" || event.key === "S") &&
        (event.ctrlKey || event.metaKey) &&
        !event.altKey
      ) {
        event.preventDefault();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Tree arrow navigation, attached to the nav container (not TreePane) so the
  // post-F6 container-focused case enters the list. Collapsed branches are
  // unmounted, so the DOM-order button list is exactly the visible order.
  const treeKeyDown = (event: ReactKeyboardEvent<HTMLElement>): void => {
    const { key } = event;
    if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") {
      return;
    }
    const nav = treeRef.current;
    if (nav === null) {
      return;
    }
    const next = moveFocusInList([...nav.querySelectorAll("button")], document.activeElement, key);
    next?.focus();
    // Clamped steps are handled too: arrow keys never scroll the tree pane.
    event.preventDefault();
  };

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

  // The git-status load rides the catalog-tree effect shape (cancelled-flag
  // cleanup); every completed outcome replaces the last one and invalidates the
  // per-row diff cache, so diffs are fetched at most once per status snapshot.
  // biome-ignore lint/correctness/useExhaustiveDependencies: catalogEpoch and gitRefreshCount are the explicit refresh triggers.
  useEffect(() => {
    let cancelled = false;
    setGitStatusPending(true);
    const load = async (): Promise<void> => {
      const outcome = await fetchGitStatus();
      if (cancelled) {
        return;
      }
      setGitStatus(outcome);
      setGitStatusPending(false);
      gitDiffCache.invalidate();
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [writeState.catalogEpoch, gitRefreshCount]);

  // A false→true freeze transition means a save landed even though the catalog
  // refresh failed — the working tree changed without an epoch bump, so re-observe.
  const frozenRef = useRef(writeState.frozen);
  useEffect(() => {
    if (!frozenRef.current && writeState.frozen) {
      setGitRefreshCount((count) => count + 1);
    }
    frozenRef.current = writeState.frozen;
  }, [writeState.frozen]);

  // Derived per-path annotation for the tree badges and the inspector row — empty
  // unless the last completed outcome is loaded and available.
  const gitStates: ReadonlyMap<string, GitFileState> = useMemo(() => {
    const map = new Map<string, GitFileState>();
    if (gitStatus?.status === "loaded" && gitStatus.result.status === "available") {
      for (const entry of gitStatus.result.entries) {
        map.set(entry.path, entry.state);
      }
    }
    return map;
  }, [gitStatus]);

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
  useEffect(() => () => gitDiffCache.dispose(), [gitDiffCache]);

  // Reload recovery: re-adopt a still-running check once on mount.
  useEffect(() => {
    checkSession.adoptLatest();
    return () => checkSession.dispose();
  }, [checkSession]);

  // Starting any check opens the drawer — the record surface — so a click in the
  // center pane is immediately visible.
  const startCheck = (check: CheckId): void => {
    checkSession.start(check);
    setDrawerOpen(true);
  };

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
        <header ref={headerRef} className="app-header" tabIndex={-1}>
          <h1>Prose Review</h1>
          <SearchBar key={writeState.catalogEpoch} onSelect={selectSource} />
          <WorkspaceButton
            open={drawerOpen}
            onToggle={() => setDrawerOpen((open) => !open)}
            buttonRef={workspaceButtonRef}
          />
          {(writeState.frozen || writeState.suspended) && (
            <p className="write-state-warning">{writeState.detail ?? INDETERMINATE_DETAIL}</p>
          )}
        </header>
        <nav
          ref={treeRef}
          className="pane tree-pane"
          aria-label="Capability tree"
          tabIndex={-1}
          onKeyDown={treeKeyDown}
        >
          {treeState.status === "loading" && <p className="pane-hint">Loading catalog tree…</p>}
          {treeState.status === "failed" && (
            <p className="pane-hint">Failed to load catalog tree.</p>
          )}
          {treeWarning !== null && <p className="catalog-warning">{treeWarning}</p>}
          {treeState.status === "loaded" && (
            <TreePane
              tree={treeState.tree}
              gitStates={gitStates}
              selection={selection}
              onSelect={select}
            />
          )}
        </nav>
        <main ref={centerRef} className="pane center-pane" aria-label="Center pane" tabIndex={-1}>
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
            checkActive={checkState.active !== null}
            onRunCheck={startCheck}
          />
        </main>
        <aside
          ref={inspectorRef}
          className="pane inspector-pane"
          aria-label="Inspector"
          tabIndex={-1}
        >
          <InspectorPane
            key={writeState.catalogEpoch}
            mode={mode}
            selection={selection}
            comparisonState={comparisonState}
            selectedComparison={selectedComparison}
            assemblyState={assemblyState}
            gitStates={gitStates}
            onShowGitChanges={() => setDrawerOpen(true)}
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
            // Focus must never be left on a node the drawer close unmounts.
            centerRef.current?.focus();
          }}
          onClose={() => {
            setDrawerOpen(false);
            workspaceButtonRef.current?.focus();
          }}
          sectionRef={drawerRef}
          checks={checkState}
          onRunCheck={startCheck}
          onCancelCheck={checkSession.cancel}
          gitStatus={gitStatus}
          gitStatusPending={gitStatusPending}
          onRefreshGit={() => setGitRefreshCount((count) => count + 1)}
          gitDiffCache={gitDiffCache}
          gitDiffView={gitDiffView}
        />
        <WorkspaceBeforeUnload />
      </div>
    </WorkspaceProvider>
  );
}
