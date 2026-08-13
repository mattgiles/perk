import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { createCorpusLinkAudit } from "./corpus-link-audit.mjs";
import remarkRewriteCorpusLinks, {
  corpusRoute,
  listCorpusFiles,
  sweepCorpusLinks,
} from "./remark-rewrite-corpus-links.mjs";

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
function rewrite(url, { source = "how-to/x.md", nodeType = "link", audit, log, collect } = {}) {
  const auditInstance = audit ?? createCorpusLinkAudit();
  const transform = remarkRewriteCorpusLinks({
    corpusDir,
    audit: auditInstance,
    log: log ?? (() => {}),
    collect,
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

/** Sweep a throwaway corpus tree described as `relativePath → body` (hermetic baselines). */
async function sweep(pages, { escapeBaseline = [], anchorBaseline = [] } = {}) {
  const sweepDir = fs.mkdtempSync(path.join(os.tmpdir(), "perk-sweep-corpus-"));
  try {
    for (const [relative, body] of Object.entries(pages)) {
      const target = path.join(sweepDir, relative);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, body);
    }
    const audit = createCorpusLinkAudit();
    const logged = [];
    const collected = await sweepCorpusLinks({
      corpusDir: sweepDir,
      audit,
      log: (line) => logged.push(line),
      escapeBaseline,
      anchorBaseline,
    });
    const entries = audit.entries().map(({ sourcePath, url, reason }) => ({
      source: path.relative(sweepDir, sourcePath).split(path.sep).join("/"),
      url,
      reason,
    }));
    return { entries, logged, collected };
  } finally {
    fs.rmSync(sweepDir, { recursive: true, force: true });
  }
}

test("rewrites a parent-relative link with a fragment", () => {
  assert.equal(rewrite("../reference/cli.md#anchor"), "/reference/cli/#anchor");
});

test("preserves a query string (with and without a fragment) on rewrite", () => {
  assert.equal(
    rewrite("./sibling.md?view=compact#section"),
    "/how-to/sibling/?view=compact#section",
  );
  assert.equal(rewrite("./sibling.md?view=compact"), "/how-to/sibling/?view=compact");
  assert.equal(rewrite("../index.md?q=1"), "/?q=1");
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

test("schemes, protocol-relative, site-absolute, fragment-only, and in-corpus non-.md paths pass through", () => {
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
  assert.deepEqual(audit.entries(), [
    { sourcePath, url: "./missing.md", reason: "target file does not exist" },
  ]);
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

test("collect: escapes are emitted whatever their extension (directory links included)", () => {
  const records = [];
  assert.equal(
    rewrite("../guiding-principles/", { source: "index.md", collect: (r) => records.push(r) }),
    "../guiding-principles/",
  );
  assert.equal(
    rewrite("../../shared/contracts.md", { collect: (r) => records.push(r) }),
    "../../shared/contracts.md",
  );
  assert.deepEqual(records, [
    {
      kind: "escape",
      sourcePath: path.join(corpusDir, "index.md"),
      url: "../guiding-principles/",
    },
    {
      kind: "escape",
      sourcePath: path.join(corpusDir, "how-to/x.md"),
      url: "../../shared/contracts.md",
    },
  ]);
});

test("collect: in-corpus fragment links emit the resolved target; fragment-only targets the source", () => {
  const records = [];
  rewrite("../reference/cli.md#anchor", { collect: (r) => records.push(r) });
  rewrite("./sibling.md?view=compact#section", { collect: (r) => records.push(r) });
  rewrite("#own-heading", { collect: (r) => records.push(r) });
  const sourcePath = path.join(corpusDir, "how-to/x.md");
  assert.deepEqual(records, [
    {
      kind: "fragment",
      sourcePath,
      targetPath: path.join(corpusDir, "reference/cli.md"),
      url: "../reference/cli.md#anchor",
      fragment: "anchor",
    },
    {
      kind: "fragment",
      sourcePath,
      targetPath: path.join(corpusDir, "how-to/sibling.md"),
      url: "./sibling.md?view=compact#section",
      fragment: "section",
    },
    {
      kind: "fragment",
      sourcePath,
      targetPath: sourcePath,
      url: "#own-heading",
      fragment: "own-heading",
    },
  ]);
});

test("collect: in-corpus assets and fragmentless in-corpus links emit nothing", () => {
  const records = [];
  const collect = (r) => records.push(r);
  rewrite("../images/diagram.png", { collect });
  rewrite("./sibling.md", { collect });
  rewrite("https://example.com/page.md#frag", { collect });
  assert.deepEqual(records, []);
});

test("sweepCorpusLinks finds dangling links from disk alone (no render involved)", async () => {
  const { entries, logged, collected } = await sweep({
    "index.md":
      '---\ntitle: "Home"\n---\n\n# Home\n\n[ok](./how-to/x.md) and [gone](./missing.md)\n',
    "how-to/x.md":
      "# X\n\n```md\n[fenced example](./not-a-real-link.md)\n```\n\n[out](../../outside.md)\n",
    "how-to/_authoring.md": "# Draft\n\n[bad](./nope.md)\n",
    "page.mdx": "# P\n\n[gone too](./absent.md)\n",
  });
  // Frontmatter is tolerated; fenced example links are NOT link nodes (real parser); the
  // `_`-prefixed source is unrouted and skipped; the out-of-corpus link is an (unbaselined)
  // escape; the dangling md and mdx sources are both found.
  assert.deepEqual(entries, [
    { source: "index.md", url: "./missing.md", reason: "target file does not exist" },
    { source: "page.mdx", url: "./absent.md", reason: "target file does not exist" },
    {
      source: "how-to/x.md",
      url: "../../outside.md",
      reason:
        "relative link escapes docs/user-docs — link an in-corpus page or an absolute GitHub URL, or extend the baseline only for a later-node-owned deferral",
    },
  ]);
  assert.equal(logged.length, 2);
  assert.deepEqual(collected.escapes.length, 1);
});

test("sweep: a valid fragment (target heading exists, post-strip) passes clean", async () => {
  const { entries } = await sweep({
    "a.md": "# A\n\n[good](./b.md#real-heading) and [self](#local)\n\n## Local\n",
    "b.md": "# B\n\n## Real heading\n",
  });
  assert.deepEqual(entries, []);
});

test("sweep: a dangling fragment is recorded with the missing-anchor reason", async () => {
  const { entries } = await sweep({
    "a.md": "# A\n\n[bad](./b.md#nope)\n",
    "b.md": "# B\n\n## Real heading\n",
  });
  assert.deepEqual(entries, [
    { source: "a.md", url: "./b.md#nope", reason: "missing anchor '#nope' in b.md" },
  ]);
});

test("sweep: fragment-only links validate against the source's own POST-STRIP heading set", async () => {
  // `# Title` is stripped by the site pipeline (frontmatter title renders the H1), so
  // `#title` is NOT an anchor on the rendered page; `## Section` is.
  const { entries } = await sweep({
    "a.md": "# Title\n\n[ok](#section)\n\n[gone](#title)\n\n## Section\n",
  });
  assert.deepEqual(entries, [
    { source: "a.md", url: "#title", reason: "missing anchor '#title' in a.md" },
  ]);
});

test("sweep: baselined escape and baselined anchor pass clean (exact-pair match)", async () => {
  const { entries } = await sweep(
    {
      "index.md": "# Home\n\n[design](../design/) and [skill](./a.md#gone-heading)\n",
      "a.md": "# A\n\n## Kept heading\n",
    },
    {
      escapeBaseline: [{ source: "index.md", url: "../design/" }],
      anchorBaseline: [{ source: "index.md", url: "./a.md#gone-heading" }],
    },
  );
  assert.deepEqual(entries, []);
});

test("sweep: a baseline entry matching zero live findings is recorded as stale", async () => {
  const { entries } = await sweep(
    { "index.md": "# Home\n" },
    {
      escapeBaseline: [{ source: "index.md", url: "../removed-escape.md" }],
      anchorBaseline: [{ source: "a.md", url: "./b.md#fixed" }],
    },
  );
  assert.deepEqual(entries, [
    { source: "index.md", url: "../removed-escape.md", reason: "stale baseline entry — remove it" },
    { source: "a.md", url: "./b.md#fixed", reason: "stale baseline entry — remove it" },
  ]);
});

test("sweep: an anchor-baseline entry whose fragment now resolves is stale (ratchet)", async () => {
  const { entries } = await sweep(
    { "a.md": "# A\n\n[fixed](./b.md#real)\n", "b.md": "# B\n\n## Real\n" },
    { anchorBaseline: [{ source: "a.md", url: "./b.md#real" }] },
  );
  assert.deepEqual(entries, [
    { source: "a.md", url: "./b.md#real", reason: "stale baseline entry — remove it" },
  ]);
});

test("sweep returns the collected escapes and fragments for tests", async () => {
  const { collected } = await sweep({
    "a.md": "# A\n\n[out](../outside.md)\n\n[frag](./b.md#real)\n",
    "b.md": "# B\n\n## Real\n",
  });
  assert.equal(collected.escapes.length, 1);
  assert.equal(collected.escapes[0].url, "../outside.md");
  assert.equal(collected.fragments.length, 1);
  assert.equal(collected.fragments[0].fragment, "real");
});

test("listCorpusFiles mirrors the loader: skips dot-prefixed directories AND basenames", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "perk-list-corpus-"));
  try {
    for (const file of [
      "index.md",
      "sub/page.mdx",
      "sub/_draft.md",
      ".hidden/page.md",
      ".stray.md",
      "notes.txt",
    ]) {
      const target = path.join(dir, file);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, "# stub\n");
    }
    assert.deepEqual(listCorpusFiles(dir), [
      path.join(dir, "index.md"),
      path.join(dir, "sub/page.mdx"),
    ]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("corpusRoute maps corpus-relative paths onto blueprint §2 routes", () => {
  assert.equal(corpusRoute("index.md"), "/");
  assert.equal(corpusRoute("how-to/index.md"), "/how-to/");
  assert.equal(corpusRoute("how-to/resume-a-plan.md"), "/how-to/resume-a-plan/");
  assert.equal(corpusRoute("explanation/page.mdx"), "/explanation/page/");
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
