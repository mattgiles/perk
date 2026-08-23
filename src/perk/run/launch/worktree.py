"""Worktree + run-target resolution for the cold-door launch.

The pure-ish resolution layer: the
:class:`ResolvedWorktree` / :class:`WorktreeRequest` / :class:`Target` value types, the target
resolver (:func:`resolve_target`), the deterministic worktree-name derivation
(:func:`resolve_plan_worktree_name`), the origin-aware base resolution (:func:`resolve_base` /
:func:`_fetch_best_effort`), and the validating worktree selector/positioner
(:func:`resolve_worktree`) — the single interface used whenever a cold door needs a plan
checkout (contracts.md §8.38).
"""

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk import plan
from perk.backends import resolve as backend_resolve
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.delivery import DeliveryError, PrepareRequest, resolve_delivery
from perk.delivery import layer as layer_mod
from perk.run import resume
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config
from perk.substrate.git import GitError
from perk.substrate.output import io_step, log_warn
from perk.substrate.registry import Stage

# The dry-run base report for a stacked layer: the parent is derived from the train at create
# time (a network reconstruction), so an offline dry run names the derivation instead of
# pretending a base resolved.
STACKED_DRY_RUN_BASE = "stacked layer — parent derived at create"

# How a resolution positioned (or would position) the stage's checkout — shared verbatim by the
# dry-run preview and the real setup/materialization gating (no created-flag asymmetry):
# `root` (a `worktree: none` stage in the invoking checkout), `reuse-local` (a validated
# existing checkout), `create-fresh` (a new branch + worktree), `restore-remote` (a missing
# checkout restored from the existing `origin/plan-<id>` branch).
Disposition = Literal["root", "reuse-local", "create-fresh", "restore-remote"]

# `worktree: reuse` consumers that never restore a missing checkout: `learn` runs post-squash-
# merge when GitHub commonly auto-deletes `origin/plan-<id>`, and its real input — machine-local
# session evidence under the worktree's gitignored run artifacts — cannot be restored from any
# remote anyway.
_RESTORE_EXCLUDED = frozenset({"learn"})


@dataclass(frozen=True)
class WorktreeRequest:
    """What a cold door asks of the positioner: the worktree *policy* (the registry vocabulary:
    ``none`` / ``create`` / ``reuse``) plus the consumer's name (diagnostics + the learn
    restore exclusion)."""

    policy: Literal["none", "create", "reuse"]
    consumer: str

    @classmethod
    def for_stage(cls, stage: Stage) -> "WorktreeRequest":
        # The registry validator already pins `worktree` to this vocabulary; the equality chain
        # re-checks it here so the Literal narrowing is honest rather than a cast.
        policy = stage.worktree
        if policy == "none":
            return cls(policy="none", consumer=stage.id)
        if policy == "create":
            return cls(policy="create", consumer=stage.id)
        if policy == "reuse":
            return cls(policy="reuse", consumer=stage.id)
        raise UserFacingCliError(f"stage '{stage.id}' has an unknown worktree policy {policy!r}")


@dataclass(frozen=True)
class ResolvedWorktree:
    """The checkout a stage runs in: the selected plan-ref, its canonical branch, the path, the
    per-disposition base, and the disposition itself.

    ``base`` per disposition: the creation start-point for ``create-fresh`` (``None`` ⇒ off
    local HEAD), the restored remote branch name (``origin/plan-<id>``) for ``restore-remote``,
    ``None`` for ``reuse-local`` and ``root``. ``plan_ref`` is the launch authority for prompts,
    materialization, and dry-run JSON (``None`` only for ``root`` and a bare-id dry-run restore
    preview, which deliberately performs no canonical read).
    """

    path: Path
    plan_ref: plan.PlanRef | None
    disposition: Disposition
    branch: str | None = None
    base: str | None = None


@dataclass(frozen=True)
class Target:
    """Where a stage runs: local (exec ``pi`` here) or a remote runner. The output of the
    pure :func:`resolve_target` step."""

    is_remote: bool
    runner: str | None = None  # the remote runner ref ("" => the default runner); None when local


