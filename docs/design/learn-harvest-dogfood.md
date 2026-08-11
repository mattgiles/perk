# Dogfood: `perk learn harvest` through its direct and wave paths

## Status and scope

**Status:** validation record (the `*-dogfood.md` genre) for the shipped `perk learn harvest`
objective factory — one bounded live acceptance gate per route, run before this node's first
`/submit`:

- **Direct leg** — a file-scoped, single-lane invocation
  (`--from docs/learned/workflow/learn-harvest.md`) whose parent session analyzes the lane
  directly, with **zero** `run_harvest_wave` calls.
- **Wave leg** — an unscoped, full-corpus invocation whose parent session makes **exactly one**
  `run_harvest_wave` call over the multi-lane manifest (the real `pi-subagents` RPC wave, first
  exercised live here).

**Overall verdict:** `<pending — filled from Part B's deterministic aggregation>`.

Every valid saved objective from either leg is **retained as real backlog** (overlap disclosed,
never deduplicated). Part A is the repeatable procedure; Part B is the dated captured evidence.

**Explicit non-goals of this gate:** the guarded pre-gather sync (`--no-sync` is deliberate on
both legs — the sync boundary is already offline-pinned), forced/synthetic failures (every
degradation arm is capture-if-fired only), a warm `/learn-harvest` door (deferred by the
objective), cross-run dedupe of harvested objectives, learned-corpus cleanup, and
omitted-count deepening re-runs (`omitted_count > 0` is recorded with the lane's exact doc
paths and a recommendation only — no third invocation).

## Part A — the repeatable procedure

Two actors run this protocol:

- **The staging shell** — a non-interactive shell rooted at the implementation worktree. It owns
  the capture directory, the preflight, the baselines/census, the independent inventory, the
  evidence projections, and the cleanup. It never runs a harvest command.
- **Fresh interactive harvest sessions** — each harvest invocation (`direct-1`, `wave-1`, and
  any permitted rerun `direct-2`/`wave-2`) is a **fresh interactive Pi session** started by the
  operator in a separate terminal, `cd`'d to the same implementation worktree at the recorded
  clean HEAD. `--json` on this door is launch observability, not a terminal harvest result, so
  the dogfood commands stay interactive.

### 1. Scaffold, private capture root, and preflight

Commit this record's Part A + empty Part B and the provisional `docs/index.md` row **before any
live launch** (no `/submit` yet). In the staging shell, create the only ad hoc capture root — a
mode-0700 OS temporary directory, never a repo path:

```bash
CAPTURE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/perk-learn-harvest-dogfood.XXXXXX")
chmod 700 "$CAPTURE_ROOT"
trap 'rm -rf -- "$CAPTURE_ROOT"' EXIT HUP INT TERM
printf '%s\n' "$CAPTURE_ROOT"
```

(When the staging shell is a per-command tool shell rather than one long-lived process, skip the
`trap` — it would fire at the end of the creating command — and guarantee the explicit teardown
deletion in step 8 instead.)

Never copy `.perk/local.toml` or a complete Pi parent JSONL into this directory: parent JSONL is
queried in place and only the minimized event projection (step 5) is written here. Product
manifests remain at their minted `.perk/workflow/scratch/runs/<run_id>/harvest-manifest.json`
paths (normal run-scratch GC).

Install the lockfile-current dependencies, then capture versions and run the two focused
offline pins:

```bash
uv sync --all-packages
npm ci
npm ci --prefix .pi/npm

uv run perk --version > "$CAPTURE_ROOT/perk-version.txt"
pi --version > "$CAPTURE_ROOT/pi-version.txt"
node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" \
  > "$CAPTURE_ROOT/pi-subagents-version.txt"
uv run pytest tests/test_learn_harvest_cmd.py tests/test_learn_harvest.py \
  > "$CAPTURE_ROOT/python-focused.txt"
node --test extension/doors/harvestWaveTools.test.ts extension/waves/harvestWave.test.ts \
  > "$CAPTURE_ROOT/typescript-focused.txt"
```

Capture the effective analyst model without exposing local overlay bytes — this helper is the
only process allowed to read `.perk/local.toml`, and it emits only the resolved model id, a
source label, the fallback ids, a presence bit, and SHA-256 fingerprints:

