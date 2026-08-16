import { type DocumentLike, mutationHeaders } from "./mutationRequest.ts";
import { parseSourceSaveResult, type SourceSaveResult } from "./save.ts";
import type { SourceTarget } from "./selection.ts";
import type { FetchLike, ResponseLike } from "./sourceLoad.ts";

export type SourceSaveLoadOutcome =
  | { status: "loaded"; result: SourceSaveResult }
  | { status: "not-sent" }
  | { status: "rejected"; detail: string }
  | { status: "indeterminate" };

export type SourceSaveLoadOptions = {
  fetch?: FetchLike;
  document?: DocumentLike;
  signal?: AbortSignal;
};

async function rejectionDetail(response: ResponseLike): Promise<string> {
  try {
    const value: unknown = await response.json();
    if (typeof value === "object" && value !== null) {
      const detail = (value as Record<string, unknown>).detail;
      if (typeof detail === "string") {
        return detail;
      }
    }
  } catch {
    // The received status still proves the save handler did not mutate.
  }
  return "The save request was rejected before mutation.";
}

function matchesIdentity(result: SourceSaveResult, target: SourceTarget): boolean {
  if (result.status !== "saved") {
    return true;
  }
  return (
    result.source.unit === target.unit.id &&
    result.source.kind === target.unit.kind &&
    result.source.file.path === target.unit.path
  );
}

/** POST a reviewed complete buffer and preserve indeterminate post-dispatch outcomes. */
export async function saveUnitSource(
  target: SourceTarget,
  loadHash: string,
  text: string,
  options: SourceSaveLoadOptions = {},
): Promise<SourceSaveLoadOutcome> {
  const headers = mutationHeaders(options.document ?? globalThis.document);
  if (headers === null) {
    return { status: "not-sent" };
  }
  const fetchFn = options.fetch ?? fetch;
  try {
    const response = await fetchFn("/api/source/save", {
      method: "POST",
      headers,
      body: JSON.stringify({
        unit: target.unit.id,
        load_hash: loadHash,
        text,
      }),
      signal: options.signal,
    });
    if (response.status === 404 || response.status === 422) {
      return { status: "rejected", detail: await rejectionDetail(response) };
    }
    if (!response.ok) {
      return { status: "indeterminate" };
    }
    const result = parseSourceSaveResult(await response.json());
    if (result === null || !matchesIdentity(result, target)) {
      return { status: "indeterminate" };
    }
    return { status: "loaded", result };
  } catch {
    return { status: "indeterminate" };
  }
}
