"""The Python plane's production prompt render seam.

:func:`render` loads templates by explicit ``name`` (root-relative under ``prompts/``), while
:func:`render_text` compiles caller-supplied source. Both APIs use one production Jinja Environment
and the same eager, string-only variable contract (the frozen mini-jinja subset,
``contracts.md §8.31``). ``StrictUndefined`` makes a missing variable fail loudly rather than render
an empty string. The TS twin remains the file-backed ``extension/substrate/prompts.ts`` API.

jinja2 is the **reference engine**: the committed golden bytes under
``prompts/_fixtures/golden/`` ARE this seam's output, and the TS twin's vendored mini-jinja renderer
(``extension/substrate/miniJinja.ts``) must reproduce them byte-for-byte. Golden parity is enforced
by ``tests/test_prompts.py`` + ``extension/substrate/prompts.test.ts``. The Environment config below
is the parity baseline both engines share (autoescape off, ``trim_blocks`` on so a block tag on its
own line emits no spurious newline — letting conditional templates keep their tags off the content
lines while preserving indentation — ``lstrip_blocks`` off, and ``keep_trailing_newline`` on so
jinja2 does not strip a trailing ``\\n`` the TS renderer keeps).
"""

from collections.abc import Mapping

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from perk._resources import prompts_dir

_loader = FileSystemLoader(str(prompts_dir()))
_env = Environment(
    loader=_loader,
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=False,
)


def _validate_variables(variables: Mapping[str, object]) -> None:
    for key, value in variables.items():
        if not isinstance(value, str):
            raise TypeError(
                f"perk prompts: variable {key!r} is {type(value).__name__}, not str "
                "(the render contract is string-only)"
            )


def render_text(template_text: str, variables: Mapping[str, object]) -> str:
    """Render maintainer-owned repository prompt source with ``variables``.

    Supported callers supply contained, trusted local source in the frozen mini-jinja subset
    (``contracts.md §8.31``). This low-level renderer is not a sandbox or runtime grammar validator:
    arbitrary remote or user-authored source must not be passed here, and out-of-subset Jinja
    constructs remain unsupported even when the production Environment accepts them.

    The variable map is validated eagerly and is **string-only**, matching :func:`render` and the
    TS twin's contract while using the production Environment and root-relative include loader.
    """
    _validate_variables(variables)
    return _env.from_string(template_text).render(variables)


def render(name: str, variables: Mapping[str, object]) -> str:
    """Load and render ``name`` (root-relative under ``prompts/``) with ``variables``.

    The render contract is **string-only** (the frozen mini-jinja subset, ``contracts.md §8.31``):
    every variable value must be a ``str``. This mechanically enforces the same contract the TS
    twin's vendored renderer enforces — the difference being only *when* it fires: the TS renderer
    throws lazily on a referenced non-string, this validates the whole var map eagerly. Both forbid
    the silent ``str(value)`` coercion (a future ``False`` must never render ``"False"``).
    """
    _validate_variables(variables)
    template_text, _, _ = _loader.get_source(_env, name)
    return render_text(template_text, variables)
