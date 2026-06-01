# Phase 1 · Turn 5 — PR lifecycle (`/submit`, `/land` + `/learn`, `perk resume`)

> Detailed, implementation-level plan for **P1.T5**. Grounded in
> [phase-1-plan.md](../phase-1-plan.md) (the T5 section), [cli-vs-pi.md](../cli-vs-pi.md)
> (§2.3 hand-off, §3.2 supervisor surface, §4.1 door legality), the T2a write conventions
> (`perk/github.py` — REST `gh api`, body-via-file, `run_id` idempotency, `GitHubError →
> UserFacingCliError`), the metadata-block engine (`perk/plan.py` — `PlanHeader` with **staged**
> `branch`/`pr`, `render`/`find_metadata_block`), the T3 warm-door delegation pattern
> (`extension/planSave.ts` + `perk/cli/commands/plan_save_cmd.py`), the T4 plan-ref-aware launcher
> (`perk/launch.py` `resolve_plan_worktree_name`/`launch_stage`), the markers semaphore
> (`perk/cache.py` `set_marker`/`has_marker`/`clear_marker`), and the erk prior-art
> ([pr-submit-phases](../../.prior-art/erk/docs/learned/pr-operations/pr-submit-phases.md),
> [lifecycle](../../.prior-art/erk/docs/learned/planning/lifecycle.md) — the staged-field
> population table + the `pending-learn`/branch→issue linking semantics).
>
> **Scope discipline.** T5 closes `implement → submit → land → learn` and adds the one genuinely-new
> CLI verb. It is **three independent seams** landed in order:
> - **T5a — `/submit`:** push the branch, open a **draft** PR linking the plan (`Closes #N`), and
>   populate the staged `branch`/`pr` header fields. A Python worker (`perk pr-submit`) does the
>   deterministic write; the warm door delegates to it (T3 pattern).
> - **T5b — `/land` + `/learn`:** `/land` marks the PR ready (if draft), squash-merges it (closing
>   the plan issue), and sets the `pending-learn` marker (Python worker `perk pr-land`); `/learn` is
>   a **thin** TS-only `pending-learn` clear (no GitHub write) that releases the worktree.
> - **T5c — `perk resume <plan>`:** read a plan from GitHub, reconstruct `cache.plan-ref`, derive its
>   current stage, and launch it (reusing `launch_stage`). The generalization of T4a's idempotent
>   reuse to an explicit plan id.
>
> It does **not**: craft AI PR titles/bodies or embed the full plan markdown in the PR (Phase 2),
> implement `pr check` / Graphite / the draft→ready *review* nuance beyond the minimal mark-ready,
> build the review/`address` loop or feedback classification (Phase 2), do reconciliation typing or
> deep learn tooling / a `perk:learn` label (Phase 2), handle the no-changes PR scenario (Phase 2),
> or recreate a `reuse`-stage worktree from a remote branch on a fresh clone (Phase 2 — `resume`
> assumes a local worktree for `submit`/`land`/`learn`; `implement` is idempotent so it works fresh).

---

## 1. Objective & the gate

**Close `implement → submit → land → learn`** and ship **`perk resume`** so any plan can be picked
up at its current stage. After this turn, perk can drive a change all the way from a saved plan to a
merged-and-learned PR — the substrate the **P1.T6 dogfood gate** ("perk ships perk") runs on.

Three verify gates run **fully offline** (no `pi` model turn, no network — `gh` is faked via a
`PERK_GH`-style stub or exercised only through `--dry-run`):

**`scripts/verify-p1-t5a.sh` (submit):**
1. `perk pr-submit --dry-run` (in a worktree with an active `cache.plan-ref`) composes the PR
   create + header-update plan and exits 0 — no `git push`, no `gh`.
2. `--json --dry-run` emits one well-formed `{ success, pr, plan_header, dry_run: true }` object.
3. Exit-code discipline: no plan-ref → 1 (`no_plan_ref`); not-a-repo → 2.
4. The registry `submit` stage I/O is filled and the self-check holds.

**`scripts/verify-p1-t5b.sh` (land + learn):**
5. `perk pr-land --dry-run` composes the mark-ready + squash-merge plan and exits 0; `--json`
   well-formed; the `pending-learn` marker is **not** set on a dry run.
6. The TS live suite passes offline: `/land` (faked worker) sets `pending-learn`; `/learn` clears it
   (idempotent); the registry `land`/`learn` I/O is filled.

**`scripts/verify-p1-t5c.sh` (resume):**
7. `perk resume <N> --dry-run` (faked `get_plan`) resolves the **current stage** from the plan
   header + PR state + `pending-learn`, reconstructs the plan-ref, and prints the launch plan; the
   stage-resolution matrix (planned→implement, impl+open→submit, merged+pending-learn→learn) holds.
8. No such plan → 1 (`plan_not_found`); not-a-repo → 2.

`just verify` runs t1…t7 + p1-t1…p1-t4b + **p1-t5a + p1-t5b + p1-t5c**; `just ci` stays green.

---

## 2. Grounding & doc lineage (what governs T5)

- **[phase-1-plan.md](../phase-1-plan.md) T5:** three thin handlers + the resume verb, cohesive at
  build time (all thin GitHub ops + marker moves), separated only at runtime by review/CI. T5a
  reuses T2a's write conventions; T5b's `/land` sets the `pending-learn` semaphore and `/learn`
  clears it; T5c is completable here because by T5 every stage exists. Defer body craft, `pr check`,
  draft→ready nuance, reconciliation typing, and deep learn tooling to Phase 2.
