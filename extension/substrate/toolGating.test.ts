// The tool-gating primitive: pure policy matrix + a live read-only round-trip driven
// through a REAL bound AgentSession via the harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import {
  loadPerkSession,
  plantRawSession,
  plantSession,
  scaffoldRepo,
} from "../testing/harness.ts";
import {
  FFF_SEARCH_TOOLS,
  isReadOnlyBashCommand,
  READ_ONLY_CONTEXT,
  READ_ONLY_TOOLS,
  SUBAGENT_CHILD_TOOLS,
} from "./toolGating.ts";

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
    // The delegation carve-in (the gated objective-plan explorer spawn).
    "subagent",
    "wait",
    "subagent_supervisor",
    "intercom",
    // The child-side carve-in (gated adopt-children keep the engine's injected tools).
    "structured_output",
    "contact_supervisor",
    "subagent_wait",
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
    "cd repo && agent-browser screenshot", // per-segment acceptance with a cd prefix
    "find . -name '*.ts'",
    "wc -l file",
    "sed -n '1,10p' file",
    "cat x 2>&1", // fd duplication is not a file write
    "grep foo bar 2>&1",
    "ls -la 1>&2",
    "cat foo 2>/dev/null", // /dev/null redirect is not a file write
    'grep -rn "user-docs" README.md 2>/dev/null',
    "cd /tmp && grep foo bar", // cd prefix + per-segment safe
    "cd repo && perk objective show 453 2>&1 | head -200", // reported example 1
    `ls tests/ | grep -iE 'doc|user|cli|link'; echo "---"; grep -rl "user-docs" tests/ 2>/dev/null`, // reported example 3 (quoted | does not split; 2>/dev/null allowed)
    `find tests -name '*.py' | grep -iE 'doc|user|cli' ; echo --- ; grep -rl "user-docs" tests 2>/dev/null`, // reported example 4
    "perk objective show", // perk's read-only objective queries
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
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), true, `expected allowed: ${cmd}`);
  }
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
    "for f in a b c; do echo $f; done", // leading `for` segment non-safe → loops stay blocked
    "git status && some-unknown-binary", // per-segment tightening: second segment non-safe
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
    "code file.ts", // the `code` editor in command position stays blocked
    "ls; code .", // …after a `;` sequencer
    "echo hi && code .", // …after `&&`
    "cat $(code y)", // …inside a command substitution
  ]) {
    assert.equal(isReadOnlyBashCommand(cmd), false, `expected blocked: ${cmd}`);
  }
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
