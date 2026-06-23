// A small, reusable structured-output substrate over `@earendil-works/pi-ai`.
//
// pi-ai has no dedicated JSON-mode; structured output is done via tool calling. This module wraps
// that idiom into two pure, dependency-light, NEVER-throwing helpers:
//   - `resolveModelAuth(ctx)` reuses the session's configured + authenticated model (the sanctioned
//     `ModelRegistry.getApiKeyAndHeaders` path), and
//   - `completeStructured(opts)` builds a single-tool `Context`, calls `complete`, and validates the
//     returned tool-call arguments against a TypeBox schema.
// Both report failure via a soft `{ ok:false, error }` outcome — no throws ever reach the caller, so
// every consumer can stay fail-safe with a deterministic fallback. The first consumer is
// `extension/factories/planTitle.ts` (LLM-generated plan-issue titles).

import {
  type Api,
  type Context,
  complete,
  type Model,
  type Static,
  type Tool,
  type ToolCall,
  type TSchema,
  validateToolCall,
} from "@earendil-works/pi-ai";

/** Structurally-minimal slice of `ExtensionContext` needed to reuse the session's model + auth. */
export interface ModelAuthContext {
  model: Model<Api> | undefined;
  modelRegistry: {
    getApiKeyAndHeaders(
      model: Model<Api>,
    ): Promise<
      { ok: true; apiKey?: string; headers?: Record<string, string> } | { ok: false; error: string }
    >;
  };
}

/** Resolved model + auth, or a soft failure (no model / unresolved auth). */
export type ResolvedModelAuth =
  | { ok: true; model: Model<Api>; apiKey?: string; headers?: Record<string, string> }
  | { ok: false; error: string };

/** The generic structured-output outcome — soft success/failure, never a throw. */
export interface StructuredOutcome<T> {
  ok: boolean;
  value?: T;
  error?: string;
}

/**
 * Resolve the session's model and its API key + headers via the sanctioned `ModelRegistry`. Returns
 * `{ ok:false }` when no model is configured or auth cannot be resolved (offline, no key). Pure
 * apart from the single `getApiKeyAndHeaders` await, which is wrapped so a throw becomes a soft
 * failure.
 */
export async function resolveModelAuth(ctx: ModelAuthContext): Promise<ResolvedModelAuth> {
  const model = ctx.model;
  if (!model) return { ok: false, error: "no model configured for this session" };
  try {
    const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
    if (!auth.ok) return { ok: false, error: auth.error };
    return { ok: true, model, apiKey: auth.apiKey, headers: auth.headers };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

export interface CompleteStructuredOptions<S extends TSchema> {
  model: Model<Api>;
  /** TypeBox schema describing the structured result (becomes the single tool's parameters). */
  schema: S;
  /** The forced tool's name (the model is instructed to call it). */
  toolName: string;
  toolDescription: string;
  /** Optional system prompt. */
  system?: string;
  /** Instruction prepended to the input in the single user message. */
  instruction: string;
  /** The payload (e.g. the document to summarize/classify). */
  input: string;
  apiKey?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/**
 * Ask the model for a structured object via a single tool call, validated against `schema`. Never
 * throws: any model error, missing tool call, or schema-invalid arguments yields `{ ok:false }`.
 *
 * Deliberately sets no provider-specific `toolChoice` — the generic `complete` surface has no
 * portable forced-tool value (providers disagree: `"required"` vs `"any"`), so tool use is requested
 * via the prompt and the call site keeps a deterministic fallback. No `maxTokens` cap is set, so
 * reasoning models are not truncated before emitting the tool call.
 */
export async function completeStructured<S extends TSchema>(
  opts: CompleteStructuredOptions<S>,
): Promise<StructuredOutcome<Static<S>>> {
  const tool: Tool = {
    name: opts.toolName,
    description: opts.toolDescription,
    parameters: opts.schema,
  };
  const context: Context = {
    systemPrompt: opts.system,
    messages: [
      {
        role: "user",
        content: `${opts.instruction}\n\n${opts.input}`,
        timestamp: Date.now(),
      },
    ],
    tools: [tool],
  };

  let msg: Awaited<ReturnType<typeof complete>>;
  try {
    msg = await complete(opts.model, context, {
      apiKey: opts.apiKey,
      headers: opts.headers,
      signal: opts.signal,
      timeoutMs: opts.timeoutMs,
    });
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }

  if (msg.stopReason === "error" || msg.stopReason === "aborted") {
    return { ok: false, error: msg.errorMessage ?? `model stopped: ${msg.stopReason}` };
  }

  const toolCalls = msg.content.filter((b): b is ToolCall => b.type === "toolCall");
  const call = toolCalls.find((c) => c.name === opts.toolName) ?? toolCalls[0];
  if (!call) return { ok: false, error: "model returned no tool call" };

  try {
    const value = validateToolCall([tool], call) as Static<S>;
    return { ok: true, value };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
