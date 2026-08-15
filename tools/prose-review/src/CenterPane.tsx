import { useEffect, useState } from "react";
import type { Mode, Selection } from "./App.tsx";
import { BOUNDARY_INFO } from "./boundaries.ts";
import { parseUnitSource, type UnitSource } from "./source.ts";
import type { UnitRef } from "./tree.ts";
import type { BoundaryKind } from "./wire.ts";

const MODES: { id: Mode; label: string }[] = [
  { id: "edit", label: "Edit" },
  { id: "compare", label: "Compare" },
  { id: "assembly", label: "Assembly" },
];

// The closed source-load state machine: `refused` is the endpoint's deliberate 404
// (one of its three fixed details); `failed` is everything else — network error,
// non-ok status other than 404, a 404 without a string detail, invalid JSON, or a
// parseUnitSource rejection.
type SourceLoadState =
  | { status: "loading" }
  | { status: "loaded"; source: UnitSource }
  | { status: "refused"; detail: string }
  | { status: "failed" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

// Read-only whole-file source view, fetched on every selection change (no client
// cache — edit buffers are a later milestone). The effect is keyed on the unit id
// with a cleanup-set `cancelled` flag, so a response arriving after cleanup never
// updates state and only the current selection can win.
function SourceView({ unit }: { unit: UnitRef }) {
  const [state, setState] = useState<SourceLoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    const load = async (): Promise<void> => {
      try {
        const response = await fetch(`/api/source?unit=${encodeURIComponent(unit.id)}`);
        if (response.status === 404) {
          const body: unknown = await response.json();
          if (isRecord(body) && typeof body.detail === "string") {
            if (!cancelled) {
              setState({ status: "refused", detail: body.detail });
            }
            return;
          }
          throw new Error("404 without a string detail");
        }
        if (!response.ok) {
          throw new Error(`unexpected status ${response.status}`);
        }
        const source = parseUnitSource(await response.json());
        if (source === null) {
          throw new Error("ill-shaped source payload");
        }
        if (!cancelled) {
          setState({ status: "loaded", source });
        }
      } catch {
        if (!cancelled) {
          setState({ status: "failed" });
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [unit.id]);

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
  return (
    <div className="source-view">
      <div className="source-header">
        <span className="source-path">{source.path}</span>
        <span className="kind-badge">{source.kind}</span>
        <span className="readonly-badge">Read-only</span>
      </div>
      <pre className="source-text">{source.content}</pre>
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
  return <SourceView key={selection.unit.id} unit={selection.unit} />;
}

// The persistent mode bar + mode content. Mode switches never touch the selection,
// and the placeholders are honest about unbuilt capabilities.
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