def resolve_target(stage: Stage, remote: str | None) -> Target:
    """Resolve a stage's run target (D12). Pure + unit-testable.

    - ``remote is None`` → **local** (today's behavior).
    - ``remote`` set on a ``cold_remote:false`` stage → ``UserFacingCliError`` (``remote_blocked``).
    - ``remote`` set on a ``cold_remote:true`` stage → a remote ``Target`` that
      :func:`launch_stage` drives: persist the ``run_id→plan`` linkage, then trigger the runner
      (contracts.md §8.13).
    """
    if remote is None:
        return Target(is_remote=False)
    if stage.doors.get("cold_remote") is not True:
        raise UserFacingCliError(
            f"stage '{stage.id}' is local-only (cold_remote:false)\n"
            "Run without --remote for a local session.",
            error_type="remote_blocked",
        )
    return Target(is_remote=True, runner=remote)


def resolve_plan_worktree_name(plan_ref: plan.PlanRef) -> str:
    """Deterministic, re-derivable worktree/branch name for a plan (D1).

    ``pr_id`` stays a string (provider-agnostic): ``42 -> plan-42``, ``PROJ-123 ->
    plan-PROJ-123``. Rejects ids that cannot be a single path segment.
    """
    pr_id = plan_ref.pr_id.strip()
    Ensure.invariant(
        bool(pr_id) and "/" not in pr_id and pr_id not in (".", ".."),
        f"plan-ref pr_id unusable as a worktree name: {pr_id!r}",
    )
    return f"plan-{pr_id}"


def resolve_base(
    repo_root: Path, name: str, base_override: str | None, plan_base: str | None = None
) -> str | None:
    """The start-point ref a freshly-created ``plan-<pr_id>`` branch should base off (D: origin-
    aware create). Reads **local** refs only (no network) so it is dry-run-safe; the caller
    fetches first on the materialize path so a fresh ``origin/*`` is visible here.

    Precedence: an explicit ``--base`` wins verbatim (deliberate stacking, even on a non-origin
    ref); else track an existing ``origin/<name>`` (resumed/remote plan); else base off
    ``origin/<trunk>`` when it exists; else ``None`` (no usable origin ref — fall back to local
    HEAD, e.g. no remote). ``plan_base`` (the plan's pinned target branch) replaces the
    detected trunk as the trunk source when set, so a plan declaring a non-default base cuts its
    worktree from that branch.
    """
    if base_override is not None:
        return base_override
    if git.remote_ref_exists(repo_root, f"origin/{name}"):
        return f"origin/{name}"
    trunk = plan_base or git.detect_trunk_branch(repo_root)
    if git.remote_ref_exists(repo_root, f"origin/{trunk}"):
        return f"origin/{trunk}"
    return None


def _fetch_best_effort(repo_root: Path) -> None:
    """Fetch ``origin`` before basing a new branch; an offline failure is **non-fatal but warns
    loudly** (silent-off-stale-local is the bug this guards against)."""
    with io_step("fetching origin") as s:
        try:
            git.fetch(repo_root)
            s.done("fetched origin")
        except GitError as exc:
            s.warn(
                f"could not fetch origin ({exc}); basing this branch on the LAST-KNOWN origin ref "
                "— it may be STALE. Connect and re-run, or pass --base, to start from up-to-date "
                "trunk."
            )


def _sync_main_checkout(repo_root: Path) -> None:
    """Guarded fast-forward of the **main checkout** before a read-only ``worktree: none`` launch.

    Read-only planning/authoring stages run in the user's main checkout and do no remote sync at
    launch, so a planning session could open against a stale tree (missing sibling nodes already
    landed on trunk). This best-effort, loud-but-non-fatal sync (mirroring ``_fetch_best_effort``)
    fast-forwards the current branch to its upstream — **only** when the checkout is clean, on a
    branch, has an upstream, and can fast-forward. Any other condition warns and skips: it never
    aborts the launch, never creates a merge commit, and never touches a dirty or detached tree
    (the user's working state is sacred).
    """
    if not git.has_remote(repo_root):
        return  # nothing to sync against (also keeps remote-less repos / the test suite offline)
    branch = git.current_branch(repo_root)
    if branch is None:
        log_warn("detached HEAD — skipping checkout sync")
        return
    if git.is_dirty(repo_root):
        log_warn("uncommitted changes — skipping checkout sync (commit or stash to pick up remote)")
        return
    with io_step("fetching origin") as s:
        try:
            git.fetch(repo_root)
        except GitError as exc:
            s.warn(
                f"could not fetch origin ({exc}); using the LAST-KNOWN checkout state — it may be "
                "STALE. Connect and re-run to sync the main checkout."
            )
            return
        upstream = git.upstream_ref(repo_root)
        if upstream is None:
            s.warn(f"branch '{branch}' has no upstream — skipping checkout sync")
            return
        if not git.merge_ff_only(repo_root, upstream):
            s.warn(
                f"'{branch}' has diverged from {upstream} — skipping fast-forward "
                "(reconcile manually)"
            )
            return
        s.done(f"synced {branch} → {upstream}")


