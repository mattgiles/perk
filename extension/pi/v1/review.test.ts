// The shared review-surface machinery (review.ts): the `runFirstPartyReview` pure-core matrix
// (edit write-back-or-abort, viewOnly, blank-edit, the abort re-check points, the verdict arms),
// the `chooseReviewLaunch` unit matrix (Esc arms, trim, every abort re-check), and the subject
// mapper cores (`subjectReviewOutcomeResult` / `approvedSubjectSaveResult` — driven with the
// plan descriptor so every rendered text is pinned byte-stable, including the defensive
// no-source / implement-here shapes). Fully offline: scripted ui fakes drive the dialogs.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Result } from "../../substrate/result.ts";
import {
  approvedSubjectSaveResult,
  chooseReviewLaunch,
  PLAN_SUBJECT,
  type PlanReviewUI,
  type ReviewLaunchUI,
  type ReviewOutcome,
  runFirstPartyReview,
  SKIP_TEXT,
  type SubjectSaveOutcome,
  skipResult,
  subjectReviewOutcomeResult,
  VERDICT_IMPLEMENT_HERE,
  verdictsFor,
  waveLaunchedResult,
} from "./review.ts";

/** A recording first-party UI: scripted editor/select/input answers, captured prompts + opts. */
function fakeUI(script: {
  editor?: (string | undefined)[];
  select?: (string | undefined)[];
  input?: (string | undefined)[];
}): PlanReviewUI &
  ReviewLaunchUI & {
    editors: { title: string; prefill: string | undefined }[];
    selects: { title: string; options: string[]; opts?: { signal?: AbortSignal } }[];
    inputs: { title: string; opts?: { signal?: AbortSignal } }[];
  } {
  const editorAnswers = [...(script.editor ?? [])];
  const selectAnswers = [...(script.select ?? [])];
  const inputAnswers = [...(script.input ?? [])];
  const ui = {
    editors: [] as { title: string; prefill: string | undefined }[],
    selects: [] as { title: string; options: string[]; opts?: { signal?: AbortSignal } }[],
    inputs: [] as { title: string; opts?: { signal?: AbortSignal } }[],
    async editor(title: string, prefill?: string) {
      ui.editors.push({ title, prefill });
      return editorAnswers.shift();
    },
    async select(title: string, options: string[], opts?: { signal?: AbortSignal }) {
      ui.selects.push({ title, options, opts });
      return selectAnswers.shift();
    },
    async input(title: string, _placeholder?: string, opts?: { signal?: AbortSignal }) {
      ui.inputs.push({ title, opts });
      return inputAnswers.shift();
    },
  };
  return ui;
}

const APPROVE = "Approve — auto-save to GitHub";
const DENY_OPT = "Deny — send feedback for revision";
const SKIP_OPT = "Skip — decide later (manual /plan-save)";

const noopWrite = (_plan: string): boolean => true;

// --------------------------------------------------- runFirstPartyReview (the pure core arms)

test("runFirstPartyReview: approve without edits (default plan titles + 3-option select)", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: [APPROVE] });
  const r = await runFirstPartyReview({ ui, plan: "# Plan", writeDraft: noopWrite });
  assert.equal(r.outcome.status, "completed");
  assert.equal((r.outcome as { approved: boolean }).approved, true);
  assert.ok((r.outcome as { reviewId: string }).reviewId, "a reviewId was minted");
  assert.equal(r.plan, "# Plan");
  assert.equal(r.edited, false);
  assert.equal(
    ui.editors[0]?.title,
    "Plan review — Enter: continue to verdict · Esc: skip · Ctrl+G: $EDITOR",
  );
  assert.equal(ui.selects[0]?.title, "Plan review verdict");
  assert.deepEqual(ui.selects[0]?.options, [APPROVE, DENY_OPT, SKIP_OPT]);
});

test("runFirstPartyReview: a blank edit result is treated as no-edit", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["   \n"], select: [APPROVE] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
  });
  assert.equal(writes.length, 0, "no write-back for a blank edit");
  assert.equal(r.plan, "# Plan", "the original bytes stay the reviewed plan");
  assert.equal(r.edited, false);
});

test("runFirstPartyReview: an edit writes back before the verdict; the edited plan is returned", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["# Plan v2"], select: [APPROVE] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
  });
  assert.deepEqual(writes, ["# Plan v2"]);
  assert.equal(r.plan, "# Plan v2");
  assert.equal(r.edited, true);
  assert.equal(r.outcome.status, "completed");
});

