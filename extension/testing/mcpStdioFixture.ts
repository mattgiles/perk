// A minimal stdio MCP server for the worker e2e tier, run as `node <this file>` (Node strips the
// types). Newline-delimited JSON-RPC; one tool, `echo { text, delayMs? }`.
//
// Oracles it leaves behind (every path is the test's to read):
// - startup writes the fixture's own pid to `$PERK_MCP_FIXTURE_MARKER` when set — "was this
//   server ever spawned", and the pid a teardown assertion probes for liveness;
// - every `tools/call` appends one JSON line `{ at, id, pid, args, token }` to
//   `<cwd>/mcp-fixture-calls.log` (Pi runs stdio servers in the session cwd) on receipt, before
//   it answers — so the line is also the "call in flight" barrier. `id` is the JSON-RPC request
//   id the client allocated; `token` is `$PERK_MCP_FIXTURE_TOKEN`, so a call proves which config
//   `env` the client launched it with;
// - `echo` answers after `delayMs` when given (a held call), at once otherwise;
// - every `notifications/cancelled` appends one JSON line `{ at, requestId }` to
//   `<cwd>/mcp-fixture-cancelled.log` — `requestId` matches the cancelled call's `id`;
// - before each call's response it writes a `notifications/message` on the same stdout. The client
//   handles a notification (Pi's synchronous server-log append) before it resolves the response,
//   so once the call returns its log line already exists;
// - with `$PERK_MCP_FIXTURE_EXIT_LOG` and `$PERK_MCP_FIXTURE_WATCH_DIR` both set, it writes
//   `{ at, entries }` to the exit log immediately before exiting — `entries` is the watched
//   directory's listing at the moment the server exits (a shutdown-ordering oracle).
//
// `$PERK_MCP_FIXTURE_INIT_DELAY_MS` (default 0) holds back the `initialize` answer: a
// slow-starting server.
// It exits when stdin closes (the client closed the transport), after
// `$PERK_MCP_FIXTURE_EXIT_DELAY_MS` (default 0) — a delay that keeps it alive through part of the
// client's close sequence.

import { appendFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";

interface RpcMessage {
  id?: number | string;
  method?: string;
  params?: {
    protocolVersion?: string;
    arguments?: { text?: unknown; delayMs?: unknown };
    requestId?: unknown;
  };
}

const send = (message: Record<string, unknown>): void => {
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", ...message })}\n`);
};

const marker = process.env.PERK_MCP_FIXTURE_MARKER;
if (marker) writeFileSync(marker, `${process.pid}\n`, "utf8");
const initDelayMs = Number(process.env.PERK_MCP_FIXTURE_INIT_DELAY_MS ?? "0") || 0;

const ECHO_TOOL = {
  name: "echo",
  description: "Echo the text back.",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" }, delayMs: { type: "number" } },
    required: ["text"],
  },
};

const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
  let message: RpcMessage;
  try {
    message = JSON.parse(line) as RpcMessage;
  } catch {
    return;
  }
  // A notification carries no id, so this one is handled before the id short-circuit below.
  if (message.method === "notifications/cancelled") {
    appendFileSync(
      join(process.cwd(), "mcp-fixture-cancelled.log"),
      `${JSON.stringify({ at: new Date().toISOString(), requestId: message.params?.requestId })}\n`,
    );
    return;
  }
  // Other notifications (`notifications/initialized`) need no answer.
  if (message.id === undefined) return;
  switch (message.method) {
    case "initialize": {
      const id = message.id;
      const protocolVersion = message.params?.protocolVersion;
      const answer = (): void => {
        send({
          id,
          result: {
            protocolVersion,
            capabilities: { tools: {}, logging: {} },
            serverInfo: { name: "perk-mcp-fixture", version: "1.0.0" },
          },
        });
      };
      if (initDelayMs > 0) setTimeout(answer, initDelayMs);
      else answer();
      return;
    }
    case "tools/list":
      send({ id: message.id, result: { tools: [ECHO_TOOL] } });
      return;
    case "tools/call": {
      const args = message.params?.arguments ?? null;
      appendFileSync(
        join(process.cwd(), "mcp-fixture-calls.log"),
        `${JSON.stringify({
          at: new Date().toISOString(),
          id: message.id,
          pid: process.ppid,
          args,
          token: process.env.PERK_MCP_FIXTURE_TOKEN,
        })}\n`,
      );
      const id = message.id;
      const answer = (): void => {
        send({ method: "notifications/message", params: { level: "info", data: "echo" } });
        send({ id, result: { content: [{ type: "text", text: String(args?.text ?? "") }] } });
      };
      const delayMs = typeof args?.delayMs === "number" ? args.delayMs : 0;
      if (delayMs > 0) setTimeout(answer, delayMs);
      else answer();
      return;
    }
    case "ping":
      send({ id: message.id, result: {} });
      return;
    default:
      send({ id: message.id, error: { code: -32601, message: "method not found" } });
  }
});

const exitDelayMs = Number(process.env.PERK_MCP_FIXTURE_EXIT_DELAY_MS ?? "0") || 0;
const exitLog = process.env.PERK_MCP_FIXTURE_EXIT_LOG;
const watchDir = process.env.PERK_MCP_FIXTURE_WATCH_DIR;

lines.on("close", () => {
  setTimeout(() => {
    if (exitLog && watchDir) {
      writeFileSync(
        exitLog,
        `${JSON.stringify({ at: new Date().toISOString(), entries: readdirSync(watchDir) })}\n`,
        "utf8",
      );
    }
    process.exit(0);
  }, exitDelayMs);
});
