// Native discovery and the restoration window at a RESTORED startup on Pi 1.4.0 (contracts.md
// §8.40 "Native discovery" / "Restoration window"): Pi restores a resumed or forked session's
// recorded loadout in its constructor, before any `session_start`, and keeps restored-but-
// unregistered tools pending until the first run starts. The family registers deferred, so Pi's
// restore is the keep: a recorded member comes back, the rest stay off, and perk's startup
// reconciliation only adds until `agent_start` — a late MCP tool recorded in the transcript comes
// back when its server reconnects.
//
// Mode B (`packages: []`): perk loads by path before `builtin:tool-search` / `builtin:mcp` —
// production's extension order — and runs in the loader's own module instance, so every assertion
// reads the live session. Fully offline: the MCP server is Pi's own in-memory transport pair
// (`@earendil-works/pi-mcp/testing`) behind a test-written responder that can hold a connection's
// `initialize`. The fixture shapes mirror the record's script
// (`docs/design/archive/pi-1.4.0-restored-discovery.md` § "The script (verbatim)").

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { before, test } from "node:test";
import {
  createMcpExtension,
  type InlineExtension,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import { createInMemoryTransportPair } from "@earendil-works/pi-mcp/testing";
import {
  COHORT_SETTINGS,
  loadAt,
  PERK_EXTENSION_PATH,
  type PerkInstall,
  type PerkSession,
  plantSession,
  type RecordedRequest,
  recordingRuntime,
  recordPerkInstalls,
  scaffoldRepo,
  spyInjections,
  toolSearch,
} from "../testing/harness.ts";
import { ensureToolCatalog } from "../testing/toolCatalog.ts";
import { discoveryFamily, isEligible } from "./toolPolicy.ts";

before(ensureToolCatalog);

/** The recorded member (a past search or prime) and the rest of the family. */
const P = "objective_stack_status";
const others = (): string[] => discoveryFamily().filter((name) => name !== P);
const TOOL = "mcp__docs__search";
const TOOL_SEARCH_PATH = "builtin:tool-search";
const MCP_PATH = "builtin:mcp";

type Recorder = Awaited<ReturnType<typeof recordingRuntime>>;

const isActive = (h: PerkSession, name: string): boolean =>
  h.session.getActiveToolNames().includes(name);
const isRegistered = (h: PerkSession, name: string): boolean =>
  h.session.getAllTools().some((t) => t.name === name);

/**
 * A Mode B perk session over `manager`: a discovery host (`tool_search` registered and opted in)
 * unless `nonparticipant` (registered, never activated). Asserts production's extension order.
 */
async function perkB(
  cwd: string,
  rt: Recorder,
  manager: SessionManager,
  more: { extras?: InlineExtension[]; tools?: string[]; nonparticipant?: boolean } = {},
): Promise<PerkSession> {
  const h = await loadAt(cwd, {
    packages: [],
    headful: false,
    model: rt.reg.getModel(),
    modelRuntime: rt.reg.modelRuntime,
    extraExtensions: [toolSearch(), ...(more.extras ?? [])],
    ...(more.nonparticipant === true ? {} : { settings: COHORT_SETTINGS }),
    env: { PERK_RUN_ID: undefined },
    sessionManager: manager,
    ...(more.tools !== undefined ? { tools: more.tools } : {}),
  });
  const paths = h.session.extensionRunner.getExtensionPaths();
  const perkAt = paths.indexOf(PERK_EXTENSION_PATH);
  assert.ok(perkAt !== -1, `fixture: perk bound by path (${paths.join(", ")})`);
  assert.ok(perkAt < paths.indexOf(TOOL_SEARCH_PATH), `fixture: perk precedes ${TOOL_SEARCH_PATH}`);
  if (paths.includes(MCP_PATH))
    assert.ok(perkAt < paths.indexOf(MCP_PATH), `fixture: perk precedes ${MCP_PATH}`);
  return h;
}

/** One census prompt; returns its (single) request. */
async function census(h: PerkSession, rt: Recorder): Promise<RecordedRequest> {
  const before = rt.requests.length;
  rt.census();
  await h.session.prompt("census");
  assert.equal(rt.requests.length, before + 1, "fixture: one request per census");
  const request = rt.requests[before];
  assert.ok(request !== undefined, "fixture: the census made a request");
  return request;
}

const plantImplement = (cwd: string): string =>
  plantSession(cwd, [{ stage: "implement", mode: "read-write" }]);

/** The seed: a fresh startup over a planted implement file, `member` activated, two censuses. */
async function seed(
  cwd: string,
  rt: Recorder,
  member: string,
  more: { nonparticipant?: boolean } = {},
): Promise<{ h: PerkSession; file: string }> {
  const file = plantImplement(cwd);
  const h = await perkB(cwd, rt, SessionManager.open(file), more);
  assert.equal(h.workflowState().stage, "implement", "fixture: the seed's stage");
  h.session.setActiveToolsByName([...h.session.getActiveToolNames(), member]);
  await census(h, rt);
  await census(h, rt);
  assert.ok(rt.last().tools.includes(member), `fixture: ${member} declared in the seed`);
  assert.ok(isActive(h, member), `fixture: ${member} active at the seed's end`);
  return { h, file };
}

/** Quit the session the way Pi does (`session_shutdown`), then dispose it. */
async function close(h: PerkSession): Promise<void> {
  try {
    await h.session.extensionRunner.emit({ type: "session_shutdown", reason: "quit" } as never);
  } catch {}
  h.dispose();
}

// --- install assertions (perk's own installs, attributed by stack) ----------------------------------

/** Non-empty, and every install kept the live set it replaced (Pi's pending set survives). */
function assertOnlyAdds(installs: readonly PerkInstall[], label: string): void {
  assert.ok(installs.length > 0, `${label}: perk reconciled (non-vacuous)`);
  for (const [i, install] of installs.entries())
    for (const name of install.before)
      assert.ok(install.names.includes(name), `${label}: install #${i} removed ${name}`);
}

/** No install dropped `name` from the live set. */
function assertKept(installs: readonly PerkInstall[], name: string, label: string): void {
  for (const [i, install] of installs.entries())
    assert.ok(
      !install.before.includes(name) || install.names.includes(name),
      `${label}: install #${i} dropped ${name}`,
    );
}

/** No install ever named one of `names` (perk never made them live). */
function assertNeverLive(
  installs: readonly PerkInstall[],
  names: readonly string[],
  label: string,
): void {
  for (const [i, install] of installs.entries())
    for (const name of names)
      assert.ok(!install.names.includes(name), `${label}: install #${i} named ${name}`);
}

// --- the fake MCP server ----------------------------------------------------------------------------

type McpTool = { name: string; description: string; inputSchema: Record<string, unknown> };
const SEARCH: McpTool = {
  name: "search",
  description: "Search the docs index for pages matching a query.",
  inputSchema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
};

type Fake = {
  connections: number;
  /** Hold the NEXT connection's `initialize`. */
  holdNext(): void;
  /** Resolves when the held `initialize` has arrived at the server. */
  held(): Promise<void>;
  /** Answer the held `initialize`. */
  release(): void;
  client(): ReturnType<typeof createInMemoryTransportPair>["client"];
};

/** One server shared by a row's sessions; each connection gets its own transport pair. */
function fakeServer(tools: readonly McpTool[]): Fake {
  let holdArmed = false;
  let arrived: Promise<void> = Promise.resolve();
  let markArrived: (() => void) | undefined;
  let releaseHeld: (() => void) | undefined;
  const fake: Fake = {
    connections: 0,
    holdNext() {
      holdArmed = true;
      arrived = new Promise((resolve) => {
        markArrived = resolve;
      });
    },
    held: () => arrived,
    release() {
      const release = releaseHeld;
      releaseHeld = undefined;
      assert.ok(release !== undefined, "fixture: a held initialize to release");
      release();
    },
    client() {
      fake.connections += 1;
      const { client, server } = createInMemoryTransportPair();
      let gate: Promise<void> | undefined;
      if (holdArmed) {
        holdArmed = false;
        gate = new Promise((resolve) => {
          releaseHeld = resolve;
        });
      }
      const signal = markArrived;
      markArrived = undefined;
      server.onMessage(async (raw) => {
        const message = raw as {
          id?: number | string;
          method?: string;
          params?: { protocolVersion?: string };
        };
        if (message.id === undefined || typeof message.method !== "string") return;
        let result: unknown = {};
        if (message.method === "initialize") {
          if (gate !== undefined) {
            signal?.();
            await gate;
          }
          result = {
            protocolVersion: message.params?.protocolVersion,
            capabilities: { tools: {} },
            serverInfo: { name: "docs", version: "1.0.0" },
          };
        } else if (message.method === "tools/list") {
          result = { tools };
        } else if (message.method === "tools/call") {
          result = { content: [{ type: "text", text: "ok" }] };
        }
        await server.send({ jsonrpc: "2.0", id: message.id, result } as never).catch(() => {});
      });
      void server.start();
      return client;
    },
  };
  return fake;
}

/** A FRESH `builtin:mcp` extension over `fake` (one per session), its server deferred. */
function mcp(fake: Fake): InlineExtension {
  const logs = mkdtempSync(join(tmpdir(), "perk-mcp-log-"));
  return {
    name: "mcp",
    factory: createMcpExtension({
      loadConfig: () => ({
        servers: [
          {
            name: "docs",
            config: { url: "http://unused.invalid", exposure: "deferred" },
            source: "fixture",
          },
        ],
        errors: [],
      }),
      createTransport: () => fake.client() as never,
      logPath: join(logs, "mcp.log"),
    }),
    builtin: true,
  };
}

/** Wait (bounded) for the MCP tool's registration. */
async function registration(h: PerkSession): Promise<void> {
  const deadline = Date.now() + 5000;
  while (!isRegistered(h, TOOL)) {
    if (Date.now() > deadline) throw new Error(`fixture: ${TOOL} never registered`);
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

/** Load the MCP tool through `tool_search` into the active set and the transcript. */
async function seedMcp(h: PerkSession, rt: Recorder): Promise<void> {
  await registration(h);
  rt.callThenStop("tool_search", { query: "search the docs" });
  await h.session.prompt("load");
  assert.ok(isActive(h, TOOL), "fixture: the MCP tool is active after the search");
  const request = await census(h, rt);
  assert.ok(request.tools.includes(TOOL), "fixture: the MCP tool is declared (recorded)");
}

// --- the rows ---------------------------------------------------------------------------------------

test("resume and fork keep (B): Pi restored the recorded member before perk ran; the startup reconciliation only adds; it is declared and stays active, the rest of the family stays off", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const rt = await recordingRuntime();
  const { h: seeded, file } = await seed(cwd, rt, P);
  await close(seeded);
  const managers = [
    ["resume", SessionManager.open(file)],
    ["fork", SessionManager.forkFrom(file, cwd)],
  ] as const;
  for (const [how, manager] of managers) {
    installs.length = 0;
    const h = await perkB(cwd, rt, manager);
    try {
      assert.equal(h.workflowState().stage, "implement", `${how}: the resumed stage`);
      assert.ok(isActive(h, P), `${how}: Pi restored it`);
      for (const name of discoveryFamily())
        assert.equal(h.toolInfo(name)?.exposure, "deferred", `${how}: ${name} registered deferred`);
      assertOnlyAdds(installs, `${how}: startup (the diet waits in the window)`);
      const r1 = await census(h, rt);
      assert.ok(r1.tools.includes(P), `${how}: declared in the first request`);
      assert.ok(isActive(h, P), `${how}: still active after it`);
      assertKept(installs, P, how);
      assertNeverLive(installs, others(), how);
      for (const name of others()) {
        assert.ok(!r1.tools.includes(name), `${how}: ${name} undeclared`);
        assert.ok(!isActive(h, name), `${how}: ${name} inactive`);
      }
      const r2 = await census(h, rt);
      assert.ok(r2.tools.includes(P), `${how}: still declared in the second request`);
    } finally {
      await close(h);
    }
  }
});

test("consecutive resume after one request (B): nothing of perk's was live at the first request to be recorded, so a second resume restores only the recorded member", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const rt = await recordingRuntime();
  const { h: seeded, file } = await seed(cwd, rt, P);
  await close(seeded);
  installs.length = 0;
  const once = await perkB(cwd, rt, SessionManager.open(file));
  try {
    await census(once, rt);
  } finally {
    await close(once);
  }
  const h = await perkB(cwd, rt, SessionManager.open(file));
  try {
    assert.ok(isActive(h, P), "the recorded member restored again");
    const r1 = await census(h, rt);
    assert.ok(r1.tools.includes(P), "and declared");
    for (const name of others()) {
      assert.ok(!r1.tools.includes(name), `${name} undeclared`);
      assert.ok(!isActive(h, name), `${name} inactive`);
    }
    assertNeverLive(installs, others(), "both resumes");
  } finally {
    await close(h);
  }
});

test("late MCP keep (B): a deferred MCP tool recorded in the transcript, whose server reconnects after perk's startup reconciliation, comes back active on resume", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const fake = fakeServer([SEARCH]);
  const rt = await recordingRuntime();
  const file = plantImplement(cwd);
  const seeded = await perkB(cwd, rt, SessionManager.open(file), { extras: [mcp(fake)] });
  try {
    assert.equal(seeded.workflowState().stage, "implement", "fixture: the seed's stage");
    await seedMcp(seeded, rt);
  } finally {
    await close(seeded);
  }
  assert.ok(readFileSync(file, "utf8").includes(TOOL), "fixture: the session file names the tool");
  const connections = fake.connections;
  fake.holdNext();
  installs.length = 0;
  const h = await perkB(cwd, rt, SessionManager.open(file), { extras: [mcp(fake)] });
  try {
    assert.ok(!isRegistered(h, TOOL), "held: not registered yet");
    await fake.held();
    assert.equal(fake.connections, connections + 1, "fixture: exactly one new connection");
    fake.release();
    await registration(h);
    assert.ok(isActive(h, TOOL), "Pi's pending set activated it");
    assertOnlyAdds(installs, "every install since the load");
    const r1 = await census(h, rt);
    assert.ok(r1.tools.includes(TOOL), "declared in the first request");
    assert.ok(isActive(h, TOOL), "still active after the run");
  } finally {
    await close(h);
  }
});

