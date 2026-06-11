// P2.T1 — the tool-gating primitive: pure policy matrix + a live read-only round-trip driven
// through a REAL bound AgentSession via the P1.T1 harness (fully offline). See toolGating.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { loadPerkSession, plantSession, scaffoldRepo } from "./testing/harness.ts";
import { isReadOnlyBashCommand, READ_ONLY_TOOLS } from "./toolGating.ts";

test("READ_ONLY_TOOLS: contains plan_review (the plannotator review bridge is callable in plan mode)", () => {
  assert.ok(READ_ONLY_TOOLS.includes("plan_review"));
});

test("READ_ONLY_TOOLS: contains the four pi-web-access research tools (web research during planning)", () => {
  for (const tool of ["web_search", "code_search", "fetch_content", "get_search_content"]) {
    assert.ok(READ_ONLY_TOOLS.includes(tool), `missing ${tool}`);
  }
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
    "find . -name '*.ts'",
    "wc -l file",
    "sed -n '1,10p' file",
    "cat x 2>&1", // fd duplication is not a file write
    "grep foo bar 2>&1",
    "ls -la 1>&2",
    "perk objective show", // perk's read-only objective queries
    "perk objective next",
    "perk obj show 42",
    "perk objective s", // s/n aliases
    "perk obj n",
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
    "perk objective create foo", // mutating objective subcommands stay blocked
    "perk objective node 1.1",
    "perk objective reconcile",
    "perk init", // would allow scaffolding writes
    "perk obj node 2.3", // the `n` alias must not match `node`
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