```bash
uv run python - "$CAPTURE_ROOT/model-config.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

import yaml

from perk.substrate.config import load_config

root = Path.cwd().resolve()
agent_path = root / "agents" / "harvest-analyst.md"
frontmatter = yaml.safe_load(agent_path.read_text(encoding="utf-8").split("---", 2)[1])
override = load_config(root).subagents.get("harvest-analyst")
primary = override or frontmatter["model"]
local = root / ".perk" / "local.toml"
payload = {
    "effective_harvest_analyst": primary,
    "model_source": "resolved models.subagents.harvest-analyst" if override else "agents/harvest-analyst.md frontmatter",
    "fallback_models": frontmatter.get("fallbackModels", []),
    "committed_config_sha256": hashlib.sha256((root / ".perk" / "config.toml").read_bytes()).hexdigest(),
    "local_config_present": local.is_file(),
    "local_config_sha256": hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
```

Require the installed orchestration surfaces and supervisor bridge to be explicitly clean.
`subagent-compat` is report-only (`info` when absent, `warn` on surface divergence), so process
exit status is insufficient — both selected rows must be **present** and `status == "ok"`:

```bash
uv run perk doctor --json > "$CAPTURE_ROOT/doctor.json"
jq -e '
  [.checks[] | select(.name == "subagent-compat" or .name == "subagent-bridge-config")] as $rows |
  ($rows | length) == 2 and all($rows[]; .status == "ok")
' "$CAPTURE_ROOT/doctor.json"
```

Finally require that the exact resolved primary model is catalogued and can complete a
credentialed call:

```bash
MODEL=$(jq -r '.effective_harvest_analyst' "$CAPTURE_ROOT/model-config.json")
pi --list-models "${MODEL%%:*}" > "$CAPTURE_ROOT/model-list.txt"
PI_SKIP_VERSION_CHECK=1 pi --no-session --no-tools --model "$MODEL" -p 'Reply exactly READY.' \
  > "$CAPTURE_ROOT/model-smoke.txt"
test "$(tr -d '\r\n' < "$CAPTURE_ROOT/model-smoke.txt")" = "READY"
```

Any dependency install failure, focused-pin failure, missing/non-`ok` doctor row, unresolved
model, or failed credential smoke **blocks launch and consumes no attempt budget**: repair an
environment-only problem and rerun the entire preflight. A product test failure follows the
strict-fix/successor rule (step 6) before any live attempt; a nontrivial blocker yields a
bounded FAIL record plus successor rather than spending a harvest attempt on a known-bad
environment.

After preflight, record the clean initial revision and baselines:

```bash
git status --short > "$CAPTURE_ROOT/git-status.initial.txt"
test ! -s "$CAPTURE_ROOT/git-status.initial.txt"
git rev-parse --abbrev-ref HEAD > "$CAPTURE_ROOT/branch.initial.txt"
git rev-parse HEAD > "$CAPTURE_ROOT/head.initial.txt"
git worktree list --porcelain > "$CAPTURE_ROOT/worktrees.before.txt"
git ls-remote --heads origin | sort > "$CAPTURE_ROOT/remote-heads.before.txt"
gh pr list --state open --limit 1000 --json number,headRefName,baseRefName,url,title \
  | jq 'sort_by(.number)' > "$CAPTURE_ROOT/prs.before.json"
gh issue list --state all --label perk:objective --limit 1000 --json number,url \
  | jq 'sort_by(.number)' > "$CAPTURE_ROOT/objectives.before.json"
```

**Both initial legs must use this same clean HEAD.** No repository edit occurs between them. If
an initial attempt exposes a defect, log it but finish the other initial leg from the same
revision unless continuing would create a security/data-loss risk; that exceptional skip is a
FAIL for the unrun leg and requires a successor.

### 2. Independently enumerate the eligible corpus

Before the full-corpus attempt — and again before any full-corpus rerun at a new HEAD — produce
an implementation-independent inventory from filesystem rules (never by reading the manifest or
calling `resolve_harvest_docs`/`partition_lanes`). No doc count is an invariant: each attempt
gets a fresh inventory, and the live manifest is compared to it.

