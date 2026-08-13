import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import {
  ANCHOR_BASELINE,
  corpusLinkGate,
  createCorpusLinkAudit,
  ESCAPE_BASELINE,
} from "./corpus-link-audit.mjs";

// A real temp corpus for the gate tests: the build-done hook sweeps the corpus from disk
// (render-cache-independent), so the fixture is a real tree. The gate tests pass empty
// baselines (the hermetic test seam) — the checked-in baselines describe the REAL corpus.
const corpusDir = fs.mkdtempSync(path.join(os.tmpdir(), "perk-gate-corpus-"));
const emptyBaselines = { escapeBaseline: [], anchorBaseline: [] };
after(() => fs.rmSync(corpusDir, { recursive: true, force: true }));

function writePage(relative, body) {
  const target = path.join(corpusDir, relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, body);
}

writePage("index.md", "# Home\n\n[good](./how-to/x.md)\n");
writePage("how-to/x.md", "# X\n");

test("record/entries round-trip", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md", "target file does not exist");
  audit.record("/corpus/a.md", "../gone.md", "target file does not exist");
  audit.record("/corpus/b.md", "nowhere.md", "missing anchor '#x' in b.md");
  assert.deepEqual(audit.entries(), [
    { sourcePath: "/corpus/a.md", url: "./missing.md", reason: "target file does not exist" },
    { sourcePath: "/corpus/a.md", url: "../gone.md", reason: "target file does not exist" },
    { sourcePath: "/corpus/b.md", url: "nowhere.md", reason: "missing anchor '#x' in b.md" },
  ]);
});

test("record requires a reason", () => {
  const audit = createCorpusLinkAudit();
  assert.throws(() => audit.record("/corpus/a.md", "./missing.md"), /`reason` is required/);
  assert.throws(() => audit.record("/corpus/a.md", "./missing.md", ""), /`reason` is required/);
});

test("beginFile clears only that file's entries", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md", "target file does not exist");
  audit.record("/corpus/b.md", "nowhere.md", "target file does not exist");
  audit.beginFile("/corpus/a.md");
  assert.deepEqual(audit.entries(), [
    { sourcePath: "/corpus/b.md", url: "nowhere.md", reason: "target file does not exist" },
  ]);
});

test("assertClean is a no-op when empty", () => {
  const audit = createCorpusLinkAudit();
  audit.assertClean();
  audit.record("/corpus/a.md", "./missing.md", "target file does not exist");
  audit.beginFile("/corpus/a.md");
  audit.assertClean();
});

test("assertClean throws one error naming EVERY source path, URL, and reason", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md", "target file does not exist");
  audit.record("/corpus/b.md", "nowhere.md", "missing anchor '#x' in b.md");
  assert.throws(
    () => audit.assertClean(),
    (error) => {
      assert.ok(error instanceof Error);
      assert.match(
        error.message,
        /\/corpus\/a\.md → \.\/missing\.md \(target file does not exist\)/,
      );
      assert.match(error.message, /\/corpus\/b\.md → nowhere\.md \(missing anchor '#x' in b\.md\)/);
      return true;
    },
  );
});

test("the checked-in baselines are frozen {source, url} pairs", () => {
  for (const baseline of [ESCAPE_BASELINE, ANCHOR_BASELINE]) {
    assert.ok(Object.isFrozen(baseline));
    for (const entry of baseline) {
      assert.ok(Object.isFrozen(entry));
      assert.deepEqual(Object.keys(entry).sort(), ["source", "url"]);
      assert.ok(!entry.source.startsWith("/") && !entry.source.includes("\\"));
    }
  }
});

test("gate hook resolves silently on a clean corpus", async () => {
  const audit = createCorpusLinkAudit();
  const gate = corpusLinkGate(audit, { corpusDir, log: () => {}, ...emptyBaselines });
  assert.equal(gate.name, "perk-corpus-link-gate");
  await gate.hooks["astro:build:done"]();
  assert.deepEqual(audit.entries(), []);
});

test("gate hook rejects on a dangling link with NO prior render-time record (cache independence)", async () => {
  // Simulates the cached-render gap: the audit is empty (no page was re-rendered this build),
  // yet a target-only change left index.md pointing at a now-missing page. The hook's own
  // sweep must find it and fail the build naming the source file + URL + reason.
  writePage("index.md", "# Home\n\n[gone](./how-to/x.md)\n");
  fs.rmSync(path.join(corpusDir, "how-to/x.md"));
  try {
    const audit = createCorpusLinkAudit();
    const hook = corpusLinkGate(audit, { corpusDir, log: () => {}, ...emptyBaselines }).hooks[
      "astro:build:done"
    ];
    await assert.rejects(hook(), (error) => {
      assert.match(error.message, /index\.md → \.\/how-to\/x\.md \(target file does not exist\)/);
      return true;
    });
  } finally {
    writePage("index.md", "# Home\n\n[good](./how-to/x.md)\n");
    writePage("how-to/x.md", "# X\n");
  }
});

test("gate hook rejects on an unbaselined escape and on a dangling anchor", async () => {
  writePage("index.md", "# Home\n\n[good](./how-to/x.md#nope)\n\n[out](../elsewhere.md)\n");
  try {
    const audit = createCorpusLinkAudit();
    const hook = corpusLinkGate(audit, { corpusDir, log: () => {}, ...emptyBaselines }).hooks[
      "astro:build:done"
    ];
    await assert.rejects(hook(), (error) => {
      assert.match(error.message, /index\.md → \.\.\/elsewhere\.md \(relative link escapes/);
      assert.match(
        error.message,
        /index\.md → \.\/how-to\/x\.md#nope \(missing anchor '#nope' in how-to\/x\.md\)/,
      );
      return true;
    });
  } finally {
    writePage("index.md", "# Home\n\n[good](./how-to/x.md)\n");
  }
});

test("gate hook supersedes stale render-time records for re-swept files", async () => {
  // A dev-session leftover (or duplicate-path record) for a file whose link is now fine must
  // not fail the build: the sweep's beginFile replaces that file's entries.
  const audit = createCorpusLinkAudit();
  audit.record(
    path.join(corpusDir, "index.md"),
    "./stale-from-earlier-render.md",
    "target file does not exist",
  );
  await corpusLinkGate(audit, { corpusDir, log: () => {}, ...emptyBaselines }).hooks[
    "astro:build:done"
  ]();
  assert.deepEqual(audit.entries(), []);
});

test("gate construction validates corpusDir and audit at config-load time", () => {
  const audit = createCorpusLinkAudit();
  assert.throws(() => corpusLinkGate(audit), /`corpusDir` is required/);
  assert.throws(() => corpusLinkGate(audit, { corpusDir: "relative/dir" }), /must be absolute/);
  assert.throws(
    () => corpusLinkGate(audit, { corpusDir: path.join(corpusDir, "nope") }),
    /not an existing directory/,
  );
  assert.throws(() => corpusLinkGate(undefined, { corpusDir }), /`audit` is required/);
});
