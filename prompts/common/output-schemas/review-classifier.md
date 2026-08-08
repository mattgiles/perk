{
  "type": "object",
  "additionalProperties": false,
  "required": ["pr", "review_threads", "discussion_comments", "counts"],
  "properties": {
    "pr": {"type": "integer"},
    "review_threads": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["thread_id", "classification", "path", "line", "summary"],
        "properties": {
          "thread_id": {"type": "string"},
          "classification": {"type": "string", "enum": ["actionable", "informational", "praise", "question"]},
          "path": {"type": ["string", "null"]},
          "line": {"type": ["integer", "null"]},
          "summary": {"type": "string"}
        }
      }
    },
    "discussion_comments": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["comment_id", "classification", "summary"],
        "properties": {
          "comment_id": {"type": "integer"},
          "classification": {"type": "string", "enum": ["actionable", "informational", "praise", "question"]},
          "summary": {"type": "string"}
        }
      }
    },
    "counts": {
      "type": "object",
      "additionalProperties": false,
      "required": ["actionable", "informational", "praise", "question"],
      "properties": {
        "actionable": {"type": "integer"},
        "informational": {"type": "integer"},
        "praise": {"type": "integer"},
        "question": {"type": "integer"}
      }
    }
  }
}
