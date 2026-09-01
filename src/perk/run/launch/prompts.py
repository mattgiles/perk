"""Cold-door seed-prompt builders.

The worker-prompt-parity twins: the
stage dispatcher (:func:`_initial_prompt`), the per-backend plan-read instruction
(:func:`_plan_read_instruction`), the implement/address/learn primers, and the prompt assembler
(:func:`_resolve_prompt`) that appends the resolved skill bindings. Each builder is byte-identical
to its TypeScript twin (``stageExecution.ts`` / ``substrate/prompts.ts`` /
``lifecycleGates.ts``); drift in either plane fails the
paired parity suites.

The binding suffix is the **cold-local** delivery arm only: warm sessions and the remote worker
receive the same rendered content via Mechanism A (in-session injection, dedup'd by the shared
header) — byte-parity enforced by ``tests/test_binding_render_parity.py`` (contracts.md §8.38).
"""

from pathlib import Path

from perk import plan
from perk.prompts import render
from perk.run.launch.worktree import ResolvedWorktree
from perk.substrate.binding_delivery import render_cold_bindings
from perk.substrate.config import Config
from perk.substrate.output import log_warn
from perk.substrate.registry import Stage


def _initial_prompt(
    stage: Stage,
    plan_ref: plan.PlanRef | None,
    preview: bool = False,
) -> str | None:
    """The first message ``pi`` is launched with, so the session *starts working* rather than
    opening idle. ``implement``, ``address``, and ``learn``
    are primed; ``None`` (no prompt) for other stages — e.g. ``plan`` is user-driven."""
    if plan_ref is None:
        return None
    if stage.id == "implement":
        return _implement_prompt(plan_ref)
    if stage.id == "address":
        return _address_prompt(plan_ref, preview=preview)
    if stage.id == "learn":
        return _learn_prompt(plan_ref)
    return None


def _plan_read_instruction(provider: str, pr_id: str, url: str) -> str:
    """The per-backend plan-read instruction — the prompt SSOT for "how do I read the
    saved plan". Byte-identical to `extension/substrate/prompts.ts::planReadInstruction` (the TS
    twin); drift in either plane fails the paired parity suites. ``github`` reads via `gh`;
    ``linear`` points at the pi-mono-linear tools with an `open <url>` fallback; any other
    provider falls back to opening the url.

    The wording now lives in the canonical templates ``prompts/common/plan-read/*.md``, rendered
    identically by both planes via the shared render seam (contracts.md §8.31); branching stays in
    code — only the arm chosen and the vars passed differ. Golden-fixture parity (the three
    `plan-read-*` cases) plus a thin per-arm selection test replace the dedicated substring parity.
    """
    if provider == "github":
        return render("common/plan-read/github.md", {"pr_id": pr_id, "url": url})
    if provider == "linear":
        return render("common/plan-read/linear.md", {"pr_id": pr_id, "url": url})
    return render("common/plan-read/other.md", {"pr_id": pr_id, "url": url})


def _implement_prompt(plan_ref: plan.PlanRef) -> str:
    """The implement-stage primer. The wording lives in the canonical template
    ``prompts/stages/implement.md``, rendered identically by both planes via the shared render seam
    (contracts.md §8.31); branching stays in code — only the ``read_cmd`` var (the provider-selected
    plan-read instruction) differs. Byte-identical to its TS twins
    ``stageExecution.ts::initialPromptFor``
    and ``lifecycleGates.ts::implementHandoffPrompt`` (the warm handoff now carries the same
    "Progress tracking:" tail — the prior shorter near-copy omission is removed). One golden case
    (`implement-github`) plus the thin per-plane composition tests replace the substring parity.
    """
    provider = plan_ref.provider
    pr_id = plan_ref.pr_id
    url = plan_ref.url
    read_cmd = _plan_read_instruction(provider, pr_id, url)
    return render(
        "stages/implement.md",
        {"provider": provider, "pr_id": pr_id, "url": url, "read_cmd": read_cmd},
    )


