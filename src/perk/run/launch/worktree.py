"""Worktree + run-target resolution for the cold-door launch.

The pure-ish resolution layer: the
:class:`ResolvedWorktree` / :class:`Target` value types, the target resolver
(:func:`resolve_target`), the deterministic worktree-name derivation
(:func:`resolve_plan_worktree_name`), the origin-aware base resolution (:func:`resolve_base` /
:func:`_fetch_best_effort`), and the validating worktree resolver (:func:`resolve_worktree`).
"""

from dataclasses import dataclass
from pathlib import Path

from perk import plan
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.delivery import layer as layer_mod
from perk.delivery import observe
from perk.delivery import train as train_mod
from perk.delivery.persistence import TrainPersistenceError
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


@dataclass(frozen=True)
class ResolvedWorktree:
    """The worktree a stage runs in, plus the plan-ref to materialize into it (if derived)."""

    path: Path
    plan_ref: plan.PlanRef | None
    base: str | None = None  # the start-point the create path used (None => off local HEAD)
    # True only when this resolution **freshly created** the worktree (the `git.worktree_add`
    # branch) — not idempotent reuse, a dry run, or a `worktree: none` stage. Gates the
    # `[worktree] setup` hook so it fires once per fresh worktree.
    created: bool = False


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


def prepare_stacked_layer(repo_root: Path, plan_ref: plan.PlanRef) -> layer_mod.PreparedLayerStart:
    """The parent-aware creation gate for a stacked layer (contracts.md §8.46).

    Reconstructs the delivery train fresh (the `delivery_lineage` routing field only routes —
    the train is the authority), requires this plan's layer to BE the readiness-derived
    candidate, then fetches and verifies the latest parent head. Typed failures surface as
    :class:`UserFacingCliError` preserving their ``error_type``.
    """
    objective_id = plan_ref.objective_id
    if objective_id is None:
        raise UserFacingCliError(
            f"plan #{plan_ref.pr_id} carries delivery_lineage but no objective_id — its "
            "delivery train cannot be reconstructed.",
            error_type="invalid_train",
        )
    with io_step("reconstructing the delivery train") as s:
        try:
            status = observe.reconstruct_repo_train(repo_root, objective_id)
        except train_mod.TrainReconstructionError as exc:
            raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
        except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise UserFacingCliError(str(exc), error_type="github_error") from exc
        if not isinstance(status, train_mod.DeliveryTrain):
            # The routing field says stacked but the objective is incremental now — fail
            # closed rather than silently creating off trunk.
            raise UserFacingCliError(
                f"plan #{plan_ref.pr_id} carries delivery_lineage but objective "
                f"#{objective_id} has no delivery train ({status.reason}).",
                error_type="invalid_train",
            )
        try:
            ctx = layer_mod.require_ready_layer(status, plan_id=plan_ref.pr_id)
            prepared = layer_mod.prepare_layer_start(repo_root, ctx)
        except layer_mod.LayerError as exc:
            raise UserFacingCliError(str(exc), error_type=exc.error_type) from exc
        s.done(f"layer {ctx.node_id} starts from {ctx.parent_branch} @ {prepared.parent_sha[:12]}")
    return prepared


