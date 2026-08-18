import assert from "node:assert/strict";
import test from "node:test";
import {
  fetchGitDiff,
  fetchGitStatus,
  GIT_DIFF_EMPTY_COPY,
  GIT_DIFF_FAILED_COPY,
  GIT_DIFF_LOADING_COPY,
  GIT_DIFF_TRUNCATED_COPY,
  GIT_DIFF_UNAVAILABLE_COPY,
  GIT_DIFF_UNAVAILABLE_REASONS,
  GIT_FILE_STATES,
  GIT_STATE_LABELS,
  GIT_STATUS_CLEAN_COPY,
  GIT_STATUS_FAILED_COPY,
  GIT_STATUS_LOADING_COPY,
  GIT_STATUS_UNAVAILABLE_COPY,
  GIT_STATUS_UNAVAILABLE_REASONS,
  gitOtherChangesNote,
  parseGitDiff,
  parseGitStatus,
} from "./src/git.ts";
import type { FetchLike, ResponseLike } from "./src/sourceLoad.ts";

const AVAILABLE_STATUS = {
  status: "available",
  reason: null,
  entries: [
    { path: "a.md", state: "modified" },
    { path: "b.md", state: "untracked" },
  ],
  other_change_count: 2,
};

const AVAILABLE_DIFF = {
  status: "available",
  reason: null,
  diff: "+changed\n",
  truncated: false,
};

function jsonResponse(status: number, body: unknown): ResponseLike {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  };
}

test("the closed git vocabulary is pinned exactly", () => {
  // Backend/frontend wire drift (a dropped or renamed state/reason) must fail here —
  // iterating over the live arrays alone would be self-referential.
  assert.deepEqual(
    [...GIT_FILE_STATES],
    ["modified", "added", "deleted", "untracked", "conflicted"],
  );
  assert.deepEqual([...GIT_STATUS_UNAVAILABLE_REASONS], ["git-missing", "timeout", "git-error"]);
  assert.deepEqual(
    [...GIT_DIFF_UNAVAILABLE_REASONS],
    ["git-missing", "timeout", "too-large", "git-error"],
  );
});

test("the fixed copy tables are pinned exactly", () => {
  assert.deepEqual(GIT_STATE_LABELS, {
    modified: "modified",
    added: "added",
    deleted: "deleted",
    untracked: "untracked",
    conflicted: "conflicted",
  });
  assert.deepEqual(GIT_STATUS_UNAVAILABLE_COPY, {
    "git-missing": "Git is not available on this machine.",
    timeout: "Git timed out.",
    "git-error": "Git could not report working-tree status.",
  });
  assert.equal(GIT_STATUS_FAILED_COPY, "Git status could not be loaded.");
  assert.equal(GIT_STATUS_LOADING_COPY, "Loading Git status…");
  assert.equal(GIT_STATUS_CLEAN_COPY, "No changes to catalog files.");
  assert.equal(gitOtherChangesNote(3), "3 changed file(s) outside the catalog.");
  assert.equal(GIT_DIFF_LOADING_COPY, "Loading diff…");
  assert.equal(GIT_DIFF_FAILED_COPY, "Git diff could not be loaded.");
  assert.deepEqual(GIT_DIFF_UNAVAILABLE_COPY, {
    "git-missing": "Git is not available on this machine.",
    timeout: "Git timed out.",
    "too-large": "File too large to diff safely.",
    "git-error": "Git could not produce a diff for this file.",
  });
  assert.equal(GIT_DIFF_EMPTY_COPY, "No changes on disk for this file.");
  assert.equal(GIT_DIFF_TRUNCATED_COPY, "Diff truncated — showing raw text.");
});

test("parseGitStatus accepts both well-formed envelope arms", () => {
  assert.deepEqual(parseGitStatus(AVAILABLE_STATUS), {
    status: "available",
    entries: [
      { path: "a.md", state: "modified" },
      { path: "b.md", state: "untracked" },
    ],
    otherChangeCount: 2,
  });
  assert.deepEqual(
    parseGitStatus({
      status: "unavailable",
      reason: "git-missing",
      entries: [],
      other_change_count: 0,
    }),
    { status: "unavailable", reason: "git-missing" },
  );
});

