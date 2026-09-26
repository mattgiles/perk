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
    "env -i FOO=bar", // a wrapper chain with no command word is its own command
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "echo ${x/;/,}; ls", // ${…} is one unit: its `;` is not an operator
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
    // a `#` inside ${…} is not a comment, so the later command is still checked
    `echo \${x:-a #b}; node -e "require('fs').writeFileSync('x','y')"`,
    // a wrapper operand's expansion could split into the command itself
    `PAYLOAD='DROP node -e x'; env -u $PAYLOAD ls`,
    // xargs supplies the bare env's command from its input
    `printf '%s\\0' node -e x | xargs -0 env`,
    // a delimiter whose quote-removed value is unknown, and one whose `\`-newline is not quoting
    "cat <<$'echo'\necho\nnode -e x\n$'echo'",
    "cat <<E\\\nOF\n$(node -e x)\nEOF",
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

test("isReadOnlyBashCommand: the census-driven read-only forms are allowed", () => {
  for (const cmd of [
    // git's pure reads, any arguments, behind the admitted global options
    "git rev-parse HEAD",
    "git rev-parse --show-toplevel",
    "cd $(git rev-parse --show-toplevel) && rg foo",
    "git status --short && git rev-parse HEAD && git log -1 --format='%H %s'",
    "git worktree list --porcelain",
    "git blame -L 1,5 f",
    "git grep -n foo -- src",
    "git grep -o -e foo", // `-o` (only-matching) is not the pager flag `-O`
    "git check-ignore -v p",
    "git merge-base --is-ancestor a HEAD",
    "git rev-list --count HEAD",
    "git cat-file -t abc",
    "git describe --tags",
    "git name-rev HEAD",
    "git ls-files docs",
    "git ls-tree -r HEAD",
    "git ls-remote origin",
    "git for-each-ref --format='%(refname)' refs/heads",
    "git show-ref --heads",
    "git shortlog -sn",
    "git count-objects -v",
    "git range-diff a^..a b^..b",
    "git show abc --pretty=format: | git patch-id --stable",
    "git show 4a71:skills/x/SKILL.md | git hash-object --stdin",
    "git hash-object f",
    "git diff -Oorder.txt", // diff's `-O<orderfile>` only reads
    "git --version",
    "git version",
    "git -C /other/repo diff --stat v1 v2 -- p",
    'git -C "$(pwd)" status',
    "git --no-pager log -1",
    "git -P log -1",
    // symbolic-ref: exactly one ref
    "git symbolic-ref HEAD",
    "git symbolic-ref --short -q HEAD",
    "git symbolic-ref HEAD 2>/dev/null",
    // reflog: the positive list
    "git reflog",
    "git reflog show --format='%h %gs' -12 plan-2354",
    "git reflog -12 --date=iso-strict",
    "git reflog --all",
    "git reflog list",
    "git reflog exists refs/heads/main",
    // tag: a list-implying flag, or bare with display modifiers
    "git tag",
    "git tag --list",
    "git tag -l 'v*'",
    "git tag --contains HEAD",
    "git tag -n5",
    "git tag --sort=-v:refname",
    "git tag --points-at HEAD",
    "git tag --merged main",
    "git branch --all --contains HEAD && git tag --contains HEAD | head -20",
    // branch: a list-implying flag, or bare with display modifiers
    "git branch",
    "git branch -v",
    "git branch -vv",
    "git branch --show-current",
    "git branch -a",
    "git branch --all",
    "git branch -r",
    "git branch -l",
    "git branch --list 'plan-*'",
    "git branch -a --contains abc",
    "git branch --merged main",
    "git branch --no-merged",
    "git branch --points-at HEAD",
    "git branch --format='%(refname:short)' --sort=-committerdate",
    "git branch --format '%(refname)' -a",
    "git branch -v 2>&1",
    "git branch \\\n  --list 'x*'", // a continued line is one command
    // remote, stash, config: the read forms
    "git remote",
    "git remote -v",
    "git remote --verbose",
    "git remote show origin",
    "git remote get-url origin",
    "git remote -v show origin",
    "git stash list",
    "git stash show -p stash@{0}",
    "git stash list --format='%gd %s'",
    "git config --get user.name",
    "git config --get-regexp '^alias\\.'",
    "git config --list",
    "git config -l",
    "git config --list --show-origin",
    "git config --local --get core.hooksPath",
    "git config core.hooksPath",
    "git config --show-origin diff.renames",
    "git config get user.name",
    "git config list",
    "git config --global --get user.email",
    // everyday read-only utilities
    "nl -ba shared/contracts.md | sed -n '736,757p'",
    "shasum -a 256 f",
    "sha256sum f",
    "sha1sum f",
    "md5 f",
    "md5sum f",
    "readlink /usr/local/bin/pi",
    "realpath .",
    'basename "$f"',
    'dirname "$f"',
    "test -f x && cat x",
    "[ -f x ] && cat x",
    "[ -d dir ]",
    "true",
    "false",
    "ls x 2>/dev/null || true",
    "read -r line < f",
    'while read -r l; do echo "$l"; done < f',
    "set -eu\nprintf '%s\\n' '--- pi ---'\ncommand -v pi || true",
    "set -o pipefail; rg foo | head",
    "column -t f",
    "tr ',' '\\n' < f",
    "cut -c1-200 f",
    "cut -d: -f1 f",
    "paste a b",
    "comm -12 a b",
    "tac f",
    "rev f",
    "od -c f | head",
    "xxd f | head",
    "xxd -l 16 -s 0x10 f",
    "xxd -r -p f",
    "xxd -p f",
    "strings f | grep foo",
    "sleep 1",
    "fold -w 180 f",
    "cmp a b",
    "command -v pi",
    "command -V pi",
    "command -pv pi",
    // sed in every form but -i
    "sed -n '1,10p' f",
    "sed 's/a/b/' f",
    "sed -E 's/(a)/\\1/' f",
    "sed -e 's/a/b/' -e 's/c/d/' f",
    "sed '1d;$d' f",
    "sed -n '/^```markdown$/,/^```$/p' d.md | sed '1d;$d' | wc -c",
    "sed 's/x/y/' f 2>/dev/null",
    "sed -n '/-i/p' f", // a quoted `-i` INSIDE a script word is not the flag
    // perk / pi read verbs
    "perk --version",
    "perk --help",
    "perk plan --help",
    "perk objective node --help",
    "perk skills create --help",
    "perk objective --help 2>&1",
    "perk init --help", // Click's eager help exits before the command body runs
    "perk learn docs-check",
    "perk learn docs-check --json",
    "pi --version",
    "pi --version 2>/dev/null | head -1",
    // already admitted — regression pins
    "date -u +%Y-%m-%dT%H:%M:%SZ",
    "stat -f '%Sm %N' f",
    "npm audit",
    "npm audit --json",
    "find . -name '*.ts' -print",
    "find . -type f -print0 | xargs -0 grep -l foo",
    "sort -k1,1 f",
    "sort -r f",
    "tree -L 2",
    "tree -a",
    // a `--sort`/`--tree` flag is not the `sort`/`tree` command
    "rg --sort path -o 'x' f",
    "eza --tree -o",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: an argument walk never crosses into the next command", () => {
  // Each later command's flag would match the earlier command's writer row if the walk crossed
  // the newline or the operator.
  for (const cmd of [
    "git branch\nwc -c README.md",
    "git config --get user.name\nrg -e needle README.md",
    "git tag\nsed -n 1p f",
    "git remote -v; sort -k1 f",
    "git branch -a; rg -m 1 foo f",
    "git hash-object f\nrg -w x f",
    "sed -n 1p f\nrg -i x f",
    "find . -name x\nrg --fixed-strings -delete f",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: heredoc data is data", () => {
  for (const cmd of [
    "wc -c <<'EOF'\na `git add` here and a > here and rm -rf and `npm ci`\nEOF",
    "cat <<EOF\n-> arrow => fat arrow git push\nEOF",
    "cat <<-EOF | wc -l\n\t> quoted\n\tEOF",
    "cat <<'EOF' | wc -c\nsed -i x\nEOF",
    "echo $(cat <<X\n> inside a substitution's heredoc\nX\n)",
    "wc -c <<'EOF'\n---\ntitle: x\n---\nEOF",
    "cat <<A <<'B' | wc -c\nrm a\nA\nmv b\nB",
    "cat <<EOF\nrm in prose, $(git rev-parse HEAD) -> here\nEOF", // a read-only substitution beside vetoable data
    "cat <<EOF\n`pwd` > prose\nEOF",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: argument-level writers and non-list forms are blocked", () => {
  for (const cmd of [
    // branch: a positional without a list-implying flag, or any writer flag anywhere
    "git branch foo",
    "git branch -v foo",
    "git branch foo main",
    "git branch -m old new",
    "git branch -M new",
    "git branch -c a b",
    "git branch -C a b",
    "git branch -u origin/main",
    "git branch --set-upstream-to=origin/main",
    "git branch --unset-upstream",
    "git branch --move a b",
    "git branch --copy a b",
    "git branch --edit-description",
    "git branch -d foo",
    "git branch -D foo",
    "git branch '-D' foo",
    'git branch "-D" foo',
    "git branch \\-D foo",
    "git branch --delete foo",
    "git branch -rd origin/foo",
    "git branch -a -D foo",
    "git branch -f foo HEAD",
    "git branch --force foo",
    "git branch -t foo origin/foo",
    "git branch --track foo origin/foo",
    "git branch --create-reflog foo",
    "git branch --no-track foo",
    "git branch --list -D foo",
    "git branch --format=%(refname) foo",
    "git branch \\\n  -D foo", // a continued line is one command
    // remote
    "git remote add o url",
    "git remote remove o",
    "git remote rm o",
    "git remote rename a b",
    "git remote set-url o url",
    "git remote set-head o -a",
    "git remote set-branches o main",
    "git remote prune o",
    "git remote update",
    "git remote -v add o url",
    "git remote 'add' o url",
    // worktree
    "git worktree add /tmp/x",
    "git worktree remove x",
    "git worktree move a b",
    "git worktree prune",
    "git worktree lock x",
    "git worktree unlock x",
    "git worktree repair",
    "git worktree",
    // tag
    "git tag v1",
    "git tag v1 HEAD",
    "git tag -a v1 -m msg",
    "git tag -am msg v1",
    "git tag '-a' v1 -m msg",
    "git tag -s v1",
    "git tag -u key v1",
    "git tag -d v1",
    "git tag --delete v1",
    "git tag -f v1",
    "git tag --force v1",
    "git tag -F msgfile v1",
    "git tag -e v1",
    "git tag -l -d v1",
    "git tag --sort=x v1",
    // stash: every form but list/show
    "git stash",
    "git stash push",
    "git stash save x",
    "git stash pop",
    "git stash apply",
    "git stash drop",
    "git stash clear",
    "git stash branch b",
    "git stash -u",
    "git stash -q",
    "git stash create",
    "git stash store x",
    // notes, refs, reflog actions, the remaining whole-subcommand mutators
    "git notes add -m x",
    "git notes",
    "git update-ref refs/heads/x abc",
    "git update-ref -d refs/heads/x",
    "git symbolic-ref HEAD refs/heads/x",
    "git symbolic-ref -d refs/x",
    "git symbolic-ref --delete refs/x",
    "git symbolic-ref -m msg HEAD refs/heads/x",
    "git symbolic-ref",
    "git reflog expire --all",
    "git reflog delete HEAD@{1}",
    "git reflog drop --all",
    "git reflog drop refs/heads/x",
    "git reflog plan-2354", // ref-first — over-strict, pinned
    "git fetch",
    "git switch main",
    "git restore f",
    "git am p",
    "git apply p",
    // config: action flags, the subcommand-form writers, the legacy `<key> <value>` set
    "git config user.name x",
    "git config --global user.name x",
    "git config --add x y",
    "git config --unset x",
    "git config --unset-all x",
    "git config --replace-all x y",
    "git config --rename-section a b",
    "git config --remove-section a",
    "git config --edit",
    "git config -e",
    "git config set user.name x",
    "git config unset x",
    "git config edit",
    "git config rename-section a b",
    "git config remove-section a",
    "git config 'set' k v",
    // hash-object -w, --output
    "git hash-object -w f",
    "git hash-object -wt blob f",
    "git hash-object '-w' f",
    "git hash-object -w --stdin",
    "git diff --output=x.patch",
    "git log --output x",
    "git show --output=f HEAD",
    // global options: `-c`/`--git-dir` never admitted; `-C` keeps every writer veto
    "git -c alias.x='!python -c 1' x",
    "git -c core.pager=cat log",
    "git --git-dir=/x status",
    "git -C /x branch -D foo",
    "git -C /x stash pop",
    "git -C /x tag v1",
    "git -C /x remote add o u",
    // find's writers
    "find . -name '*.log' -delete",
    "find . -delete",
    "find . '-delete'",
    "find . -fprint out.txt",
    "find . -fprint0 out",
    "find . -fprintf out '%p\\n'",
    "find . -fls out",
    // sed -i, in every spelling the veto reads through
    "sed -i 's/a/b/' f",
    "sed -i.bak 's/a/b/' f",
    "sed '-i.bak' 's/a/b/' f",
    "sed \"-i\" 's/a/b/' f",
    "sed \\-i 's/a/b/' f",
    "sed -i'' 's/a/b/' f",
    "sed -ni 's/a/b/p' f",
    "sed -Ei 's/a/b/' f",
    "sed -e 's/a/b/' -i f",
    "sed --in-place 's/a/b/' f",
    "sed --in-place=.bak 's/a/b/' f",
    "sed -n '1p' f -i",
    "sed -I 's/a/b/' f",
    // npm audit fix, sort -o, tree -o, xxd's output operand
    "npm audit fix",
    "npm audit fix --force",
    "sort -o out f",
    "sort -o./out.txt f",
    "sort -ro out f",
    "sort '-o' out f",
    "sort --output=out f",
    "sort --output out f",
    "tree -o out.txt",
    "tree -ao out",
    "tree -oout",
    "xxd in out",
    "xxd -r in out",
    "xxd -p f out",
    "xxd -l 16 f out",
    // an admitted utility never admits the next command
    "command -v python && python -c 1",
    "test -f x && rm x",
    "true && python -c 1",
    "set -e; python -c 1",
    "read -r x < f && python -c 1",
    "sleep 5; rm x",
    "tr a b < f > g",
    "nl f > out",
    "git rev-parse HEAD > sha",
    // perk / pi: only the enumerated read verbs
    "perk init",
    "perk learn docs-sync",
    "perk learn docs",
    "perk plan 12",
    "perk --version && perk init",
    "perk objective node-add 2544 --phase 1 --description --help", // an option consumes `--help` as its value
    "perk plan --force --help",
    "perk plan 12 --help", // over-strict on non-identifier words — pinned
    "perk objective node 2.3 --status done --help",
    "perk plan -- --help",
    // perk registers only `--help`: `-h` reaches the command body as an ordinary argument
    "perk -h",
    "perk skills create review-probe -h",
    'pi -p "x"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: a list form holds only when git's effective mode is list mode", () => {
  // each creates the named branch/tag or writes a config file in a real repository
  for (const cmd of [
    // a negation cancels the list flag (abbreviated too)
    "git branch --list --no-list b1",
    "git branch --show-current --no-show-current b2",
    "git branch --points-at HEAD --no-points-at b3",
    "git branch --list --no-lis b9",
    "git tag --points-at HEAD --no-points-at t2",
    // a list-flag lookalike consumed as a value-taking option's value
    "git branch --format --list b4",
    "git branch --sort --list b5",
    "git tag --format -l t3",
    "git config --file --get a.b c",
    "git config -f --list a.b c",
    // a quoted or escaped option is still an option, never a positional
    "git branch --list '--no-list' b6",
    "git branch --list \\--no-list b7",
    // an unlisted option in a list form
    "git branch -a --bogus foo",
    // a flag lookalike inside a quoted value is no list flag
    'git branch --format "x\\" -a \\"" b8',
    // over-strict, pinned: a substitution's inner words read as the command's own
    "git branch -a --contains $(git rev-list --all -1)",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
  // …while list forms with values, attached filters and display options still pass
  for (const cmd of [
    "git branch --contains=HEAD --no-color",
    "git branch --merged=main -v 'plan-*'",
    "git tag -l --sort=-v:refname --format '%(refname)' 'v*'",
    "git config --get-regexp --file x.cfg 'a\\.' ",
    "git config --show-origin --get-all remote.origin.fetch",
    'c=$(git rev-list --all -1); git branch -a --contains "$c"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: an argument walk crosses escaped operators, substitutions and backticks", () => {
  for (const cmd of [
    // the writer flag follows an escaped `;`, a nested operator or a `${…}` holding one
    "find victim -exec echo {} \\; -delete",
    "git hash-object $(echo input.txt; echo) -w",
    "git hash-object `echo input.txt; echo` -w",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "find . ${x/;/,} -delete",
    'sed "s/a/b/; s/c/d/" -i f',
    // a closing backtick ends the flag word, top-level and inside an expanding heredoc
    "echo `find victim -delete`",
    "cat <<EOF\n`find victim -delete`\nEOF",
    "echo `git branch -D foo`",
    // a nested substitution's own writer flag is judged in its own text
    "cat <<EOF\n$(git hash-object $(echo a; echo) -w)\nEOF",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: exec flags of admitted git subcommands and flag words ending at an operator are blocked", () => {
  for (const cmd of [
    // `git grep -O<cmd>` runs its pager through the shell; `git ls-remote --upload-pack=<cmd>`
    // (hidden alias `--exec`) runs a local command — abbreviations included
    "git grep -Opython x",
    "git grep -O'python3 -c 1' x",
    "git grep -nO x",
    "git grep --open-files-in-pager=python x",
    "git grep --open x",
    "git ls-remote --upload-pack=python .",
    "git ls-remote --upload-pack python .",
    "git ls-remote --up=python .",
    "git ls-remote --exec=python .",
    // a writer flag's word ends at an operator, a newline or a closing `)` as well as a blank
    "find . -delete; ls",
    "find . -delete\nls",
    "find . -delete&& ls",
    "echo $(find . -delete)",
    "git branch -a --unset-upstream; ls",
    "git branch -a --edit-description\nls",
    "git tag -l -d v1; ls",
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

test("isReadOnlyBashCommand: heredoc code is still code", () => {
  for (const cmd of [
    "cat <<EOF > out\nx\nEOF",
    "cat <<'EOF' >> out\nx\nEOF",
    "cat <<EOF\n$(echo x > out)\nEOF",
    "cat <<EOF\n$(printf x > out)\nEOF",
    "cat <<EOF\n$(> out echo x)\nEOF", // a leading redirection inside the substitution
    "cat <<EOF\n$(find . -delete)\nEOF",
    "cat <<EOF\n$(sort -o out f)\nEOF",
    "cat <<EOF\n`sed -i s/a/b/ f`\nEOF",
    "cat <<EOF\n`rm x`\nEOF",
    // biome-ignore lint/suspicious/noTemplateCurlyInString: shell `${…}` text is the point
    "cat <<EOF\n${x:-$(git branch -D foo)}\nEOF",
    "cat <<EOF\n$(rm -rf x)\nEOF",
    "cat <<EOF\n$(python -c 1)\nEOF",
    "bash <<'EOF'\nrm -rf x\nEOF",
    "python <<'PY'\nprint(1)\nPY",
    "sh <<EOF\nls\nEOF",
    "xargs -0 env <<EOF\nX=1 python\nEOF", // a bare `env` after `xargs` is xargs's own command
    "awk '{print > \"f\"}' in", // quoted `>` elsewhere stays vetoed on purpose
    'echo "a > b"',
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
});

// The policy comment's accepted leniencies, pinned so a future tightening is a deliberate change.
test("isReadOnlyBashCommand: recorded leniencies stay as recorded", () => {
  for (const cmd of [
    "sed -f script.sed f", // an in-program writer in a program file is invisible
    "awk -f prog.awk f",
    "find . -type f -print0 | xargs -0 git branch --list", // run-time appended arguments
    "sed -f - f <<'EOF'\nw out\nEOF", // a program read from a literal heredoc
    "sed -'i' 's/a/b/' f", // a quote INSIDE the flag word
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed (recorded leniency): ${cmd}`);
  }
});

test("readOnlyBashVerdict: argument-level and heredoc reasons", () => {
  const reason = (cmd: string) => {
    const verdict = readOnlyBashVerdict(cmd);
    return verdict.allowed ? "allowed" : verdict.reason;
  };
  const VETO = "matches the destructive veto /";
  // explicit writer flags and writer subcommands are vetoed…
  for (const cmd of [
    "git branch -D foo",
    "git stash",
    "find . -delete",
    "sed -i 's/a/b/' f",
    "git reflog drop --all",
  ])
    assert.ok(reason(cmd).startsWith(VETO), cmd);
  // …positional-only write forms fail the allowlist shape
  assert.equal(reason("git branch foo"), "not allowlisted: git branch foo");
  assert.equal(reason("git tag v1"), "not allowlisted: git tag v1");
  // heredoc code meets the redirect row; heredoc data meets nothing
  assert.equal(
    reason("cat <<EOF\n$(echo x > out)\nEOF"),
    "matches the destructive veto /(^|[^<])>(?!>)/",
  );
  assert.deepEqual(readOnlyBashVerdict("wc -c <<'EOF'\nrm -rf x\nEOF"), { allowed: true });
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
