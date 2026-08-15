// The ONE ranking object both Pagefind consumers share, so the relevance matrix
// (checks/pagefind.test.mjs, driving the Pagefind API directly) and the real browser UI
// (astro.config.mjs → starlight({ pagefind: { ranking } }) → PagefindUI) can never disagree
// on ranking.
//
// The values below are the pinned Starlight's own effective defaults: even with no `pagefind`
// key in the Starlight config, `StarlightConfigSchema` fills `pagefind.ranking` with these
// exact values and ships them to the browser `PagefindUI` (verified in the built Search
// bundle). A bare `pagefind.options({ basePath })` call would instead run Pagefind's raw
// engine defaults (pageLength 0.75, termFrequency 1.0) — so the shared object must carry the
// full effective set, not an empty override. Spreading it into the Starlight config is
// behavior-preserving; passing it to `pagefind.options` aligns the test with the UI.
//
// The measured relevance matrix passes on these stock values (one bound copy edit sufficed;
// no ranking step was needed) — any future change here must cite the measured failing rows
// that justify it.
export const ranking = {
  pageLength: 0.1,
  termFrequency: 0.1,
  termSaturation: 2,
  termSimilarity: 9,
  diacriticSimilarity: 0.8,
};