```bash
uv run python - "$CAPTURE_ROOT/full-selection.json" <<'PY'
import json
import sys
from collections import defaultdict
from pathlib import Path

root = Path.cwd().resolve()
learned_source = root / "docs" / "learned"
learned = learned_source.resolve()
if not learned.is_relative_to(root):
    raise SystemExit("docs/learned escapes the repository")
rows = []
for path in learned_source.glob("**/*.md"):
    if not path.is_file() or path == learned_source / "index.md":
        continue
    if not path.resolve().is_relative_to(learned):
        continue
    relative = path.relative_to(learned_source)
    category = relative.parent.as_posix()
    rows.append((category, path.stem, path.relative_to(root).as_posix()))
rows.sort(key=lambda row: (row[0], row[1]))
groups = defaultdict(list)
for category, _slug, path in rows:
    group = "root" if category == "." else category.split("/", 1)[0]
    groups[group].append(path)
lanes = []
for group in sorted(groups):
    docs = sorted(groups[group])
    for offset in range(0, len(docs), 8):
        lanes.append({"id": f"{group}-{offset // 8 + 1}", "docs": docs[offset:offset + 8]})
payload = {"eligible_docs": [row[2] for row in rows], "lanes": lanes}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
```

The record carries the inventory's SHA-256, eligible count, ordered lane ids, and per-lane
paths/counts — never a hard-coded planning snapshot.

### 3. The direct leg (fresh interactive session)

From a separate terminal at the same clean initial HEAD, the operator runs exactly:

```bash
uv run perk learn harvest --no-sync --from docs/learned/workflow/learn-harvest.md
```

This invocation is `direct-1` and consumes the direct leg's initial attempt **at invocation**.
Use Pi `/session` before leaving the parent session to record its session id and absolute JSONL
path; record the harvest run id and manifest path from the seeded launch. Never copy the full
JSONL.

Validate the direct manifest against the literal selection:

```bash
HEAD=$(cat "$CAPTURE_ROOT/head.initial.txt")
jq -e --arg head "$HEAD" '
  .schema_version == "1" and
  .commit_sha == $head and
  ([.lanes[].id] == ["workflow-1"]) and
  ([.lanes[].docs[].path] == ["docs/learned/workflow/learn-harvest.md"])
' "$DIRECT_MANIFEST"
```

The parent must read the selected learned doc and ground candidate source pointers itself, make
**zero** `run_harvest_wave` calls, and reach one valid terminal:

- **saved objective:** drive every viable draft through review. DENIED review is revised in the
  same session (no new attempt). APPROVED review auto-saves; only an unavailable/dismissed
  review surface permits the artifact-first `/objective-save` failsafe. Record the issue URL/id
  and `uv run perk objective show <id> --json`. Keep it open as backlog.
- **zero opportunity:** preserve the parent's evidence report (doc inspected, pointers checked,
  rejection reasons) and stop with **zero** `objective_draft`/`plan_review`/`objective_save`
  calls and no new objective carrying this harvest run id.

An explicit human abandonment/rejection of an otherwise viable objective is an **operator
interruption**, not incomplete harvest: it consumes the current attempt and follows the bounded
rerun table (step 6).

### 4. The full-corpus wave leg (second fresh interactive session)

Without editing the repository, the operator runs exactly:

```bash
uv run perk learn harvest --no-sync
```

This invocation is `wave-1` and consumes the wave leg's initial attempt at invocation. Record
`/session`, the harvest run id, and the manifest path. Validate the manifest against both the
initial HEAD and the independent inventory:

```bash
HEAD=$(cat "$CAPTURE_ROOT/head.initial.txt")
jq -e --arg head "$HEAD" --slurpfile expected "$CAPTURE_ROOT/full-selection.json" '
  .schema_version == "1" and
  .commit_sha == $head and
  ([.lanes[] | {id, docs: [.docs[].path]}] == $expected[0].lanes) and
  (.lanes | length) > 1
' "$WAVE_MANIFEST"
```

The parent calls `run_harvest_wave` **exactly once** with `manifest_path` equal to
`realpath "$WAVE_MANIFEST"`. It never retries the wave or an individual lane. Preserve the
single result's `message.content[].text` and `message.details.{reports,skipped,attempts}`.
Verify:

