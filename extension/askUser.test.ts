// #187 — fully-offline coverage for the `ask_user_question` pure core. Mirrors ciExecutor.test.ts:
// a pure core over an injected fake UI (no network, no real dialogs). See askUser.ts.

import assert from "node:assert/strict";
import { test } from "node:test";
import { type AskUserUI, OTHER_CHOICE, runAskUserQuestion } from "./askUser.ts";

interface Call {
  method: "select" | "input";
  title: string;
  options?: string[];
  opts?: { signal?: AbortSignal };
}

/** A fake UI that records every call and returns scripted values (one per method). */
function fakeUI(scripts: { select?: string | undefined; input?: string | undefined }): {
  ui: AskUserUI;
  calls: Call[];
} {
  const calls: Call[] = [];
  const ui: AskUserUI = {
    async select(title, options, opts) {
      calls.push({ method: "select", title, options, opts });
      return scripts.select;
    },
    async input(title, _placeholder, opts) {
      calls.push({ method: "input", title, opts });
      return scripts.input;
    },
  };
  return { ui, calls };
}

function textOf(result: { content: { type: "text"; text: string }[] }): string {
  return result.content[0]?.text ?? "";
}

function at(calls: Call[], i: number): Call {
  const c = calls[i];
  if (!c) throw new Error(`no call at index ${i}`);
  return c;
}

test("headless: hasUI:false → no-user sentinel, UI never called", async () => {
  const { ui, calls } = fakeUI({});
  const result = await runAskUserQuestion({ hasUI: false, ui, question: "Which?" });
  assert.match(textOf(result), /no interactive user available/);
  assert.deepEqual(result.details, { ok: true, answered: false });
  assert.equal(calls.length, 0);
});

test("empty question → no-question text, UI never called", async () => {
  const { ui, calls } = fakeUI({ input: "ignored" });
  const result = await runAskUserQuestion({ hasUI: true, ui, question: "   " });
  assert.equal(textOf(result), "ask_user_question: no question provided.");
  assert.equal(calls.length, 0);
});

test("free-text (no options): input called with question, typed answer returned", async () => {
  const { ui, calls } = fakeUI({ input: "blue" });
  const result = await runAskUserQuestion({ hasUI: true, ui, question: "Favorite color?" });
  assert.equal(textOf(result), "blue");
  assert.deepEqual(result.details, { ok: true, answered: true });
  assert.equal(calls.length, 1);
  assert.equal(at(calls, 0).method, "input");
  assert.equal(at(calls, 0).title, "Favorite color?");
});

test("select: select called with options + OTHER_CHOICE, chosen option returned", async () => {
  const { ui, calls } = fakeUI({ select: "B" });
  const result = await runAskUserQuestion({
    hasUI: true,
    ui,
    question: "Pick one",
    options: ["A", "B"],
  });
  assert.equal(textOf(result), "B");
  assert.equal(calls.length, 1);
  assert.equal(at(calls, 0).method, "select");
  assert.deepEqual(at(calls, 0).options, ["A", "B", OTHER_CHOICE]);
});

test("select → Other → input: routes to free-text and returns the typed answer", async () => {
  const { ui, calls } = fakeUI({ select: OTHER_CHOICE, input: "custom answer" });
  const result = await runAskUserQuestion({
    hasUI: true,
    ui,
    question: "Pick one",
    options: ["A", "B"],
  });
  assert.equal(textOf(result), "custom answer");
  assert.equal(calls.length, 2);
  assert.equal(at(calls, 0).method, "select");
  assert.equal(at(calls, 1).method, "input");
});

test("dismiss at select: select returns undefined → dismissed text", async () => {
  const { ui } = fakeUI({ select: undefined });
  const result = await runAskUserQuestion({
    hasUI: true,
    ui,
    question: "Pick one",
    options: ["A", "B"],
  });
  assert.deepEqual(result.details, { ok: true, answered: false });
  assert.equal(textOf(result), "(no answer — the user dismissed the prompt.)");
});

test("dismiss at input: input returns undefined → dismissed text", async () => {
  const { ui } = fakeUI({ input: undefined });
  const result = await runAskUserQuestion({ hasUI: true, ui, question: "Free text?" });
  assert.equal(textOf(result), "(no answer — the user dismissed the prompt.)");
});

test("dismiss at Other→input: dismissed text after choosing OTHER_CHOICE", async () => {
  const { ui } = fakeUI({ select: OTHER_CHOICE, input: undefined });
  const result = await runAskUserQuestion({
    hasUI: true,
    ui,
    question: "Pick one",
    options: ["A"],
  });
  assert.equal(textOf(result), "(no answer — the user dismissed the prompt.)");
});

test("signal propagation: select and input receive the passed signal in opts", async () => {
  const controller = new AbortController();
  const { ui, calls } = fakeUI({ select: OTHER_CHOICE, input: "x" });
  await runAskUserQuestion({
    hasUI: true,
    ui,
    question: "Pick one",
    options: ["A"],
    signal: controller.signal,
  });
  assert.equal(at(calls, 0).opts?.signal, controller.signal);
  assert.equal(at(calls, 1).opts?.signal, controller.signal);
});
