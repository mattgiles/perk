{
  "type": "object",
  "additionalProperties": false,
  "required": ["node", "relevant_files", "symbols", "anchors", "patterns", "open_questions"],
  "properties": {
    "node": {"type": "string"},
    "relevant_files": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["path", "why"],
        "properties": {
          "path": {"type": "string"},
          "why": {"type": "string"}
        }
      }
    },
    "symbols": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["name", "path", "why"],
        "properties": {
          "name": {"type": "string"},
          "path": {"type": "string"},
          "why": {"type": "string"}
        }
      }
    },
    "anchors": {"type": "array", "items": {"type": "string"}},
    "patterns": {"type": "array", "items": {"type": "string"}},
    "open_questions": {"type": "array", "items": {"type": "string"}}
  }
}
