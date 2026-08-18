// The ONLY module importing @pierre/diffs: main.tsx (the production composition
// root) passes this component into App's `gitDiffView` prop, and App's default stays
// the built-in literal-text view — so jsdom suites never load the library's heavy
// DOM/layout machinery. It is mounted ONLY for loaded, non-truncated, non-empty
// patches (App's row rendering guarantees that), keeping PatchDiff's empty-patch
// rejection structurally unreachable.

import type { FileDiffOptions } from "@pierre/diffs";
import { PatchDiff } from "@pierre/diffs/react";

// Module scope satisfies the library's stable-options-reference requirement.
const GIT_DIFF_OPTIONS: FileDiffOptions<undefined> = {
  theme: { dark: "pierre-dark", light: "pierre-light" },
  themeType: "system",
  diffStyle: "unified",
  disableFileHeader: true,
  hunkSeparators: "simple",
};

export function GitDiffView({ patch }: { patch: string }) {
  return <PatchDiff patch={patch} options={GIT_DIFF_OPTIONS} />;
}
