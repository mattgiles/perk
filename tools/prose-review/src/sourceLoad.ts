// The source-view load pipeline, extracted from the React component so node:test can
// drive it with controllable fetch stubs. Two pieces: response classification (the
// closed loading/loaded/refused/failed state machine) and the latest-wins selection
// guard (a response arriving after a newer selection — or after dispose — is dropped,
// so only the current selection can win).

import { parseUnitSource, type UnitSource } from "./source.ts";

// The terminal states: `refused` is the endpoint's deliberate 404 (one of its three
// fixed details); `failed` is everything else — network error, non-ok status other
// than 404, a 404 without a string detail, invalid JSON, or a parseUnitSource
// rejection.
export type SourceLoadOutcome =
  | { status: "loaded"; source: UnitSource }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type SourceLoadState = { status: "loading" } | SourceLoadOutcome;

// The minimal structural slice of Response the loader consumes, so tests can fake
// fetch without a DOM.
export type ResponseLike = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

export type FetchLike = (url: string) => Promise<ResponseLike>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Fetch + classify one unit's source. Never rejects: every defect maps to a state. */
export async function loadUnitSource(
  unitId: string,
  fetchFn: FetchLike,
): Promise<SourceLoadOutcome> {
  try {
    const response = await fetchFn(`/api/source?unit=${encodeURIComponent(unitId)}`);
    if (response.status === 404) {
      const body: unknown = await response.json();
      if (isRecord(body) && typeof body.detail === "string") {
        return { status: "refused", detail: body.detail };
      }
      return { status: "failed" };
    }
    if (!response.ok) {
      return { status: "failed" };
    }
    const source = parseUnitSource(await response.json());
    if (source === null) {
      return { status: "failed" };
    }
    return { status: "loaded", source };
  } catch {
    return { status: "failed" };
  }
}

export type SourceLoader = {
  select: (unitId: string) => void;
  dispose: () => void;
};

/**
 * Latest-wins source loading: each select emits `loading` then its outcome — unless a
 * newer select (or dispose) superseded it first, in which case the stale outcome is
 * dropped. Out-of-order responses therefore never overwrite the current selection.
 */
export function createSourceLoader(
  onState: (state: SourceLoadState) => void,
  fetchFn: FetchLike = fetch,
): SourceLoader {
  let current = 0;
  return {
    select(unitId: string): void {
      current += 1;
      const request = current;
      onState({ status: "loading" });
      void loadUnitSource(unitId, fetchFn).then((outcome) => {
        if (request === current) {
          onState(outcome);
        }
      });
    },
    dispose(): void {
      current += 1;
    },
  };
}
