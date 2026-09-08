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
  changedTargetComponents,
  type DraftReviewBindingPorts,
  projectReviewHandoff,
  TARGET_COMPONENTS,
  TARGET_ENCODING_PREFIX,
  type TargetComponent,
  type TargetProjection,
  targetComponents,
  targetDriftDetail,
  targetEncoding,
} from "./draftReviewBinding.ts";
import {
  digestSessionData,
  REFINEMENT_CONTEXT_ARTIFACT,
  type WorkflowSession,
} from "./workflowSession.ts";

const emptyDigest = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const absent = { state: "absent" as const };
const projection: TargetProjection = {
  worktree_root: "/repo",
  git_dir: "/repo/.git",
  git_common_dir: "/repo/.git",
  run_id: "RID",
  subject: "plan",
  warm_node_claim: null,
  handoff: null,
  config: {
    main_issues: { backend: absent, team: absent },
    workflow_base: { committed: absent, local: absent },
    linear_credentials: { api_key: absent },
  },
  git_config_digest: emptyDigest,
  environment: { GH_REPO: null, GH_HOST: null },
};
const encoding =
  'perk/draft-review-target/v2\n{"worktree_root":"/repo","git_dir":"/repo/.git","git_common_dir":"/repo/.git","run_id":"RID","subject":"plan","warm_node_claim":null,"handoff":null,"config":{"main_issues":{"backend":{"state":"absent"},"team":{"state":"absent"}},"workflow_base":{"committed":{"state":"absent"},"local":{"state":"absent"}},"linear_credentials":{"api_key":{"state":"absent"}}},"git_config_digest":"sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","environment":{"GH_REPO":null,"GH_HOST":null}}';
const encodingDigest = "sha256:5746f265ae7b6469f50fcec7a1e85f77a2ba8cd8791624d94761fd4c3f35fad6";
/** The retired v1 encoding of the same inputs (whole-file marks) — must never compare equal. */
const v1Encoding =
  'perk/draft-review-target/v1\n{"worktree_root":"/repo","git_dir":"/repo/.git","git_common_dir":"/repo/.git","run_id":"RID","subject":"plan","warm_node_claim":null,"handoff":null,"files":{"main_config":{"state":"absent"},"worktree_config":{"state":"absent"},"worktree_local":{"state":"absent"}},"git_config_digest":"sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","environment":{"GH_REPO":null,"GH_HOST":null}}';
const v1Digest = "sha256:33e357e7ed77d5adbcfc0df41491deda7b152aede4858bdd2be270302d874163";
const FAKE_KEY = "lin_api_FAKE0000deadbeef";

