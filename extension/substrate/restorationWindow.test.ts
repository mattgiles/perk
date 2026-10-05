// The restoration-window rule (contracts.md §8.40) through REAL bound AgentSessions (Mode A,
// fully offline). An inline late registrant stands in for a reconnecting MCP server: its deferred
// tool is active and recorded in the transcript, and after `/reload` it registers only when the
// test releases it. The invariant half is version-agnostic — inside the window every perk install
// only adds, and the first request after it declares none of the names the window's close
// removed. The restoration half engages on Pi ≥ 1.0.0, whose pending set re-activates the late
// tool when it registers (0.99.2 has no pending set, so there it stays inactive).

import assert from "node:assert/strict";
import { before, test } from "node:test";
import { type ExtensionAPI, type InlineExtension, VERSION } from "@earendil-works/pi-coding-agent";
import {
  COHORT_SETTINGS,
  type PerkInstall,
  type PerkSession,
  recordingRuntime,
  recordPerkInstalls,
  staged,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { discoveryFamily, isPerkTool, LOADOUT_HOST_NAME, perkToolsFor } from "./toolPolicy.ts";

before(ensureToolCatalog);

const LATE = "late_probe";

/** Whether the host keeps restored-but-unregistered tools pending: Pi ≥ 1.0.0 (numeric compare). */
function hostRestoresPending(): boolean {
  const [major = 0, minor = 0, patch = 0] = VERSION.split(/[.+-]/).map((n) =>
    Number.parseInt(n, 10),
  );
  const floor = [1, 0, 0];
  for (const [i, part] of [major, minor, patch].entries()) {
    const min = floor[i] ?? 0;
    if (part !== min) return part > min;
  }
  return true;
}

/** A registrant whose deferred tool registers at load, and after a reload only once released. */
function lateRegistrant(): { extension: InlineExtension; release(): void } {
  let calls = 0;
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const register = (pi: ExtensionAPI) =>
    pi.registerTool({
      name: LATE,
      label: LATE,
      description: "a late-registering deferred tool (test)",
      parameters: { type: "object", properties: {} },
      exposure: "deferred",
      async execute() {
        return { content: [{ type: "text", text: "ok" }], details: {} };
      },
    });
  return {
    extension: {
      name: "late-registrant",
      factory: (pi) => {
        calls += 1;
        if (calls === 1) register(pi);
        else void held.then(() => register(pi));
      },
    },
    release: () => release(),
  };
}

/** An inline command that starts a turn through `pi.sendMessage` — no `before_agent_start`. */
const triggerTurn = (): InlineExtension => ({
  name: "trigger-turn",
  factory: (pi) => {
    pi.registerCommand("probe-turn", {
      description: "start a sendMessage-triggered turn (test)",
      handler: async () => {
        pi.sendMessage(
          { customType: "probe", content: "go", display: false },
          { triggerTurn: true },
        );
      },
    });
  },
});

const isActive = (h: PerkSession, name: string) => h.session.getActiveToolNames().includes(name);
const isRegistered = (h: PerkSession, name: string) =>
  h.session.getAllTools().some((t) => t.name === name);

async function registration(h: PerkSession, name: string): Promise<void> {
  for (let i = 0; i < 200 && !isRegistered(h, name); i++) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.ok(isRegistered(h, name), `${name} registered once released`);
}

/** The registered perk names ineligible in the landing — the reload re-activates every one. */
function ineligibleOwn(h: PerkSession, stage: string, mode: "read-only" | "read-write"): string[] {
  const eligible = new Set(perkToolsFor(stage, mode));
  return h.session
    .getAllTools()
    .map((t) => t.name)
    .filter((name) => isPerkTool(name) && name !== LOADOUT_HOST_NAME && !eligible.has(name));
}

/** Every in-window install kept the live set it replaced (no deactivation clears Pi's pending set). */
function assertOnlyAdds(installs: readonly PerkInstall[], label: string): void {
  assert.ok(installs.length > 0, `${label}: perk reconciled inside the window (non-vacuous)`);
  for (const [i, install] of installs.entries()) {
    for (const name of install.before)
      assert.ok(install.names.includes(name), `${label}: in-window install #${i} removed ${name}`);
  }
}

test("the window after /reload (A): every perk install only adds until the run starts; the first request declares none of the names the close removed; on Pi ≥ 1.0 the late tool comes back", async (t) => {
  const installs = recordPerkInstalls(t);
  const family = discoveryFamily();
  for (const [stage, mode] of [
    ["implement", "read-write"],
    ["objective-plan", "read-only"],
  ] as const) {
    const label = `${stage} ${mode}`;
    const late = lateRegistrant();
    const rt = await recordingRuntime();
    const h = await staged(stage, mode, {
      headful: false,
      model: rt.reg.getModel(),
      modelRuntime: rt.reg.modelRuntime,
      extraExtensions: [toolSearch(), late.extension],
      settings: COHORT_SETTINGS,
    });
    try {
      h.session.setActiveToolsByName([...h.session.getActiveToolNames(), LATE]);
      rt.census();
      await h.session.prompt("census");
      assert.ok(isActive(h, LATE), `${label}: the late tool is active and recorded`);

      const from = installs.length;
      await h.reload();
      assert.ok(!isRegistered(h, LATE), `${label}: not registered yet (the window is open)`);
      const removable = [...family, ...ineligibleOwn(h, stage, mode)];
      for (const name of removable)
        assert.ok(isActive(h, name), `${label}: ${name} stays active until the run starts`);
      assertOnlyAdds(installs.slice(from), label);

      late.release();
      await registration(h, LATE);
      assertOnlyAdds(installs.slice(from), `${label} (after the registration)`);
      if (hostRestoresPending())
        assert.ok(isActive(h, LATE), `${label}: Pi restored the late tool (VERSION ${VERSION})`);

      const before = rt.requests.length;
      rt.census();
      await h.session.prompt("census");
      const first = rt.requests[before];
      assert.ok(first !== undefined, `${label}: the census made a request`);
      for (const name of removable) {
        assert.ok(!first.tools.includes(name), `${label}: ${name} undeclared in the first request`);
        assert.ok(!isActive(h, name), `${label}: ${name} deactivated when the run started`);
      }
      if (hostRestoresPending())
        assert.ok(isActive(h, LATE), `${label}: perk never deactivates the restored foreign tool`);
    } finally {
      h.dispose();
    }
  }
});

test("a /tree restore inside the window (A): after /reload, navigating back to a leaf whose transcript declared an activated family member keeps it through the next run; the rest of the family is switched off", async () => {
  const family = discoveryFamily();
  const restored = "objective_stack_status";
  const rt = await recordingRuntime();
  const h = await staged("implement", "read-write", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch()],
    settings: COHORT_SETTINGS,
  });
  try {
    const [first] = h.entryIds() as [string];
    // A past activation (a `tool_search` hit), recorded in the transcript by the next prompt.
    h.session.setActiveToolsByName([...h.session.getActiveToolNames(), restored]);
    rt.census();
    await h.session.prompt("census");
    assert.ok(rt.last().tools.includes(restored), `${restored} declared in the transcript`);
    const leaf = h.session.sessionManager.getLeafId();
    assert.ok(leaf !== null);

    await h.reload();
    for (const name of family) assert.ok(isActive(h, name), `${name} active inside the window`);
    await h.navigateTo(first);
    await h.navigateTo(leaf);
    const before = rt.requests.length;
    rt.census();
    await h.session.prompt("census");
    const request = rt.requests[before];
    assert.ok(request !== undefined, "the census made a request");
    assert.ok(request.tools.includes(restored), `${restored}, restored by /tree, is declared`);
    assert.ok(isActive(h, restored), `${restored} survives the window's close`);
    for (const name of family.filter((n) => n !== restored)) {
      assert.ok(!request.tools.includes(name), `${name} undeclared`);
      assert.ok(!isActive(h, name), `${name} switched off`);
    }
  } finally {
    h.dispose();
  }
});

test("a sendMessage-triggered turn inside the window (A): no before_agent_start, yet its first request declares none of the removed names and the removals land", async (t) => {
  const installs = recordPerkInstalls(t);
  const family = discoveryFamily();
  const rt = await recordingRuntime();
  const h = await staged("objective-plan", "read-only", {
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), triggerTurn()],
    settings: COHORT_SETTINGS,
  });
  try {
    const from = installs.length;
    await h.reload();
    const removable = [...family, ...ineligibleOwn(h, "objective-plan", "read-only")];
    for (const name of removable) assert.ok(isActive(h, name), `${name} active inside the window`);
    assertOnlyAdds(installs.slice(from), "reload");

    const before = rt.requests.length;
    rt.census();
    await h.invokeCommand("probe-turn");
    for (let i = 0; i < 200 && rt.requests.length === before; i++) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    await h.session.waitForIdle();
    const first = rt.requests[before];
    assert.ok(first !== undefined, "the triggered turn made a request");
    for (const name of removable) {
      assert.ok(!first.tools.includes(name), `${name} undeclared in the triggered turn's request`);
      assert.ok(!isActive(h, name), `${name} deactivated when the triggered run started`);
    }
  } finally {
    h.dispose();
  }
});
