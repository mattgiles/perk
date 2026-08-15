// The corpus-link ledger + build gate. The pinned glob loader (astro@7.2.1) CATCHES remark
// transformer throws, logs them, and stores the entry anyway — so a throw inside the rewrite
// plugin is not a reliable build gate. Instead the plugin *records* each dangling in-corpus
// link here and the `corpusLinkGate` integration fails the build from its build-completion
// hook when the audit is non-empty — naming every source file + offending URL + reason
// (precise and complete, not first-failure-only). Because the same loader also serves cached
// rendered entries for unchanged sources (a target-only deletion never re-renders its
// dependents), the gate does not trust render-time records alone: at build completion it
// re-sweeps the WHOLE corpus independently of the render cache (see sweepCorpusLinks) — which
// also validates anchors (`#fragment` targets) and ratchets out-of-corpus escapes against the
// checked-in baselines below — and asserts on the result. Dev builds never invoke build
// hooks; dev signal is the plugin's own loud per-link log line.

import { sweepCorpusLinks, validateCorpusDir } from "./remark-rewrite-corpus-links.mjs";

/**
 * The escape ratchet's checked-in baseline: the complete current set of out-of-corpus
 * relative links, each `{ source, url }` — corpus-relative POSIX source path, link URL
 * verbatim as written — matched by exact string equality on the pair. The sweep fails the
 * build on any escape NOT listed here, and on any entry here that matches zero live escapes
 * (stale — remove it). Extend ONLY for a later-node-owned deferral; each entry names the
 * node that owns its removal.
 */
export const ESCAPE_BASELINE = Object.freeze([]);

/**
 * The dangling-anchor baseline: blueprint-recorded deferrals only (docs/design/
 * docs-site-blueprint.md §5), same `{ source, url }` shape and exact-pair matching as
 * ESCAPE_BASELINE. A genuinely new dangling anchor never joins silently — see the sweep's
 * reason text and the corpus-edit policy it points at.
 */
export const ANCHOR_BASELINE = Object.freeze([]);

/**
 * Per-config-instance audit of corpus link findings (no module-level state — testable, and
 * dev-rebuild-safe: each re-render of a file replaces that file's entries, so a fixed link
 * clears its record).
 */
export function createCorpusLinkAudit() {
  /** @type {Map<string, Array<{url: string, reason: string}>>} sourcePath → findings */
  const findings = new Map();
  return {
    /** A (re-)render of `sourcePath` starts: drop its previously recorded findings. */
    beginFile(sourcePath) {
      findings.delete(sourcePath);
    },
    /** Record one link finding for `sourcePath` (occurrence-level: duplicates append). */
    record(sourcePath, url, reason) {
      if (typeof reason !== "string" || reason.length === 0) {
        throw new Error("corpus-link-audit: `reason` is required");
      }
      const urls = findings.get(sourcePath) ?? [];
      urls.push({ url, reason });
      findings.set(sourcePath, urls);
    },
    /** Flat list of every recorded finding. */
    entries() {
      return [...findings.entries()].flatMap(([sourcePath, urls]) =>
        urls.map(({ url, reason }) => ({ sourcePath, url, reason })),
      );
    },
    /** No-op when clean; otherwise throw one Error listing EVERY recorded finding. */
    assertClean() {
      const entries = this.entries();
      if (entries.length === 0) return;
      const lines = entries.map(
        ({ sourcePath, url, reason }) => `  ${sourcePath} → ${url} (${reason})`,
      );
      throw new Error(
        `Corpus link finding${entries.length === 1 ? "" : "s"}:\n${lines.join("\n")}`,
      );
    },
  };
}

/**
 * Minimal Astro integration failing `astro build` when the corpus has dangling in-corpus
 * links, dangling anchors, or unbaselined out-of-corpus escapes. The build-completion hook
 * first sweeps the whole corpus (render-cache-independent — see sweepCorpusLinks), then
 * asserts the audit clean; a hook throw rejects the build pipeline, so the build exits
 * nonzero with the audit's complete message. `escapeBaseline`/`anchorBaseline` are the
 * hermetic test seam; production call sites omit them (defaults = the checked-in consts).
 */
export function corpusLinkGate(audit, { corpusDir, log, escapeBaseline, anchorBaseline } = {}) {
  validateCorpusDir(corpusDir);
  if (audit === undefined || audit === null) {
    throw new Error("corpusLinkGate: `audit` is required");
  }
  return {
    name: "perk-corpus-link-gate",
    hooks: {
      "astro:build:done": async () => {
        await sweepCorpusLinks({ corpusDir, audit, log, escapeBaseline, anchorBaseline });
        audit.assertClean();
      },
    },
  };
}
