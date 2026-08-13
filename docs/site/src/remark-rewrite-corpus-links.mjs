import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createMarkdownProcessor, parseFrontmatter } from "@astrojs/markdown-remark";
import { ANCHOR_BASELINE, ESCAPE_BASELINE } from "./corpus-link-audit.mjs";
import remarkStripFirstH1 from "./remark-strip-first-h1.mjs";

// Closes the bridge spike's recorded gap: intra-corpus relative `.md`/`.mdx` links would pass
// through the external-tree bridge unrewritten (broken as site links). Links that path-resolve
// inside the corpus are rewritten onto the blueprint route convention
// (docs/design/docs-site-blueprint.md §2: corpus-relative path, minus extension,
// directory-style with trailing slash; `index` maps to its directory root); everything else —
// schemes, site-absolute, fragment-only, in-corpus non-.md paths (assets), out-of-corpus
// targets — passes through verbatim. Dangling in-corpus targets are left verbatim but recorded
// into the audit (build gate) and logged loudly (dev signal) — never thrown: the pinned glob
// loader swallows transformer throws (see corpus-link-audit.mjs).
//
// The optional `collect` callback feeds the sweep's two extra gates (anchors + the escape
// ratchet); with it absent the render-time behavior is unchanged.

const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

const ESCAPE_REASON =
  "relative link escapes docs/user-docs — link an in-corpus page or an absolute GitHub URL, " +
  "or extend the baseline only for a later-node-owned deferral";

/**
 * @param {object} options
 * @param {string} options.corpusDir absolute path of the corpus root (docs/user-docs/)
 * @param {ReturnType<import("./corpus-link-audit.mjs").createCorpusLinkAudit>} options.audit
 * @param {(line: string) => void} [options.log] dev-visible reporter (default console.error)
 * @param {(record: object) => void} [options.collect] sweep-only collector; receives
 *   `{ kind: "escape", sourcePath, url }` for each relative link resolving outside the corpus
 *   and `{ kind: "fragment", sourcePath, targetPath, url, fragment }` for each in-corpus
 *   `.md`/`.mdx` link carrying a `#fragment` (fragment-only links target the source itself)
 */
export default function remarkRewriteCorpusLinks({
  corpusDir,
  audit,
  log = console.error,
  collect,
} = {}) {
  validateCorpusDir(corpusDir);
  if (audit === undefined || audit === null) {
    throw new Error("remarkRewriteCorpusLinks: `audit` is required");
  }

  return (tree, file) => {
    // Both pinned renderers set `file.path` (markdown-remark from renderOpts.fileURL, MDX from
    // the module id); no other field is probed. A pathless render is a virtual document
    // carrying no corpus-relative links — return unchanged.
    const sourcePath = file?.path;
    if (typeof sourcePath !== "string" || sourcePath.length === 0) return tree;

    audit.beginFile(sourcePath);
    visit(tree, (node) => {
      if (node.type !== "link" && node.type !== "definition") return;
      node.url = rewriteUrl(node.url, { sourcePath, corpusDir, audit, log, collect });
    });
    return tree;
  };
}

/**
 * Corpus-dir config errors fail loudly at config-load time. An *empty* existing directory is
 * valid — there is simply nothing in-corpus to rewrite. Shared by the plugin factory and the
 * `corpusLinkGate` integration (both take the same option).
 */
export function validateCorpusDir(corpusDir) {
  if (typeof corpusDir !== "string" || corpusDir.length === 0) {
    throw new Error("corpus-links: `corpusDir` is required and must be a string");
  }
  if (!path.isAbsolute(corpusDir)) {
    throw new Error(`corpus-links: \`corpusDir\` must be absolute, got: ${corpusDir}`);
  }
  if (!fs.existsSync(corpusDir) || !fs.statSync(corpusDir).isDirectory()) {
    throw new Error(`corpus-links: \`corpusDir\` is not an existing directory: ${corpusDir}`);
  }
}

