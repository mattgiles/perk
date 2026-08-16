import assert from "node:assert/strict";
import test from "node:test";
import type { SourceTarget } from "./src/selection.ts";
import type { SourceView, UnitSource } from "./src/source.ts";
import {
  type DocumentLike,
  type FetchLike,
  loadUnitSource,
  projectUnitSource,
  type ResponseLike,
} from "./src/sourceLoad.ts";
import type { UnitRef } from "./src/tree.ts";

const HASH = "0123456789abcdef".repeat(4);
const UNIT: UnitRef = {
  id: "managed:repo-agents",
  kind: "managed-prose",
  path: "AGENTS.md",
};
const FRAGMENT = { id: "section:agents/developing-perk", label: "Developing perk" };
const TARGET: SourceTarget = { unit: UNIT, fragment: FRAGMENT };
const WHOLE_TARGET: SourceTarget = { unit: UNIT, fragment: null };
const VIEW: SourceView = {
  unit: UNIT.id,
  fragment: FRAGMENT,
  kind: UNIT.kind,
  before: "# AGENTS\r\n",
  focus: "Focused 😀\r",
  after: "tail",
  editable: true,
  read_only_reason: null,
};
const WHOLE_VIEW: SourceView = {
  unit: UNIT.id,
  fragment: null,
  kind: UNIT.kind,
  before: "",
  focus: "# AGENTS\n",
  after: "",
  editable: false,
  read_only_reason: "whole-unit",
};
const LOAD: UnitSource = {
  file: { path: UNIT.path, mode: 0o644, newline_style: "mixed", load_hash: HASH },
  view: VIEW,
};
const WHOLE_LOAD: UnitSource = { ...LOAD, view: WHOLE_VIEW };
const META: DocumentLike = {
  querySelector: (selector) =>
    selector === 'meta[name="csrf-token"]'
      ? { getAttribute: (name) => (name === "content" ? "csrf-token" : null) }
      : null,
};

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function respondInvalidJson(status: number): ResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.reject(new SyntaxError("invalid json")),
  };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

test("loadUnitSource orders and encodes GET identity and propagates AbortSignal", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const controller = new AbortController();
  const fetchFn: FetchLike = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(respond(200, LOAD));
  };
  assert.deepEqual(await loadUnitSource(TARGET, fetchFn, controller.signal), {
    status: "loaded",
    source: LOAD,
  });
  assert.deepEqual(calls, [
    {
      url: "/api/source?unit=managed%3Arepo-agents&fragment=section%3Aagents%2Fdeveloping-perk",
      init: { signal: controller.signal },
    },
  ]);

  const wholeCalls: { url: string; init: RequestInit | undefined }[] = [];
  assert.deepEqual(
    await loadUnitSource(WHOLE_TARGET, (url, init) => {
      wholeCalls.push({ url, init });
      return Promise.resolve(respond(200, WHOLE_LOAD));
    }),
    { status: "loaded", source: WHOLE_LOAD },
  );
  assert.deepEqual(wholeCalls, [
    { url: "/api/source?unit=managed%3Arepo-agents", init: { signal: undefined } },
  ]);
});

test("projectUnitSource emits deterministic POST JSON and exactly one meta CSRF header", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const controller = new AbortController();
  const fetchFn: FetchLike = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(respond(200, VIEW));
  };
  const text = "# AGENTS\r\nBrowser 😀\rtext";
  assert.deepEqual(await projectUnitSource(TARGET, text, fetchFn, controller.signal, META), {
    status: "loaded",
    view: VIEW,
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0]?.url, "/api/source/project");
  assert.deepEqual(calls[0]?.init, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Prose-Review-Csrf": "csrf-token",
    },
    body: JSON.stringify({ unit: UNIT.id, fragment: FRAGMENT.id, text }),
    signal: controller.signal,
  });
  assert.equal(
    calls[0]?.init?.body,
    `{"unit":"managed:repo-agents","fragment":"section:agents/developing-perk","text":"# AGENTS\\r\\nBrowser 😀\\rtext"}`,
  );
});

test("projectUnitSource refuses missing or empty CSRF metadata before fetch", async () => {
  let calls = 0;
  const fetchFn: FetchLike = () => {
    calls += 1;
    return Promise.resolve(respond(200, VIEW));
  };
  const absent: DocumentLike = { querySelector: () => null };
  const empty: DocumentLike = {
    querySelector: () => ({ getAttribute: () => "   " }),
  };
  assert.deepEqual(await projectUnitSource(TARGET, "text", fetchFn, undefined, absent), {
    status: "failed",
  });
  assert.deepEqual(await projectUnitSource(TARGET, "text", fetchFn, undefined, empty), {
    status: "failed",
  });
  assert.equal(calls, 0);
});

test("canonical load rejects nested file and view identity mismatches", async () => {
  const mismatches = [
    { ...LOAD, file: { ...LOAD.file, path: "other.md" } },
    { ...LOAD, view: { ...VIEW, unit: "other" } },
    { ...LOAD, view: { ...VIEW, kind: "markdown" } },
    { ...LOAD, view: { ...VIEW, fragment: { ...FRAGMENT, id: "other" } } },
    { ...LOAD, view: { ...VIEW, fragment: { ...FRAGMENT, label: "Other" } } },
    WHOLE_LOAD,
  ];
  for (const mismatch of mismatches) {
    assert.deepEqual(await loadUnitSource(TARGET, fetchOnce(respond(200, mismatch))), {
      status: "failed",
    });
  }
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(200, LOAD))), {
    status: "failed",
  });
});

test("projection rejects returned view identity mismatches", async () => {
  for (const mismatch of [
    { ...VIEW, unit: "other" },
    { ...VIEW, kind: "markdown" },
    { ...VIEW, fragment: { ...FRAGMENT, id: "other" } },
    { ...VIEW, fragment: { ...FRAGMENT, label: "Other" } },
    WHOLE_VIEW,
  ]) {
    assert.deepEqual(
      await projectUnitSource(TARGET, "text", fetchOnce(respond(200, mismatch)), undefined, META),
      { status: "failed" },
    );
  }
});

test("GET and POST map fixed 404 details to refused", async () => {
  assert.deepEqual(
    await loadUnitSource(WHOLE_TARGET, fetchOnce(respond(404, { detail: "unknown unit" }))),
    { status: "refused", detail: "unknown unit" },
  );
  assert.deepEqual(
    await projectUnitSource(
      TARGET,
      "text",
      fetchOnce(respond(404, { detail: "unknown fragment" })),
      undefined,
      META,
    ),
    { status: "refused", detail: "unknown fragment" },
  );
});

test("GET and POST fail non-ok, network, JSON, and parser errors", async () => {
  const badResponses = [
    respond(404, { detail: 7 }),
    respond(500, { detail: "boom" }),
    respondInvalidJson(200),
    respond(200, { unit: UNIT.id }),
  ];
  for (const response of badResponses) {
    assert.deepEqual(await loadUnitSource(WHOLE_TARGET, fetchOnce(response)), { status: "failed" });
    assert.deepEqual(
      await projectUnitSource(TARGET, "text", fetchOnce(response), undefined, META),
      { status: "failed" },
    );
  }
  const offline: FetchLike = () => Promise.reject(new TypeError("offline"));
  assert.deepEqual(await loadUnitSource(WHOLE_TARGET, offline), { status: "failed" });
  assert.deepEqual(await projectUnitSource(TARGET, "text", offline, undefined, META), {
    status: "failed",
  });
});
