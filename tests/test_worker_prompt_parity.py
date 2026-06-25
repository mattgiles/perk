"""Cross-plane prompt-parity invariant.

The headless worker (`extension/worker/worker.ts` `initialPromptFor`) re-derives the
`implement`/`address` initial prompts in TypeScript, and MUST stay textually in lockstep with the
Python cold door (`perk/run/launch.py._implement_prompt`/`_address_prompt`). The `implement`
substrings here are the shared invariant: the SAME literals are asserted from the TS side in
`extension/worker/worker.test.ts`, so a drift in EITHER plane (someone edits one prompt but not the
other) fails CI here or there. The `address` body now renders from the canonical templates
`prompts/stages/address/*` (contracts.md §8.31), so its cross-plane byte-parity is proved by the
`address-*` live-parity cases; only the thin model-clause selection assertions remain here.
"""

from perk.run.launch import (
    _address_prompt,
    _implement_prompt,
    _learn_prompt,
    _plan_read_instruction,
)

# Keep in lockstep with ADDRESS_SUBSTRINGS in extension/worker/worker.test.ts.
# The linear plan-read instruction — keep in lockstep with LINEAR_READ_SUBSTRINGS in
# extension/worker/worker.test.ts (the literal fragments of the shared linear arm).
LINEAR_READ_SUBSTRINGS = [
    "use the `linear_get_issue` tool",
    "then `linear_list_comments`",
    "the plan body is the first comment",
    "if the linear tools are unavailable, open ",
]

_PLAN_REF = {
    "provider": "github",
    "pr_id": "148",
    "url": "https://github.com/mattgiles/perk/issues/148",
}


def test_implement_prompt_composes_template_with_read_cmd() -> None:
    """Thin composition guard (the live-parity case proves cross-plane byte-identity of the
    template; this proves the helper wires body + read_cmd + the inline progress paragraph)."""
    prompt = _implement_prompt(_PLAN_REF)
    assert prompt.startswith("You are implementing perk plan github #148")
    assert "gh issue view 148 --comments" in prompt
    assert prompt.endswith("otherwise don't invent step numbers.")


# The review-classifier model clause — byte-identical to ADDRESS_MODEL_CLAUSE in
# extension/worker/worker.test.ts. Drift in either plane fails the paired suites.
_ADDRESS_MODEL_CLAUSE = (
    ', passing `model: "test/model"` on that call '
    "(the configured [subagents] review-classifier model)"
)


def test_address_prompt_injects_classifier_model_when_configured() -> None:
    prompt = _address_prompt(_PLAN_REF, "test/model")
    assert _ADDRESS_MODEL_CLAUSE in prompt, "address prompt missing the configured model clause"


def test_address_prompt_omits_model_clause_when_unconfigured() -> None:
    assert "passing `model:" not in _address_prompt(_PLAN_REF)


def test_plan_read_instruction_selects_arm_per_provider() -> None:
    """Thin per-arm selection guard for the render-backed helper (the live-parity cases prove
    cross-plane byte-identity; this proves code picks the right arm and render() is wired)."""
    assert _plan_read_instruction("github", "42", "u") == "gh issue view 42 --comments"
    linear = _plan_read_instruction("linear", "uuid-1", "https://linear.app/x/ENG-1")
    for needle in LINEAR_READ_SUBSTRINGS:
        assert needle in linear, f"linear arm drifted — missing: {needle!r}"
    assert "use the `linear_get_issue` tool (id `uuid-1`)" in linear
    assert linear.endswith("open https://linear.app/x/ENG-1")
    assert _plan_read_instruction("gitlab", "9", "u") == "open u"


def test_implement_prompt_non_github_uses_open_url() -> None:
    ref = {"provider": "gitlab", "pr_id": "9", "url": "https://gl/x"}
    assert "open https://gl/x" in _implement_prompt(ref)


_LINEAR_PLAN_REF = {
    "provider": "linear",
    "pr_id": "a1b2c3d4-0000-0000-0000-000000000000",
    "url": "https://linear.app/acme/issue/ENG-123",
}


def test_implement_prompt_linear_carries_linear_read_substrings() -> None:
    """The linear arm of the implement prompt — the same literals are asserted from
    the TS side (LINEAR_READ_SUBSTRINGS in extension/worker/worker.test.ts)."""
    prompt = _implement_prompt(_LINEAR_PLAN_REF)
    for needle in LINEAR_READ_SUBSTRINGS:
        assert needle in prompt, f"linear implement prompt drifted — missing: {needle!r}"
    assert "open https://linear.app/acme/issue/ENG-123" in prompt


def test_learn_prompt_linear_reads_via_tools_and_keeps_gh_pr_derivation() -> None:
    """The linear learn prompt reads the plan via the linear tools but keeps the
    merged-PR derivation on `gh` — PRs are GitHub-universal under every issue backend.

    A thin selection test (cold renders the linear `read_cmd` + the `gh pr list --head plan-<pr_id>`
    block); the four `learn-*` live-parity cases now carry the cross-plane byte-parity."""
    prompt = _learn_prompt(_LINEAR_PLAN_REF)
    for needle in LINEAR_READ_SUBSTRINGS:
        assert needle in prompt, f"linear learn prompt drifted — missing: {needle!r}"
    assert f"gh pr list --head plan-{_LINEAR_PLAN_REF['pr_id']} --state merged" in prompt