test("allowlist resume (B): a --tools allowlist that names the deferred member activates it (Pi seeds the initial active set from the named entries) and perk keeps it; a pattern entry that matches it leaves it inactive and undeclared (Pi's pattern arm activates declarable names only) until a door primes it", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const rt = await recordingRuntime();
  const { h: seeded, file } = await seed(cwd, rt, P);
  await close(seeded);
  const base = ["read", "bash", "edit", "write", "tool_search", "perk_stage"];

  installs.length = 0;
  const named = await perkB(cwd, rt, SessionManager.open(file), { tools: [...base, P] });
  try {
    assert.equal(named.toolInfo(P)?.exposure, "deferred", "named: registered deferred");
    assert.ok(isActive(named, P), "named: active at startup");
    const r1 = await census(named, rt);
    assert.ok(r1.tools.includes(P), "named: declared");
    assert.ok(isActive(named, P), "named: still active after the run");
    assertKept(installs, P, "named");
  } finally {
    await close(named);
  }

  const matched = await perkB(cwd, rt, SessionManager.open(file), {
    tools: [...base, "objective_stack_*"],
  });
  try {
    assert.ok(isRegistered(matched, P), "matched: registered (the pattern keeps it)");
    assert.equal(matched.toolInfo(P)?.exposure, "deferred", "matched: registered deferred");
    assert.ok(!isActive(matched, P), "matched: inactive");
    const r1 = await census(matched, rt);
    assert.ok(!r1.tools.includes(P), "matched: undeclared");
    spyInjections(matched);
    await matched.invokeCommand("objective-sync", "7");
    assert.ok(isActive(matched, P), "matched: the door primed it");
    const r2 = await census(matched, rt);
    assert.ok(r2.tools.includes(P), "matched: declared on the next request");
  } finally {
    await close(matched);
  }
});

