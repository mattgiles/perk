import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { readDraftReview } from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import type { ContextPolicyInputs } from "../../substrate/contextPolicy.ts";
import { acquireDraftReviewLock } from "../../substrate/draftReviewLock.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { type BranchEntry, WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { gitInit, scaffoldRepo } from "../../testing/harness.ts";
import type { ReportWave } from "../../waves/reportWave.ts";
import { createDraftReviewActivation } from "./draftReviewActivation.ts";
import { installGistBindings } from "./gist.ts";
import { installObjectiveAuthoringBindings } from "./objectiveAuthoring.ts";
import { installObjectivePlanningBindings } from "./objectivePlanning.ts";
import { installPlanBindings } from "./plan.ts";
import type { ToolResult } from "./review.ts";

/** The non-runner context-policy input the installer tests compose (no runner suppression). */
const NOT_A_RUNNER: ContextPolicyInputs = { runnerChild: () => false };

function deferred<T>() {
  let resolve = (_value: T): void => {
    throw new Error("uninitialized deferred");
  };
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

type Subject = "plan" | "objective" | "gist";
type Tool = {
  name: string;
  execute(
    id: string,
    params: unknown,
    signal: undefined,
    update: undefined,
    ctx: ExtensionContext,
  ): Promise<ToolResult>;
};
const sources = {
  plan: {
    name: "plan-draft.md",
    params: { plan: "# Original\n" },
    changed: { plan: "# Changed\n" },
  },
  objective: {
    name: "objective-draft.json",
    params: {
      prose: "Original",
      title: "Title",
      roadmap: [{ id: "1.1", description: "One" }],
      delivery: "incremental",
    },
    changed: {
      prose: "Original",
      title: "Title",
      roadmap: [{ id: "1.1", description: "One", comment: "invisible change" }],
      delivery: "incremental",
    },
  },
  gist: {
    name: "gist-draft.json",
    params: { prose: "Original", scope: "plan" },
    changed: { prose: "Original", scope: "objective" },
  },
} as const;

function fixture(subject: Subject = "plan", runId: string | null = "RID") {
  const cwd = scaffoldRepo();
  gitInit(cwd, { dirty: false });
  const branch: BranchEntry[] = [
    {
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: {
        ...(runId === null ? {} : { run_id: runId }),
        stage: subject === "plan" ? "plan" : `${subject}-author`,
        mode: "read-only",
      },
    },
  ];
  const tools = new Map<string, Tool>();
  const commands = new Map<string, (args: string, ctx: ExtensionContext) => Promise<void>>();
  const events = new Map<string, ((event: unknown, ctx: ExtensionContext) => void)[]>();
  const notices: string[] = [];
  const messages: string[] = [];
  const calls: string[][] = [];
  let dropPointers = false;
  let dropLinkage = false;
  let failSaveNotice = false;
  let backendWait: (() => Promise<void>) | undefined;
  let editor: (text: string) => Promise<string | undefined> = async (text) => text;
  let verdict = "Skip — decide later (manual /plan-save)";
  let exits = 0;
  const pi = {
    events: {
      emit() {
        assert.fail("first-party fixture must not emit transport requests");
      },
      on() {
        throw new Error("no transport");
      },
    },
    on(name: string, handler: (event: unknown, ctx: ExtensionContext) => void) {
      events.set(name, [...(events.get(name) ?? []), handler]);
    },
    registerTool(tool: Tool) {
      tools.set(tool.name, tool);
    },
    registerCommand(
      name: string,
      spec: { handler: (args: string, ctx: ExtensionContext) => Promise<void> },
    ) {
      commands.set(name, spec.handler);
    },
    registerShortcut() {},
    registerFlag() {},
    appendEntry(customType: string, data: Record<string, unknown>) {
      if (dropPointers && data.session_artifacts !== undefined) return;
      if (
        dropLinkage &&
        (data.active_plan_ref !== undefined || data.active_objective !== undefined)
      )
        return;
      branch.push({ type: "custom", customType, data });
    },
    sendUserMessage(text: string) {
      messages.push(text);
    },
    async exec(_cmd: string, args: string[]) {
      calls.push(args);
      await backendWait?.();
      const payload = args.includes("node")
        ? { comment_updated: true }
        : args.includes("objective")
          ? { objective: { id: "7", url: "https://example.test/7", existed: false } }
          : args.includes("gist")
            ? { gist: { id: "8", url: "https://example.test/8", existed: false }, scope: "plan" }
            : {
                plan_ref: {
                  provider: "github",
                  pr_id: "42",
                  url: "https://example.test/42",
                  labels: ["perk:plan"],
                  objective_id: null,
                },
                issue: { id: "42", url: "https://example.test/42", existed: false },
              };
      return {
        code: 0,
        stdout: JSON.stringify({ success: true, ...payload }),
        stderr: "",
        killed: false,
      };
    },
  } as unknown as ExtensionAPI;
  const ctx = {
    cwd,
    hasUI: true,
    isIdle: () => true,
    sessionManager: { getBranch: () => branch, getSessionId: () => "mutation-session" },
    ui: {
      notify(text: string) {
        if (failSaveNotice && /Saved (plan|objective|gist)/.test(text)) {
          failSaveNotice = false;
          throw new Error("controlled post-save notice failure");
        }
        notices.push(text);
      },
      editor: (_title: string, text: string) => editor(text),
      select: async () => {
        assert.ok(
          !existsSync(join(sessionDataDir(cwd, "RID"), "draft-review.lock")),
          "no claim spans the verdict wait",
        );
        return verdict;
      },
    },
  } as unknown as ExtensionContext;
  const gating = {
    isActive: () => true,
    exit() {
      exits++;
    },
    enter() {},
    syncFromState() {},
  } satisfies ToolGating;
  const reviews = createDraftReviewActivation(pi);
  installPlanBindings(pi, gating, reviews, NOT_A_RUNNER);
  installObjectiveAuthoringBindings(pi, gating, reviews, NOT_A_RUNNER);
  installGistBindings(pi, gating, reviews, NOT_A_RUNNER);
  // The explorer wave is unrelated; any accidental use fails rather than bypassing a guard.
  installObjectivePlanningBindings(pi, gating, {} as ReportWave, reviews);
  const session = openBranchWorkflowSession(pi, ctx);
  const invoke = async (name: string, params: unknown = {}) => {
    const tool = tools.get(name);
    assert.ok(tool, `registered ${name}`);
    return tool.execute("actual-tool-id", params, undefined, undefined, ctx);
  };
  const command = async (name: string) => {
    const handler = commands.get(name);
    assert.ok(handler, `registered /${name}`);
    await handler("Explicit title", ctx);
  };
  const draft = (changed = false) =>
    invoke(`${subject}_draft`, changed ? sources[subject].changed : sources[subject].params);
  const record = () => {
    const result = readDraftReview(session);
    assert.ok(result.ok && result.record);
    return result.record;
  };
  const open = (pending = true, parameter?: string) => {
    const result = reviews.prepare(ctx, parameter);
    assert.ok(result.ok);
    const prepared = result.value;
    const requestId = randomUUID();
    assert.deepEqual(prepared.registration.open(requestId), { ok: true });
    if (pending)
      assert.deepEqual(prepared.registration.attach(requestId, "review-id"), { ok: true });
    return prepared;
  };
  return {
    cwd,
    pi,
    ctx,
    reviews,
    branch,
    session,
    gating,
    invoke,
    command,
    draft,
    record,
    open,
    calls,
    notices,
    messages,
    get exits() {
      return exits;
    },
    set dropPointers(value: boolean) {
      dropPointers = value;
    },
    set dropLinkage(value: boolean) {
      dropLinkage = value;
    },
    set failSaveNotice(value: boolean) {
      failSaveNotice = value;
    },
    set backendWait(value: (() => Promise<void>) | undefined) {
      backendWait = value;
    },
    set editor(value: typeof editor) {
      editor = value;
    },
    set verdict(value: string) {
      verdict = value;
    },
    bytes: () => readFileSync(join(sessionDataDir(cwd, "RID"), sources[subject].name), "utf8"),
    dispose() {
      for (const handler of events.get("session_shutdown") ?? []) handler({}, ctx);
      rmSync(cwd, { recursive: true, force: true });
    },
  };
}

for (const subject of ["plan", "objective", "gist"] as const) {
  test(`${subject}: actual draft registration permits strict no-record and preserves identical pending bytes`, async () => {
    const f = fixture(subject);
    try {
      assert.equal((await f.draft()).details.ok, true);
      assert.deepEqual(readDraftReview(f.session), { ok: true, record: null });
      f.open();
      const before = f.record();
      assert.equal((await f.draft()).details.ok, true);
      assert.deepEqual(f.record(), before);
      assert.equal((await f.draft(true)).details.ok, true);
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "source-changed" });
    } finally {
      f.dispose();
    }
  });
  for (const pending of [false, true])
    test(`${subject}: ${pending ? "pending" : "opening"} invalidation failure blocks actual draft bytes and retains claim`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        f.open(pending);
        const before = f.bytes();
        f.dropPointers = true;
        const result = await f.draft(true);
        assert.equal(result.details.reason, "persistence-failed");
        assert.equal(f.bytes(), before, "no draft write after an unverified invalidation");
        assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
        const blocked = await f.invoke(`${subject}_save`, {
          ...sources[subject].params,
          title: "Title",
        });
        assert.equal(blocked.details.reason, "busy");
        assert.equal(f.calls.length, 0);
      } finally {
        f.dispose();
      }
    });
  for (const manual of ["tool", "command"] as const)
    test(`${subject}: actual ${manual} save invalidates pending before backend and owns linkage through await`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        f.open();
        const entered = deferred<void>();
        const finish = deferred<void>();
        f.backendWait = async () => {
          assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "manual-save" });
          entered.resolve();
          await finish.promise;
        };
        const save =
          manual === "tool"
            ? f.invoke(`${subject}_save`, { ...sources[subject].params, title: "Title" })
            : f.command(`${subject}-save`);
        await entered.promise;
        assert.equal((await f.draft(true)).details.reason, "busy");
        assert.equal(
          (await f.invoke("objective_node", { objective: "7", node: "1.1", status: "planning" }))
            .details.reason,
          "busy",
        );
        finish.resolve();
        await save;
        assert.equal(f.calls.length, 1);
        assert.ok(f.calls[0]?.includes("--run-id"));
        assert.equal(f.record().consumption.state, "invalidated");
        assert.equal((await f.draft(true)).details.ok, true, "claim released after bounded save");
      } finally {
        f.dispose();
      }
    });
}

