// A thin `git`-shelling seam for the extension interior — the TS twin of perk/substrate/git.py.
//
// Node builtins only (so it loads cleanly under `node --test`); shells `git` via `execFileSync`,
// never with a shell. Fail-open by design: every failure degrades to the caller's `cwd` (or null
// where stated) rather than throwing — the carriers that use this must never wedge a session.
// The ONE deliberate fail-closed composition is `revalidationBracket` (documented there): a
// snapshot proof must treat an unprovable probe as drift, never as "unchanged".

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

/** Run one git command; trimmed stdout, or null on any failure (the module's fail-open style). */
function git(cwd: string, args: string[], timeout?: number): string | null {
  try {
    const out = execFileSync("git", args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      ...(timeout !== undefined ? { timeout } : {}),
    }).trim();
    return out === "" ? null : out;
  } catch {
    return null;
  }
}

/**
 * Tracked files under `pathspec` (repo-relative names), [] when none or on ANY failure (not a
 * repo, git missing — the module's fail-open style). Callers deciding trust on the result must
 * treat [] as "nothing PROVEN tracked", not proof of cleanliness.
 */
export function lsFiles(cwd: string, pathspec: string): string[] {
  const out = git(cwd, ["ls-files", "--", pathspec]);
  return out === null ? [] : out.split("\n").filter((line) => line !== "");
}

/** The bounded best-effort `git fetch` budget (ms) — see `sinceBaseSha` step 2. */
const FETCH_TIMEOUT_MS = 15_000;

/**
 * The since-base merge-base of the working tree: `merge-base(HEAD, origin/<base>)` — the sha the
 * terminal review door diffs the active worktree against. **Fail-open**: null on any failure
 * (not a repo, no such ref, git missing), never throws.
 *
 * 1. Resolve the base branch name: `base` when given; else the repo default via
 *    `git symbolic-ref --short refs/remotes/origin/HEAD` (`origin/main` → `main`).
 * 2. Best-effort `git fetch origin <branch>` with a bounded timeout — a failure (offline, no
 *    remote) is swallowed and the stale local ref is used, keeping the door usable offline (and
 *    the test scaffold network-free).
 * 3. `git merge-base HEAD origin/<branch>` → the full sha.
 */
export function sinceBaseSha(cwd: string, base: string | null | undefined): string | null {
  let branch = base ?? null;
  if (branch === null) {
    const head = git(cwd, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]);
    if (head === null) return null;
    // `origin/main` → `main` (keep anything after the first slash — branch names may carry `/`).
    branch = head.includes("/") ? head.slice(head.indexOf("/") + 1) : head;
  }
  if (branch === "") return null;
  git(cwd, ["fetch", "origin", branch], FETCH_TIMEOUT_MS);
  return git(cwd, ["merge-base", "HEAD", `origin/${branch}`]);
}

/**
 * The current HEAD sha. **Fail-open**: null on any failure — not a repo, git missing, or an
 * unborn HEAD (no commits yet), which callers treat as "no before-point to diff from".
 */
export function headSha(cwd: string): string | null {
  return git(cwd, ["rev-parse", "HEAD"]);
}

/** Whether HEAD is a positively-PROVEN unborn branch pointer: `symbolic-ref -q HEAD` resolves
 * AND `for-each-ref` proves the pointed-to ref ABSENT (an exit-0 run, empty output). `false` =
 * the ref EXISTS (a failing `headSha` read was transient, not unborn); **fail-open to null**
 * when either probe fails outright — callers must never read null as unborn. Own `execFileSync`
 * for the second probe: `git()` conflates empty output (absence — meaningful here) with
 * failure. */