test("runFirstPartyReview: write-back failure -> unavailable, no verdict prompt", async () => {
  const ui = fakeUI({ editor: ["# Plan v2"], select: [APPROVE] });
  const r = await runFirstPartyReview({ ui, plan: "# Plan", writeDraft: () => false });
  assert.equal(r.outcome.status, "unavailable");
  assert.match(
    (r.outcome as { warning: string }).warning,
    /could not write the edited draft back .* nothing saved/,
  );
  assert.equal(ui.selects.length, 0, "the verdict prompt never opened");
  assert.equal(r.edited, false);
});

test("runFirstPartyReview: deny -> the feedback editor; blank/dismissed feedback is omitted", async () => {
  const withFeedback = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", "too vague"], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal(withFeedback.outcome.status, "completed");
  assert.equal((withFeedback.outcome as { approved: boolean }).approved, false);
  assert.equal((withFeedback.outcome as { feedback?: string }).feedback, "too vague");

  const blank = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", "  "], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal((blank.outcome as { feedback?: string }).feedback, undefined);

  const dismissed = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan", undefined], select: [DENY_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.equal(dismissed.outcome.status, "completed", "a dismissed feedback editor still denies");
  assert.equal((dismissed.outcome as { feedback?: string }).feedback, undefined);
});

test("runFirstPartyReview: the deny-feedback editor title carries the key hint", async () => {
  const ui = fakeUI({ editor: ["# Plan", "fb"], select: [DENY_OPT] });
  await runFirstPartyReview({ ui, plan: "# Plan", writeDraft: noopWrite });
  assert.equal(ui.editors[1]?.title, "Deny feedback (optional) — Enter to send");
});

test("runFirstPartyReview: viewOnly skips the write-back; custom title/verdicts rendered", async () => {
  const writes: string[] = [];
  const ui = fakeUI({ editor: ["# Plan v2 (edited)"], select: ["Custom approve"] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: (p) => {
      writes.push(p);
      return true;
    },
    viewOnly: true,
    editorTitle: "Custom title",
    verdicts: { approve: "Custom approve", deny: "Custom deny", skip: "Custom skip" },
  });
  assert.equal(writes.length, 0, "viewOnly never writes back");
  assert.equal(r.plan, "# Plan", "the original bytes are returned unchanged");
  assert.equal(r.edited, false);
  assert.equal(r.outcome.status, "completed");
  assert.equal((r.outcome as { approved: boolean }).approved, true);
  assert.equal(ui.editors[0]?.title, "Custom title");
  assert.deepEqual(ui.selects[0]?.options, ["Custom approve", "Custom deny", "Custom skip"]);
});

test("runFirstPartyReview: the implementHere verdict returns the implement-here outcome", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: ["Impl here"] });
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    verdicts: { approve: "A", deny: "D", skip: "S", implementHere: "Impl here" },
  });
  assert.equal(r.outcome.status, "implement-here");
  assert.ok((r.outcome as { reviewId: string }).reviewId, "a reviewId was minted");
  assert.deepEqual(
    ui.selects[0]?.options,
    ["A", "Impl here", "D", "S"],
    "implement-here sits between approve and deny",
  );

  // A dismissed select (undefined) with implement-here offered is still dismissed — the
  // undefined-verdict comparison never matches the optional option.
  const esc = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [undefined] }),
    plan: "# Plan",
    writeDraft: noopWrite,
    verdicts: { approve: "A", deny: "D", skip: "S", implementHere: "Impl here" },
  });
  assert.deepEqual(esc.outcome, { status: "dismissed" });
});

test("runFirstPartyReview: verdict dismissed or Skip -> dismissed", async () => {
  const esc = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [undefined] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.deepEqual(esc.outcome, { status: "dismissed" });

  const skip = await runFirstPartyReview({
    ui: fakeUI({ editor: ["# Plan"], select: [SKIP_OPT] }),
    plan: "# Plan",
    writeDraft: noopWrite,
  });
  assert.deepEqual(skip.outcome, { status: "dismissed" });
});

test("runFirstPartyReview: an already-aborted signal short-circuits before any dialog", async () => {
  const ui = fakeUI({ editor: ["# Plan"], select: [APPROVE] });
  const controller = new AbortController();
  controller.abort();
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    signal: controller.signal,
  });
  assert.deepEqual(r.outcome, { status: "aborted" });
  assert.equal(ui.editors.length, 0, "no dialog after an abort");
});

test("runFirstPartyReview: an abort during the editor dialog wins over its result", async () => {
  const controller = new AbortController();
  const ui: PlanReviewUI = {
    async editor() {
      controller.abort();
      return "# Plan";
    },
    async select() {
      throw new Error("the verdict prompt must never open after an abort");
    },
  };
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    signal: controller.signal,
  });
  assert.deepEqual(r.outcome, { status: "aborted" });
});