const competingTools = [
  ["plan_draft", { plan: "New" }],
  ["objective_draft", { prose: "New" }],
  ["gist_draft", { prose: "New" }],
  ["plan_save", { plan: "New", title: "Title" }],
  ["objective_save", { prose: "New" }],
  ["gist_save", { prose: "New" }],
  ["objective_node", { objective: "7", node: "1.1", status: "planning" }],
  ["plan_review", { plan: "New" }],
] as const;
for (const identity of [null, "../unsafe"] as const)
  test(`every participating registration refuses ${identity === null ? "missing" : "unsafe"} identity`, async () => {
    const f = fixture("plan", identity);
    try {
      for (const [name, params] of competingTools) {
        const result = await f.invoke(name, params);
        assert.equal(result.details.status, "refused", name);
        assert.ok(["no-identity", "invalid-state"].includes(String(result.details.reason)), name);
      }
      for (const name of ["plan-save", "objective-save", "gist-save", "implement-here"])
        await f.command(name);
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      assert.equal(f.messages.length, 0);
      assert.equal(f.branch.length, 1);
    } finally {
      f.dispose();
    }
  });

for (const state of ["busy", "dispatch", "uncertain"] as const)
  test(`every competing registration blocks on ${state}`, async () => {
    const f = fixture();
    let release = () => {};
    try {
      await f.draft();
      const prepared = f.open();
      if (state === "busy") {
        const claim = acquireDraftReviewLock(f.cwd, {
          sessionId: "competitor",
          runId: "RID",
          requestId: randomUUID(),
        });
        assert.equal(claim.kind, "acquired");
        if (claim.kind !== "acquired") assert.fail("claim unavailable");
        release = () => {
          claim.claim.finish("release");
        };
      } else {
        await prepared.complete(
          { status: "completed", approved: false, feedback: "Feedback", reviewId: "review-id" },
          {
            effect: "revision",
            carrier: { kind: "tool", tool_call_id: "previous-tool" },
            async execute() {
              if (state === "uncertain") throw new Error("controlled effect failure");
              return { content: [{ type: "text", text: "Feedback" }], details: { ok: true } };
            },
          },
        );
        assert.equal(f.record().consumption.state, state);
      }
      const before = f.bytes();
      for (const [name, params] of competingTools)
        assert.equal(
          (await f.invoke(name, params)).details.reason,
          state === "busy" ? "busy" : "unresolved-dispatch",
          name,
        );
      for (const name of ["plan-save", "objective-save", "gist-save", "implement-here"])
        await f.command(name);
      assert.equal(f.bytes(), before);
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      assert.equal(f.messages.length, 0);
    } finally {
      release();
      f.dispose();
    }
  });

