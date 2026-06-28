// A thin `git`-shelling seam for the extension interior — the TS twin of perk/substrate/git.py.
//
// Node builtins only (so it loads cleanly under `node --test`); shells `git` via `execFileSync`,
// never with a shell. Fail-open by design: every failure degrades to the caller's `cwd` (or null
// where stated) rather than throwing — the carriers that use this must never wedge a session.

import { execFileSync } from "node:child_process";
import { isAbsolute, resolve } from "node:path";

/**
 * The MAIN working tree's root, even when `cwd` is inside a linked worktree — the TS twin of
 * `main_worktree_root`. Resolves `git rev-parse --git-common-dir` (the shared `.git` of the main
 * checkout) and returns its parent (equal to the repo root in the main checkout). **Fail-open**:
 * any failure (not a repo, git missing) returns `cwd`, so a session-pointer write always has a
 * location — never throws. (Python returns `null` outside a repo; here the single caller wants
 * `main_worktree_root(cwd) or cwd`, so we fold the fallback in.)
 */
export function mainCheckoutRoot(cwd: string): string {
  let out: string;
  try {
    out = execFileSync("git", ["rev-parse", "--git-common-dir"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return cwd;
  }
  if (out === "") return cwd;
  // `--git-common-dir` may be relative (to `cwd`) or absolute; resolve then take the parent
  // (the dir containing `.git` = the main checkout root).
  const common = isAbsolute(out) ? out : resolve(cwd, out);
  return resolve(common, "..");
}
