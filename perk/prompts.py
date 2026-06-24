"""The Python plane's prompt render seam (TS twin: ``extension/substrate/prompts.ts``).

Templates are loaded by explicit ``name`` (root-relative under ``prompts/``) via
:func:`perk._resources.prompts_dir`, the same directory the TS twin reads. The feature
surface is intentionally small — ``{{ var }}`` substitution and ``{% include %}`` — and
``StrictUndefined`` makes a missing variable fail loudly rather than render an empty string.

jinja2 is the **reference engine**: the committed golden bytes under
``prompts/_fixtures/golden/`` ARE this seam's output, and the nunjucks twin (and the future
vendored renderer) must reproduce them byte-for-byte. Golden parity is enforced by
``tests/test_prompts.py`` + ``extension/substrate/prompts.test.ts``. The Environment config
below is the parity baseline both engines share (autoescape off, ``trim_blocks`` on so a block
tag on its own line emits no spurious newline — letting conditional templates keep their tags
off the content lines while preserving indentation — ``lstrip_blocks`` off, and
``keep_trailing_newline`` on so jinja2 does not strip a trailing ``\\n`` that nunjucks keeps).
"""

from collections.abc import Mapping

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from perk._resources import prompts_dir

_env = Environment(
    loader=FileSystemLoader(str(prompts_dir())),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=False,
)


def render(name: str, variables: Mapping[str, object]) -> str:
    """Render the template at ``name`` (root-relative under ``prompts/``) with ``variables``."""
    return _env.get_template(name).render(variables)
