"""Cross-verb helpers for the `perk registry` group."""

from perk.cli.ensure import UserFacingCliError
from perk.registry import Registry, RegistryError, load_registry


def load_or_die() -> Registry:
    try:
        return load_registry()
    except RegistryError as exc:
        raise UserFacingCliError(str(exc)) from exc
