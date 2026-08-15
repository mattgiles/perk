// The explicit initial sidebar — the realized form of the binding sidebar map in
// docs/design/docs-site-blueprint.md §3 (the ordering/membership SSOT; changing membership or
// order there requires an objective reconciliation first). Every entry mirrors the per-page
// frontmatter records: ordering follows `sidebar.order`, and each how-to guide sits in the
// subgroup named by its `sidebarGroup`. `sidebar.test.mjs` asserts that agreement
// deterministically — corpus and sidebar cannot drift apart silently.
//
// Shape rules:
// - Non-Home entries are bare slug shorthands: labels come from page titles (label polish is
//   owned by later nodes). "Home" is the one §3-named label override.
// - Section labels are non-linking group headings (stock Starlight groups cannot link); each
//   landing page is its group's position-0 entry, labeled by its title — the §3 realized shape.
// - Outer sections are `collapsed: true` (Starlight auto-expands the reader's current section);
//   the how-to subgroups keep the default `collapsed: false` — the outer group already collapses.

/** @type {import("@astrojs/starlight/types").StarlightUserConfig["sidebar"]} */
export const sidebar = [
  { label: "Home", slug: "index" },
  {
    label: "Tutorials",
    collapsed: true,
    items: [
      "tutorials",
      "tutorials/get-started",
      "tutorials/drive-an-objective",
      "tutorials/drive-a-stacked-objective",
    ],
  },
  {
    label: "How-to guides",
    collapsed: true,
    items: [
      "how-to",
      {
        label: "Core workflow",
        items: [
          "how-to/drive-the-full-spine",
          "how-to/resume-a-plan",
          "how-to/address-review-feedback",
          "how-to/review-a-foreign-pr",
          "how-to/review-a-stacked-train",
          "how-to/replan-an-open-plan",
          "how-to/adopt-an-existing-issue",
          "how-to/capture-a-gist",
          "how-to/adopt-an-existing-project",
          "how-to/target-a-non-default-base-branch",
          "how-to/run-ci-in-session",
          "how-to/configure-and-verify-ci-checks",
          "how-to/recover-a-dirty-worktree",
          "how-to/diagnose-a-perk-repo",
          "how-to/run-a-worktree-setup-hook",
          "how-to/track-implement-progress",
          "how-to/send-feedback-from-hunk-watch",
        ],
      },
      {
        label: "Objectives & learnings",
        items: [
          "how-to/author-a-roadmap",
          "how-to/replan-an-objective",
          "how-to/advance-or-skip-nodes",
          "how-to/reconcile-an-objective",
          "how-to/check-an-objective-for-drift",
          "how-to/recover-a-stacked-train",
          "how-to/run-the-learn-docs-factory",
          "how-to/run-the-learn-code-factory",
          "how-to/run-the-learn-harvest-factory",
        ],
      },
      {
        label: "Headless & remote",
        items: [
          "how-to/set-up-the-remote-runner",
          "how-to/dispatch-a-stage-to-ci",
          "how-to/supervise-dispatched-runs",
          "how-to/advance-an-objective-headlessly",
        ],
      },
      {
        label: "Customization",
        items: [
          "how-to/attach-a-skill-to-a-stage",
          "how-to/author-a-repo-skill",
          "how-to/write-a-custom-subagent",
          "how-to/scope-pi-resources-per-project",
        ],
      },
      {
        label: "Providers & backends",
        items: ["how-to/select-a-provider", "how-to/switch-to-linear"],
      },
    ],
  },
  {
    label: "Reference",
    collapsed: true,
    items: [
      "reference",
      "reference/requirements-and-compatibility",
      "reference/cli",
      "reference/cli/setup-and-health",
      "reference/cli/plan",
      "reference/cli/objective",
      "reference/cli/pr",
      "reference/cli/learn-and-gist",
      "reference/cli/remote-and-utility",
      "reference/in-session",
      "reference/in-session/stages-and-doors",
      "reference/in-session/workflow-commands",
      "reference/in-session/review-and-authoring",
      "reference/in-session/model-tools",
      "reference/configuration",
      "reference/configuration/repository-layout",
      "reference/configuration/workflow-and-ci",
      "reference/configuration/backends",
      "reference/configuration/models-and-compaction",
      "reference/configuration/skills-and-bindings",
      "reference/objectives",
      {
        label: "Providers & issue backends",
        items: [
          "reference/providers-and-backends",
          "reference/providers-and-backends/providers",
          "reference/providers-and-backends/issue-backends",
        ],
      },
      "reference/json-schemas",
      "reference/glossary",
    ],
  },
  {
    label: "Explanation",
    collapsed: true,
    items: [
      "explanation",
      "explanation/how-perk-thinks",
      "explanation/gists-plans-and-objectives",
      "explanation/human-gates-and-trust",
      "explanation/headless-and-remote",
      "explanation/perk-in-zed",
    ],
  },
];
