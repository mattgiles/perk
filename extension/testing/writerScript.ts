// Only the fixed code span is evaluated; the surrounding dispatch prose remains model-authored.
import assert from "node:assert/strict";

export function writerScript(guidance: string): string {
  const start = guidance.indexOf('const r = await runs.run("resolve",');
  const end = guidance.indexOf("output: r.output};", start);
  assert.ok(start >= 0 && end > start, "fixed resolver script must be present");
  return guidance.slice(start, end + "output: r.output};".length);
}

export async function evaluateWriterScript(
  guidance: string,
  scriptedChild?: () => Promise<unknown>,
) {
  const calls: { key: string; params: Record<string, unknown> }[] = [];
  const child = {
    key: "resolve",
    ok: false,
    error: "stopped",
    output: "resolution",
    results: ["private"],
  };
  const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor;
  const result: unknown = await new AsyncFunction("runs", writerScript(guidance))({
    run: async (key: string, params: Record<string, unknown>) => {
      calls.push({ key, params });
      return scriptedChild ? scriptedChild() : child;
    },
  });
  return { calls, result };
}
