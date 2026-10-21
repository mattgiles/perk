// A minimal stdio MCP server for the worker e2e tier, run as `node <this file>` (Node strips the
// types). Newline-delimited JSON-RPC; one tool, `echo { text }`.
//
// Oracles it leaves behind (every path is the test's to read):
// - startup touches `$PERK_MCP_FIXTURE_MARKER` when set — "was this server ever spawned";
// - every `tools/call` appends one JSON line `{ at, pid, args, token }` to
//   `<cwd>/mcp-fixture-calls.log` (Pi runs stdio servers in the session cwd); `token` is
//   `$PERK_MCP_FIXTURE_TOKEN`, so a call proves which config `env` the client launched it with;
// - before each call's response it writes a `notifications/message` on the same stdout. The client
//   handles a notification (Pi's synchronous server-log append) before it resolves the response,
//   so once the call returns its log line already exists.
//
// It exits when stdin closes (the client closed the transport).

import { appendFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";

interface RpcMessage {
  id?: number | string;
  method?: string;
  params?: { protocolVersion?: string; arguments?: { text?: unknown } };
}

const send = (message: Record<string, unknown>): void => {
  process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", ...message })}\n`);
};

const marker = process.env.PERK_MCP_FIXTURE_MARKER;
if (marker) writeFileSync(marker, `${process.pid}\n`, "utf8");

const ECHO_TOOL = {
  name: "echo",
  description: "Echo the text back.",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
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
  // Notifications (`notifications/initialized`) carry no id and need no answer.
  if (message.id === undefined) return;
  switch (message.method) {
    case "initialize":
      send({
        id: message.id,
        result: {
          protocolVersion: message.params?.protocolVersion,
          capabilities: { tools: {}, logging: {} },
          serverInfo: { name: "perk-mcp-fixture", version: "1.0.0" },
        },
      });
      return;
    case "tools/list":
      send({ id: message.id, result: { tools: [ECHO_TOOL] } });
      return;
    case "tools/call": {
      const args = message.params?.arguments ?? null;
      appendFileSync(
        join(process.cwd(), "mcp-fixture-calls.log"),
        `${JSON.stringify({
          at: new Date().toISOString(),
          pid: process.ppid,
          args,
          token: process.env.PERK_MCP_FIXTURE_TOKEN,
        })}\n`,
      );
      send({ method: "notifications/message", params: { level: "info", data: "echo" } });
      send({
        id: message.id,
        result: { content: [{ type: "text", text: String(args?.text ?? "") }] },
      });
      return;
    }
    case "ping":
      send({ id: message.id, result: {} });
      return;
    default:
      send({ id: message.id, error: { code: -32601, message: "method not found" } });
  }
});
lines.on("close", () => process.exit(0));
