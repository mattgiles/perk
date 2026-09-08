import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { digestSessionData } from "../substrate/sessionData.ts";
import { gitInit, scaffoldRepo } from "../testing/harness.ts";
import {
  captureSaveDestination,
  changedDestinationComponents,
  DESTINATION_COMPONENTS,
  type SaveDestination,
} from "./saveDestination.ts";

const CLAIM = { objective: "41", node: "2.3" };

function git(cwd: string, ...args: string[]): void {
  execFileSync("git", args, { cwd, stdio: "ignore" });
}

/** A git-initialised scaffold with one `origin` remote and an optional committed `[issues]` table. */
function repo(issuesToml?: string): string {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  git(cwd, "remote", "add", "origin", "https://github.com/acme/widgets.git");
  if (issuesToml !== undefined) writeIssues(cwd, issuesToml);
  return cwd;
}

function writeIssues(cwd: string, toml: string): void {
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), toml, "utf8");
}

function capture(
  cwd: string,
  claim: { objective: string; node: string } | null = CLAIM,
): SaveDestination {
  const destination = captureSaveDestination(cwd, claim);
  assert.ok(destination, "the capture is verifiable");
  return destination;
}

test("identical captures compare equal and carry every component on the GitHub arm", () => {
  const cwd = repo('[issues]\nbackend = "github"\n');
  const a = capture(cwd);
  const b = capture(cwd);
  assert.deepEqual(Object.keys(a).sort(), [...DESTINATION_COMPONENTS].sort());
  assert.deepEqual(changedDestinationComponents(a, b), []);
  for (const digest of Object.values(a)) assert.match(digest, /^sha256:[0-9a-f]{64}$/);
});

test("the incident: branch.*, user.*, an unrelated [compaction] edit and a comment change nothing", () => {
  const cwd = repo('[issues]\nbackend = "github"\n');
  const reviewed = capture(cwd);
  git(cwd, "config", "branch.tmp.remote", "origin");
  git(cwd, "config", "branch.tmp.merge", "refs/heads/tmp");
  git(cwd, "config", "user.email", "someone-else@example.com");
  writeIssues(
    cwd,
    '# routing\n[issues]\nbackend = "github"\n\n[compaction]\nobjective_threshold = 0.5\n',
  );
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), []);
  git(cwd, "config", "--unset", "branch.tmp.remote");
  git(cwd, "config", "--unset", "branch.tmp.merge");
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), []);
});

test("git remote set-url changes only `remotes`", () => {
  const cwd = repo();
  const reviewed = capture(cwd);
  git(cwd, "remote", "set-url", "origin", "https://github.com/acme/other.git");
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["remotes"]);
});

test("a gh-resolved marker on a remote changes only `remotes`", () => {
  const cwd = repo();
  const reviewed = capture(cwd);
  git(cwd, "config", "remote.origin.gh-resolved", "base");
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["remotes"]);
});

test("[issues] backend/team edits change only `issues` — basic and literal spellings alike", () => {
  const cwd = repo('[issues]\nbackend = "github"\n');
  const reviewed = capture(cwd);
  writeIssues(cwd, "[issues]\nbackend = 'github'\n");
  assert.deepEqual(
    changedDestinationComponents(reviewed, capture(cwd)),
    [],
    "same value, other quotes",
  );
  writeIssues(cwd, '[issues]\nbackend = "github"\nteam = "ENG"\n');
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues"]);
  writeIssues(cwd, "[issues]\nbackend = 'github'\nteam = 'OPS'\n");
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues"]);
});

test("a spelling the subset reader cannot vouch for widens `issues` to the whole document", () => {
  // The finding: `issues.backend = …` is valid TOML tomllib reads and the subset reader does
  // not — so a Linear→GitHub flip written that way must still move the fence.
  const cwd = repo('issues.backend = "linear"\nissues.team = "ENG"\n');
  const reviewed = capture(cwd);
  writeIssues(cwd, 'issues.backend = "github"\nissues.team = "ENG"\n');
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues"]);
  writeIssues(cwd, 'issues = { backend = "linear", team = "OPS" }\n');
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues"]);
  // Widened means over-fenced: an unrelated edit to the same document reads as `issues` too —
  // never under-fenced. (Proven documents ignore such edits: see the incident test above.)
  writeIssues(cwd, 'issues.backend = "linear"\nissues.team = "ENG"\n\n[compaction]\nx = 1\n');
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues"]);
  // The proven and widened digests of the same routing never collide (and the proven Linear
  // read now also drops the fail-safe GitHub arm's `remotes`).
  writeIssues(cwd, '[issues]\nbackend = "linear"\nteam = "ENG"\n');
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd)), ["issues", "remotes"]);
});

