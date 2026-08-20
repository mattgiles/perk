# Dogfood: `perk learn dream` — the whole-corpus curation factory, live

## Status and scope

**Status:** validation record (the `*-dogfood.md` genre) for the shipped `perk learn dream`
curation factory — ONE bounded live acceptance gate, run before this node's first `/submit`:
the full-corpus dream audit at one stamped commit, driven end to end (origin preflight →
dirty-refusal probe → the live `dream-1` leg → the overlap-refusal probe when applicable →
census), with attempt 1 plus at most one fresh-session attempt 2 reserved for confirmed
external/interruption causes on unchanged product bytes.

**Overall verdict:** *(pending — filled by Part B)*

**The scope boundary (one rule, no exceptions).** This gate's in-node edits touch only
non-executing documentation prose. Any defect discovered in executing surfaces — production
code, the seed (`prompts/stages/learn-dream.md`), the `perk-learn-dream` skill, agent defs,
tool descriptions, schemas, config — is recorded as a D-row below and becomes a successor node
(`perk objective node-add 1892 --phase 5 --depends-on 5.2 …`), **never** an in-node fix. There
is no strict-trivial carve-out: attempt 2 exists only for confirmed external/interruption
causes on unchanged product bytes.

**Explicit non-goals of this gate:** the guarded pre-gather sync (`--no-sync` is deliberate —
the sync boundary is offline-pinned), forced/synthetic failures (every refusal arm beyond the
two designed probes is capture-if-fired only), a warm `/learn-dream` door (an objective
non-goal), executing the saved curation objective's roadmap, and the **Linear live proof**
(consciously deferred by reviewed decision to the named successor node — see
[the Linear live-proof successor](#the-linear-live-proof-successor) below).

**The contracts-coherence rider.** The node's planning-time ledger (10 topics over §8.24 +
§8.59–§8.65, cross-checked against the seed, the `perk-learn-dream` skill, and the CLI
reference) was re-verified against the tree at implementation HEAD in this pass: all 10 topics
coherent, **zero contract edits** — the only gaps were `origin` documentation coverage (user
docs + perk-expert mirror), closed by this node's docs pass.

Any valid saved curation objective from the live leg is **retained open as real backlog**
(disclosed: the origin guard then blocks future dreams until it completes — that is the
designed one-open-dream-objective behavior, not a defect).

## Part A — the repeatable procedure

Two actors run this protocol:

- **The staging shell** — a non-interactive shell rooted at the implementation worktree (this
  implement session's per-command bash tool). It owns the capture directory, the preflight,
  the pre-attempt origin sweep, the baselines/census, the independent inventory, the two
  refusal probes, the evidence projections, and the cleanup. It **never runs a dream**.
- **Fresh interactive dream sessions** — the live invocation (`dream-1`, and `dream-2` only if
  the rerun row permits) is a **fresh interactive Pi session** started by the operator in a
  separate terminal, `cd`'d to the same implementation worktree at the recorded clean HEAD.

### 1. Scaffold, private capture root, and preflight

Commit this record's Part A + empty Part B and the provisional `docs/index.md` row **before
any live launch** (no `/submit` yet). In the staging shell, create the only ad hoc capture
root — a mode-0700 OS temporary directory, never a repo path:

```bash
CAPTURE_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/perk-learn-dream-dogfood.XXXXXX")
chmod 700 "$CAPTURE_ROOT"
printf '%s\n' "$CAPTURE_ROOT"
```

(The staging shell is a per-command tool shell, not one long-lived process, so no `trap` — the
explicit teardown deletion in step 8 is the guaranteed cleanup.)

Never copy `.perk/local.toml` or a complete Pi parent JSONL into this directory: parent JSONL
is queried in place and only the minimized event projection (step 6) is written here. The
product manifest and analyst bundle remain at their minted
`.perk/workflow/scratch/runs/<run_id>/` paths (normal run-scratch GC).

Install the lockfile-current dependencies, capture versions, and run the focused offline pins:

```bash
uv sync --all-packages
npm ci
npm ci --prefix .pi/npm

uv run perk --version > "$CAPTURE_ROOT/perk-version.txt"
pi --version > "$CAPTURE_ROOT/pi-version.txt"
node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" \
  > "$CAPTURE_ROOT/pi-subagents-version.txt"

uv run pytest tests/test_learn_dream.py tests/test_learn_dream_cmd.py \
  tests/test_dream_companion.py tests/test_dream_companion_backends.py \
  tests/test_objective_dream_save_cmd.py tests/test_linear_project_store.py \
  tests/test_linear_objectives.py > "$CAPTURE_ROOT/python-focused.txt"
node --test extension/waves/dreamWave.test.ts extension/waves/dreamReducerWave.test.ts \
  extension/waves/dreamReport.test.ts extension/doors/dreamWaveTools.test.ts \
  extension/factories/objectiveDreamReport.test.ts \
  extension/factories/objectiveDraft.test.ts > "$CAPTURE_ROOT/typescript-focused.txt"
```

Require the installed orchestration surfaces and supervisor bridge to be explicitly clean —
both selected doctor rows must be **present** and `status == "ok"`:

```bash
uv run perk doctor --json > "$CAPTURE_ROOT/doctor.json"
jq -e '
  [.checks[] | select(.name == "subagent-compat" or .name == "subagent-bridge-config")] as $rows |
  ($rows | length) == 2 and all($rows[]; .status == "ok")
' "$CAPTURE_ROOT/doctor.json"
```

Capture the effective wave models without exposing local overlay bytes — the harvest record's
safe helper, extended to BOTH dream agents and BOTH `[models.subagents]` keys. This helper is
the only process allowed to read `.perk/local.toml`, and it emits only resolved model ids,
source labels, fallback ids, a presence bit, and SHA-256 fingerprints:

```bash
uv run python - "$CAPTURE_ROOT/model-config.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

import yaml

from perk.substrate.config import load_config

root = Path.cwd().resolve()
config = load_config(root)
payload: dict[str, object] = {}
for agent in ("dream-analyst", "dream-reducer"):
    agent_path = root / "agents" / f"{agent}.md"
    frontmatter = yaml.safe_load(agent_path.read_text(encoding="utf-8").split("---", 2)[1])
    override = config.subagents.get(agent)
    payload[agent] = {
        "effective_model": override or frontmatter["model"],
        "model_source": f"resolved models.subagents.{agent}" if override else f"agents/{agent}.md frontmatter",
        "fallback_models": frontmatter.get("fallbackModels", []),
    }
local = root / ".perk" / "local.toml"
payload["committed_config_sha256"] = hashlib.sha256((root / ".perk" / "config.toml").read_bytes()).hexdigest()
payload["local_config_present"] = local.is_file()
payload["local_config_sha256"] = hashlib.sha256(local.read_bytes()).hexdigest() if local.is_file() else None
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
```

Then require every distinct resolved primary model to be catalogued and able to complete one
credentialed call (one `READY` smoke per resolved model):

```bash
for MODEL in $(jq -r '[.["dream-analyst"].effective_model, .["dream-reducer"].effective_model] | unique[]' \
    "$CAPTURE_ROOT/model-config.json"); do
  pi --list-models "${MODEL%%:*}" >> "$CAPTURE_ROOT/model-list.txt"
  PI_SKIP_VERSION_CHECK=1 pi --no-session --no-tools --model "$MODEL" -p 'Reply exactly READY.' \
    > "$CAPTURE_ROOT/model-smoke-$(echo "$MODEL" | tr '/:' '--').txt"
  test "$(tr -d '\r\n' < "$CAPTURE_ROOT/model-smoke-$(echo "$MODEL" | tr '/:' '--').txt")" = "READY"
done
```

Any dependency install failure, focused-pin failure, missing/non-`ok` doctor row, unresolved
model, or failed credential smoke **blocks launch and consumes no attempt budget**: repair an
environment-only problem and rerun the entire preflight. A focused pin proving a product
defect follows the scope boundary — a D-row + successor node, never an in-node fix; the gate
records a bounded FAIL rather than spending a dream attempt on a known-bad product.

### 2. The pre-attempt origin preflight (blocked-state disposition)

Before attempt 1, the staging shell sweeps the open `perk:objective` census and inspects each
`objective-header` for `origin: learn-dream`:

```bash
gh issue list --state open --label perk:objective --limit 1000 --json number,body \
  | jq '[.[] | select(.body | test("origin: learn-dream")) | .number]' \
  > "$CAPTURE_ROOT/open-dream-objectives.json"
```

A live match ⇒ the gate is **BLOCKED, not failed, and no attempt is consumed**: record the
blocking objective; the disposition is non-destructive — the backlog objective is
completed/closed through ordinary work on its own merits, **never closed to unblock the
gate** — and the gate resumes afterwards. (Expected state at planning time: none exists.)

### 3. Baselines

Trimmed to what a dream can affect (no branch/PR/worktree surface exists on this read-only
factory path; the census is the save-side backstop):

```bash
git status --porcelain > "$CAPTURE_ROOT/git-status.initial.txt"
test ! -s "$CAPTURE_ROOT/git-status.initial.txt"
git rev-parse --abbrev-ref HEAD > "$CAPTURE_ROOT/branch.initial.txt"
git rev-parse HEAD > "$CAPTURE_ROOT/head.initial.txt"
gh issue list --state open --label perk:objective --limit 1000 --json number,url \
  | jq 'sort_by(.number)' > "$CAPTURE_ROOT/objectives.before.json"
```

The after-census (step 8) must differ from the before-census by exactly the intentionally
saved curation objective, or by nothing (an independently attributable concurrent objective is
named, never misattributed).

### 4. Independent corpus inventory

Before the attempt — and again fresh before any permitted rerun — produce an
implementation-independent recompute of the expected partition **from filesystem rules**
(never by calling the gather code): the tracked `docs/learned/**/*.md` set minus the generated
`index.md`, joined with the `docs/learned/clusters.yaml` registry order and each doc's
`cluster` frontmatter, path-sorted per cluster and chunked sequentially at 8 into
`<cluster>-<n>` lane ids:

```bash
uv run python - "$CAPTURE_ROOT/dream-inventory.json" <<'PY'
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml

root = Path.cwd().resolve()
tracked = subprocess.run(
    ["git", "ls-files", "docs/learned"], capture_output=True, text=True, check=True, timeout=30
).stdout.split()
docs = sorted(p for p in tracked if p.endswith(".md") and p != "docs/learned/index.md")
registry = yaml.safe_load((root / "docs" / "learned" / "clusters.yaml").read_text(encoding="utf-8"))
order = [cluster["id"] for cluster in registry["clusters"]]
members: dict[str, list[str]] = defaultdict(list)
for doc in docs:
    frontmatter = yaml.safe_load((root / doc).read_text(encoding="utf-8").split("---", 2)[1])
    members[frontmatter["cluster"]].append(doc)
lanes = []
for cluster_id in order:
    cluster_docs = sorted(members.get(cluster_id, []))
    for offset in range(0, len(cluster_docs), 8):
        lanes.append({"id": f"{cluster_id}-{offset // 8 + 1}", "docs": cluster_docs[offset : offset + 8]})
payload = {"doc_count": len(docs), "eligible_docs": docs, "lanes": lanes}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
```

The record carries the fresh recompute's SHA-256, doc count, ordered lane ids, and per-lane
counts — never a hard-coded planning snapshot. (Planning-time expectation, for orientation
only: 66 docs, 13 non-empty clusters, 14 lanes — `toolchain-gotchas` at 9 members splits into
two.) The live manifest must match the inventory: lane ids, per-lane doc paths, `commit_sha`
equal to the recorded initial HEAD, and the doc/byte counts internally consistent.

### 5. Live probe 1 — the dirty refusal (pre-leg, fully reverted)

One scratch untracked file must refuse the whole door (`--dry-run` runs the clean check too),
and its teardown must be proven:

```bash
touch dogfood-dirty-probe.txt
uv run perk learn dream --dry-run --json > "$CAPTURE_ROOT/probe1-dirty.json" || true
jq -e '.success == false and .error_type == "dirty_checkout"' "$CAPTURE_ROOT/probe1-dirty.json"
rm dogfood-dirty-probe.txt
git status --porcelain > "$CAPTURE_ROOT/probe1-teardown.txt"
test ! -s "$CAPTURE_ROOT/probe1-teardown.txt"
```

Probes never consume attempt budget.

### 6. The live leg (`dream-1`)

From a separate terminal at the recorded clean HEAD, the operator runs exactly:

```bash
uv run perk learn dream --no-sync
```

(`--no-sync` is the one-revision discipline; the guarded pre-gather sync boundary is
offline-pinned, not exercised here.) This invocation is `dream-1` and consumes the leg's
attempt **at invocation**. Use Pi `/session` before leaving the parent session to record its
session id and absolute JSONL path; record the dream run id and the manifest path from the
seeded launch. Never copy the full JSONL.

Validate the manifest against the recorded HEAD and the independent inventory:

```bash
HEAD=$(cat "$CAPTURE_ROOT/head.initial.txt")
jq -e --arg head "$HEAD" --slurpfile expected "$CAPTURE_ROOT/dream-inventory.json" '
  .schema_version == "1" and
  .commit_sha == $head and
  .registry_mode == "clusters" and
  .doc_count == $expected[0].doc_count and
  ([.lanes[] | {id, docs: [.docs[].path]}] == $expected[0].lanes)
' "$DREAM_MANIFEST"
```

In-session expectations: exactly **ONE** `run_dream_wave` call (no retry, no direct corpus
read); the review-first loop; on an actionable audit — the reviewed curation objective +
`dream_report` saved as ONE bundle (a DENIED review is revised in the same session; the
`/objective-save` failsafe only if the review surface is unavailable). The three honest
terminals and their handling are the state-machine table below. A saved objective is
**retained open as real backlog** (disclosed: the origin guard then blocks future dreams until
it completes).

**The parent-session event projection** (the harvest record's pinned Pi JSONL-v3 shape —
assistant `message.content[]` `toolCall` blocks; `toolResult` rows with
`toolCallId`/`toolName`/`content`/`details`/`isError`) is the pinned source for the wave-call
count, its typed aggregate result, and the draft/review/save gestures. Point `SESSION_FILE` at
the `/session` path:

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
        $call.name == "find" or $call.name == "run_dream_wave")
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
]' "$SESSION_FILE" > "$CAPTURE_ROOT/dream-events.json"
```

Exact predicates: `[.[] | select(.kind=="tool_call" and .name=="run_dream_wave")] | length`
must be `1`; a clean-audit or incomplete terminal requires zero tool calls named
`objective_draft`, `plan_review`, or `objective_save` — with the run-id issue search and the
pre/post census as the independent save/no-save backstop:

```bash
gh issue list --state all --label perk:objective --search "$RUN_ID in:body" \
  --limit 100 --json number,url > "$CAPTURE_ROOT/run-id-lookup.json"
