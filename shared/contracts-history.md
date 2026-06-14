# perk cross-plane contracts — history

The changelog sibling of [`contracts.md`](./contracts.md). It carries the relocated chronological
`Status (…)` history so the spec file stays a compact current-spec document — the durable `## §N.M`
contract bodies live in `contracts.md`; the present-tense-of-a-past-node landing notes live here.
This file ships in **both** build artifacts alongside `contracts.md` (the whole `shared/` dir is
bundled — the Python wheel as package data `perk/_shared/`, the npm package under `shared/`).

## Entry convention

- Entries are **grouped by the originating `§N.M` anchor**, in `contracts.md`'s section order.
- **Chronological within** each group (oldest landing first).
- Each entry is the original `Status (…)` blockquote **verbatim** — keep-and-annotate, never
  reword, never "fix" a now-stale claim (the relocation is mechanical; reconciliation judgment
  stays out).
- Each group's `§N.M` heading **is** the cross-reference anchor.
- **Exception:** document-opening statuses not bound to a single section live under the leading
  **"General / opening"** group below.

## General / opening

> **Status (T2):** specs locked. Implementations land later — state helpers in **T3**, the
> launch/`PERK_RUN_ID` emit in **T4**, the gateway verification ops in **T5** (Python) /
> Phase 1 (TS). Gateway *mutation* ops are named here but **not authored** (payloads land in
> Phase 1, when `/plan-save` knows their shape — `Q7`/`Q9`).
>
> **Status (T5):** the §8.4 **verification ops are implemented in the Python plane**
> (`perk/github/auth.py` — `check_auth` / `check_repo_access`, verification-only, never mutating);
> the TS plane authors the same shapes in Phase 1. The §8.5 init machine-surface contract is
> live (`perk init --json`).
>
> **Status (P1.T2a):** the §8.4 **plan-write mutations are implemented in the Python plane**
> (`perk/github/plans.py` `create_label` / `create_plan_issue` / `add_issue_comment` /
> `find_plan_issue` + `perk/plan.py` storage) — the **cold/worker** save door
> (`perk plan-save`). The warm in-session twin (the TS `/plan-save` tool) is T3. Both planes
> use **REST `gh api`** (never porcelain — porcelain's GraphQL has a separate, often-exhausted
> rate-limit quota) and pass large bodies via `-F body=@file`.