type Layout = "main" | "linked";
function setup(
  subject: "plan" | "objective" | "gist" | "refinement" = "plan",
  layout: Layout = "main",
) {
  const session: WorkflowSession = openMemoryWorkflowSession({ runId: "RID" });
  session.draftReviewContext = () => ({ ok: true, runId: "RID", subject, warmNodeClaim: null });
  const files = new Map<string, Uint8Array>();
  const reads: string[] = [];
  let env: { GH_REPO?: string; GH_HOST?: string } = {};
  let configBytes: Uint8Array = new Uint8Array();
  // A linked worktree's roots: the common dir lives under the MAIN checkout.
  const worktreeRoot = layout === "main" ? "/repo" : "/repo/.worktrees/linked";
  const ports: DraftReviewBindingPorts = {
    git: () => ({
      worktreeRoot,
      gitDir: layout === "main" ? "/repo/.git" : "/repo/.git/worktrees/linked",
      gitCommonDir: "/repo/.git",
      configBytes,
    }),
    read(path) {
      reads.push(path);
      return files.get(path) ?? null;
    },
    environment: () => env,
  };
  const result = () => captureDraftReviewBinding(worktreeRoot, session, ports);
  const bound = () => {
    const captured = result();
    assert.ok(captured.ok, JSON.stringify(captured));
    return captured.binding;
  };
  const capture = () => bound().digest;
  const write = (path: string, text: string | Uint8Array) =>
    files.set(path, typeof text === "string" ? Buffer.from(text) : text);
  return {
    session,
    ports,
    files,
    reads,
    result,
    bound,
    capture,
    worktreeRoot,
    mainConfig: (text: string | Uint8Array) => write(configFile("/repo"), text),
    mainLocal: (text: string | Uint8Array) => write(localConfigFile("/repo"), text),
    worktreeConfig: (text: string | Uint8Array) => write(configFile(worktreeRoot), text),
    worktreeLocal: (text: string | Uint8Array) => write(localConfigFile(worktreeRoot), text),
    env(value: typeof env) {
      env = value;
    },
    git(bytes: string | Uint8Array) {
      configBytes = typeof bytes === "string" ? Buffer.from(bytes) : bytes;
    },
  };
}
const ROUTING = '[issues]\nbackend = "linear"\nteam = "ENG"\n\n[workflow]\nbase = "main"\n';
const UNRELATED =
  '\n[compaction]\nreserve_tokens = 65536\nobjective_threshold = 0.8\n\n[models]\ndefault = "anthropic/claude-sonnet-4-5"\n\n[models.subagents]\npr-reviewer = "openai/gpt-5"\n\n[ci]\ntrusted = true\n\n[[ci.checks]]\nname = "lint"\ncommand = "just lint"\n\n[providers]\nplan = "plannotator-plan"\n\n[[bindings]]\ntrigger = "plan"\nskill = "x"\n\n[skills]\ndir = ".agents/skills"\n';

test("v2 target encoding and digest are independently pinned, including nested key order; v1 never compares equal", () => {
  assert.equal(TARGET_ENCODING_PREFIX, "perk/draft-review-target/v2\n");
  assert.equal(targetEncoding(projection), encoding);
  assert.equal(digestSessionData(encoding), encodingDigest);
  assert.equal(digestSessionData(v1Encoding), v1Digest, "the retired v1 pin is what it was");
  assert.notEqual(encoding, v1Encoding);
  assert.notEqual(encodingDigest, v1Digest);
  assert.ok(!encoding.includes('"files"'), "whole-file marks are gone from the fingerprint");
  const reordered = {
    ...projection,
    environment: { GH_HOST: null, GH_REPO: null },
    config: {
      linear_credentials: { api_key: absent },
      workflow_base: { local: absent, committed: absent },
      main_issues: { team: absent, backend: absent },
    },
  };
  assert.equal(targetEncoding(reordered), encoding);
  const f = setup();
  assert.equal(f.capture(), encodingDigest);
  // Main checkout: handoff first, then each DISTINCT routing file exactly once (main == worktree).
  assert.deepEqual(f.reads, [
    handoffPath("/repo", "RID"),
    configFile("/repo"),
    localConfigFile("/repo"),
  ]);
  // Gist/refinement carry a null workflow_base and never read the worktree-role files.
  const gist = setup("gist");
  assert.equal(
    gist.capture(),
    "sha256:a9dbcd074f309638c56cf3a84af08097fd3969cd90e57aad8445f6b9a0ac3fbb",
  );
  assert.ok(
    targetEncoding({
      ...projection,
      subject: "gist",
      config: { ...projection.config, workflow_base: null },
    }).includes('"workflow_base":null'),
  );
});