test("actual node transition owns exclusion until warm claim update; manual save cannot race backend await", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    const entered = deferred<void>();
    const finish = deferred<void>();
    f.backendWait = async () => {
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "target-changed" });
      entered.resolve();
      await finish.promise;
    };
    const transition = f.invoke("objective_node", {
      objective: "7",
      node: "1.1",
      status: "planning",
    });
    await entered.promise;
    assert.equal((await f.invoke("plan_save", { title: "Title" })).details.reason, "busy");
    assert.equal(f.session.nodeClaim(), null);
    finish.resolve();
    assert.equal((await transition).details.ok, true);
    assert.deepEqual(f.session.nodeClaim(), { objective: "7", node: "1.1" });
    const before = f.exits;
    await f.command("implement-here");
    assert.equal(f.exits, before);
    assert.equal(f.messages.length, 0);
    assert.ok(f.notices.some((text) => text.includes("objective-node planning session")));
  } finally {
    f.dispose();
  }
});

for (const subject of ["plan", "objective", "gist"] as const)
  test(`${subject}: first-party replacement invalidates and RELEASES before editor; new dispatch blocks late completion/writeback`, async () => {
    const f = fixture(subject);
    try {
      await f.draft();
      f.open();
      const entered = deferred<void>();
      const finish = deferred<string>();
      f.editor = async () => {
        assert.deepEqual(f.record().consumption, {
          state: "invalidated",
          reason: "first-party-review",
        });
        assert.ok(!existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
        entered.resolve();
        return finish.promise;
      };
      f.verdict = "Approve — auto-save to GitHub";
      const review = f.invoke("plan_review");
      await entered.promise;
      const successor = f.open();
      await successor.complete(
        { status: "completed", approved: false, reviewId: "review-id" },
        {
          effect: "revision",
          carrier: { kind: "tool", tool_call_id: "successor" },
          async execute() {
            return { content: [{ type: "text", text: "Feedback" }], details: { ok: true } };
          },
        },
      );
      const before = f.bytes();
      finish.resolve("# Human edits\n");
      assert.equal((await review).details.reason, "unresolved-dispatch");
      assert.equal(f.bytes(), before);
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
    } finally {
      f.dispose();
    }
  });

test("first-party plan edit writeback uses mutation seam and releases before verdict", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    f.editor = async () => "# Human edits\n";
    const review = await f.invoke("plan_review");
    assert.equal(review.details.status, "skipped");
    assert.equal(f.bytes(), "# Human edits\n");
    assert.deepEqual(f.record().consumption, {
      state: "invalidated",
      reason: "first-party-review",
    });
    assert.ok(!existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});

test("decode-first registration errors do not invalidate pending review", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    const before = f.record();
    for (const [name] of competingTools) {
      const result = await f.invoke(name, { plan: 2, prose: 2, objective: {}, node: false });
      assert.equal(result.details.ok, false, name);
      assert.deepEqual(f.record(), before);
    }
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});