@dataclass(frozen=True)
class _Selection:
    """The settled plan selection: the ref (``None`` only for a bare-id selection that has not
    needed a canonical read yet), the bare id it must match, and the human name of the source
    (typed-diagnostic vocabulary)."""

    ref: plan.PlanRef | None
    plan_id: str
    source: str


def _same_path(a: Path, b: Path) -> bool:
    """Path equality with both sides resolved (the macOS ``/var`` → ``/private/var`` case)."""
    return a.resolve() == b.resolve()


def _read_binding(path: Path) -> plan.PlanRef | None:
    """The checkout's worktree-local binding; a corrupt file reads as *unreadable* (``None``) —
    the caller refuses ``worktree_unbound`` rather than guessing."""
    try:
        return cache.read_plan_ref(path)
    except cache.CacheError as exc:
        log_warn(f"unreadable worktree binding at {path}: {exc}")
        return None


def _validate_existing_checkout(
    *,
    repo_root: Path,
    path: Path,
    selection: _Selection,
) -> plan.PlanRef:
    """Validate an existing checkout before reuse (read-only git probes only — no mutating or
    network git operations) and return the settled ref.

    The checkout must be a registered git worktree at the resolved path, be checked out on the
    selected ``plan-<id>`` branch, carry a readable worktree-local ``plan-ref``, and that
    binding must equal the selected ref across every ``PlanRef`` field. Disagreements fail
    before handoff/materialization/exec with typed diagnostics naming each source.
    """
    try:
        entries = git.worktree_list(repo_root)
    except GitError as exc:
        raise UserFacingCliError(f"git worktree list failed: {exc}") from exc
    entry = next((w for w in entries if _same_path(w.path, path)), None)
    if entry is None:
        raise UserFacingCliError(
            f"{path} exists but is not a registered git worktree.\n"
            "Move it aside (or delete it) and re-run to get a managed checkout.",
            error_type="worktree_unregistered",
        )
    # A `git worktree list` entry alone is not proof of a usable checkout: git retains a
    # prunable admin entry when the checkout's `.git` gitfile is gone — and because the path
    # sits under the main repo, git commands run there would silently resolve to the MAIN
    # checkout. Require a live read-only probe: the path's own toplevel must be exactly this
    # resolved path.
    live_top = git.repo_root(path)
    if live_top is None or live_top.resolve() != path.resolve():
        resolved_to = str(live_top) if live_top is not None else "no repository"
        raise UserFacingCliError(
            f"{path} is registered but not a usable git worktree (its checkout metadata is "
            f"missing or broken — git resolves the path to {resolved_to}).\n"
            f"Run `git worktree repair` in {repo_root}, or remove the entry "
            f"(git worktree remove --force {path}) and re-run.",
            error_type="worktree_unregistered",
        )
    binding = _read_binding(path)
    if binding is None:
        raise UserFacingCliError(
            f"Worktree {path} carries no readable plan-ref binding — refusing to guess "
            "(an existing checkout is never silently rebound).\n"
            f"Remove it (git worktree remove {path}) and re-run to restore the checkout.",
            error_type="worktree_unbound",
        )
    expected_branch = (
        resolve_plan_worktree_name(selection.ref)
        if selection.ref is not None
        else f"plan-{selection.plan_id}"
    )
    if entry.branch != expected_branch:
        raise UserFacingCliError(
            f"Worktree {path} is checked out on branch "
            f"{entry.branch or '(detached HEAD)'!s}, expected {expected_branch!r} "
            f"({selection.source}).\n"
            "perk never repositions an existing checkout — check out the expected branch "
            f"there, or remove the worktree (git worktree remove {path}) and re-run.",
            error_type="worktree_branch_mismatch",
        )
    if selection.ref is not None and binding != selection.ref:
        raise UserFacingCliError(
            f"Plan selection disagrees with the worktree binding: {selection.source} selects "
            f"plan #{selection.ref.pr_id}, but {path} is bound to plan #{binding.pr_id} "
            f"(binding fields differ: {_diff_fields(selection.ref, binding)}).\n"
            "Re-run without the conflicting selector, or remove the worktree "
            f"(git worktree remove {path}) and re-run to restore it from canonical state.",
            error_type="worktree_plan_mismatch",
        )
    if selection.ref is None and binding.pr_id != selection.plan_id:
        raise UserFacingCliError(
            f"Plan selection disagrees with the worktree binding: {selection.source} selects "
            f"plan #{selection.plan_id}, but {path} is bound to plan #{binding.pr_id}.\n"
            f"Remove the worktree (git worktree remove {path}) and re-run to restore it.",
            error_type="worktree_plan_mismatch",
        )
    return selection.ref if selection.ref is not None else binding


