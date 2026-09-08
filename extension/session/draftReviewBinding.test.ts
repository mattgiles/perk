import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { handoffPath } from "../substrate/cache.ts";
import { draftReviewGitContext } from "../substrate/git.ts";
import { configFile, localConfigFile } from "../substrate/paths.ts";
import { openMemoryWorkflowSession } from "../testing/memoryWorkflowSession.ts";
import {
  captureDraftReviewBinding,
  type DraftReviewBindingPorts,
  projectReviewHandoff,
  type TargetProjection,
  targetEncoding,
} from "./draftReviewBinding.ts";
import {
  digestSessionData,
  REFINEMENT_CONTEXT_ARTIFACT,
  type WorkflowSession,
} from "./workflowSession.ts";

const emptyDigest = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const projection: TargetProjection = {
  worktree_root: "/repo",
  git_dir: "/repo/.git",
  git_common_dir: "/repo/.git",
  run_id: "RID",
  subject: "plan",
  warm_node_claim: null,
  handoff: null,
  files: {
    main_config: { state: "absent" },
    worktree_config: { state: "absent" },
    worktree_local: { state: "absent" },
  },
  git_config_digest: emptyDigest,
  environment: { GH_REPO: null, GH_HOST: null },
};
const encoding =
  'perk/draft-review-target/v1\n{"worktree_root":"/repo","git_dir":"/repo/.git","git_common_dir":"/repo/.git","run_id":"RID","subject":"plan","warm_node_claim":null,"handoff":null,"files":{"main_config":{"state":"absent"},"worktree_config":{"state":"absent"},"worktree_local":{"state":"absent"}},"git_config_digest":"sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","environment":{"GH_REPO":null,"GH_HOST":null}}';

function setup(subject: "plan" | "objective" | "gist" | "refinement" = "plan") {
  const session: WorkflowSession = openMemoryWorkflowSession({ runId: "RID" });
  session.draftReviewContext = () => ({ ok: true, runId: "RID", subject, warmNodeClaim: null });
  const files = new Map<string, Uint8Array>();
  const reads: string[] = [];
  let env: { GH_REPO?: string; GH_HOST?: string } = {};
  let configBytes: Uint8Array = new Uint8Array();
  const ports: DraftReviewBindingPorts = {
    git: () => ({
      worktreeRoot: "/repo",
      gitDir: "/repo/.git",
      gitCommonDir: "/repo/.git",
      configBytes,
    }),
    read(path) {
      reads.push(path);
      return files.get(path) ?? null;
    },
    environment: () => env,
  };
  const capture = () => {
    const result = captureDraftReviewBinding("/repo", session, ports);
    assert.ok(result.ok, JSON.stringify(result));
    return result.binding.digest;
  };
  return {
    session,
    ports,
    files,
    reads,
    capture,
    env(value: typeof env) {
      env = value;
    },
    git(bytes: string | Uint8Array) {
      configBytes = typeof bytes === "string" ? Buffer.from(bytes) : bytes;
    },
  };
}
test("target encoding and digest are independently pinned, including nested key order", () => {
  assert.equal(targetEncoding(projection), encoding);
  assert.equal(
    digestSessionData(encoding),
    "sha256:33e357e7ed77d5adbcfc0df41491deda7b152aede4858bdd2be270302d874163",
  );
  const reordered = {
    ...projection,
    environment: { GH_HOST: null, GH_REPO: null },
    files: {
      worktree_local: { state: "absent" as const },
      worktree_config: { state: "absent" as const },
      main_config: { state: "absent" as const },
    },
  };
  assert.equal(targetEncoding(reordered), encoding);
  const f = setup();
  assert.equal(f.capture(), digestSessionData(encoding));
  assert.deepEqual(f.reads, [
    handoffPath("/repo", "RID"),
    configFile("/repo"),
    configFile("/repo"),
    localConfigFile("/repo"),
  ]);
});

test("file/env/git projections preserve empty, absent, exact bytes and non-UTF8 git output", () => {
  const f = setup();
  const absent = f.capture();
  f.files.set(configFile("/repo"), Buffer.alloc(0));
  const emptyFile = f.capture();
  assert.notEqual(emptyFile, absent);
  f.files.set(configFile("/repo"), Buffer.from(" \n雪\n"));
  assert.notEqual(f.capture(), emptyFile);
  f.files.clear();
  f.env({ GH_REPO: "" });
  assert.notEqual(f.capture(), absent);
  const emptyEnv = f.capture();
  f.env({ GH_REPO: " " });
  assert.notEqual(f.capture(), emptyEnv);
  f.env({ GH_HOST: "" });
  assert.notEqual(f.capture(), emptyEnv);
  f.env({});
  f.git("file:/global\0include.path\n/path\0");
  const included = f.capture();
  assert.notEqual(included, absent);
  f.git("file:/global\0include.path\n/path\0\n");
  assert.notEqual(f.capture(), included);
  f.git(new Uint8Array([0xff, 0]));
  const invalidUtf8 = f.capture();
  f.git(new Uint8Array([0xef, 0xbf, 0xbd, 0]));
  assert.notEqual(f.capture(), invalidUtf8);
});