for (const subject of ["plan", "objective", "gist"] as const) {
  test(`${subject}: valid no-record manual tool save keeps ordinary subject policy`, async () => {
    const f = fixture(subject);
    try {
      const result = await f.invoke(`${subject}_save`, {
        ...sources[subject].params,
        title: "Explicit title",
      });
      assert.equal(result.details.ok, true);
      assert.equal(f.calls.length, 1);
      assert.deepEqual(readDraftReview(f.session), { ok: true, record: null });
    } finally {
      f.dispose();
    }
  });
  test(`${subject}: opening invalidation succeeds before changed bytes and late attach cannot restore eligibility`, async () => {
    const f = fixture(subject);
    try {
      await f.draft();
      const prepared = f.open(false);
      const id = f.record().request_id;
      assert.equal((await f.draft(true)).details.ok, true);
      assert.deepEqual(f.record().consumption, { state: "invalidated", reason: "source-changed" });
      assert.equal(prepared.registration.attach(id, "late-id").ok, false);
      assert.equal(f.record().correlation.review_id, null);
    } finally {
      f.dispose();
    }
  });
}

test("first-party replacement invalidation failure prevents editor and any speculative repair", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    const before = f.bytes();
    f.dropPointers = true;
    f.editor = async () => assert.fail("editor must not open after failed replacement");
    const result = await f.invoke("plan_review");
    assert.equal(result.details.reason, "persistence-failed");
    assert.equal(f.bytes(), before);
    assert.equal(f.calls.length, 0);
    assert.equal((await f.invoke("plan_review")).details.reason, "busy");
  } finally {
    f.dispose();
  }
});