test("unrelated Perk TOML changes leave the target unchanged; formatting, comments, order and file existence are not identity", () => {
  for (const subject of ["plan", "objective", "gist"] as const) {
    const f = setup(subject);
    f.mainConfig(ROUTING);
    f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n`);
    const reviewed = f.capture();
    // The incident: a compaction-only edit pulled into the checkout during an open review.
    f.mainConfig(`${ROUTING}\n[compaction]\nreserve_tokens = 65536\n`);
    assert.equal(f.capture(), reviewed, `${subject}: compaction edit`);
    f.mainConfig(`${ROUTING}${UNRELATED}`);
    assert.equal(f.capture(), reviewed, `${subject}: model/CI/skill/provider/presentation edits`);
    f.mainConfig(
      `# [issues] backend = "github"  (a comment, not a header)\n[workflow] # base = "release"\n  base   =   "main"\n\n\n[issues]\nteam = 'ENG'\nbackend = """linear"""\n`,
    );
    assert.equal(f.capture(), reviewed, `${subject}: equivalent spelling/order/comments`);
    f.mainConfig(`issues = { backend = "linear", team = "ENG" }\nworkflow.base = "main"\n`);
    assert.equal(f.capture(), reviewed, `${subject}: inline tables and dotted keys`);
    f.mainLocal(
      `[linear]\napi_key = "${FAKE_KEY}"\n[models.subagents]\ndraft-reviewer = "inherit"\n`,
    );
    assert.equal(f.capture(), reviewed, `${subject}: unrelated local overlay edit`);
    // A provider-selection change does not retarget the already registered browser review.
    f.mainConfig(`${ROUTING}\n[providers]\nplan = "perk-plan"\n`);
    assert.equal(f.capture(), reviewed, `${subject}: provider selection`);
    // File existence is not identity: missing, empty, comment-only and empty-table files coincide.
    f.files.clear();
    const missing = f.capture();
    f.mainConfig("");
    f.mainLocal('# only comments\n# [linear]\n# api_key = "x"\n');
    assert.equal(f.capture(), missing);
    f.mainConfig("[issues]\n[workflow]\n");
    f.mainLocal("[linear]\n");
    assert.equal(f.capture(), missing);
    assert.notEqual(missing, reviewed, "routing values present vs absent still differ");
  }
});