test("an escape in a proven-looking table widens too (the reader's unescape is not tomllib's)", () => {
  const cwd = repo('[issues]\nbackend = "github"\n');
  const reviewed = capture(cwd);
  // tomllib reads both spellings as `github`; the subset reader reads the escape verbatim. The
  // fence must not compare a value it cannot vouch for — it widens, so the edit is a change —
  // and the verbatim non-`linear` read keeps the GitHub arm, so `remotes` stays fenced.
  writeIssues(cwd, '[issues]\nbackend = "\\u0067ithub"\n');
  const widened = capture(cwd);
  assert.deepEqual(changedDestinationComponents(reviewed, widened), ["issues"]);
  assert.equal(widened.issues, capture(cwd).issues, "widened captures are stable");
  git(cwd, "remote", "set-url", "origin", "https://github.com/acme/other.git");
  assert.deepEqual(changedDestinationComponents(widened, capture(cwd)), ["remotes"]);
});

test("an unknown backend keeps the fail-safe GitHub arm (Python refuses the save; remotes stay fenced)", () => {
  const cwd = repo('[issues]\nbackend = "jira"\n');
  assert.deepEqual(Object.keys(capture(cwd)).sort(), [...DESTINATION_COMPONENTS].sort());
});

test("a different node claim (or none) changes only `node_claim`; key order is fixed", () => {
  const cwd = repo();
  const reviewed = capture(cwd);
  assert.deepEqual(
    changedDestinationComponents(reviewed, capture(cwd, { objective: "41", node: "2.4" })),
    ["node_claim"],
  );
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd, null)), ["node_claim"]);
  // Two claims with the same fields digest identically whatever property order the caller used.
  const swapped = { node: "2.3", objective: "41" } as { objective: string; node: string };
  assert.deepEqual(changedDestinationComponents(reviewed, capture(cwd, swapped)), []);
  assert.equal(
    reviewed.node_claim,
    digestSessionData(JSON.stringify({ objective: "41", node: "2.3" })),
  );
});

test("backend = linear → no `remotes` component and NO git subprocess", () => {
  const cwd = repo('[issues]\nbackend = "linear"\nteam = "ENG"\n');
  let remoteCalls = 0;
  const destination = captureSaveDestination(cwd, CLAIM, {
    issues: () => ({ kind: "keys", backend: "linear", team: "ENG" }),
    remotes: () => {
      remoteCalls++;
      return null;
    },
  });
  assert.ok(destination);
  assert.equal(remoteCalls, 0, "Linear never reads git remotes");
  assert.deepEqual(Object.keys(destination).sort(), ["issues", "node_claim"]);
  // Same through the production ports: the literal spelling selects the Linear arm too.
  writeIssues(cwd, "[issues]\nbackend = 'linear'\nteam = 'ENG'\n");
  assert.deepEqual(Object.keys(capture(cwd)).sort(), ["issues", "node_claim"]);
});

test("an unproven document with no readable backend takes the fail-safe GitHub arm", () => {
  // `issues.backend = "linear"` is invisible to the subset reader, so the arm falls back to
  // GitHub and captures remotes as well — over-capture, never a skipped component.
  const cwd = repo('issues.backend = "linear"\nissues.team = "ENG"\n');
  assert.deepEqual(Object.keys(capture(cwd)).sort(), [...DESTINATION_COMPONENTS].sort());
});

test("a GitHub-backend repo with no remotes captures `remotes` over the empty string", () => {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  const destination = capture(cwd);
  assert.equal(destination.remotes, digestSessionData(""));
});

test("a non-repo cwd on the GitHub arm is unverifiable (null); Linear still captures", () => {
  const cwd = mkdtempSync(join(tmpdir(), "perk-dest-norepo-"));
  assert.equal(captureSaveDestination(cwd, null), null);
  writeIssues(cwd, '[issues]\nbackend = "linear"\n');
  assert.ok(captureSaveDestination(cwd, null));
});

test("changedDestinationComponents: a key present on one side only counts as changed", () => {
  const withRemotes: SaveDestination = { issues: "a", node_claim: "b", remotes: "c" };
  const without: SaveDestination = { issues: "a", node_claim: "b" };
  assert.deepEqual(changedDestinationComponents(withRemotes, without), ["remotes"]);
  assert.deepEqual(changedDestinationComponents(without, withRemotes), ["remotes"]);
  assert.deepEqual(changedDestinationComponents({ issues: "x", node_claim: "b" }, withRemotes), [
    "issues",
    "remotes",
  ]);
});
