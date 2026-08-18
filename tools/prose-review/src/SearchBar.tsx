import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";
import type { CapabilityRef } from "./inspect.ts";
import { moveFocusInList } from "./keyboardNav.ts";
import type { SearchResult } from "./search.ts";
import {
  createSearchPanel,
  type Filters,
  NO_FILTERS,
  type PanelState,
  panelHint,
} from "./searchPanel.ts";
import { type SourceTarget, searchResultTarget } from "./selection.ts";
import {
  AUDIENCES,
  type Audience,
  PROSE_KINDS,
  PROSE_ROLES,
  type ProseKind,
  type ProseRole,
} from "./wire.ts";

function joinBreadcrumb(breadcrumb: CapabilityRef[]): string {
  return breadcrumb.map((capability) => capability.label).join(" / ");
}

// Unit and concern rows navigate to the whole unit; fragment rows preserve their
// exact composite identity. Capability/session-shape rows remain informational.
function ResultRow({
  result,
  onChoose,
}: {
  result: SearchResult;
  onChoose: (target: SourceTarget) => void;
}) {
  const content = (
    <>
      <span className="kind-badge">{result.kind}</span>
      <span className="search-result-label">{result.label}</span>
      <span className="search-result-breadcrumb">{joinBreadcrumb(result.breadcrumb)}</span>
      {result.matched.map((field) => (
        <span key={field} className="match-badge">
          {field}
        </span>
      ))}
      {result.kind === "unit" && result.unit !== null && (
        <span className="search-result-path">{result.unit.path}</span>
      )}
    </>
  );
  const target = searchResultTarget(result);
  if (target === null) {
    return <span className="search-result">{content}</span>;
  }
  return (
    <button type="button" className="search-result selectable" onClick={() => onChoose(target)}>
      {content}
    </button>
  );
}

// The PRD §5 top-bar search: a labeled query input, three closed-vocabulary filters,
// and a dropdown results panel. The panel state machine — idle/loading/loaded/failed,
// the enter-idle rule, the in-flight invalidation on idle transitions, and the fixed
// panel copy — lives in searchPanel.ts (node:test-covered); this component only
// renders its states. No debounce — the catalog is small and in-memory; latest-wins
// in the loader suppresses stale responses.
export function SearchBar({ onSelect }: { onSelect: (target: SourceTarget) => void }) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [panel, setPanel] = useState<PanelState>({ status: "idle" });
  const [controller] = useState(() => createSearchPanel(setPanel));
  const barRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => () => controller.dispose(), [controller]);

  // The search keyboard contract: Esc closes the panel and returns focus to the
  // input; ArrowDown enters the results from the input; Arrow keys step between
  // result buttons (ArrowUp from the first returns to the input). The scoped
  // `.search-panel button.search-result` query never captures the filter/Clear
  // controls, and unhandled keys (selects, Enter) keep their native behavior.
  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>): void => {
    // An active IME composition owns its keys (Esc cancels the composition,
    // arrows move through candidates) — never claim composing events.
    if (event.nativeEvent.isComposing) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      controller.close();
      inputRef.current?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    // Modified arrows keep their native behavior (e.g. Shift+ArrowDown extends
    // the input's text selection).
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) {
      return;
    }
    const bar = barRef.current;
    if (bar === null) {
      return;
    }
    const results = [...bar.querySelectorAll<HTMLElement>(".search-panel button.search-result")];
    const active = document.activeElement;
    if (active === inputRef.current) {
      if (event.key === "ArrowDown" && results.length > 0) {
        event.preventDefault();
        results[0]?.focus();
      }
      return;
    }
    // Identity lookup only — a non-HTMLElement active is simply absent (-1).
    const current = active === null ? -1 : results.indexOf(active as HTMLElement);
    if (current === -1) {
      return;
    }
    event.preventDefault();
    const next = moveFocusInList(results, active, event.key);
    if (next !== null) {
      next.focus();
    } else if (event.key === "ArrowUp" && current === 0) {
      inputRef.current?.focus();
    }
  };

  function refresh(nextQuery: string, nextFilters: Filters): void {
    setQuery(nextQuery);
    setFilters(nextFilters);
    controller.refresh(nextQuery, nextFilters);
  }

  function choose(target: SourceTarget): void {
    onSelect(target);
    controller.close();
  }

  return (
    <search ref={barRef} className="search-bar" onKeyDown={onKeyDown}>
      <label className="search-field">
        Search
        <input
          ref={inputRef}
          type="text"
          className="search-input"
          value={query}
          onChange={(event) => refresh(event.target.value, filters)}
        />
      </label>
      <label className="search-field">
        Audience
        <select
          value={filters.audience}
          onChange={(event) =>
            refresh(query, { ...filters, audience: event.target.value as Audience | "" })
          }
        >
          <option value="">All</option>
          {AUDIENCES.map((audience) => (
            <option key={audience} value={audience}>
              {audience}
            </option>
          ))}
        </select>
      </label>
      <label className="search-field">
        Role
        <select
          value={filters.role}
          onChange={(event) =>
            refresh(query, { ...filters, role: event.target.value as ProseRole | "" })
          }
        >
          <option value="">All</option>
          {PROSE_ROLES.map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
      </label>
      <label className="search-field">
        Kind
        <select
          value={filters.kind}
          onChange={(event) =>
            refresh(query, { ...filters, kind: event.target.value as ProseKind | "" })
          }
        >
          <option value="">All</option>
          {PROSE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {kind}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="search-clear" onClick={() => refresh("", NO_FILTERS)}>
        Clear
      </button>
      {panel.status !== "idle" && (
        <div className="search-panel">
          {panelHint(panel) !== null && <p className="pane-hint">{panelHint(panel)}</p>}
          {panel.status === "loaded" && panel.results.total > 0 && (
            <>
              <ul className="search-results">
                {/* Fragment ids are unique per owning unit (the snapshot invariant),
                    so unit-backed rows key on unit id + entity id. */}
                {panel.results.results.map((result) => (
                  <li
                    key={
                      result.unit === null
                        ? `${result.kind}:${result.id}`
                        : `${result.kind}:${result.unit.id}:${result.id}`
                    }
                  >
                    <ResultRow result={result} onChoose={choose} />
                  </li>
                ))}
              </ul>
              {panel.results.total > panel.results.results.length && (
                <p className="search-overflow">
                  Showing first {panel.results.results.length} of {panel.results.total} matches
                </p>
              )}
            </>
          )}
        </div>
      )}
    </search>
  );
}
