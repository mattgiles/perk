import assert from "node:assert/strict";
import test from "node:test";
import { GIT_DIFF_FAILED_COPY, GIT_DIFF_UNAVAILABLE_COPY, type GitDiffOutcome } from "./src/git.ts";
import { createGitDiffCache, GIT_DIFF_IDLE_ROW } from "./src/gitDiffCache.ts";

type Deferred = {
  promise: Promise<GitDiffOutcome>;
  resolve: (outcome: GitDiffOutcome) => void;
};

function deferred(): Deferred {
  let resolve!: (outcome: GitDiffOutcome) => void;
  const promise = new Promise<GitDiffOutcome>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function loaded(diff: string, truncated = false): GitDiffOutcome {
  return { status: "loaded", result: { status: "available", diff, truncated } };
}

async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

test("open fetches once per path and retains results across close/reopen", async () => {
  const fetched: string[] = [];
  const cache = createGitDiffCache({
    fetchDiff: (path) => {
      fetched.push(path);
      return Promise.resolve(loaded(`+${path}\n`));
    },
  });
  let notifications = 0;
  cache.subscribe(() => {
    notifications += 1;
  });

  cache.open("a.md");
  assert.deepEqual(cache.state().get("a.md"), { status: "loading" });
  await settle();
  assert.deepEqual(cache.state().get("a.md"), {
    status: "loaded",
    diff: "+a.md\n",
    truncated: false,
  });
  // Re-opening a loaded row (a closed-then-reopened details element) never refetches.
  cache.open("a.md");
  await settle();
  assert.deepEqual(fetched, ["a.md"]);
  assert.equal(notifications, 2);
  assert.equal(cache.state().get("missing.md"), undefined);
  assert.deepEqual(GIT_DIFF_IDLE_ROW, { status: "idle" });
});

test("open while loading never issues a second fetch", async () => {
  const first = deferred();
  const fetched: string[] = [];
  const cache = createGitDiffCache({
    fetchDiff: (path) => {
      fetched.push(path);
      return first.promise;
    },
  });
  cache.open("a.md");
  cache.open("a.md");
  assert.deepEqual(fetched, ["a.md"]);
  first.resolve(loaded("+a\n"));
  await settle();
  assert.deepEqual(cache.state().get("a.md"), { status: "loaded", diff: "+a\n", truncated: false });
});

test("failed and unavailable outcomes fold to failed rows with their fixed copy", async () => {
  const outcomes = new Map<string, GitDiffOutcome>([
    ["transport.md", { status: "failed" }],
    ["large.md", { status: "loaded", result: { status: "unavailable", reason: "too-large" } }],
  ]);
  const cache = createGitDiffCache({
    fetchDiff: (path) => {
      const outcome = outcomes.get(path);
      assert.ok(outcome !== undefined);
      return Promise.resolve(outcome);
    },
  });
  cache.open("transport.md");
  cache.open("large.md");
  await settle();
  assert.deepEqual(cache.state().get("transport.md"), {
    status: "failed",
    copy: GIT_DIFF_FAILED_COPY,
  });
  assert.deepEqual(cache.state().get("large.md"), {
    status: "failed",
    copy: GIT_DIFF_UNAVAILABLE_COPY["too-large"],
  });
  // A failed row is retained (no automatic retry loop) until the next invalidation.
  cache.open("transport.md");
  await settle();
  assert.deepEqual(cache.state().get("transport.md"), {
    status: "failed",
    copy: GIT_DIFF_FAILED_COPY,
  });
});

test("invalidate clears every row and drops an out-of-order stale response", async () => {
  const held = deferred();
  let calls = 0;
  const cache = createGitDiffCache({
    fetchDiff: () => {
      calls += 1;
      return calls === 1 ? held.promise : Promise.resolve(loaded("+fresh\n"));
    },
  });
  cache.open("a.md");
  cache.invalidate();
  assert.equal(cache.state().size, 0);

  // The generation-N response lands AFTER the invalidation: it must be dropped,
  // never repopulating the cleared row.
  held.resolve(loaded("+stale\n"));
  await settle();
  assert.equal(cache.state().get("a.md"), undefined);

  // The reopened row belongs to the new generation and fetches fresh.
  cache.open("a.md");
  await settle();
  assert.deepEqual(cache.state().get("a.md"), {
    status: "loaded",
    diff: "+fresh\n",
    truncated: false,
  });
  assert.equal(calls, 2);
});

test("subscribe notifies on every commit and unsubscribe stops notifications", async () => {
  const cache = createGitDiffCache({ fetchDiff: () => Promise.resolve(loaded("+x\n")) });
  const seen: number[] = [];
  const unsubscribe = cache.subscribe(() => {
    seen.push(cache.state().size);
  });
  cache.open("a.md");
  await settle();
  assert.deepEqual(seen, [1, 1]);
  unsubscribe();
  cache.invalidate();
  assert.deepEqual(seen, [1, 1]);
});

test("state returns a stable reference between commits and a new one after", async () => {
  const cache = createGitDiffCache({ fetchDiff: () => Promise.resolve(loaded("+x\n")) });
  const before = cache.state();
  assert.equal(cache.state(), before);
  cache.open("a.md");
  const during = cache.state();
  assert.notEqual(during, before);
  await settle();
  assert.notEqual(cache.state(), during);
});

test("dispose drops in-flight responses for good", async () => {
  const held = deferred();
  const cache = createGitDiffCache({ fetchDiff: () => held.promise });
  cache.open("a.md");
  cache.dispose();
  held.resolve(loaded("+late\n"));
  await settle();
  // The loading row is left behind but never transitions: the response was stale.
  assert.deepEqual(cache.state().get("a.md"), { status: "loading" });
});

test("an unexpected fetch rejection degrades to the failed transport copy", async () => {
  const cache = createGitDiffCache({ fetchDiff: () => Promise.reject(new Error("boom")) });
  cache.open("a.md");
  await settle();
  assert.deepEqual(cache.state().get("a.md"), {
    status: "failed",
    copy: GIT_DIFF_FAILED_COPY,
  });
});