def _diff_fields(a: plan.PlanRef, b: plan.PlanRef) -> str:
    """The names of the ``PlanRef`` fields that disagree (diagnostic vocabulary)."""
    names = [
        f.name for f in dataclasses.fields(plan.PlanRef) if getattr(a, f.name) != getattr(b, f.name)
    ]
    return ", ".join(names) if names else "none"


def _fetch_plan_state(repo_root: Path, plan_id: str) -> tuple[PlanState, str]:
    """One canonical backend read for a restore that needs it (a bare-id selection, or a stacked
    layer-context rebuild). Returns the state plus the resolved backend id (the provider)."""
    try:
        backend = backend_resolve.resolve_issue_backend(repo_root)
        with io_step(f"looking up plan #{plan_id}") as s:
            state = backend.get_plan(issue_id=plan_id)
            if state is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_id} not found", error_type="plan_not_found"
                )
            s.done(f"found plan #{plan_id}")
    except IssueBackendError as exc:
        raise UserFacingCliError(
            f"could not read plan #{plan_id} from the issue backend\n{exc}",
            error_type="github_error",
        ) from exc
    return state, backend.backend_id


def _checkpoint_pair(state: PlanState) -> tuple[str, str] | None:
    """The stacked checkpoint pair from the canonical plan header (``None`` when incomplete)."""
    parent = state.header.get("parent_checkpoint_sha")
    published = state.header.get("published_head_sha")
    if not (isinstance(parent, str) and parent.strip()):
        return None
    if not (isinstance(published, str) and published.strip()):
        return None
    return parent.strip(), published.strip()


def _validate_stacked_checkpoints(*, repo_root: Path, branch: str, state: PlanState) -> None:
    """Verify the canonical checkpoint pair against the FETCHED remote tip before any
    materialization: the recorded ``published_head_sha`` must BE the remote tip and the recorded
    ``parent_checkpoint_sha`` must resolve locally (the strict branch fetch brings the layer's
    history) and be an ancestor of that tip. A force-pushed, manually-moved, or stale-header
    branch refuses ``worktree_restore_failed`` here — otherwise an unrelated full sha would be
    restored into ``layer-context.parent_sha`` and ``plan watch`` would trust it as the exact
    layer delta. The strict fetch is shared with :func:`_restore_checkout` (idempotent).
    """
    parent_sha, published_sha = Ensure.not_none(
        _checkpoint_pair(state), "stacked checkpoint validation reached without a pair"
    )

    def _refuse(reason: str) -> UserFacingCliError:
        return UserFacingCliError(
            f"could not restore worktree for plan branch {branch}: {reason}",
            error_type="worktree_restore_failed",
        )

    try:
        git.fetch_refspecs(repo_root, [branch])
    except GitError as exc:
        raise _refuse(
            f"the remote branch could not be fetched ({exc}). If the plan was never "
            "pushed, run `perk implement` first."
        ) from exc
    tip = git.resolve_commit(repo_root, f"refs/remotes/origin/{branch}")
    if tip is None:
        raise _refuse("origin has no such branch after fetch")
    if published_sha != tip:
        raise _refuse(
            f"the canonical header records published head {published_sha[:12]} but "
            f"origin/{branch} is at {tip[:12]} — the branch drifted from its recorded "
            "publication. Run `perk objective stack status` (and sync/adopt) to reconcile, "
            "then re-run."
        )
    if (
        git.resolve_commit(repo_root, parent_sha) != parent_sha
        or git.is_ancestor(repo_root, parent_sha, tip) is not True
    ):
        raise _refuse(
            f"the recorded parent checkpoint {parent_sha[:12]} is not an ancestor of "
            f"origin/{branch} — the layer's operational record is stale. Run "
            "`perk objective stack status` to inspect the train."
        )