def _address_prompt(plan_ref: plan.PlanRef, preview: bool = False) -> str:
    """Prime the address stage: classify feedback in an isolated child (the
    ``classify_review_feedback`` tool — it owns the wave mechanics and reads the configured
    ``[models.subagents] review-classifier`` model at execute time), fix only actionable items,
    then resolve the threads. The perk-address skill (the judgment layer) is delivered by
    the skill-binding mechanism, not hardcoded here.

    When ``preview`` is set (the cold ``perk pr address --preview`` flag, mirroring the warm
    ``addressGuidance(preview=true)`` shape), the prompt stops after surfacing the classification:
    the model takes NO action (no fix/resolve/land tail).

    The wording lives in the canonical templates ``prompts/stages/address/*`` (contracts.md
    §8.31); branching stays in code — the preview/action split selects which template to render.
    All three address consumers (this builder, the worker's ``initialPromptFor("address")``, and
    the warm ``addressGuidance``) converge on the same two templates."""
    provider = plan_ref.provider
    pr_id = plan_ref.pr_id
    url = plan_ref.url
    variables = {"provider": provider, "pr_id": pr_id, "url": url}
    if preview:
        return render("stages/address/preview.md", variables)
    return render("stages/address/action.md", variables)


def _learn_prompt(plan_ref: plan.PlanRef) -> str:
    """Prime the learn stage: investigate the just-landed change and capture durable learnings.
    The perk-learn skill (the judgment layer) is delivered by the skill-binding
    mechanism, not hardcoded here.

    ``pr_id`` is the **plan-issue** number, not the PR; by the time learn runs the PR is merged
    and is discoverable via its head branch ``plan-<pr_id>``.

    The wording lives in the canonical template ``prompts/stages/learn.md``, rendered identically
    by both planes via the shared render seam (contracts.md §8.31); the github/linear/other/no-ref
    branching is the template conditional on ``provider`` (+ ``pr_id`` presence), and ``read_cmd``
    is the node-2.1 plan-read instruction. Byte-identical to its TS twin
    ``lifecycleGates``/``learning/prose.ts::learnGuidance`` (no worker twin — learn has only
    cold + warm).
    Four ``learn-*`` golden cases per provider arm replace the dedicated substring parity.
    """
    provider = plan_ref.provider
    pr_id = plan_ref.pr_id
    url = plan_ref.url
    read_cmd = _plan_read_instruction(provider, pr_id, url)
    return render(
        "stages/learn.md",
        {"provider": provider, "pr_id": pr_id, "url": url, "read_cmd": read_cmd},
    )


def _resolve_prompt(
    *,
    stage: Stage,
    resolved: ResolvedWorktree,
    repo_root: Path,
    config: Config,
    prompt_override: str | None,
    binding_trigger: str | None,
    preview: bool = False,
    prompt_suffix: str | None = None,
) -> str | None:
    """Assemble the initial prompt for a cold-local launch (prompt + suffix + skill bindings).

    See :func:`launch_stage`'s docstring for the ``prompt_override``/``binding_trigger``/
    ``prompt_suffix`` semantics. ``prompt_suffix`` is augment-only (mirroring binding delivery's
    D2 rule): it is appended between the resolved stage prompt and the binding suffix, and never
    synthesizes a prompt — an idle launch (no stage prompt) stays idle and the suffix is dropped.
    """
    # Prime the session from the ONE resolved ref (launch authority — an explicit --worktree
    # resolves through its own binding, so there is no root-selector fallback here). A
    # `prompt_override` wins outright.
    prompt = prompt_override
    if prompt is None:
        prompt = _initial_prompt(stage, resolved.plan_ref, preview=preview)
    # Augment-only suffix (caller-supplied judgment, e.g. the resume prior-work advisory):
    # appended after the stage prompt and before the binding suffix; never synthesizes a prompt.
    if prompt is not None and prompt_suffix is not None:
        prompt = f"{prompt}\n\n{prompt_suffix}"
    # Append the resolved skill bindings (defaults ⊕ user overlay) for this launch's
    # trigger — the single delivery path for perk's own nudges. Resolver issues + delivery warnings
    # are surfaced loud-but-non-fatal and never block a launch. Delivery AUGMENTS an existing
    # prompt only (D2): an idle launch (no _initial_prompt) stays idle — the warm door's Mechanism A
    # delivers the binding there — so the binding never synthesizes a prompt and auto-starts a turn.
    trigger = binding_trigger or f"stage:{stage.id}"
    delivery = render_cold_bindings(config.user_bindings, repo_root, trigger)
    for issue in delivery.issues:
        log_warn(f"skill binding: {issue}")
    for warning in delivery.warnings:
        log_warn(warning)
    if delivery.text and prompt is not None:
        prompt = f"{prompt}\n\n{delivery.text}"
    return prompt