- `attempts | length == 1`, `attempts[0].attempt == 1`, and `attempts[0].requestedKeys`
  byte-equals the manifest's ordered lane ids;
- the observed children reconcile by receipt `key`, `agent`, `runId`, `success`,
  `outputState`, and `artifactPaths` — without assuming every requested lane spawned;
- on a completed wave, each requested key is represented once by a valid report or a `skipped`
  row; on a wave-level failure, the attempt receipt and failure reason remain explicit;
- every `omitted_count > 0` is recorded with that lane's exact manifest doc paths and a
  recommendation only — no third/deepening run;
- ≥ 1 valid report plus skipped lanes yields partial coverage; zero valid reports or a typed
  wave-level failure, correctly surfaced by the parent as incomplete harvest, yields
  degradation.

For each receipt-listed child, read only the receipt's `_meta.json` and `_transcript.jsonl`
paths long enough to create a redacted summary — receipt key/run id; `_meta` fields `agent`,
`exitCode`, `model`, `attemptedModels`, `modelAttempts`, `error`, `timestamp`; transcript
first/last timestamps; assistant `model`/`stopReason`/normalized `usage`; and
`structured_output` `tool_start`/`tool_end.isError`. Never commit prompts, full model text, or
raw transcripts. A suitable exact projection per child:

```bash
jq '{runId,agent,exitCode,model,attemptedModels,modelAttempts,error,transcriptPath,timestamp}' "$META"
jq -s '{
  first_timestamp: .[0].timestamp,
  last_timestamp: .[-1].timestamp,
  assistant_messages: [.[] | select(.recordType == "message" and .role == "assistant") |
    {timestamp,model,stopReason,usage}],
  structured_output: [.[] | select((.recordType == "tool_start" or .recordType == "tool_end") and
    .toolName == "structured_output") | {recordType,timestamp,toolCallId,isError}]
}' "$TRANSCRIPT"
```

Every candidate admitted to a roadmap must have a **parent** `read`/`grep` call after the wave
tool result and before the first `objective_draft`; child reads never satisfy this. Unresolved
child pointers may enter a roadmap only if that later parent reread resolves them. Drive the
parent to saved objective, zero opportunity, partial-coverage saved/zero, or the specified
incomplete-harvest stop. Saved objectives follow the direct leg's persist-through-review rule
and remain open even if they overlap the direct result — disclose overlap, never deduplicate.

### 5. One pinned parent-session event projection for both legs

Pi session JSONL v3 stores assistant tool calls in `message.content[]` blocks
(`{type:"toolCall", id, name, arguments}`) and tool results as `message.role == "toolResult"`
rows (`toolCallId`, `toolName`, `content[]`, `details`, `isError`) — the pinned source for
route, save-gesture, and pointer-reread claims. For each parent session, point `SESSION_FILE`
at the `/session` path and create this minimized ordered projection in the capture root:

```bash
jq -s '[
  to_entries[] |
  .key as $line |
  .value as $entry |
  select($entry.type == "message") |
  if $entry.message.role == "assistant" then
    $entry.message.content[]? |
    select(.type == "toolCall") |
    . as $call |
    {
      jsonl_line: ($line + 1), entry_id: $entry.id, timestamp: $entry.timestamp,
      kind: "tool_call", tool_call_id: $call.id, name: $call.name,
      arguments: (if ($call.name == "read" or $call.name == "grep" or
        $call.name == "find" or $call.name == "run_harvest_wave")
        then $call.arguments else null end)
    }
  elif $entry.message.role == "toolResult" then
    {
      jsonl_line: ($line + 1), entry_id: $entry.id, timestamp: $entry.timestamp,
      kind: "tool_result", tool_call_id: $entry.message.toolCallId,
      name: $entry.message.toolName, is_error: $entry.message.isError,
      content: $entry.message.content, details: $entry.message.details
    }
  else empty end
]' "$SESSION_FILE" > "$CAPTURE_ROOT/$LEG-events.json"
```

**The fact-to-source matrix.** Part B fills the evidence column; redaction is mandatory before
commit.

