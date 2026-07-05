# Hello from the perk remote runner

The perk remote runner lets you take a saved perk plan and run it on a GitHub
Actions runner instead of your local machine. You kick it off with
`perk implement <N> --remote`, where `<N>` is the plan's issue number. A headless
worker then checks out the plan's `plan-<N>` branch, implements the plan's steps
there, and commits the work as it goes. When the implementation is complete, the
worker opens a draft pull request so you can review the result. This means a plan
can move from idea to draft PR without tying up your own workstation.