test("declared routing fields are sensitive: exact strings, whitespace, empty vs absent, shadowed inputs, and the hashed credential", () => {
  const f = setup();
  f.mainConfig(ROUTING);
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n`);
  const reviewed = f.bound();
  const drifted = (name: TargetComponent[], label: string) => {
    const current = f.bound();
    assert.notEqual(current.digest, reviewed.digest, label);
    assert.deepEqual(changedTargetComponents(reviewed.components, current.components), name, label);
  };
  f.mainConfig(ROUTING.replace('backend = "linear"', 'backend = "github"'));
  drifted(["main_config.issues.backend"], "backend");
  f.mainConfig(ROUTING.replace('team = "ENG"', 'team = "ENG "'));
  drifted(["main_config.issues.team"], "trailing whitespace is exact");
  f.mainConfig(ROUTING.replace('team = "ENG"', 'team = ""'));
  drifted(["main_config.issues.team"], "empty string differs from a value");
  f.mainConfig(ROUTING.replace('team = "ENG"\n', ""));
  drifted(["main_config.issues.team"], "absent differs from present");
  f.mainConfig(ROUTING.replace('base = "main"', 'base = "release"'));
  drifted(
    ["worktree_config.workflow.base"],
    "committed base (main checkout aliases worktree role)",
  );
  f.mainConfig(ROUTING);
  // A local base that Python may or may not prefer is still a declared input: conservatively bound.
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n[workflow]\nbase = "main"\n`);
  drifted(["worktree_local.workflow.base"], "local base appears even when equal to committed");
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n`);
  assert.equal(f.capture(), reviewed.digest);
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}x"\n`);
  drifted(["main_local.linear.api_key"], "credential rotation");
  // Several fields at once report in fixed component order.
  f.mainConfig(
    ROUTING.replace('backend = "linear"', 'backend = "github"').replace(
      'base = "main"',
      'base = "release"',
    ),
  );
  drifted(
    ["main_config.issues.backend", "worktree_config.workflow.base", "main_local.linear.api_key"],
    "multiple fields",
  );
  // The secret never appears in the binding, its components, or the drift detail.
  const current = f.bound();
  const rendered = JSON.stringify({ reviewed, current });
  assert.ok(!rendered.includes("lin_api_"));
  const detail = targetDriftDetail({
    checkpoint: "attach",
    reviewed: reviewed.digest,
    current: current.digest,
    changed: changedTargetComponents(reviewed.components, current.components),
  });
  assert.equal(
    detail,
    `checkpoint: attach; reviewed target: ${reviewed.digest}; current target: ${current.digest}; changed components: main_config.issues.backend, worktree_config.workflow.base, main_local.linear.api_key`,
  );
  assert.ok(
    !detail.includes("lin_api_") && !detail.includes("github") && !detail.includes("release"),
  );
  assert.equal(
    targetDriftDetail({ checkpoint: "candidate", reviewed: "a", current: "b", changed: null }),
    "checkpoint: candidate; reviewed target: a; current target: b; changed components: unavailable (no matching diagnostic baseline)",
  );
  assert.equal(
    targetDriftDetail({ checkpoint: "save", reviewed: "a", current: "b", changed: [] }),
    "checkpoint: save; reviewed target: a; current target: b; changed components: none identified",
  );
  // Unselected fields in the SAME tables are ignored (plan_authoring; local/worktree issues).
  f.mainConfig(`${ROUTING}plan_authoring = "x"\n`);
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n[issues]\nbackend = "github"\nteam = "OPS"\n`);
  assert.equal(f.capture(), reviewed.digest, "local [issues] is not a canonical routing input");
});

test("linked worktree: [issues] and the credential follow the MAIN checkout, [workflow] base the invoking checkout; each distinct file once", () => {
  const f = setup("plan", "linked");
  f.mainConfig(ROUTING);
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n`);
  f.worktreeConfig('[workflow]\nbase = "feature"\n[issues]\nbackend = "github"\n');
  f.worktreeLocal(`[workflow]\nbase = "feature-local"\n[linear]\napi_key = "lin_api_WORKTREE"\n`);
  const reviewed = f.bound();
  assert.deepEqual(f.reads, [
    handoffPath(f.worktreeRoot, "RID"),
    configFile("/repo"),
    configFile(f.worktreeRoot),
    localConfigFile(f.worktreeRoot),
    localConfigFile("/repo"),
  ]);
  const changed = () => changedTargetComponents(reviewed.components, f.bound().components);
  // The worktree's own [issues] selection and local credential are NOT routing inputs.
  f.worktreeConfig('[workflow]\nbase = "feature"\n[issues]\nbackend = "linear"\nteam = "OPS"\n');
  f.worktreeLocal(`[workflow]\nbase = "feature-local"\n[linear]\napi_key = "lin_api_ROTATED"\n`);
  assert.equal(f.capture(), reviewed.digest);
  f.mainConfig(ROUTING.replace('team = "ENG"', 'team = "OPS"'));
  assert.deepEqual(changed(), ["main_config.issues.team"]);
  f.mainConfig(ROUTING);
  f.worktreeConfig('[workflow]\nbase = "other"\n');
  assert.deepEqual(changed(), ["worktree_config.workflow.base"]);
  f.worktreeConfig('[workflow]\nbase = "feature"\n');
  f.worktreeLocal("");
  assert.deepEqual(changed(), ["worktree_local.workflow.base"]);
  f.worktreeLocal('[workflow]\nbase = "feature-local"\n');
  f.mainLocal("");
  assert.deepEqual(changed(), ["main_local.linear.api_key"]);
  // The main checkout's [workflow] base is NOT the invoking checkout's: changing it is invisible.
  f.mainLocal(`[linear]\napi_key = "${FAKE_KEY}"\n`);
  f.mainConfig(`${ROUTING.replace('base = "main"', 'base = "elsewhere"')}`);
  assert.equal(f.capture(), reviewed.digest);
  // Gist/refinement in a linked worktree read only the two main-checkout files.
  const gist = setup("gist", "linked");
  gist.capture();
  assert.deepEqual(gist.reads, [
    handoffPath(gist.worktreeRoot, "RID"),
    configFile("/repo"),
    localConfigFile("/repo"),
  ]);
});