| Fact | Pinned source / command | Required match | Durable/redaction rule |
|---|---|---|---|
| Clean bytes exercised | `git status --short`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD` immediately before each invocation | status empty; manifest `commit_sha` equals that HEAD | Commit branch/SHA/status only |
| Dependencies and versions | the three install commands; `uv run perk --version`; `pi --version`; package `node -p` above | installs and focused pins pass; versions parse | Commit versions and pass/fail, not install logs |
| Orchestration readiness | `perk doctor --json` selected by exact `checks[].name` | exactly two selected rows, both `ok` | Commit those two rows only |
| Analyst credential | safe model helper, `pi --list-models`, no-session `READY` smoke | resolved primary listed and exact smoke succeeds | Commit effective model/source, fallback ids, fingerprints, and `READY`; never local bytes/credentials |
| Full eligible corpus | independent Python inventory above | full manifest lane ids/paths byte-equal inventory; index excluded; lane count >1 | Commit hash/count/lane table |
| Direct routing | direct manifest + parent event projection | literal one doc/`workflow-1`; zero wave calls | Commit manifest excerpt and count |
| Wave invocation | parent tool-call projection | total `run_harvest_wave` call count exactly 1 and argument realpath-equals manifest | Commit call id/line/time/path relative to repo |
| Wave result/coverage | matching parent tool-result `content`/`details` | one attempt; requested keys equal manifest; report/skip reconciliation follows result arm | Commit typed attempt/report/skip summary; redact prose to decisive failure excerpts |
| No lane retry | same call/result | one parent wave call and `attempts == [{attempt:1,…}]` | Commit counts/receipt id |
| Parent pointer reread | ordered `read`/`grep` call plus successful matching tool result | file portion equals `read.path`, or `grep.path` scopes it and `grep.pattern` names the symbol; for wave, line is after wave result; all are before first draft | One row per admitted pointer: pointer, JSONL line/call id, arguments, result success, decision; concise source excerpt only |
| Save/no-save | event projection plus run-id issue query | saved: draft/review or failsafe gesture and exactly the returned objective; no-save: zero draft/review/save calls and no objective attributable to run id | Commit tool names/ids and objective URL or explicit zero; never unsaved draft prose |
| Run-id objective lookup | `gh issue list --state all --label perk:objective --search "$RUN_ID in:body" --limit 100 --json number,url` plus pre/post census | saved run resolves to retained issue; no-save run resolves empty and creates no census delta attributable to it | Commit ids/URLs only |
| Child execution | receipt `attempts[].children[].artifactPaths`, projected `_meta` and transcript records | observed lane/run/model/output state reconcile; structured-output success/failure and usage are explicit | Commit redacted summary only; delete every exact receipt path later |
| No branch/PR/worktree side effect | pre/post `git worktree list --porcelain`, `git ls-remote --heads origin`, and `gh pr list…` | exact equality in a quiet repo; any delta is investigated and attributed | Commit hashes/ids for deltas only; unrelated concurrent changes are named, not misattributed |
| No raw residue staged | `git diff --cached --name-only`; cleanup checks below | no `.perk/`/`.pi-subagents/` capture path staged; temp root and receipt paths absent | Commit command result, not ignored-file contents |

For tool counts, use exact event-projection predicates. Direct requires
`[.[] | select(.kind=="tool_call" and .name=="run_harvest_wave")] | length == 0`; wave requires
length `== 1`, and the sole call's `arguments.manifest_path` must equal the manifest realpath.
A zero/incomplete terminal requires zero tool calls named `objective_draft`, `plan_review`, or
`objective_save`; the run-id issue query and pre/post objective census are the independent
backstop for a slash-command save.

For pointer evidence, the record's table — not a narrative assertion — is authoritative. A
`find` call may locate a path but never satisfies reread by itself. Cite the successful
`read`/`grep` tool result paired by `tool_call_id`. For the wave leg, `jsonl_line` must be
greater than the `run_harvest_wave` result line. For every saved roadmap, the grounding line
must precede the first `objective_draft` line that contains that roadmap.

### 6. The bounded attempt/fix state machine

Each exact harvest command invocation consumes one attempt **as soon as it is invoked**, even
if the CLI or parent later fails. Each leg has attempt 1 plus at most one fresh-session
attempt 2. Preflight retries consume no harvest attempts. Continued review/revision inside the
same parent session is not a rerun. Restarting after a code/prompt change is a rerun, never a
free reload. Child lanes never retry.

| Observed outcome | Classification and precedence | Action | Budget effect |
|---|---|---|---|
| Preflight/install/doctor/model smoke fails before command invocation | environment blocker unless a focused pin proves a product defect | correct environment and rerun all preflight; strict-trivial product fix only under rule below, otherwise FAIL + successor | none |
| Parent/CLI/session ends without a product-defined terminal because of transport loss, terminal closure, explicit operator abort, or model call failure before a typed wave result | external/operator interruption, if evidence confirms it | log D-row; if attempt 2 remains, start one fresh session from a clean recorded HEAD; otherwise leg FAIL | consumes current attempt |
| Wave returns typed details with ≥1 valid report and skipped lanes, and parent completes curation | product-defined partial coverage, even if a skipped lane cites provider failure | terminal `PARTIAL_COVERAGE`; disclose skipped lanes; no rerun | consumes current attempt; closes leg |
| Wave returns a typed wave failure or zero valid reports and parent follows the prescribed incomplete stop | product-defined degradation; takes precedence over reinterpreting child/provider reasons as a retryable interruption because the route itself completed | terminal `DEGRADATION`; log underlying D-row/successor if warranted; no rerun | consumes current attempt; closes leg |
| Viable objective review is DENIED | review continuation, not terminal and not interruption | revise in the same session until approval; failsafe only when review is unavailable | no additional attempt |
| Human explicitly abandons/rejects a viable objective, or review/save cannot complete for a confirmed external reason | operator interruption | one fresh rerun if available; otherwise leg FAIL | consumes current attempt |
| Demonstrated strict-trivial product defect and every leg invalidated by the fix still has attempt 2 available | fixable in node | after both initial legs, add owning regression, commit fix/test, require clean status, record new HEAD, rerun every invalidated leg in a fresh session; manifests must carry new SHA | each rerun consumes attempt 2 |
| Strict-trivial candidate exists but any invalidated leg has already spent attempt 2 | unverifiable within ceiling | do not land the fix in this node; record FAIL and create successor for fix + re-verification | no third attempt |
| Nontrivial defect or protocol/evidence violation | product FAIL | do not broaden scope or rerun hoping it disappears; create successor and land bounded FAIL record | no extra attempt |
| Attempt 2 is interrupted, violates protocol, or still exhibits the defect | exhausted | leg FAIL; successor for product cause, explicit external residual otherwise | no third attempt |

**The strict-trivial boundary.** A fix is strict-trivial only if all conditions hold:

- one D-row demonstrates it;
- it changes either non-executing docs/prose, or one localized implementation module plus its
  existing owning focused regression;
- any executing prompt/skill prose change also updates an existing owning pin in the same
  commit; if no such pin exists, it is a successor, not a live-tuned fix;
- it introduces no cross-plane behavior, contract/schema/config/provider/backend/routing
  change, public behavior decision, new abstraction, or multi-module design;
- the complete fix and focused test are committed before rerun, `git status --short` is empty,
  and the rerun record captures branch/new HEAD. Dirty fixes are forbidden — a manifest SHA
  would not identify the bytes exercised.

Record targeted test output before rerun. A TypeScript change requires a newly started Pi
session so changed extension code is loaded; by definition all reruns are fresh sessions, so
Python/prompt changes also get a clean parent. If one fix affects both routes, both must have
unused attempt 2 before taking it, and both are rerun from the same clean fix commit.

**The successor rule.** Anything else becomes one pending Phase 3 successor per demonstrated
root cause before `/submit`:

```bash
uv run perk objective node-add 1538 --phase 3 --depends-on 3.1 \
  --description "<bounded remediation and re-verification>" \
  --comment "learn-harvest dogfood D<n>; docs/design/learn-harvest-dogfood.md" --json
