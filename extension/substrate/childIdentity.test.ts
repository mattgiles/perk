import assert from "node:assert/strict";
import { test } from "node:test";
import { createChildIdentity, parseChildIdentity } from "./childIdentity.ts";
import { readNativeSessionKey } from "./nativeSessionKey.ts";

const tag = (name: string) => `<active_agent name="${name}"/>`;
const provenance = "native-system-prompt-prefix";

test("bounded first-line parser: exact shapes, diagnostics, Unicode and canonical entities", () => {
  const cases: [string, string, string, string?][] = [
    ["known", tag("perk.pr-reviewer"), "available", "perk.pr-reviewer"],
    ["custom case preserved", tag("CUSTOM.Agent"), "available", "CUSTOM.Agent"],
    ["empty prompt", "", "absent"],
    ["later marker", `instructions\n${tag("perk.pr-reviewer")}`, "absent"],
    ["partial literal", "<active_agent", "malformed"],
    ["plural", '<active_agents name="x"/>', "malformed"],
    ["misspelled", '<active_agnet name="x"/>', "absent"],
    ["case changed", '<Active_agent name="x"/>', "absent"],
    ["prefix", `prefix ${tag("x")}`, "malformed"],
    ["leading padding", ` ${tag("x")}`, "malformed"],
    ["trailing padding", `${tag("x")} `, "malformed"],
    ["CR retained", `${tag("x")}\r\nbody`, "malformed"],
    ["extra attribute", '<active_agent name="x" role="y"/>', "malformed"],
    ["single quotes", "<active_agent name='x'/>", "malformed"],
    ["double tags", `${tag("x")}${tag("y")}`, "malformed"],
    ["empty name", tag(""), "malformed"],
    ["256 bytes", tag("x".repeat(256)), "available", "x".repeat(256)],
    ["257 bytes", tag("x".repeat(257)), "malformed"],
    ["multibyte 256", tag("é".repeat(128)), "available", "é".repeat(128)],
    ["multibyte one over", tag(`${"é".repeat(128)}x`), "malformed"],
    ["astral 256", tag("😀".repeat(64)), "available", "😀".repeat(64)],
    ["all four entities", tag("&amp;&quot;&lt;&gt;"), "available", '&"<>'],
    ["single pass", tag("&amp;quot;"), "available", "&quot;"],
    ["unknown entity", tag("&apos;"), "malformed"],
    ["numeric entity", tag("&#34;"), "malformed"],
    ["literal ampersand", tag("x&y"), "malformed"],
    ["literal quote", tag('x"y'), "malformed"],
    ["literal less", tag("x<y"), "malformed"],
    ["literal greater", tag("x>y"), "malformed"],
    ["NUL", tag("x\u0000"), "malformed"],
    ["C1 control", tag("x\u0085"), "malformed"],
    ["tab", tag("x\t"), "malformed"],
    ["format not Cc", tag("x\u200d"), "available", "x\u200d"],
    ["4096 bytes unrelated", "x".repeat(4096), "absent"],
    ["4097 bytes unrelated", "x".repeat(4097), "malformed"],
    ["4096 multibyte", "é".repeat(2048), "absent"],
    ["4097 multibyte", `${"é".repeat(2048)}x`, "malformed"],
    ["bounded tagged line", tag("x".repeat(4073)), "malformed"],
    ["large later text ignored", `${tag("x")}\n${"x".repeat(100_000)}`, "available", "x"],
  ];
  for (const [label, prompt, result, name] of cases) {
    assert.deepEqual(
      parseChildIdentity(prompt),
      result === "available"
        ? { status: "available", name, provenance }
        : { status: "unavailable", reason: result, provenance },
      label,
    );
  }
});

function context() {
  let sessionId = "uuid-a";
  let sessionFile: string | null | undefined = "/one/session.jsonl";
  let brokenKey = false;
  let brokenPrompt = false;
  let prompt = tag("perk.pr-reviewer");
  let promptReads = 0;
  const warnings: string[] = [];
  const ctx = {
    hasUI: true,
    ui: {
      notify: (message: string) => {
        warnings.push(message);
      },
    },
    sessionManager: {
      getSessionId: () => {
        if (brokenKey) throw "SENSITIVE_KEY";
        return sessionId;
      },
      getSessionFile: () => sessionFile,
    },
    getSystemPrompt: () => {
      promptReads++;
      if (brokenPrompt) throw "SENSITIVE_PROMPT";
      return prompt;
    },
  };
  return {
    ctx,
    warnings,
    key: (id: string, file: string | null | undefined) => {
      sessionId = id;
      sessionFile = file;
    },
    breakKey: (value: boolean) => {
      brokenKey = value;
    },
    breakPrompt: (value: boolean) => {
      brokenPrompt = value;
    },
    prompt: (value: string) => {
      prompt = value;
    },
    reads: () => promptReads,
  };
}

