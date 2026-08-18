import assert from "node:assert/strict";
import test from "node:test";
import { CHECK_IDS } from "./src/checks.ts";
import { CATALOG_STALE_DETAIL, CONFLICT_DETAIL, parseSourceSaveResult } from "./src/save.ts";
import { createSaveReview } from "./src/saveReview.ts";
import type { UnitRef } from "./src/tree.ts";

const HASH = "0123456789abcdef".repeat(4);
const UNIT: UnitRef = {
  id: "managed:repo-agents",
  kind: "managed-prose",
  path: "AGENTS.md",
};
const SAVED = {
  status: "saved",
  source: {
    unit: UNIT.id,
    kind: UNIT.kind,
    file: { path: UNIT.path, mode: 0o6751, newline_style: "mixed", load_hash: HASH },
  },
  materialized: [
    {
      id: "ambient-index",
      relationship: "materializes-to",
      targets: [".pi/APPEND_SYSTEM.md"],
    },
  ],
  checks: [
    { id: "prose-map", command: "uv run --no-sync perk-dev prose-map check" },
    { id: "learned-docs", command: "uv run --no-sync perk learn docs-check" },
  ],
  catalog_refreshed: true,
  refresh_detail: null,
};

test("parseSourceSaveResult accepts every tagged domain outcome", () => {
  assert.deepEqual(parseSourceSaveResult(SAVED), SAVED);
  assert.deepEqual(
    parseSourceSaveResult({
      ...SAVED,
      catalog_refreshed: false,
      refresh_detail: CATALOG_STALE_DETAIL,
    }),
    { ...SAVED, catalog_refreshed: false, refresh_detail: CATALOG_STALE_DETAIL },
  );
  assert.deepEqual(
    parseSourceSaveResult({
      status: "validation-failed",
      diagnostics: [
        {
          code: "syntax-error",
          message: "invalid",
          selector: null,
          line: 2,
          column: 3,
        },
        {
          code: "selector-not-found",
          message: "missing",
          selector: "heading:missing",
          line: null,
          column: null,
        },
      ],
    }),
    {
      status: "validation-failed",
      diagnostics: [
        {
          code: "syntax-error",
          message: "invalid",
          selector: null,
          line: 2,
          column: 3,
        },
        {
          code: "selector-not-found",
          message: "missing",
          selector: "heading:missing",
          line: null,
          column: null,
        },
      ],
    },
  );
  assert.deepEqual(parseSourceSaveResult({ status: "conflict", detail: CONFLICT_DETAIL }), {
    status: "conflict",
    detail: CONFLICT_DETAIL,
  });
  assert.deepEqual(
    parseSourceSaveResult({
      status: "refused",
      reason: "unsupported-family",
      detail: "Save support has not landed for this source family.",
    }),
    {
      status: "refused",
      reason: "unsupported-family",
      detail: "Save support has not landed for this source family.",
    },
  );
});

test("parseSourceSaveResult accepts every allowlisted check id", () => {
  // Suggested checks ride the one CheckRunner vocabulary: a backend response naming
  // any allowlisted id must parse, so dropping an id from checks.ts fails here.
  const checks = CHECK_IDS.map((id) => ({ id, command: `run ${id}` }));
  const parsed = parseSourceSaveResult({ ...SAVED, checks });
  assert.ok(parsed !== null && parsed.status === "saved");
  assert.deepEqual(parsed.checks, checks);
});

test("parseSourceSaveResult rejects malformed and incoherent combinations", () => {
  const malformed = [
    null,
    {},
    { ...SAVED, source: { ...SAVED.source, unit: 1 } },
    { ...SAVED, source: { ...SAVED.source, kind: "unknown" } },
    { ...SAVED, source: { ...SAVED.source, file: { ...SAVED.source.file, mode: -1 } } },
    { ...SAVED, materialized: [{ id: "x", relationship: "runs", targets: [] }] },
    { ...SAVED, checks: [{ id: "unknown", command: "x" }] },
    { ...SAVED, catalog_refreshed: true, refresh_detail: "failure" },
    { ...SAVED, catalog_refreshed: false, refresh_detail: null },
    {
      status: "validation-failed",
      diagnostics: [
        { code: "syntax-error", message: "x", selector: "heading:x", line: 1, column: 1 },
      ],
    },
    {
      status: "validation-failed",
      diagnostics: [
        {
          code: "selector-not-found",
          message: "x",
          selector: null,
          line: null,
          column: null,
        },
      ],
    },
    { status: "refused", reason: "unknown", detail: "x" },
    { status: "conflict", detail: 1 },
    { status: "unknown" },
  ];
  for (const value of malformed) {
    assert.equal(parseSourceSaveResult(value), null);
  }
});

test("createSaveReview freezes a full-context patch and exact buffer metadata", () => {
  const loaded = "\uFEFFfirst\r\nunchanged <script>\nold 😀\rlast";
  const current = "\uFEFFfirst\r\nunchanged <script>\nnew ���\rlast\r";
  const review = createSaveReview({
    path: "docs/hostile.md",
    unit: "markdown:docs/hostile.md",
    loadHash: HASH,
    loadText: loaded,
    currentText: current,
    revision: 7,
  });

  assert.equal(Object.isFrozen(review), true);
  assert.equal(Object.isFrozen(review.loaded), true);
  assert.equal(Object.isFrozen(review.current), true);
  assert.match(review.diff, /^={10,}$/m);
  assert.match(review.diff, /--- a\/docs\/hostile\.md\tloaded/);
  assert.match(review.diff, /\+\+\+ b\/docs\/hostile\.md\tcurrent/);
  assert.match(review.diff, / unchanged <script>/);
  assert.match(review.diff, /-old 😀/);
  assert.match(review.diff, /\+new ���/);
  assert.match(review.diff, /last/);
  assert.deepEqual(review.loaded, {
    bytes: new TextEncoder().encode(loaded).byteLength,
    newlineStyle: "mixed",
    finalNewline: false,
    bom: true,
  });
  assert.deepEqual(review.current, {
    bytes: new TextEncoder().encode(current).byteLength,
    newlineStyle: "mixed",
    finalNewline: true,
    bom: true,
  });
});