```

One successor may cover multiple D-rows only when the record demonstrates one shared root
cause. Verify with `uv run perk objective show 1538 --json` and map returned node ids back to
every D-row. A nontrivial true protocol failure lands as FAIL plus successor; it never expands
this node. The docs-only gate admits no `docs/learned/`, user-doc, `shared/contracts.md`,
config, or CHANGELOG edit — a fix needing any of those behavior/contract surfaces is
nontrivial here and becomes a successor.

### 7. Deterministic verdict aggregation

Keep every attempt row, including superseded attempts. For each leg, the authoritative terminal
is attempt 1 if no rerun occurred, otherwise attempt 2. A defect-bearing attempt 1 followed by
a successful committed-fix rerun is not erased: its D-row remains, but the leg is
`PASS AFTER RERUN` (or the corresponding coverage variant), not FAIL.

| Condition at authoritative terminal | Base grade | Terminal kind |
|---|---|---|
| Required protocol/evidence complete; saved objective or grounded zero-opportunity; no skipped coverage | `PASS` | `SAVED_OBJECTIVE` or `ZERO_OPPORTUNITY` |
| Wave has ≥1 valid report and ≥1 skipped lane, then reaches saved/zero terminal with disclosure | `PARTIAL_COVERAGE` | `SAVED_OBJECTIVE` or `ZERO_OPPORTUNITY` |
| Typed wave failure or zero-valid-report arm is faithfully surfaced as incomplete | `DEGRADATION` | `INCOMPLETE_HARVEST` |
| Missing evidence, protocol violation, abandoned viable draft after budget, nontrivial failure, or exhausted retry | `FAIL` | `FAILURE` |

Add modifier `AFTER_RERUN` when attempt 2 is authoritative. Render leg/overall labels exactly
as one of: `PASS` · `PASS AFTER RERUN` · `PASS WITH PARTIAL COVERAGE` ·
`PASS AFTER RERUN WITH PARTIAL COVERAGE` · `PASS WITH DEGRADATION` ·
`PASS AFTER RERUN WITH DEGRADATION` · `FAIL`.

Compute the overall base grade as the worse of the two authoritative leg grades under strict
precedence `FAIL > DEGRADATION > PARTIAL_COVERAGE > PASS`; add `AFTER_RERUN` to a non-FAIL
overall label if either authoritative leg is attempt 2. Saved versus zero-opportunity is a
terminal-kind column, not a severity input. `docs/index.md` uses this exact overall label.

### 8. Finalize, successors, cleanup, submit

After both legs and any permitted reruns:

1. Fill Part B (attempt matrix, pointer table, D-log, retained-objective list, pre/post
   census). Run:
   ```bash
   git worktree list --porcelain > "$CAPTURE_ROOT/worktrees.after.txt"
   git ls-remote --heads origin | sort > "$CAPTURE_ROOT/remote-heads.after.txt"
   gh pr list --state open --limit 1000 --json number,headRefName,baseRefName,url,title \
     | jq 'sort_by(.number)' > "$CAPTURE_ROOT/prs.after.json"
   gh issue list --state all --label perk:objective --limit 1000 --json number,url \
     | jq 'sort_by(.number)' > "$CAPTURE_ROOT/objectives.after.json"
   ```
   Worktree/head/PR equality is expected. Investigate any delta: a harvest-created
   branch/PR/worktree is FAIL; an independently attributable concurrent change is named
   without being misclassified. The objective delta must equal the intentionally retained
   saved outputs plus any independently attributable concurrent objective.
2. Create/verify required successors, update D-rows, and commit the redacted decisive evidence
   and final index result **before deleting raw evidence**. Never commit full session/model
   prose, local config, or raw child artifacts.
3. Extract every receipt-listed child artifact path from the wave tool-result details, validate
   that it resolves under this worktree's `.pi-subagents/artifacts/`, and delete every listed
   path (raw child artifacts are NOT managed by perk's run-scratch GC). Never glob-delete
   unrelated runs. Then remove the capture root:
   ```bash
   ARTIFACT_ROOT=$(realpath .pi-subagents/artifacts)
   while IFS= read -r artifact; do
     resolved=$(realpath "$artifact")
     case "$resolved" in
       "$ARTIFACT_ROOT"/*) rm -f -- "$resolved" ;;
       *) printf 'refusing non-artifact path: %s\n' "$artifact" >&2; exit 1 ;;
     esac
   done < "$RECEIPT_ARTIFACT_PATHS"
   rm -rf -- "$CAPTURE_ROOT"
   trap - EXIT HUP INT TERM
   test ! -e "$CAPTURE_ROOT"
   ```
   `RECEIPT_ARTIFACT_PATHS` is generated from the matching tool result's
   `details.attempts[].children[].artifactPaths` values, sorted unique. Save the list's
   hash/count in the record before deleting the list itself. If a receipt path is missing,
   record that fact rather than broadening deletion.
4. Add the cleanup attestations to the record and commit them. Verify
   `git diff --cached --name-only` contains no `.perk/` or `.pi-subagents/` path and each
   receipt path is absent. Standard Pi parent session files remain in Pi's normal session
   history (no duplicate full transcript is created); run-scratch manifests remain only in
   their real `scratch/runs/<run_id>` locations under normal perk GC.
5. Run targeted checks for any strict-trivial fix, then the repository's single run-all
   `run_ci` immediately before `/submit` (never bare `just ci`). Never submit the scaffold or
   an evidence-only intermediate commit early.

## Part B — dated evidence

### Run metadata

_Pending — UTC time, worktree/branch, every authoritative clean HEAD, versions, focused-pin
results, the two doctor rows, analyst-model resolution (effective id, source, fallbacks,
config fingerprints, local-overlay presence bit), model catalog + READY smoke, and the capture
root's location/mode/staging-shell actor note._

### Independent inventory (fresh, pre-wave, at the initial HEAD)

- `full-selection.json` SHA-256 `<pending>`; eligible count `<pending>`; lane count
  `<pending>`.

| Lane id | Docs |
|---|---|
| `<pending>` | `<pending>` |

### Attempt matrix

| Attempt | Leg | UTC | HEAD | Session id | Harvest run id | Outcome | Consumed budget |
|---|---|---|---|---|---|---|---|
| `direct-1` | direct | `<pending>` | `<pending>` | `<pending>` | `<pending>` | `<pending>` | attempt 1 |
| `wave-1` | wave | `<pending>` | `<pending>` | `<pending>` | `<pending>` | `<pending>` | attempt 1 |

### Direct leg evidence

_Pending — manifest excerpt, zero-wave-call predicate result, pointer-reread rows,
save/no-save proof, `perk objective show` output or zero-opportunity evidence._

### Wave leg evidence

_Pending — manifest-vs-inventory equality, the single wave call (call id/line/path), attempt
receipt, report/skip reconciliation, omitted_count disclosures, redacted child summaries,
post-wave pointer-reread rows, terminal outcome._

### Pointer-reread table

| Leg | Pointer | Grounding call (JSONL line / tool_call_id / tool) | Arguments | Result | First draft line | Decision |
|---|---|---|---|---|---|---|
| `<pending>` | | | | | | |

### Per-leg verdicts and the overall label

| Leg | Authoritative attempt | Base grade | Terminal kind | Modifier | Label |
|---|---|---|---|---|---|
| direct | `<pending>` | | | | |
| wave | `<pending>` | | | | |

**Overall:** `<pending>` (worse-of precedence `FAIL > DEGRADATION > PARTIAL_COVERAGE > PASS`).

## Defect/friction log

_Pending — D1, D2, … with observation, evidence, classification (perk defect /
environment-operator interruption / expected product outcome), affected legs, disposition,
focused regression/commit where applicable, rerun ids, and successor node id. No speculation
about fixes not taken._

## Honest residuals

_Pending — every capture-if-fired arm that did not occur live, each named with its offline
pin (`tests/test_learn_harvest_cmd.py`, `tests/test_learn_harvest.py`,
`extension/doors/harvestWaveTools.test.ts`, `extension/waves/harvestWave.test.ts`). Unobserved
live failure arms are never claimed as passed._

## Teardown/census

_Pending — pre/post worktree, remote-head, open-PR, and objective-issue comparison;
intentionally retained harvested objective ids; deletion attestation for the capture root and
every receipt-listed child artifact path; staged-diff attestation that no `.perk/` or
`.pi-subagents/` path was committed. Only the run manifests remain, in their real
`.perk/workflow/scratch/runs/<run_id>/` locations under normal run-scratch GC — neither the
custom capture root nor `.pi-subagents/artifacts` is GC-managed._