export function unbornHead(cwd: string): boolean | null {
  const pointer = git(cwd, ["symbolic-ref", "-q", "HEAD"]);
  if (pointer === null) return null;
  try {
    const out = execFileSync("git", ["for-each-ref", "--format=%(refname)", pointer], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return out.trim() === "";
  } catch {
    return null;
  }
}

/**
 * Whether the working tree has anything uncommitted (`git status --porcelain`). Untracked files
 * count as dirty — deliberate: the model decides whether they belong in a commit. **Fail-open to
 * null** on any failure (not a repo, git missing) — callers must NOT conflate null with clean.
 * Own `execFileSync` rather than the `git()` helper: `git()` conflates empty output (a clean
 * tree — meaningful here) with failure.
 */
export function worktreeDirty(cwd: string): boolean | null {
  try {
    const out = execFileSync("git", ["status", "--porcelain"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return out.trim() !== "";
  } catch {
    return null;
  }
}

/**
 * Whether the index carries `assume-unchanged` (a lowercase `git ls-files -v` tag) or
 * `skip-worktree` (`S`/`s` — sparse checkouts) entries. Either bit hides worktree edits from
 * `git status --porcelain`, so a status-based cleanliness proof over a flagged index is not a
 * proof. **Fail-open to null** on any failure (not a repo, git missing) — callers must NOT
 * conflate null with "no flags". Own `execFileSync` rather than the `git()` helper: `git()`
 * conflates empty output (an empty index — meaningful here) with failure. Module-private:
 * `revalidationBracket`'s default flags probe is the one consumer (tests reach the arms through
 * the bracket — real-repo flag arms — and its `probes` seam for the null arm).
 */
function indexHidesChanges(cwd: string): boolean | null {
  try {
    const out = execFileSync("git", ["ls-files", "-v"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return out.split("\n").some((line) => {
      const tag = line[0];
      return tag !== undefined && (tag === "S" || (tag >= "a" && tag <= "z"));
    });
  } catch {
    return null;
  }
}

/**
 * The dream-snapshot revalidation bracket (contracts.md §8.65) — the module's ONE deliberately
 * **fail-closed** composition (a documented exception to the fail-open charter above): it exists
 * to PROVE the repository still matches a stamped snapshot, so an unprovable probe must read as
 * drift, never as "unchanged". The claim is END-STATE equality only — HEAD unchanged, the
 * working tree clean, and no assume-unchanged/skip-worktree index flags (which would hide edits
 * from the status probe) at the moment of the check — never mid-window byte immutability (a
 * transient modify-and-restore inside the window is invisible by design; §8.65's accepted
 * residuals). `probes` defaults to the real `headSha`/`worktreeDirty`/`indexHidesChanges` and
 * exists so tests can pin each fail-closed arm independently (from a non-repo fixture the HEAD
 * arm returns first, making the later null arms reachable only through the seam).
 */
export function revalidationBracket(
  cwd: string,
  expectedSha: string,
  probes?: {
    head?: (cwd: string) => string | null;
    dirty?: (cwd: string) => boolean | null;
    flags?: (cwd: string) => boolean | null;
  },
): { ok: boolean; detail: string | null } {
  const head = probes?.head ?? headSha;
  const dirty = probes?.dirty ?? worktreeDirty;
  const flags = probes?.flags ?? indexHidesChanges;
  const actual = head(cwd);
  if (actual === null) {
    return {
      ok: false,
      detail: "HEAD could not be resolved — cannot prove the snapshot is unchanged",
    };
  }
  if (actual !== expectedSha) {
    return { ok: false, detail: `HEAD moved from ${expectedSha} to ${actual}` };
  }
  const isDirty = dirty(cwd);
  if (isDirty === null) {
    return { ok: false, detail: "working-tree cleanliness could not be verified" };
  }
  if (isDirty) {
    return { ok: false, detail: "the working tree is no longer clean" };
  }
  const hidden = flags(cwd);
  if (hidden === null) {
    return { ok: false, detail: "index flag state could not be verified" };
  }
  if (hidden) {
    return {
      ok: false,
      detail:
        "the index carries assume-unchanged/skip-worktree flag(s) — worktree cleanliness " +
        "cannot be proven against the snapshot",
    };
  }
  return { ok: true, detail: null };
}

/**
 * The `git log --oneline <fromSha>..HEAD` listing of commits now ahead of `fromSha` — or every
 * commit (`git log --oneline HEAD`) when `fromSha` is null (HEAD was unborn at capture time).
 * This is range evidence, not proof that this command created every listed commit. **Fail-open**:
 * null on failure or when the range is empty.
 */
export function commitsSince(cwd: string, fromSha: string | null): string | null {
  const range = fromSha === null ? "HEAD" : `${fromSha}..HEAD`;
  return git(cwd, ["log", "--oneline", range]);
}
