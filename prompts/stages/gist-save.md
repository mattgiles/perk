perk /gist-save — persist the gist the session converged on.
1. If the gist is NOT yet a clear statement of intent, finish converging first, then call the tool.
2. Call the `gist_save` tool NOW, passing `prose` (the gist's full prose — problem-focused intent, no implementation steps) and, when settled, `scope` (`plan` or `objective`).
{% if title %}
3. Pass `title: "{{ title }}"` as the gist title.
{% else %}
3. `title` is optional (defaults to the prose's first heading).
{% endif %}
4. The tool persists the gist via `perk gist create` and terminates the turn. Judgment + durable writes stay with you.