```

### 7. Live probe 2 — the overlap refusal (only on the `SAVED_OBJECTIVE` terminal)

When and only when `dream-1` saved an objective, one more invocation from the staging shell
must refuse at the pre-launch origin guard — naming the just-saved objective, with no session,
no spend, and no attempt consumed (a probe, not an attempt):

```bash
uv run perk learn dream --json > "$CAPTURE_ROOT/probe2-overlap.json" || true
jq -e '.success == false and .error_type == "origin_conflict"' "$CAPTURE_ROOT/probe2-overlap.json"
```

On a `CLEAN_AUDIT` terminal this probe is inapplicable (no open dream objective exists to
conflict with); the overlap criterion is then recorded as offline-pinned, not observed live.

### 8. Evidence, census, cleanup, attestations

**Evidence is product-artifact-first — no child-transcript mining pipeline exists in this
gate.** The committed evidence set:

- the minimized parent event projection (step 6) — tool calls/results, the one
  `run_dream_wave` call + its typed aggregate (`complete`, `analysis`, `bracket`, `bundle`,
  `reducers`, `attempts`), and the draft/review/save gestures;
- the run-scoped manifest (validated against HEAD + the inventory);
- the finalized `dream-analyses.json` — presence of the `reducers` section + `manifest_digest`
  (the finalized shape, not the analyses-only mid-wave shape);
- on a save: the saved objective via `gh issue view <id>` / `perk objective show <id> --json` —
  header `origin: learn-dream` + `dream_report`, the roadmap (≤ 12 distinct nodes), and the
  marker-keyed companion comments (`perk:learn-dream-report:<run_id>:<part>`) as persisted;
- the run-id issue search (step 6) as the independent save/no-save backstop;
- the pre/post open-objective census delta.

Raw pi-subagents child artifacts are neither mined nor committed; the only cleanup obligation
they carry here is the no-staged-residue check below. Redaction is mandatory before commit:
versions and pass/fail (never install logs), the two doctor rows only, resolved model
ids/sources/fingerprints and `READY` (never local bytes/credentials), decisive failure
excerpts only (never full model prose), ids/URLs only for the census.

Close the pass:

```bash
gh issue list --state open --label perk:objective --limit 1000 --json number,url \
  | jq 'sort_by(.number)' > "$CAPTURE_ROOT/objectives.after.json"