test("first-party writeback failure stops before verdict/save and retains residue", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    f.editor = async () => {
      f.dropPointers = true;
      return "# Edited\n";
    };
    f.verdict = "Approve — auto-save to GitHub";
    const result = await f.invoke("plan_review");
    assert.equal(result.details.reason, "persistence-failed");
    assert.equal(f.bytes(), "# Edited\n", "unverified bytes may exist but cannot authorize save");
    assert.equal(f.calls.length, 0);
    assert.equal(f.exits, 0);
    assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
  } finally {
    f.dispose();
  }
});

test("first-party plan saves human bytes with explicit mutation capability, never a competing save guard", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.open();
    f.editor = async () => "# Edited\n";
    f.verdict = "Approve — auto-save to GitHub";
    const result = await f.invoke("plan_review");
    assert.equal(result.details.saved, true);
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    const args = f.calls[0];
    assert.ok(args);
    const path = args[args.indexOf("--plan-file") + 1];
    assert.ok(path);
    assert.equal(
      readFileSync(path, "utf8"),
      "# Edited",
      "existing plan-save trimming is preserved",
    );
    assert.equal(f.session.nodeClaim(), null);
    assert.ok(!existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
  } finally {
    f.dispose();
  }
});

test("actual draft registration observes persisted revision before rewriting and preserves consumed record", async () => {
  const f = fixture();
  try {
    await f.draft();
    const prepared = f.open();
    const result = await prepared.complete(
      { status: "completed", approved: false, reviewId: "review-id" },
      {
        effect: "revision",
        carrier: { kind: "tool", tool_call_id: "persisted-call" },
        async execute() {
          return { content: [{ type: "text", text: "Revise" }], details: { ok: true } };
        },
      },
    );
    assert.ok(result.ok && "content" in result.value);
    const entry = {
      type: "message",
      id: "persisted-entry",
      message: {
        role: "toolResult",
        toolName: "plan_review",
        toolCallId: "persisted-call",
        ...result.value,
      },
    };
    f.branch.push(entry);
    assert.equal((await f.draft(true)).details.ok, true);
    assert.equal(f.record().consumption.state, "consumed");
    const before = f.record();
    assert.equal((await f.draft()).details.ok, true);
    assert.deepEqual(f.record(), before);
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});

for (const subject of ["plan", "objective"] as const) {
  for (const surface of ["tool", "command", "first-party"] as const)
    test(`${subject} ${surface}: failed linkage retains typed receipt, applicable gate facts, and exclusion`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        f.open();
        f.dropLinkage = true;
        f.verdict = "Approve — auto-save to GitHub";
        const result =
          surface === "command"
            ? await f.command(`${subject}-save`)
            : await f.invoke(
                surface === "tool" ? `${subject}_save` : "plan_review",
                surface === "tool" ? { ...sources[subject].params, title: "Explicit title" } : {},
              );
        const receipt =
          subject === "plan"
            ? { id: "42", url: "https://example.test/42" }
            : { id: "7", url: "https://example.test/7" };
        if (result !== undefined) {
          assert.equal(result.details.reason, "persistence-failed");
          assert.deepEqual(result.details.save_receipt, receipt);
          assert.equal(result.details.gate_exited === true, surface !== "tool");
          assert.match(result.content[0]?.text ?? "", /Confirmed save:.*Do not retry/s);
        } else {
          assert.ok(
            f.notices.some(
              (text) =>
                text.includes(`Confirmed save: ${receipt.id} (${receipt.url})`) &&
                text.includes("Do not retry"),
            ),
          );
        }
        assert.equal(
          f.exits,
          surface === "tool" ? 0 : 1,
          "no new manual-tool gate exit and no duplicate approval exit",
        );
        assert.equal(f.calls.length, 1);
        assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
        assert.equal((await f.draft(true)).details.reason, "busy");
        assert.equal(f.calls.length, 1, "retained failure cannot replay the save");
      } finally {
        f.dispose();
      }
    });
}

