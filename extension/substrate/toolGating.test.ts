// The tool-gating primitive: pure policy matrix + a live read-only round-trip driven
// through a REAL bound AgentSession via the harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import { REFUSAL_REASONS } from "./commandPositions.ts";
import {
  FFF_SEARCH_TOOLS,
  gatedToolsFor,
  isReadOnlyBashCommand,
  LINEAR_READ_TOOLS,
  READ_ONLY_CONTEXT,
  READ_ONLY_TOOLS,
  REFINEMENT_READ_ONLY_CONTEXT,
  REFINEMENT_READ_ONLY_TOOLS,
  readOnlyBashVerdict,
  registerToolGating,
  SUBAGENT_CHILD_TOOLS,
  WEB_RESEARCH_TOOLS,
} from "./toolGating.ts";

type Hook = (
  event: { toolName?: string; input?: Record<string, unknown>; messages?: unknown[] },
  ctx: ExtensionContext,
) => Promise<{ block?: boolean; message?: { content: string }; messages?: unknown[] } | undefined>;

function gateFixture(floor: () => boolean) {
  const hooks = new Map<string, Hook>();
  let fail: "snapshot" | "census" | "toolset" | "append" | undefined;
  const appends: unknown[] = [];
  const installed: string[][] = [];
  const pi = {
    on: (name: string, hook: Hook) => {
      hooks.set(name, hook);
    },
    getActiveTools: () => {
      if (fail === "snapshot") throw new Error("snapshot");
      return ["read", "write", "plan_save"];
    },
    getAllTools: () => {
      if (fail === "census") throw new Error("census");
      return ["read", "write", "plan_save"].map((name) => ({ name }));
    },
    setActiveTools: (names: string[]) => {
      if (fail === "toolset") throw new Error("toolset");
      installed.push(names);
    },
    appendEntry: (_type: string, data: unknown) => {
      if (fail === "append") throw new Error("append");
      appends.push(data);
    },
  } as ExtensionAPI;
  const gate = registerToolGating(pi, floor);
  const sessionManager = SessionManager.inMemory("/repo");
  sessionManager.getBranch = () => {
    throw new Error("branch unavailable");
  };
  const context: Pick<ExtensionContext, "sessionManager"> = { sessionManager };
  const ctx = context as ExtensionContext;
  return {
    gate,
    appends,
    installed,
    fail: (value: typeof fail) => {
      fail = value;
    },
    call: (name: string, event: Parameters<Hook>[0] = {}) => hooks.get(name)?.(event, ctx),
  };
}

async function assertBackstop(h: ReturnType<typeof gateFixture>) {
  assert.equal(h.gate.isActive(), true);
  for (const toolName of ["edit", "write", "plan_save", "submit", "foreign_mutator"]) {
    assert.equal((await h.call("tool_call", { toolName, input: {} }))?.block, true, toolName);
  }
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: "touch x" } }))?.block,
    true,
  );
  for (const toolName of ["read", ...SUBAGENT_CHILD_TOOLS]) {
    assert.equal(await h.call("tool_call", { toolName, input: {} }), undefined, toolName);
  }
  assert.equal(
    await h.call("tool_call", { toolName: "bash", input: { command: "git status" } }),
    undefined,
  );
  assert.equal((await h.call("before_agent_start"))?.message?.content, READ_ONLY_CONTEXT);
  assert.equal(
    await h.call("context", { messages: [{ customType: "perk:mode-context" }] }),
    undefined,
  );
}

test("floor enforces all observations before sync, despite snapshot/census/toolset/append failures", async () => {
  for (const mode of [undefined, "read-write"]) {
    for (const failure of ["snapshot", "census", "toolset", "append"] as const) {
      const h = gateFixture(() => true);
      await assertBackstop(h);
      h.fail(failure);
      assert.throws(() =>
        failure === "append" ? h.gate.enter() : h.gate.syncFromState(mode, undefined),
      );
      await assertBackstop(h);
      h.fail(undefined);
      h.gate.exit();
      assert.deepEqual(h.appends, [], "floor exit never appends read-write");
      h.gate.syncFromState("read-write", undefined);
      assert.deepEqual(h.installed.at(-1), READ_ONLY_TOOLS);
      await assertBackstop(h);
    }
  }
});

test("false cannot clear inherited read-only; ordinary parents use the same backstop; read-write is unaffected", async () => {
  const h = gateFixture(() => false);
  h.gate.syncFromState("read-only", undefined);
  await assertBackstop(h);
  h.fail("toolset");
  assert.throws(() => h.gate.syncFromState("read-write", undefined));
  await assertBackstop(h);
  h.fail(undefined);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
  for (const toolName of ["write", "foreign_mutator", "plan_save", "submit", "bash"]) {
    assert.equal(await h.call("tool_call", { toolName, input: { command: "touch x" } }), undefined);
  }
});

