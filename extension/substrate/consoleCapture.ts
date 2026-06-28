// A small, pure swap of the global `console.error` so in-process chatter can be re-routed through a
// TUI-safe sink while a background task runs. plannotator's browser code-review setup writes
// progress straight to `process.stderr` via plain `console.error(...)` (fetching the PR, creating
// the local checkout, …); those raw writes bypass pi's managed rendering and paint over the input
// box. While the request is in flight we install a replacement that forwards each captured line to
// an injected sink (perk routes it through `report()`), then restore the original.
//
// Restore is debounce-driven: setup emits a burst of lines then goes quiet once the browser is up,
// so we restore after `quietMs` with no new line (self-adjusts to the variable several-second
// setup, no fixed-duration guess). A `finally` backstop in the caller restores too; `restore()` is
// idempotent and only reassigns `console.error` when our replacement is still installed, so an
// accidental overlap with a newer patcher is safe rather than clobbering.

export type ConsoleErrorSink = (line: string) => void;

export interface ConsoleErrorInterceptor {
  restore(): void;
}

interface InterceptOptions {
  quietMs: number;
  /** Injectable purely so the unit test drives a deterministic fake clock. */
  schedule?: (fn: () => void, ms: number) => unknown;
  clearScheduled?: (handle: unknown) => void;
}

/**
 * Swap `console.error` so captured lines reach `sink` (joined with a space for multi-arg calls,
 * mirroring plannotator's occasional 2-arg `console.error`). Returns an interceptor whose
 * `restore()` reinstates the original. The original is also restored automatically once no captured
 * line has arrived for `quietMs`.
 */
export function interceptConsoleError(
  sink: ConsoleErrorSink,
  opts: InterceptOptions,
): ConsoleErrorInterceptor {
  const schedule = opts.schedule ?? ((fn, ms) => globalThis.setTimeout(fn, ms));
  const clearScheduled =
    opts.clearScheduled ??
    ((handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>));

  const original = console.error;
  let restored = false;
  let handle: unknown;

  const restore = (): void => {
    if (handle !== undefined) {
      clearScheduled(handle);
      handle = undefined;
    }
    if (restored) return;
    restored = true;
    // Only reclaim the slot if it is still OUR replacement — never clobber a newer patcher.
    if (console.error === replacement) console.error = original;
  };

  const resetQuietTimer = (): void => {
    if (handle !== undefined) clearScheduled(handle);
    handle = schedule(restore, opts.quietMs);
    // Never keep the event loop alive on our account.
    (handle as { unref?: () => void })?.unref?.();
  };

  const replacement = (...args: unknown[]): void => {
    sink(args.map(String).join(" "));
    resetQuietTimer();
  };

  console.error = replacement;
  // Start the timer immediately so a zero-line case (no setup output) still restores after quietMs.
  resetQuietTimer();

  return { restore };
}
