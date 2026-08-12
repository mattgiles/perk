import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { createCorpusLinkAudit } from "./corpus-link-audit.mjs";
import remarkRewriteCorpusLinks from "./remark-rewrite-corpus-links.mjs";

// A real temp corpus: existence checks are behavioral, so the fixture is a real tree.
const corpusDir = fs.mkdtempSync(path.join(os.tmpdir(), "perk-corpus-"));
after(() => fs.rmSync(corpusDir, { recursive: true, force: true }));

for (const file of [
  "index.md",
  "how-to/index.md",
  "how-to/x.md",
  "how-to/sibling.md",
  "reference/cli.md",
  "tutorials/index.md",
  "tutorials/drive-an-objective.md",
  "explanation/page.mdx",
  "_authoring.md",
]) {
  const target = path.join(corpusDir, file);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, "# stub\n");
}

/** Run one URL through the transformer from `source` (corpus-relative); return the result. */
function rewrite(url, { source = "how-to/x.md", nodeType = "link", audit, log } = {}) {
  const auditInstance = audit ?? createCorpusLinkAudit();
  const transform = remarkRewriteCorpusLinks({
    corpusDir,
    audit: auditInstance,
    log: log ?? (() => {}),
  });
  const node =
    nodeType === "link"
      ? { type: "link", url, children: [] }
      : { type: "definition", identifier: "ref", url };
  const tree = {
    type: "root",
    children: nodeType === "link" ? [{ type: "paragraph", children: [node] }] : [node],
  };
  transform(tree, { path: path.join(corpusDir, source) });
  return node.url;
}

test("rewrites a parent-relative link with a fragment", () => {
  assert.equal(rewrite("../reference/cli.md#anchor"), "/reference/cli/#anchor");
});

test("rewrites sibling ./x.md and bare x.md forms", () => {
  assert.equal(rewrite("./sibling.md"), "/how-to/sibling/");
  assert.equal(rewrite("sibling.md"), "/how-to/sibling/");
});

test("index.md maps to its containing-directory route", () => {
  assert.equal(rewrite("index.md", { source: "how-to/x.md" }), "/how-to/");
});

test("root ../index.md maps to /", () => {
  assert.equal(rewrite("../index.md"), "/");
});

test("rewrites an .mdx target", () => {
  assert.equal(rewrite("../explanation/page.mdx"), "/explanation/page/");
});

test("rewrites a definition node's URL (defensive arm)", () => {
  assert.equal(rewrite("../reference/cli.md", { nodeType: "definition" }), "/reference/cli/");
});

test("out-of-corpus relative links pass through verbatim", () => {
  assert.equal(rewrite("../../shared/contracts.md"), "../../shared/contracts.md");
});

test("schemes, protocol-relative, site-absolute, fragment-only, and non-.md paths pass through", () => {
  for (const url of [
    "https://example.com/page.md",
    "http://example.com/",
    "mailto:someone@example.com",
    "//example.com/page.md",
    "/x.md",
    "#fragment-only",
    "../images/diagram.png",
  ]) {
    assert.equal(rewrite(url), url);
  }
});

test("_-prefixed basenames pass through verbatim (unrouted by the collection pattern)", () => {
  assert.equal(rewrite("../_authoring.md"), "../_authoring.md");
});

test("dangling in-corpus target: verbatim URL, audit record, one precise log line", () => {
  const audit = createCorpusLinkAudit();
  const logged = [];
  const url = rewrite("./missing.md", { audit, log: (line) => logged.push(line) });
  const sourcePath = path.join(corpusDir, "how-to/x.md");
  assert.equal(url, "./missing.md");
  assert.deepEqual(audit.entries(), [{ sourcePath, url: "./missing.md" }]);
  assert.equal(logged.length, 1);
  assert.ok(logged[0].includes(sourcePath));
  assert.ok(logged[0].includes("./missing.md"));
});

test("a re-transform after the file is fixed leaves the audit clean (beginFile semantics)", () => {
  const audit = createCorpusLinkAudit();
  const transform = remarkRewriteCorpusLinks({ corpusDir, audit, log: () => {} });
  const sourcePath = path.join(corpusDir, "how-to/x.md");
  const dangling = { type: "link", url: "./missing.md", children: [] };
  transform({ type: "root", children: [dangling] }, { path: sourcePath });
  assert.equal(audit.entries().length, 1);
  const fixed = { type: "link", url: "./sibling.md", children: [] };
  transform({ type: "root", children: [fixed] }, { path: sourcePath });
  assert.deepEqual(audit.entries(), []);
  assert.equal(fixed.url, "/how-to/sibling/");
});

test("pathless vfile: tree returned unchanged, audit untouched", () => {
  const audit = createCorpusLinkAudit();
  const transform = remarkRewriteCorpusLinks({ corpusDir, audit, log: () => {} });
  const node = { type: "link", url: "./sibling.md", children: [] };
  const tree = { type: "root", children: [node] };
  assert.equal(transform(tree, {}), tree);
  assert.equal(node.url, "./sibling.md");
  assert.deepEqual(audit.entries(), []);
});

test("factory validation: missing/relative/nonexistent corpusDir throws; empty dir accepted", () => {
  const audit = createCorpusLinkAudit();
  assert.throws(() => remarkRewriteCorpusLinks({ audit }), /`corpusDir` is required/);
  assert.throws(
    () => remarkRewriteCorpusLinks({ corpusDir: "relative/dir", audit }),
    /must be absolute/,
  );
  assert.throws(
    () => remarkRewriteCorpusLinks({ corpusDir: path.join(corpusDir, "nope"), audit }),
    /not an existing directory/,
  );
  assert.throws(() => remarkRewriteCorpusLinks({ corpusDir }), /`audit` is required/);
  const emptyDir = fs.mkdtempSync(path.join(os.tmpdir(), "perk-empty-corpus-"));
  try {
    remarkRewriteCorpusLinks({ corpusDir: emptyDir, audit });
  } finally {
    fs.rmSync(emptyDir, { recursive: true, force: true });
  }
});
