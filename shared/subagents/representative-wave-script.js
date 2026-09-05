const reports = await runs.all([
  {
    "key": "plan-fidelity",
    "agent": "perk.pr-reviewer",
    "task": "angle: plan-fidelity — review ONLY plan fidelity & completeness.",
    "label": "plan-fidelity",
    "phase": "review"
  },
  {
    "key": "custom-scope",
    "agent": "perk.pr-reviewer",
    "task": "angle: custom-scope — review ONLY the requested scope.",
    "label": "custom-scope-lane",
    "outputSchema": {
      "type": "object",
      "properties": {
        "angle": {
          "enum": [
            "custom-scope"
          ]
        }
      }
    }
  },
  {
    "key": "ponytail",
    "agent": "perk.pr-reviewer",
    "task": "angle: ponytail — the standalone simplification pass.",
    "skill": "ponytail-review",
    "label": "ponytail"
  }
]);
return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));