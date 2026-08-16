import { type Change, diffLines } from "diff";
import { useState } from "react";
import type { Mode } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import {
  type ComparisonPlacement,
  comparisonPlacementKey,
  type SelectedComparison,
} from "./comparison.ts";
import type { ComparisonLoadState } from "./comparisonLoad.ts";
import {
  CLIPBOARD_FAILURE_DETAIL,
  type SourceDiagnostic,
  supportsSourceSave,
  UNSUPPORTED_FAMILY_DETAIL,
} from "./save.ts";
import {
  type Selection,
  type SourceTarget,
  sourceTargetKey,
  wholeUnitTarget,
} from "./selection.ts";
import { READ_ONLY_PRESENTATION, sourceCurrentText } from "./source.ts";
import { useWorkspace, useWorkspaceSource, type WorkspaceLoadState } from "./WorkspaceContext.tsx";
import type { BoundaryKind } from "./wire.ts";

export { WorkspaceProvider } from "./WorkspaceContext.tsx";

function keyedDiagnostics(
  diagnostics: SourceDiagnostic[],
): { diagnostic: SourceDiagnostic; key: string }[] {
  const occurrences = new Map<string, number>();
  return diagnostics.map((diagnostic) => {
    const identity = JSON.stringify(diagnostic);
    const occurrence = occurrences.get(identity) ?? 0;
    occurrences.set(identity, occurrence + 1);
    return { diagnostic, key: `${identity}:${occurrence}` };
  });
}

const MODES: { id: Mode; label: string }[] = [
  { id: "edit", label: "Edit" },
  { id: "compare", label: "Compare" },
  { id: "assembly", label: "Assembly" },
];

