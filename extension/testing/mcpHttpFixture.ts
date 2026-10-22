// A minimal in-process streamable-HTTP MCP server for the worker e2e tier. The worker drives in the
// test process, so a `${VAR}` header in a project entry resolves from the test's env and a test
// can act on the server (`expireSession`) between scripted replies. Loopback only.
//
// It implements exactly what pi-mcp's `StreamableHttpTransport` + `McpClient` need: every JSON-RPC
// message is a `POST`; a request is answered `200` + `application/json` (no SSE), a notification
// `202` with no body; the standalone `GET` stream is refused with `405` (the client then opens
// none); `DELETE` (the transport's close) is answered `204`. One tool, `echo { text }`.
//
// Oracles: `requests` records every request in arrival order with the status it was answered —
// method, path, lowercased headers and the parsed JSON body. Only `/mcp` is served; anything else
// (an OAuth discovery request, say) is recorded and answered `404`.

import { createServer, type IncomingHttpHeaders, type IncomingMessage } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * How the fixture authenticates `/mcp` requests (absent ⇒ every request is served):
 * - `bearer` — a request whose `authorization` is not exactly `Bearer <token>` gets a `401` with
 *   no `WWW-Authenticate` challenge;
 * - `challenge` — every request gets `status` with that `WWW-Authenticate` header (a function
 *   receives the fixture's own origin, for a challenge that points back at it);
 * - `status` — every request gets `status` with an empty body.
 */
export type McpHttpAuth =
  | { kind: "bearer"; token: string }
  | {
      kind: "challenge";
      status: 401 | 403;
      wwwAuthenticate: string | ((origin: string) => string);
    }
  | { kind: "status"; status: number };

/** One request the fixture received, with the status it answered. */
export interface McpHttpRequest {
  method: string;
  path: string;
  /** Lowercased names (Node's), repeated values joined with `, `. */
  headers: Record<string, string>;
  /** The body, parsed when it is JSON; absent when empty. */
  body?: unknown;
  /** `0` until answered. */
  status: number;
}

export interface McpHttpFixture {
  /** `http://127.0.0.1:<port>/mcp`. */
  url: string;
  /** `http://127.0.0.1:<port>`. */
  origin: string;
  requests: McpHttpRequest[];
  /**
   * Forget the current session (a server restart): a later request carrying its
   * `mcp-session-id` is answered `404` — what pi-mcp turns into `McpSessionExpiredError` while
   * it holds a session — and the next `initialize` opens the next session.
   */
  expireSession(): void;
  close(): Promise<void>;
}

interface RpcMessage {
  id?: number | string;
  method?: string;
  params?: { protocolVersion?: unknown; arguments?: { text?: unknown } };
}

const ECHO_TOOL = {
  name: "echo",
  description: "Echo the text back.",
  inputSchema: {
    type: "object",
    properties: { text: { type: "string" } },
    required: ["text"],
  },
};

function flattenHeaders(headers: IncomingHttpHeaders): Record<string, string> {
  const flat: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    if (value !== undefined) flat[name] = Array.isArray(value) ? value.join(", ") : value;
  }
  return flat;
}

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

function parseBody(text: string): unknown {
  if (text === "") return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/** The JSON-RPC result (or error) the fixture answers `message` with. */
function rpcReply(message: RpcMessage): Record<string, unknown> {
  switch (message.method) {
    case "initialize":
      return {
        result: {
          protocolVersion: message.params?.protocolVersion,
          capabilities: { tools: {} },
          serverInfo: { name: "perk-mcp-http-fixture", version: "1.0.0" },
        },
      };
    case "tools/list":
      return { result: { tools: [ECHO_TOOL] } };
    case "tools/call":
      return {
        result: {
          content: [{ type: "text", text: String(message.params?.arguments?.text ?? "") }],
        },
      };
    case "ping":
      return { result: {} };
    default:
      return { error: { code: -32601, message: "method not found" } };
  }
}

/**
 * Start the fixture on `127.0.0.1:0`. With `sessionId`, every `initialize` opens session
 * `<sessionId>-<n>` (`n` from 1, sent as `Mcp-Session-Id`); a request carrying any other session
 * id is answered `404`. Without it the fixture is stateless.
 */
export async function startMcpHttpFixture(
  opts: { auth?: McpHttpAuth; sessionId?: string } = {},
): Promise<McpHttpFixture> {
  const requests: McpHttpRequest[] = [];
  let sessions = 0;
  let current: string | undefined;
  let origin = "";

  const server = createServer((req, res) => {
    const record: McpHttpRequest = {
      method: req.method ?? "",
      path: new URL(req.url ?? "/", "http://127.0.0.1").pathname,
      headers: flattenHeaders(req.headers),
      status: 0,
    };
    requests.push(record);
    const reply = (status: number, headers: Record<string, string> = {}, body?: string): void => {
      record.status = status;
      res.writeHead(status, headers);
      res.end(body);
    };
    void readBody(req).then(
      (text) => {
        const body = parseBody(text);
        if (body !== undefined) record.body = body;
        if (record.path !== "/mcp") return reply(404);
        const auth = opts.auth;
        if (auth?.kind === "status") return reply(auth.status);
        if (auth?.kind === "challenge") {
          const challenge =
            typeof auth.wwwAuthenticate === "function"
              ? auth.wwwAuthenticate(origin)
              : auth.wwwAuthenticate;
          return reply(auth.status, { "www-authenticate": challenge });
        }
        if (auth?.kind === "bearer" && record.headers.authorization !== `Bearer ${auth.token}`) {
          return reply(401);
        }
        const session = record.headers["mcp-session-id"];
        if (session !== undefined && session !== current) return reply(404);
        if (record.method === "DELETE") return reply(204);
        if (record.method !== "POST") return reply(405);
        const message = (typeof body === "object" && body !== null ? body : {}) as RpcMessage;
        // A notification (no id) is acknowledged without a body.
        if (message.id === undefined) return reply(202);
        const headers: Record<string, string> = { "content-type": "application/json" };
        if (message.method === "initialize" && opts.sessionId !== undefined) {
          sessions += 1;
          current = `${opts.sessionId}-${sessions}`;
          headers["mcp-session-id"] = current;
        }
        return reply(
          200,
          headers,
          JSON.stringify({ jsonrpc: "2.0", id: message.id, ...rpcReply(message) }),
        );
      },
      () => reply(400),
    );
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
  const { port } = server.address() as AddressInfo;
  origin = `http://127.0.0.1:${port}`;
  return {
    url: `${origin}/mcp`,
    origin,
    requests,
    expireSession: () => {
      current = undefined;
    },
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
        // The client's keep-alive sockets would otherwise hold `close` open.
        server.closeAllConnections();
      }),
  };
}
