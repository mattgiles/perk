# Skill improvements

This is a proposal for a later skill-editing pass. It audits all 38 Matt Pocock skill entrypoints against all 27 perk-authored skills, with exact replacements and deletions. It also proposes narrow companion changes to three reviewer rubrics. No skill, agent, tool, binding, or workflow is changed by this document.

The strongest additions are small: behavioral tests with independent expectations, symptom-based debugging, evidence-backed lessons that change a future action, and review comments that distinguish a documented rule from design judgment. The largest safe cuts are duplicated descriptions, repeated examples of an already-clear rule, and historical or speculative commentary. Much of perk’s remaining detail defines behavior that the upstream workflow does not have.

## Decisions guiding the proposals

- Preserve all machinery: tools, Pi subagent/wave directions, model selection, stages, bindings, review and save boundaries, state transitions, report schemas, and publication rules.
- Preserve where information is stored and how it is retrieved: issue backends, scratch artifacts, plans, specs, glossary, design/contract records, learned docs, indexes, and skill references. No new ADR tree, spec folder, handoff file, router, or glossary.
- Treat length as editorial guidance, not a per-file quota. A useful short addition can grow one file if the collection becomes more economical. Do not disguise growth by moving text into references.
- Offer exact passage edits with rationale. Include small wording improvements as well as borrowed logic.
- Use verifiable slices or tracer bullets only where useful. Prerequisite work and broad refactors may need a different decomposition.
- Prefer tests of behavior through public or other stable interfaces, with expected results independent of the implementation. Keep internal tests that guard a concrete invariant.
- Distinguish documented rule breaches from design judgment, and explain consequences. Keep the existing review angles, report fields, finding bars, and triage/posting behavior.
- For debugging, reproduce the reported symptom where possible, test a falsifiable explanation, and recheck the original case. Disclose unavailable evidence; add no fixed phases or tool preference.
- Judge a learning by what a future agent would do differently, supported by actual session or code evidence.
- Reuse compact vocabulary selectively. Preserve perk’s terms and the distinction between a gist, objective, refinement, and decision-complete plan.

The approved compression exemplar is used verbatim, apart from line wrapping: “Anchor plan steps to files, symbols, behaviors, or structural locations. Use line numbers only in research notes; they drift as code changes.”

## Baseline and scope

| Source | Audited revision | Scope |
| --- | --- | --- |
| This perk checkout | `d0432c91a35f44726104d95aa53cbcabc4a1bd50` | 24 `skills/perk-*/SKILL.md` files and three `.perk/skills/*/SKILL.md` files |
| Local `~/dev/github/mattpocock/skills` checkout | `74ca5fe077456a0b3b2f5310cf9430999fd0b5fd` | All 38 entrypoints: 18 engineering, seven productivity, nine in-progress, four misc |

Both checkouts were clean at the baseline; audit date: 2026-09-17. Upstream links below are pinned to that local revision. The in-progress category is treated as exploratory source material, not an endorsement of a finished workflow. The deprecated category contains no skill entrypoints.

The owned targets are the source directories, not the managed `.agents/skills` delivery symlinks. Vendored or installed skills such as `codebase-design`, `ast-grep`, `dignified-python`, `mastering-typescript`, and browser/tooling skills are reference material, not edit targets. Neither are launch prompts, executable helpers, runtime code, or analyst-agent definitions.

All 65 skill entrypoints were read. Supporting reads focused on the relevant upstream testing, domain/module design, triage, research/authoring, and skill-mechanics guidance; perk’s glossary format and backend recipes; TypeScript core/testing/review guidance; and the reviewer rubrics. Reference indexes and delivery contracts were inspected to assess ownership. This is not a claim that every line of the Pydantic, TypeScript, and operator-reference manuals received a technical freshness audit. Their complete Markdown contents are nevertheless included in the size accounting, and the only reference edit proposed is in TypeScript’s testing guide.

Perk’s [carrier contract](../../shared/contracts.md) (§8.57) matters more than resemblance to upstream: launch guidance owns the flow, bound skills own judgment and operational detail, injected context carries state/pointers, and adapters carry surface differences. Hidden-skill descriptions are catalog cues; visible descriptions are discovery cues. The [skill-author delivery rule](../../skills/perk-skill-author/SKILL.md) also requires useful guidance to survive delivery into consuming repos. Accordingly, [perk-expert’s references](../../skills/perk-expert/SKILL.md) intentionally mirror operator documentation; removing that material or replacing it with repo-only links would break delivery.

## What transfers, and what already works

**Discovery and prose.** Upstream `writing-for-agents` gives the most widely useful editorial lens: retain distinct task branches, remove synonymous triggers, keep a rule with its exception, and make each passage carry a decision. Perk’s hidden descriptions often repeat “Authoring … Use when authoring …” and summarize tool flow already supplied elsewhere. Visible descriptions need more care: the proposed expert and language descriptions keep their different task branches. Pydantic’s body invocation checklist can go because the revised description retains its cases. This is an editorial inference from the sources, not a measured claim about model performance.

**Design conversations.** The valuable grilling and domain-modeling logic is already substantially present: ask the human for decisions, investigate facts, challenge ambiguous language, test concrete scenarios, and keep resolved terms. The concrete mismatch is the grill description’s obsolete “one-question-at-a-time” promise. The body’s rounds and all delegation directions stay. Domain-modeling’s escalation test and perk-specific storage routing also stay; only examples and redundant emphasis shrink.

**Planning at different levels.** `to-spec`, `to-tickets`, and `wayfinder` offer complementary ideas, not one replacement for perk-plan. A gist frames intent and strategic opinions; an objective defines the goal and roadmap; a refinement can name unresolved future assumptions; a saved plan resolves execution choices. The proposals preserve those differences. A tracer bullet is a useful choice when an end-to-end slice will expose integration uncertainty, not a compulsory shape for every roadmap node. Perk’s existing completion audit already makes completion depend on requirement-to-artifact evidence, so no second audit is added.

**Verification and diagnosis.** `tdd` is most valuable here for what a good test proves: behavior at a stable interface, with expectations that do not merely repeat the implementation. That does not require its entire red/green workflow or a ban on internal tests. `diagnosing-bugs` adds a compact epistemic discipline: reproduce the actual symptom, test an explanation that evidence could disprove, and revisit the original case. A production-only symptom may remain unavailable locally; the skill should make that limitation visible instead of claiming confirmation. Plan-text feedback is still plan-text work.

**Reviews and architecture.** `code-review` distinguishes intent from standards. The useful addition is to identify whether a concern violates an actual local rule or rests on design judgment, then explain its consequence. Perk already has multiple angles, evidence reads, independent contexts, and different bars for automated versus human-triaged review. Those stay. `codebase-design` and `improve-codebase-architecture` encourage small useful interfaces and less caller knowledge; perk already installs that vocabulary and reads it in API review. The harvest proposal asks for observed friction and consequence, without changing its fixed eligibility or ranking policy. Standalone simplification/deletion remains Ponytail’s exclusive concern.

**Learning.** `retro` overlaps strongly with learn capture and placement, but its workflow is not perk’s. The transferable value test is the evidence-backed change in a future agent’s action. Learn-code’s “let the implement stage scope it” is an internal inconsistency with the decision-complete plan contract, so the proposal resolves scope before saving. Learn-docs’ classification hierarchy, inbox boundary, generated indexes, frontmatter limits, and distillation rules all remain. Dream’s full census and destructive-evidence requirements are useful detail, not fat.

## Upstream → perk overlap map

“Direct” means a shared goal with a useful proposal; “already adopted” means the useful logic is already present and generally needs only editing; “partial” means a shared concern with materially different scope or machinery. “No counterpart” is an affirmative audit result. These are concern mappings, not claims that every perk skill descended from the named source. `writing-for-agents` and the editorial sources can influence multiple targets independently of a direct workflow match.

