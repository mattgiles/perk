"""The Node module census (the ``--import`` tracer arm) — filled in beside ``module_tracer.mjs``."""

# The SDK packages whose duplicate copies outside the Pi host root the census reports on. A
# reporting filter only — the specifier census later work pins is its own, not this constant.
SDK_PACKAGE_NAMES: tuple[str, ...] = (
    "@earendil-works/pi-coding-agent",
    "@earendil-works/pi-tui",
    "@earendil-works/pi-ai",
    "@earendil-works/pi-agent-core",
    "typebox",
)