test("full UUID/path/null keys distinguish sessions; unreadable paths and empty IDs are classified", () => {
  const h = context();
  const identity = createChildIdentity();
  identity.capture(h.ctx, true);
  for (const [id, file] of [
    ["uuid-b", "/one/session.jsonl"],
    ["uuid-a", "/two/session.jsonl"],
    ["uuid-a", null],
  ] as const) {
    h.key(id, file);
    assert.deepEqual(identity.lookup(h.ctx), {
      runner: true,
      identity: { status: "unavailable", reason: "stale", provenance },
    });
  }
  h.key("uuid-a", "/one/session.jsonl");
  assert.equal(identity.lookup(h.ctx).identity.status, "available");
  h.key("", null);
  assert.deepEqual(readNativeSessionKey(h.ctx), { status: "unreadable" });
  assert.deepEqual(identity.lookup(h.ctx), {
    runner: true,
    identity: { status: "unavailable", reason: "unreadable", provenance },
  });
  assert.deepEqual(
    readNativeSessionKey({
      sessionManager: {
        getSessionId: () => "id",
        getSessionFile: () => {
          throw "SECRET";
        },
      },
    }),
    { status: "unreadable" },
  );
  h.key("memory", undefined);
  assert.deepEqual(readNativeSessionKey(h.ctx), {
    status: "known",
    key: { sessionId: "memory", sessionFile: null },
  });
});

test("capture replaces advice; lookups never read later prompt or environment; activations and shutdown isolate", (t) => {
  const savedRunner = process.env.PI_SUBAGENT_CHILD;
  t.after(() => {
    if (savedRunner === undefined) delete process.env.PI_SUBAGENT_CHILD;
    else process.env.PI_SUBAGENT_CHILD = savedRunner;
  });
  const h = context();
  const first = createChildIdentity();
  const second = createChildIdentity();
  first.capture(h.ctx, true);
  h.prompt(tag("custom"));
  second.capture(h.ctx, false);
  process.env.PI_SUBAGENT_CHILD = "0";
  h.breakPrompt(true);
  assert.equal(first.lookup(h.ctx).runner, true, "later env cannot replace the captured fallback");
  assert.equal(first.lookup(h.ctx).identity.status, "available");
  assert.deepEqual(second.lookup(h.ctx), {
    runner: false,
    identity: { status: "available", name: "custom", provenance },
  });
  assert.equal(h.reads(), 2);
  first.capture(h.ctx, true);
  assert.deepEqual(first.lookup(h.ctx).identity, {
    status: "unavailable",
    reason: "unreadable",
    provenance,
  });
  first.clear();
  assert.equal(first.lookup(h.ctx).runner, false);
  assert.equal(second.lookup(h.ctx).identity.status, "available");
  h.breakPrompt(false);
  h.prompt(tag("writer"));
  first.capture(h.ctx, false);
  assert.deepEqual(first.lookup(h.ctx).identity, {
    status: "available",
    name: "writer",
    provenance,
  });
});

test("known and anonymous warning buckets are bounded, private, and reset only in their own scopes", () => {
  const h = context();
  const identity = createChildIdentity();
  h.prompt("SENSITIVE_PROMPT");
  identity.capture(h.ctx, false);
  assert.equal(h.warnings.length, 0);
  identity.capture(h.ctx, true);
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 1);
  h.prompt("<active_agent SENSITIVE_NAME");
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 2);
  h.key("different", "/other/session.jsonl");
  identity.lookup(h.ctx);
  identity.lookup(h.ctx);
  assert.equal(h.warnings.length, 3, "stale warns on captured scope");
  h.breakKey(true);
  identity.capture(h.ctx, true);
  identity.capture(h.ctx, true);
  identity.lookup(h.ctx);
  assert.equal(h.warnings.length, 4);
  h.breakKey(false);
  assert.equal(
    identity.lookup(h.ctx).identity.status,
    "unavailable",
    "anonymous capture is not reusable",
  );
  h.key("uuid-a", "/one/session.jsonl");
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 4, "same known scope survives a key outage");
  h.key("different", "/other/session.jsonl");
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 5, "different known key resets known reasons");
  h.breakKey(true);
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 5, "anonymous reasons survive readable recovery");
  identity.clear();
  identity.capture(h.ctx, true);
  assert.equal(h.warnings.length, 6);
  assert.doesNotMatch(h.warnings.join("\n"), /SENSITIVE/);
});
