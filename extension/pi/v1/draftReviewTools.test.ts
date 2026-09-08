import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fauxAssistantMessage, fauxToolCall } from "@earendil-works/pi-ai";
import {
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionAPI,
  type ExtensionContext,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { openBranchWorkflowSession } from "../../session/branchWorkflowSession.ts";
import { readDraftReview } from "../../session/draftReviewState.ts";
import { sessionDataDir } from "../../substrate/cache.ts";
import type { ToolGating } from "../../substrate/toolGating.ts";
import { WORKFLOW_STATE_TYPE } from "../../substrate/workflowState.ts";
import { report } from "../../surfaces/report.ts";
import { dreamReportInput, plantDreamFiles } from "../../testing/dreamFixtures.ts";
import {
  fakePerkRouter,
  fauxModelRuntime,
  gitInit,
  loadPerkSession,
  scaffoldRepo,
  spyInjections,
} from "../../testing/harness.ts";
import { createDraftReviewActivation } from "./draftReviewActivation.ts";
import { installGistBindings } from "./gist.ts";
import { installObjectiveAuthoringBindings } from "./objectiveAuthoring.ts";
import { installPlanBindings, planSaveDepsFor } from "./plan.ts";
import { runPlanReviewV1 } from "./planReview.ts";
import { createPlannotatorBridge } from "./providers/plannotator.ts";
import type { ToolResult } from "./review.ts";

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
    signal: AbortSignal | undefined,
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
  mkdirSync(join(cwd, ".perk"), { recursive: true });
  writeFileSync(join(cwd, ".perk", "config.toml"), '[providers]\nplan = "plannotator-plan"\n');
  const branch: unknown[] = [
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
  const requests: { action: string; requestId: string; respond(value: unknown): void }[] = [];
  const listeners = new Set<(value: unknown) => void>();
  const ready = deferred<void>();
  let failReviewState: string | undefined;
  let corruptPatch = false;
  let dropPointers = false;
  let dropLinkage = false;
  let failSaveNotice = false;
  let backendWait: (() => Promise<void>) | undefined;
  let backendResult: { code: number; stdout: string; stderr: string; killed: boolean } | undefined;
  let editor: (text: string) => Promise<string | undefined> = async (text) => text;
  let verdict = "Skip — decide later (manual /plan-save)";
  let exits = 0;
  const pi = {
    events: {
      emit(_name: string, request: (typeof requests)[number]) {
        requests.push(request);
        if (request.action === "plan-review")
          request.respond({
            status: "handled",
            result: { status: "pending", reviewId: "review-id" },
          });
        else ready.resolve();
      },
      on(_name: string, listener: (value: unknown) => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
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
      if (corruptPatch && data.session_artifacts !== undefined) {
        const path = join(sessionDataDir(cwd, "RID"), "plan-draft.md");
        if (existsSync(path) && readFileSync(path, "utf8") === "# Edited\n") {
          writeFileSync(path, "# Corrupted unverified patch\n");
          return;
        }
      }
      if (data.session_artifacts !== undefined && failReviewState !== undefined) {
        const path = join(sessionDataDir(cwd, "RID"), "draft-review.json");
        if (
          existsSync(path) &&
          (JSON.parse(readFileSync(path, "utf8")).consumption.state === failReviewState ||
            (failReviewState === "delivery" &&
              JSON.parse(readFileSync(path, "utf8")).consumption.attempt?.delivery != null))
        )
          return;
      }
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
      if (backendResult !== undefined) return backendResult;
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
                ...(args.includes("--node-id")
                  ? {
                      objective_node: {
                        linked: true,
                        node: args[args.indexOf("--node-id") + 1],
                        status: "in_progress",
                        error: null,
                      },
                    }
                  : {}),
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
  installPlanBindings(pi, gating, reviews);
  installObjectiveAuthoringBindings(pi, gating, reviews);
  installGistBindings(pi, gating, reviews);
  const session = openBranchWorkflowSession(pi, ctx);
  const invoke = async (name: string, params: unknown = {}, signal?: AbortSignal) => {
    const tool = tools.get(name);
    assert.ok(tool, `registered ${name}`);
    return tool.execute("actual-tool-id", params, signal, undefined, ctx);
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
  return {
    cwd,
    pi,
    ctx,
    gating,
    reviews,
    branch,
    session,
    invoke,
    command,
    draft,
    record,
    calls,
    ready: ready.promise,
    requests,
    listeners,
    event(approved: boolean, feedback?: string) {
      for (const listener of [...listeners])
        listener({ reviewId: "review-id", approved, feedback });
    },
    status(approved: boolean, feedback?: string) {
      const request = requests.find((r) => r.action === "review-status");
      assert.ok(request);
      request.respond({
        status: "handled",
        result: { status: "completed", reviewId: "review-id", approved, feedback },
      });
    },
    persist(result: ToolResult, id = "actual-tool-id") {
      branch.push({
        type: "message",
        id: "persisted-tool",
        message: {
          role: "toolResult",
          toolName: "plan_review",
          toolCallId: id,
          content: result.content,
          details: result.details,
        },
      });
    },
    turnEnd() {
      for (const handler of events.get("turn_end") ?? []) handler({}, ctx);
    },
    messageEnd() {
      for (const handler of events.get("message_end") ?? []) handler({}, ctx);
    },
    set failReviewState(value: string | undefined) {
      failReviewState = value;
    },
    notices,
    messages,
    get exits() {
      return exits;
    },
    set corruptPatch(value: boolean) {
      corruptPatch = value;
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
    set backendResult(value: typeof backendResult) {
      backendResult = value;
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
  for (const order of ["event", "status"] as const) {
    test(`${subject}: registered tool ${order}-first approval saves once; only exact persisted tool result acknowledges`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        const pending = f.invoke("plan_review");
        await f.ready;
        assert.equal(f.record().consumption.state, "pending");
        assert.equal(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")), false);
        if (order === "event") {
          f.event(true);
          f.status(false, "duplicate");
        } else {
          f.status(true);
          f.event(false, "duplicate");
        }
        const result = await pending;
        assert.equal(result.details.ok, true);
        assert.equal(result.terminate, true);
        assert.equal(f.calls.length, 1);
        assert.equal(f.exits, 1);
        const dispatched = f.record().consumption;
        assert.equal(dispatched.state, "dispatch");
        if (dispatched.state !== "dispatch") assert.fail();
        assert.deepEqual(dispatched.attempt.save, {
          state: "confirmed",
          id: subject === "plan" ? "42" : subject === "objective" ? "7" : "8",
          url: `https://example.test/${subject === "plan" ? "42" : subject === "objective" ? "7" : "8"}`,
        });
        assert.equal(result.details.draft_review_dispatch, dispatched.attempt.dispatch_id);
        assert.deepEqual(dispatched.attempt.delivery?.carrier, {
          kind: "tool",
          tool_call_id: "actual-tool-id",
        });
        f.messageEnd();
        f.turnEnd();
        assert.equal(
          f.record().consumption.state,
          "dispatch",
          "return/message_end is not evidence",
        );
        f.persist(result, "wrong-tool-id");
        f.turnEnd();
        assert.equal(f.record().consumption.state, "dispatch");
        f.persist(result);
        f.turnEnd();
        assert.equal(f.record().consumption.state, "consumed");
        assert.equal(f.calls.length, 1);
        assert.equal(f.listeners.size, 0);
      } finally {
        f.dispose();
      }
    });
  }
  for (const approved of [false, true]) {
    test(`${subject}: changed full source allows only stale DATA for ${approved ? "approval/structured edits" : "denial"}`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        const pending = f.invoke("plan_review");
        await f.ready;
        const digest = f.record().correlation.source_digest;
        assert.equal((await f.draft(true)).details.ok, true);
        const feedback =
          approved && subject !== "plan"
            ? "# Direct Edits\n\nverbatim <script>"
            : "verbatim <script>\napply this";
        f.event(approved, feedback);
        const result = await pending;
        assert.equal(result.details.status, "stale-reference");
        const text = result.content[0]?.text ?? "";
        assert.ok(text.includes(feedback));
        assert.ok(text.includes(digest));
        assert.match(text, /untrusted_reviewer_feedback/);
        assert.doesNotMatch(text, /Fold|call plan_review again|with (plan|objective|gist)_draft/);
        assert.equal(f.calls.length, 0);
        assert.equal(f.exits, 0);
        f.persist(result);
        assert.equal(
          (await f.draft()).details.ok,
          true,
          "next guarded mutation observes persisted DATA first",
        );
        assert.equal(f.record().consumption.state, "consumed");
      } finally {
        f.dispose();
      }
    });
  }
  test(`${subject}: rejected dispatch pointer poisons effects and retains claim without speculative uncertainty`, async () => {
    const f = fixture(subject);
    try {
      await f.draft();
      const pending = f.invoke("plan_review");
      await f.ready;
      f.failReviewState = "dispatch";
      f.event(true);
      const result = await pending;
      assert.equal(result.details.reason, "persistence-failed");
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      const raw = JSON.parse(
        readFileSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.json"), "utf8"),
      );
      assert.equal(raw.consumption.state, "dispatch", "no speculative repair write");
      assert.equal(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")), true);
    } finally {
      f.dispose();
    }
  });
}

for (const subject of ["objective", "gist"] as const) {
  test(`${subject}: approved Direct Edits is one persisted revision and never a structured save`, async () => {
    const f = fixture(subject);
    try {
      await f.draft();
      const pending = f.invoke("plan_review");
      await f.ready;
      f.status(true, "# Direct Edits\n\nraw edits");
      const result = await pending;
      assert.equal(result.details.status, "revise");
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      const state = f.record().consumption;
      assert.equal(state.state, "dispatch");
      if (state.state !== "dispatch") assert.fail();
      assert.equal(state.attempt.effect, "revision");
      assert.deepEqual(state.attempt.save, { state: "not-required" });
      f.persist(result);
      f.turnEnd();
      assert.equal(f.record().consumption.state, "consumed");
    } finally {
      f.dispose();
    }
  });
}

for (const appearing of [false, true]) {
  test(`parameter plan: ${appearing ? "new identical artifact permits only stale DATA" : "approval saves frozen parameter"}`, async () => {
    const f = fixture();
    try {
      const pending = f.invoke("plan_review", { plan: "# Original\n" });
      await f.ready;
      if (appearing) await f.draft();
      f.event(true);
      const result = await pending;
      assert.equal(result.details.status, appearing ? "stale-reference" : "completed");
      assert.equal(f.calls.length, appearing ? 0 : 1);
      if (!appearing) {
        const args = f.calls[0] ?? [];
        assert.equal(
          readFileSync(args[args.indexOf("--plan-file") + 1] ?? "", "utf8"),
          "# Original",
        );
      }
    } finally {
      f.dispose();
    }
  });
}

test("registered plan: saved receipt/gate survives failed linkage bookkeeping, never retries", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.dropLinkage = true;
    const pending = f.invoke("plan_review");
    await f.ready;
    f.event(true);
    const result = await pending;
    // Linkage failure happens after the typed backend receipt and definitive gate outcome.
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    assert.equal(result.details.status, "refused");
    assert.deepEqual(result.details.save_receipt, { id: "42", url: "https://example.test/42" });
    assert.equal(result.details.gate_exited, true);
    assert.match(result.content[0]?.text ?? "", /Confirmed save: 42/);
    assert.equal(
      (await f.invoke("plan_review")).details.reason,
      "busy",
      "failed bookkeeping retains claim",
    );
    assert.equal(f.calls.length, 1);
  } finally {
    f.dispose();
  }
});

for (const kind of ["source", "target"] as const) {
  test(`plan title await: ${kind} drift blocks the production cold door after verified intent`, async () => {
    const f = fixture();
    const title = deferred<string>();
    const entered = deferred<void>();
    try {
      await f.draft();
      const deps = planSaveDepsFor(f.pi, f.ctx, f.gating);
      const pending = runPlanReviewV1(
        f.ctx,
        { ...createPlannotatorBridge(f.pi.events), ...f.reviews },
        {
          ...deps,
          generateTitle: async () => {
            entered.resolve();
            return title.promise;
          },
        },
        undefined,
        undefined,
        undefined,
        "title-tool-id",
      );
      await f.ready;
      f.event(true);
      await entered.promise;
      assert.equal(f.record().consumption.state, "dispatch");
      assert.equal((await f.draft(true)).details.reason, "busy", "participating writer excluded");
      if (kind === "source") f.session.writeArtifact("plan-draft.md", "# External change\n");
      else
        writeFileSync(
          join(f.cwd, ".perk", "config.toml"),
          '[providers]\nplan = "plannotator-plan"\n[issues]\nbackend = "linear"\n',
        );
      title.resolve("Title");
      const result = await pending;
      assert.equal(result.details.status, "refused");
      assert.equal(result.details.reason, kind === "source" ? "source-changed" : "target-changed");
      if (kind === "target")
        assert.match(
          String(result.content[0]?.text),
          /checkpoint: save;.*changed components: main_config\.issues\.backend/,
        );
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      assert.equal(f.record().consumption.state, "uncertain");
    } finally {
      title.resolve("Title");
      f.dispose();
    }
  });
  test(`registered plan backend await: later ${kind} change cannot replay or erase the typed save`, async () => {
    const f = fixture();
    const started = deferred<void>();
    const release = deferred<void>();
    try {
      await f.draft();
      f.backendWait = async () => {
        started.resolve();
        await release.promise;
      };
      const pending = f.invoke("plan_review");
      await f.ready;
      f.event(true);
      await started.promise;
      const state = f.record().consumption;
      assert.equal(state.state, "dispatch");
      if (state.state !== "dispatch") assert.fail();
      assert.deepEqual(state.attempt.save, { state: "started" });
      assert.equal((await f.draft(true)).details.reason, "busy");
      if (kind === "source") f.session.writeArtifact("plan-draft.md", "# External change\n");
      else
        writeFileSync(
          join(f.cwd, ".perk", "config.toml"),
          '[providers]\nplan = "plannotator-plan"\n[issues]\nbackend = "linear"\n',
        );
      release.resolve();
      const result = await pending;
      assert.equal(result.details.ok, true);
      assert.equal(f.calls.length, 1);
      assert.equal(f.exits, 1);
      f.persist(result);
      f.turnEnd();
      assert.equal(
        f.record().consumption.state,
        "consumed",
        "completion checks evidence, not old source/target",
      );
    } finally {
      release.resolve();
      f.dispose();
    }
  });
}

test("registered plan approval passes captured warm node argv and clears only its saved claim", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.branch.push({
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { objective_node_claim: { objective: " OBJ-7 ", node: " 1.1 " } },
    });
    const pending = f.invoke("plan_review");
    await f.ready;
    f.event(true);
    const result = await pending;
    assert.equal(result.details.ok, true);
    const args = f.calls[0] ?? [];
    assert.equal(args[args.indexOf("--objective-id") + 1], " OBJ-7 ");
    assert.equal(args[args.indexOf("--node-id") + 1], " 1.1 ");
    assert.equal(f.calls.length, 1);
    assert.equal(f.session.nodeClaim(), null, "successful node-linked save clears warm claim");
    f.persist(result);
    f.turnEnd();
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

test("registered objective approval retains dream-report canonical parts and structured argv", async () => {
  const f = fixture("objective");
  try {
    const digest = plantDreamFiles(f.cwd, "RID");
    f.branch.push({
      type: "custom",
      customType: WORKFLOW_STATE_TYPE,
      data: { dream_bundle_digest: digest },
    });
    const drafted = await f.invoke("objective_draft", {
      ...sources.objective.params,
      base: "release",
      dream_report: dreamReportInput(),
    });
    assert.equal(drafted.details.ok, true, drafted.content[0]?.text);
    const original = JSON.parse(f.bytes());
    const pending = f.invoke("plan_review");
    await f.ready;
    f.status(true);
    const result = await pending;
    assert.equal(result.details.ok, true, result.content[0]?.text);
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    const args = f.calls[0] ?? [];
    assert.equal(args[args.indexOf("--base") + 1], "release");
    assert.equal(args[args.indexOf("--delivery") + 1], "incremental");
    assert.deepEqual(JSON.parse(args[args.indexOf("--roadmap") + 1] ?? ""), original.roadmap);
    const transfer = JSON.parse(
      readFileSync(
        join(f.cwd, ".perk", "workflow", "scratch", "runs", "RID", "dream-report-transfer.json"),
        "utf8",
      ),
    );
    assert.deepEqual(transfer, {
      schema_version: "1",
      run_id: "RID",
      parts: original.dream_report.parts,
    });
    f.persist(result);
    f.turnEnd();
    assert.equal(f.record().consumption.state, "consumed");
  } finally {
    f.dispose();
  }
});

test("Pi SDK: real registered plan_review result is absent at message_end and persisted/consumed at turn_end", async () => {
  const f = fixture();
  const runtime = await fauxModelRuntime();
  // The helper's model object is the provider's canonical model, not a lookalike registration.
  const selected = runtime.getModel() as NonNullable<
    Parameters<typeof createAgentSession>[0]
  >["model"];
  assert.ok(selected);
  runtime.setResponses([
    fauxAssistantMessage(fauxToolCall("plan_review", {}, { id: "sdk-actual-id" }), {
      stopReason: "toolUse",
    }),
  ]);
  const agentDir = join(f.cwd, "sdk-agent");
  const manager = SessionManager.create(f.cwd, join(agentDir, "sessions"));
  const evidence: { phase: string; present: boolean; consumption: string }[] = [];
  const errors: string[] = [];
  const loader = new DefaultResourceLoader({
    cwd: f.cwd,
    agentDir,
    extensionFactories: [
      (pi) => {
        const reviews = createDraftReviewActivation(pi);
        installPlanBindings({ ...pi, exec: f.pi.exec }, f.gating, reviews);
        pi.on("session_start", (_event, ctx) => {
          pi.appendEntry(WORKFLOW_STATE_TYPE, { run_id: "RID", stage: "plan", mode: "read-only" });
          assert.equal(
            openBranchWorkflowSession(pi, ctx).writeArtifact("plan-draft.md", "# Original\n")
              .status,
            "applied",
          );
        });
        pi.events.on("plannotator:request", (raw) => {
          const request = raw as { action: string; respond(value: unknown): void };
          request.respond({
            status: "handled",
            result:
              request.action === "plan-review"
                ? { status: "pending", reviewId: "sdk-review" }
                : { status: "completed", reviewId: "sdk-review", approved: true },
          });
        });
        const observe = (phase: string, ctx: ExtensionContext) => {
          const current = readDraftReview(openBranchWorkflowSession(pi, ctx));
          assert.ok(current.ok && current.record);
          evidence.push({
            phase,
            present: ctx.sessionManager
              .getBranch()
              .some(
                (e) =>
                  e.type === "message" &&
                  e.message.role === "toolResult" &&
                  e.message.toolCallId === "sdk-actual-id",
              ),
            consumption: current.record.consumption.state,
          });
        };
        pi.on("message_end", (event, ctx) => {
          if (event.message.role === "toolResult") observe("message_end", ctx);
        });
        pi.on("turn_end", (_event, ctx) => observe("turn_end", ctx));
      },
    ],
  });
  let session: Awaited<ReturnType<typeof createAgentSession>>["session"] | undefined;
  const previousNoLlm = process.env.PERK_NO_LLM;
  try {
    process.env.PERK_NO_LLM = "1";
    await loader.reload();
    ({ session } = await createAgentSession({
      cwd: f.cwd,
      agentDir,
      resourceLoader: loader,
      sessionManager: manager,
      model: selected,
      modelRuntime: runtime.modelRuntime,
      tools: ["plan_review"],
      settingsManager: SettingsManager.inMemory({
        compaction: { enabled: false },
        retry: { enabled: false },
      }),
    }));
    await session.bindExtensions({
      uiContext: f.ctx.ui,
      onError: (error) => {
        errors.push(error.error);
      },
    });
    await session.prompt("Review the draft.");
    assert.deepEqual(errors, []);
    assert.deepEqual(evidence, [
      { phase: "message_end", present: false, consumption: "dispatch" },
      { phase: "turn_end", present: true, consumption: "consumed" },
    ]);
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    const path = manager.getSessionFile();
    assert.ok(path);
    const reopened = SessionManager.open(path);
    assert.ok(
      reopened
        .getBranch()
        .some(
          (e) =>
            e.type === "message" &&
            e.message.role === "toolResult" &&
            e.message.toolCallId === "sdk-actual-id" &&
            typeof e.message.details === "object" &&
            e.message.details !== null &&
            "draft_review_dispatch" in e.message.details,
        ),
    );
  } finally {
    session?.dispose();
    if (previousNoLlm === undefined) delete process.env.PERK_NO_LLM;
    else process.env.PERK_NO_LLM = previousNoLlm;
    f.dispose();
  }
});

for (const corrupt of [false, true]) {
  test(`registered plan Direct Edits: ${corrupt ? "unverified patch saves frozen original only" : "verified patch saves edited bytes"}`, async () => {
    const f = fixture();
    try {
      await f.draft();
      f.corruptPatch = corrupt;
      const pending = f.invoke("plan_review");
      await f.ready;
      f.event(
        true,
        "# Direct Edits\n\n```diff\n--- a/plan.md\n+++ b/plan.md\n@@ -1 +1 @@\n-# Original\n+# Edited\n```\n\n---\n\nRemaining feedback",
      );
      const result = await pending;
      assert.equal(result.details.ok, true, result.content[0]?.text);
      assert.equal(f.calls.length, 1);
      assert.equal(f.exits, 1);
      const args = f.calls[0] ?? [];
      assert.equal(
        readFileSync(args[args.indexOf("--plan-file") + 1] ?? "", "utf8"),
        corrupt ? "# Original" : "# Edited",
      );
      assert.equal(f.bytes(), corrupt ? "# Corrupted unverified patch\n" : "# Edited\n");
      if (corrupt) assert.equal(result.details.direct_edits_applied, false);
      else assert.equal(result.details.edited, true);
      f.persist(result);
      f.turnEnd();
      assert.equal(f.record().consumption.state, "consumed");
    } finally {
      f.dispose();
    }
  });
}

for (const approved of [false, true]) {
  test(`registered gist: abort immediately after ${approved ? "approval/Direct Edits" : "denial"} candidate leaves pending and emits no actionable result`, async () => {
    const f = fixture("gist");
    const controller = new AbortController();
    try {
      await f.draft();
      const pending = f.invoke("plan_review", {}, controller.signal);
      await f.ready;
      f.event(approved, "# Direct Edits\n\nraw feedback");
      controller.abort();
      const result = await pending;
      assert.equal(result.details.status, "aborted");
      assert.equal(f.calls.length, 0);
      assert.equal(f.exits, 0);
      assert.equal(result.details.draft_review_dispatch, undefined);
      assert.equal(f.record().consumption.state, "pending");
    } finally {
      f.dispose();
    }
  });
}

test("plan completion: throwing real notification after saved rendering retains receipt and gate without replay", async () => {
  const f = fixture();
  try {
    await f.draft();
    f.failSaveNotice = true;
    const deps = planSaveDepsFor(f.pi, f.ctx, f.gating);
    const pending = runPlanReviewV1(
      f.ctx,
      { ...createPlannotatorBridge(f.pi.events), ...f.reviews },
      {
        ...deps,
        renderSave(save) {
          const result = deps.renderSave(save);
          report(f.ctx, "plan-save", "info", "Saved plan 42");
          return result;
        },
      },
      undefined,
      undefined,
      undefined,
      "notification-tool-id",
    );
    await f.ready;
    f.event(true);
    const result = await pending;
    assert.equal(result.details.status, "refused");
    assert.deepEqual(result.details.save_receipt, { id: "42", url: "https://example.test/42" });
    assert.equal(result.details.gate_exited, true);
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    assert.equal(f.record().consumption.state, "uncertain");
    const stopped = await f.invoke("plan_review");
    assert.equal(stopped.details.reason, "unresolved-dispatch");
    const diagnostic = stopped.content[0]?.text ?? "";
    assert.ok(diagnostic.includes(f.record().request_id));
    assert.ok(diagnostic.includes("review-id"));
    assert.match(diagnostic, /known save receipt: "42"/);
    assert.match(diagnostic, /https:\/\/example\.test\/42/);
    assert.match(diagnostic, /uncertain\/effect-failed/);
    assert.match(diagnostic, /reconcile-a-draft-review-stop\.md/);
    assert.equal(f.calls.length, 1);
  } finally {
    f.dispose();
  }
});

test("registered tool: failed delivery expectation retains confirmed receipt/gate and poisons further effects", async () => {
  const f = fixture();
  try {
    await f.draft();
    const pending = f.invoke("plan_review");
    await f.ready;
    f.failReviewState = "delivery";
    f.event(true);
    const result = await pending;
    assert.equal(result.details.reason, "persistence-failed");
    assert.deepEqual(result.details.save_receipt, { id: "42", url: "https://example.test/42" });
    assert.equal(result.details.gate_exited, true);
    assert.equal(f.calls.length, 1);
    assert.equal(f.exits, 1);
    assert.equal((await f.invoke("plan_review")).details.reason, "busy");
    const raw = JSON.parse(
      readFileSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.json"), "utf8"),
    );
    assert.equal(
      raw.consumption.state,
      "dispatch",
      "failed expectation gets no speculative repair",
    );
  } finally {
    f.dispose();
  }
});

test("registered parameter review: broken artifact provenance never falls back to parameter", async () => {
  const f = fixture();
  try {
    await f.draft();
    writeFileSync(join(sessionDataDir(f.cwd, "RID"), "plan-draft.md"), "# External corruption\n");
    const result = await f.invoke("plan_review", { plan: "# Fallback" });
    assert.equal(result.details.reason, "invalid-state");
    assert.equal(f.requests.length, 0);
    assert.equal(f.calls.length, 0);
    assert.equal(f.exits, 0);
  } finally {
    f.dispose();
  }
});

for (const subject of ["plan", "objective", "gist"] as const) {
  const key = subject === "plan" ? "plan_ref" : subject;
  for (const [name, response] of [
    ["nonzero exit", { code: 1, stdout: "", stderr: "backend failed", killed: false }],
    ["killed", { code: 0, stdout: "{}", stderr: "", killed: true }],
    ["malformed JSON", { code: 0, stdout: "{", stderr: "", killed: false }],
    ["missing payload", { code: 0, stdout: '{"success":true}', stderr: "", killed: false }],
    ...(
      [
        ["null", null],
        ["missing ID", { url: "https://example.test/42", existed: false }],
        ["blank ID", { id: " ", url: "https://example.test/42", existed: false }],
        ["mistyped ID", { id: 42, url: "https://example.test/42", existed: false }],
        ["missing URL", { id: "42", existed: false }],
        ["blank URL", { id: "42", url: " ", existed: false }],
        ["mistyped URL", { id: "42", url: false, existed: false }],
      ] as const
    ).map(
      ([name, receipt]) =>
        [
          name,
          {
            code: 0,
            stdout: JSON.stringify({
              success: true,
              issue: { id: "42", url: "https://example.test/42", existed: false },
              scope: "plan",
              [key]:
                subject !== "plan" || receipt === null
                  ? receipt
                  : {
                      provider: "github",
                      labels: ["perk:plan"],
                      objective_id: null,
                      ...("id" in receipt ? { pr_id: receipt.id } : {}),
                      ...("url" in receipt ? { url: receipt.url } : {}),
                    },
            }),
            stderr: "",
            killed: false,
          },
        ] as const,
    ),
  ] as const) {
    test(`registered ${subject}: post-backend ${name} is unconfirmed, never retryable`, async () => {
      const f = fixture(subject);
      try {
        await f.draft();
        f.backendResult = response;
        const pending = f.invoke("plan_review");
        await f.ready;
        f.event(true);
        const result = await pending;
        assert.equal(result.details.reason, "unresolved-dispatch", result.content[0]?.text);
        assert.equal(result.details.save_receipt, undefined);
        assert.equal(f.calls.length, 1);
        assert.equal(f.exits, 0);
        const state = f.record().consumption;
        assert.equal(state.state, "uncertain");
        if (state.state !== "uncertain") assert.fail();
        assert.equal(state.reason, "backend-unconfirmed");
        assert.deepEqual(state.attempt.save, { state: "started" });
        assert.equal(state.attempt.delivery, null);
        assert.match(result.content[0]?.text ?? "", /reconcile-a-draft-review-stop\.md/);
        assert.equal((await f.invoke("plan_review")).details.reason, "unresolved-dispatch");
        assert.equal((await f.draft(true)).details.reason, "unresolved-dispatch");
        assert.equal(f.calls.length, 1);
        assert.equal(f.messages.length, 0);
      } finally {
        f.dispose();
      }
    });
  }
}

for (const residue of ["retained opening lock", "opening orphan"] as const) {
  test(`operator fixture: ${residue} leaves old run refused; fresh run inherits no authority`, async () => {
    const f = fixture();
    try {
      await f.draft();
      const prepared = f.reviews.prepare(f.ctx);
      assert.ok(prepared.ok);
      if (!prepared.ok) assert.fail();
      const request = "11111111-1111-4111-8111-111111111111";
      if (residue === "retained opening lock") {
        f.failReviewState = "opening";
        const failed = prepared.value.registration.open(request);
        assert.ok(!failed.ok && failed.reason === "persistence-failed");
        assert.match(failed.detail, /checkpoint: open/);
        assert.ok(failed.detail.includes(request));
      } else {
        const snapshot = prepared.value.snapshot;
        writeFileSync(
          join(sessionDataDir(f.cwd, "RID"), "draft-review.json"),
          JSON.stringify({
            schema_version: 1,
            request_id: request,
            correlation: {
              review_id: null,
              subject: "plan",
              source: snapshot.source,
              source_digest: snapshot.sourceDigest,
              target: { operation: "plan-save", digest: snapshot.binding.digest },
            },
            consumption: { state: "opening" },
          }),
        );
      }
      const original = readFileSync(
        join(sessionDataDir(f.cwd, "RID"), "draft-review.json"),
        "utf8",
      );
      const stopped = await f.invoke("plan_review");
      assert.equal(
        stopped.details.reason,
        residue === "retained opening lock" ? "busy" : "invalid-state",
      );
      const text = stopped.content[0]?.text ?? "";
      assert.ok(text.includes(join(sessionDataDir(f.cwd, "RID"), "draft-review.json")));
      assert.ok(text.includes(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")));
      assert.match(text, /Run: "RID"/);
      assert.match(text, /owner metadata is not proof of effects/);
      assert.match(text, /reconcile-a-draft-review-stop\.md/);
      assert.doesNotMatch(text, /# Original|plannotator-plan/);
      assert.equal(f.requests.length, 0);
      assert.equal(f.calls.length, 0);
      f.failReviewState = undefined;
      f.branch.push({
        type: "custom",
        customType: WORKFLOW_STATE_TYPE,
        data: { run_id: "FRESH", session_artifacts: {} },
      });
      const fresh = createDraftReviewActivation(f.pi);
      installPlanBindings(f.pi, f.gating, fresh);
      assert.equal((await f.draft()).details.ok, true);
      const freshRecord = readDraftReview(f.session);
      assert.deepEqual(freshRecord, { ok: true, record: null });
      const abandoned = f.reviews.mutate(f.ctx, "manual-save", () =>
        assert.fail("old activation cannot act in fresh run"),
      );
      assert.ok(!abandoned.ok);
      if (abandoned.ok) assert.fail();
      assert.ok(
        abandoned.detail.includes(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")),
        "diagnostics locate retained old namespace, never replacement run",
      );
      assert.equal(f.requests.length, 0, "fresh content does not copy approval or dispatch");
      assert.equal(f.calls.length, 0);
      assert.equal(
        readFileSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.json"), "utf8"),
        original,
      );
      assert.equal(existsSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.lock")), true);
      prepared.value.dispose();
    } finally {
      f.dispose();
    }
  });
}

for (const retained of [
  "opening",
  "pending",
  "invalidated",
  "dispatch",
  "uncertain",
  "consumed",
] as const) {
  test(`full extension startup/reload: ${retained} never queries, saves, injects prior feedback or consumes old delivery`, async () => {
    const f = fixture();
    const previousCwd = process.cwd();
    try {
      await f.draft();
      const pending = f.invoke("plan_review");
      await f.ready;
      f.event(false, "PRIOR_FEEDBACK_MUST_NOT_REPLAY");
      const result = await pending;
      f.persist(result);
      const record = f.record();
      assert.equal(record.consumption.state, "dispatch");
      if (record.consumption.state !== "dispatch") assert.fail();
      const attempt = record.consumption.attempt;
      if (retained === "opening") {
        record.correlation.review_id = null;
        record.consumption = { state: "opening" };
      } else if (retained === "pending") record.consumption = { state: "pending" };
      else if (retained === "invalidated")
        record.consumption = { state: "invalidated", reason: "degraded" };
      else if (retained === "uncertain")
        record.consumption = { state: "uncertain", reason: "delivery-unconfirmed", attempt };
      else if (retained === "consumed")
        record.consumption = { state: "consumed", attempt, delivery_entry_id: "prior-entry" };
      f.session.writeArtifact("draft-review.json", JSON.stringify(record));
      assert.equal(f.record().consumption.state, retained);
      const before = readFileSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.json"), "utf8");
      const manager = SessionManager.inMemory(f.cwd);
      for (const entry of f.branch) {
        assert.ok(typeof entry === "object" && entry !== null && "type" in entry);
        if (entry.type === "custom") {
          assert.ok(
            "customType" in entry && typeof entry.customType === "string" && "data" in entry,
          );
          manager.appendCustomEntry(entry.customType, entry.data);
        }
      }
      manager.appendMessage({
        role: "toolResult",
        toolCallId: "actual-tool-id",
        toolName: "plan_review",
        content: result.content,
        details: result.details,
        isError: false,
        timestamp: 1,
      });
      const requests: unknown[] = [];
      process.chdir(f.cwd);
      const argvFile = join(f.cwd, "cold-door-calls");
      const bin = fakePerkRouter(f.cwd, {}, { argvFile });
      const h = await loadPerkSession({
        cwd: f.cwd,
        headful: false,
        sessionManager: manager,
        env: { PERK_BIN: bin },
        extraExtensions: [
          (pi) => {
            pi.events.on("plannotator:request", (value) => {
              requests.push(value);
            });
          },
        ],
      });
      try {
        const injections = spyInjections(h);
        for (const name of ["plan_review", "plan_draft", "objective_draft", "gist_draft"])
          assert.ok(h.registeredTool(name), `production root registers ${name}`);
        assert.ok(h.registeredCommands().includes("plan-review-browser"));
        assert.ok(h.registeredCommands().includes("objective-review-browser"));
        for (const name of h.registeredCommands())
          assert.doesNotMatch(name, /draft.*resume|resume.*review/);
        await h.emitSessionStart();
        await h.reload();
        await h.session.extensionRunner?.emit({
          type: "turn_end",
          turnIndex: 0,
          message: fauxAssistantMessage("No recovery"),
          toolResults: [],
        });
        assert.deepEqual(requests, []);
        const coldCalls = existsSync(argvFile) ? readFileSync(argvFile, "utf8") : "";
        assert.doesNotMatch(coldCalls, /plan save|objective create|gist create/);
        const context = await h.emitBeforeAgentStart("No recovery requested");
        assert.ok(
          [...injections, ...context].every(
            (entry) => !JSON.stringify(entry).includes("PRIOR_FEEDBACK_MUST_NOT_REPLAY"),
          ),
        );
        assert.equal(
          manager
            .getBranch()
            .filter((entry) => entry.type === "message" && entry.message.role === "user").length,
          0,
        );
        for (const tool of h.session.getActiveToolNames())
          assert.doesNotMatch(tool, /draft.*resume|resume.*review/);
        assert.equal(
          readFileSync(join(sessionDataDir(f.cwd, "RID"), "draft-review.json"), "utf8"),
          before,
        );
      } finally {
        h.dispose();
      }
    } finally {
      process.chdir(previousCwd);
      f.dispose();
    }
  });
}

test("plan completion without actual caller identity refuses rather than minting a replacement", async () => {
  const f = fixture();
  try {
    await f.draft();
    const result = await runPlanReviewV1(
      f.ctx,
      { ...createPlannotatorBridge(f.pi.events), ...f.reviews },
      planSaveDepsFor(f.pi, f.ctx, f.gating),
      undefined,
    );
    assert.equal(result.details.reason, "invalid-state");
    assert.equal(f.requests.length, 0);
    assert.equal(f.calls.length, 0);
  } finally {
    f.dispose();
  }
});
