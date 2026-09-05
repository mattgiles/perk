"""The managed ``.gitignore`` + ``AGENTS.md`` blocks and the generic block applier."""

from pathlib import Path

from perk import __version__
from perk.substrate.paths import LOCAL_CONFIG_FILENAME

GITIGNORE_BEGIN = "# BEGIN perk managed"
GITIGNORE_END = "# END perk managed"
# Pi install caches + perk's transient tier-2 cache tree + per-user config +
# worktrees. The whole `.perk/workflow/` cache tree is gitignored (contracts.md §8.1) —
# runtime/cache state, not durable source; no committed `.gitkeep`. `.pi-subagents/` is the
# borrowed `pi-subagents` engine's project-scoped artifact root (debug artifacts + chain runs
# in the session cwd) — transient, never tracked. The conventional project agent dir's
# contents are ignored except models.json: exclude contents, not the directory itself, so
# negations work. Users can opt more files in with later rules after the managed block.
GITIGNORE_BODY = "\n".join(
    [
        "/.pi/npm/",
        "/.pi/git/",
        "/.pi/agent/*",
        "!/.pi/agent/models.json",
        f"/.perk/{LOCAL_CONFIG_FILENAME}",
        "/.worktrees/",
        "/.perk/workflow/",
        "/.pi-subagents/",
    ]
)

AGENTS_BEGIN = "<!-- BEGIN perk managed -->"
AGENTS_END = "<!-- END perk managed -->"


def _agents_inner() -> str:
    return f"""## perk conventions (managed by `perk init` — do not edit between these markers)

This repo is wired for the **perk** plan-oriented workflow on Pi.

- **`perk init` owns all Pi wiring and the `.perk/` dot-directory** — `.pi/settings.json`
  package entries, `.perk/config.toml`, `.gitignore` entries, this block. Re-run `perk init`
  to converge (idempotent); `perk doctor --fix` repairs oddities.
- **GitHub access goes through the `gh` CLI.** Never fetch `github.com` over raw HTTPS
  (curl/fetch) — private repos reject unauthenticated requests. Read-only `gh` query
  subcommands (view/list/diff/status/checks/search) work even in perk read-only sessions.
- **Prefer ast-grep for code search.** Structural/AST queries go through `ast-grep` (see the
  `ast-grep` skill); plain `grep` stays fine for literal text.

perk version: {__version__}"""


def _apply_managed_block(
    path: Path,
    *,
    begin: str,
    end: str,
    inner: str,
    label: str,
    header_if_new: str = "",
    apply: bool = True,
) -> list[str]:
    block = f"{begin}\n{inner.rstrip(chr(10))}\n{end}\n"
    old = path.read_text(encoding="utf-8") if path.is_file() else None

    if old is not None and begin in old and end in old:
        start = old.index(begin)
        stop = old.index(end) + len(end)
        new = old[:start] + block.rstrip("\n") + old[stop:]
        verb = "updated"
    else:
        base = old if old is not None else header_if_new
        if base and not base.endswith("\n"):
            base += "\n"
        if base and not base.endswith("\n\n"):
            base += "\n"
        new = base + block
        verb = "created"

    if new == old:
        return []
    if apply:
        path.write_text(new, encoding="utf-8")
    return [f"{label}: {verb}"]
