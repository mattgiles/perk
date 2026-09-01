---
title: "Models and compaction"
description: "The [models] hierarchy and [compaction] keys that choose AI defaults and manage session context."
sidebar:
  order: 3034
---

# Models and compaction

The `[models]` hierarchy chooses repository, stage, and perk-agent defaults. `[compaction]`
combines settings converged into Pi's project settings with the objective runtime threshold.

## `[models]`

Which AI runs where. One namespace contains the repository-default `default` and `thinking` keys,
per-stage `[models.stages.<id>]` sub-tables, and the per-agent `[models.subagents]` table.
Precedence is visible as nesting: an explicit launch flag beats a stage override, which beats the
repository default.

The **repository-default model and thinking level** are converged by `perk init` and
`perk doctor --fix` into `.pi/settings.json`'s top-level `defaultProvider`, `defaultModel`, and
`defaultThinkingLevel` keys, which Pi reads natively at session boot. Because they land in the
committed settings file, they apply to **every** Pi session in the repo: perk cold doors, plain
`pi`, and the headless worker, locally or remotely. The worker resolves its model from the
checkout's disk-layered settings.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `default` | string (`provider/id`) | _(Pi default)_ | Must be an **exact** `provider/id` pair; Pi's settings default is an exact provider-and-id lookup, not a fuzzy match. It splits on the **first** `/`, so OpenRouter ids retain inner slashes (`openrouter/meta-llama/llama-3-70b` becomes provider `openrouter`, id `meta-llama/llama-3-70b`). A `:thinking` suffix is accepted. |
| `thinking` | string | _(Pi default)_ | One of `off`, `minimal`, `low`, `medium`, `high`, or `xhigh`. |

Either key may be set alone. A `:thinking` suffix on `default`, such as
`default = "anthropic/claude-opus-4-1:high"`, is split at convergence. The final colon segment
counts as a thinking level only when it is one of Pi's levels, so an Ollama-style tag such as
`ollama/llama3:70b` stays part of the model id. An explicit `thinking` key **wins** over a
differing suffix, and `perk doctor` warns on the conflict. An invalid `thinking` value or a
`default` without `/` is a **hard config error**; `perk doctor`'s `config` check pinpoints the
field.

`default` and `thinking` are **committed-only**: perk reads them from `.perk/config.toml`, never
the `.perk/local.toml` overlay. Their `[models.stages.<id>]` and `[models.subagents]` siblings are
overlay-aware. This keeps committed `.pi/settings.json` a deterministic function of committed
configuration. Per-user escape hatches are `perk <stage> --model`, a local
`[models.stages.<id>]` override, or the in-session model switch. Convergence is
**write-when-present and leave-when-absent** per key: an absent table or key leaves a pre-existing
settings default untouched, and removing the keys leaves previously written settings in place
to clean up by hand. perk cannot prove ownership of a bare settings key, the same residual as
`[compaction]`. A committed `[models] default` also beats a user's global
`~/.pi/agent/settings.json` default because Pi layers project settings over global settings.

**Cold-launch precedence:** explicit `perk <stage> --model` or `--thinking` flags >
`[models.stages.<id>]` > committed `[models]` values converged into project settings > Pi's
curated per-provider defaults > the first authenticated model. Subagents are independent:
`[models.subagents]` > agent frontmatter `model:`. The project settings default does not apply to
perk's agents, which carry a frontmatter model.

```toml
[models]
default = "anthropic/claude-opus-4-1"
thinking = "high"
```

> **Related settings convergence (no config knob):** alongside the `[compaction]` and `[models]`
> convergences, perk converges the non-config-driven constant
> `"subagents": {"disableBuiltins": true}` into the same perk-managed `.pi/settings.json` slice.
> pi-subagents' built-in agents are disabled in every perk repo; perk borrows the delegation
> engine and ships its own `perk.*` agents. There is no `.perk/config.toml` knob. To re-enable one
> built-in, add a project-settings per-agent entry:
> `"subagents": {"agentOverrides": {"<name>": {"disabled": false}}}`. perk owns only
> `disableBuiltins`, so sibling keys survive init and doctor.
>
> perk also **seeds** `"tuiMode": "fullscreen"` into the same slice, but only when the key is
> absent. To opt out, set `"tuiMode": "regular"` in `.pi/settings.json`; the value survives init
> and doctor. Pi's `/settings` toggle writes the global settings file, which the committed project
> key overrides, so the durable opt-out is the project key itself.

## `[models.stages.<id>]`

Per-stage **model** and **thinking-level** defaults, injected as Pi `--model` and `--thinking`
flags when `perk <stage>` cold-launches that stage's Pi session. Each stage is its own sub-table,
such as `[models.stages.implement]` or `[models.stages.plan]`.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `model` | string (model id) | _(Pi default)_ | A free-form Pi model string such as `anthropic/claude-opus-4-1`; perk does not validate it, and Pi resolves it at session start. A `model:thinking` suffix also works because Pi's `--model` accepts it. |
| `thinking` | string | _(Pi default)_ | One of `off`, `minimal`, `low`, `medium`, `high`, or `xhigh`. |

Either key may be set alone. When a stage configures **neither**, perk injects nothing and leaves
Pi's model and thinking resolution untouched. That resolution falls through to the
`[models]`-converged project settings when configured. An explicit command-line flag wins:
`perk implement --model X` overrides `[models.stages.implement] model` because perk injects the
configured flag first and Pi parses the last value.

