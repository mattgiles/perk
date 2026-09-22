"""``perk-dev profile-startup`` — repeatable measurement of perk's cold startup.

The command drives each subject's real ``perk`` console script through a pseudo-terminal under
Pi's offline startup-benchmark mode, alternates subjects sample by sample after one discarded
warm-up each, records per-subject provenance, and writes a run directory with raw samples plus a
JSON + Markdown summary. Profiled runs (the Python stop-before-exec arms and the Node module
census) are separate spawns, never mixed into the timing statistics.

Module map: ``timings`` (Pi's startup-timing report grammar + the stateful startup marker),
``pty_session`` (the one PTY spawn), ``subjects`` (subject specs, preflight, trust, the
provenance stamp), ``handoff`` (the Python arms over ``exec_pi``'s ``PERK_PROFILE_HANDOFF``
seam), ``census`` + ``module_tracer.mjs`` (the Node module census), ``summary`` (statistics,
the ``--json`` snapshot, the Markdown render), ``harness`` (the run orchestration), ``cli``
(the Click verb).
"""