def _restore_layer_context(
    *, repo_root: Path, path: Path, ref: plan.PlanRef, state: PlanState, branch: str
) -> None:
    """Rewrite the restored checkout's ``layer-context.json`` from the fetched canonical plan
    header (contracts.md §8.46): ``parent_branch`` from ``predecessor_plan_id`` (``plan-<pred>``,
    or the base for the bottom layer), ``branch = plan-<id>``, and ``parent_sha`` from the
    header's verified ``parent_checkpoint_sha``. Keeps `plan watch`'s layer-arm diff base exact
    after restoration instead of silently degrading to the whole-stack delta.
    """
    pair = Ensure.not_none(
        _checkpoint_pair(state), "restore reached layer-context without a checkpoint pair"
    )
    parent_sha = pair[0]
    predecessor = state.header.get("predecessor_plan_id")
    predecessor_id = (
        predecessor.strip() if isinstance(predecessor, str) and predecessor.strip() else None
    )
    node_id = state.header.get("objective_node_id")
    base_branch = ref.base or git.detect_trunk_branch(repo_root)
    ctx = layer_mod.LayerContext(
        objective_id=ref.objective_id or "",
        node_id=node_id if isinstance(node_id, str) else "",
        plan_id=ref.pr_id,
        delivery_lineage=ref.delivery_lineage,
        predecessor_plan_id=predecessor_id,
        base=base_branch,
        parent_branch=f"plan-{predecessor_id}" if predecessor_id else base_branch,
        branch=branch,
    )
    cache.write_layer_context(path, ctx, parent_sha)


def _refuse_stale_registration(repo_root: Path, path: Path) -> None:
    """A path that is missing but still registered in ``git worktree list`` (a stale admin
    entry) refuses typed — never auto-pruned."""
    try:
        entries = git.worktree_list(repo_root)
    except GitError as exc:
        raise UserFacingCliError(f"git worktree list failed: {exc}") from exc
    if any(_same_path(w.path, path) for w in entries):
        raise UserFacingCliError(
            f"{path} is missing but still registered as a git worktree (a stale admin entry).\n"
            f"Run `git worktree prune` in {repo_root}, then re-run.",
            error_type="worktree_stale_registration",
        )


def _restore_checkout(*, repo_root: Path, path: Path, branch: str) -> None:
    """Restore a missing checkout from the existing remote plan branch, non-destructively.

    Strictly fetch ``origin/<branch>``; create the local branch from the remote tip when
    absent; attach it when equal; fast-forward an un-checked-out local branch only when it is
    provably behind; refuse as ``worktree_restore_failed`` **without changing local branch
    refs** when it is ahead, divergent, checked out elsewhere, unresolvable, or the remote
    branch cannot be fetched (the strict fetch legitimately updates ``refs/remotes/origin/*``;
    the refusal guarantee scopes to local refs). Never synthesizes a missing plan branch.
    """

    def _refuse(reason: str) -> UserFacingCliError:
        return UserFacingCliError(
            f"could not restore worktree {path} from origin/{branch}: {reason}",
            error_type="worktree_restore_failed",
        )

    with io_step(f"restoring worktree {path.name} from origin/{branch}") as s:
        try:
            git.fetch_refspecs(repo_root, [branch])
        except GitError as exc:
            raise _refuse(
                f"the remote branch could not be fetched ({exc}). If the plan was never "
                "pushed, run `perk implement` first."
            ) from exc
        remote_sha = git.resolve_commit(repo_root, f"refs/remotes/origin/{branch}")
        if remote_sha is None:
            raise _refuse("origin has no such branch after fetch")
        local_sha = git.resolve_commit(repo_root, f"refs/heads/{branch}")
        try:
            if local_sha is None:
                # Create the local branch from the remote tip (tracking it) + attach.
                git.worktree_add(
                    repo_root, path, branch=branch, create_branch=True, base=f"origin/{branch}"
                )
            else:
                if local_sha != remote_sha:
                    behind = git.is_ancestor(repo_root, local_sha, remote_sha)
                    if behind is not True:
                        ahead = git.is_ancestor(repo_root, remote_sha, local_sha)
                        shape = "ahead of" if ahead is True else "divergent from"
                        raise _refuse(
                            f"local branch {branch} is {shape} origin/{branch} — refusing to "
                            "touch it (local branch refs were left unchanged). Reconcile the "
                            "branch manually, then re-run."
                        )
                # The checked-out-elsewhere guard sits at the MUTATION boundary (immediately
                # before the ref write below), and the fast-forward itself is a compare-and-swap
                # against the observed sha — a branch another process advanced or checked out
                # between the probes and the write refuses instead of being overwritten. (The
                # final `worktree add` is git's own backstop: it refuses a branch that became
                # checked out elsewhere in the residual window.)
                entries = git.worktree_list(repo_root)
                holder = next((w for w in entries if w.branch == branch), None)
                if holder is not None:
                    raise _refuse(
                        f"local branch {branch} is already checked out at {holder.path} — "
                        "local branch refs were left unchanged"
                    )
                if local_sha != remote_sha:
                    # Provably behind and not checked out anywhere: safe fast-forward (CAS).
                    git.update_ref(
                        repo_root, f"refs/heads/{branch}", remote_sha, expected=local_sha
                    )
                git.worktree_add(repo_root, path, branch=branch, create_branch=False)
        except GitError as exc:
            raise _refuse(str(exc)) from exc
        s.done(f"restored worktree {path.name} @ {remote_sha[:12]}")