test("runFirstPartyReview: an abort during the verdict select wins over its result", async () => {
  const controller = new AbortController();
  const ui: PlanReviewUI = {
    async editor(_title, prefill) {
      return prefill;
    },
    async select() {
      controller.abort();
      return APPROVE;
    },
  };
  const r = await runFirstPartyReview({
    ui,
    plan: "# Plan",
    writeDraft: noopWrite,
    signal: controller.signal,
  });
  assert.deepEqual(r.outcome, { status: "aborted" }, "the resolved approve is discarded");
});

// -------------------------------------------------------------- the verdict/skip vocabulary

test("verdictsFor: the subject's manual failsafe varies; the implement-here constant stands alone", () => {
  assert.deepEqual(verdictsFor(PLAN_SUBJECT), {
    approve: APPROVE,
    deny: DENY_OPT,
    skip: SKIP_OPT,
  });
  assert.equal(VERDICT_IMPLEMENT_HERE, "Implement here — no issue saved");
});

test("skipResult/waveLaunchedResult: the headless skip + the non-terminating wave shapes", () => {
  const skip = skipResult();
  assert.equal(skip.content[0]?.text, SKIP_TEXT);
  assert.match(SKIP_TEXT, /no interactive review surface available/);
  assert.deepEqual(skip.details, { ok: true, status: "skipped" });
  assert.equal(skip.terminate, undefined);

  const wave = waveLaunchedResult(PLAN_SUBJECT, "THE GUIDANCE");
  assert.equal(wave.content[0]?.text, "THE GUIDANCE", "the door guidance rides back verbatim");
  assert.deepEqual(wave.details, { ok: true, status: "wave_launched" });
  assert.equal(wave.terminate, undefined, "non-terminating — the decision routes later");
});

// ----------------------------------------------------------- chooseReviewLaunch (unit, pure ui)

const LAUNCH_WAVE = "Browser review + reviewer wave";
const LAUNCH_PLAIN = "Browser review only";

