# Dogfood: browser denial across an unrelated compaction change (v2 draft-review target)

**Status:** validation record for the routing-projection fix to the Plannotator draft-review
target fingerprint (contracts §8.23, `perk/draft-review-target/v2`). The offline suites prove the
projection and the composed decision paths against fake transport/backend ports; this record is
the one **live** browser-denial check the plan required — a fresh Pi session loading the changed
extension, the real Plannotator server, and a compaction-only `.perk/config.toml` edit landed
while the review was open. Recorded once (2026-09-08); the driver is a disposable scratch script,
not a shipped tool.

## Procedure (what was run)

- **Disposable repository** under `$TMPDIR` (`git init`, one commit): `.pi/settings.json`
  `packages` = the plan worktree's absolute path (the changed extension) + the locally installed
  `@plannotator/pi-extension`; `.perk/config.toml` =
  `[providers] plan = "plannotator-plan"` and `[compaction] reserve_tokens = 32768`.
- **Fresh session:** `pi --mode rpc --approve` in that repository with `PERK_RUN_ID` /
  `PI_SESSION_FILE` unset (the probe env-leak guard), `PLANNOTATOR_REMOTE=1` (the real server
  runs; no browser window is opened), `PLANNOTATOR_PORT=47311`. RPC mode is `hasUI = true`, so
  `plan_review` and the launch chooser run their interactive arms; `--approve` is required —
  non-interactive modes otherwise ignore an untrusted project's `.pi/settings.json` entirely
  (nothing loads, `/plan` reaches the model as text).
- **Review opened:** `/plan` (perk plan mode ON, read-only gate), then one model turn that called
  `plan_draft` (`# Dogfood plan …`) and `plan_review`; the chooser answered "Browser review only".
  The Plannotator server served `/api/plan`; `draft-review.json` read `{"state":"pending"}`.
- **The incident shape:** with the review pending, `reserve_tokens = 32768` → `65536` in the
  repository's `.perk/config.toml` (the only change; the draft untouched).
- **"Send feedback":** `POST http://localhost:47311/api/deny` with
  `{"feedback":"Tighten §2 — the rollout step is missing (dogfood denial)."}` — the browser UI's
  own denial endpoint (the button's request), not a fake bus.

## Observed result

- `plan_review` returned once: `details = {ok:true, status:"completed", approved:false,
  feedback:"Tighten §2 — …", reviewId, draft_review_dispatch}`; text
  `plan DENIED — revise per this feedback …` with the feedback verbatim inside the
  `<untrusted_reviewer_feedback>` delimiters. **No `target-changed`.**
- `draft-review.json` after the turn: `consumption.state = "consumed"`, `attempt.effect =
  "revision"`, `attempt.save = {"state":"not-required"}` (**zero saves**), delivery carrier
  `{kind:"tool", tool_call_id:<the real plan_review toolCallId>}`, and `delivery_entry_id`
  equal to the persisted `plan_review` tool-result entry's id (exact evidence, not the return).
- The draft bytes were unchanged at decision time (`source_digest` preserved on the consumed
  record); the model then revised the draft per the delivered feedback, as the denial text directs.
- The read-only gate stayed active: the session's final `perk:workflow-state` `mode` is
  `read-only`; no `perk plan save` subprocess ran and no plan-ref was recorded.
- Under the retired whole-file hash this exact sequence is the reported incident (a
  `target-changed` stop on "Send feedback"); under the v2 projection the compaction edit is
  invisible to the target.

## Observations outside the fix's path

- The model, following the denial text, immediately revised and called `plan_review` again; the
  driver terminated `pi` while that second launch chooser was open, and Pi reported one
  `extension_error` (`This extension ctx is stale after session replacement or reload`) on the
  `context` event during that teardown. Teardown-with-open-dialog is not part of the reviewed
  path and was not investigated here.
- The Plannotator server also archived the denial to `~/.plannotator/plans/…-denied.md` (its
  own feature; unrelated to perk's record).
