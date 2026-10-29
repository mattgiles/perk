"""The experimental pi-durable v2 door (contracts.md §8.77).

Exterior launch only: the door mints the execution id, chooses the store directory under the main
checkout's ``.perk/executions/`` and the workspace identity, invokes the TypeScript v2 host
(``extension/pi/v2/door/main.ts``), and validates the one JSON door envelope it prints. Python
never reads or writes an execution store — the host is its one advancement owner. Hidden, perk's
own source checkout only, and not shipped.
"""