Valid ids are registry stages (`plan`, `implement`, `address`, `learn`, `objective-author`,
`objective-plan`, and the other entries shown by `perk registry`). This is a **launch-seam**
setting: it applies only when a stage cold-launches an interactive Pi session. Warm in-session
transitions inherit the launched session's model, and the remote CI runner is unaffected.

The sub-tables are **overlay-aware**. A `.perk/local.toml` `[models.stages.<id>]` table leaf-merges
over committed values. `perk doctor` validates stage ids against the registry and thinking
levels against Pi's set. An unknown stage id or invalid thinking level is a loud, non-fatal
`warn`, never a failure.

```toml
[models.stages.implement]
model = "anthropic/claude-opus-4-1"
thinking = "high"

[models.stages.plan]
thinking = "xhigh"
```

## `[models.subagents]`

Per-agent model overrides for each perk-owned project agent.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `pr-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the PR-reviewer agent. |
| `review-classifier` | string (model id) | _(agent frontmatter default)_ | Model for the review-classifier agent, consumed by `classify_review_feedback` at execute time. |
| `objective-explorer` | string (model id) | _(agent frontmatter default)_ | Model for the objective-explorer agent, consumed by `explore_objective_node` at execute time. |
| `conflict-resolver` | string (model id) | _(agent frontmatter default)_ | Model for the conflict-resolver agent spawned by `/submit` on merge conflicts and by `/objective-sync`'s retained-continuation drive. |
| `learn-analyst` | string (model id) | _(agent frontmatter default)_ | Model for the learn-analyst agent used by `/learn` to analyze a landed plan's session evidence. |
| `adversarial-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the adversarial-reviewer agent spawned by `/pr-review-terminal` and `/pr-review-browser`. |
| `draft-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for streamed draft review from `/plan-review-browser` and `/objective-review-browser`. |
| `harvest-analyst` | string (model id) | _(agent frontmatter default)_ | Model for each `docs/learned` mining lane in `perk learn harvest`. |
| `dream-analyst` | string (model id) | _(agent frontmatter default)_ | Model for each `docs/learned` cluster-audit lane in `perk learn dream`'s analyst wave, consumed by `run_dream_wave` at execute time. |
| `dream-reducer` | string (model id) | _(agent frontmatter default)_ | Model for the three fixed reducer lanes in `perk learn dream`'s reducer wave, consumed by `run_dream_wave` at execute time. |
| `session-auditor` | string (model id) | _(agent frontmatter default)_ | **Dev-only** — model for perk's own repository's session-audit judgment wave. The agent definition is repo-local, not delivered by `perk init`, so the key is dormant in consumer repos. |

An absent key falls back to the agent's frontmatter default. The table is **fixed-key**: it
configures only perk's own agents, delivered into the perk-managed `.pi/agents/perk/` directory
by `perk init`, except for the dev-only `session-auditor`. It has no effect on custom subagents,
which set their model in frontmatter.

A value may carry a **`:thinking` suffix** to set that agent's thinking level, such as
`pr-reviewer = "anthropic/claude-sonnet-4-5:high"`. The last colon segment counts as a thinking
level only when it is one of `off`, `minimal`, `low`, `medium`, `high`, or `xhigh`, so an
Ollama-style tag such as `llama3:70b` stays part of the model id. The special value **`inherit`**
makes the agent inherit the parent session's model. `perk doctor` warns on a suspicious suffix:
an alphabetic final segment that is not a Pi thinking level, such as a `:hgih` typo, would
otherwise silently become part of the model id.

```toml
[models.subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5:high"
review-classifier = "anthropic/claude-haiku-4-5"
```

## `[compaction]`

How a session manages its context. The `enabled`, `reserve_tokens`, and `keep_recent_tokens` keys
tune Pi's auto-compaction for `perk <stage>` sessions. They are **committed-only**, converged into
`.pi/settings.json`'s `compaction` object by `perk init` and `perk doctor --fix`; editing them
requires re-running init or doctor. Convergence is **write-when-present and leave-when-absent**
per key: absent keys leave existing Pi settings untouched, while removing previously converged
keys leaves those settings in place to clean up by hand. The `objective_threshold` sibling is
**runtime-read** and overlay-aware in the extension instead.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | _(Pi default)_ | Turns Pi's auto-compaction on or off. |
| `reserve_tokens` | int (> 0) | _(Pi default)_ | Tokens reserved for the response. |
| `keep_recent_tokens` | int (> 0) | _(Pi default)_ | Recent tokens kept verbatim. |
| `objective_threshold` | float in `(0,1]` | `0.8` | The context-usage fraction that triggers compaction **while an objective is active**. It is a native float (`0.8`, not `"0.8"`) and is never converged into `settings.json`. |

```toml
[compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000
objective_threshold = 0.8
```

## Related

- **Do:** [How to write a custom subagent](../../how-to/write-a-custom-subagent.md) — define an agent outside perk's fixed override table.
- **Look up:** [Model-facing tools](../in-session/model-tools.md) — inspect the tools exposed inside sessions.
- **Look up:** [Configuration files](../configuration.md) — file precedence, value types, and the family map.
