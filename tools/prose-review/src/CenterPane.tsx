import { useEffect, useState } from "react";
import type { Mode, Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import { type SourceTarget, sourceTargetKey } from "./selection.ts";
import { READ_ONLY_PRESENTATION } from "./source.ts";
import { createSourceLoader, type SourceLoadState } from "./sourceLoad.ts";
import type { BoundaryKind } from "./wire.ts";

const MODES: { id: Mode; label: string }[] = [
  { id: "edit", label: "Edit" },
  { id: "compare", label: "Compare" },
  { id: "assembly", label: "Assembly" },
];

function SourceView({ target }: { target: SourceTarget }) {
  const [state, setState] = useState<SourceLoadState>({ status: "loading" });
  const [loader] = useState(() => createSourceLoader(setState));

  useEffect(() => {
    loader.select(target);
  }, [loader, target]);

  useEffect(() => () => loader.dispose(), [loader]);

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
  return <SourceView key={sourceTargetKey(selection.target)} target={selection.target} />;
}

export function CenterPane({
  mode,
  onModeChange,
  selection,
}: {
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  selection: Selection | null;
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
      {mode === "edit" && <EditMode selection={selection} />}
      {mode === "compare" && (
        <p className="pane-hint">
          Compare mode is not built yet: graph-backed comparison panes are a later capability.
        </p>
      )}
      {mode === "assembly" && (
        <p className="pane-hint">
          Assembly mode is not built yet: assembly preview is a later capability.
        </p>
      )}
    </div>
  );
}
