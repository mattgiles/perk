// Test-owned IPC barriers exercise the production lock across actual Node processes.
import { acquireWorktreeResolverLock } from "../substrate/worktreeResolverLock.ts";

const cwd = process.argv[2];
if (!cwd) throw new Error("missing test worktree");
const acquisition = acquireWorktreeResolverLock(cwd, {
  sessionId: "child",
  runId: "run",
  requestId: "request",
});
process.on("message", (message) => {
  if (message === "release" && acquisition.kind === "acquired") {
    process.send?.(acquisition.claim.finish("release"));
  } else if (message === "try") {
    const result = acquireWorktreeResolverLock(cwd, {
      sessionId: "contender",
      runId: "later",
      requestId: "later",
    });
    process.send?.({ kind: result.kind });
    if (result.kind === "acquired") result.claim.finish("retain");
  } else if (message === "exit") process.exit(0);
});
process.send?.({ kind: acquisition.kind });