test("chooseReviewLaunch: Esc arms, trim behavior, and every abort re-check point", async () => {
  // Esc at the select -> plain (the flavor choice, never a cancel).
  {
    const ui = fakeUI({ select: [undefined] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan"), { launch: "plain" });
  }
  // The plain pick -> plain; no input dialog.
  {
    const ui = fakeUI({ select: [LAUNCH_PLAIN] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan"), { launch: "plain" });
    assert.equal(ui.inputs.length, 0);
  }
  // The wave pick + a padded custom -> trimmed custom; the caller's signal is FORWARDED to
  // both dialogs (a dropped signal would leave a real pending dialog un-dismissable on abort).
  {
    const controller = new AbortController();
    const ui = fakeUI({ select: [LAUNCH_WAVE], input: ["  the angle  "] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Objective", controller.signal), {
      launch: "wave",
      custom: "the angle",
    });
    assert.equal(ui.selects[0]?.title, "Objective review launch", "the subject noun titles it");
    assert.deepEqual(ui.selects[0]?.options, [LAUNCH_WAVE, LAUNCH_PLAIN]);
    assert.equal(ui.selects[0]?.opts?.signal, controller.signal, "the select gets the signal");
    assert.equal(ui.inputs[0]?.opts?.signal, controller.signal, "the input gets the signal");
    assert.match(ui.inputs[0]?.title ?? "", /Custom review angle/);
  }
  // The wave pick + blank/Esc input -> wave with NO custom key.
  for (const typed of ["   ", undefined]) {
    const ui = fakeUI({ select: [LAUNCH_WAVE], input: [typed] });
    const choice = await chooseReviewLaunch(ui, "Plan");
    assert.equal(choice.launch, "wave");
    assert.equal("custom" in choice, false);
  }
  // Abort at entry: no dialog is ever opened.
  {
    const controller = new AbortController();
    controller.abort();
    const ui = fakeUI({ select: [LAUNCH_WAVE] });
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
    assert.equal(ui.selects.length, 0);
  }
  // Abort landing during the select outranks the resolved selection.
  {
    const controller = new AbortController();
    const ui = fakeUI({});
    ui.select = async (title: string, options: string[]) => {
      ui.selects.push({ title, options });
      controller.abort();
      return LAUNCH_WAVE;
    };
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
    assert.equal(ui.inputs.length, 0, "the input is never reached");
  }
  // Abort landing during the input outranks the resolved text.
  {
    const controller = new AbortController();
    const ui = fakeUI({ select: [LAUNCH_WAVE] });
    ui.input = async (title: string) => {
      ui.inputs.push({ title });
      controller.abort();
      return "typed text";
    };
    assert.deepEqual(await chooseReviewLaunch(ui, "Plan", controller.signal), {
      launch: "aborted",
    });
  }
});

// ------------------------------------------- the subjectReviewOutcomeResult mapper (plan flavor)

test("subjectReviewOutcomeResult: the dismissed arm renders the manual-failsafe skip", () => {
  const result = subjectReviewOutcomeResult(PLAN_SUBJECT, { status: "dismissed" });
  assert.match(String(result.content[0]?.text), /plan review dismissed/);
  assert.match(String(result.content[0]?.text), /\/plan-save \(the manual failsafe\)/);
  assert.deepEqual(result.details, { ok: true, status: "skipped", reason: "dismissed" });
});

test("subjectReviewOutcomeResult: the defensive implement-here arm maps to a skip shape", () => {
  const result = subjectReviewOutcomeResult(PLAN_SUBJECT, {
    status: "implement-here",
    reviewId: "rev-i",
  });
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /nothing saved/);
  assert.match(String(result.content[0]?.text), /outside the execute path/);
  assert.deepEqual(result.details, { ok: true, status: "skipped", reason: "implement-here" });
});

test("subjectReviewOutcomeResult: unavailable + aborted arms", () => {
  const unavailable = subjectReviewOutcomeResult(PLAN_SUBJECT, {
    status: "unavailable",
    warning: "handshake timeout",
  });
  assert.match(String(unavailable.content[0]?.text), /WARNING: handshake timeout/);
  assert.match(
    String(unavailable.content[0]?.text),
    /Present the complete plan to the user in your next message/,
  );
  assert.deepEqual(unavailable.details, {
    ok: false,
    error: "handshake timeout",
    error_type: "unavailable",
    status: "unavailable",
  });

  const aborted = subjectReviewOutcomeResult(PLAN_SUBJECT, { status: "aborted" });
  assert.equal(aborted.content[0]?.text, "plan review aborted (turn interrupted).");
  assert.deepEqual(aborted.details, { ok: true, status: "aborted" });
});

test("subjectReviewOutcomeResult: completed renders DENIED with the plan_draft redirect", () => {
  const result = subjectReviewOutcomeResult(PLAN_SUBJECT, {
    status: "completed",
    approved: false,
    feedback: "needs work",
    reviewId: "rev-d",
  });
  const text = String(result.content[0]?.text);
  assert.match(text, /plan DENIED — revise per this feedback/);
  assert.match(text, /rewrite the working draft with plan_draft, then call plan_review again\./);
  assert.match(text, /Reviewer feedback:\nneeds work/);
  assert.deepEqual(result.details, {
    ok: true,
    status: "completed",
    approved: false,
    feedback: "needs work",
    reviewId: "rev-d",
  });
});

// --------------------------------------------- the approvedSubjectSaveResult pure mapper arms

const APPROVED_FB: Extract<ReviewOutcome, { status: "completed" }> = {
  status: "completed",
  approved: true,
  reviewId: "rev-f",
  feedback: "ship it; watch the edge case",
};

function okSave(gateExited: boolean): SubjectSaveOutcome {
  const result: Result<Record<string, unknown>> = {
    content: [{ type: "text", text: "Saved plan #42 → https://gh/o/r/issues/42" }],
    details: {
      ok: true,
      issue: { id: "42", url: "https://gh/o/r/issues/42" },
      cached: true,
      existed: false,
      updated: false,
      objective_node: null,
      plan_source: "plan-draft",
    },
    terminate: true,
  };
  return { status: "saved", result, gateExited };
}

function failedSave(): SubjectSaveOutcome {
  const result: Result<Record<string, unknown>> = {
    content: [{ type: "text", text: "plan-save failed: gh exploded" }],
    details: { ok: false, error: "gh exploded", error_type: "github_error" },
  };
  return { status: "save-failed", result, gateExited: false };
}

test("approvedSubjectSaveResult: saved -> terminating, feedback verbatim, save message relayed", () => {
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, okSave(true), {
    paramMismatch: false,
  });
  assert.equal(result.terminate, true);
  const text = String(result.content[0]?.text);
  assert.match(text, /plan APPROVED by reviewer\./);
  assert.match(text, /Reviewer feedback \(implementation guidance/);
  assert.match(text, /the approved plan was saved verbatim/);
  assert.match(text, /ship it; watch the edge case/);
  assert.match(text, /Saved plan #42 → https:\/\/gh\/o\/r\/issues\/42/);
  assert.doesNotMatch(text, /differing plan param ignored/);
  assert.doesNotMatch(text, /human edits were written back/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, true);
  assert.equal(details.status, "completed");
  assert.equal(details.approved, true);
  assert.equal(details.reviewId, "rev-f");
  assert.equal(details.feedback, "ship it; watch the edge case");
  assert.equal(details.saved, true);
  assert.equal(details.gateExited, true);
  assert.equal(details.edited, undefined);
  assert.equal((details.save as { ok?: boolean }).ok, true);
});

test("approvedSubjectSaveResult: edited -> the edits-written-back suffix + details.edited", () => {
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, okSave(true), {
    paramMismatch: false,
    edited: true,
  });
  assert.match(
    String(result.content[0]?.text),
    /human edits were written back to the draft and saved/,
  );
  assert.equal((result.details as { edited?: boolean }).edited, true);
});

test("approvedSubjectSaveResult: paramMismatch -> the ignored param is flagged in the text", () => {
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, okSave(false), {
    paramMismatch: true,
  });
  assert.match(
    String(result.content[0]?.text),
    /⚠ differing plan param ignored — the validated draft was reviewed and saved\./,
  );
  assert.equal((result.details as { gateExited?: boolean }).gateExited, false);
});

test("approvedSubjectSaveResult: directEditsFailed -> the saved-WITHOUT-them warning + flag", () => {
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, okSave(true), {
    paramMismatch: false,
    directEditsFailed: true,
  });
  const text = String(result.content[0]?.text);
  assert.match(text, /Direct Edits could NOT be auto-applied/);
  assert.match(text, /saved WITHOUT them/);
  assert.match(text, /apply it to the plan issue manually or via a follow-up/);
  assert.equal((result.details as { direct_edits_applied?: boolean }).direct_edits_applied, false);
});

test("approvedSubjectSaveResult: save-failed -> non-terminating, error surfaced, failsafe directed", () => {
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, failedSave(), {
    paramMismatch: false,
  });
  assert.equal(result.terminate, undefined);
  const text = String(result.content[0]?.text);
  assert.match(text, /plan APPROVED by reviewer, but the auto-save FAILED \(gh exploded\)/);
  assert.match(text, /the session stays read-only/);
  assert.match(text, /\/plan-save \(the manual failsafe\)/);
  assert.match(text, /ship it; watch the edge case/, "feedback still surfaced");
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "gh exploded");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal((details.save as { ok?: boolean }).ok, false);
});

