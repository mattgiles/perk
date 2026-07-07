{{ marker }}
This implement session tracks progress through the `@juicesharp/rpiv-todo` checklist overlay — the
selected todo provider (`[providers] todo = "juicesharp-todo"`). perk's own checkpoint surface has
stepped aside (Node 3.1), so the foreign overlay is the sole progress surface here.

Carry perk's implement-progress discipline onto that overlay: seed it from the plan body's
`## Steps` numbered list — one checklist item per step, in order — then mark each item complete as
you finish the corresponding step, the same gather-then-advance flow perk's checkpoints embody. Use
the overlay's own controls to add and complete items; you do not need perk's `[WIP:n]`/`[DONE:n]`
markers here (perk's checkpoint scanner is deferred under this selection). If the plan has no
`## Steps` list, there is nothing to seed — let the overlay behave as its defaults suggest.