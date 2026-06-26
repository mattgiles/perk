perk /objective-save — persist the objective the session converged on.
1. If the objective + roadmap are NOT yet decision-complete, finish converging first, then call the tool.
2. Call the `objective_save` tool NOW, passing `prose` (the decision-complete objective prose) and `roadmap` (the STRUCTURED roadmap as a JSON array of nodes, each with a stable `id` and `description`) — NEVER hand-write the roadmap as YAML.
{% if title %}
3. Pass `title: "{{ title }}"` as the objective title.
{% else %}
3. `title` is optional (defaults to the prose's first heading).
{% endif %}
4. The tool creates the perk:objective issue, activates it, starts budget tracking, and terminates the turn. Judgment + durable writes stay with you.