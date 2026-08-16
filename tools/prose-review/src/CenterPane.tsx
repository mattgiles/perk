import { type Change, diffLines } from "diff";
import { useEffect, useState } from "react";
import type { Mode } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import {
  type ComparisonPlacement,
  comparisonPlacementKey,
  type SelectedComparison,
} from "./comparison.ts";
import type { ComparisonLoadState } from "./comparisonLoad.ts";
import {
  type Selection,
  type SourceTarget,
  sourceTargetKey,
  wholeUnitTarget,
} from "./selection.ts";
import { READ_ONLY_PRESENTATION, sourceCurrentText } from "./source.ts";
import { createSourceLoader, type SourceLoadState } from "./sourceLoad.ts";
import type { BoundaryKind } from "./wire.ts";

const MODES: { id: Mode; label: string }[] = [
  { id: "edit", label: "Edit" },
  { id: "compare", label: "Compare" },
  { id: "assembly", label: "Assembly" },
];

function useSourceLoad(target: SourceTarget): SourceLoadState {
  const [state, setState] = useState<SourceLoadState>({ status: "loading" });
  const [loader] = useState(() => createSourceLoader(setState));

  useEffect(() => {
    loader.select(target);
  }, [loader, target]);

  useEffect(() => () => loader.dispose(), [loader]);
  return state;
}

function SourceLoadPresentation({ state }: { state: SourceLoadState }) {
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
  const presentation =
    source.read_only_reason === null ? null : READ_ONLY_PRESENTATION[source.read_only_reason];
  return (
    <div className="source-view">
      <div className="source-header">
        <span className="source-path">{source.path}</span>
        <span className="kind-badge">{source.kind}</span>
        <span className={source.editable ? "editable-badge" : "readonly-badge"}>
          {source.editable ? "Editable range" : presentation?.badge}
        </span>
      </div>
      {presentation !== null && (
        <div className="source-readonly-explanation">
          <h2>{presentation.heading}</h2>
          <p>{presentation.explanation}</p>
        </div>
      )}
      {source.editable && (
        <div className="source-legend">
          <span className="readonly-badge">Read-only context</span>
          <span className="editable-badge">Editable range</span>
        </div>
      )}
      <pre className="source-text">
        <span className="source-context">{source.before}</span>
        <span className={source.editable ? "source-focus" : "source-readonly-focus"}>
          {source.focus}
        </span>
        <span className="source-context">{source.after}</span>
      </pre>
      {source.editable && source.focus.length === 0 && (
        <p className="empty-focus-hint">This mapped fragment is empty.</p>
      )}
    </div>
  );
}

function SourceView({ target }: { target: SourceTarget }) {
  return <SourceLoadPresentation state={useSourceLoad(target)} />;
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
  state: SourceLoadState;
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
  left: SourceLoadState;
  right: SourceLoadState;
}) {
  const chunks =
    left.status === "loaded" && right.status === "loaded"
      ? diffLines(sourceCurrentText(left.source), sourceCurrentText(right.source))
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

function useWholeUnitSource(unit: ComparisonPlacement["unit"]): SourceLoadState {
  const [target] = useState(() => wholeUnitTarget(unit));
  return useSourceLoad(target);
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
  if (origin.unit.id === target.unit.id) {
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