| Upstream skill | Category | Overlap | Perk concerns | Portable logic and boundary |
| --- | --- | --- | --- | --- |
| [ask-matt](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/ask-matt/SKILL.md) | Engineering | Partial | perk-expert; perk-skill-author | Route from the user’s task to relevant guidance. Perk already has conditional reference reads; do not introduce another router or context-clearing workflow. |
| [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md) | Engineering | Direct | perk-pr-review; both PR review surfaces; both draft review surfaces; reviewer rubrics; dignified-typescript | Compare implementation with intent and standards; distinguish a local rule from design judgment. Keep perk’s angles, source reads, separate finding bars, and review machinery. |
| [codebase-design](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/codebase-design/SKILL.md) | Engineering | Already adopted / partial | perk-grill; perk-plan; objective authoring; perk-pr-review; dignified-typescript | Small interfaces hiding substantial capability, useful seams, and locality already inform perk’s installed codebase-design skill and API lane. Add no duplicate module-design tutorial or mandated directory shape. |
| [diagnosing-bugs](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/diagnosing-bugs/SKILL.md) | Engineering | Direct | perk-implement; perk-address | Reproduce the symptom, test a falsifiable explanation, and verify the original case. Decline the six gated phases and prescribed debugging tool order. |
| [domain-modeling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/domain-modeling/SKILL.md) | Engineering | Already adopted | perk-domain-modeling; perk-grill; plan/objective authoring | Active terminology challenges, concrete scenarios, code checks, immediate term capture, and the rare-decision test are already present. Keep perk’s glossary and existing-record routing; import no ADR tree. |
| [grill-with-docs](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/grill-with-docs/SKILL.md) | Engineering | Partial | perk-grill; perk-plan; perk-objective-author; perk-objective-refine | Ground questions in evidence the agent can read. Perk already separates factual investigation from user decisions; keep its learned-doc discovery and child-work directions. |
| [implement](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/implement/SKILL.md) | Engineering | Direct / partial | perk-implement; perk-address; perk-objective-plan | Execute a defined unit with feedback and verification. Keep perk’s plan, checklist, worktree, submit, and learning lifecycle; borrow no replacement implementation loop. |
| [improve-codebase-architecture](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/improve-codebase-architecture/SKILL.md) | Engineering | Partial | perk-learn-harvest; perk-learn-dream; perk-pr-review; dignified-typescript | Look for observed caller/maintainer friction before proposing a deeper module. Harvest already verifies pointers; sharpen evidence, preserve fixed ranking. Whole-corpus dream is not a hotspot sampler. |
| [prototype](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/prototype/SKILL.md) | Engineering | Partial | perk-gist-author; perk-objective-author; perk-objective-refine | Clarify the uncertainty an experiment would resolve. These perk authoring sessions stay read-only; do not run a prototype, add disposable artifact storage, or invent a new stage. |
| [research](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/research/SKILL.md) | Engineering | Partial | copy-docs-to-markdown; perk-plan; perk-objective-author; perk-objective-refine; perk-expert | Evidence and source provenance support decisions. A docs mirror is not a research synthesis; retain source URLs and existing lookup paths without adding research agents or browsing requirements. |
| [resolving-merge-conflicts](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/resolving-merge-conflicts/SKILL.md) | Engineering | Partial | perk-implement; perk-address; perk-replan; perk-objective-reconcile | Recover both sides’ intent and verify combined behavior. Conflict commands, synchronization, and publication are machinery; no new conflict recipe is proposed here. |
| [setup-matt-pocock-skills](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/setup-matt-pocock-skills/SKILL.md) | Engineering | Partial | perk-skill-author; perk-expert | Skills need a discoverable, coherent entrypoint. Installation, preferences, skill locations, and dispatch belong to perk’s existing delivery system. |
| [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md) | Engineering | Direct | perk-plan; perk-implement; perk-address; dignified-typescript; PR reviewer tests rubrics | Behavior through stable interfaces and independent expected results. Keep concrete-invariant internal tests; decline compulsory red/green ordering, pre-approved seams, and a review-only refactoring policy. |
| [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md) | Engineering | Direct | perk-plan; perk-gist-author; perk-objective-author; perk-objective-refine; both replans; draft review surfaces | Synthesize decisions, outcomes, boundaries, and useful tests. Keep perk’s plan sections and durable file/symbol anchors; decline the long user-story catalog and blanket ban on file paths. |
| [to-tickets](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-tickets/SKILL.md) | Engineering | Direct / partial | perk-objective-author; perk-objective-plan; perk-objective-refine; perk-plan; perk-learn-code | Complete verifiable slices can expose integration uncertainty. Use them situationally; preserve node/dependency semantics, delivery choices, tracker objects, and exceptions for prerequisite work or broad refactors. |
| [triage](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/triage/SKILL.md) | Engineering | Partial | perk-address; perk-replan; perk-objective-reconcile; perk-learn-code; perk-learn-docs | Verify claims and existing coverage before choosing the bounded change. Keep captured classifications, inboxes, state transitions, labels, and records; no new issue-triage state machine. |
| [wayfinder](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/wayfinder/SKILL.md) | Engineering | Direct / partial | perk-gist-author; perk-objective-author; perk-objective-refine; perk-objective-replan | Distinguish the destination, exclusions, unknowns, and unresolved future assumptions. Keep perk’s gist/objective/refinement distinction instead of adopting decision tickets. |
| [wizard](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/wizard/SKILL.md) | Engineering | Partial | perk-grill; perk-gist-author; perk-objective-author; perk-plan; perk-expert | Guide the user from intent toward the next useful decision. Perk’s entrypoints and transitions already provide that structure; no new orchestrator skill or handoff protocol. |
| [grill-me](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/grill-me/SKILL.md) | Productivity | Already adopted / partial | perk-grill; all authoring/replanning callers | Stress-test a design before building. The wrapper’s workflow is not the unit to copy; perk already invokes its own grill skill at the right boundaries. |
| [grilling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/grilling/SKILL.md) | Productivity | Already adopted | perk-grill; perk-domain-modeling | Investigate factual answers, ask for decisions, and resolve an independent frontier of questions in rounds. Keep the body; correct the contradictory one-question-at-a-time description. |
| [handoff](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/handoff/SKILL.md) | Productivity | Partial | perk-plan; perk-replan; perk-objective-refine; perk-implement; perk-skill-author | A future reader needs decisions and precise references, not a transcript. Perk’s canonical artifacts already carry continuity; do not add handoff files or change session transitions. |
| [teach](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/teach/SKILL.md) | Productivity | No direct counterpart | None; limited editorial relevance to perk-expert | Human teaching is a different goal from perk-learn’s operational knowledge capture. Do not infer overlap from the word “learn” or turn expert answers into a mandatory lesson. |
| [to-questionnaire](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/to-questionnaire/SKILL.md) | Productivity | Partial | perk-grill; authoring and draft review surfaces | Ask decision-relevant questions with enough context to answer. Keep perk’s question tools, rounds, direct edits, and review surfaces; do not add a questionnaire artifact. |
| [wait-what](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/wait-what/SKILL.md) | Productivity | Partial | perk-grill; perk-domain-modeling; perk-expert | Resolve confusion by making a concept or distinction concrete. Perk’s terminology and clarification guidance already serves this; no separate explanation protocol is needed. |
| [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md) | Productivity | Direct, cross-cutting | All 27 authored skills; reviewer rubric prose | Distinct task branches in discovery cues; rules beside reasons/exceptions; useful leading words; checkable completion; delete repeated meaning. Preserve sole-carrier contract detail and deliberate portable mirrors. |
| [claude-handoff](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/claude-handoff/SKILL.md) | In progress | Partial | perk-plan; perk-replan; perk-objective-replan; perk-implement | Preserve decisions and evidence across sessions. Claude-specific session handoff, files, and commands are outside the permitted changes. |
| [implement-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/implement-spec/SKILL.md) | In progress | Partial | perk-plan; perk-implement; perk-objective-plan | An implementable unit needs resolved decisions and verifiable results. Do not import its execution loop or spec storage. |
| [loop-me](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/loop-me/SKILL.md) | In progress | Partial | perk-implement; perk-objective-plan | Bound work and know what completion means. Perk’s checklist and completion audit already do this; no autonomous loop, new gates, or session machinery. |
| [pr](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/pr/SKILL.md) | In progress | Partial | perk-implement; perk-address; perk-pr-review | Describe the concrete change and validation evidence. PR composition/publication is already owned elsewhere; no new PR template or posting flow in these skills. |
| [retro](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/retro/SKILL.md) | In progress | Direct / partial | perk-learn; perk-learn-code; perk-learn-docs; perk-learn-dream | Capture the evidence that corrected a mistake and the future action it changes; place enforceable facts near code. Preserve perk’s classification, consolidation, and learning pipeline. |
| [setup-ts-deep-modules](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/setup-ts-deep-modules/SKILL.md) | In progress | Partial | dignified-typescript; perk-pr-review; perk-skill-author | Boundary and interface design overlap; prescribed TypeScript scaffolding, export layout, and tooling do not. Keep local project precedence. |
| [writing-beats](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/writing-beats/SKILL.md) | In progress | Partial, editorial | All 27 authored skills | Each passage should advance the reader’s understanding. Borrow economy, not the staged writing/approval process. |
| [writing-fragments](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/writing-fragments/SKILL.md) | In progress | Partial, editorial | perk-gist-author; perk-objective-refine; perk-skill-author | Fragments can reveal what is worth saying before polishing. Perk already has working drafts; add no fragment files, new draft states, or writing loop. |
| [writing-shape](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/writing-shape/SKILL.md) | In progress | Partial, editorial | All 27 authored skills | Choose prose, lists, and tables for the structure of the idea. Preserve tables that encode closed choices; combine tiny repeated lessons into compact prose. |
| [git-guardrails-claude-code](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/misc/git-guardrails-claude-code/SKILL.md) | Misc | Partial concern; no adoption | perk-implement; perk-address; perk-expert | Safe publication overlaps in purpose. Hook installation and guardrail enforcement are tool/harness changes and stay outside this audit’s proposals. |
| [migrate-to-shoehorn](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/misc/migrate-to-shoehorn/SKILL.md) | Misc | No direct counterpart | None; narrow conceptual overlap with dignified-typescript assertions | A library-specific migration is not a general TypeScript style skill. No new assertion dependency or migration is justified. |
| [scaffold-exercises](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/misc/scaffold-exercises/SKILL.md) | Misc | No counterpart | None | Educational exercise scaffolding has no equivalent among these operational and house-style skills. |
| [setup-pre-commit](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/misc/setup-pre-commit/SKILL.md) | Misc | Partial concern; no adoption | perk-expert; perk-implement | Fast deterministic feedback overlaps in purpose. Keep perk’s existing checks, CI authority, and toolchains; do not add hooks. |

## Perk → upstream coverage and disposition

Every authored skill has an explicit disposition. “Description only” means the body was reviewed and deliberately retained. The companion agent edits appear after the skill proposals, where their rubric ownership is clear.

