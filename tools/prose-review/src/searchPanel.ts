// The SearchBar results-panel state machine, extracted from the React component so
// node:test can drive it with controllable fetch stubs (the sourceLoad.ts extraction
// idiom). It owns the closed idle/loading/loaded/failed panel states, the enter-idle
// rule (empty trimmed query AND no active filter), the explicit in-flight
// invalidation on every idle transition, and the fixed panel copy — the component
// only renders what this module decides.

import { createSearchLoader, type SearchLoadState, type SearchParams } from "./searchLoad.ts";
import type { FetchLike } from "./sourceLoad.ts";
import type { Audience, ProseKind, ProseRole } from "./wire.ts";

export type Filters = {
  audience: Audience | "";
  role: ProseRole | "";
  kind: ProseKind | "";
};

export const NO_FILTERS: Filters = { audience: "", role: "", kind: "" };

// `idle` renders no panel at all; the loader's three states map onto the other arms.
export type PanelState = { status: "idle" } | SearchLoadState;

/**
 * The fixed panel copy for non-result states; null means the results list renders.
 * A successful response with zero matches keeps the panel open with "No matches." —
 * never an empty floating panel, never a silent idle.
 */
export function panelHint(state: PanelState): string | null {
  if (state.status === "loading") {
    return "Searching…";
  }
  if (state.status === "failed") {
    return "Search failed.";
  }
  if (state.status === "loaded" && state.results.total === 0) {
    return "No matches.";
  }
  return null;
}

function toParams(query: string, filters: Filters): SearchParams {
  return {
    q: query,
    audience: filters.audience === "" ? null : filters.audience,
    role: filters.role === "" ? null : filters.role,
    kind: filters.kind === "" ? null : filters.kind,
  };
}

export type SearchPanel = {
  refresh: (query: string, filters: Filters) => void;
  close: () => void;
  dispose: () => void;
};

/**
 * The panel controller: `refresh` re-evaluates every input/filter change — the
 * empty-query-and-no-filter combination transitions to idle AND invalidates any
 * in-flight request (a late response must never reopen a closed panel); anything
 * else fires a latest-wins search. `close` is the same idle+invalidate transition
 * (used when a result is selected); `dispose` is the final invalidation.
 */
export function createSearchPanel(
  onState: (state: PanelState) => void,
  fetchFn: FetchLike = fetch,
): SearchPanel {
  const loader = createSearchLoader(onState, fetchFn);

  function close(): void {
    onState({ status: "idle" });
    loader.clear();
  }

  return {
    refresh(query: string, filters: Filters): void {
      const filterless = filters.audience === "" && filters.role === "" && filters.kind === "";
      if (query.trim() === "" && filterless) {
        close();
        return;
      }
      loader.select(toParams(query, filters));
    },
    close,
    dispose(): void {
      loader.dispose();
    },
  };
}
