// The inspector load pipeline, extracted from the React component so node:test can
// drive it with controllable fetch stubs (the sourceLoad.ts pattern — the small
// duplication is deliberate: one module per endpoint is the shipped idiom). Two
// pieces: response classification (the closed loading/loaded/refused/failed state
// machine) and the latest-wins selection guard.

import { parseUnitInspect, type UnitInspect } from "./inspect.ts";
import type { FetchLike } from "./sourceLoad.ts";

// The terminal states: `refused` is the endpoint's deliberate 404 (its one fixed
// detail); `failed` is everything else — network error, non-ok status other than
// 404, a 404 without a string detail, invalid JSON, or a parseUnitInspect rejection.
export type InspectLoadOutcome =
  | { status: "loaded"; detail: UnitInspect }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type InspectLoadState = { status: "loading" } | InspectLoadOutcome;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Fetch + classify one unit's relationships. Never rejects: every defect maps to a state. */
export async function loadUnitInspect(
  unitId: string,
  fetchFn: FetchLike,
): Promise<InspectLoadOutcome> {
  try {
    const response = await fetchFn(`/api/inspect?unit=${encodeURIComponent(unitId)}`);
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
    const detail = parseUnitInspect(await response.json());
    if (detail === null) {
      return { status: "failed" };
    }
    return { status: "loaded", detail };
  } catch {
    return { status: "failed" };
  }
}

export type InspectLoader = {
  select: (unitId: string) => void;
  dispose: () => void;
};

/**
 * Latest-wins inspect loading: each select emits `loading` then its outcome — unless
 * a newer select (or dispose) superseded it first, in which case the stale outcome is
 * dropped. Out-of-order responses therefore never overwrite the current selection.
 */
export function createInspectLoader(
  onState: (state: InspectLoadState) => void,
  fetchFn: FetchLike = fetch,
): InspectLoader {
  let current = 0;
  return {
    select(unitId: string): void {
      current += 1;
      const request = current;
      onState({ status: "loading" });
      void loadUnitInspect(unitId, fetchFn).then((outcome) => {
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