test("parseGitStatus rejects unknown vocabulary, malformed shapes, and contradictions", () => {
  assert.equal(parseGitStatus(null), null);
  assert.equal(parseGitStatus([]), null);
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, status: "pending" }), null);
  // Unknown per-file state.
  assert.equal(
    parseGitStatus({
      ...AVAILABLE_STATUS,
      entries: [{ path: "a.md", state: "renamed" }],
    }),
    null,
  );
  // Malformed entries and counts.
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, entries: [{ path: 4 }] }), null);
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, entries: "none" }), null);
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, other_change_count: -1 }), null);
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, other_change_count: 1.5 }), null);
  // Contradiction: available must carry a null reason.
  assert.equal(parseGitStatus({ ...AVAILABLE_STATUS, reason: "git-error" }), null);
  // Contradiction: unavailable must carry no entries and a zero count.
  assert.equal(
    parseGitStatus({
      status: "unavailable",
      reason: "git-error",
      entries: [{ path: "a.md", state: "modified" }],
      other_change_count: 0,
    }),
    null,
  );
  assert.equal(
    parseGitStatus({
      status: "unavailable",
      reason: "git-error",
      entries: [],
      other_change_count: 1,
    }),
    null,
  );
  // `too-large` is not a status reason; unknown reasons fold to the parse failure.
  assert.equal(
    parseGitStatus({
      status: "unavailable",
      reason: "too-large",
      entries: [],
      other_change_count: 0,
    }),
    null,
  );
});

test("parseGitDiff accepts both well-formed envelope arms including the empty diff", () => {
  assert.deepEqual(parseGitDiff(AVAILABLE_DIFF), {
    status: "available",
    diff: "+changed\n",
    truncated: false,
  });
  assert.deepEqual(parseGitDiff({ status: "available", reason: null, diff: "", truncated: true }), {
    status: "available",
    diff: "",
    truncated: true,
  });
  assert.deepEqual(
    parseGitDiff({ status: "unavailable", reason: "too-large", diff: null, truncated: false }),
    { status: "unavailable", reason: "too-large" },
  );
});

test("parseGitDiff rejects unknown vocabulary, malformed shapes, and contradictions", () => {
  assert.equal(parseGitDiff(null), null);
  assert.equal(parseGitDiff({ ...AVAILABLE_DIFF, status: "done" }), null);
  assert.equal(parseGitDiff({ ...AVAILABLE_DIFF, diff: null }), null);
  assert.equal(parseGitDiff({ ...AVAILABLE_DIFF, truncated: "yes" }), null);
  // Contradiction: available must carry a null reason.
  assert.equal(parseGitDiff({ ...AVAILABLE_DIFF, reason: "timeout" }), null);
  // Contradictions: unavailable must carry no diff text and truncated false.
  assert.equal(
    parseGitDiff({ status: "unavailable", reason: "timeout", diff: "+x\n", truncated: false }),
    null,
  );
  assert.equal(
    parseGitDiff({ status: "unavailable", reason: "timeout", diff: null, truncated: true }),
    null,
  );
  // Unknown reason folds to the parse failure.
  assert.equal(
    parseGitDiff({ status: "unavailable", reason: "confused", diff: null, truncated: false }),
    null,
  );
});

test("fetchGitStatus classifies success, non-200, parse failure, and thrown transport", async () => {
  const okFetch: FetchLike = () => Promise.resolve(jsonResponse(200, AVAILABLE_STATUS));
  assert.deepEqual(await fetchGitStatus(okFetch), {
    status: "loaded",
    result: {
      status: "available",
      entries: [
        { path: "a.md", state: "modified" },
        { path: "b.md", state: "untracked" },
      ],
      otherChangeCount: 2,
    },
  });
  const errorFetch: FetchLike = () => Promise.resolve(jsonResponse(500, { detail: "boom" }));
  assert.deepEqual(await fetchGitStatus(errorFetch), { status: "failed" });
  const illShapedFetch: FetchLike = () => Promise.resolve(jsonResponse(200, { status: "odd" }));
  assert.deepEqual(await fetchGitStatus(illShapedFetch), { status: "failed" });
  const throwingFetch: FetchLike = () => Promise.reject(new Error("offline"));
  assert.deepEqual(await fetchGitStatus(throwingFetch), { status: "failed" });
});

test("fetchGitDiff encodes the path and classifies every arm without throwing", async () => {
  const urls: string[] = [];
  const okFetch: FetchLike = (url) => {
    urls.push(url);
    return Promise.resolve(jsonResponse(200, AVAILABLE_DIFF));
  };
  assert.deepEqual(await fetchGitDiff("dir/a b.md", okFetch), {
    status: "loaded",
    result: { status: "available", diff: "+changed\n", truncated: false },
  });
  assert.deepEqual(urls, ["/api/git/diff?path=dir%2Fa%20b.md"]);
  // The fixed no-leak 404 is a transport failure to the row, never special-cased.
  const notFoundFetch: FetchLike = () =>
    Promise.resolve(jsonResponse(404, { detail: "unknown path" }));
  assert.deepEqual(await fetchGitDiff("a.md", notFoundFetch), { status: "failed" });
  const illShapedFetch: FetchLike = () => Promise.resolve(jsonResponse(200, {}));
  assert.deepEqual(await fetchGitDiff("a.md", illShapedFetch), { status: "failed" });
  const throwingFetch: FetchLike = () => Promise.reject(new Error("offline"));
  assert.deepEqual(await fetchGitDiff("a.md", throwingFetch), { status: "failed" });
});