test("nonparticipant resume (B): the family is re-declared direct; every implement-eligible member is active and declared and no perk install drops one", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const rt = await recordingRuntime();
  const { h: seeded, file } = await seed(cwd, rt, P, { nonparticipant: true });
  await close(seeded);
  installs.length = 0;
  const h = await perkB(cwd, rt, SessionManager.open(file), { nonparticipant: true });
  try {
    assert.ok(!isActive(h, "tool_search"), "fixture: tool_search registered, never activated");
    for (const name of discoveryFamily())
      assert.equal(h.toolInfo(name)?.exposure, "direct", `${name} re-declared direct`);
    const members = discoveryFamily().filter((name) =>
      isEligible(name, undefined, "implement", "read-write"),
    );
    assert.ok(members.length > 0, "fixture: implement-eligible members");
    for (const name of members) assert.ok(isActive(h, name), `${name} active`);
    const r1 = await census(h, rt);
    for (const name of members) {
      assert.ok(r1.tools.includes(name), `${name} declared`);
      assert.ok(isActive(h, name), `${name} still active`);
      assertKept(installs, name, "nonparticipant");
    }
  } finally {
    await close(h);
  }
});

test("fresh startup control (B): the family is deferred, inactive and undeclared; tool_search is declared; the diet installs and never names a family member", async (t) => {
  const installs = recordPerkInstalls(t);
  const cwd = scaffoldRepo();
  const rt = await recordingRuntime();
  const h = await perkB(cwd, rt, SessionManager.open(plantImplement(cwd)));
  try {
    const family = discoveryFamily();
    for (const name of family) {
      assert.equal(h.toolInfo(name)?.exposure, "deferred", `${name} registered deferred`);
      assert.ok(!isActive(h, name), `${name} inactive`);
    }
    const r1 = await census(h, rt);
    assert.ok(r1.tools.includes("tool_search"), "tool_search declared");
    for (const name of family) assert.ok(!r1.tools.includes(name), `${name} undeclared`);
    assert.ok(installs.length > 0, "the diet installed (non-vacuous)");
    assertNeverLive(installs, family, "fresh startup");
  } finally {
    await close(h);
  }
});