function SourceLoadPresentation({
  target,
  state,
  retry,
}: {
  target: SourceTarget;
  state: WorkspaceLoadState;
  retry: () => void;
}) {
  const workspace = useWorkspace();
  const [clipboardFailure, setClipboardFailure] = useState<string | null>(null);
  if (state.status === "loading") {
    return <p className="pane-hint">Loading source…</p>;
  }
  if (state.status === "refused") {
    return (
      <div className="source-refused">
        <h2>Source unavailable</h2>
        <p>{state.detail}</p>
      </div>
    );
  }
  if (state.status === "failed") {
    return <p className="pane-hint">Failed to load source.</p>;
  }

  const { source } = state;
  const { editor, saveState, view } = source;
  const presentation =
    view.read_only_reason === null ? null : READ_ONLY_PRESENTATION[view.read_only_reason];
  const locked =
    saveState.status === "saving" ||
    saveState.status === "reconciling" ||
    saveState.status === "indeterminate" ||
    saveState.status === "reloading";
  const copyEdits = async (): Promise<void> => {
    const snapshot = workspace.snapshot(source.path);
    if (snapshot === null) {
      setClipboardFailure(CLIPBOARD_FAILURE_DETAIL);
      return;
    }
    try {
      await navigator.clipboard.writeText(snapshot.currentText);
      setClipboardFailure(null);
    } catch {
      setClipboardFailure(CLIPBOARD_FAILURE_DETAIL);
    }
  };
  const attentionControls =
    saveState.status === "conflict" ||
    saveState.status === "reconciling" ||
    saveState.status === "indeterminate" ||
    saveState.status === "reloading";

  return (
    <div className="source-view">
      <div className="source-header">
        <span className="source-path">{source.path}</span>
        <span className="kind-badge">{view.kind}</span>
        <span className={view.editable ? "editable-badge" : "readonly-badge"}>
          {view.editable ? "Editable range" : presentation?.badge}
        </span>
        {source.dirty && <span className="dirty-badge">Dirty</span>}
        {source.dirty && source.canDiscard && (
          <button
            type="button"
            className="discard-button"
            onClick={() => {
              if (window.confirm(`Discard unsaved changes to ${source.path}?`)) {
                workspace.discard(source.path);
              }
            }}
          >
            Discard file
          </button>
        )}
      </div>
      {presentation !== null && (
        <div className="source-readonly-explanation">
          <h2>{presentation.heading}</h2>
          <p>{presentation.explanation}</p>
          {view.read_only_reason === "adapter-unavailable" && (
            <button type="button" onClick={retry}>
              Retry adapter
            </button>
          )}
        </div>
      )}
      {view.editable && (
        <div className="source-legend">
          <span className="readonly-badge">Read-only context</span>
          <span className="editable-badge">Editable range</span>
        </div>
      )}
      {view.editable && editor !== null ? (
        <div className="source-edit-regions">
          <pre className="source-text source-context">{view.before}</pre>
          <textarea
            className="source-focus-editor"
            aria-label={`Edit ${target.fragment?.label ?? target.unit.id}`}
            value={editor.display}
            disabled={locked}
            spellCheck={false}
            onInput={(event) => {
              const outcome = workspace.editFocus({
                target,
                base: editor,
                nextDisplay: event.currentTarget.value,
              });
              if (outcome.status !== "applied") {
                event.currentTarget.value = editor.display;
              }
            }}
          />
          <pre className="source-text source-context">{view.after}</pre>
        </div>
      ) : (
        <pre className="source-text source-readonly-focus">{view.focus}</pre>
      )}
      {view.editable && view.focus.length === 0 && (
        <p className="empty-focus-hint">This mapped fragment is empty.</p>
      )}

      {source.dirty && !supportsSourceSave(target) && (
        <p className="save-unsupported">{UNSUPPORTED_FAMILY_DETAIL}</p>
      )}
      {source.review === null && source.canReview && (
        <button
          type="button"
          className="save-action"
          onClick={() => workspace.beginSaveReview(source.path)}
        >
          Review full-file diff
        </button>
      )}
      {source.review !== null && (
        <section className="save-review" aria-label="Full-file save review">
          <h2>Full-file save review</h2>
          <dl className="save-metadata">
            <div>
              <dt>Loaded</dt>
              <dd>
                {source.review.loaded.bytes} bytes · {source.review.loaded.newlineStyle} · final
                newline {source.review.loaded.finalNewline ? "yes" : "no"} · BOM{" "}
                {source.review.loaded.bom ? "yes" : "no"}
              </dd>
            </div>
            <div>
              <dt>Current</dt>
              <dd>
                {source.review.current.bytes} bytes · {source.review.current.newlineStyle} · final
                newline {source.review.current.finalNewline ? "yes" : "no"} · BOM{" "}
                {source.review.current.bom ? "yes" : "no"}
              </dd>
            </div>
          </dl>
          <pre className="save-diff">{source.review.diff}</pre>
          {source.canSave && (
            <button
              type="button"
              className="save-action"
              onClick={() => void workspace.saveReviewed(source.path)}
            >
              Save reviewed file
            </button>
          )}
        </section>
      )}

      {saveState.status === "saving" && <p className="save-status">Saving reviewed file…</p>}
      {saveState.status === "validation-failed" && (
        <section className="save-result save-validation">
          <h2>Validation failed</h2>
          <ul>
            {keyedDiagnostics(saveState.diagnostics).map(({ diagnostic, key }) => (
              <li key={key}>
                <code>
                  {diagnostic.line !== null && diagnostic.column !== null
                    ? `${source.path}:${diagnostic.line}:${diagnostic.column}`
                    : (diagnostic.selector ?? source.path)}
                </code>{" "}
                {diagnostic.message}
              </li>
            ))}
          </ul>
        </section>
      )}
      {saveState.status === "refused" && (
        <p className="save-result save-refused">{saveState.detail}</p>
      )}
      {saveState.status === "conflict" && (
        <section className="save-result save-conflict">
          <p>{saveState.detail}</p>
          <button type="button" onClick={() => void copyEdits()}>
            Copy Edits
          </button>
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(`Reload ${source.path} from disk and replace all in-memory edits?`)
              ) {
                void workspace.reloadConflict(source.path);
              }
            }}
          >
            Reload from disk
          </button>
        </section>
      )}
      {saveState.status === "reconciling" && <p>{saveState.detail}</p>}
      {saveState.status === "reloading" && <p>Reloading canonical source…</p>}
      {saveState.status === "indeterminate" && (
        <section className="save-result save-indeterminate">
          <p>{saveState.detail}</p>
          <button type="button" onClick={() => void workspace.reconcileSave(source.path)}>
            Retry reconciliation
          </button>
        </section>
      )}
      {attentionControls && saveState.status !== "conflict" && (
        <button type="button" onClick={() => void copyEdits()}>
          Copy Edits
        </button>
      )}
      {clipboardFailure !== null && <p className="clipboard-failure">{clipboardFailure}</p>}
      {saveState.status === "saved" && (
        <section className="save-result save-success">
          <h2>Saved</h2>
          {saveState.result.materialized.length > 0 && (
            <>
              <h3>Materialization handoff</h3>
              <ul>
                {saveState.result.materialized.map((lineage) => (
                  <li key={lineage.id}>
                    <strong>{lineage.id}</strong> · {lineage.relationship}:{" "}
                    {lineage.targets.join(", ")}
                  </li>
                ))}
              </ul>
            </>
          )}
          {saveState.result.checks.length > 0 && (
            <>
              <h3>Suggested checks</h3>
              <ul>
                {saveState.result.checks.map((check) => (
                  <li key={check.id}>
                    <code>{check.command}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
          {saveState.result.refresh_detail !== null && <p>{saveState.result.refresh_detail}</p>}
        </section>
      )}
      {saveState.status === "reconciled-saved" && (
        <p className="save-result save-success">{saveState.detail}</p>
      )}
    </div>
  );
}

function SourceView({ target }: { target: SourceTarget }) {
  const { state, retry } = useWorkspaceSource(target);
  return <SourceLoadPresentation target={target} state={state} retry={retry} />;
}

function BoundaryExplanation({ boundary, label }: { boundary: BoundaryKind; label: string }) {
  const info = BOUNDARY_INFO[boundary];
  return (
    <div className="boundary-explanation">
      <h2>{label}</h2>
      <p>
        <strong>Owner:</strong> {info.owner}
      </p>
      <p>{info.explanation}</p>
    </div>
  );
}

function EditMode({ selection }: { selection: Selection | null }) {
  if (selection === null) {
    return <p className="pane-hint">Select a unit in the capability tree to view its source.</p>;
  }
  if (selection.type === "boundary") {
    return <BoundaryExplanation boundary={selection.boundary} label={selection.label} />;
  }
  if (selection.type === "shape") {
    return (
      <p className="pane-hint">
        This shape has no singular source. Select one of its source-bearing layers to view it.
      </p>
    );
  }
  return <SourceView key={sourceTargetKey(selection.target)} target={selection.target} />;
}

function ComparisonHeader({ placement }: { placement: ComparisonPlacement }) {
  return (
    <div className="comparison-header">
      <h3>{placement.label}</h3>
      <p className="comparison-breadcrumb">
        {placement.breadcrumb.map((capability) => capability.label).join(" / ")}
      </p>
      {placement.shape !== null && (
        <p>
          {placement.shape.label} <span className="delivery-badge">{placement.shape.delivery}</span>
        </p>
      )}
      {placement.assembly !== null && (
        <p>
          {placement.assembly} #{placement.position} · {placement.label}
        </p>
      )}
      <p className="source-path">{placement.unit.path}</p>
      <p>
        <span className="kind-badge">{placement.unit.kind}</span>
      </p>
    </div>
  );
}

function DiffChunks({ chunks, side }: { chunks: Change[]; side: "left" | "right" }) {
  let offset = 0;
  return (
    <pre className="comparison-source-text">
      {chunks.map((chunk) => {
        offset += chunk.value.length;
        if ((side === "left" && chunk.added) || (side === "right" && chunk.removed)) {
          return null;
        }
        const changed = side === "left" ? chunk.removed : chunk.added;
        return (
          <span
            key={`${offset}:${chunk.added}:${chunk.removed}`}
            className={
              changed
                ? `comparison-${side === "left" ? "removed" : "added"}`
                : "comparison-unchanged"
            }
          >
            {chunk.value}
          </span>
        );
      })}
    </pre>
  );
}

function ComparisonSourcePane({
  placement,
  state,
  chunks,
  side,
}: {
  placement: ComparisonPlacement;
  state: WorkspaceLoadState;
  chunks: Change[] | null;
  side: "left" | "right";
}) {
  return (
    <section className="comparison-pane">
      <ComparisonHeader placement={placement} />
      {state.status === "loading" && <p className="pane-hint">Loading source…</p>}
      {state.status === "refused" && (
        <div className="source-refused">
          <h3>Source unavailable</h3>
          <p>{state.detail}</p>
        </div>
      )}
      {state.status === "failed" && <p className="pane-hint">Failed to load source.</p>}
      {state.status === "loaded" && chunks === null && (
        <p className="pane-hint">Source loaded; waiting for the other side…</p>
      )}
      {state.status === "loaded" && chunks !== null && <DiffChunks chunks={chunks} side={side} />}
    </section>
  );
}

function ComparisonPanes({
  origin,
  target,
  left,
  right,
}: {
  origin: ComparisonPlacement;
  target: ComparisonPlacement;
  left: WorkspaceLoadState;
  right: WorkspaceLoadState;
}) {
  const chunks =
    left.status === "loaded" && right.status === "loaded"
      ? diffLines(sourceCurrentText(left.source.view), sourceCurrentText(right.source.view))
      : null;
  const identical = chunks?.every((chunk) => !chunk.added && !chunk.removed) === true;
  return (
    <div className="comparison-result">
      <div className="comparison-legend">
        <span className="comparison-removed-badge">Removed from origin</span>
        <span className="comparison-added-badge">Added in target</span>
        {identical && <span>No differences in current content.</span>}
      </div>
      <div className="comparison-grid">
        <ComparisonSourcePane placement={origin} state={left} chunks={chunks} side="left" />
        <ComparisonSourcePane placement={target} state={right} chunks={chunks} side="right" />
      </div>
    </div>
  );
}

function useWholeUnitSource(unit: ComparisonPlacement["unit"]): WorkspaceLoadState {
  return useWorkspaceSource(wholeUnitTarget(unit)).state;
}

function SharedComparisonSources({
  origin,
  target,
}: {
  origin: ComparisonPlacement;
  target: ComparisonPlacement;
}) {
  const state = useWholeUnitSource(origin.unit);
  return <ComparisonPanes origin={origin} target={target} left={state} right={state} />;
}

function DistinctComparisonSources({
  origin,
  target,
}: {
  origin: ComparisonPlacement;
  target: ComparisonPlacement;
}) {
  const left = useWholeUnitSource(origin.unit);
  const right = useWholeUnitSource(target.unit);
  return <ComparisonPanes origin={origin} target={target} left={left} right={right} />;
}

function SelectedComparisonPair({
  origin,
  selected,
}: {
  origin: ComparisonPlacement;
  selected: SelectedComparison;
}) {
  const target = selected.choice.target;
  const pairKey = JSON.stringify([
    comparisonPlacementKey(origin),
    selected.relation,
    comparisonPlacementKey(target),
  ]);
  if (origin.unit.path === target.unit.path) {
    return <SharedComparisonSources key={pairKey} origin={origin} target={target} />;
  }
  return <DistinctComparisonSources key={pairKey} origin={origin} target={target} />;
}

function CompareMode({
  selection,
  state,
  selected,
}: {
  selection: Selection | null;
  state: ComparisonLoadState;
  selected: SelectedComparison | null;
}) {
  if (selection === null) {
    return <p className="pane-hint">Select a unit to compare its whole source.</p>;
  }
  if (selection.type === "boundary") {
    return <p className="pane-hint">Boundaries are not comparison subjects.</p>;
  }
  if (selection.type === "shape") {
    return (
      <p className="pane-hint">
        Choose a source-bearing assembly layer in the inspector to start comparing this shape.
      </p>
    );
  }
  if (state.status === "idle" || state.status === "loading") {
    return <p className="pane-hint">Loading comparison options…</p>;
  }
  if (state.status === "refused") {
    return <p className="pane-hint">Comparison unavailable: {state.detail}</p>;
  }
  if (state.status === "failed") {
    return <p className="pane-hint">Failed to load comparison options.</p>;
  }
  if (state.options.groups.length === 0) {
    return <p className="pane-hint">No graph-backed comparison targets for this unit.</p>;
  }
  if (selected === null) {
    return (
      <div className="comparison-guidance">
        <h2>{state.options.origin.label}</h2>
        <p>Choose a graph-backed comparison target in the inspector.</p>
      </div>
    );
  }
  return <SelectedComparisonPair origin={state.options.origin} selected={selected} />;
}

function AssemblyMode({ selection }: { selection: Selection | null }) {
  if (selection?.type === "shape") {
    return <p className="pane-hint">Assembly mode does not render a shape preview yet.</p>;
  }
  return (
    <p className="pane-hint">
      Assembly mode is not built yet: assembly preview is a later capability.
    </p>
  );
}

export function CenterPane({
  mode,
  onModeChange,
  selection,
  comparisonState,
  selectedComparison,
}: {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  selection: Selection | null;
  comparisonState: ComparisonLoadState;
  selectedComparison: SelectedComparison | null;
}) {
  return (
    <div className="center-content">
      <div className="mode-bar">
        {MODES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="mode-button"
            aria-pressed={mode === entry.id}
            onClick={() => onModeChange(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div className="center-mode-body">
        {mode === "edit" && <EditMode selection={selection} />}
        {mode === "compare" && (
          <CompareMode
            selection={selection}
            state={comparisonState}
            selected={selectedComparison}
          />
        )}
        {mode === "assembly" && <AssemblyMode selection={selection} />}
      </div>
    </div>
  );
}
