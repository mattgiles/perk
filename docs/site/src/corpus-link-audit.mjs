// The dangling-link ledger + build gate. The pinned glob loader (astro@7.2.1) CATCHES remark
// transformer throws, logs them, and stores the entry anyway — so a throw inside the rewrite
// plugin is not a reliable build gate. Instead the plugin *records* each dangling in-corpus
// link here and the `corpusLinkGate` integration fails the build from its build-completion
// hook when the audit is non-empty — naming every source file + offending URL (precise and
// complete, not first-failure-only). Because the same loader also serves cached rendered
// entries for unchanged sources (a target-only deletion never re-renders its dependents), the
// gate does not trust render-time records alone: at build completion it re-sweeps the WHOLE
// corpus independently of the render cache (see sweepCorpusLinks) and asserts on the result.
// Dev builds never invoke build hooks; dev signal is the plugin's own loud per-link log line.

import { sweepCorpusLinks, validateCorpusDir } from "./remark-rewrite-corpus-links.mjs";

/**
 * Per-config-instance audit of dangling in-corpus links (no module-level state — testable,
 * and dev-rebuild-safe: each re-render of a file replaces that file's entries, so a fixed
 * link clears its record).
 */
export function createCorpusLinkAudit() {
  /** @type {Map<string, string[]>} sourcePath → offending URLs */
  const findings = new Map();
  return {
    /** A (re-)render of `sourcePath` starts: drop its previously recorded findings. */
    beginFile(sourcePath) {
      findings.delete(sourcePath);
    },
    /** Record one dangling in-corpus link found while rendering `sourcePath`. */
    record(sourcePath, url) {
      const urls = findings.get(sourcePath) ?? [];
      urls.push(url);
      findings.set(sourcePath, urls);
    },
    /** Flat list of every recorded finding. */
    entries() {
      return [...findings.entries()].flatMap(([sourcePath, urls]) =>
        urls.map((url) => ({ sourcePath, url })),
      );
    },
    /** No-op when clean; otherwise throw one Error listing EVERY recorded finding. */
    assertClean() {
      const entries = this.entries();
      if (entries.length === 0) return;
      const lines = entries.map(({ sourcePath, url }) => `  ${sourcePath} → ${url}`);
      throw new Error(
        `Dangling in-corpus link${entries.length === 1 ? "" : "s"} (target file does not exist):\n${lines.join("\n")}`,
      );
    },
  };
}

/**
 * Minimal Astro integration failing `astro build` when the corpus has dangling in-corpus
 * links. The build-completion hook first sweeps the whole corpus (render-cache-independent —
 * see sweepCorpusLinks), then asserts the audit clean; a hook throw rejects the build
 * pipeline, so the build exits nonzero with the audit's complete message.
 */
export function corpusLinkGate(audit, { corpusDir, log } = {}) {
  validateCorpusDir(corpusDir);
  if (audit === undefined || audit === null) {
    throw new Error("corpusLinkGate: `audit` is required");
  }
  return {
    name: "perk-corpus-link-gate",
    hooks: {
      "astro:build:done": async () => {
        await sweepCorpusLinks({ corpusDir, audit, log });
        audit.assertClean();
      },
    },
  };
}