def _materialize_binding(path: Path, ref: plan.PlanRef) -> None:
    """The positioner owns worktree-binding materialization: a newly created/restored checkout
    receives the selected ``plan-ref`` immediately after checkout creation (before the setup
    hook), plus the ``setup-pending`` marker the marker-gated setup hook consumes."""
    cache.ensure_layout(path)
    cache.write_plan_ref(path, ref)
    cache.set_marker(path, cache.SETUP_PENDING)


def resolve_worktree(
    *,
    repo_root: Path,
    config: Config,
    request: WorktreeRequest,
    worktree: str | None,
    materialize: bool,
    base: str | None = None,
    invocation_root: Path | None = None,
    selected_ref: plan.PlanRef | None = None,
    plan_state: PlanState | None = None,
    plan_id: str | None = None,
) -> ResolvedWorktree:
    """Resolve the checkout this stage runs in (validating); mutate only when ``materialize``
    (i.e. not a dry run — dry runs perform no fetch, no ref/file writes, no markers).

    Sources resolve in a fixed order — the cache is fallback only:

    1. an explicit canonical ``selected_ref`` (a positional plan id, already resolved) — or the
       bare ``plan_id`` twin (`plan watch`), whose canonical read happens lazily, only on a real
       restore;
    2. for an explicit existing ``--worktree``, that checkout's local binding (an unrelated
       root selector is not a competing source);
    3. otherwise, the **invocation root's** active selector (``invocation_root`` defaults to
       ``repo_root``; a no-argument launch inside a plan worktree selects that worktree's own
       plan).

    The selected ref always derives branch ``plan-<pr_id>``; ``--worktree NAME`` changes only
    the directory under the configured worktree root, never plan identity or branch name.
    ``plan_state`` is the selection's already-fetched canonical state (spares the restore path
    a re-read). Existing checkouts are preserved: no fetch, reset, checkout, fast-forward, or
    any ref/branch mutation occurs when a valid registered checkout already exists.
    """
    if request.policy == "none":
        return ResolvedWorktree(path=repo_root, plan_ref=None, disposition="root")
    invocation_root = invocation_root if invocation_root is not None else repo_root

    # --- selection (the fixed precedence above) -------------------------------------------
    selection: _Selection
    if selected_ref is not None:
        selection = _Selection(
            ref=selected_ref, plan_id=selected_ref.pr_id, source="the explicit plan selector"
        )
    elif plan_id is not None:
        selection = _Selection(ref=None, plan_id=plan_id, source=f"plan id {plan_id}")
    elif worktree is not None:
        # An explicit --worktree without a plan id selects through the checkout's own binding
        # (read during validation below); a missing directory cannot invent a binding.
        path = config.worktree_root / checked_name(worktree)
        if not path.exists():
            raise UserFacingCliError(
                f"Worktree not found: {path}\n"
                "An explicit --worktree without a PLAN cannot invent a plan binding — pass the "
                "plan id too, or drop --worktree.",
                error_type="worktree_not_found",
            )
        binding = _read_binding(path)
        if binding is None:
            raise UserFacingCliError(
                f"Worktree {path} carries no readable plan-ref binding — refusing to guess "
                "(an existing checkout is never silently rebound).\n"
                f"Remove it (git worktree remove {path}) and re-run.",
                error_type="worktree_unbound",
            )
        selection = _Selection(
            ref=binding, plan_id=binding.pr_id, source=f"the worktree binding at {path}"
        )
    else:
        active = cache.read_plan_ref(invocation_root)
        if active is None:
            raise UserFacingCliError(
                f"Stage '{request.consumer}' needs a saved plan — run /plan-save first "
                "(or pass a plan id).",
                error_type="no_plan_ref",
            )
        selection = _Selection(
            ref=active,
            plan_id=active.pr_id,
            source=f"the active plan-ref selector at {invocation_root}",
        )

    branch = (
        resolve_plan_worktree_name(selection.ref)
        if selection.ref is not None
        else f"plan-{selection.plan_id}"
    )
    name = checked_name(worktree) if worktree is not None else branch
    path = config.worktree_root / name

    plan_base = selection.ref.base if selection.ref is not None else None
    plan_base = plan_base if plan_base and plan_base.strip() else None

    # --- an existing checkout: validated reuse (never mutated) ----------------------------
    if path.exists():
        ref = _validate_existing_checkout(repo_root=repo_root, path=path, selection=selection)
        return ResolvedWorktree(path=path, plan_ref=ref, disposition="reuse-local", branch=branch)

    # --- a missing checkout: create (create policy) or restore (reuse policy) -------------
    if request.policy == "create":
        return _create_fresh(
            repo_root=repo_root,
            path=path,
            branch=branch,
            base=base,
            plan_base=plan_base,
            ref=Ensure.not_none(
                selection.ref, "create-policy resolution reached creation without a plan ref"
            ),
            materialize=materialize,
        )

    # reuse policy, missing path.
    if request.consumer in _RESTORE_EXCLUDED:
        raise UserFacingCliError(
            f"Worktree not found: {path}\n"
            f"'{request.consumer}' never restores a checkout: it runs after the squash-merge "
            f"(origin/{branch} is commonly auto-deleted) and its input — the session evidence "
            "under the worktree's gitignored run artifacts — is machine-local. Run it on the "
            f"machine where plan #{selection.plan_id} was implemented, or skip it.",
            error_type="worktree_not_found",
        )
    if not materialize:  # a dry run reports the planned restore without fetching anything
        return ResolvedWorktree(
            path=path,
            plan_ref=selection.ref,
            disposition="restore-remote",
            branch=branch,
            base=f"origin/{branch}",
        )
    ref = selection.ref
    state = plan_state
    if ref is None:  # a bare-id selection restores from canonical state (the one lazy read)
        state, provider = _fetch_plan_state(repo_root, selection.plan_id)
        ref = resume.reconstruct_plan_ref(state, provider=provider)
        # The backend may canonicalize the raw selector (e.g. GitHub "007" → id "7"), so
        # positioning is recomputed from the CANONICAL id — a restore can never materialize a
        # `plan-007` directory bound to plan #7. A checkout that exists under the canonical
        # name is validated reuse, exactly as if the canonical id had been passed.
        canonical_branch = resolve_plan_worktree_name(ref)
        if canonical_branch != branch:
            selection = _Selection(ref=ref, plan_id=ref.pr_id, source=selection.source)
            branch = canonical_branch
            path = config.worktree_root / (
                checked_name(worktree) if worktree is not None else branch
            )
            if path.exists():
                validated = _validate_existing_checkout(
                    repo_root=repo_root, path=path, selection=selection
                )
                return ResolvedWorktree(
                    path=path, plan_ref=validated, disposition="reuse-local", branch=branch
                )
    if ref.delivery_lineage is not None:
        if state is None:
            state, _provider = _fetch_plan_state(repo_root, ref.pr_id)
        if _checkpoint_pair(state) is None:
            raise UserFacingCliError(
                f"plan #{ref.pr_id} is a stacked layer with a remote branch but no checkpoint "
                "pair on its canonical header — the layer's operational record cannot be "
                "restored. Run `perk objective stack status` to inspect the train.",
                error_type="worktree_restore_failed",
            )
        _validate_stacked_checkpoints(repo_root=repo_root, branch=branch, state=state)
    _refuse_stale_registration(repo_root, path)
    _restore_checkout(repo_root=repo_root, path=path, branch=branch)
    _materialize_binding(path, ref)
    if ref.delivery_lineage is not None:
        stacked_state = Ensure.not_none(state, "stacked restore lost its canonical state")
        _restore_layer_context(
            repo_root=repo_root, path=path, ref=ref, state=stacked_state, branch=branch
        )
    return ResolvedWorktree(
        path=path,
        plan_ref=ref,
        disposition="restore-remote",
        branch=branch,
        base=f"origin/{branch}",
    )