test("a census-read failure on a cold read-only sync stays closed, records no half engagement, and the startup re-apply retakes it", async () => {
  // No floor: the ordinary cold read-only sync (a `mode: read-only` handoff) whose first
  // engagement read throws AFTER the snapshot read — the one path where the in-memory gate had
  // never been engaged, so fail-closed must come from `apply()` itself, not from a prior state.
  const h = gateFixture(() => false);
  h.fail("census");
  assert.throws(() => h.gate.syncFromState("read-only", undefined));
  await assertBackstop(h);
  assert.deepEqual(h.installed, [], "a half-taken engagement installs nothing");
  // The `resources_discover` re-apply (Pi reports the throw) does not open the gate either.
  await assert.rejects(() => h.call("resources_discover") ?? Promise.resolve());
  await assertBackstop(h);
  assert.deepEqual(h.installed, []);
  // The failed read recorded nothing: once it succeeds, the same re-apply takes a FRESH
  // snapshot + census and installs the gated set; the exit then restores that fresh snapshot.
  h.fail(undefined);
  await h.call("resources_discover");
  assert.deepEqual(h.installed, [READ_ONLY_TOOLS]);
  await assertBackstop(h);
  h.gate.exit();
  assert.equal(h.gate.isActive(), false);
  assert.deepEqual(h.installed.at(-1), ["read", "write", "plan_save"]);
  assert.deepEqual(h.appends, [{ mode: "read-write" }]);
});

test("a throwing supplier and malformed bash inputs never open the gate", async () => {
  const h = gateFixture(() => {
    throw new Error("floor read failed");
  });
  h.gate.syncFromState(undefined, undefined);
  await assertBackstop(h);
  h.gate.exit();
  assert.deepEqual(h.appends, []);
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: Object.create(null) } }))
      ?.block,
    true,
  );
});

test("READ_ONLY_TOOLS: the exact recomposed set + order", () => {
  // The family-constant recomposition is STRUCTURAL: set and order stay byte-identical to the
  // pre-extraction literals (+ the deliberate delegation carve-in at the tail). An exact
  // deepEqual guards both.
  assert.deepEqual(READ_ONLY_TOOLS, [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "ask_user_question",
    "plan_review",
    "plan_draft",
    "objective_draft",
    "gist_draft",
    "objective_node",
    "web_search",
    "code_search",
    "fetch_content",
    "get_search_content",
    "ollama_web_search",
    "ollama_web_fetch",
    "web_fetch",
    "linear_whoami",
    "linear_workspace_metadata",
    "linear_list_teams",
    "linear_get_team",
    "linear_list_users",
    "linear_get_user",
    "linear_list_issues",
    "linear_get_issue",
    "linear_search_issues",
    "linear_list_my_issues",
    "linear_list_projects",
    "linear_get_project",
    "linear_list_issue_statuses",
    "linear_get_issue_status",
    "linear_list_labels",
    "linear_list_cycles",
    "linear_list_documents",
    "linear_get_document",
    "linear_list_comments",
    // FFF local search (both mode name-sets; the override names find/grep are above).
    "fffind",
    "ffgrep",
    "fff-multi-grep",
    "multi_grep",
    // The delegation carve-in (the gated flows' spawn surface).
    "subagent",
    "wait",
    "subagent_supervisor",
    "intercom",
    // The explorer-wave carve-in (the gated objective-plan explore tool).
    "explore_objective_node",
    // The scout-wave carve-in (the authoring sessions' launcher; read-only perk.scout lanes over
    // the delegation family, no worktree writes).
    "run_scout_wave",
    // The child-side carve-in (gated adopt-children keep the engine's injected tools — perk's
    // own waves spawn bridge-off so `contact_supervisor` is absent there, but an ad-hoc gated
    // child with an active bridge must keep its supervisor door).
    "structured_output",
    "contact_supervisor",
    // The draft-review-door carve-in (plan-authoring sessions run gated; the
    // /plan-review-browser companions must stay reachable).
    "push_annotations",
    "start_draft_review_wave",
    "collect_draft_review_wave",
    // The audit-wave carve-in (the gated audit-judge session's wave call; write target bound
    // to the cold door's workflow-state audit_bundle_dir — no caller-supplied path exists).
    "run_audit_wave",
    // The harvest-wave carve-in (the gated learn-harvest session's wave call; the manifest
    // read is bound to the claimed run-scoped scratch path — any other path refused).
    "run_harvest_wave",
    // The dream-wave carve-in (the gated learn-dream session's wave call; NO parameters — the
    // manifest read AND the fixed-name bundle write are both derived from the claimed run's
    // manifest path, the no-aimable-writer posture on both sides).
    "run_dream_wave",
  ]);
});