| Authored target | Upstream concerns | Disposition |
| --- | --- | --- |
| [perk-plan](#perk-plan) | to-spec, to-tickets, tdd, grilling, research, handoff | Change description, two verbose rules, test criteria, and backend wording. Keep all save/review exits, steps/checklist semantics, evidence reads, and scout instructions. |
| [perk-implement](#perk-implement) | implement, tdd, diagnosing-bugs, implement-spec, loop-me, handoff, pr | Add short test/debugging judgment; shorten description. Keep the full launch recap, checklist, plan contract, and backend recipes. This entrypoint may grow. |
| [perk-address](#perk-address) | diagnosing-bugs, code-review, triage, tdd, pr, resolving-merge-conflicts | Add symptom-based debugging only for code bugs; shorten description. Keep classification, preview stop, Plan File Mode, publishing, retries, and hand-off. |
| [perk-domain-modeling](#perk-domain-modeling) | domain-modeling, grilling, wait-what | Compress repeated terminology examples and the glossary-only rule. Keep active challenge, immediate capture, read-only draft steps, and existing record routing. |
| [perk-grill](#perk-grill) | grilling, grill-me, grill-with-docs, to-questionnaire, wait-what, wizard | Description correction only. The body already carries the valuable upstream logic; retain questions in rounds and all child-work directions. |
| [perk-gist-author](#perk-gist-author) | wayfinder, to-spec, prototype, writing-fragments | Condense artifact scope and description. Keep high-level solution opinions, no implementation decisions, scope routing, review, and adoption. |
| [perk-objective-author](#perk-objective-author) | wayfinder, to-spec, to-tickets, grilling, research, prototype | Tighten scope language, offer situational tracer bullets, remove historical narration, and use backend-neutral wording. Keep every structured-node and delivery choice instruction. |
| [perk-objective-plan](#perk-objective-plan) | to-tickets, implement-spec, loop-me, research, triage | Description only; keep body. The detailed claim, paging, explorer/scout, save, and completion-audit clauses carry distinct behavior and failure handling. |
| [perk-objective-refine](#perk-objective-refine) | wayfinder, to-tickets, to-spec, prototype, handoff, writing-fragments | Condense artifact criteria and description. Keep advisory uncertainty, context provenance limitations, exact reads, comment replacement, and fresh review requirements. |
| [perk-replan](#perk-replan) | to-spec, triage, handoff, resolving-merge-conflicts | Delete erk comparisons, retain four research categories, shorten the single-plan limit and description. Keep original identity and all input/review paths. |
| [perk-objective-replan](#perk-objective-replan) | wayfinder, to-spec, triage, claude-handoff | Compress description and the reason for supersession. Keep every carry-forward, stacked transfer, identity, recovery, and Linear instruction. |
| [perk-objective-reconcile](#perk-objective-reconcile) | triage, resolving-merge-conflicts, to-spec | Condense the divergence catalog and description. Keep all section boundaries and differences between merged and accepted-range evidence. |
| [perk-learn](#perk-learn) | retro, writing-for-agents | Sharpen the session-deviation criterion and description. Keep waves, classifications, report schema, evidence bundle, SKIP, and capture ownership. |
| [perk-learn-code](#perk-learn-code) | retro, triage, to-spec | Shorten placement explanation and resolve scope before saving. Keep the hierarchy, verified target, inbox reads, route-back, and consumed issues. |
| [perk-learn-docs](#perk-learn-docs) | retro, triage, writing-for-agents | Add the future-action/evidence value test in place of the cache metaphor; shorten description. Keep all storage, routing, frontmatter, and distillation detail. |
| [perk-learn-dream](#perk-learn-dream) | retro, improve-codebase-architecture, writing-for-agents | Description only; keep body. Closed dispositions, two-reducer endorsement, no-upward resolution, fixed ranking, complete census, and survivor references justify their space. |
| [perk-learn-harvest](#perk-learn-harvest) | improve-codebase-architecture, codebase-design, research | Ask evidence to explain observed friction and consequence; cut the hypothetical cap-edit aside; shorten description. Keep the fixed pipeline and honest incomplete outcomes. |
| [perk-pr-review](#perk-pr-review) | code-review, codebase-design, tdd, pr | Shorten description and remove speculative headless promotion. Put testing/quality improvements in its existing reviewer agent, preserving every wave and posting rule. |
| [perk-pr-review-browser](#perk-pr-review-browser) | code-review, to-questionnaire, tdd | Description only in the skill; companion rubric changes in adversarial-reviewer. Preserve all three modes, stack review, finding/triage bars, and posting behavior. |
| [perk-pr-review-terminal](#perk-pr-review-terminal) | code-review, to-questionnaire, tdd | Description only in the skill; companion rubric changes in adversarial-reviewer. Keep hunk CLI, anchor translations, triage choreography, and degraded modes. |
| [perk-plan-review-browser](#perk-plan-review-browser) | code-review, to-spec, to-questionnaire | Description only in the skill; companion judgment wording in draft-reviewer. Preserve browser/direct-edit mechanics, automatic Ponytail coverage, and review loops. |
| [perk-objective-review-browser](#perk-objective-review-browser) | code-review, wayfinder, to-questionnaire | Description only in the skill; companion judgment wording in draft-reviewer. Preserve rendered-objective semantics and all review mechanics. |
| [perk-skill-author](#perk-skill-author) | writing-for-agents, ask-matt, setup-matt-pocock-skills, handoff | Make descriptions visibility-aware, collapse task synonyms, and add a sentence deletion test. Keep frontmatter, delivery layout, mirror rule, bindings, and user-owned commits. |
| [perk-expert](#perk-expert) | ask-matt, research, wizard, wait-what | Shorten description and repeated intro catalog. Keep all conditional reads and all five portable operator references, including intentional duplication with repo docs. |
| [dignified-typescript](#dignified-typescript) | tdd, code-review, codebase-design, setup-ts-deep-modules | Shorten description and repeated precedence advice; add independent expectations in testing.md. Keep runtime-specific guidance, all load conditions, defaults, and exceptions. |
| [dignified-pydantic](#dignified-pydantic) | writing-for-agents; partial codebase-design boundary concerns | Delete the duplicate invocation checklist, preserve its cases in description, and remove the brittle section count. Keep all Pydantic/ty policy and technical references. |
| [copy-docs-to-markdown](#copy-docs-to-markdown) | research, writing-for-agents | Shorten description and intro; preserve source provenance and index purpose. Keep the complete script workflow, output location, scope/pruning, and report contract. |

## Exact proposed edits

Apply each replacement to the cited source file at the baseline above. Each **Before** block is an exact, uniquely occurring source span. **After** is its complete replacement; **Delete** removes only that span. Unshown content remains unchanged. Multiple edits to one file have been composed together to check that they do not overlap. Description scalars are quoted to preserve valid YAML.

These are reviewable proposals, not instructions to execute the quoted skill bodies. Source links name the upstream influence; the explanation states the adaptation. Description cuts in hidden skills follow perk’s existing visibility contract rather than importing another harness’s invocation rules.

### perk-plan

Change description, two verbose rules, test criteria, and backend wording. Keep all save/review exits, steps/checklist semantics, evidence reads, and scout instructions.

#### P01 · Shorten the description

Source: [skills/perk-plan/SKILL.md](../../skills/perk-plan/SKILL.md).

**Before**

````markdown
description: Authoring a perk implementation plan in a perk plan session. Use when drafting, revising, or reviewing a perk plan before it is saved.
````

**After**

````markdown
description: "Author, revise, and review a decision-complete perk implementation plan."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P02 · Keep the estimate rule; cut its repeated defense

Source: [skills/perk-plan/SKILL.md](../../skills/perk-plan/SKILL.md).

**Before**

````markdown
### No time or effort estimates

A perk plan describes **what changes and why**, never **how long it takes**. Do not include time
estimates, effort sizing, story points, velocity, or any other quantification of duration in a plan —
not in the title, the steps, or the prose. They add no implementation signal, drift the moment
anything shifts, and a saved plan is a canonical GitHub artifact where such guesses read as
commitments. Describe scope through the concrete edits themselves; let the work define its own size.
````

**After**

````markdown
### No time or effort estimates

Describe scope through concrete changes. Omit time and effort estimates, sizing, story points,
and velocity throughout the plan.
````

The imperative is sufficient. The existing paragraph repeats scope, drift, and commitment arguments after stating the rule. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P03 · Replace the anchor catalog with the approved concise rule

Source: [skills/perk-plan/SKILL.md](../../skills/perk-plan/SKILL.md).

**Before**

````markdown
## 🔴 Line-number references are DISALLOWED

Line numbers drift as code changes and cause implementation failures. **Never** reference a line
number in a plan step. Use **durable anchors** instead:

- ✅ **Function / class names** — "Update `savePlan()` in `extension/authoring/plan/save.ts`"
- ✅ **Behavioral descriptions** — "Add a read-back check before appending the linkage"
- ✅ **Structural locations** — "In the `save` stage descriptor in `shared/registry.yaml`, add …"
- ✅ **File + context** — "In the `session_start` handler in `extension/index.ts`, after the run_id claim"
- 🔴 **Disallowed** — "edit `extension/index.ts:142`"

(Historical line numbers are fine *only* in a "Context / research" note documenting what you found,
never in an actionable step.)
````

**After**

````markdown
## 🔴 Line-number references are DISALLOWED

Anchor plan steps to files, symbols, behaviors, or structural locations. Use line numbers only
in research notes; they drift as code changes.
````

This preserves both the actionable-step prohibition and the research-note exception. The examples repeat four forms of the same instruction. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P04 · State what useful verification proves

Source: [skills/perk-plan/SKILL.md](../../skills/perk-plan/SKILL.md).

**Before**

````markdown
How the change is verified (commands, new/updated tests, the acceptance gate).
````

**After**

````markdown
Verify changed behavior through stable interfaces, with independent expected results. Name commands,
new/updated tests, and the acceptance gate; use internal tests when they guard a concrete invariant.
````

Adopt behavioral tests and independent expectations without banning internal invariant tests or adding a test-first gate. Basis: [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md), [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md).

Preserve: The Test plan section, commands, acceptance gate, and all review/save/checklist mechanics remain.

#### P05 · Use the existing backend-neutral term

Source: [skills/perk-plan/SKILL.md](../../skills/perk-plan/SKILL.md).

**Before**

````markdown
then save it **verbatim** to GitHub.
````

**After**

````markdown
then save it **verbatim** to the issue backend.
````

The shipped workflow supports GitHub and Linear. This removes a misleading GitHub-only summary without changing either backend recipe. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-implement

Add short test/debugging judgment; shorten description. Keep the full launch recap, checklist, plan contract, and backend recipes. This entrypoint may grow.

#### P06 · Shorten the description

Source: [skills/perk-implement/SKILL.md](../../skills/perk-implement/SKILL.md).

**Before**

````markdown
description: Implementing a saved perk plan on its worktree branch — the implement stage. Use when implementing a perk plan in a perk repo.
````

**After**

````markdown
description: "Implement a saved perk plan on its worktree branch."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P07 · Add compact test and debugging judgment

Source: [skills/perk-implement/SKILL.md](../../skills/perk-implement/SKILL.md).

**Before**

````markdown
- **The plan body is the contract** — implement *that*, not a reinterpretation.
````

**After**

````markdown
- **The plan body is the contract** — implement *that*, not a reinterpretation.
- **Verify behavior through stable interfaces**, with independent expected results. Internal tests
  are useful when they guard a concrete invariant.
- **For bugs**, reproduce the reported symptom where possible, test a falsifiable explanation,
  and recheck the original case after the fix. State which evidence you could not obtain.
````

This small entrypoint has no guidance about what a test should prove or how to confirm a bug fix. The addition is justified even though this file grows. Basis: [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md), [diagnosing-bugs](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/diagnosing-bugs/SKILL.md).

Preserve: The full launch-flow recap, backend lookup, plan-as-contract clause, checklist ownership, and /submit path remain verbatim. No phase gates or new tools.

### perk-address

Add symptom-based debugging only for code bugs; shorten description. Keep classification, preview stop, Plan File Mode, publishing, retries, and hand-off.

#### P08 · Shorten the description

Source: [skills/perk-address/SKILL.md](../../skills/perk-address/SKILL.md).

**Before**

````markdown
description: Handling PR review feedback — classify in isolation, fix, publish, resolve — the /address loop. Use when addressing review feedback on a perk PR.
````

**After**

````markdown
description: "Address PR review feedback through classification, fixes, publication, and resolution."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P09 · Confirm code fixes against the reported symptom

Source: [skills/perk-address/SKILL.md](../../skills/perk-address/SKILL.md).

**Before**

````markdown
  Treat `question` with judgment: answer it; change code only if the answer demands it.
````

**After**

````markdown
  Treat `question` with judgment: answer it; change code only if the answer demands it.
  For a code bug, reproduce the reported symptom where possible, test a falsifiable explanation,
  and recheck the original case after fixing it. State which evidence you could not obtain.
````

Apply the debugging discipline only to code bugs. It must not turn plan-text feedback into implementation work. Basis: [diagnosing-bugs](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/diagnosing-bugs/SKILL.md).

Preserve: Classification, preview’s immediate stop, Plan File Mode, finalization retries, and the verbatim hand-off remain unchanged.

### perk-domain-modeling

Compress repeated terminology examples and the glossary-only rule. Keep active challenge, immediate capture, read-only draft steps, and existing record routing.

#### P10 · Shorten the description

Source: [skills/perk-domain-modeling/SKILL.md](../../skills/perk-domain-modeling/SKILL.md).

**Before**

````markdown
description: Build and sharpen a project's domain model — pin down domain terminology or a ubiquitous language (CONTEXT.md glossary), and route crystallized design decisions to the repo's durable records. Use when the user wants to pin terminology, record a design decision durably, or when another skill needs to maintain the domain model.
````

**After**

````markdown
description: "Sharpen domain terminology and maintain the CONTEXT.md glossary. Use when resolving ambiguous terms, testing domain relationships against code, or recording design decisions in the repo’s existing durable records."
````

Keep the distinct terminology, code-checking, and decision-recording branches; remove repeated “pin” and “domain model” wording. Basis: [domain-modeling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/domain-modeling/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P11 · Combine four actions without four miniature lessons

Source: [skills/perk-domain-modeling/SKILL.md](../../skills/perk-domain-modeling/SKILL.md).

**Before**

````markdown
### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"
````

**After**

````markdown
### Challenge and verify the language

Challenge terms that conflict with `CONTEXT.md`; resolve vague or overloaded terms into precise
canonical names. Use concrete scenarios to test relationships and edge cases. Check claims
against the code and ask the user to resolve contradictions.
````

Retain challenge, disambiguation, scenario testing, and code checks. The quoted cancellation/account examples repeat these actions. Basis: [domain-modeling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/domain-modeling/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: Immediate term capture, CONTEXT-FORMAT.md, read-only draft steps, routing discovery, and all three escalation criteria remain verbatim.

#### P12 · State the glossary boundary once

Source: [skills/perk-domain-modeling/SKILL.md](../../skills/perk-domain-modeling/SKILL.md).

**Before**

````markdown
`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.
````

**After**

````markdown
`CONTEXT.md` is a glossary. Keep specs, scratch notes, and implementation decisions out of it.
````

“Totally devoid” and “nothing else” add emphasis without adding a boundary. Basis: [domain-modeling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/domain-modeling/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-grill

Description correction only. The body already carries the valuable upstream logic; retain questions in rounds and all child-work directions.

#### P13 · Shorten the description

Source: [skills/perk-grill/SKILL.md](../../skills/perk-grill/SKILL.md).

**Before**

````markdown
description: Grill the user relentlessly about a plan or design — a one-question-at-a-time interview that stress-tests every decision before building. Use when stress-testing a plan, design, or objective before requesting review or implementing, or when the user says "grill me" or uses any other 'grill' trigger phrase.
````

**After**

````markdown
description: "Stress-test a plan, design, or objective before review or implementation. Use when the user asks to be grilled or needs decisions challenged and resolved."
````

Remove the stale “one-question-at-a-time” promise: the existing body asks independent questions in rounds. Keep the rounds and delegation instructions intact. Basis: [grilling](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/grilling/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-gist-author

Condense artifact scope and description. Keep high-level solution opinions, no implementation decisions, scope routing, review, and adoption.

#### P14 · Shorten the description

Source: [skills/perk-gist-author/SKILL.md](../../skills/perk-gist-author/SKILL.md).

**Before**

````markdown
description: Authoring a new perk gist — a problem-space statement of intent — in a read-only gist-author session. Use when capturing a statement of intent in a perk repo.
````

**After**

````markdown
description: "Author and review a perk gist: a statement of intent upstream of plans and objectives."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P15 · Condense gist scope and altitude

Source: [skills/perk-gist-author/SKILL.md](../../skills/perk-gist-author/SKILL.md).

**Before**

````markdown
## What a gist is (and is not)

- **Is**: the problem or desire, why it matters, and the constraints that bound it — honest,
  code-informed framing of the problem space (the high-level shape, the real surfaces involved) —
  plus a strategic-altitude read on the 2–3 most consequential solution-domain elements (design,
  architecture, API surface, risk): identify them and opine, at a higher level than an objective
  or plan would.
- **Is not**: a plan. No implementation steps, no detailed solution design, no estimates, no
  acceptance criteria. Solution-domain *opinions* belong; recorded decisions, tactics, and
  file-by-file detail do not. If you find yourself enumerating steps or naming the functions
  you'd edit, you have drifted downstream — a gist gets *adopted* into a plan or objective later,
  and that flow does the designing.
````

**After**

````markdown
## What a gist contains

State the problem or desire, why it matters, and its constraints. Ground the framing in the
codebase and offer high-level opinions on the 2–3 most consequential solution choices
(design, architecture, API surface, or risk).

Leave implementation steps, roadmaps, estimates, acceptance criteria, detailed design, and
recorded implementation decisions to the later plan or objective.
````

Keep the positive content contract, the 2–3 consequential choices, and the downstream boundary. Cut examples of drifting into a plan. Basis: [wayfinder](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/wayfinder/SKILL.md), [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: Scope routing, storage/adoption, parent ownership, review flow, and save outcomes are unchanged.

### perk-objective-author

Tighten scope language, offer situational tracer bullets, remove historical narration, and use backend-neutral wording. Keep every structured-node and delivery choice instruction.

#### P16 · Shorten the description

Source: [skills/perk-objective-author/SKILL.md](../../skills/perk-objective-author/SKILL.md).

**Before**

````markdown
description: Authoring a new perk objective + roadmap in a read-only objective-author session. Use when drafting a new objective in a perk repo.
````

**After**

````markdown
description: "Author and review a perk objective with a structured roadmap."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P17 · Name the question directly

Source: [skills/perk-objective-author/SKILL.md](../../skills/perk-objective-author/SKILL.md).

**Before**

````markdown
1. **Clarify the goal.** Talk to the user. What is the objective actually trying to achieve, and —
   just as important — what is explicitly **out of scope**? An objective without boundaries grows
   unbounded.
````

**After**

````markdown
1. **Clarify the goal and boundaries with the user.** State the desired outcome and explicit non-goals.
````

The final sentence only restates why a boundary is a boundary. Basis: [wayfinder](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/wayfinder/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P18 · Offer verifiable slices as a situational technique

Source: [skills/perk-objective-author/SKILL.md](../../skills/perk-objective-author/SKILL.md).

**Before**

````markdown
   - a **description** of what the node delivers;
````

**After**

````markdown
   - a **description** of what the node delivers; when useful, choose a complete, verifiable
     slice through the system (a tracer bullet). Prerequisite work and broad refactors may need
     a different shape;
````

Use tracer bullets when they reduce uncertainty or expose integration early. Do not prescribe them for every node or force broad refactors into feature slices. Basis: [to-tickets](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-tickets/SKILL.md), [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md).

Preserve: Node ids, dependencies, statuses, slugs, delivery choice, tool inputs, and review rules are unchanged.

#### P19 · Replace provenance with the failure it explains

Source: [skills/perk-objective-author/SKILL.md](../../skills/perk-objective-author/SKILL.md).

**Before**

````markdown
**Never** author the `objective-roadmap` YAML block by hand: that is the
loudest tripwire from erk's objective history (hand-written roadmap frontmatter drifts and
corrupts). Decide the nodes; let the tool render them.
````

**After**

````markdown
**Never** author the `objective-roadmap` YAML block by hand; it can drift from the structured
nodes. Decide the nodes; let the tool render them.
````

The instruction needs its data-integrity reason, not the history of another workflow. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P20 · Use the existing backend-neutral term

Source: [skills/perk-objective-author/SKILL.md](../../skills/perk-objective-author/SKILL.md).

**Before**

````markdown
an approval saves it to GitHub, where `/objective-plan` later
````

**After**

````markdown
an approval saves it to the issue backend, where `/objective-plan` later
````

Match GitHub and Linear support without changing save behavior. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-objective-plan

Description only; keep body. The detailed claim, paging, explorer/scout, save, and completion-audit clauses carry distinct behavior and failure handling.

#### P21 · Shorten the description

Source: [skills/perk-objective-plan/SKILL.md](../../skills/perk-objective-plan/SKILL.md).

**Before**

````markdown
description: Orchestrating the perk /objective-plan factory — select the next objective node, optionally explore it in an isolated child, author a bounded plan, review it with plan_review, and on approval the plan is saved linked to the objective (the node backlinked and advanced automatically). Use when planning an objective node in a perk repo.
````

**After**

````markdown
description: "Plan the next objective node and save the reviewed plan with its objective link."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-objective-refine

Condense artifact criteria and description. Keep advisory uncertainty, context provenance limitations, exact reads, comment replacement, and fresh review requirements.

#### P22 · Shorten the description

Source: [skills/perk-objective-refine/SKILL.md](../../skills/perk-objective-refine/SKILL.md).

**Before**

````markdown
description: Authoring an advisory refinement of a future objective node — a dated, target-bound note that sharpens a pending/blocked node before anyone plans it — in a read-only objective-refine session. Use when refining an objective node in a perk repo.
````

**After**

````markdown
description: "Author an advisory refinement for a pending or blocked objective node that has no plan."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P23 · Separate current evidence from future assumptions

Source: [skills/perk-objective-refine/SKILL.md](../../skills/perk-objective-refine/SKILL.md).

**Before**

````markdown
## What a refinement is (and is not)

- **Is**: what the node must deliver and why; the prerequisites it needs that do not exist yet
  (and which earlier nodes are expected to supply them); the code seams it will touch **as
  observed at capture time**; the risks; the questions a later real plan must re-verify; the
  known changed-code assumptions.
- **Is not**: a plan, a design spec or an estimate. No step lists, no claims about what the code
  will look like when the node is finally planned, no "this is settled" language over things a
  later pass must recheck.
````

**After**

````markdown
## What a refinement contains

State the node’s intended outcome and why it matters, missing prerequisites and their expected
earlier nodes, code seams observed at capture time, risks, and changed-code assumptions the
later plan must re-verify.

Keep it advisory: no implementation steps, design spec, estimates, or claims that future code
is settled. Name unresolved assumptions.
````

Keep all required substance while reducing the mirrored “is/is not” phrasing. Uncertainty is legitimate in an advisory refinement. Basis: [wayfinder](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/wayfinder/SKILL.md), [to-tickets](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-tickets/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: The dated observation disclaimer, full context reads, comment storage/replacement, metadata binding, saves, and pending/blocked eligibility remain verbatim.

### perk-replan

Delete erk comparisons, retain four research categories, shorten the single-plan limit and description. Keep original identity and all input/review paths.

#### P24 · Shorten the description

Source: [skills/perk-replan/SKILL.md](../../skills/perk-replan/SKILL.md).

**Before**

````markdown
description: Re-authoring an open perk plan against the current codebase in a replan session. Use when replanning a perk plan.
````

**After**

````markdown
description: "Rewrite an open perk plan against the current codebase, preserving its identity."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P25 · Delete the comparison with erk

Source: [skills/perk-replan/SKILL.md](../../skills/perk-replan/SKILL.md).

**Before**

````markdown
- This is perk's analog of erk's `/erk:replan`, but erk creates-new-and-closes-old; perk updates in
  place so the plan number, the plan→objective link, and the node→plan backlink all survive.

````

**Delete** this span; add no replacement.

The immediately preceding contract already states same issue, original run_id, and preserved objective link. Another tool’s behavior does not guide this action. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P26 · Remove provenance from an operative instruction

Source: [skills/perk-replan/SKILL.md](../../skills/perk-replan/SKILL.md).

**Before**

````markdown
Gather findings into four categories before
   rewriting (structure findings *before* authoring — the erk "sparse plan" lesson):
````

**After**

````markdown
Gather findings into four categories before
   rewriting:
````

Retain the four research categories and their ordering; remove only the historical aside. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P27 · Shorten the unsupported-case boundary

Source: [skills/perk-replan/SKILL.md](../../skills/perk-replan/SKILL.md).

**Before**

````markdown
## Not yet supported

**Multi-plan consolidation** (erk's `/erk:replan 123 456 789` — merge several plans into one) is
**deferred**. `replan` re-authors a single plan in place; consolidating multiple plans is out of
scope for now.
````

**After**

````markdown
## Not yet supported

Replan updates one open plan in place. Multi-plan consolidation is deferred.
````

The extra command example repeats the single-plan limit. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-objective-replan

Compress description and the reason for supersession. Keep every carry-forward, stacked transfer, identity, recovery, and Linear instruction.

#### P28 · Shorten the description

Source: [skills/perk-objective-replan/SKILL.md](../../skills/perk-objective-replan/SKILL.md).

**Before**

````markdown
description: Re-authoring an objective as a superseding net-new objective in the objective-replan session. Use when replanning a perk objective.
````

**After**

````markdown
description: "Replan unfinished objective work as a successor that supersedes the old objective."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P29 · Keep the identity reason; cut the design-status narration

Source: [skills/perk-objective-replan/SKILL.md](../../skills/perk-objective-replan/SKILL.md).

**Before**

````markdown
perk's `objective_save` is find-then-return
idempotent on `run_id` (not an upsert), so there is no in-place objective rewrite primitive — the
close-old/create-new model is the resolved design.
````

**After**

````markdown
`objective_save` is find-then-return
idempotent on `run_id`, not an upsert; objective replan therefore creates a successor.
````

This is an editorial compression of the existing supersession contract, not a proposal to change it. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All old/new identity stamps, unfinished-node rules, stacked transfer constraints, recovery commands, and Linear adopt_issue instructions remain verbatim.

### perk-objective-reconcile

Condense the divergence catalog and description. Keep all section boundaries and differences between merged and accepted-range evidence.

#### P30 · Shorten the description

Source: [skills/perk-objective-reconcile/SKILL.md](../../skills/perk-objective-reconcile/SKILL.md).

**Before**

````markdown
description: Orchestrating the perk objective-reconcile pass — reconcile an objective's stale roadmap prose (and node descriptions) against what was actually built, either post-land (after a node's PR merges) or at ready time (after a stacked layer's handoff stamp, against the pinned accepted diff range). Use when reconciling an objective in a perk repo.
````

**After**

````markdown
description: "Reconcile objective prose and node descriptions with landed work or a stacked handoff’s accepted diff."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P31 · Condense the divergence catalog and cover both modes

Source: [skills/perk-objective-reconcile/SKILL.md](../../skills/perk-objective-reconcile/SKILL.md).

**Before**

````markdown
Reconcile only genuine divergence between the objective's text and what landed:

- **Decision overrides** — a decision the plan/PR reversed or refined.
- **Scope changes** — work added, dropped, or moved between nodes.
- **Naming divergence** — names in the objective prose that the implementation renamed.
- **Architecture drift** — structural choices the objective described differently.
````

**After**

````markdown
Reconcile concrete differences in decisions, scope, names, or architecture between the objective
and the evidence for this pass.
````

The four bullets unpack ordinary nouns. “Evidence for this pass” also respects the accepted-but-not-landed mode defined above. Basis: [triage](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/triage/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: Input reads, section routing, no-churn rule, done audit, node-add conditions, automatic reopen, and narrower ready-time powers remain verbatim.

### perk-learn

Sharpen the session-deviation criterion and description. Keep waves, classifications, report schema, evidence bundle, SKIP, and capture ownership.

#### P32 · Shorten the description

Source: [skills/perk-learn/SKILL.md](../../skills/perk-learn/SKILL.md).

**Before**

````markdown
description: Multi-angle knowledge capture after a perk plan lands — the /learn analyst wave. Use when running the learn step in a perk repo.
````

**After**

````markdown
description: "Capture evidence-backed learnings after a perk plan lands."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P33 · Turn “highest value” into an evidence and action test

Source: [skills/perk-learn/SKILL.md](../../skills/perk-learn/SKILL.md).

**Before**

````markdown
  **special emphasis** on **what the agent got wrong or didn't understand about the codebase that
  sent it off-track**: mental-model gaps, dead ends, and wasted time/effort. This is the
  highest-value "don't repeat this trap" signal.
````

**After**

````markdown
  **special emphasis** on what sent the agent off-track, the session or code evidence that
  corrected it, and what a future agent should do differently.
````

A lesson earns space by changing a future decision, not by retelling a surprising session. The existing summary/evidence fields can carry this without a schema change. Basis: [retro](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/retro/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All angles, wave directions, report fields, classifications, SKIP rules, retrieval, and capture ownership remain unchanged.

### perk-learn-code

Shorten placement explanation and resolve scope before saving. Keep the hierarchy, verified target, inbox reads, route-back, and consumed issues.

#### P34 · Shorten the description

Source: [skills/perk-learn-code/SKILL.md](../../skills/perk-learn-code/SKILL.md).

**Before**

````markdown
description: Routing pre-stamped SHOULD_BE_CODE perk:learn issues into precise code homes — the /learn-code factory. Use when routing captured learnings into code in a perk repo.
````

**After**

````markdown
description: "Plan code changes from pre-stamped SHOULD_BE_CODE learnings."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P35 · Let the existing placement hierarchy do the explaining

Source: [skills/perk-learn-code/SKILL.md](../../skills/perk-learn-code/SKILL.md).

**Before**

````markdown
- **Place the insight where an agent will encounter it.** A comment lives at the line it explains; a
  docstring at the function it documents; a constant beside the others it joins. The point of routing
  to code is that the knowledge sits exactly where it is needed — not in a doc an agent must know to
  fetch.
````

**After**

````markdown
- **Place the insight where an agent needs it:** the relevant definition, comment, docstring,
  schema, or user-docs passage.
````

The earlier hierarchy already distinguishes these homes. Remove its repeated examples and defense. Basis: [retro](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/retro/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: The exact hierarchy and verified-target instruction remain unchanged. No new storage or retrieval rule.

#### P36 · Resolve scope before the executor inherits the plan

Source: [skills/perk-learn-code/SKILL.md](../../skills/perk-learn-code/SKILL.md).

**Before**

````markdown
- **Don't widen scope.** If implementing a learning would require a larger change, capture that as
  the step's intent and let the implement stage scope it — the plan stays bounded to the inbox.
````

**After**

````markdown
- **Keep scope bounded to the inbox.** Resolve the extent of each change before saving; if a
  larger change is necessary, make that scope explicit in the plan.
````

“Let the implement stage scope it” conflicts with perk-plan’s decision-complete contract. Make the bounded scope concrete at planning time. Basis: [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md), [triage](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/triage/SKILL.md).

Preserve: Inbox selection, classification, route-back, approval/save, and on-land consumption remain unchanged. This changes planning judgment only.

### perk-learn-docs

Add the future-action/evidence value test in place of the cache metaphor; shorten description. Keep all storage, routing, frontmatter, and distillation detail.

#### P37 · Shorten the description

Source: [skills/perk-learn-docs/SKILL.md](../../skills/perk-learn-docs/SKILL.md).

**Before**

````markdown
description: Consolidating doc-destined perk:learn issues into a bounded docs/learned plan — the /learn-docs factory. Use when consolidating captured learnings in a perk repo.
````

**After**

````markdown
description: "Plan bounded consolidation of captured learnings into docs/learned/."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P38 · Define a learning by its effect on future work

Source: [skills/perk-learn-docs/SKILL.md](../../skills/perk-learn-docs/SKILL.md).

**Before**

````markdown
Learned docs are **token caches for future AI agents** — preserved reasoning so they don't recompute
it. Document **reality**, not aspiration (workarounds, quirks, tech debt all belong).
````

**After**

````markdown
Preserve reasoning that changes what a future agent does, backed by session or code evidence.
Document **reality**, including workarounds, quirks, and tech debt.
````

Keep the caching purpose, but make usefulness assessable: what action changes, and what evidence supports it? Basis: [retro](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/in-progress/retro/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All placement, inbox, classification, consumption, One Code Rule, frontmatter, routing, and distillation requirements remain verbatim.

### perk-learn-dream

Description only; keep body. Closed dispositions, two-reducer endorsement, no-upward resolution, fixed ranking, complete census, and survivor references justify their space.

#### P39 · Shorten the description

Source: [skills/perk-learn-dream/SKILL.md](../../skills/perk-learn-dream/SKILL.md).

**Before**

````markdown
description: Auditing the whole learned corpus and curating ONE bounded curation objective + dream report — the perk learn dream factory. Use when running perk learn dream in a perk repo.
````

**After**

````markdown
description: "Audit the learned corpus and propose one bounded curation objective with a dream report."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-learn-harvest

Ask evidence to explain observed friction and consequence; cut the hypothetical cap-edit aside; shorten description. Keep the fixed pipeline and honest incomplete outcomes.

#### P40 · Shorten the description

Source: [skills/perk-learn-harvest/SKILL.md](../../skills/perk-learn-harvest/SKILL.md).

**Before**

````markdown
description: Mining docs/learned as lenses into the code and curating ONE bounded improvement objective — the perk learn harvest factory. Use when running perk learn harvest in a perk repo.
````

**After**

````markdown
description: "Use learned docs to find code improvements and propose one bounded objective."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P41 · Connect observed friction to its consequence

Source: [skills/perk-learn-harvest/SKILL.md](../../skills/perk-learn-harvest/SKILL.md).

**Before**

````markdown
- **evidence** — the doc that surfaced it + what you actually observed in the code;
````

**After**

````markdown
- **evidence** — the doc that surfaced it + observed code behavior or friction, and its consequence;
````

Make a simplification or elegance lead explain an actual cost to a caller, maintainer, or user. This elaborates evidence without adding an eligibility gate. Basis: [improve-codebase-architecture](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/improve-codebase-architecture/SKILL.md), [codebase-design](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/codebase-design/SKILL.md).

Preserve: The schema, all kinds, caps, fallback state table, grounding, fixed ranking, theme selection, and three output buckets remain unchanged.

#### P42 · Remove an invitation to change the fixed cap

Source: [skills/perk-learn-harvest/SKILL.md](../../skills/perk-learn-harvest/SKILL.md).

**Before**

````markdown
The cap stays 5 deliberately: starvation is made visible by the disclosure row,
  and widening is a one-constant edit.
````

**After**

````markdown
The disclosure row makes omitted leads visible.
````

The surrounding sentences already give the cap, constant, and disclosure. A hypothetical implementation edit is not runtime guidance. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-pr-review

Shorten description and remove speculative headless promotion. Put testing/quality improvements in its existing reviewer agent, preserving every wave and posting rule.

#### P43 · Shorten the description

Source: [skills/perk-pr-review/SKILL.md](../../skills/perk-pr-review/SKILL.md).

**Before**

````markdown
description: Automated multi-angle review of the active PR — the /pr-review reviewer wave. Use when running automated code review of a perk PR.
````

**After**

````markdown
description: "Review the active PR through perk’s automated reviewer wave."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P44 · Delete the unbuilt headless-promotion aside

Source: [skills/perk-pr-review/SKILL.md](../../skills/perk-pr-review/SKILL.md).

**Before**

````markdown
## Still a warm command, not a `DriveStage`

`/pr-review` stays a **human-invoked warm command** (like `/ci`), not a registry stage — the headless
worker drives only `implement` and `address`. The `post_pr_review` tool turn + `last_pr_review`
record make it **structurally symmetric** with `/address`, so a future promotion to a headless stage
is a clean follow-up — but it is **not** built here.
````

**After**

````markdown
## Still a warm command, not a `DriveStage`

`/pr-review` is a **human-invoked warm command**, not a registry stage. The headless worker drives
only `implement` and `address`.
````

Keep the current invocation boundary; remove speculation about a future stage. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: No changes to wave instructions, review angles, posting floors, reconciliation, configuration, or records.

### perk-pr-review-browser

Description only in the skill; companion rubric changes in adversarial-reviewer. Preserve all three modes, stack review, finding/triage bars, and posting behavior.

#### P45 · Shorten the description

Source: [skills/perk-pr-review-browser/SKILL.md](../../skills/perk-pr-review-browser/SKILL.md).

**Before**

````markdown
description: Human-in-the-loop adversarial PR review on the plannotator browser surface. Use when reviewing a PR with /pr-review-browser or a whole PR stack with /stack-review-browser.
````

**After**

````markdown
description: "Review a PR through /pr-review-browser or a stack through /stack-review-browser."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-pr-review-terminal

Description only in the skill; companion rubric changes in adversarial-reviewer. Keep hunk CLI, anchor translations, triage choreography, and degraded modes.

#### P46 · Shorten the description

Source: [skills/perk-pr-review-terminal/SKILL.md](../../skills/perk-pr-review-terminal/SKILL.md).

**Before**

````markdown
description: Human-in-the-loop adversarial PR review in the hunk terminal TUI. Use when reviewing a PR with /pr-review-terminal.
````

**After**

````markdown
description: "Review a PR through /pr-review-terminal in the hunk TUI."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-plan-review-browser

Description only in the skill; companion judgment wording in draft-reviewer. Preserve browser/direct-edit mechanics, automatic Ponytail coverage, and review loops.

#### P47 · Shorten the description

Source: [skills/perk-plan-review-browser/SKILL.md](../../skills/perk-plan-review-browser/SKILL.md).

**Before**

````markdown
description: Human-in-the-loop review of the working plan draft in the plannotator browser. Use when reviewing a plan draft with /plan-review-browser.
````

**After**

````markdown
description: "Review the working plan draft through /plan-review-browser."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-objective-review-browser

Description only in the skill; companion judgment wording in draft-reviewer. Preserve rendered-objective semantics and all review mechanics.

#### P48 · Shorten the description

Source: [skills/perk-objective-review-browser/SKILL.md](../../skills/perk-objective-review-browser/SKILL.md).

**Before**

````markdown
description: Human-in-the-loop review of the rendered working objective draft in the plannotator browser. Use when reviewing an objective draft with /objective-review-browser.
````

**After**

````markdown
description: "Review the working objective draft through /objective-review-browser."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### perk-skill-author

Make descriptions visibility-aware, collapse task synonyms, and add a sentence deletion test. Keep frontmatter, delivery layout, mirror rule, bindings, and user-owned commits.

#### P49 · Shorten the description

Source: [skills/perk-skill-author/SKILL.md](../../skills/perk-skill-author/SKILL.md).

**Before**

````markdown
description: Authoring a repo-specific skill via `perk skills create`/`refine`. Use when authoring or refining a repo-authored skill.
````

**After**

````markdown
description: "Author or refine a repo-specific skill through perk skills create/refine."
````

This skill is prompt-hidden. Use one catalog cue; the body already carries the stage mechanics. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P50 · Make discovery guidance branch-based and visibility-aware

Source: [skills/perk-skill-author/SKILL.md](../../skills/perk-skill-author/SKILL.md).

**Before**

````markdown
## Write a concrete `description`

The `description` is the *entire* discovery surface — Pi matches a task against it to decide whether
to surface the skill. A vague topic label ("Python helpers") never fires; a concrete trigger does.

- **Name the tasks and trigger phrases**, not the subject area. Lead with what the skill *does*, end
  with an explicit "Use when …" clause naming the situations that should activate it.
- Mirror the words a user or agent would actually use for the task.
- Keep it one or two sentences — long enough to be concrete, short enough to scan.
````

**After**

````markdown
## Write a concrete `description`

For an ambient-visible skill, the description is its discovery cue. Name the distinct tasks
that should activate it, using the words a user or agent would use. Lead with the action and
include a concrete “Use when …” clause. Collapse synonyms for the same task; retain separate
branches that require different guidance. Keep it to one or two sentences.

For prompt-hidden bound skills, use the one-line catalog cue described below.
````

The original says all descriptions are discovery surfaces, then correctly exempts hidden skills later. Align the advice and avoid synonym stuffing. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md), [ask-matt](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/ask-matt/SKILL.md).

Preserve: The canonical carrier rule, invocation flags, stages, bindings, delivery, validation, and hidden-skill read paths remain unchanged.

#### P51 · Specify how to be concise, beyond “keep it lean”

Source: [skills/perk-skill-author/SKILL.md](../../skills/perk-skill-author/SKILL.md).

**Before**

````markdown
## Prefer scripts/references over prose

Keep `SKILL.md` **lean** — durable judgment and the loop, not an encyclopedia. Heavy or reference
material (long tables, API dumps, worked examples, helper scripts) goes in **sibling files** under
`references/` or `scripts/`. The per-skill delivery symlink carries the whole skill directory, so
those siblings travel for free — reference them by relative path from `SKILL.md`. A wall of prose is
harder to apply than a tight body that points at the detail when it's needed.
````

**After**

````markdown
## Prefer scripts/references over prose

Keep `SKILL.md` focused on durable judgment and the loop. Put long tables, API details, worked
examples, and helpers in sibling `references/` or `scripts/` files. Link them by relative path
with the condition for reading them; the delivery symlink carries the whole directory.

Keep a rule beside its reason and exceptions. Remove sentences whose deletion loses no
decision guidance; keep the operative rule and a short reason where it helps.
````

Add a sentence-level deletion test and co-locate exceptions. Preserve the existing supporting-file layout instead of proposing new storage. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: This sharpens authoring advice only. It does not relocate any existing reference or change when another skill reads it.

### perk-expert

Shorten description and repeated intro catalog. Keep all conditional reads and all five portable operator references, including intentional duplication with repo docs.

#### P52 · Shorten the description

Source: [skills/perk-expert/SKILL.md](../../skills/perk-expert/SKILL.md).

**Before**

````markdown
description: Expert guidance on how perk works and how to configure and customize it in a repo that uses perk — `.perk/config.toml` tables and the local overlay, the three provider seams (plan/footer/web), the GitHub vs Linear issue backend, skill bindings (`[[bindings]]`), CI checks (`[ci]` / `[[ci.checks]]`), the `[models]` namespace (default/per-stage/subagent model overrides), worktree/base-branch settings, and stacked delivery trains (publish/cascade/sync/recover/atomic landing). Use when answering "how does perk … / how do I configure … / which knob controls … / how does a stacked train work" questions about a repo using perk, or when shaping perk's workflow behavior via config.
````

**After**

````markdown
description: "Explain perk’s workflow and configuration. Use for config tables and local overrides, plan/footer/web providers, GitHub or Linear backends, skill bindings, CI checks, model overrides, worktrees and base branches, or stacked delivery trains."
````

Keep every discovery branch while removing duplicated question examples and syntax that the reference index already supplies. Basis: [ask-matt](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/ask-matt/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P53 · Let the description and reference index carry the topic catalog

Source: [skills/perk-expert/SKILL.md](../../skills/perk-expert/SKILL.md).

**Before**

````markdown
This
skill is the on-demand expert on **how a repo configures and customizes perk's behavior** — the
`.perk/config.toml` surface, provider seams, the issue backend, skill bindings, CI checks, subagent model
overrides, and worktree/base-branch settings. It carries light orientation so a knob can be placed in
context.
````

**After**

````markdown
Use this skill to understand that workflow and configure it for a consuming repo.
````

The intro repeats the same configuration branches supplied by the description and index. Preserve the workflow orientation and all read-before-answer rules. Basis: [ask-matt](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/ask-matt/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All five references, their conditional reads, live-surface commands, and deliberate self-contained operator-doc mirrors remain unchanged.

### dignified-typescript

Shorten description and repeated precedence advice; add independent expectations in testing.md. Keep runtime-specific guidance, all load conditions, defaults, and exceptions.

#### P54 · Shorten the description

Source: [.perk/skills/dignified-typescript/SKILL.md](../../.perk/skills/dignified-typescript/SKILL.md).

**Before**

````markdown
description: Opinionated production TypeScript and TSX guidance for writing, reviewing, refactoring, and designing maintainable code. Use for TypeScript code quality, type modeling, runtime validation, assertions and `any`, discriminated unions, async cancellation and cleanup, ESM/package boundaries, Node CLIs, React, Cloudflare Workers/RPC, tests, or requests to make code idiomatic, elegant, strict, or safer. Inspect the repository toolchain and runtime first; preserve explicit project conventions when they differ.
````

**After**

````markdown
description: "Write, review, or refactor production TypeScript and TSX. Use for type modeling, runtime validation, assertions and any, discriminated unions, async cancellation and cleanup, ESM/package boundaries, Node CLIs, React, Cloudflare Workers/RPC, or tests. Inspect the toolchain and runtime; preserve explicit project conventions."
````

Keep the distinct task and platform branches; remove the synonym list “idiomatic, elegant, strict, or safer.” Runtime detection and local precedence remain explicit. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md), [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P55 · Use the existing precedence section

Source: [.perk/skills/dignified-typescript/SKILL.md](../../.perk/skills/dignified-typescript/SKILL.md).

**Before**

````markdown
Treat this as an opinionated production baseline, not a substitute for repository instructions. Prefer a
small coherent change over a style crusade.
````

**After**

````markdown
Prefer a small coherent change. Apply the precedence rules in “Resolve conflicts deliberately.”
````

The complete ordered precedence rule already exists below. Retain the small-change instruction and point at that rule. Basis: [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P56 · Add independent expectations to the existing testing guidance

Source: [.perk/skills/dignified-typescript/references/testing.md](../../.perk/skills/dignified-typescript/references/testing.md).

**Before**

````markdown
Tests should explain what callers may rely on:
````

**After**

````markdown
Test behavior through stable interfaces. Derive expected results independently of the code under
test; internal tests are useful when they guard a concrete invariant. Cover what callers rely on:
````

The reference already has strong boundary, lifecycle, and concurrency guidance. Extend its opening criterion rather than import a second TDD workflow. Basis: [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md).

Preserve: Keep all existing case lists, examples, public-boundary levels, private-order exception, runner choices, and reference-load conditions.

### dignified-pydantic

Delete the duplicate invocation checklist, preserve its cases in description, and remove the brittle section count. Keep all Pydantic/ty policy and technical references.

#### P57 · Shorten the description

Source: [.perk/skills/dignified-pydantic/SKILL.md](../../.perk/skills/dignified-pydantic/SKILL.md).

**Before**

````markdown
description: House style for using Pydantic v2 well — validation/serialization at trust boundaries, strict vs lenient and extra-field policy, request/response/domain model separation, field/model validators, aliases, PATCH (exclude_unset) semantics, settings, and writing constructor calls that type-check under `ty`. Use when adding or reviewing a Pydantic model, designing an API/Celery/config/third-party-API boundary, deciding model_validate vs the constructor, choosing strict/coercion or extra ignore/forbid/allow, untangling "one model for everything", moving business logic out of validators, or making Pydantic code type-checker-friendly.
````

**After**

````markdown
description: "Apply the Pydantic v2 house style when writing or reviewing models, API/Celery/config/third-party/LLM boundaries, model_validate versus constructors, coercion and extra-field policies, request/response/domain separation, validators, aliases, PATCH/exclude_unset, settings, or calls that must type-check under ty."
````

Keep all distinct invocation cases before deleting the repeated body checklist. Technical policy stays in the body and references. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P58 · Delete the repeated invocation checklist

Source: [.perk/skills/dignified-pydantic/SKILL.md](../../.perk/skills/dignified-pydantic/SKILL.md).

**Before**

````markdown
## When to use this skill

Reach for this when you are:

- **adding or reviewing a Pydantic model** — and choosing its base, fields, and config;
- **designing a boundary** — an HTTP request/response, a Celery task payload, a config/settings
  loader, a third-party API response, or an LLM structured output;
- **deciding `Model.model_validate(raw)` vs the constructor `Model(...)`**;
- **choosing strictness and extra-field policy** — `strict=True` vs coercion, `extra` `forbid` /
  `ignore` / `allow`;
- **untangling "one model for everything"** into separate request / domain / response shapes;
- **moving business logic out of a validator** into a service;
- **making Pydantic code type-check cleanly under `ty`** (which has no Pydantic plugin).


````

**Delete** this span; add no replacement.

The revised description retains every distinct case, including LLM structured output. The operational rules and reference pointers remain in place. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: No changes to constructor/validation, strictness, extras, aliases, PATCH, settings, ty policy, or reference reads.

#### P59 · Remove the title echo and brittle section count

Source: [.perk/skills/dignified-pydantic/SKILL.md](../../.perk/skills/dignified-pydantic/SKILL.md).

**Before**

````markdown
Opinionated house style for Pydantic v2. The full guide — 48 numbered sections with runnable
examples — lives in the sibling `references/` files; read them when you need depth on a specific
mechanism. This page is the durable judgment you apply on every model.
````

**After**

````markdown
Apply these rules to every model. Read the sibling `references/` files for detail and examples
on the mechanism at hand.
````

The reference-read condition stays; “48 numbered sections” describes the document rather than guiding model design. Basis: [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

### copy-docs-to-markdown

Shorten description and intro; preserve source provenance and index purpose. Keep the complete script workflow, output location, scope/pruning, and report contract.

#### P60 · Shorten the description

Source: [.perk/skills/copy-docs-to-markdown/SKILL.md](../../.perk/skills/copy-docs-to-markdown/SKILL.md).

**Before**

````markdown
description: Mirror technical documentation from a website URL into a local directory of organized Markdown files (default docs/library/<name>/), preserving the site's section structure, rewriting internal links to local relative links, and generating an index.md entrypoint. Use when asked to copy or mirror docs locally, vendor a library's documentation into the repo, crawl a documentation site into Markdown, or build a local Markdown reference of an external doc set.
````

**After**

````markdown
description: "Mirror technical documentation from a website into local Markdown, defaulting to docs/library/<name>/. Use when copying, vendoring, or refreshing a documentation site locally; preserve its section structure, rewrite internal links, and create an index.md entrypoint."
````

One task branch covers the repeated copy/mirror/vendor/crawl phrases. Preserve the output contract and default destination. Basis: [research](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/research/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All surrounding instructions and frontmatter fields are unchanged.

#### P61 · Keep purpose, provenance, and routing in two sentences

Source: [.perk/skills/copy-docs-to-markdown/SKILL.md](../../.perk/skills/copy-docs-to-markdown/SKILL.md).

**Before**

````markdown
Create a local Markdown reference copy of technical documentation from a documentation URL, so
future agents can read it without network access. Keep the result readable: preserve the site
structure, retain source URLs, and write a practical `index.md` that explains where to look for
each topic.
````

**After**

````markdown
Create an offline Markdown reference. Preserve the site structure and source URLs, and make
`index.md` route readers to each topic.
````

The description already names the input and output. Retain the useful source-URL requirement and index’s job. Basis: [research](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/research/SKILL.md), [writing-for-agents](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/productivity/writing-for-agents/SKILL.md).

Preserve: All tooling, script commands, scope rules, page caps, destination, pruning, inspection, and reporting remain unchanged.

### pr-reviewer companion rubric

Only the existing judgment paragraphs below change. All frontmatter, tools, source lookup, context reads, wave behavior, angle ownership, findings fields, and posting/triage rules remain unchanged.

#### P62 · Align automated test review with the proposed testing judgment

Source: [agents/pr-reviewer.md](../../agents/pr-reviewer.md).

**Before**

````markdown
   - **tests** — *Tests & validation adequacy.* Is the **new behavior** actually covered, including
     its failure modes? Missing coverage for a real risk is a finding. Reason about tests — do not
     execute them.
````

**After**

````markdown
   - **tests** — *Tests & validation adequacy.* Does coverage exercise new behavior and failure
     modes through stable interfaces, with independent expected results? Internal tests are useful
     when they guard a concrete invariant. Missing coverage for a real risk is a finding.
     Reason about tests — do not execute them.
````

The reviewer must judge the same behavioral evidence the implementation skill asks for, without prohibiting internal invariant tests. Basis: [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md), [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md).

Preserve: Keep the tests angle, no-execution rule, binary finding bar, derived verdict, report schema, all tool/context reads, and metadata.

#### P63 · Distinguish a rule breach from design judgment

Source: [agents/pr-reviewer.md](../../agents/pr-reviewer.md).

**Before**

````markdown
   - **quality** — *Clarity, maintainability, naming & docs/contracts accuracy.* Review whether
     the changed code is understandable and maintainable, names communicate intent, and touched
     docs/contracts stay accurate. Standalone simplification/deletion findings belong to Ponytail.
````

**After**

````markdown
   - **quality** — *Clarity, maintainability, naming & docs/contracts accuracy.* Check clarity,
     names, and touched docs/contracts. Cite a documented rule when one applies; otherwise label
     the concern as design judgment and explain its consequence. Honor explicit local choices.
     Standalone simplification/deletion findings belong to Ponytail.
````

Borrow standards-versus-judgment discipline within the existing quality lane. A preference becomes reviewable when its consequence is explicit. Basis: [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md), [codebase-design](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/codebase-design/SKILL.md).

Preserve: No new angle, field, mandatory report template, posting bar, standards lookup, or change to Ponytail ownership.

### adversarial-reviewer companion rubric

Only the existing judgment paragraphs below change. All frontmatter, tools, source lookup, context reads, wave behavior, angle ownership, findings fields, and posting/triage rules remain unchanged.

#### P64 · Align human-triaged test review with the proposed testing judgment

Source: [agents/adversarial-reviewer.md](../../agents/adversarial-reviewer.md).

**Before**

````markdown
   - **tests** — *Tests & validation adequacy.* Is the **new behavior** actually covered,
     including its failure modes? Missing coverage for a real risk is a finding. Reason about
     tests only — never execute them (rule 3 stands).
````

**After**

````markdown
   - **tests** — *Tests & validation adequacy.* Does coverage exercise new behavior and failure
     modes through stable interfaces, with independent expected results? Internal tests are useful
     when they guard a concrete invariant. Missing coverage for a real risk is a finding.
     Reason about tests only — never execute them (rule 3 stands).
````

Use the same criterion in the other existing tests lane; keep its distinct human-attention bar. Basis: [tdd](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/tdd/SKILL.md), [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md).

Preserve: Keep severity/confidence, FYI, no verdict, blocked semantics, read-only posture, context reads, metadata, and all orchestration.

#### P65 · Apply the same rule-versus-judgment distinction in human review

Source: [agents/adversarial-reviewer.md](../../agents/adversarial-reviewer.md).

**Before**

````markdown
   - **quality** — *Clarity, maintainability, naming & docs accuracy.* Review whether changed
     code is understandable and maintainable, names communicate intent, and touched docs stay
     accurate. Standalone simplification/deletion findings belong to Ponytail.
````

**After**

````markdown
   - **quality** — *Clarity, maintainability, naming & docs accuracy.* Check clarity, names,
     and touched docs. Cite a documented rule when one applies; otherwise label the concern as
     design judgment and explain its consequence. Honor explicit local choices.
     Standalone simplification/deletion findings belong to Ponytail.
````

Keep the concern intelligible to the human without adding a structured category or demanding certainty for low-confidence findings. Basis: [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md), [codebase-design](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/codebase-design/SKILL.md).

Preserve: All existing severity/confidence, triage, anchors, FYI, ownership, and report rules remain unchanged.

### draft-reviewer companion rubric

Only the existing judgment paragraphs below change. All frontmatter, tools, source lookup, context reads, wave behavior, angle ownership, findings fields, and posting/triage rules remain unchanged.

#### P66 · Make draft criticism explain its basis

Source: [agents/draft-reviewer.md](../../agents/draft-reviewer.md).

**Before**

````markdown
   2. **What does it get wrong?** Concrete defects along your angle — ordinary findings.
````

**After**

````markdown
   2. **What does it get wrong?** For defects along your angle, cite the violated requirement
      or documented rule; for design judgment, say so and explain the consequence.
````

The existing four-question rubric is the right home for the distinction. Keep uncertain-but-useful findings eligible under its current bar. Basis: [code-review](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/code-review/SKILL.md), [to-spec](https://github.com/mattpocock/skills/blob/74ca5fe077456a0b3b2f5310cf9430999fd0b5fd/skills/engineering/to-spec/SKILL.md).

Preserve: No change to angles, findings fields, severity/confidence, phrase anchoring, human triage, tool posture, metadata, or Ponytail.

## Projected size

Counts compare complete original files with complete hypothetical files after all proposals compose. Words are whitespace-separated tokens, including frontmatter, Markdown syntax, and code; bytes are UTF-8 file bytes. They are not model-token estimates. Signed changes are `after − before`. No text is moved into a new file or omitted from the collection total to manufacture a saving.

| Skill | Entrypoint words | Δ words | All skill Markdown words | All skill Markdown bytes |
| --- | --- | --- | --- | --- |
| [perk-plan](#perk-plan) | 1,330 → 1,189 | −141 | 1,330 → 1,189 | 8,679 → 7,791 |
| [perk-implement](#perk-implement) | 178 → 212 | +34 | 343 → 377 | 2,128 → 2,388 |
| [perk-address](#perk-address) | 447 → 462 | +15 | 447 → 462 | 3,126 → 3,254 |
| [perk-domain-modeling](#perk-domain-modeling) | 749 → 606 | −143 | 1,087 → 944 | 7,234 → 6,385 |
| [perk-grill](#perk-grill) | 380 → 358 | −22 | 380 → 358 | 2,486 → 2,333 |
| [perk-gist-author](#perk-gist-author) | 797 → 712 | −85 | 797 → 712 | 5,231 → 4,713 |
| [perk-objective-author](#perk-objective-author) | 881 → 868 | −13 | 881 → 868 | 6,063 → 5,984 |
| [perk-objective-plan](#perk-objective-plan) | 1,373 → 1,334 | −39 | 1,373 → 1,334 | 9,726 → 9,471 |
| [perk-objective-refine](#perk-objective-refine) | 879 → 809 | −70 | 879 → 809 | 5,880 → 5,535 |
| [perk-replan](#perk-replan) | 559 → 494 | −65 | 559 → 494 | 3,786 → 3,351 |
| [perk-objective-replan](#perk-objective-replan) | 777 → 760 | −17 | 777 → 760 | 5,632 → 5,514 |
| [perk-objective-reconcile](#perk-objective-reconcile) | 1,296 → 1,221 | −75 | 1,296 → 1,221 | 9,101 → 8,593 |
| [perk-learn](#perk-learn) | 1,044 → 1,019 | −25 | 1,184 → 1,159 | 8,314 → 8,162 |
| [perk-learn-code](#perk-learn-code) | 515 → 451 | −64 | 515 → 451 | 3,400 → 3,070 |
| [perk-learn-docs](#perk-learn-docs) | 1,137 → 1,119 | −18 | 1,137 → 1,119 | 7,872 → 7,751 |
| [perk-learn-dream](#perk-learn-dream) | 813 → 797 | −16 | 813 → 797 | 5,610 → 5,524 |
| [perk-learn-harvest](#perk-learn-harvest) | 928 → 900 | −28 | 928 → 900 | 6,326 → 6,173 |
| [perk-pr-review](#perk-pr-review) | 1,764 → 1,716 | −48 | 1,764 → 1,716 | 12,867 → 12,574 |
| [perk-pr-review-browser](#perk-pr-review-browser) | 2,020 → 2,007 | −13 | 2,020 → 2,007 | 14,130 → 14,041 |
| [perk-pr-review-terminal](#perk-pr-review-terminal) | 1,781 → 1,774 | −7 | 1,781 → 1,774 | 12,038 → 11,981 |
| [perk-plan-review-browser](#perk-plan-review-browser) | 1,123 → 1,111 | −12 | 1,123 → 1,111 | 8,017 → 7,941 |
| [perk-objective-review-browser](#perk-objective-review-browser) | 1,167 → 1,154 | −13 | 1,167 → 1,154 | 8,422 → 8,331 |
| [perk-skill-author](#perk-skill-author) | 1,019 → 981 | −38 | 1,019 → 981 | 6,696 → 6,509 |
| [perk-expert](#perk-expert) | 757 → 659 | −98 | 16,856 → 16,758 | 121,999 → 121,317 |
| [dignified-typescript](#dignified-typescript) | 938 → 906 | −32 | 9,019 → 9,008 | 64,830 → 64,747 |
| [dignified-pydantic](#dignified-pydantic) | 616 → 439 | −177 | 5,596 → 5,419 | 47,703 → 46,481 |
| [copy-docs-to-markdown](#copy-docs-to-markdown) | 430 → 371 | −59 | 430 → 371 | 3,116 → 2,760 |

The “All skill Markdown” columns include the entrypoint and every existing Markdown reference/backend file in that skill directory. No executable helpers are changed or counted as prose.

| Collection | Words | Δ words | UTF-8 bytes | Δ bytes |
| --- | --- | --- | --- | --- |
| 27 entrypoints | 25,698 → 24,429 | −1,269 | 178,473 → 170,587 | −7,886 |
| All 49 Markdown files in the 27 skill directories | 55,501 → 54,253 | −1,248 | 400,412 → 392,674 | −7,738 |
| Three companion reviewer files | 6,331 → 6,397 | +66 | 44,950 → 45,400 | +450 |
| Skills plus companion reviewers | 61,832 → 60,650 | −1,182 | 445,362 → 438,074 | −7,288 |

| Companion file | Words | Δ words | UTF-8 bytes | Δ bytes |
| --- | --- | --- | --- | --- |
| [agents/pr-reviewer.md](../../agents/pr-reviewer.md) | 2,397 → 2,423 | +26 | 17,226 → 17,406 | +180 |
| [agents/adversarial-reviewer.md](../../agents/adversarial-reviewer.md) | 2,331 → 2,358 | +27 | 16,265 → 16,449 | +184 |
| [agents/draft-reviewer.md](../../agents/draft-reviewer.md) | 1,603 → 1,616 | +13 | 11,459 → 11,545 | +86 |

The entrypoints shrink by **1,269 words (4.9%)**. Counting all skill references, the reduction is **1,248 words**; counting companion reviewers too, it is **1,182 words**. Only two skill entrypoints grow: perk-implement by 34 words and perk-address by 15, both for the agreed verification/debugging judgment. The testing reference grows by 21 words; the three reviewer files grow by 66 words together. These additions are included in every applicable total.

The table deliberately includes retained reference manuals and backend recipes. The proposal document itself is excluded: it is a review artifact, not skill content delivered to an agent. Reviewer files are reported separately because they are companion prompts, not skills. These projections assume every proposal is accepted; selecting a subset changes the totals.

## Validation and implementation notes

The proposal set contains **66 exact edits across 31 prospective files**: 27 skill entrypoints, one existing testing reference, and three reviewer definitions. Validation performed while authoring this document:

- Checked every Before span against the pinned checkout: exactly one occurrence, with no overlapping edits. Composed complete hypothetical files in memory; the source skills were never overwritten.
- Verified all 38 upstream entrypoint paths, all 27 owned targets, and every relative file link in this document. Pinned upstream links resolve to paths present in the local audited clone; no network freshness claim is made.
- Parsed all 27 hypothetical skill frontmatters with perk’s existing parser. Names, stages, invocation flags, reference declarations, and all other fields match the originals; only descriptions differ. All three reviewer frontmatters remain byte-identical.
- Checked **43 protected body spans byte-for-byte**, including complete bodies for the seven description-only skills; plan save/review and scout guidance; objective claiming/paging; refinement context and save boundaries; learning schemas/routing; review posting and report contracts; and technical reference-load rules.
- Ran **15 existing targeted checks** against an in-memory read overlay of the hypothetical skills: all of [test_skill_semantic_contracts.py](../../tests/test_skill_semantic_contracts.py), the description-budget check in [test_prompt_surface_budgets.py](../../tests/test_prompt_surface_budgets.py), and the skill-semantic checks in [test_learn_harvest_cmd.py](../../tests/test_learn_harvest_cmd.py) and [test_learn_dream_cmd.py](../../tests/test_learn_dream_cmd.py). All passed. Worker parallelism was disabled so the overlay was actually used; reads of all 24 shipped perk skills were confirmed. This is candidate-prose verification, not a full CI run or an agent-behavior test.
- The longest parsed hypothetical shipped-perk description is **242 UTF-8 bytes**, within the existing **896-byte** ceiling. No ceiling reset or semantic-pin edit is needed for these checked passages.
- Reconciled complete-file word/byte totals, including unchanged supporting Markdown and the companion increases. No hypothetical skill files are committed with the report.

The exact-span, metadata, and protected-section checks establish editorial consistency, not that prose cannot affect agent behavior. The new judgment criteria are the intended behavioral influence. Reviewer-rubric wording is not validated by the skill semantic pins; its schema and execution constraints are preserved explicitly, and its interpretation is covered by the walkthroughs below.

The following scenario walkthroughs check the intended reading of the proposals. They are editorial checks, not empirical model evaluations:

| Scenario | Expected interpretation after the proposals |
| --- | --- |
| A plan names a function to change and records historical research line numbers | The function is a valid action anchor; line numbers remain permitted only in research notes. |
| An objective spans a user-visible feature and an expand/contract migration | A verifiable slice is available as a technique; the migration may use another decomposition. No mandatory slicing scheme or new delivery default. |
| An advisory refinement depends on a future node | Name the missing prerequisite and assumption; do not invent certainty or treat capture-time HEAD as a frozen guarantee. |
| A test asserts an internal queue ordering invariant | It is legitimate when that ordering protects a concrete invariant; the new guidance does not ban internal tests. |
| Expected output is calculated by calling the same helper being tested | Reviewers can identify the circular evidence and ask for an independently justified expected result. |
| A bug occurs only against unavailable production data | Try to reproduce where possible, test the explanation with available evidence, and disclose that the original case could not be confirmed. |
| Review feedback asks for another approach on a plan-only PR | Revise the plan text. The code-bug instruction does not authorize implementation. Preview still stops after classification. |
| A reviewer dislikes an interface that follows an explicit local decision | Explain a concrete consequence as design judgment; do not present preference as a rule violation. Existing finding and posting bars still apply. |
| A learning merely retells the session | Seek the evidence-backed future action it changes; the existing earned-SKIP path remains valid. No extra report field. |
| An inbox learning needs a larger change than first suggested | Verify its home and resolve the actual bounded scope in the plan; do not hand an open scope decision to implementation. |
| A dream proposal would retire a doc without both required endorsements | The unchanged evidence bar prevents that disposition. Shorter descriptions do not weaken the body. |
| Harvest surfaces attractive but unsupported simplification | The unchanged pointer/claim/confidence checks and ranking still decide eligibility and selection. Consequence clarifies evidence, not a new score. |
| A consuming repo asks about a provider or local model override | Read the existing relevant perk-expert reference before answering; repo-local operator docs are not substituted. |
| A reviewer needs execution evidence or encounters a missing input | Existing parent-owned execution evidence, FYI, blocked-lane, and incomplete-coverage rules still govern; none are revised here. |

For a later implementation, apply the exact spans in source directories and make the matching reviewer-rubric edits together with testing/review judgment changes. Recheck against the then-current source if the baseline has moved. Keep the existing description ceiling and semantic tests; do not relax tests to conceal a changed contract. Run the repository’s required checks for the actual skill change at that time. No change to `shared/contracts.md`, user docs, configuration, or delivery artifacts is proposed, because the behavior and machinery they specify remain fixed.

## Deliberate non-adoptions

- No upstream plan/spec/ticket/ADR/handoff locations, tracker schemas, labels, commit rules, integration branches, or session-clearing conventions.
- No replacement of perk’s waves with code-review’s two-agent arrangement, generic background research, or a new router. Preserve all Pi subagent instructions, model lookup, failure/fallback behavior, and ownership.
- No strict TDD ritual, pre-approved test seams, blanket prohibition on internal tests, or deferral of all refactoring until review.
- No mandatory six-phase debugger, automatic instrumentation, new redaction process, or prescribed tool sequence.
- No wholesale deep-module scaffolding, export-layout mandate, smell catalog, assertion library, new hook, or toolchain migration.
- No compulsory tracer bullets, blanket ban on file paths in plans, or long user-story catalog.
- No change to the learning pipeline, no new standards stored only in review, and no replacement of full-corpus dream with sampled architecture exploration.
- No broad rewrite of strong, detailed reference manuals merely to meet a shrink target. Preserve their useful local exceptions and branch-specific reads.
- No technical-policy change to Pydantic or TypeScript inferred from a superficially related upstream skill. The local skills’ runtime and repository precedence remains authoritative.
- No inference that shorter prompts improve model behavior by a quantified amount. The measured result here is less prose with explicitly retained constraints; actual behavior would need evaluation after adoption.