test("component digests cover every fixed group, never leak values, and identify the drifted group", () => {
  assert.deepEqual(Object.keys(targetComponents(projection)), [...TARGET_COMPONENTS]);
  const base = targetComponents(projection);
  for (const digest of Object.values(base)) assert.match(digest, /^sha256:[0-9a-f]{64}$/);
  const probe = (patch: Partial<TargetProjection>, expected: TargetComponent[]) =>
    assert.deepEqual(
      changedTargetComponents(base, targetComponents({ ...projection, ...patch })),
      expected,
    );
  probe({ run_id: "OTHER" }, ["identity"]);
  probe({ subject: "objective" }, ["identity"]);
  probe({ warm_node_claim: { objective: "7", node: "1.1" } }, ["warm_node_claim"]);
  probe({ handoff: { objective_id: null, node_id: null, adopt_from: null, consumed_learn: [] } }, [
    "handoff",
  ]);
  probe({ git_config_digest: digestSessionData("x") }, ["git_config"]);
  probe({ environment: { GH_REPO: digestSessionData("o/r"), GH_HOST: null } }, ["environment"]);
  probe(
    {
      config: {
        ...projection.config,
        main_issues: {
          backend: { state: "present", digest: digestSessionData("linear") },
          team: absent,
        },
      },
    },
    ["main_config.issues.backend"],
  );
  probe({ config: { ...projection.config, workflow_base: null } }, [
    "worktree_config.workflow.base",
    "worktree_local.workflow.base",
  ]);
  // Refinement's context key is a component too; for other subjects it is a constant null.
  probe({ subject: "refinement", context_artifact: emptyDigest }, ["identity", "context_artifact"]);
  probe({ context_artifact: emptyDigest }, []);
});

