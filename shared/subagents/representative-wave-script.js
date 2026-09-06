const reports = await runs.all([
  {
    "key": "plan-fidelity",
    "agent": "perk.pr-reviewer",
    "task": "angle: plan-fidelity — review ONLY plan fidelity & completeness.",
    "extensionBindings": {
      "perk.parent-restrictions/1": {
        "readOnly": false
      }
    },
    "label": "plan-fidelity",
    "phase": "review"
  },
  {
    "key": "custom-scope",
    "agent": "perk.pr-reviewer",
    "task": "angle: custom-scope — review ONLY the requested scope.",
    "extensionBindings": {
      "perk.parent-restrictions/1": {
        "readOnly": false
      }
    },
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
    "extensionBindings": {
      "perk.parent-restrictions/1": {
        "readOnly": false
      }
    },
    "skill": "ponytail-review",
    "label": "ponytail"
  }
]);
return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));