git status --porcelain > "$CAPTURE_ROOT/git-status.final.txt"
```

Fill Part B, create/verify the required successor node(s), and commit the redacted decisive
evidence **before deleting the capture root**. Then:

```bash
rm -rf -- "$CAPTURE_ROOT"
test ! -e "$CAPTURE_ROOT"
git diff --cached --name-only | grep -E '^\.(perk|pi-subagents)/' && exit 1 || true
```

The attestations recorded in Part B: capture root deleted; no `.perk/` or `.pi-subagents/`
path ever staged. The run-scoped manifest and analyst bundle remain at their real
`scratch/runs/<run_id>/` locations under normal perk GC; the parent session remains in Pi's
normal session history (no duplicate transcript is created anywhere).

### The dream attempt/outcome state machine (complete, dream-specific)

Each real `perk learn dream` invocation of the live leg consumes one attempt **at invocation**
(probes and `--dry-run` never do). Attempt 1 plus at most one fresh-session attempt 2.

| Observed outcome | Classification | Action | Budget |
|---|---|---|---|
| Preflight/install/doctor/model-smoke failure before invocation | environment blocker | repair; rerun the whole preflight | none |
| Pre-attempt origin sweep finds an open learn-dream objective | gate BLOCKED | record it; resume the gate after it completes naturally (never close backlog to unblock) | none |
| Session/transport loss, terminal closure, explicit operator abort, or a confirmed provider/model outage before a product terminal | external interruption | `dream-2`: one fresh session at the recorded clean HEAD (product bytes unchanged; a docs-only HEAD delta from this PR's own commits is permitted and disclosed) | consumes the attempt |
| `INCOMPLETE_AUDIT` (any `run_dream_wave` failure or drift, faithfully surfaced) with a confirmed **external** cause | external interruption | `dream-2` as above | consumes the attempt |
| `INCOMPLETE_AUDIT` with a **product** cause (or an unattributable cause) | product FAIL | D-row + successor node; no in-node fix, no third attempt | consumes the attempt; closes the gate |
| `CLEAN_AUDIT` (complete waves, nothing selected, zero draft/review/save calls, no run-id-attributable objective) | valid honest terminal | close the gate | consumes the attempt; closes the gate |
| `SAVED_OBJECTIVE` (approved bundle auto-saved) | valid honest terminal | run live probe 2; close the gate | consumes the attempt; closes the gate |
| DENIED review on a viable draft | in-session continuation | revise in the same session; the `/objective-save` failsafe only if the review surface is unavailable | none |
| Human abandons a viable draft | operator interruption | `dream-2` if available, else FAIL | consumes the attempt |
| `dream-2` interrupted or incomplete again | exhausted | FAIL (+ successor for any product cause) | closes the gate |

### Per-terminal verdicts and the acceptance-criteria evidence map

Base grades: `SAVED_OBJECTIVE` → **PASS** · `CLEAN_AUDIT` → **PASS** (with the save-chain
criteria explicitly offline-pinned per the map below) · authoritative
`INCOMPLETE_AUDIT`/exhausted → **FAIL** (the honest surfacing itself is recorded as live
evidence for the incomplete-rule behavior, but the gate's criteria are unproven). Modifier
`AFTER RERUN` when `dream-2` is authoritative. `docs/index.md` carries the exact overall
label.

Every criterion is classified in Part B as **observed live** · **not fired → offline-pinned**
(exact test cited) · **unobserved, not passed**. The per-terminal map:

| Criterion | `SAVED_OBJECTIVE` | `CLEAN_AUDIT` |
|---|---|---|
| full-corpus audit at one stamped commit | live (manifest vs inventory + HEAD) | live (same) |
| dirty refusal | live probe 1 | live probe 1 |
| overlap (`origin_conflict`) refusal | live probe 2 | offline-pinned (`tests/test_learn_dream_cmd.py` guard arms + the store-tier lookup pins in `tests/test_linear_project_store.py` / GitHub store tests) — recorded as not observed live |
| stale-bracket refusal | offline-pinned (`extension/substrate/git.test.ts` `revalidationBracket` pins; `extension/doors/dreamWaveTools.test.ts` post-wave no-finalize arm; `extension/factories/objectiveDreamReport.test.ts` drifted-`bad_state` pins) | same |
| ≤8-doc semantic lanes | live (manifest) | live (manifest) |
| three reducers with stances | live (finalized `dream-analyses.json`) | live (same) |
| incomplete-lane refusal | offline-pinned (strict-completeness pins in `extension/waves/dreamWave.test.ts` / `extension/waves/dreamReducerWave.test.ts` / `extension/doors/dreamWaveTools.test.ts`) | same |
| one disposition per doc | live (report rows) + `extension/waves/dreamReport.test.ts` pins | live (the session's reported dispositions) |
| evidence-bar enforcement | live if a destructive proposal fires (stances + any downgrade recorded); else offline-pinned (`dreamReport.test.ts` destructive-eligibility pins) | offline-pinned |
| ≤12-node roadmap | live (saved roadmap) | offline-pinned (`dreamReport.test.ts` cap pins) |
| durable overflow + harvest follow-ups | live (report sections; either may be honestly empty) | offline-pinned |
| atomic objective+report review | live (one approval bundle; companion comments + `dream_report` header) | offline-pinned (`extension/factories/objectiveDreamReport.test.ts` + `tests/test_objective_dream_save_cmd.py`) |
| GitHub/Linear origin + companion equivalence | GitHub live; Linear **offline parity** — `tests/test_linear_project_store.py` + `tests/test_linear_objectives.py` (origin lookup/stamp/carry) and `tests/test_dream_companion_backends.py` + `tests/parity/dream_report_invariance.json` (companion + invariance) — recorded as *flagged not-live-proven* with the successor below | same |
| honest no-action outcome | unobserved, not passed (prompt/skill-defined judgment; the harvest zero-opportunity precedent) | **observed live** |
| byte-identical legacy behavior | offline-pinned — `tests/test_objective_dream_save_cmd.py` (cold-door side), `extension/factories/objectiveDraft.test.ts` "core: absence byte-identity" (draft side), `extension/factories/objectiveSave.test.ts` (save side) | same |

`INCOMPLETE_AUDIT`: probe 1 (and probe 2 only if a prior open dream objective existed —
inapplicable at today's expected state) still report; all other criteria are unproven → FAIL
per the grade rule.

### The Linear live-proof successor

The Linear live proof staged into this gate by node 4.3 is **consciously deferred** (a
reviewed user decision recorded in this node's plan). To keep the objective honest,
implementation creates ONE successor node before submit:

```bash
uv run perk objective node-add 1892 --phase 5 --depends-on 5.2 --description "Linear live-proof gate for dream origin + companion: drive the §8.64 save arm live against a Linear workspace — origin stamped at create, sentinel companion parts, upload_file + Resources link, dream_report header, idempotent retry convergence, and the live origin guard (origin_conflict) — the live proof staged out of node 5.2 by reviewed decision (docs/design/learn-dream-dogfood.md)."
```

The residuals section and the equivalence acceptance row both name the created successor node
id in Part B.

## Part B — dated evidence

*(empty — filled after the live gate; committed before any raw-evidence deletion)*

### Run metadata

*(pending)*

### Pre-attempt origin preflight

*(pending)*

### Independent inventory

*(pending)*

### Probe 1 — dirty refusal

*(pending)*

### Attempt matrix

*(pending)*

### Live-leg evidence

*(pending)*

### Probe 2 — overlap refusal

*(pending)*

### Acceptance-criteria classification

*(pending)*

### Verdict

*(pending)*

### Defect/friction log

*(pending)*

### Honest residuals

*(pending)*

### Teardown/census attestations

*(pending)*