test("handoff projection ignores unrelated fields but retains every relevant byte, order and duplicate", () => {
  assert.deepEqual(projectReviewHandoff({ run_id: "RID", unrelated: "ignore" }, "plan", "RID"), {
    objective_id: null,
    node_id: null,
    adopt_from: null,
    consumed_learn: [],
  });
  assert.deepEqual(
    projectReviewHandoff(
      {
        run_id: "RID",
        objective_id: " 雪 ",
        node_id: " 1.1 ",
        adopt_from: null,
        consumed_learn: ["a", "a", " b "],
      },
      "plan",
      "RID",
    ),
    { objective_id: " 雪 ", node_id: " 1.1 ", adopt_from: null, consumed_learn: ["a", "a", " b "] },
  );
  assert.deepEqual(
    projectReviewHandoff(
      { run_id: "RID", adopt_from: " x ", supersedes: null, objective_id: false },
      "objective",
      "RID",
    ),
    { adopt_from: " x ", supersedes: null },
  );
  assert.deepEqual(
    projectReviewHandoff({ run_id: "RID", gist_scope: "objective" }, "gist", "RID"),
    { gist_scope: "objective" },
  );
  for (const subject of ["plan", "objective", "gist"] as const) {
    for (const raw of [null, [], {}, { run_id: "WRONG" }])
      assert.throws(() => projectReviewHandoff(raw, subject, "RID"));
  }
  for (const key of ["objective_id", "node_id", "adopt_from"])
    for (const value of ["", "  ", false, 42, []])
      assert.throws(() => projectReviewHandoff({ run_id: "RID", [key]: value }, "plan", "RID"));
  for (const value of [null, {}, [""], [42]])
    assert.throws(() =>
      projectReviewHandoff({ run_id: "RID", consumed_learn: value }, "plan", "RID"),
    );
  for (const key of ["adopt_from", "supersedes"])
    assert.throws(() => projectReviewHandoff({ run_id: "RID", [key]: false }, "objective", "RID"));
  for (const value of [false, "", "other"])
    assert.throws(() => projectReviewHandoff({ run_id: "RID", gist_scope: value }, "gist", "RID"));
  const f = setup();
  const missing = f.capture();
  const handoff = (extra: object) =>
    f.files.set(
      handoffPath("/repo", "RID"),
      Buffer.from(JSON.stringify({ run_id: "RID", ...extra })),
    );
  handoff({});
  const present = f.capture();
  assert.notEqual(present, missing);
  handoff({
    objective_id: null,
    node_id: null,
    adopt_from: null,
    consumed_learn: [],
    ignored: "yes",
  });
  assert.equal(f.capture(), present);
  handoff({ consumed_learn: ["a", "b", "a"] });
  const ordered = f.capture();
  handoff({ consumed_learn: ["a", "a", "b"] });
  assert.notEqual(f.capture(), ordered);
});

test("refinement binds the strict context artifact digest and only the namespaced handoff block", () => {
  // Projection: only `objective_refinement.context_digest` is relevant; planning-link fields and
  // gist scope never fall through (no rebind by a top-level objective_id/node_id).
  const digest = "sha256:33e357e7ed77d5adbcfc0df41491deda7b152aede4858bdd2be270302d874163";
  assert.deepEqual(
    projectReviewHandoff(
      {
        run_id: "RID",
        objective_id: "7",
        node_id: "1.1",
        gist_scope: "plan",
        objective_refinement: { context_digest: digest, ignored: true },
      },
      "refinement",
      "RID",
    ),
    { context_digest: digest },
  );
  assert.deepEqual(
    projectReviewHandoff({ run_id: "RID", objective_id: "7" }, "refinement", "RID"),
    {
      context_digest: null,
    },
  );
  assert.deepEqual(
    projectReviewHandoff({ run_id: "RID", objective_refinement: null }, "refinement", "RID"),
    { context_digest: null },
  );
  for (const block of [[], "x", 42, { context_digest: "" }, { context_digest: false }])
    assert.throws(() =>
      projectReviewHandoff({ run_id: "RID", objective_refinement: block }, "refinement", "RID"),
    );
  assert.throws(() => projectReviewHandoff({ run_id: "WRONG" }, "refinement", "RID"));

  // Encoding: the refinement key is trailing and conditional — the pinned plan encoding above is
  // byte-identical (no `context_artifact` key ever appears for another subject).
  const withContext: TargetProjection = {
    ...projection,
    subject: "refinement",
    handoff: { context_digest: digest },
    context_artifact: emptyDigest,
  };
  const encoded = targetEncoding(withContext);
  assert.ok(encoded.endsWith(`,"context_artifact":"${emptyDigest}"}`));
  assert.ok(encoded.includes(`"handoff":{"context_digest":"${digest}"}`));
  assert.equal(targetEncoding({ ...projection, context_artifact: emptyDigest }), encoding);
  assert.notEqual(targetEncoding({ ...withContext, context_artifact: digest }), encoded);

  // Capture: a missing or invalid context artifact refuses; the digest is the strict read's.
  const f = setup("refinement");
  assert.deepEqual(captureDraftReviewBinding("/repo", f.session, f.ports), {
    ok: false,
    reason: "invalid-state",
    detail: "draft review refused: invalid-state",
  });
  const written = f.session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, '{"a":1}\n', {
    provenance: "strict",
  });
  assert.equal(written.status, "applied");
  const first = f.capture();
  const rewritten = f.session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, '{"a":2}\n', {
    provenance: "strict",
  });
  assert.equal(rewritten.status, "applied");
  assert.notEqual(f.capture(), first, "a re-prepared context changes the target fingerprint");
  const other = setup("gist");
  other.session.writeArtifact(REFINEMENT_CONTEXT_ARTIFACT, '{"a":2}\n', { provenance: "strict" });
  assert.equal(other.capture(), setup("gist").capture(), "other subjects ignore the context");
});

