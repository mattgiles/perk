import assert from "node:assert/strict";
import test from "node:test";
import type { DocumentLike } from "./src/mutationRequest.ts";
import { saveUnitSource } from "./src/saveLoad.ts";
import type { SourceTarget } from "./src/selection.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";
import type { UnitRef } from "./src/tree.ts";

const HASH = "0123456789abcdef".repeat(4);
const UNIT: UnitRef = {
  id: "managed:repo-agents",
  kind: "managed-prose",
  path: "AGENTS.md",
};
const TARGET: SourceTarget = { unit: UNIT, fragment: null };
const META: DocumentLike = {
  querySelector: (selector) =>
    selector === 'meta[name="csrf-token"]'
      ? { getAttribute: (name) => (name === "content" ? "csrf-token" : null) }
      : null,
};
const SAVED = {
  status: "saved",
  source: {
    unit: UNIT.id,
    kind: UNIT.kind,
    file: { path: UNIT.path, mode: 0o644, newline_style: "lf", load_hash: HASH },
  },
  materialized: [],
  checks: [{ id: "prose-map", command: "perk-dev prose-map check" }],
  catalog_refreshed: true,
  refresh_detail: null,
};

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function invalidJson(status: number): ResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("invalid json")),
  };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

test("saveUnitSource sends exact ordered reviewed-buffer JSON with shared CSRF", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const controller = new AbortController();
  const text = "complete 😀\r\nbuffer";
  const outcome = await saveUnitSource(TARGET, HASH, text, {
    document: META,
    signal: controller.signal,
    fetch: (url, init) => {
      calls.push({ url, init });
      return Promise.resolve(respond(200, SAVED));
    },
  });

  assert.deepEqual(outcome, { status: "loaded", result: SAVED });
  assert.deepEqual(calls, [
    {
      url: "/api/source/save",
      init: {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Prose-Review-Csrf": "csrf-token",
        },
        body: `{"unit":"managed:repo-agents","load_hash":"${HASH}","text":"complete 😀\\r\\nbuffer"}`,
        signal: controller.signal,
      },
    },
  ]);
});

test("saveUnitSource classifies missing CSRF as not-sent without dispatch", async () => {
  let calls = 0;
  const outcome = await saveUnitSource(TARGET, HASH, "text", {
    document: { querySelector: () => null },
    fetch: () => {
      calls += 1;
      return Promise.resolve(respond(200, SAVED));
    },
  });
  assert.deepEqual(outcome, { status: "not-sent" });
  assert.equal(calls, 0);
});

test("saveUnitSource classifies received 404 and 422 as determinate rejection", async () => {
  assert.deepEqual(
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(respond(404, { detail: "unknown unit" })),
    }),
    { status: "rejected", detail: "unknown unit" },
  );
  assert.deepEqual(
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(invalidJson(422)),
    }),
    { status: "rejected", detail: "The save request was rejected before mutation." },
  );
});

test("saveUnitSource preserves every post-dispatch uncertainty as indeterminate", async () => {
  const outcomes = [
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: () => Promise.reject(new TypeError("network lost")),
    }),
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(respond(500, { detail: "boom" })),
    }),
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(invalidJson(200)),
    }),
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(respond(200, { status: "saved" })),
    }),
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(respond(200, { ...SAVED, source: { ...SAVED.source, unit: "other" } })),
    }),
    await saveUnitSource(TARGET, HASH, "text", {
      document: META,
      fetch: fetchOnce(
        respond(200, {
          ...SAVED,
          source: { ...SAVED.source, file: { ...SAVED.source.file, path: "other.md" } },
        }),
      ),
    }),
  ];
  assert.deepEqual(
    outcomes,
    outcomes.map(() => ({ status: "indeterminate" })),
  );
});

test("saveUnitSource accepts all valid non-saved tagged outcomes without identity fields", async () => {
  for (const result of [
    { status: "validation-failed", diagnostics: [] },
    { status: "conflict", detail: "changed" },
    { status: "refused", reason: "unsafe-path", detail: "unsafe" },
  ]) {
    assert.deepEqual(
      await saveUnitSource(TARGET, HASH, "text", {
        document: META,
        fetch: fetchOnce(respond(200, result)),
      }),
      { status: "loaded", result },
    );
  }
});
