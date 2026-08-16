import {
  type ComparisonOptions,
  type ComparisonRequest,
  comparisonOptionsMatchRequest,
  parseComparisonOptions,
} from "./comparison.ts";
import type { FetchLike } from "./sourceLoad.ts";

export type ComparisonLoadOutcome =
  | { status: "loaded"; options: ComparisonOptions }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type ComparisonLoadState =
  | { status: "idle" }
  | { status: "loading" }
  | ComparisonLoadOutcome;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function comparisonUrl(request: ComparisonRequest): string {
  const query = new URLSearchParams({ unit: request.unit });
  if (request.shape !== null) {
    query.set("shape", request.shape);
    query.set("position", String(request.position));
  }
  return `/api/compare?${query.toString()}`;
}

/** Fetch and classify one whole-unit comparison origin. Never rejects. */
export async function loadComparisonOptions(
  request: ComparisonRequest,
  fetchFn: FetchLike,
): Promise<ComparisonLoadOutcome> {
  try {
    const response = await fetchFn(comparisonUrl(request));
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
    const options = parseComparisonOptions(await response.json());
    if (options === null || !comparisonOptionsMatchRequest(options, request)) {
      return { status: "failed" };
    }
    return { status: "loaded", options };
  } catch {
    return { status: "failed" };
  }
}

export type ComparisonLoader = {
  select: (request: ComparisonRequest) => void;
  clear: () => void;
  dispose: () => void;
};

/** Latest-wins comparison loading with explicit idle invalidation. */
export function createComparisonLoader(
  onState: (state: ComparisonLoadState) => void,
  fetchFn: FetchLike = fetch,
): ComparisonLoader {
  let current = 0;
  return {
    select(request: ComparisonRequest): void {
      current += 1;
      const generation = current;
      onState({ status: "loading" });
      void loadComparisonOptions(request, fetchFn).then((outcome) => {
        if (generation === current) {
          onState(outcome);
        }
      });
    },
    clear(): void {
      current += 1;
      onState({ status: "idle" });
    },
    dispose(): void {
      current += 1;
    },
  };
}
