import assert from "node:assert/strict";
import test from "node:test";
import type { AssemblyOptions, AssemblyRender, AssemblyRenderRequest } from "./src/assembly.ts";
import { loadAssemblyOptions, renderAssembly } from "./src/assemblyLoad.ts";
import type { WorkspaceBufferExport } from "./src/editWorkspace.ts";
import type { DocumentLike } from "./src/mutationRequest.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

const SCENARIO = {
  id: "scenario:warm",
  label: "Warm defaults",
  variables: { plan: "42" },
  include_ambient: true,
  include_tools: false,
};

const OPTIONS: AssemblyOptions = {
  assembly: "plan authoring/v1",
  scenarios: [SCENARIO],
};

const RENDER: AssemblyRender = {
  assembly: "plan-authoring",
  scenario: SCENARIO,
  presentation: { include_ambient: true, include_tools: false },
  layers: [],
};

const REQUEST: AssemblyRenderRequest = {
  assembly: "plan-authoring",
  scenario: SCENARIO.id,
  presentation: { include_ambient: null, include_tools: true },
};

const BUFFERS: WorkspaceBufferExport[] = [
  { path: "a.md", text: "alpha\n" },
  { path: "b.md", text: "beta\n" },
];

function respond(status: number, body: unknown): ResponseLike {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function fetchOnce(response: ResponseLike): FetchLike {
  return () => Promise.resolve(response);
}

function documentWithToken(token: string | null): DocumentLike {
  return {
    querySelector: (selector) =>
      selector === 'meta[name="csrf-token"]' && token !== null
        ? { getAttribute: () => token }
        : null,
  };
}

test("loadAssemblyOptions requests the exact encoded options URL", async () => {
  const urls: string[] = [];
  const fetchFn: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(respond(200, structuredClone(OPTIONS)));
  };
  assert.deepEqual(await loadAssemblyOptions("plan authoring/v1", fetchFn), {
    status: "loaded",
    options: OPTIONS,
  });
  assert.deepEqual(urls, ["/api/assembly/options?assembly=plan+authoring%2Fv1"]);
});

test("loadAssemblyOptions classifies the fixed-detail 404 as refused", async () => {
  assert.deepEqual(
    await loadAssemblyOptions("missing", fetchOnce(respond(404, { detail: "unknown assembly" }))),
    { status: "refused", detail: "unknown assembly" },
  );
  assert.deepEqual(await loadAssemblyOptions("missing", fetchOnce(respond(404, { detail: 4 }))), {
    status: "failed",
  });
  assert.deepEqual(await loadAssemblyOptions("missing", fetchOnce(respond(404, "gone"))), {
    status: "failed",
  });
});

test("loadAssemblyOptions fails non-ok, thrown, malformed, and mismatched responses", async () => {
  assert.deepEqual(
    await loadAssemblyOptions("plan authoring/v1", fetchOnce(respond(500, { detail: "boom" }))),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadAssemblyOptions("plan authoring/v1", () => Promise.reject(new TypeError("offline"))),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadAssemblyOptions(
      "plan authoring/v1",
      fetchOnce(respond(200, { assembly: "plan authoring/v1", scenarios: [] })),
    ),
    { status: "failed" },
  );
  assert.deepEqual(
    await loadAssemblyOptions("other-assembly", fetchOnce(respond(200, structuredClone(OPTIONS)))),
    { status: "failed" },
  );
});

test("renderAssembly POSTs the exact body with CSRF and JSON headers", async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const fetchFn: FetchLike = (url, init) => {
    calls.push({ url, init });
    return Promise.resolve(respond(200, structuredClone(RENDER)));
  };
  assert.deepEqual(
    await renderAssembly(REQUEST, BUFFERS, fetchFn, documentWithToken("test-token")),
    { status: "loaded", render: RENDER },
  );
  assert.equal(calls.length, 1);
  const call = calls[0];
  assert.ok(call !== undefined);
  assert.equal(call.url, "/api/assembly/render");
  assert.equal(call.init?.method, "POST");
  assert.deepEqual(call.init?.headers, {
    "Content-Type": "application/json",
    "X-Prose-Review-Csrf": "test-token",
  });
  assert.deepEqual(JSON.parse(String(call.init?.body)), {
    assembly: "plan-authoring",
    scenario: "scenario:warm",
    presentation: { include_ambient: null, include_tools: true },
    buffers: [
      { path: "a.md", text: "alpha\n" },
      { path: "b.md", text: "beta\n" },
    ],
  });
});

test("renderAssembly returns not-sent without fetching when the token is missing", async () => {
  let fetchCalls = 0;
  const fetchFn: FetchLike = () => {
    fetchCalls += 1;
    return Promise.resolve(respond(200, structuredClone(RENDER)));
  };
  assert.deepEqual(await renderAssembly(REQUEST, BUFFERS, fetchFn, documentWithToken(null)), {
    status: "not-sent",
  });
  assert.deepEqual(await renderAssembly(REQUEST, BUFFERS, fetchFn, documentWithToken("  ")), {
    status: "not-sent",
  });
  assert.deepEqual(await renderAssembly(REQUEST, BUFFERS, fetchFn, undefined), {
    status: "not-sent",
  });
  assert.equal(fetchCalls, 0);
});

for (const status of [404, 409, 422]) {
  test(`renderAssembly classifies a fixed-detail ${status} as refused`, async () => {
    const detail =
      status === 404
        ? "unknown assembly render subject"
        : status === 409
          ? "catalog stale"
          : "invalid workspace buffers";
    assert.deepEqual(
      await renderAssembly(
        REQUEST,
        BUFFERS,
        fetchOnce(respond(status, { detail })),
        documentWithToken("test-token"),
      ),
      { status: "refused", detail },
    );
    assert.deepEqual(
      await renderAssembly(
        REQUEST,
        BUFFERS,
        fetchOnce(respond(status, { detail: 9 })),
        documentWithToken("test-token"),
      ),
      { status: "failed" },
    );
  });
}

test("renderAssembly fails non-ok, thrown, malformed, and mismatched responses", async () => {
  const token = documentWithToken("test-token");
  assert.deepEqual(
    await renderAssembly(REQUEST, BUFFERS, fetchOnce(respond(500, { detail: "boom" })), token),
    { status: "failed" },
  );
  assert.deepEqual(
    await renderAssembly(REQUEST, BUFFERS, () => Promise.reject(new TypeError("offline")), token),
    { status: "failed" },
  );
  assert.deepEqual(
    await renderAssembly(REQUEST, BUFFERS, fetchOnce(respond(200, { assembly: "x" })), token),
    { status: "failed" },
  );
  assert.deepEqual(
    await renderAssembly(
      REQUEST,
      BUFFERS,
      fetchOnce(respond(200, { ...structuredClone(RENDER), assembly: "other" })),
      token,
    ),
    { status: "failed" },
  );
  assert.deepEqual(
    await renderAssembly(
      { ...REQUEST, scenario: "scenario:other" },
      BUFFERS,
      fetchOnce(respond(200, structuredClone(RENDER))),
      token,
    ),
    { status: "failed" },
  );
});