/**
 * Render-cache-independent link sweep of the WHOLE corpus: parse every routed corpus page
 * with a real markdown processor running the site pipeline (H1 strip, then this same rewrite
 * plugin), recording into `audit`
 *
 * - dangling in-corpus links (the rewrite plugin's own render-time record),
 * - in-corpus `#fragment` links whose fragment is missing from the target page's rendered
 *   heading-slug set (the same rehypeHeadingIds/github-slugger path the site uses; heading
 *   sets are post-H1-strip, so a rendered page's anchors match; fragments compare
 *   percent-decoded — browser URL semantics — and an empty `#` carries no anchor
 *   requirement), and
 * - out-of-corpus relative links (escapes) — ratcheted against `escapeBaseline` — plus any
 *   baseline entry (either baseline) that exempted zero live findings (stale — remove it).
 *
 * The build gate needs the from-disk sweep because the pinned glob loader serves cached
 * rendered entries for unchanged sources — a target-only change (deleting or renaming a
 * linked page, or removing a linked heading) never re-renders the pages that link to it, so
 * render-time auditing alone would miss the breakage. `.mdx` sources are best-effort swept
 * through the markdown parser (imports/JSX parse as prose; markdown-syntax links are still
 * checked), and an `.mdx` target's heading-slug set is likewise the markdown-parse
 * approximation — headings emitted by imported components are invisible to anchor
 * validation. Zero `.mdx` pages exist today; an MDX-faithful path is deferred until one does.
 *
 * `escapeBaseline`/`anchorBaseline` are the hermetic test seam; production call sites omit
 * them (defaults = the checked-in consts). Returns the collected `{ escapes, fragments }`.
 */
export async function sweepCorpusLinks({
  corpusDir,
  audit,
  log = console.error,
  escapeBaseline = ESCAPE_BASELINE,
  anchorBaseline = ANCHOR_BASELINE,
} = {}) {
  const escapes = [];
  const fragments = [];
  const collect = (record) => {
    (record.kind === "escape" ? escapes : fragments).push(record);
  };
  const processor = await createMarkdownProcessor({
    syntaxHighlight: false,
    remarkPlugins: [
      remarkStripFirstH1,
      [remarkRewriteCorpusLinks, { corpusDir, audit, log, collect }],
    ],
  });

  // Pass 1 — render every routed page: the plugin records dangling links / feeds the
  // collector, and each render's heading slugs accumulate into the anchor-validation map.
  /** @type {Map<string, Set<string>>} absolute file path → rendered heading slugs */
  const headingSlugs = new Map();
  for (const file of listCorpusFiles(corpusDir)) {
    const { content } = parseFrontmatter(fs.readFileSync(file, "utf8"));
    const rendered = await processor.render(content, { fileURL: pathToFileURL(file) });
    headingSlugs.set(file, new Set((rendered.metadata.headings ?? []).map((h) => h.slug)));
  }

  // Pass 2 — classify the collected records against the baselines.
  const posixRel = (absolute) => path.relative(corpusDir, absolute).split(path.sep).join("/");
  const matchIndex = (baseline, record) =>
    baseline.findIndex(
      (entry) => entry.source === posixRel(record.sourcePath) && entry.url === record.url,
    );
  const escapeHits = new Set();
  for (const record of escapes) {
    const index = matchIndex(escapeBaseline, record);
    if (index === -1) audit.record(record.sourcePath, record.url, ESCAPE_REASON);
    else escapeHits.add(index);
  }
  const anchorHits = new Set();
  for (const record of fragments) {
    if (headingSlugs.get(record.targetPath)?.has(safeDecodeFragment(record.fragment))) continue;
    const index = matchIndex(anchorBaseline, record);
    if (index === -1) {
      audit.record(
        record.sourcePath,
        record.url,
        `missing anchor '#${record.fragment}' in ${posixRel(record.targetPath)}`,
      );
    } else {
      anchorHits.add(index);
    }
  }
  for (const [baseline, hits] of [
    [escapeBaseline, escapeHits],
    [anchorBaseline, anchorHits],
  ]) {
    baseline.forEach((entry, index) => {
      if (hits.has(index)) return;
      audit.record(
        path.join(corpusDir, entry.source),
        entry.url,
        "stale baseline entry — remove it",
      );
    });
  }
  return { escapes, fragments };
}

/**
 * The routed corpus pages, mirroring the collection pattern `**\/[^_]*.{md,mdx}` (sorted):
 * `_`-prefixed basenames are unrouted authoring files, and dot-prefixed basenames — files AND
 * directories — are skipped entirely (glob never matches into hidden trees; mirrored by
 * `tests/test_user_docs_metadata.py::_walk_files`). Exported for the post-build checks and
 * the sidebar agreement guard, which must walk exactly the loader's page set.
 */
export function listCorpusFiles(dir) {
  const files = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const entryPath = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...listCorpusFiles(entryPath));
    else if (/\.mdx?$/.test(entry.name) && !entry.name.startsWith("_")) files.push(entryPath);
  }
  return files;
}