test("env/git projections preserve empty, absent, exact bytes and non-UTF8 git output", () => {
  const f = setup();
  const absent = f.capture();
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

test("all unreadable/malformed routing inputs refuse instead of sentinel hashing, naming the file role but never its contents", () => {
  const f = setup();
  const unreadable = captureDraftReviewBinding("/repo", f.session, {
    ...f.ports,
    read(p) {
      if (p === handoffPath("/repo", "RID")) throw new Error("EACCES secret handoff");
      return null;
    },
  });
  assert.deepEqual(unreadable, {
    ok: false,
    reason: "io-error",
    detail: "draft review refused: io-error",
  });
  for (const [path, role] of [
    [configFile("/repo"), "main_config/worktree_config"],
    [localConfigFile("/repo"), "worktree_local/main_local"],
  ] as const) {
    const result = captureDraftReviewBinding("/repo", f.session, {
      ...f.ports,
      read(p) {
        if (p === path) throw new Error(`EACCES ${FAKE_KEY}`);
        return null;
      },
    });
    assert.deepEqual(result, {
      ok: false,
      reason: "io-error",
      detail: `draft review refused: io-error; routing config ${role}: unreadable`,
    });
  }
  // File-level failures name every role sharing the file; field-level failures name the
  // selecting role and field.
  const shared = "main_config/worktree_config";
  const cases: [string | Uint8Array, string][] = [
    ['[issues\nbackend = "linear"\n', `${shared}: TOML parse failed`],
    [`[linear]\napi_key = "${FAKE_KEY}"\napi_key = "dup"\n`, `${shared}: TOML parse failed`],
    [
      Buffer.from([0x5b, 0x69, 0x73, 0x73, 0x75, 0x65, 0x73, 0x5d, 0x0a, 0xff]),
      `${shared}: not valid UTF-8`,
    ],
    ['issues = "linear"\n', "main_config: [issues] is not a table"],
    ['[[issues]]\nbackend = "linear"\n', "main_config: [issues] is not a table"],
    ["[issues]\nbackend = 1\n", "main_config: [issues] backend is not a string"],
    ['[issues]\nteam = ["ENG"]\n', "main_config: [issues] team is not a string"],
    ["[workflow]\nbase = 2024-01-01\n", "worktree_config: [workflow] base is not a string"],
  ];
  for (const [bytes, explanation] of cases) {
    f.files.clear();
    f.mainConfig(bytes);
    const result = f.result();
    assert.ok(!result.ok, explanation);
    assert.equal(result.reason, "io-error");
    assert.equal(result.detail, `draft review refused: io-error; routing config ${explanation}`);
    assert.ok(!result.detail.includes(FAKE_KEY) && !result.detail.includes("linear"));
  }
  f.files.clear();
  f.mainLocal(`[linear]\napi_key = ${FAKE_KEY}\n`);
  const bare = f.result();
  assert.ok(!bare.ok);
  assert.equal(
    bare.detail,
    "draft review refused: io-error; routing config worktree_local/main_local: TOML parse failed",
  );
  f.files.clear();
  f.mainLocal(`[linear]\napi_key = true\n`);
  const typed = f.result();
  assert.ok(!typed.ok);
  assert.equal(
    typed.detail,
    "draft review refused: io-error; routing config main_local: [linear] api_key is not a string",
  );
  // Gist ignores the worktree-only role: a broken [workflow] base is still read in a main
  // checkout (same file), but a linked worktree's broken local file is never consulted.
  const linkedGist = setup("gist", "linked");
  linkedGist.worktreeLocal("[broken");
  assert.ok(linkedGist.result().ok);
  const linkedPlan = setup("plan", "linked");
  linkedPlan.worktreeLocal("[broken");
  const brokenLocal = linkedPlan.result();
  assert.ok(!brokenLocal.ok);
  assert.equal(
    brokenLocal.detail,
    "draft review refused: io-error; routing config worktree_local: TOML parse failed",
  );
  f.files.clear();
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
    writeFileSync(configFile(root), '[issues]\nbackend = "github"\n');
    writeFileSync(configFile(linked), '[workflow]\nbase = "main"\n');
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
    // Unrelated edits to either checkout's config leave the real production capture unchanged.
    writeFileSync(
      configFile(root),
      '[issues]\nbackend = "github"\n[compaction]\nreserve_tokens = 65536\n',
    );
    writeFileSync(
      configFile(linked),
      '# comment\n[workflow]\nbase = "main"\n[ci]\ntrusted = true\n',
    );
    const unrelated = captureDraftReviewBinding(linked, session);
    assert.ok(unrelated.ok);
    assert.equal(first.binding.digest, unrelated.binding.digest);
    writeFileSync(configFile(root), '[issues]\nbackend = "linear"\n');
    const second = captureDraftReviewBinding(linked, session);
    assert.ok(second.ok);
    assert.notEqual(first.binding.digest, second.binding.digest);
    assert.deepEqual(changedTargetComponents(first.binding.components, second.binding.components), [
      "main_config.issues.backend",
    ]);
    writeFileSync(configFile(linked), '[workflow]\nbase = "release"\n');
    const third = captureDraftReviewBinding(linked, session);
    assert.ok(third.ok);
    assert.notEqual(second.binding.digest, third.binding.digest);
    assert.deepEqual(changedTargetComponents(second.binding.components, third.binding.components), [
      "worktree_config.workflow.base",
    ]);
    writeFileSync(localConfigFile(root), `[linear]\napi_key = "${FAKE_KEY}"\n`);
    const credential = captureDraftReviewBinding(linked, session);
    assert.ok(credential.ok);
    assert.deepEqual(
      changedTargetComponents(third.binding.components, credential.binding.components),
      ["main_local.linear.api_key"],
    );
    assert.ok(!JSON.stringify(credential).includes(FAKE_KEY));
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
