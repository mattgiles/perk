# Hello from the perk remote runner

Launching an unattended stage with `--remote` (for example `implement` or `address`) dispatches the
managed `perk-run.yml` GitHub Actions workflow instead of driving the stage locally. The workflow
checks out the plan branch, installs perk plus pi, and runs the stage headlessly through
`perk run-worker` and the Node worker. When the run finishes, its outcome is reported back onto the
plan issue as a run-report comment and mirrored into the job summary. This lets a plan advance
entirely in CI, with no attended terminal, while the plan issue stays the canonical record of what
happened.