for (const subject of ["plan", "objective", "gist"] as const) {
  for (const surface of ["command", "first-party"] as const) {
    test(`${subject} ${surface}: throwing approval gate preserves the typed save receipt`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        f.open();
        f.verdict = "Approve — auto-save to GitHub";
        f.gating.exit = () => {
          throw new Error("controlled gate bookkeeping failure");
        };
        const result =
          surface === "command"
            ? await f.command(`${subject}-save`)
            : await f.invoke("plan_review");
        const savedId = subject === "plan" ? "42" : subject === "objective" ? "7" : "8";
        if (result !== undefined) {
          assert.equal(result.details.ok, false);
          assert.deepEqual(result.details.save_receipt, {
            id: savedId,
            url: `https://example.test/${savedId}`,
          });
          assert.notEqual(result.details.gate_exited, true);
          assert.match(result.content[0]?.text ?? "", /Confirmed save:.*Do not retry/s);
        } else {
          assert.ok(
            f.notices.some(
              (text) =>
                text.includes(`Confirmed save: ${savedId}`) &&
                text.includes("Do not retry") &&
                !text.includes("already exited"),
            ),
          );
        }
        assert.equal(f.calls.length, 1);
        assert.equal(f.exits, 0);
        assert.deepEqual(
          f.record().consumption,
          {
            state: "invalidated",
            reason: surface === "command" ? "manual-save" : "first-party-review",
          },
          "ordinary saves must not manufacture dispatch/consumption records",
        );
      } finally {
        f.dispose();
      }
    });
  }
}

test("gist slash-save: post-save notice failure preserves receipt and definitive gate outcome", async () => {
  const f = fixture("gist");
  try {
    await f.draft();
    f.open();
    f.failSaveNotice = true;
    await f.command("gist-save");
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    assert.ok(
      f.notices.some(
        (text) =>
          text.includes("Confirmed save: 8 (https://example.test/8)") &&
          text.includes("already exited") &&
          text.includes("Do not retry"),
      ),
    );
  } finally {
    f.dispose();
  }
});

test("owned manual save receipt survives replaced claim without any gate effect or deleting replacement", async () => {
  const f = fixture();
  let release = () => {};
  try {
    await f.draft();
    f.open();
    f.backendWait = async () => {
      rmSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock"));
      const replacement = acquireDraftReviewLock(f.cwd, {
        sessionId: "replacement",
        runId: "RID",
        requestId: randomUUID(),
      });
      assert.equal(replacement.kind, "acquired");
      if (replacement.kind !== "acquired") assert.fail("replacement unavailable");
      release = () => {
        replacement.claim.finish("release");
      };
    };
    await f.command("plan-save");
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 0);
    assert.ok(
      f.notices.some(
        (text) =>
          text.includes("ownership-lost") &&
          text.includes("Confirmed save: 42") &&
          !text.includes("already exited"),
      ),
    );
    assert.ok(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
  } finally {
    release();
    f.dispose();
  }
});