test("READ_ONLY_TOOLS: contains run_harvest_wave (the gated learn-harvest session's wave call)", () => {
  // The seeded `perk learn harvest` session runs GATED (the read-only objective-author borrow),
  // so the wave must be reachable while read-only. Safe in every gated session: the tool's
  // manifest read is structurally bound to the session's claimed run-scoped scratch path (a
  // relayed param naming any other path is refused — the run_audit_wave no-aimable-writer
  // posture, read-side), it spawns only the read-only perk.harvest-analyst, and it writes
  // nothing to the worktree.
  assert.ok(READ_ONLY_TOOLS.includes("run_harvest_wave"));
});

test("READ_ONLY_TOOLS: contains the pi-subagents child-side tools (gated adopt-children keep the engine-injected structured_output)", () => {
  // The read-only gate is inherited by adopted children (§8.3 adopt arm); stripping the
  // engine-injected structured_output made an outputSchema child fail with
  // structuredOutputFailed after completing its whole exploration.
  for (const tool of SUBAGENT_CHILD_TOOLS) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains plan_review (the review door is callable in plan mode)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("plan_review"));
});

test("READ_ONLY_TOOLS: contains plan_draft (the session-data carve-out)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("plan_draft"));
});

test("READ_ONLY_TOOLS: contains objective_draft (the twin of the carve-out)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("objective_draft"));
});

test("READ_ONLY_TOOLS: contains objective_node (the gated factory's node-transition door)", () => {
  // Both objective-plan factory paths run gated; the `objective_node_claim` carrier can only be
  // written by calling the tool inside the gated session — excluding it saves plans unlinked.
  assert.ok(READ_ONLY_TOOLS.includes("objective_node"));
});

test("READ_ONLY_TOOLS: contains the UNION of all web-seam providers' research tools", () => {
  // perk does not normalize names — the allowlist carries every known web provider's tool names
  // (pi-web-access + @ollama/pi-web-search + @juicesharp/rpiv-web-tools), inert when absent.
  for (const tool of [
    "web_search",
    "code_search",
    "fetch_content",
    "get_search_content",
    "ollama_web_search",
    "ollama_web_fetch",
    "web_fetch",
  ]) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains the FFF search tools", () => {
  // Both pi-fff mode name-sets are enumerated (tools-and-ui + override's multi_grep), static
  // and inert when the package is absent; local search belongs in read-only exploration.
  for (const tool of FFF_SEARCH_TOOLS) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
});

test("READ_ONLY_TOOLS: contains the read-only linear_* tools, never the mutating ones", () => {
  for (const tool of [
    "linear_get_issue",
    "linear_list_comments",
    "linear_list_issues",
    "linear_search_issues",
    "linear_whoami",
  ]) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
  for (const tool of [
    "linear_create_issue",
    "linear_update_issue",
    "linear_create_comment",
    "linear_upload_file",
    "linear_upload_file_to_issue_comment",
    "linear_configure_auth",
  ]) {
    assert.ok(!READ_ONLY_TOOLS.includes(tool), `mutating tool allowlisted: ${tool}`);
  }
  // The context steers GitHub reads to the allowlisted read-only `gh` subcommands.
  assert.ok(READ_ONLY_CONTEXT.includes("read-only `gh` subcommands"));
  assert.ok(READ_ONLY_CONTEXT.includes("never raw curl/fetch against github.com"));
});

