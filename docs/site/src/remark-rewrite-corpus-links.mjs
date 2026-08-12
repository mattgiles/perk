import fs from "node:fs";
import path from "node:path";

// Closes the bridge spike's recorded gap: intra-corpus relative `.md`/`.mdx` links would pass
// through the external-tree bridge unrewritten (broken as site links). Links that path-resolve
// inside the corpus are rewritten onto the blueprint route convention
// (docs/design/docs-site-blueprint.md §2: corpus-relative path, minus extension,
// directory-style with trailing slash; `index` maps to its directory root); everything else —
// schemes, site-absolute, fragment-only, non-.md paths, out-of-corpus targets — passes through
// verbatim. Dangling in-corpus targets are left verbatim but recorded into the audit (build
// gate) and logged loudly (dev signal) — never thrown: the pinned glob loader swallows
// transformer throws (see corpus-link-audit.mjs).

const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/**
 * @param {object} options
 * @param {string} options.corpusDir absolute path of the corpus root (docs/user-docs/)
 * @param {ReturnType<import("./corpus-link-audit.mjs").createCorpusLinkAudit>} options.audit
 * @param {(line: string) => void} [options.log] dev-visible reporter (default console.error)
 */
export default function remarkRewriteCorpusLinks({ corpusDir, audit, log = console.error } = {}) {
  // Config errors fail loudly at config-load time. An *empty* existing directory is valid —
  // the transformer simply has nothing in-corpus to rewrite.
  if (typeof corpusDir !== "string" || corpusDir.length === 0) {
    throw new Error("remarkRewriteCorpusLinks: `corpusDir` is required and must be a string");
  }
  if (!path.isAbsolute(corpusDir)) {
    throw new Error(`remarkRewriteCorpusLinks: \`corpusDir\` must be absolute, got: ${corpusDir}`);
  }
  if (!fs.existsSync(corpusDir) || !fs.statSync(corpusDir).isDirectory()) {
    throw new Error(
      `remarkRewriteCorpusLinks: \`corpusDir\` is not an existing directory: ${corpusDir}`,
    );
  }
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
      node.url = rewriteUrl(node.url, { sourcePath, corpusDir, audit, log });
    });
    return tree;
  };
}

/** Hand-rolled recursive visitor over `children` — zero deps by design. */
function visit(node, fn) {
  fn(node);
  if (Array.isArray(node.children)) {
    for (const child of node.children) visit(child, fn);
  }
}

function rewriteUrl(url, { sourcePath, corpusDir, audit, log }) {
  if (typeof url !== "string" || url.length === 0) return url;
  // Verbatim: schemes (https:, mailto:, …), protocol-relative, site-absolute, fragment-only.
  if (SCHEME_RE.test(url) || url.startsWith("//") || url.startsWith("/") || url.startsWith("#")) {
    return url;
  }

  const hashIndex = url.indexOf("#");
  const linkPath = hashIndex === -1 ? url : url.slice(0, hashIndex);
  const fragment = hashIndex === -1 ? "" : url.slice(hashIndex);
  if (!linkPath.endsWith(".md") && !linkPath.endsWith(".mdx")) return url;

  const target = path.resolve(path.dirname(sourcePath), linkPath);
  const relative = path.relative(corpusDir, target);
  // Outside the corpus → verbatim (node 2.4's link checks own those).
  if (relative.startsWith("..") || path.isAbsolute(relative)) return url;
  // `_`-prefixed basenames are excluded from the collection pattern → unrouted → verbatim.
  if (path.basename(target).startsWith("_")) return url;
  if (!fs.existsSync(target)) {
    // Dangling in-corpus link: leave verbatim, record for the build gate, log for dev.
    audit.record(sourcePath, url);
    log(`[perk-corpus-links] dangling in-corpus link in ${sourcePath}: ${url}`);
    return url;
  }

  // Route mapping (blueprint §2): corpus-relative POSIX path, minus extension, drop a trailing
  // `index` segment, directory-style with trailing slash; root index.md → `/`.
  const segments = relative.split(path.sep);
  const last = segments.length - 1;
  segments[last] = segments[last].replace(/\.mdx?$/, "");
  if (segments[last] === "index") segments.pop();
  if (segments.length === 0) return `/${fragment}`;
  return `/${segments.join("/")}/${fragment}`;
}
