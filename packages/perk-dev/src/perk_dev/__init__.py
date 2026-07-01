"""perk-dev — perk's internal maintainer/release tooling (dev-only; never published).

This workspace member depends on the root ``perk`` package so it can reuse perk's
version-reading (``perk.__version__``) and git/LBYL helpers (``perk.substrate.git``).
It carries no independent version: the version story is perk's.
"""
