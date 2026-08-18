// Never-rejecting classified transports for the two assembly endpoints (the
// comparisonLoad.ts/saveLoad.ts posture). Render never mutates, so every
// non-deterministic defect classifies as `failed` and is safely retryable — there is
// no indeterminate arm. The deterministic 404/409/422 refusals carry the server's
// fixed detail copy and cannot be repaired by an identical re-request.

import {
  type AssemblyOptions,
  type AssemblyRender,
  type AssemblyRenderRequest,
  assemblyRenderMatchesRequest,
  parseAssemblyOptions,
  parseAssemblyRender,
} from "./assembly.ts";
import type { WorkspaceBufferExport } from "./editWorkspace.ts";
import { type DocumentLike, mutationHeaders } from "./mutationRequest.ts";
import type { FetchLike, ResponseLike } from "./sourceLoad.ts";

export type AssemblyOptionsOutcome =
  | { status: "loaded"; options: AssemblyOptions }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type AssemblyRenderOutcome =
  | { status: "loaded"; render: AssemblyRender }
  | { status: "refused"; detail: string }
  | { status: "not-sent" }
  | { status: "failed" };

const REFUSAL_STATUSES: readonly number[] = [404, 409, 422];

async function refusalDetail(response: ResponseLike): Promise<string | null> {
  const body: unknown = await response.json();
  if (typeof body === "object" && body !== null) {
    const detail = (body as Record<string, unknown>).detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  return null;
}

/** GET and classify one assembly's ordered scenario fixtures. Never rejects. */
export async function loadAssemblyOptions(
  assembly: string,
  fetchFn: FetchLike = fetch,
): Promise<AssemblyOptionsOutcome> {
  try {
    const query = new URLSearchParams({ assembly });
    const response = await fetchFn(`/api/assembly/options?${query.toString()}`);
    if (response.status === 404) {
      const detail = await refusalDetail(response);
      return detail === null ? { status: "failed" } : { status: "refused", detail };
    }
    if (!response.ok) {
      return { status: "failed" };
    }
    const options = parseAssemblyOptions(await response.json());
    if (options === null || options.assembly !== assembly) {
      return { status: "failed" };
    }
    return { status: "loaded", options };
  } catch {
    return { status: "failed" };
  }
}

/** POST and classify one guarded assembly render over the exported workspace. Never rejects. */
export async function renderAssembly(
  request: AssemblyRenderRequest,
  buffers: WorkspaceBufferExport[],
  fetchFn: FetchLike = fetch,
  documentRoot: DocumentLike | undefined = globalThis.document,
): Promise<AssemblyRenderOutcome> {
  const headers = mutationHeaders(documentRoot);
  if (headers === null) {
    return { status: "not-sent" };
  }
  try {
    const response = await fetchFn("/api/assembly/render", {
      method: "POST",
      headers,
      body: JSON.stringify({
        assembly: request.assembly,
        scenario: request.scenario,
        presentation: {
          include_ambient: request.presentation.include_ambient,
          include_tools: request.presentation.include_tools,
        },
        buffers,
      }),
    });
    if (REFUSAL_STATUSES.includes(response.status)) {
      const detail = await refusalDetail(response);
      return detail === null ? { status: "failed" } : { status: "refused", detail };
    }
    if (!response.ok) {
      return { status: "failed" };
    }
    const render = parseAssemblyRender(await response.json());
    if (render === null || !assemblyRenderMatchesRequest(render, request)) {
      return { status: "failed" };
    }
    return { status: "loaded", render };
  } catch {
    return { status: "failed" };
  }
}
