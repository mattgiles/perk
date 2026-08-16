import type { SourceTarget } from "./selection.ts";
import { parseUnitSource, type UnitSource } from "./source.ts";

export type SourceLoadOutcome =
  | { status: "loaded"; source: UnitSource }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type SourceLoadState = { status: "loading" } | SourceLoadOutcome;

export type ResponseLike = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

export type FetchLike = (url: string) => Promise<ResponseLike>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function matchesTarget(source: UnitSource, target: SourceTarget): boolean {
  if (source.unit !== target.unit.id) {
    return false;
  }
  if (source.fragment === null || target.fragment === null) {
    return source.fragment === null && target.fragment === null;
  }
  return (
    source.fragment.id === target.fragment.id && source.fragment.label === target.fragment.label
  );
}

/** Fetch + classify one composite source target. Never rejects. */
export async function loadUnitSource(
  target: SourceTarget,
  fetchFn: FetchLike,
): Promise<SourceLoadOutcome> {
  try {
    const params = [`unit=${encodeURIComponent(target.unit.id)}`];
    if (target.fragment !== null) {
      params.push(`fragment=${encodeURIComponent(target.fragment.id)}`);
    }
    const response = await fetchFn(`/api/source?${params.join("&")}`);
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
    if (source === null || !matchesTarget(source, target)) {
      return { status: "failed" };
    }
    return { status: "loaded", source };
  } catch {
    return { status: "failed" };
  }
}

export type SourceLoader = {
  select: (target: SourceTarget) => void;
  dispose: () => void;
};

/** Latest-wins source loading across whole-unit and fragment identities. */
export function createSourceLoader(
  onState: (state: SourceLoadState) => void,
  fetchFn: FetchLike = fetch,
): SourceLoader {
  let current = 0;
  return {
    select(target: SourceTarget): void {
      current += 1;
      const request = current;
      onState({ status: "loading" });
      void loadUnitSource(target, fetchFn).then((outcome) => {
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
