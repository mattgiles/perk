---
title: Hermetic pytest coverage of prompt-capable library APIs
read_when: You are testing a library API that can reach click.confirm/click.prompt, hit a pytest stdin-capture OSError, or pass locally but fail on a lean CI host.
cluster: toolchain-gotchas
---

# Hermetic pytest coverage of prompt-capable library APIs

Prompt-capable library entry points need a stronger test posture than their CLI adapters suggest.
The concrete anchors are the suite-wide guard in `tests/conftest.py`, the lean-host fixtures in
`tests/test_init_t5.py`, guided gestures in `src/perk/convergence/init/onboarding.py`, and the init
CLI's interactivity gate in `src/perk/cli/commands/init_cmd.py`.

## A direct library call bypasses the CLI interactivity gate

The init CLI computes interactivity from `--no-interactive`, `--json`, and stdin TTY state before
calling the library. A test that calls `run_init` directly bypasses that adapter and receives the
library default `interactive=True` unless it says otherwise.

Prompt reachability can then depend on the host. Gap-driven installers ask only when a required
tool is absent, so the same test stays green on a fully tooled developer machine but reaches a
prompt on lean CI. Under pytest capture, the result is usually a cryptic stdin-read `OSError`; under
a `CliRunner`, it can instead consume input silently.

Hermetic coverage needs **both** controls:

1. Pin the environment shape that makes the intended branch reachable. The established lean-CI
   fixture records git, gh, and Node as present, with Pi absent, rather than inspecting the host.
2. Pass `interactive=False` to the library entry point unless the test is specifically exercising
   a prompt.

These controls solve different problems. The environment fixture creates deterministic
reachability; the explicit flag guarantees the branch cannot prompt. A prompt guard alone cannot
provide reachability coverage because an unreached prompt never trips it on a fully tooled host.

## Patch where the prompt name is looked up

Import style determines the correct monkeypatch target. If a consuming module binds
`user_confirm` at import time, patch that consuming module's binding; changing the defining module
afterward does not replace the already-bound name. Gesture tests therefore patch the onboarding
module's prompt bindings.

The suite-wide backstop patches `click.confirm` and `click.prompt` themselves. That is the lowest
common seam reached by the normal wrappers and catches any unstubbed prompt family-wide. A test
that intentionally exercises prompting applies its own monkeypatch in the test body after autouse
fixture setup, so its explicit stub naturally replaces the refusal.

## The autouse refusal guard is diagnosis, not determinism

An autouse fixture in `tests/conftest.py` replaces real Click prompts with a descriptive
`AssertionError` that tells the author to stub the prompt seam or run non-interactively. This turns
the class of failure into a clear, actionable message everywhere it recurs and prevents accidental
input consumption under CLI runners.

Keep the responsibilities separate:

- Hermetic environment stubs and explicit interactivity arguments make tests deterministic.
- The autouse refusal guard detects any prompt path those tests forgot to control.
- Prompt-specific tests override the guard at the lookup seam they intend to exercise.

## Cross-references

- `docs/learned/workflow/init-doctor.md` — host primitives may need fixture stubs separate from
  init-facade gesture stubs
- `docs/learned/workflow/init-external-cli.md` — the gap-driven onboarding gesture and facade-patch
  discipline
- `docs/learned/toolchain/test-parallelism.md` — suite speed and host-independent determinism are
  separate axes