def resolve_worktree(
    *,
    repo_root: Path,
    config: Config,
    stage: Stage,
    worktree: str | None,
    materialize: bool,
    base: str | None = None,
) -> ResolvedWorktree:
    """Resolve the worktree this stage runs in (validating); create it only when
    ``materialize`` (i.e. not a dry run). ``create`` reuses an existing worktree (D4)."""
    if stage.worktree == "none":
        return ResolvedWorktree(path=repo_root, plan_ref=None)

    plan_ref: plan.PlanRef | None = None
    name = worktree
    base_ref: plan.PlanRef | None = None
    if name is None:  # D2/D3: derive the name from the active plan-ref
        plan_ref = cache.read_plan_ref(repo_root)
        if plan_ref is None:
            raise UserFacingCliError(
                f"Stage '{stage.id}' needs a saved plan — run /plan-save first "
                "(or pass --worktree NAME).",
                error_type="no_plan_ref",
            )
        name = resolve_plan_worktree_name(plan_ref)
        base_ref = plan_ref
    else:
        # Explicit --worktree NAME: best-effort recover the active plan-ref for the pinned base
        # ONLY — it drives the start-point but is NOT returned as `plan_ref` (which stays
        # None on this path, so a reuse-stage run never clobbers the named
        # worktree's own cache.plan-ref). A missing ref simply leaves plan_base=None.
        base_ref = cache.read_plan_ref(repo_root)

    plan_base = base_ref.base if base_ref else None
    plan_base = plan_base if plan_base and plan_base.strip() else None

    Ensure.invariant(
        "/" not in name and name not in ("", ".", ".."),
        f"Invalid worktree name '{name}' — no path separators.",
    )
    path = config.worktree_root / name
    resolved_base: str | None = None
    created = False
    # The §8.46 stacked routing: only the derived-name path (a real plan-ref) routes into the
    # parent-aware creation — the explicit --worktree, reuse, and `worktree: none` arms are
    # untouched.
    stacked = plan_ref is not None and plan_ref.delivery_lineage is not None
    if stage.worktree == "create":
        if stacked and base is not None:
            raise UserFacingCliError(
                f"--base is not accepted for a stacked layer (plan #{plan_ref.pr_id}): the "
                "parent is derived from the delivery train, never chosen.",
                error_type="invalid_input",
            )
        if path.exists():
            pass  # D4: idempotent reuse (resume) — do not fetch, re-base, re-create, or error
        elif materialize:
            _fetch_best_effort(repo_root)  # network sync first so a fresh origin/* is seen
            if stacked and not git.remote_ref_exists(repo_root, f"origin/{name}"):
                # Fresh stacked creation: the layer starts from the VERIFIED parent commit,
                # not a moving ref. An existing origin/plan-<id> (a resumed layer) keeps the
                # ordinary arm below — the parent-aware path only governs creation.
                prepared = prepare_stacked_layer(repo_root, plan_ref)
                resolved_base = prepared.parent_sha
                with io_step(
                    f"creating worktree {name} from {prepared.context.parent_branch} @ "
                    f"{prepared.parent_sha[:12]}"
                ) as s:
                    try:
                        git.worktree_add(
                            repo_root,
                            path,
                            branch=name,
                            create_branch=True,
                            base=prepared.parent_sha,
                        )
                    except GitError as exc:
                        raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
                    s.done(f"created worktree {name}")
                created = True
                # The session-scoped operational record (§8.46) — never authoritative;
                # publication re-verifies live.
                cache.ensure_layout(path)
                cache.write_layer_context(path, prepared.context, prepared.parent_sha)
            else:
                resolved_base = resolve_base(repo_root, name, base, plan_base)
                # The GitError raise escapes the step (dangling + the error text below, as
                # today).
                with io_step(f"creating worktree {name} from {resolved_base or 'local HEAD'}") as s:
                    try:
                        git.worktree_add(
                            repo_root, path, branch=name, create_branch=True, base=resolved_base
                        )
                    except GitError as exc:
                        raise UserFacingCliError(f"git worktree add failed: {exc}") from exc
                    s.done(f"created worktree {name}")
                created = True  # fresh creation only — gates the `[worktree] setup` hook
        elif stacked:  # dry-run create on a stacked layer: stays offline, names the derivation
            resolved_base = STACKED_DRY_RUN_BASE
        else:  # dry-run create: resolve the base from local refs only (no fetch, no create)
            resolved_base = resolve_base(repo_root, name, base, plan_base)
    else:  # reuse
        Ensure.path_exists(
            path,
            f"Worktree not found: {path}\nRun 'perk implement' first.",
        )
    return ResolvedWorktree(path=path, plan_ref=plan_ref, base=resolved_base, created=created)