/**
 * Route mapping (blueprint §2) for a corpus-relative file path: POSIX segments, minus
 * extension, drop a trailing `index` segment, directory-style with trailing slash; root
 * `index.md` → `/`. Shared by the link rewrite and the post-build checks (which map corpus
 * files onto `dist/` output paths with it).
 */
export function corpusRoute(relPath) {
  const segments = relPath.split(path.sep);
  const last = segments.length - 1;
  segments[last] = segments[last].replace(/\.mdx?$/, "");
  if (segments[last] === "index") segments.pop();
  if (segments.length === 0) return "/";
  return `/${segments.join("/")}/`;
}

/**
 * Browser URL semantics for anchor matching: a percent-encoded fragment (`#caf%C3%A9`)
 * addresses the decoded heading id (`café`). A malformed escape falls back to the raw
 * spelling — never a throw (the sweep must report, not crash).
 */
function safeDecodeFragment(fragment) {
  try {
    return decodeURIComponent(fragment);
  } catch {
    return fragment;
  }
}

/** Hand-rolled recursive visitor over `children` — zero deps by design. */
function visit(node, fn) {
  fn(node);
  if (Array.isArray(node.children)) {
    for (const child of node.children) visit(child, fn);
  }
}

function rewriteUrl(url, { sourcePath, corpusDir, audit, log, collect }) {
  if (typeof url !== "string" || url.length === 0) return url;
  // Verbatim: schemes (https:, mailto:, …), protocol-relative, site-absolute.
  if (SCHEME_RE.test(url) || url.startsWith("//") || url.startsWith("/")) return url;
  // Fragment-only: verbatim, but collected — the anchor targets the source page itself, so
  // the sweep validates it against the source's own (post-H1-strip) heading set.
  if (url.startsWith("#")) {
    collectFragment(collect, { sourcePath, targetPath: sourcePath, url, fragment: url.slice(1) });
    return url;
  }

  // Split the ?query and/or #fragment suffix off the filesystem path part first (a query
  // would otherwise defeat the extension check below); the suffix is reattached verbatim.
  const suffixIndex = url.search(/[?#]/);
  const linkPath = suffixIndex === -1 ? url : url.slice(0, suffixIndex);
  const suffix = suffixIndex === -1 ? "" : url.slice(suffixIndex);

  // A pathless `?query#fragment` link also targets the source page itself: verbatim, but its
  // fragment (if any) is validated like a fragment-only link.
  if (linkPath === "") {
    collectFragment(collect, {
      sourcePath,
      targetPath: sourcePath,
      url,
      fragment: fragmentOf(suffix),
    });
    return url;
  }

  // Path-resolve BEFORE the extension gate: an out-of-corpus target is an escape whatever its
  // shape (directory links included); the `.md`/`.mdx` gate applies only to the in-corpus
  // rewrite (in-corpus non-.md targets — assets — are neither escapes nor rewritten).
  const target = path.resolve(path.dirname(sourcePath), linkPath);
  const relative = path.relative(corpusDir, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    // Outside the corpus → verbatim; collected for the sweep's escape ratchet.
    collect?.({ kind: "escape", sourcePath, url });
    return url;
  }
  if (!linkPath.endsWith(".md") && !linkPath.endsWith(".mdx")) return url;
  // `_`-prefixed basenames are excluded from the collection pattern → unrouted → verbatim.
  if (path.basename(target).startsWith("_")) return url;
  if (!fs.existsSync(target)) {
    // Dangling in-corpus link: leave verbatim, record for the build gate, log for dev.
    audit.record(sourcePath, url, "target file does not exist");
    log(`[perk-corpus-links] dangling in-corpus link in ${sourcePath}: ${url}`);
    return url;
  }

  collectFragment(collect, { sourcePath, targetPath: target, url, fragment: fragmentOf(suffix) });
  return corpusRoute(relative) + suffix;
}

/** The `#fragment` part of a `?query`/`#fragment` suffix ("" when absent or empty). */
function fragmentOf(suffix) {
  const fragmentIndex = suffix.indexOf("#");
  return fragmentIndex === -1 ? "" : suffix.slice(fragmentIndex + 1);
}

/**
 * Emit one fragment record — unless the fragment is empty: a bare `#` (with or without a
 * path/query) is a top-of-document link carrying no anchor requirement.
 */
function collectFragment(collect, record) {
  if (collect === undefined || record.fragment === "") return;
  collect({ kind: "fragment", ...record });
}
