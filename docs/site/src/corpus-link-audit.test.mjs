import assert from "node:assert/strict";
import { test } from "node:test";
import { corpusLinkGate, createCorpusLinkAudit } from "./corpus-link-audit.mjs";

test("record/entries round-trip", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md");
  audit.record("/corpus/a.md", "../gone.md");
  audit.record("/corpus/b.md", "nowhere.md");
  assert.deepEqual(audit.entries(), [
    { sourcePath: "/corpus/a.md", url: "./missing.md" },
    { sourcePath: "/corpus/a.md", url: "../gone.md" },
    { sourcePath: "/corpus/b.md", url: "nowhere.md" },
  ]);
});

test("beginFile clears only that file's entries", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md");
  audit.record("/corpus/b.md", "nowhere.md");
  audit.beginFile("/corpus/a.md");
  assert.deepEqual(audit.entries(), [{ sourcePath: "/corpus/b.md", url: "nowhere.md" }]);
});

test("assertClean is a no-op when empty", () => {
  const audit = createCorpusLinkAudit();
  audit.assertClean();
  audit.record("/corpus/a.md", "./missing.md");
  audit.beginFile("/corpus/a.md");
  audit.assertClean();
});

test("assertClean throws one error naming EVERY recorded source path and URL", () => {
  const audit = createCorpusLinkAudit();
  audit.record("/corpus/a.md", "./missing.md");
  audit.record("/corpus/b.md", "nowhere.md");
  assert.throws(
    () => audit.assertClean(),
    (error) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /\/corpus\/a\.md → \.\/missing\.md/);
      assert.match(error.message, /\/corpus\/b\.md → nowhere\.md/);
      return true;
    },
  );
});

test("corpusLinkGate's build-done hook delegates to assertClean", () => {
  const audit = createCorpusLinkAudit();
  const gate = corpusLinkGate(audit);
  assert.equal(gate.name, "perk-corpus-link-gate");
  const hook = gate.hooks["astro:build:done"];
  hook(); // clean → silent
  audit.record("/corpus/a.md", "./missing.md");
  assert.throws(() => hook(), /\/corpus\/a\.md → \.\/missing\.md/);
});
