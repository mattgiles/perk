import { useEffect, useState } from "react";
import type { CapabilityRef } from "./inspect.ts";
import type { SearchResult, SearchResults } from "./search.ts";
import { createSearchLoader, type SearchParams } from "./searchLoad.ts";
import type { UnitRef } from "./tree.ts";
import {
  AUDIENCES,
  type Audience,
  PROSE_KINDS,
  PROSE_ROLES,
  type ProseKind,
  type ProseRole,
} from "./wire.ts";

// The results panel's closed state machine: `idle` renders no panel at all. The
// loader's three states map onto the other three arms; idle is entered only through
// the explicit clear path (empty query + no filter, the Clear button, or selecting a
// result), which also invalidates any in-flight request — an in-flight response must
// never reopen a closed panel.
type PanelState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; results: SearchResults }
  | { status: "failed" };

type Filters = {
  audience: Audience | "";
  role: ProseRole | "";
  kind: ProseKind | "";
};

const NO_FILTERS: Filters = { audience: "", role: "", kind: "" };

function joinBreadcrumb(breadcrumb: CapabilityRef[]): string {
  return breadcrumb.map((capability) => capability.label).join(" / ");
}

function toParams(query: string, filters: Filters): SearchParams {
  return {
    q: query,
    audience: filters.audience === "" ? null : filters.audience,
    role: filters.role === "" ? null : filters.role,
    kind: filters.kind === "" ? null : filters.kind,
  };
}

// A unit-backed row (unit, fragment, concern) navigates to its canonical unit; a
// capability/session-shape row is informational — the tree remains the capability
// navigation surface.
function ResultRow({
  result,
  onChoose,
}: {
  result: SearchResult;
  onChoose: (unit: UnitRef) => void;
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
  const unit = result.unit;
  if (unit === null) {
    return <span className="search-result">{content}</span>;
  }
  return (
    <button type="button" className="search-result selectable" onClick={() => onChoose(unit)}>
      {content}
    </button>
  );
}

// The PRD §5 top-bar search: a labeled query input, three closed-vocabulary filters,
// and a dropdown results panel. No debounce — the catalog is small and in-memory;
// latest-wins in the loader suppresses stale responses.
export function SearchBar({ onSelect }: { onSelect: (unit: UnitRef) => void }) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [panel, setPanel] = useState<PanelState>({ status: "idle" });
  const [loader] = useState(() => createSearchLoader(setPanel));

  useEffect(() => () => loader.dispose(), [loader]);

  function refresh(nextQuery: string, nextFilters: Filters): void {
    setQuery(nextQuery);
    setFilters(nextFilters);
    const filterless =
      nextFilters.audience === "" && nextFilters.role === "" && nextFilters.kind === "";
    if (nextQuery.trim() === "" && filterless) {
      setPanel({ status: "idle" });
      loader.clear();
      return;
    }
    loader.select(toParams(nextQuery, nextFilters));
  }

  function choose(unit: UnitRef): void {
    onSelect(unit);
    setPanel({ status: "idle" });
    loader.clear();
  }

  return (
    <div className="search-bar">
      <label className="search-field">
        Search
        <input
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
          {panel.status === "loading" && <p className="pane-hint">Searching…</p>}
          {panel.status === "failed" && <p className="pane-hint">Search failed.</p>}
          {panel.status === "loaded" && panel.results.total === 0 && (
            <p className="pane-hint">No matches.</p>
          )}
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
    </div>
  );
}
