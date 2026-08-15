// The search load pipeline, extracted from the React component so node:test can
// drive it with controllable fetch stubs. There is no `refused` state: the endpoint
// has no fixed 404, and the UI can never produce a 422 (its filter values come from
// the closed wire.ts arrays). Beyond the sourceLoad.ts shape, the loader adds
// `clear()` — the explicit in-flight invalidation: it bumps the generation WITHOUT
// firing, so any response from an earlier generation is dropped and no state is
// emitted (an in-flight response must never reopen a closed panel).

import { parseSearch, type SearchResults } from "./search.ts";
import type { FetchLike } from "./sourceLoad.ts";
import type { Audience, ProseKind, ProseRole } from "./wire.ts";

export type SearchParams = {
  q: string;
  audience: Audience | null;
  role: ProseRole | null;
  kind: ProseKind | null;
};

export type SearchLoadOutcome = { status: "loaded"; results: SearchResults } | { status: "failed" };

export type SearchLoadState = { status: "loading" } | SearchLoadOutcome;

function searchUrl(params: SearchParams): string {
  const query = new URLSearchParams({ q: params.q });
  if (params.audience !== null) {
    query.set("audience", params.audience);
  }
  if (params.role !== null) {
    query.set("role", params.role);
  }
  if (params.kind !== null) {
    query.set("kind", params.kind);
  }
  return `/api/search?${query.toString()}`;
}

/** Fetch + classify one search request. Never rejects: every defect maps to a state. */
export async function loadSearch(
  params: SearchParams,
  fetchFn: FetchLike,
): Promise<SearchLoadOutcome> {
  try {
    const response = await fetchFn(searchUrl(params));
    if (!response.ok) {
      return { status: "failed" };
    }
    const results = parseSearch(await response.json());
    if (results === null) {
      return { status: "failed" };
    }
    return { status: "loaded", results };
  } catch {
    return { status: "failed" };
  }
}

export type SearchLoader = {
  select: (params: SearchParams) => void;
  clear: () => void;
  dispose: () => void;
};

/**
 * Latest-wins search loading with explicit invalidation: `select` fires a request
 * under a new generation; `clear` bumps the generation without firing (in-flight
 * responses are dropped, nothing is emitted); `dispose` is the final invalidation
 * (same mechanism).
 */
export function createSearchLoader(
  onState: (state: SearchLoadState) => void,
  fetchFn: FetchLike = fetch,
): SearchLoader {
  let current = 0;
  return {
    select(params: SearchParams): void {
      current += 1;
      const request = current;
      onState({ status: "loading" });
      void loadSearch(params, fetchFn).then((outcome) => {
        if (request === current) {
          onState(outcome);
        }
      });
    },
    clear(): void {
      current += 1;
    },
    dispose(): void {
      current += 1;
    },
  };
}
