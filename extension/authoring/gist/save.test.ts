// Direct feature tests for saveGist + gistApprovalSave — memory session, fake backend, fake
// gate; no Pi, no cold door.

import assert from "node:assert/strict";
import { test } from "node:test";
import type { MemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { openMemoryWorkflowSession } from "../../session/memoryWorkflowSession.ts";
import { reviseGistDraft } from "./draft.ts";
import { type GistBackend, type GistGate, gistApprovalSave, saveGist } from "./save.ts";

const PROSE = "# Faster reviews\n\nWe would likely want review turnaround under a day.\n";

/** A deterministic backend fake recording requests and returning a canned result. */
function fakeBackend(result?: Awaited<ReturnType<GistBackend["save"]>>): GistBackend & {
  requests: { prose: string; title?: string; scope?: string; runId: string | null }[];
} {
  const backend = {
    requests: [] as { prose: string; title?: string; scope?: string; runId: string | null }[],
    async save(req: { prose: string; title?: string; scope?: string; runId: string | null }) {
      backend.requests.push(req);
      return (
        result ?? {
          status: "saved" as const,
          id: "7",
          url: "https://gh/o/r/issues/7",
          existed: false,
          scope: "plan",
        }
      );
    },
  };
  return backend;
}

/** A gate fake recording exits; `active` is the isActive snapshot. */
function fakeGate(active: boolean): GistGate & { exits: number } {
  const gate = {
    exits: 0,
    isActive: () => active,
    exit() {
      gate.exits += 1;
    },
  };
  return gate;
}

function memorySession(runId = "RID"): MemoryWorkflowSession {
  return openMemoryWorkflowSession({ runId });
}

// --- saveGist --------------------------------------------------------------------------------------

test("saveGist: blank prose / bad scope refuse as invalid_input before the backend", async () => {
  const backend = fakeBackend();
  const blank = await saveGist({ prose: "  \n" }, { backend, runId: "RID" });
  assert.deepEqual(blank, {
    status: "failed",
    message: "no gist prose to save (draft the gist first)",
    errorType: "invalid_input",
  });
  const scope = await saveGist(
    { prose: PROSE, scope: "banana" as never },
    { backend, runId: "RID" },
  );
  assert.deepEqual(scope, {
    status: "failed",
    message: "scope must be plan or objective",
    errorType: "invalid_input",
  });
  assert.equal(backend.requests.length, 0, "the backend was never invoked");
});

test("saveGist: trims the prose and threads title/scope/runId to the backend", async () => {
  const backend = fakeBackend();
  const result = await saveGist(
    { prose: `${PROSE}\n\n`, title: "Faster reviews", scope: "plan" },
    { backend, runId: "01RID" },
  );
  assert.equal(result.status, "saved");
  assert.deepEqual(backend.requests, [
    { prose: PROSE.trim(), title: "Faster reviews", scope: "plan", runId: "01RID" },
  ]);
});

test("saveGist: an identity-less save is representable (runId null reaches the port)", async () => {
  const backend = fakeBackend();
  const result = await saveGist({ prose: PROSE }, { backend, runId: null });
  assert.equal(result.status, "saved");
  assert.deepEqual(backend.requests, [{ prose: PROSE.trim(), runId: null }]);
});

test("saveGist: a backend failure passes through typed", async () => {
  const backend = fakeBackend({
    status: "failed",
    message: "gh exploded",
    errorType: "github_error",
  });
  const result = await saveGist({ prose: PROSE }, { backend, runId: "RID" });
  assert.deepEqual(result, { status: "failed", message: "gh exploded", errorType: "github_error" });
});

// --- gistApprovalSave ------------------------------------------------------------------------------

function draftedSession(): MemoryWorkflowSession {
  const session = memorySession();
  const revised = reviseGistDraft(
    { prose: PROSE, title: "Faster reviews", scope: "objective" },
    session,
  );
  assert.equal(revised.status, "revised");
  return session;
}

test("gistApprovalSave: no draft → no-draft, no backend call, gate untouched", async () => {
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const outcome = await gistApprovalSave({ session: memorySession(), backend, gate });
  assert.deepEqual(outcome, { status: "no-draft" });
  assert.equal(backend.requests.length, 0);
  assert.equal(gate.exits, 0);
});

test("gistApprovalSave: happy path — the draft's title/scope ride the port; gate exited once", async () => {
  const backend = fakeBackend();
  const gate = fakeGate(true);
  const outcome = await gistApprovalSave({ session: draftedSession(), backend, gate });
  assert.equal(outcome.status, "saved");
  assert.ok(outcome.status === "saved");
  assert.equal(outcome.gateExited, true);
  assert.equal(outcome.save.id, "7");
  assert.equal(gate.exits, 1, "the gate was exited exactly once");
  assert.deepEqual(backend.requests, [
    { prose: PROSE.trim(), title: "Faster reviews", scope: "objective", runId: "RID" },
  ]);
});

test("gistApprovalSave: an explicit title overrides the draft title (the /gist-save pin)", async () => {
  const backend = fakeBackend();
  await gistApprovalSave(
    { session: draftedSession(), backend, gate: fakeGate(true) },
    { title: "Override title" },
  );
  assert.equal(backend.requests[0]?.title, "Override title");
});

test("gistApprovalSave: a failed save leaves the gate on", async () => {
  const backend = fakeBackend({
    status: "failed",
    message: "gh exploded",
    errorType: "github_error",
  });
  const gate = fakeGate(true);
  const outcome = await gistApprovalSave({ session: draftedSession(), backend, gate });
  assert.equal(outcome.status, "save-failed");
  assert.ok(outcome.status === "save-failed");
  assert.equal(outcome.gateExited, false);
  assert.equal(outcome.save.message, "gh exploded");
  assert.equal(gate.exits, 0, "the gate stays on");
});

test("gistApprovalSave: a save while already read-write never exits the gate", async () => {
  const gate = fakeGate(false);
  const outcome = await gistApprovalSave({
    session: draftedSession(),
    backend: fakeBackend(),
    gate,
  });
  assert.equal(outcome.status, "saved");
  assert.ok(outcome.status === "saved");
  assert.equal(outcome.gateExited, false);
  assert.equal(gate.exits, 0, "no gate.exit call");
});

test("gistApprovalSave: gate released ONLY after the verified backend success envelope", async () => {
  // The gate snapshot is taken BEFORE the save; a backend that flips the gate off mid-save must
  // not double-exit, and a failure after the snapshot must leave it untouched.
  const order: string[] = [];
  const backend: GistBackend = {
    async save() {
      order.push("backend");
      return {
        status: "saved",
        id: "7",
        url: "https://gh/o/r/issues/7",
        existed: null,
        scope: null,
      };
    },
  };
  const gate: GistGate = {
    isActive: () => {
      order.push("snapshot");
      return true;
    },
    exit: () => {
      order.push("exit");
    },
  };
  await gistApprovalSave({ session: draftedSession(), backend, gate });
  assert.deepEqual(order, ["snapshot", "backend", "exit"], "snapshot → save → exit, in order");
});