- **[cli-vs-pi.md](../cli-vs-pi.md) §3.2 (supervisor surface):** the cold worker commands keep
  `--json` to stdout + stable exit codes + `{success, error_type, message}`. §4.1 (door legality):
  `submit`/`land`/`learn` are `warm: true` — real warm doors (unlike `implement`).
- **[contracts.md](../../shared/contracts.md) §8.4:** the mutation ops `create_pr` / `mark_pr_ready`
  / `merge_pr` / `update_plan_header` are **named-only** today ("authoring ahead is fiction"); T5
  authors their payloads as built. The plan-header's `branch`/`pr` are **staged null until submit**
  (PRIOR_ART §2 + the lifecycle field-population table).
- **T2a (`perk/github.py`):** the write conventions T5 reuses verbatim — REST `gh api` over
  porcelain (porcelain's GraphQL hits a separate, often-exhausted rate-limit quota), large bodies
  via `-F body=@<file>`, idempotency via the **list** endpoint (not the eventually-consistent search
  index) with create/find-then-return, mutations **raise** `GitHubError` and lookups return
  `… | None`.
- **T3 (`extension/planSave.ts`):** the warm-door shape T5 mirrors — a terminating tool + a
  `/command` twin over one `savePlan()`-style core that **delegates** the GitHub write to a Python
  worker via `pi.exec(perkBin, [...,"--json"], {cwd, signal})`, guards `res.killed || res.code !==
  0`, wraps `JSON.parse`, and never throws (failures route through `reportError` + a soft
  `details.ok=false`).
- **T4a (`perk/launch.py`):** `resolve_plan_worktree_name(plan_ref) → plan-<pr_id>` and
  `launch_stage(...)` (idempotent worktree, materialize ref + handoff, `exec pi`) — `resume` reuses
  both unchanged.

---

## 3. Decisions (locked with the user before writing)

**D1 — GitHub mutations are canonical in the *Python* gateway; the TS warm doors *delegate* via
`pi.exec`.** The §8.4 "two gh gateways, same shapes" was a Phase-0 hypothesis; **T3 already deviated**
(plan-save delegates), and this turn confirms delegation as the **standing pattern**: extend
`perk/github.py` with the PR ops; the warm doors call thin Python workers. Cache/session tiers keep
their per-plane I/O (`cache.ts`/`cache.py`); **GitHub mutation logic lives once** (Python, tested via
`CliRunner`), the TS plane orchestrates. Amend §8.4 to record this. Wins: reuse T2a's tested
idempotency/error conventions, a **headless cold path** for the Phase-3 supervisor, DRY. Cost: a
subprocess per mutation — negligible.

**D2 — `submit` = push + draft PR + header populate; minimal body.** The PR is opened **draft**
(matches the plan + erk; review happens before land). The body is Phase-1-minimal: a `Closes #<issue>`
keyword (so squash-merge closes the plan issue) + a `Plan: #<issue>` link + a **plain-text** checkout
footer (`` `gh pr checkout <n>` `` — erk's tripwire: HTML `<details>` breaks footer validation).
**No full-plan re-embedding** (it is one click away in the issue) — Phase-2 deepening. After the PR
exists, `update_plan_header` populates `branch=plan-<pr_id>`, `pr=<number>`, `lifecycle_stage=impl`.

**D3 — `land` = mark-ready-if-draft + squash-merge + set `pending-learn`.** The squash merge carries
`Closes #<issue>` so the plan issue closes; the post-merge state is **derived from PR**, never stored
(Q8). Idempotent: an already-merged PR is success. `mark_pr_ready` is the **one** op with no REST
endpoint — it uses `gh pr ready` (GraphQL); everything else is REST `gh api` (D1/T2a convention).

**D4 — `learn` is thin: a TS-only `pending-learn` clear.** No GitHub write, no Python worker this
phase. `/learn` clears the marker (`extension/cache.ts` `clearMarker`), closing the land→learn cycle
so the worktree is releasable. The launcher `perk learn` still execs `pi` for an interactive capture
session that ends by clearing the marker; the agentic capture + a `perk:learn` label/issue is Phase 2.

**D5 — `perk resume <plan>` reads GitHub → reconstructs the ref → derives the stage → launches.** It
fetches the plan issue (new read op `github.get_plan`), reads the plan-header + PR state +
`pending-learn`, reconstructs `cache.plan-ref`, writes it to the repo root, derives the **current
actionable stage**, and calls `launch_stage(stage=resolved)` (reusing T4a). The minimal state machine:

| Observed                                            | Resume at   |
| --------------------------------------------------- | ----------- |
| `lifecycle_stage: planned`, no `pr` in header       | `implement` |
| `lifecycle_stage: impl`, PR open (not merged)        | `submit`    |
| PR merged + `pending-learn` marker present          | `learn`     |
| PR merged, no `pending-learn`                        | (done — informative exit 0, nothing to resume) |

`resume` **launches** (execs `pi`, like `implement`); `--dry-run`/`--json` print the resolved stage +
launch plan (the test seam). For `create` stages (`implement`) it works on a fresh clone (idempotent);
for `reuse` stages (`submit`/`land`/`learn`) it requires the **local** worktree and errors clearly if
absent (recreating from a remote branch is Phase 2).

**D6 — worker command names: `perk pr-submit` / `perk pr-land`** (parallels `perk plan-save`; avoids
colliding with the registry-generated launchers `perk submit`/`perk land`). `learn` has no worker.

**D7 — `update_plan_header(issue, fields)`** reads the issue body, merges `fields` into the parsed
`plan-header` block (`plan.find_metadata_block`), re-renders it (`plan.render_metadata_block`), and
PATCHes the issue body via REST (`gh api repos/{o}/{r}/issues/{n} -X PATCH -F body=@file`). Unknown
keys raise (LBYL on the header schema). Reuses the metadata-block engine — no new parser.

**D8 — registry I/O (as built, filled per seam):**
- `submit`: `requires: [cache.plan-ref]` · `reads: [cache.plan-ref, github.plan]` ·
  `writes: [github.pr, github.plan]` (PR + header; no session append — GitHub is the source of truth,
  `/land` re-discovers the PR by branch).
- `land`: `requires: [github.pr]` · `reads: [cache.plan-ref, github.pr]` ·
  `writes: [github.pr, cache.markers]`.
- `learn`: `requires: [cache.markers]` · `reads: [cache.markers]` · `writes: [cache.markers]`.
- `doors` unchanged (all `warm: true, cold_local: true, cold_remote: false`).

**D9 — seam order T5a → T5b → T5c.** Submit before land (you merge what you opened); resume last (it
resolves into every stage, so all must exist). One turn doc, three verify gates, three outcomes
sub-sections.

**D10 — no live spike needed.** Every mechanic is a port of a proven pattern: gh REST writes (T2a),
warm-door `pi.exec` delegation (T3), `launch_stage` (T4a), the markers semaphore (Phase-0 `cache.py`).
The only new gh shapes (`gh api .../pulls`, `gh pr ready`, REST merge) are deterministic and covered
by subprocess-stubbed units + offline `--dry-run` gates.

---

## 4. Deliverables by seam

### T5a — `/submit` (the draft PR)
- **`perk/git.py`:** `push(repo, branch, *, cwd, set_upstream=True)` — `git push -u origin <branch>`
  from the worktree cwd; `GitError` on failure (existing `_run` wrapper, `check=False`, `timeout`).
- **`perk/github.py`:** `default_branch(repo_root) -> str` (read: `gh repo view --json
  defaultBranchRef --jq .defaultBranchRef.name`); `find_pr_for_branch(*, branch, repo_root) ->
  PullRequest | None` (REST `GET .../pulls?head=<owner>:<branch>&state=all`, list endpoint);
  `create_pr(*, head, base, title, body, repo_root, draft=True, dry_run=False) -> PullRequest`
  (REST `POST .../pulls`, body via file, idempotent via `find_pr_for_branch`);
  `update_plan_header(*, issue, fields, repo_root, dry_run=False) -> PlanHeaderUpdate` (D7). New
  `PullRequest` frozen dataclass `{number, url, is_draft, state, existed}`.
- **`perk/cli/commands/pr_submit_cmd.py` (NEW):** `perk pr-submit` worker — reads `cache.plan-ref`
  from cwd (the worktree), derives `branch=plan-<pr_id>`, fetches the plan issue title (via
  `get_plan`), pushes, creates/finds the draft PR, updates the header; `--dry-run`/`--json`/stable
  exit codes mirroring `plan_save_cmd.py`.
- **`extension/submit.ts` (NEW):** the `submit` terminating tool + `/submit` command twin over one
  `submitPr(pi, ctx)` core that delegates to `perk pr-submit --json` via `pi.exec` (T3 shape).
- Registry `submit` I/O (D8); contracts §8.4 author `create_pr`/`update_plan_header` + Status
  (P1.T5a); `tests/test_github.py` + `tests/test_pr_submit.py` + `extension/submit.test.ts`;
  `scripts/verify-p1-t5a.sh` + `justfile`.

### T5b — `/land` + `/learn`
- **`perk/github.py`:** `mark_pr_ready(*, number, repo_root, dry_run=False) -> None` (`gh pr ready
  <n>` — the GraphQL exception); `merge_pr(*, number, repo_root, method="squash",
  commit_message=None, dry_run=False) -> PullRequest` (REST `PUT .../pulls/{n}/merge`, idempotent —
  already-merged ⇒ success).
- **`perk/cli/commands/pr_land_cmd.py` (NEW):** `perk pr-land` worker — finds the PR for the active
  plan's branch, marks ready if draft, squash-merges with a `Closes #<issue>` commit message;
  `--dry-run`/`--json`/exit codes. Sets `pending-learn` only on a real run.
- **`extension/land.ts` (NEW):** the `land` tool + `/land` command delegating to `perk pr-land
  --json`, then `setMarker(cwd, "pending-learn")` (cache.ts). **`extension/learn.ts` (NEW):** the
  `learn` tool + `/learn` command that calls `clearMarker(cwd, "pending-learn")` — TS-only, no
  delegation. (`pending-learn` constant centralized in `extension/cache.ts` + `perk/cache.py`.)
- **`extension/cache.ts`:** confirm `setMarker`/`clearMarker`/`hasMarker` twins exist (mirror
  `perk/cache.py`); add if missing.
- Registry `land`/`learn` I/O (D8); contracts §8.4 author `merge_pr`/`mark_pr_ready` + a `pending-learn`
  paragraph + Status (P1.T5b); `tests/test_github.py` + `tests/test_pr_land.py` +
  `extension/land.test.ts` + `extension/learn.test.ts`; `scripts/verify-p1-t5b.sh` + `justfile`.

### T5c — `perk resume <plan>`
- **`perk/github.py`:** `get_plan(*, number, repo_root) -> PlanState | None` (read: `gh issue view
  <n> --json title,body,state,labels` → parse the `plan-header`; if `pr` set, `gh pr view <pr>
  --json state,isDraft`). New `PlanState` frozen dataclass `{number, url, title, header:
  dict, pr: PullRequest | None}`.
- **`perk/resume.py` (NEW):** `resolve_resume_stage(plan_state, *, has_pending_learn) -> str`
  (the pure D5 state machine, unit-testable) + `reconstruct_plan_ref(plan_state) -> dict`.
- **`perk/cli/commands/resume_cmd.py` (NEW):** `perk resume <plan>` — three-layer Click
  (thin command → `require_repo`/`require_github` → pure resolve), reconstructs + writes
  `cache.plan-ref`, then `launch_stage(stage=resolved, ...)`; `--dry-run`/`--json` print the
  resolved stage + launch plan; stable exit codes (`plan_not_found` → 1, `not_a_repo` → 2).
- Registry: no new stage (resume spans stages); contracts §8.4 author `get_plan` + Status (P1.T5c);
  `tests/test_resume.py` (CliRunner + the resolution matrix) + `tests/test_github.py`;
  `scripts/verify-p1-t5c.sh` + `justfile`; `docs/index.md`.

---

## 5. `perk/github.py` — the PR ops (pseudocode)

REST throughout (T2a convention); `gh pr ready` is the lone GraphQL exception (no REST endpoint).

```python
@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    is_draft: bool
    state: str        # "OPEN" | "MERGED" | "CLOSED" (normalized upper)
    existed: bool     # True when found (idempotent), False when freshly created


def default_branch(repo_root: Path) -> str:
    proc = _run(["repo", "view", "--json", "defaultBranchRef",
                 "--jq", ".defaultBranchRef.name"], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _failed(proc, "failed to resolve the default branch")
    return proc.stdout.strip()


def find_pr_for_branch(*, branch: str, repo_root: Path) -> PullRequest | None:
    # list endpoint, all states (idempotency — survives draft + merged)
    proc = _run(["api", "repos/{owner}/{repo}/pulls", "-X", "GET",
                 "-f", f"head={_owner(repo_root)}:{branch}", "-f", "state=all"], cwd=repo_root)
    if proc.returncode != 0:
        raise _failed(proc, f"failed to list PRs for {branch!r}")
    items = json.loads(proc.stdout or "[]")
    if not isinstance(items, list) or not items:
        return None
    pr = items[0]
    return PullRequest(number=int(pr["number"]), url=str(pr.get("html_url", "")),
                       is_draft=bool(pr.get("draft", False)),
                       state=_pr_state(pr), existed=True)


def create_pr(*, head: str, base: str, title: str, body: str, repo_root: Path,
              draft: bool = True, dry_run: bool = False) -> PullRequest:
    if dry_run:
        return PullRequest(number=0, url="(dry-run)", is_draft=draft, state="OPEN", existed=False)
    existing = find_pr_for_branch(branch=head, repo_root=repo_root)
    if existing is not None:
        return existing
    with _body_file(body) as body_path:
        args = ["api", "repos/{owner}/{repo}/pulls", "-X", "POST",
                "-f", f"title={title}", "-f", f"head={head}", "-f", f"base={base}",
                "-F", f"body=@{body_path}", "-F", f"draft={'true' if draft else 'false'}",
                "--jq", "{number: .number, url: .html_url, draft: .draft, state: .state}"]
        proc = _run(args, cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _failed(proc, "failed to create PR")
    data = json.loads(proc.stdout)
    return PullRequest(number=int(data["number"]), url=str(data["url"]),
                       is_draft=bool(data.get("draft", draft)), state="OPEN", existed=False)


def mark_pr_ready(*, number: int, repo_root: Path, dry_run: bool = False) -> None:
    if dry_run:
        return
    proc = _run(["pr", "ready", str(number)], cwd=repo_root, timeout=_WRITE_TIMEOUT)  # GraphQL
    if proc.returncode != 0:
        raise _failed(proc, f"failed to mark PR #{number} ready")


def merge_pr(*, number: int, repo_root: Path, commit_message: str | None = None,
             dry_run: bool = False) -> PullRequest:
    if dry_run:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    args = ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}/merge", "-X", "PUT",
            "-f", "merge_method=squash"]
    if commit_message:
        args += ["-f", f"commit_message={commit_message}"]
    proc = _run(args, cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode == 0:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    blob = proc.stderr + proc.stdout
    if "already merged" in blob.lower() or "405" in blob:   # idempotent: already merged ⇒ success
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    raise _failed(proc, f"failed to merge PR #{number}")


def update_plan_header(*, issue: int, fields: dict[str, object], repo_root: Path,
                       dry_run: bool = False) -> "PlanHeaderUpdate":
    body = _get_issue_body(issue, repo_root)                # GET .../issues/{n}
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
    Ensure.invariant(set(fields) <= set(header) | _HEADER_KEYS, "unknown plan-header field(s)")
    merged = {**header, **fields}
    new_body = _replace_block(body, plan.PLAN_HEADER_KEY, merged)   # render + splice
    if dry_run:
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
    with _body_file(new_body) as p:
        proc = _run(["api", f"repos/{{owner}}/{{repo}}/issues/{issue}", "-X", "PATCH",
                     "-F", f"body=@{p}"], cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update plan-header on #{issue}")
    return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)
```

`_owner(repo_root)` derives `{owner}` from `gh repo view --json owner` (cached per call); `_pr_state`
normalizes `state`/`merged` into `OPEN|MERGED|CLOSED`; `_get_issue_body` + `_replace_block` are small
helpers reusing `plan.render_metadata_block`.

## 6. The worker commands (`perk pr-submit`, `perk pr-land`)

Both mirror `plan_save_cmd.py`: a thin `@click.command` → `require_repo`/`require_github` → a pure-ish
`_impl` → `--json`/human split via `machine_output`/`user_output`, `UserFacingCliError` mapped to
stable `error_type`/exit codes (`_EXIT_FOR_TYPE = {"not_a_repo": 2}`), `GitHubError` → `github_error`.

```python
# perk pr-submit (in the worktree cwd)
plan_ref = cache.read_plan_ref(repo_root) or _fail("no_plan_ref")     # exit 1
branch = launch.resolve_plan_worktree_name(plan_ref)                  # plan-<pr_id>
issue = int(plan_ref["pr_id"])
state = github.get_plan(number=issue, repo_root=repo_root) or _fail("plan_not_found")
base = github.default_branch(repo_root)
if not dry_run:
    git.push(repo_root, branch, cwd=repo_root)
body = _compose_pr_body(issue=issue, number_hint=...)                 # Closes #N + Plan: #N + footer
pr = github.create_pr(head=branch, base=base, title=state.title,
                      body=body, repo_root=repo_root, draft=True, dry_run=dry_run)
github.update_plan_header(issue=issue, repo_root=repo_root, dry_run=dry_run,
                          fields={"branch": branch, "pr": str(pr.number),
                                  "lifecycle_stage": plan.LifecycleStage.IMPL.value})
# --json: { success, pr: {number,url,is_draft,existed}, plan_header: {fields_updated}, dry_run }
```

```python
# perk pr-land (in the worktree cwd)
plan_ref = cache.read_plan_ref(repo_root) or _fail("no_plan_ref")
branch = launch.resolve_plan_worktree_name(plan_ref)
pr = github.find_pr_for_branch(branch=branch, repo_root=repo_root) or _fail("no_pr")  # exit 1
if pr.state != "MERGED":
    if pr.is_draft:
        github.mark_pr_ready(number=pr.number, repo_root=repo_root, dry_run=dry_run)
    pr = github.merge_pr(number=pr.number, repo_root=repo_root, dry_run=dry_run,
                         commit_message=f"Closes #{plan_ref['pr_id']}")
if not dry_run:
    cache.set_marker(repo_root, cache.PENDING_LEARN)     # the Q2 semaphore
# --json: { success, pr: {number,state}, pending_learn: not dry_run, dry_run }
```

`_compose_pr_body` (D2): `` f"Closes #{issue}\n\nPlan: #{issue}\n\n`gh pr checkout {n}`\n" `` — plain
text, no HTML. (`{n}` is filled post-create when known; on dry-run it is the branch.)

## 7. The warm doors (`extension/submit.ts`, `land.ts`, `learn.ts`)

`submit`/`land` mirror `planSave.ts` exactly — a terminating tool + a `/command` twin over one core
that delegates to the worker and never throws:

```ts
// submitPr(pi, ctx): SaveResult-shaped
const res = await pi.exec(perkBin, ["pr-submit", "--json"], { cwd: ctx.cwd, signal: ctx.signal });
if (res.killed || res.code !== 0) return fail(…, "exec_failed");
const parsed = JSON.parse(res.stdout);            // wrapped
if (!parsed.success) return fail(parsed.message, parsed.error_type);
return { content: [{ type: "text", text: `Opened PR #${parsed.pr.number}` }],
         details: { ok: true, pr: parsed.pr }, terminate: true };
```

`/land` does the same against `perk pr-land --json`, then on success `setMarker(ctx.cwd,
"pending-learn")`. `/learn` is TS-only:

```ts
// learnDone(ctx): no delegation, no throw
clearMarker(ctx.cwd, "pending-learn");
return { content: [{ type: "text", text: "Cleared pending-learn — worktree releasable." }],
         details: { ok: true }, terminate: true };
```

Guidelines (`promptGuidelines`) carry the safety contract structurally (T3 pattern): submit "only
after the implementation is committed"; land "only when the PR is approved/ready to merge"; learn
"after capturing learnings, to release the worktree."

## 8. `perk resume` (state machine + launch)

```python
# perk/resume.py — pure, unit-testable
def resolve_resume_stage(plan_state: github.PlanState, *, has_pending_learn: bool) -> str | None:
    header = plan_state.header
    pr = plan_state.pr
    if pr is None and header.get("lifecycle_stage", "planned") == "planned":
        return "implement"
    if pr is not None and pr.state == "OPEN":
        return "submit"
    if pr is not None and pr.state == "MERGED" and has_pending_learn:
        return "learn"
    return None      # nothing actionable (merged + learned) → informative exit 0

def reconstruct_plan_ref(plan_state: github.PlanState) -> dict[str, object]:
    return {"provider": "github", "pr_id": str(plan_state.number), "url": plan_state.url,
            "labels": [plan.PLAN_LABEL],
            "objective_id": plan_state.header.get("objective_id")}
```

```python
# perk/cli/commands/resume_cmd.py
state = github.get_plan(number=plan_id, repo_root=repo_root) or _fail("plan_not_found")  # exit 1
cache.write_plan_ref(repo_root, resume.reconstruct_plan_ref(state))
stage_id = resume.resolve_resume_stage(state, has_pending_learn=cache.has_marker(repo_root, "pending-learn"))
if stage_id is None:
    user_output("plan is merged and learned — nothing to resume"); return       # exit 0
stage = next(s for s in load_registry().stages if s.id == stage_id)
launch.launch_stage(repo_root=repo_root, config=require_config(ctx), stage=stage,
                    worktree=None, dry_run=dry_run, remote=None, pi_args=list(pi_args))
```

`launch_stage` already derives `plan-<pr_id>` from the freshly-written ref and (for `create`)
idempotently materializes; for `reuse` stages it requires the local worktree (clear error otherwise —
the flagged Phase-2 limitation). `--dry-run` flows through `launch_stage`'s existing JSON payload
(now also carrying the resolved `stage`).

## 9. Contract & registry amendments

- **`shared/registry.yaml`:** fill `submit`/`land`/`learn` `requires`/`reads`/`writes` per **D8**, as
  each seam lands (never ahead). Cumulative-gate discipline: if a later seam legitimately changes a
  value an earlier gate hardcoded, relax to membership (the T2b/T3 precedent).
- **`shared/contracts.md` §8.4:** promote `create_pr`/`mark_pr_ready`/`merge_pr`/`update_plan_header`
  from "named-only" to authored payloads (the §5 shapes); add the `get_plan` read op; record the
  **D1 delegation decision** (GitHub mutations canonical in Python; TS delegates — the "two gateways"
  hypothesis retired); add **Status (P1.T5a/b/c)** notes; add a `pending-learn` semaphore paragraph
  (land sets, learn clears, releases the worktree).
- **`PENDING_LEARN` constant** added to both `perk/cache.py` and `extension/cache.ts` (single source
  of the marker name across planes).

## 10. Tests & gates

- **Python units (subprocess stubbed, like `test_github.py`):** `create_pr` idempotency
  (find-then-create), `merge_pr` already-merged-is-success, `update_plan_header` field merge +
  unknown-key rejection, `get_plan` parse, `resolve_resume_stage` matrix (the four rows), `git.push`.
- **Python commands (`CliRunner` + `--dry-run` + offline fake-gh):** `pr-submit`/`pr-land`/`resume`
  dry-run JSON shape + exit codes (no-plan-ref → 1, not-a-repo → 2, plan-not-found → 1).
- **TS warm doors (T1 harness, `invokeTool` + `fakePerk`):** `submit`/`land` delegate + terminate +
  soft-fail on a missing/garbage worker; `/land` sets `pending-learn`; `/learn` clears it (idempotent,
  no worker needed).
- **Gates:** `verify-p1-t5a.sh` / `-t5b.sh` / `-t5c.sh` (the §1 checks), all offline; wired into
  `just verify`; `just ci` green (ruff + ruff-format + ty + biome + tsc + pytest + node:test).

## 11. Out of scope (Phase 2+)

AI-generated PR titles/bodies + the two-target body pattern + full-plan embedding in the PR; `pr
check` / CI iteration / Graphite; the review/`address` loop + feedback classification +
`resolve_review_threads`; reconciliation typing + deep learn tooling + a `perk:learn`
label/learn-issue; the no-changes PR scenario; recreating a `reuse`-stage worktree from a remote
branch on a fresh clone; objective linkage in the plan-header (`objective_id` population). All ride
the spine this turn closes.

## 12. Definition of done

- `implement → submit → land → learn` closes: a committed worktree submits a draft PR (header
  populated), lands it (squash-merge closes the issue, `pending-learn` set), and learns (marker
  cleared, worktree releasable).
- `perk resume <N>` resolves any plan to its current stage and launches it (idempotent for
  `implement`).
- Registry `submit`/`land`/`learn` I/O filled as built; §8.4 authored (no more named-only PR ops) +
  the D1 delegation decision recorded.
- Three offline verify gates pass; `just verify` + `just ci` green.
- §13 outcomes filled on landing.

## 13. Outcomes (recorded on landing)

### T5a — `/submit` (landed, all green)

**Status: landed.** `just verify` runs t1…t7 + p1-t1…p1-t4b + **p1-t5a**, all PASS (14 gates);
`just ci` green (ruff + ruff-format + ty + biome + tsc clean). **138 pytest** (+17: `test_github.py`
+10 PR-op units, `test_pr_submit.py` +6, plus a `plan.py` helper exercised) **+ 42 `node:test`**
(+4 `submit.test.ts`). The whole T5a gate runs **offline** (no `git push`, no `gh`, no LLM — the
warm door's delegation faked via `PERK_BIN`, the worker's dry-run fully local).

**Built (matches §4–§7):**
- `perk/plan.py`: `PLAN_HEADER_FIELDS` (the staged-population schema) + `replace_metadata_block`
  (re-render a block in place; appends if absent).
- `perk/github.py`: `PullRequest`/`PlanHeaderUpdate`/`PlanState` dataclasses; `default_branch`,
  `find_pr_for_branch` (prefers an open PR), `create_pr` (REST `POST .../pulls`, body via file,
  idempotent on head), `update_plan_header` (GET→merge→PATCH, rejects unknown keys), `get_pr`,
  `get_plan` (issue view + `pulls/{n}` when the header carries `pr`). REST throughout (T2a
  convention); `mark_pr_ready` deferred to T5b (the lone GraphQL op).
- `perk/git.py`: `push(cwd, branch)`.
- `perk/cli/commands/pr_submit_cmd.py` + CLI registration: `perk pr-submit` (`--dry-run`/`--json`,
  exit codes `no_plan_ref`→1 / `plan_not_found`→1 / `not_a_repo`→2 / `github_error`/`git_error`→1).
- `extension/submit.ts` (+ `index.ts` wiring): the `submit` terminating tool + `/submit` command
  twin over one `submitPr()` core that delegates to `perk pr-submit --json` and never throws.
- `shared/registry.yaml` `submit` I/O (D8); `shared/contracts.md` §8.4 authored the submit-path
  payloads + the **D1 delegation decision** (the "two gateways" hypothesis retired) + Status
  (P1.T5a). Tests + `scripts/verify-p1-t5a.sh` + `justfile`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **`--dry-run` is fully offline by short-circuit, not by threading `dry_run` into reads.** The §6
  pseudocode called `get_plan`/`default_branch` then passed `dry_run` to `create_pr`/
  `update_plan_header` — but those are reads with no `dry_run` param (and `update_plan_header`
  reads the issue body even on a dry run). To honor the gate's "no `gh` on a dry run" (mirroring
  `plan-save --dry-run`), the **command** short-circuits: a dry run composes the preview from the
  local `cache.plan-ref` only (branch, issue, the staged header-field *names*, a stub PR `#0`) and
  performs **no** `gh` read or write. The real run does the reads/writes. Faithful enough for a
  preview; strictly offline.
- **`get_plan` built in T5a (not deferred to T5c).** `pr-submit` needs the plan issue *title* for
  the PR, so `get_plan` (+ `get_pr`, `PlanState`) landed here; T5c reuses it unchanged.
- **gh shapes used:** `gh repo view --json {owner,defaultBranchRef}`; REST `gh api .../pulls`
  (GET list with `head=<owner>:<branch>`, POST create), `.../issues/{n}` (GET `--jq .body`, PATCH),
  `.../pulls/{n}` (GET); `gh issue view --json number,title,body,state,url`. `ExecResult` fields the
  warm door uses: `code`/`killed`/`stdout`/`stderr` (unchanged from T3).

**Tree at handoff (staged-clean for the user to commit):** new — `perk/cli/commands/pr_submit_cmd.py`,
`extension/submit.ts`, `extension/submit.test.ts`, `tests/test_pr_submit.py`,
`scripts/verify-p1-t5a.sh`, `docs/planning/phase-1-turn-5.md`; modified — `perk/plan.py`,
`perk/github.py`, `perk/git.py`, `perk/cli/cli.py`, `extension/index.ts`, `tests/test_github.py`,
`shared/registry.yaml`, `shared/contracts.md`, `justfile`, `docs/index.md`.

### T5b — `/land` + `/learn` (landed, all green)

**Status: landed.** `just verify` runs t1…t7 + p1-t1…p1-t5a + **p1-t5b**, all PASS (15 gates);
`just ci` green (ruff + ruff-format + ty + biome + tsc clean). **151 pytest** (+13: `test_github.py`
+5 land-op units, `test_pr_land.py` +7, +1 helper) **+ 48 `node:test`** (+6: `land.test.ts` +3,
`learn.test.ts` +3). Fully **offline** (the `/land` merge faked via `PERK_BIN`; `/learn` is TS-only;
the worker dry-run local).

**Built (matches §4–§7):**
- `perk/github.py`: `mark_pr_ready` (the lone GraphQL op — `gh pr ready`, called only on a draft) +
  `merge_pr` (REST `PUT .../merge`, `merge_method=squash`, idempotent on `already merged`).
- `perk/cache.py` + `extension/cache.ts`: the shared `PENDING_LEARN` constant.
- `perk/cli/commands/pr_land_cmd.py` + CLI registration: `perk pr-land` (find PR → mark-ready-if-draft
  → squash-merge with `Closes #<issue>` → set `pending-learn`; `--dry-run`/`--json`; exit codes
  `no_plan_ref`→1 / `no_pr`→1 / `not_a_repo`→2 / `github_error`→1).
- `extension/land.ts` (+ `index.ts`): the `land` terminating tool + `/land` command over one
  `landPr()` core that delegates to `perk pr-land --json`, then sets `pending-learn` (in-session
  path). `extension/learn.ts`: the `learn` tool + `/learn` command — **TS-only** `clearMarker`, no
  delegation, reports `was_pending`.
- `shared/registry.yaml` `land`/`learn` I/O (D8); `shared/contracts.md` §8.4 authored
  `mark_pr_ready`/`merge_pr` + a `pending-learn` paragraph + Status (P1.T5b). Tests +
  `scripts/verify-p1-t5b.sh` + `justfile`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **`pending-learn` is dual-written, by design (per §6/§7).** The cold worker sets it on its real
  run (cold-path correctness); the warm `/land` door also sets it post-successful-delegate — because
  a faked worker (`PERK_BIN`) doesn't touch disk, so the warm-door effect must be set + tested on the
  TS plane (gate check 8). It is an **idempotent existence file**, so the double-write is harmless
  and each plane's path is independently correct. Recorded in the §8.4 Status note.
- **`merge_pr` idempotency is narrowed to the `already merged` message, not bare `405`.** The §5
  pseudocode also treated `"405" in blob` as success, but a 405 is *also* returned for an
  unmergeable PR (conflicts) — too loose. Since the worker checks `state != "MERGED"` before merging
  (the real idempotency gate), `merge_pr`'s own net only matches `"already merged"` (lowercased) and
  otherwise raises. A conflict now surfaces loudly instead of being swallowed as success.
- **gh shapes used:** `gh pr ready <n>` (GraphQL); REST `gh api .../pulls/{n}/merge -X PUT -f
  merge_method=squash [-f commit_message=...]`. `ExecResult` fields the warm door uses:
  `code`/`killed`/`stdout`/`stderr`.

**`save → implement → submit → land → learn` is closed end-to-end** (modulo the cross-stage `perk
resume` verb, T5c). The land→learn cycle releases the worktree via the `pending-learn` semaphore.

**Tree at handoff (staged-clean for the user to commit):** new — `perk/cli/commands/pr_land_cmd.py`,
`extension/land.ts`, `extension/learn.ts`, `extension/land.test.ts`, `extension/learn.test.ts`,
`tests/test_pr_land.py`, `scripts/verify-p1-t5b.sh`; modified — `perk/github.py`, `perk/cache.py`,
`extension/cache.ts`, `perk/cli/cli.py`, `extension/index.ts`, `tests/test_github.py`,
`shared/registry.yaml`, `shared/contracts.md`, `justfile`.

### T5c — `perk resume` (landed, all green)

**Status: landed — T5 complete.** `just verify` runs t1…t7 + p1-t1…p1-t5b + **p1-t5c**, all PASS
(16 gates); `just ci` green (ruff + ruff-format + ty + biome + tsc clean). **163 pytest** (+12:
`test_resume.py` — the 5-row matrix + reconstruct + 6 CliRunner cases) **+ 48 `node:test`**
(unchanged — T5c is Python-only). Fully **offline** (the CliRunner suite stubs `get_plan` +
`launch_stage`; the gate also exercises the pure matrix via `python -c`).

**Built (matches §4/§8):**
- `perk/resume.py`: `resolve_resume_stage(plan_state, *, has_pending_learn)` (the pure D5 state
  machine) + `reconstruct_plan_ref(plan_state)`.
- `perk/cli/commands/resume_cmd.py` + CLI registration: `perk resume <plan>` — three-layer Click
  (thin command → `require_repo`/`require_github`/`require_config` → pure resolve), reconstructs +
  writes `cache.plan-ref` (real run only), then `launch_stage(worktree=None)` (reuses T4a: derive
  `plan-<pr_id>` + materialize + `exec pi`). `--dry-run`/`--json` resolve + print without launching;
  exit codes `invalid_input`→1 / `plan_not_found`→1 / `github_unauthed`→1 / `not_a_repo`→2.
  `get_plan` was already built in T5a, reused unchanged.
- `shared/contracts.md` §8.4 Status (P1.T5c). Tests + `scripts/verify-p1-t5c.sh` + `justfile`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **The matrix collapsed `planned`/`impl`-no-PR into one `implement` row.** §8's table had separate
  rows for "planned, no PR" and "impl, PR open"; as-built the decision is driven by **PR presence +
  state**, not `lifecycle_stage` (which is advisory and can lag): no PR → `implement` (covers both
  planned and mid-implementation), PR open → `submit`, PR merged + `pending-learn` → `learn`, else
  done. Simpler and more robust to a stale header. The `lifecycle_stage` read was dropped from the
  resolver entirely.
- **`--dry-run` resolves via a real `get_plan` (it is not offline like submit/land's dry-run).**
  resume's whole job is the GitHub read, so `require_github` runs even for `--dry-run`; the dry run
  only suppresses the **ref write + launch**. The gate stays offline by testing the pure matrix
  (`python -c`) + the CliRunner suite (stubbed `get_plan`) rather than a live `gh` call; `not-a-repo`
  (exit 2, before any `gh`) is checked end-to-end.
- **`reuse`-stage resume assumes a local worktree** (recreate-from-remote is Phase 2, flagged in
  §8.4 Status). `implement` is idempotent so it resumes on a fresh clone.

**The Phase-1 spine is closed: `plan → save → implement → submit → land → learn`, resumable at any
stage.** P1.T6 (the dogfood gate — perk ships perk) is the next turn.

**Tree at handoff (staged-clean for the user to commit):** new — `perk/resume.py`,
`perk/cli/commands/resume_cmd.py`, `tests/test_resume.py`, `scripts/verify-p1-t5c.sh`; modified —
`perk/cli/cli.py`, `shared/contracts.md`, `justfile`, `docs/planning/phase-1-turn-5.md`.
