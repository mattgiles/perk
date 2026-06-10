"""perk CLI commands.

Two layouts (python-cli-guidelines §8.1): command **groups** are directories —
`{group}/__init__.py` (group def + registration), `{group}/{verb}_cmd.py` per verb, and an
optional `{group}/shared.py` for cross-verb helpers (nested groups nest dirs). Top-level
commands stay flat single files (`{name}_cmd.py`).
"""
