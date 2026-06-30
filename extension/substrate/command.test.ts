import assert from "node:assert/strict";
import { test } from "node:test";
import type { ExtensionAPI, RegisteredCommand } from "@earendil-works/pi-coding-agent";
import { registerPerkCommand } from "./command.ts";

type WrappedHandler = RegisteredCommand["handler"];

/** A fake `pi` that captures the single registerCommand(name, options) call. */
function fakePi(): {
  pi: ExtensionAPI;
  captured: { name: string; handler: WrappedHandler }[];
} {
  const captured: { name: string; handler: WrappedHandler }[] = [];
  const pi = {
    registerCommand(name: string, options: Omit<RegisteredCommand, "name" | "sourceInfo">) {
      captured.push({ name, handler: options.handler });
    },
  } as unknown as ExtensionAPI;
  return { pi, captured };
}

/** A fake headful ctx that records notify calls. */
function headfulCtx(notifies: { message: string; severity?: string }[]) {
  return {
    hasUI: true,
    ui: {
      notify: (message: string, severity?: string) => {
        notifies.push({ message, severity });
      },
    },
  };
}

test("registerPerkCommand emits one info entry toast before the inner handler runs", async () => {
  const { pi, captured } = fakePi();
  const seen: { args: string; ctx: unknown }[] = [];
  let completed = false;
  const handler = async (args: string, ctx: unknown) => {
    // Yield control so an omitted `await` in the wrapper would let the wrapped handler
    // resolve before this records — proving the wrapper genuinely awaits to completion.
    await new Promise((resolve) => setTimeout(resolve, 0));
    seen.push({ args, ctx });
    completed = true;
  };

  // biome-ignore lint/suspicious/noExplicitAny: minimal handler shape for the test
  registerPerkCommand(pi, "demo", { handler: handler as any });
  assert.equal(captured.length, 1);
  assert.equal(captured[0]?.name, "demo");

  const notifies: { message: string; severity?: string }[] = [];
  const ctx = headfulCtx(notifies);
  // biome-ignore lint/suspicious/noExplicitAny: fake ctx satisfies the ReportTarget slice
  await captured[0]?.handler("the-args", ctx as any);

  // exactly one info notify with the running… message
  assert.deepEqual(notifies, [{ message: "perk: demo — running…", severity: "info" }]);
  // the wrapper awaited the inner handler to completion (it yielded control before recording)
  assert.equal(completed, true);
  // the inner handler received the same (args, ctx)
  assert.equal(seen.length, 1);
  assert.equal(seen[0]?.args, "the-args");
  assert.equal(seen[0]?.ctx, ctx);
});

test("registerPerkCommand toast precedes handler side effects", async () => {
  const { pi, captured } = fakePi();
  const order: string[] = [];
  const notifies: { message: string; severity?: string }[] = [];
  const ctx = {
    hasUI: true,
    ui: {
      notify: (message: string, severity?: string) => {
        order.push(`toast:${message}`);
        notifies.push({ message, severity });
      },
    },
  };
  const handler = async () => {
    order.push("handler");
  };
  // biome-ignore lint/suspicious/noExplicitAny: minimal handler shape for the test
  registerPerkCommand(pi, "land", { handler: handler as any });
  // biome-ignore lint/suspicious/noExplicitAny: fake ctx satisfies the ReportTarget slice
  await captured[0]?.handler("", ctx as any);

  assert.deepEqual(order, ["toast:perk: land — running…", "handler"]);
});

test("registerPerkCommand is headless-safe (!hasUI falls to stderr, handler still runs)", async () => {
  const { pi, captured } = fakePi();
  let ran = false;
  const handler = async () => {
    ran = true;
  };
  // biome-ignore lint/suspicious/noExplicitAny: minimal handler shape for the test
  registerPerkCommand(pi, "demo", { handler: handler as any });

  const errors: string[] = [];
  const original = console.error;
  console.error = (...args: unknown[]) => errors.push(args.map(String).join(" "));
  try {
    const ctx = { hasUI: false, ui: { notify: () => assert.fail("notify in headless") } };
    // biome-ignore lint/suspicious/noExplicitAny: fake ctx satisfies the ReportTarget slice
    await captured[0]?.handler("", ctx as any);
  } finally {
    console.error = original;
  }

  assert.equal(ran, true);
  // the report() stderr fallback actually emitted the entry toast in headless mode
  assert.ok(
    errors.some((e) => e.includes("perk: demo — running…")),
    `stderr fallback emitted the entry toast: ${JSON.stringify(errors)}`,
  );
});