test("isReadOnlyBashCommand: allows read-only commands", () => {
  for (const cmd of [
    "cat README.md",
    "grep -r foo .",
    "ls -la",
    "git status",
    "git log --oneline -5",
    "git diff HEAD",
    "rg pattern src",
    "ast-grep run --pattern 'console.log($A)' --lang js .", // structural code search
    "ast-grep run --pattern 'print($A)' --lang python .", // language-agnostic: the allowlist gates the `ast-grep` command, not its --lang
    "ast-grep scan --inline-rules 'id: x\nlanguage: ts\nrule: {pattern: $A}'",
    "agent-browser snapshot", // browser-automation skill (command-keyed like ast-grep)
    "agent-browser navigate https://example.com",
    "npx agent-browser skills get core", // npx fallback anchored to agent-browser
    "cd repo && agent-browser screenshot", // every command position allowlisted, cd prefix
    "find . -name '*.ts'",
    "wc -l file",
    "sed -n '1,10p' file",
    "cat x 2>&1", // fd duplication is not a file write
    "grep foo bar 2>&1",
    "ls -la 1>&2",
    "cat foo 2>/dev/null", // /dev/null redirect is not a file write
    'grep -rn "user-docs" README.md 2>/dev/null',
    "cd /tmp && grep foo bar", // cd prefix + every command position safe
    "cd repo && perk objective show 453 2>&1 | head -200", // reported example 1
    `ls tests/ | grep -iE 'doc|user|cli|link'; echo "---"; grep -rl "user-docs" tests/ 2>/dev/null`, // reported example 3 (quoted | does not split; 2>/dev/null allowed)
    `find tests -name '*.py' | grep -iE 'doc|user|cli' ; echo --- ; grep -rl "user-docs" tests 2>/dev/null`, // reported example 4
    "perk objective show", // perk's read-only objective queries
    "perk objective show 7 --full", // the body read rides the same read-only verb
    "perk objective next",
    "perk obj show 42",
    "perk objective s", // s/n aliases
    "perk obj n",
    "perk objective node-engagement 7 --node 2.1 --json", // non-mutating engagement read
    "gh issue view 12 --json body", // read-only gh queries
    "gh pr view 7 --json title --jq .title",
    "gh pr diff 7",
    "gh pr checks 7",
    "gh run list --limit 5",
    "gh search prs perk",
    "gh search code registerTool --repo x/y", // `code` as a gh-search noun is not an editor invocation
    "gh auth status",
    // every command position is checked, so loops, assignment prefixes, substitutions, keywords,
    // wrappers, exec forms and heredocs pass when every command word is allowlisted
    "for f in a b c; do echo $f; done",
    'for f in agents/*.md; do wc -l "$f"; done',
    'EVID=$(cat x); echo "$EVID"',
    "env | grep PERK",
    "timeout 30 rg foo src",
    "find . -exec grep -l foo {} \\;",
    "find . -exec env X=1 grep -l foo {} \\;",
    'cd "$(cat .perk/root)" && rg foo', // the structural stand-in for `cd $(git rev-parse …) && …`
    "cd /repo\ngit ls-files docs | head -5; echo ---; sed -n '1,5p' README.md",
    'f=$(ls dist/*.js); grep -n "x" "$f"',
    'f="/a b/c"; sed -n \'1p\' "$f"',
    "LC_ALL=C sort file",
    "X=1 Y=2 grep foo f",
    "cat <<'EOF' | wc -c\nline one\nline two\nEOF",
    "cat <<EOF\n$(echo hi)\nEOF",
    'echo "$(pwd)"',
    "echo `pwd`",
    "diff <(sort a) <(sort b)",
    "< README.md wc -l",
    '<<< "text" wc -c',
    "2>/dev/null ls",
    "echo $'a\\'b'; ls",
    "rg foo \\\n  --glob '*.ts'",
    "# list files\nls -la",
    "ls # trailing comment",
    "while grep -q x f; do cat f; done",
    "if grep -q x f; then cat f; fi",
    "! grep -q x f",
    "{ cat a; cat b; }",
    "nice -n 5 rg foo",
    "time rg foo",
    "nohup rg foo",
    "command rg foo",
    "xargs -0 -n1 grep -l foo",
    "find . -name '*.py' | xargs -I{} wc -l {}",
    "env -i X=1 grep foo f",
    "timeout -k 5 30s rg foo",
    "fd -e py -x wc -l",
    "cat a |& grep b",
    "echo ok & ls",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("the reviewer defs' oversized-line byte-slice recipe passes the gate; its redirect does not", () => {
  // The agent defs teach `sed -n 'Np' <path> | tail -c +<offset> | head -c 51200` to page a line
  // over Pi's per-line `read` bound. Every segment must stay allowlisted or the defs' recipe
  // silently stops working for read-only children; a real-file redirect stays vetoed.
  const path = "/repo/.perk/workflow/scratch/runs/RUN/review-context/pr-42-0123456789ab/diff.patch";
  for (const offset of ["+1", "+51201", "+102401"])
    assert.equal(
      isReadOnlyBashCommand(`sed -n '12p' ${path} | tail -c ${offset} | head -c 51200`),
      true,
      offset,
    );
  assert.equal(isReadOnlyBashCommand(`sed -n '12p' ${path} | head -c 51200`), true);
  assert.equal(isReadOnlyBashCommand(`grep -n '^diff --git' ${path}`), true);
  assert.equal(isReadOnlyBashCommand(`wc -lc ${path}`), true);
  assert.equal(
    isReadOnlyBashCommand(`sed -n '12p' ${path} | tail -c +51201 | head -c 51200 > slice.txt`),
    false,
  );
});

const SHA_A = "a".repeat(40);
const SHA_B = "b".repeat(40);
const SHA_0 = "0".repeat(40);
/** The pinned stack form exactly as `pinnedReviewContextCommand` renders it (+ `--json`). */
const PINNED_QUERY = `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`;

test("plan-bound review queries allow only the exact argument forms", () => {
  // The plan-bound `--expected-pr` form, the human-triage doors' foreign `--pr` / `--pr --stack`
  // forms, the stack flow's PINNED form, and the feedback query — each gets the same
  // whitespace/`cd`-prefix/redirect matrix.
  const queries = [
    "perk pr review-context --expected-pr 42 --json",
    "perk pr review-context --pr 42 --json",
    "perk pr review-context --pr 42 --stack --json",
    PINNED_QUERY,
    `perk pr review-context --pr 43 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --pin-head 43=${SHA_0} --json`,
    "perk pr feedback --json",
  ];
  for (const query of queries) {
    for (const command of [
      query,
      `  ${query}  `,
      query.replaceAll(" ", "\t"),
      `cd repo && ${query}`,
    ])
      assert.equal(isReadOnlyBashCommand(command), true, command);
    for (const command of [
      `${query} --extra`,
      `${query} > report.json`,
      `${query} >> report.json`,
      `${query} && perk pr review-post`,
      `${query}; rm file`,
      `${query} | gh api user`,
    ])
      assert.equal(isReadOnlyBashCommand(command), false, command);
  }
  for (const command of [
    "perk pr review-context",
    "perk pr review-context --json",
    "perk pr review-context --expected-pr 42",
    "perk pr review-context --json --expected-pr 42",
    "perk pr review-context --expected-pr 42 --json --stack",
    "perk pr review-context --expected-pr 42 --stack --json",
    "perk pr review-context --pr 42",
    "perk pr review-context --pr 42 --stack",
    "perk pr review-context --pr 42 --json --stack",
    "perk pr review-context --stack --pr 42 --json",
    "perk pr review-context --json --pr 42",
    "perk pr review-context --pr 42 --local --json",
    "perk pr review-context --pr 42 --json --pr 43 --json",
    "perk pr review-context --pr 42 --expected-pr 42 --json",
    "perk pr review-contextual --expected-pr 42 --json",
    "perk pr review-contexts --pr 42 --json",
    // The pinned form: only WITH --stack, base + at least two heads, full lowercase 40-hex shas,
    // `<pr>=<sha>` pairs, --json last — every deviation stays blocked.
    `perk pr review-context --pr 42 --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --json`,
    `perk pr review-context --pr 42 --stack --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0.slice(0, 39)} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A.toUpperCase()} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B}x --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 0=${SHA_A} --pin-head 42=${SHA_B} --json`,
    `perk pr review-context --pr 42 --stack --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --pin-base ${SHA_0} --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --local --json`,
    `perk pr review-context --pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B}`,
    `perk pr review-context --expected-pr 42 --stack --pin-base ${SHA_0} --pin-head 41=${SHA_A} --pin-head 42=${SHA_B} --json`,
    "perk pr feedback",
    "perk pr feedback --pr 42 --json",
    "perk pr feedback-extra --json",
    "perk pr review-post --json",
    "gh api user",
    ...["0", "01", "-1", "1.5", "+1", "N", "42x"].flatMap((n) => [
      `perk pr review-context --expected-pr ${n} --json`,
      `perk pr review-context --pr ${n} --json`,
      `perk pr review-context --pr ${n} --stack --json`,
    ]),
  ])
    assert.equal(isReadOnlyBashCommand(command), false, command);
});

test("isReadOnlyBashCommand: blocks destructive / non-allowlisted commands", () => {
  for (const cmd of [
    "rm -rf /tmp/x",
    "mv a b",
    "cp a b",
    "echo hi > file.txt", // redirection write
    "cat a >> file.txt", // append redirection
    "cat a &> file.txt", // &> writes both streams to a file (still destructive)
    "git commit -m wip",
    "git push origin main",
    "npm install left-pad",
    "sudo reboot",
    "chmod +x script.sh",
    "some-unknown-binary --flag", // not in the safe table at all
    "git status && rm file", // destructive wins over a safe prefix
    "git status && some-unknown-binary", // a non-safe command at a later command position
    "ls | rm -rf x", // pipe whose second segment is destructive
    "perk objective create foo", // mutating objective subcommands stay blocked
    "perk objective node 1.1",
    "perk objective node 2.3 --status done", // sibling mutating verb stays blocked
    "perk objective node-engagement 7 --node 2.1 > f", // destructive-wins blocks the redirect
    "perk objective reconcile",
    "perk init", // would allow scaffolding writes
    "perk obj node 2.3", // the `n` alias must not match `node`
    "gh api repos/{owner}/{repo}/issues -f title=x", // gh api blocked (can POST/PATCH)
    "gh api user", // even GET-shaped gh api stays blocked
    "gh pr create --fill", // mutating gh subcommands stay blocked
    "gh issue edit 12",
    "gh pr merge 7",
    "gh repo clone o/r",
    "gh issue view 12 > out.txt", // destructive-wins blocks the redirect
    "npx some-other-pkg", // npx entry is anchored to agent-browser — bare npx stays blocked
    "agent-browser screenshot > shot.png", // >-redirect destructive veto wins over the safe entry
    "code file.ts", // the `code` editor at a command position: refused by the allowlist alone
    "ls; code .", // …after a `;` sequencer
    "echo hi && code .", // …after `&&`
    "cat $(code y)", // …inside a command substitution
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a non-allowlisted command at ANY command position is blocked", () => {
  for (const cmd of [
    // positions the leading-word check never saw
    "echo hi\nnode -e \"require('fs').writeFileSync('x','y')\"",
    "echo $(python -c \"open('x','w').write('y')\")",
    "echo ok & python -c \"open('x','w')\"",
    'echo "a\\"" ; python -c "open(\'x\',\'w\')"',
    "env X=1 node -e \"require('fs').writeFileSync('x','y')\"",
    "echo `python -c x`",
    'echo "$(python -c x)"',
    "X=$(python -c x)",
    "diff <(python -c x) f",
    "<echo python -c pass", // a leading redirection's operand is never the command
    "<<< echo python -c pass",
    "< $(python -c x) cat",
    "echo $'a\\'b'; python -c \"print(42)\" # '", // ANSI-C `\'` does not close the quote
    "echo $'\\''; python -c pass # '",
    // exec forms, incl. a wrapper at the exec position
    "find . -exec rm {} \\;",
    "find . -exec python -c x {} \\;",
    "find . -execdir python {} \\;",
    "find . -ok python {} \\;",
    "find . -okdir python {} \\;",
    "find . -exec env python -c pass {} \\;",
    "find . -maxdepth 0 -exec env python -c pass \\;",
    "find . -exec timeout 5 python {} \\;",
    "find . -exec env {} \\;", // `{}` is the command word after `env`: running the found file
    "fd -x python",
    "fd --exec python",
    "fd -X python",
    "fd --exec-batch python",
    "fd -x env python",
    // wrappers reach the wrapped command; a bare non-allowlisted wrapper is its own command
    "timeout 5 python -c x",
    "timeout 30",
    "xargs python -c x",
    "find . | xargs",
    "nice python",
    "time python",
    "nohup python",
    "command python",
    "env -i python",
    // keywords
    "if python; then ls; fi",
    "while python; do ls; done",
    'for f in x; do python "$f"; done',
    "for f in $(python -c x); do ls; done",
    "{ python; }",
    "! python",
    // an expanding heredoc body is scanned; lines after the terminator are commands
    "cat <<EOF\n$(python -c x)\nEOF",
    "cat <<EOF\nbody\nEOF\npython -c x",
    "cat <<EOF\nEO\\\nF\npython -c pass\nEOF", // bash joins `EO\⏎F` into the terminator
    "echo `echo \\`python -c pass\\``", // nested backquote escape: refused
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: what the walker does not model is refused", () => {
  for (const cmd of [
    "$CMD",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "${CMD} x",
    '"$CMD" x',
    "ls; $EDITOR x",
    "$(cat cmd)",
    "echo 'a",
    'echo "a',
    "echo $(ls",
    "ls )",
    "cat <",
    "cat <<EOF\nbody",
    "env -S 'python -c x' echo",
    "time -o out rg foo",
    "timeout rg foo",
    "xargs -a list grep foo",
    "(cd x && ls)",
    "foo() { ls; }; foo",
    "A=(1 2); ls",
    "echo $((1+1))",
    "case x in a) ls;; esac",
    "[[ -f x ]] && cat x",
    "ls \\",
    "A=1", // nothing to run
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("readOnlyBashVerdict: a refusal names its reason", () => {
  const reason = (cmd: string) => {
    const verdict = readOnlyBashVerdict(cmd);
    return verdict.allowed ? "allowed" : verdict.reason;
  };
  assert.ok(reason("git status && rm f").startsWith("matches the destructive veto /\\brm\\b/i"));
  assert.equal(reason("echo 'a"), "unterminated quote");
  assert.equal(reason("cd x && python -c 1"), "not allowlisted: python -c 1");
  assert.equal(reason("A=1"), "no command to run (only assignments, comments or whitespace)");
  assert.equal(reason("$CMD"), REFUSAL_REASONS["dynamic-command-word"]);
  assert.equal(reason("env -Q ls"), REFUSAL_REASONS["wrapper-usage"]);
  assert.equal(reason("(ls)"), REFUSAL_REASONS["unmodeled-syntax"]);
  // only the first line of the offending command, cut to 100 characters
  assert.equal(
    reason(`ls; python -c '${"x".repeat(200)}'\nmore`),
    `not allowlisted: python -c '${"x".repeat(89)}…`,
  );
  assert.deepEqual(readOnlyBashVerdict("git status"), { allowed: true });
});

test("the bash block message keeps its two-line head and appends the reason", async () => {
  const h = gateFixture(() => true);
  const result = (await h.call("tool_call", {
    toolName: "bash",
    input: { command: "cd x && python -c 1" },
  })) as { block?: boolean; reason?: string } | undefined;
  assert.equal(result?.block, true);
  assert.equal(
    result?.reason,
    "perk read-only mode: command blocked (not allowlisted).\nCommand: cd x && python -c 1\nReason: not allowlisted: python -c 1",
  );
});

test("live round-trip: gate enforces read-only, then releases on mode=read-write", async () => {
  const cwd = scaffoldRepo();
  // Two mode entries: navigating across them flips the gate (per-field LWW rebuild + session_tree
  // re-sync). No run_id/pi_session_id -> session_start takes the warm-mint "none" path (mints a run_id).
  const file = plantSession(cwd, [{ mode: "read-only" }, { mode: "read-write" }]);
  const h = await loadPerkSession({ cwd, sessionManager: SessionManager.open(file) });
  try {
    // The two planted mode entries lead the branch (later model/thinking entries are appended
    // by session setup); ids[0] = read-only, ids[1] = read-write.
    const ids = h.entryIds();
    const [readOnlyId, readWriteId] = ids as [string, string];

    // Full-branch rebuild = read-write (LWW last) -> gate starts OFF; writes allowed.
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);

    // Navigate to the read-only entry -> session_tree re-sync turns the gate ON.
    await h.navigateTo(readOnlyId);
    assert.equal(h.sentinel()?.mode, "read-only");

    const blockedWrite = await h.emitToolCall("write", { path: "x", content: "y" });
    assert.equal(blockedWrite?.block, true, "write blocked while read-only");
    const blockedEdit = await h.emitToolCall("edit", { path: "x" });
    assert.equal(blockedEdit?.block, true, "edit blocked while read-only");

    const blockedBash = await h.emitToolCall("bash", { command: "rm -rf build" });
    assert.equal(blockedBash?.block, true, "unsafe bash blocked while read-only");

    const safeBash = await h.emitToolCall("bash", { command: "git status" });
    assert.equal(safeBash?.block, undefined, "safe bash allowed while read-only");

    // Navigate back to the read-write entry -> gate turns OFF; writes allowed again.
    await h.navigateTo(readWriteId);
    assert.equal(h.sentinel()?.mode, "read-write");
    assert.equal((await h.emitToolCall("write", { path: "x", content: "y" }))?.block, undefined);
  } finally {
    h.dispose();
  }
});

test("mode-context dedups against a prior copy on the branch (once-only per live copy)", async () => {
  const cwd = scaffoldRepo();
  const file = plantRawSession(cwd, [
    { custom: { type: "perk:workflow-state", data: { run_id: "01RID", mode: "read-only" } } },
    { custom: { type: "perk:mode-context", data: { content: "[READ-ONLY MODE]\nprior copy" } } },
  ]);
  const h = await loadPerkSession({
    cwd,
    sessionManager: SessionManager.open(file),
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === "perk:mode-context"),
      false,
      "prior [READ-ONLY MODE] copy on branch → no re-injection",
    );
  } finally {
    h.dispose();
  }
});

test("mode-context is once-only per SELECTED BRANCH: a copy compaction summarized out of context does not re-inject", async () => {
  // The read-only guidance is history-scoped, not live-context-scoped: the full-branch scan is
  // the authority, so a hidden copy Pi has compacted away (it stays on the branch) still
  // suppresses. Enforcement (tool_call) never depended on the prose being readable.
  const cwd = scaffoldRepo();
  const manager = SessionManager.inMemory(cwd);
  manager.appendCustomEntry("perk:workflow-state", { run_id: "01RID", mode: "read-only" });
  manager.appendCustomMessageEntry("perk:mode-context", "[READ-ONLY MODE]\nprior copy", false);
  const kept = manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text: "recent work" }],
    api: "t",
    provider: "t",
    model: "t",
    usage: {},
    stopReason: "stop",
    timestamp: 1,
  } as never);
  manager.appendCompaction("a summary that never mentions the marker", kept, 100);
  assert.equal(
    manager
      .buildContextEntries()
      .some((entry) => entry.type === "custom_message" && entry.customType === "perk:mode-context"),
    false,
    "the copy is out of Pi's projected context",
  );
  const h = await loadPerkSession({
    cwd,
    sessionManager: manager,
    env: { PERK_RUN_ID: undefined },
  });
  try {
    assert.equal(h.workflowState().mode, "read-only");
    const injected = await h.emitBeforeAgentStart();
    assert.equal(
      injected.some((m) => m.customType === "perk:mode-context"),
      false,
      "the historical copy on the full branch still suppresses",
    );
    assert.equal(
      (await h.emitToolCall("write", { path: "x", content: "y" }))?.block,
      true,
      "enforcement holds regardless",
    );
  } finally {
    h.dispose();
  }
});

test("REFINEMENT_READ_ONLY_TOOLS: the exact refinement gate-ON selection (no claim/other-draft/save/spawn)", () => {
  assert.deepEqual(REFINEMENT_READ_ONLY_TOOLS, [
    "read",
    "grep",
    "find",
    "ls",
    "bash",
    "ask_user_question",
    "plan_review",
    "objective_refinement_draft",
    ...WEB_RESEARCH_TOOLS,
    ...LINEAR_READ_TOOLS,
    ...FFF_SEARCH_TOOLS,
  ]);
  for (const forbidden of [
    "objective_node",
    "plan_draft",
    "objective_draft",
    "gist_draft",
    "plan_save",
    "objective_save",
    "gist_save",
    "explore_objective_node",
    "run_scout_wave",
    "subagent",
    "edit",
    "write",
  ]) {
    assert.equal(REFINEMENT_READ_ONLY_TOOLS.includes(forbidden), false, forbidden);
  }
  // Existing stages never gain the refinement draft: it is absent from READ_ONLY_TOOLS.
  assert.equal(READ_ONLY_TOOLS.includes("objective_refinement_draft"), false);
  assert.equal(gatedToolsFor("objective-refine"), REFINEMENT_READ_ONLY_TOOLS);
  for (const stage of [null, "plan", "objective-plan", "objective-author", "gist-author", "bogus"])
    assert.equal(gatedToolsFor(stage), READ_ONLY_TOOLS, String(stage));
});

test("gate ON in the refinement stage: the active set, the tool_call backstop and the mode flavor follow the stage", async () => {
  const h = gateFixture(() => false);
  // An already-gated UNBOUND session (default flavor installed) that then enters refinement.
  h.gate.syncFromState("read-only", undefined);
  assert.deepEqual(h.installed.at(-1), READ_ONLY_TOOLS);
  assert.equal((await h.call("before_agent_start"))?.message?.content, READ_ONLY_CONTEXT);
  assert.equal(
    (await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }))?.block,
    true,
    "the refinement draft is NOT allowlisted outside the refinement stage",
  );
  assert.equal(await h.call("tool_call", { toolName: "objective_node", input: {} }), undefined);

  h.gate.syncFromState("read-only", "objective-refine");
  assert.deepEqual(h.installed.at(-1), REFINEMENT_READ_ONLY_TOOLS);
  assert.equal(
    await h.call("tool_call", { toolName: "objective_refinement_draft", input: {} }),
    undefined,
  );
  assert.equal(await h.call("tool_call", { toolName: "plan_review", input: {} }), undefined);
  assert.equal(await h.call("tool_call", { toolName: "read", input: {} }), undefined);
  for (const toolName of [
    "objective_node",
    "plan_draft",
    "objective_draft",
    "gist_draft",
    "plan_save",
    "objective_save",
    "gist_save",
    "run_scout_wave",
    "subagent",
    "edit",
    "write",
    "foreign_mutator",
  ]) {
    assert.equal(
      (await h.call("tool_call", { toolName, input: {} }))?.block,
      true,
      `${toolName} blocked in the gated refinement stage (late-activation backstop)`,
    );
  }
  assert.equal(
    (await h.call("tool_call", { toolName: "bash", input: { command: "touch x" } }))?.block,
    true,
    "no new bash allowance",
  );
  // The flavor: names the actual writer with a distinct marker; the default marker is not a
  // substring, so a prior default copy on the branch never masks the refinement flavor.
  const injected = (await h.call("before_agent_start"))?.message?.content;
  assert.equal(injected, REFINEMENT_READ_ONLY_CONTEXT);
  assert.ok(injected?.includes("[READ-ONLY REFINEMENT MODE]"));
  assert.ok(injected?.includes("objective_refinement_draft is the sole sanctioned write"));
  assert.equal(injected?.includes("plan_draft"), false);
  assert.equal(REFINEMENT_READ_ONLY_CONTEXT.includes("[READ-ONLY MODE]"), false);
  assert.ok(READ_ONLY_CONTEXT.includes("plan_draft is the sole sanctioned write"));

  // Gate ON: only the current flavor survives in model context — the stale plan_draft-only block
  // is dropped; user content and marker-less mode entries are untouched.
  const stale = { customType: "perk:mode-context", content: READ_ONLY_CONTEXT };
  const current = { customType: "perk:mode-context", content: REFINEMENT_READ_ONLY_CONTEXT };
  const user = { role: "user", content: "please [READ-ONLY MODE] keep me" };
  const bare = { customType: "perk:mode-context" };
  assert.deepEqual(await h.call("context", { messages: [stale, current, user, bare] }), {
    messages: [current, user, bare],
  });
  assert.equal(await h.call("context", { messages: [current, user, bare] }), undefined);

  // Gate OFF: both flavors strip (the injected type wholesale + the marker-bearing user echoes).
  h.gate.exit();
  const off = await h.call("context", {
    messages: [stale, current, { role: "user", content: "[READ-ONLY REFINEMENT MODE] echo" }, user],
  });
  assert.deepEqual(off, { messages: [] });
});