def checked_name(name: str) -> str:
    """The one worktree-name validation boundary: reject anything unusable as a single path
    segment under the managed worktree root (empty, dot-segments, ``/``-containing). Public so
    a door's pre-launch probe path derivation goes through the SAME check the positioner
    applies — an invalid ``--worktree`` can never make a probe inspect outside the root."""
    Ensure.invariant(
        "/" not in name and name not in ("", ".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    return name


def _create_fresh(
    *,
    repo_root: Path,
    path: Path,
    branch: str,
    base: str | None,
    plan_base: str | None,
    ref: plan.PlanRef,
    materialize: bool,
) -> ResolvedWorktree:
    """The fresh-create arm: the §8.46 stacked parent-aware creation for a stacked ref (unless
    ``origin/plan-<id>`` already exists — a resumed layer keeps the ordinary tracking arm), the
    origin-aware base resolution otherwise, and the positioner-owned binding materialization."""
    stacked = ref.delivery_lineage is not None
    if stacked and base is not None:
        raise UserFacingCliError(
            f"--base is not accepted for a stacked layer (plan #{ref.pr_id}): the "
            "parent is derived from the delivery train, never chosen.",
            error_type="invalid_input",
        )
    if not materialize:  # dry-run create: resolve the base from local refs only (no fetch)
        resolved_base = (
            STACKED_DRY_RUN_BASE
            if stacked and not git.remote_ref_exists(repo_root, f"origin/{branch}")
            else resolve_base(repo_root, branch, base, plan_base)
        )
        return ResolvedWorktree(
            path=path, plan_ref=ref, disposition="create-fresh", branch=branch, base=resolved_base
        )
    _refuse_stale_registration(repo_root, path)
    _fetch_best_effort(repo_root)  # network sync first so a fresh origin/* is seen
    if stacked and not git.remote_ref_exists(repo_root, f"origin/{branch}"):
        # Fresh stacked creation: Prepare owns reconstruction, readiness, and executable parent
        # verification. An existing origin/plan-<id> (a resumed layer) keeps the ordinary arm.
        if ref.objective_id is None:
            raise UserFacingCliError(
                f"plan #{ref.pr_id} carries delivery_lineage but no objective_id — its "
                "delivery train cannot be reconstructed.",
                error_type="invalid_train",
            )
        with io_step("reconstructing the delivery train") as s:
            try:
                prepared = resolve_delivery(repo_root).prepare(
                    PrepareRequest(
                        kind="layer_start",
                        mode="execution",
                        objective_id=ref.objective_id,
                        plan_id=ref.pr_id,
                    )
                )
            except DeliveryError as exc:
                raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
            context = Ensure.not_none(
                prepared.layer, "execution Prepare must carry a layer context"
            )
            parent_sha = Ensure.not_none(
                prepared.parent_sha, "execution Prepare must carry a parent SHA"
            )
            s.done(
                f"layer {context.node_id} starts from {context.parent_branch} @ {parent_sha[:12]}"
            )
        resolved_base = parent_sha
        with io_step(
            f"creating worktree {path.name} from {context.parent_branch} @ {parent_sha[:12]}"
        ) as s:
            try:
                git.worktree_add(
                    repo_root, path, branch=branch, create_branch=True, base=parent_sha
                )
            except GitError as exc:
                raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
            s.done(f"created worktree {path.name}")
        _materialize_binding(path, ref)
        # The session-scoped operational record (§8.46) — never authoritative; publication
        # re-verifies live.
        cache.write_layer_context(path, context, parent_sha)
    else:
        resolved_base = resolve_base(repo_root, branch, base, plan_base)
        # The GitError raise escapes the step (dangling + the error text below, as today).
        with io_step(f"creating worktree {path.name} from {resolved_base or 'local HEAD'}") as s:
            try:
                git.worktree_add(
                    repo_root, path, branch=branch, create_branch=True, base=resolved_base
                )
            except GitError as exc:
                raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
            s.done(f"created worktree {path.name}")
        _materialize_binding(path, ref)
    return ResolvedWorktree(
        path=path, plan_ref=ref, disposition="create-fresh", branch=branch, base=resolved_base
    )