test("approvedSubjectSaveResult: refused-draft -> non-terminating, rewrite + FRESH review, never the failsafe", () => {
  // The approval-time race arm (plan-flavored here; the gist/objective delegators pin their
  // own composed texts): gate untouched, feedback surfaced, and the guidance is rewrite + a
  // fresh review — explicitly NOT the slash-save failsafe (unreviewed replacement bytes).
  const result = approvedSubjectSaveResult(PLAN_SUBJECT, APPROVED_FB, {
    status: "refused-draft",
    problem: "the artifact digest mismatched",
  });
  assert.equal(result.terminate, undefined);
  assert.equal(
    String(result.content[0]?.text),
    "plan APPROVED by reviewer, but the working draft was invalid at save time (the artifact " +
      "digest mismatched) — NOTHING was saved; the session stays read-only. Rewrite it with " +
      "plan_draft and request a fresh review — the replacement bytes were never reviewed, so do " +
      "not use /plan-save to bypass review.\n\nReviewer feedback (fold it into the rewritten " +
      "draft — nothing was saved):\nship it; watch the edge case",
  );
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "the artifact digest mismatched");
  assert.equal(details.error_type, "bad_state");
  assert.equal(details.status, "completed");
  assert.equal(details.approved, true);
  assert.equal(details.feedback, "ship it; watch the edge case");
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});

test("approvedSubjectSaveResult: the defensively-unreachable no-source arm maps to the failed shape", () => {
  const result = approvedSubjectSaveResult(
    PLAN_SUBJECT,
    APPROVED_FB,
    { status: "no-source" },
    { paramMismatch: false },
  );
  assert.equal(result.terminate, undefined);
  assert.match(String(result.content[0]?.text), /auto-save FAILED \(no plan source resolved\)/);
  const details = result.details as Record<string, unknown>;
  assert.equal(details.ok, false);
  assert.equal(details.error, "no plan source resolved");
  assert.equal(details.error_type, "save_failed");
  assert.equal(details.saved, false);
  assert.equal(details.save, null);
});
