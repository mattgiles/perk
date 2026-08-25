// A small, reusable structured-output substrate over `@earendil-works/pi-ai`.
//
// pi-ai has no dedicated JSON-mode; structured output is done via tool calling. This module wraps
// that idiom into two pure, dependency-light, NEVER-throwing helpers:
//   - `resolveModelAuth(ctx)` reuses the session's configured + authenticated model (the compat
//     `ModelRegistry.getApiKeyAndHeaders` path — the fallback for hosts without registry
//     dispatch), and
//   - `completeStructured(opts)` builds a single-tool `Context`, completes it (via the injected
//     registry `dispatch` when the host provides one, else the compat `complete`), and validates
//     the returned tool-call arguments against a TypeBox schema.
// Both report failure via a soft `{ ok:false, error }` outcome — no throws ever reach the caller, so
// every consumer can stay fail-safe with a deterministic fallback. The first consumer is
// `extension/pi/v1/planTitle.ts` (LLM-generated plan-issue titles).

import {
  type Api,
  type AssistantMessage,
  type Context,
  type Model,
  type Static,
  type Tool,
  type ToolCall,
  type TSchema,
  validateToolCall,
} from "@earendil-works/pi-ai";
// `complete` (the old global API) lives on the /compat entrypoint from pi-ai 0.80; the root
// keeps the types. Pi's extension loader aliases both the root and /compat to the compat entry.
import { complete } from "@earendil-works/pi-ai/compat";

/**
 * Registry dispatch (mirrors pi ≥ 0.84's `ModelRegistry.complete`): pi owns final request
 * assembly — resolved auth, nullable headers, credential-resolved `baseUrl`, provider `env` —
 * end to end. Feature-detect it (`typeof … === "function"`); absent on older hosts.
 */
export type ModelDispatch = (
  model: Model<Api>,
  context: Context,
  options: { signal?: AbortSignal; timeoutMs?: number },
) => Promise<AssistantMessage>;

/**
 * Structurally-minimal slice of `ExtensionContext` needed to reuse the session's model + auth.
 * Header values mirror pi-ai's `ProviderHeaders` (`string | null` — null is a header-deletion
 * marker); `baseUrl`/`env` mirror pi 0.84's `ResolvedRequestAuth`.
 */
export interface ModelAuthContext {
  model: Model<Api> | undefined;
  modelRegistry: {
    getApiKeyAndHeaders(model: Model<Api>): Promise<
      | {
          ok: true;
          apiKey?: string;
          headers?: Record<string, string | null>;
          baseUrl?: string;
          env?: Record<string, string>;
        }
      | { ok: false; error: string }
    >;
    /** pi ≥ 0.84 registry dispatch; absent on older hosts (feature-detected, never assumed). */
    complete?(
      model: Model<Api>,
      context: Context,
      options?: { signal?: AbortSignal; timeoutMs?: number },
    ): Promise<AssistantMessage>;
  };
}

/** Resolved model + auth, or a soft failure (no model / unresolved auth). */
export type ResolvedModelAuth =
  | {
      ok: true;
      model: Model<Api>;
      apiKey?: string;
      headers?: Record<string, string | null>;
      baseUrl?: string;
      env?: Record<string, string>;
    }
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
    return {
      ok: true,
      model,
      apiKey: auth.apiKey,
      headers: auth.headers,
      baseUrl: auth.baseUrl,
      env: auth.env,
    };
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
  /**
   * Registry dispatch (pi ≥ 0.84). When present it REPLACES the compat `complete` +
   * apiKey/headers assembly below — pi owns auth end to end, including the credential-resolved
   * `baseUrl` the fallback path cannot carry.
   */
  dispatch?: ModelDispatch;
  apiKey?: string;
  /** `string | null` mirrors pi-ai's `ProviderHeaders` — a null value deletes a default header. */
  headers?: Record<string, string | null>;
  /** Provider-scoped environment values (pi 0.84 `ResolvedRequestAuth.env`), fallback path only. */
  env?: Record<string, string>;
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

  // Primary: registry dispatch (pi ≥ 0.84 owns auth/headers/baseUrl/env). Fallback: the compat
  // `complete` with caller-resolved auth — it forwards apiKey/headers/env but has NO `baseUrl`
  // option, so a credential-resolved endpoint is silently dropped on old hosts (the fallback's
  // named, pre-existing limitation; the dispatch path is the fix).
  let msg: AssistantMessage;
  try {
    msg = opts.dispatch
      ? await opts.dispatch(opts.model, context, { signal: opts.signal, timeoutMs: opts.timeoutMs })
      : await complete(opts.model, context, {
          apiKey: opts.apiKey,
          headers: opts.headers,
          env: opts.env,
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
