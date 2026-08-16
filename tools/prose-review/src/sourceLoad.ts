import type { SourceTarget } from "./selection.ts";
import { parseSourceView, parseUnitSource, type SourceView, type UnitSource } from "./source.ts";

export type SourceLoadOutcome =
  | { status: "loaded"; source: UnitSource }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type SourceProjectionOutcome =
  | { status: "loaded"; view: SourceView }
  | { status: "refused"; detail: string }
  | { status: "failed" };

export type ResponseLike = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};

export type FetchLike = (url: string, init?: RequestInit) => Promise<ResponseLike>;

export type DocumentLike = {
  querySelector: (selector: string) => { getAttribute: (name: string) => string | null } | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function matchesTarget(source: SourceView, target: SourceTarget): boolean {
  if (source.unit !== target.unit.id || source.kind !== target.unit.kind) {
    return false;
  }
  if (source.fragment === null || target.fragment === null) {
    return source.fragment === null && target.fragment === null;
  }
  return (
    source.fragment.id === target.fragment.id && source.fragment.label === target.fragment.label
  );
}

async function refused(
  response: ResponseLike,
): Promise<{ status: "refused"; detail: string } | null> {
  const body: unknown = await response.json();
  if (isRecord(body) && typeof body.detail === "string") {
    return { status: "refused", detail: body.detail };
  }
  return null;
}

/** GET and classify one canonical nested source load. Never rejects. */
export async function loadUnitSource(
  target: SourceTarget,
  fetchFn: FetchLike = fetch,
  signal?: AbortSignal,
): Promise<SourceLoadOutcome> {
  try {
    const params = [`unit=${encodeURIComponent(target.unit.id)}`];
    if (target.fragment !== null) {
      params.push(`fragment=${encodeURIComponent(target.fragment.id)}`);
    }
    const response = await fetchFn(`/api/source?${params.join("&")}`, { signal });
    if (response.status === 404) {
      return (await refused(response)) ?? { status: "failed" };
    }
    if (!response.ok) {
      return { status: "failed" };
    }
    const source = parseUnitSource(await response.json());
    if (
      source === null ||
      source.file.path !== target.unit.path ||
      !matchesTarget(source.view, target)
    ) {
      return { status: "failed" };
    }
    return { status: "loaded", source };
  } catch {
    return { status: "failed" };
  }
}

function csrfToken(documentRoot: DocumentLike | undefined): string | null {
  const token = documentRoot?.querySelector('meta[name="csrf-token"]')?.getAttribute("content");
  return token !== undefined && token !== null && token.trim().length > 0 ? token : null;
}

/** POST and classify one stateless projection over browser-supplied text. Never rejects. */
export async function projectUnitSource(
  target: SourceTarget,
  text: string,
  fetchFn: FetchLike = fetch,
  signal?: AbortSignal,
  documentRoot: DocumentLike | undefined = globalThis.document,
): Promise<SourceProjectionOutcome> {
  const token = csrfToken(documentRoot);
  if (token === null) {
    return { status: "failed" };
  }
  try {
    const response = await fetchFn("/api/source/project", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Prose-Review-Csrf": token,
      },
      body: JSON.stringify({
        unit: target.unit.id,
        fragment: target.fragment?.id ?? null,
        text,
      }),
      signal,
    });
    if (response.status === 404) {
      return (await refused(response)) ?? { status: "failed" };
    }
    if (!response.ok) {
      return { status: "failed" };
    }
    const view = parseSourceView(await response.json());
    if (view === null || !matchesTarget(view, target)) {
      return { status: "failed" };
    }
    return { status: "loaded", view };
  } catch {
    return { status: "failed" };
  }
}