test("all unreadable/malformed routing inputs refuse instead of sentinel hashing", () => {
  const f = setup();
  for (const path of [handoffPath("/repo", "RID"), configFile("/repo"), localConfigFile("/repo")]) {
    const result = captureDraftReviewBinding("/repo", f.session, {
      ...f.ports,
      read(p) {
        if (p === path) throw new Error("EACCES secret config");
        return null;
      },
    });
    assert.deepEqual(result, {
      ok: false,
      reason: "io-error",
      detail: "draft review refused: io-error",
    });
  }
  for (const bytes of [Buffer.from("{"), Buffer.from("{}"), Buffer.from([0xff])]) {
    f.files.set(handoffPath("/repo", "RID"), bytes);
    assert.equal(captureDraftReviewBinding("/repo", f.session, f.ports).ok, false);
  }
  assert.equal(
    captureDraftReviewBinding("/repo", f.session, { ...f.ports, git: () => null }).ok,
    false,
  );
  f.session.draftReviewContext = () => ({ ok: false, reason: "no-identity" });
  assert.deepEqual(captureDraftReviewBinding("/repo", f.session, f.ports), {
    ok: false,
    reason: "no-identity",
    detail: "draft review refused: no-identity",
  });
});

test("strict Git production seam discovers real paths and preserves exact config stdout, including linked-worktree/main distinction", () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "perk-review-binding-")));
  const env = {
    ...process.env,
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_AUTHOR_NAME: "Test",
    GIT_AUTHOR_EMAIL: "test@example.org",
    GIT_COMMITTER_NAME: "Test",
    GIT_COMMITTER_EMAIL: "test@example.org",
  };
  const git = (...args: string[]) =>
    execFileSync("git", args, {
      cwd: root,
      env,
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 5000,
    });
  try {
    git("init", "-q");
    git("commit", "--allow-empty", "-m", "base", "-q");
    const linked = join(root, "linked");
    git("worktree", "add", "-b", "review", linked);
    mkdirSync(join(root, ".perk"), { recursive: true });
    mkdirSync(join(linked, ".perk"), { recursive: true });
    writeFileSync(configFile(root), "main");
    writeFileSync(configFile(linked), "worktree");
    const context = draftReviewGitContext(linked);
    assert.ok(context);
    assert.equal(context.worktreeRoot, linked);
    assert.equal(context.gitCommonDir, join(root, ".git"));
    assert.notEqual(context.gitDir, context.gitCommonDir);
    const expected = execFileSync("git", ["config", "--null", "--list", "--show-origin"], {
      cwd: linked,
      timeout: 5000,
    });
    assert.deepEqual(context.configBytes, expected);
    const session = openMemoryWorkflowSession({ runId: "RID" });
    const first = captureDraftReviewBinding(linked, session);
    assert.ok(first.ok);
    writeFileSync(configFile(root), "changed main");
    const second = captureDraftReviewBinding(linked, session);
    assert.ok(second.ok);
    assert.notEqual(first.binding.digest, second.binding.digest);
    writeFileSync(configFile(linked), "changed worktree");
    const third = captureDraftReviewBinding(linked, session);
    assert.ok(third.ok);
    assert.notEqual(second.binding.digest, third.binding.digest);
    const include = join(root, "included.gitconfig");
    writeFileSync(include, "[perk]\n review = first\n");
    git("config", "include.path", include);
    const included = captureDraftReviewBinding(linked, session);
    assert.ok(included.ok);
    writeFileSync(include, "[perk]\n review = second\n");
    const drift = captureDraftReviewBinding(linked, session);
    assert.ok(drift.ok);
    assert.notEqual(included.binding.digest, drift.binding.digest);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  assert.equal(draftReviewGitContext(root), null);
});
