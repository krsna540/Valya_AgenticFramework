---
name: json-formatter
description: Parses a raw JSON string and returns it pretty-printed with a given indent. Use when the user pastes minified or messy JSON and wants it readable.
license: MIT
metadata:
  category: text
  origin: built-in
---

# json-formatter

Parses a raw JSON string and returns it pretty-printed, keys sorted.

## When to use

- The user pastes minified or messy JSON and wants it readable.

## How to use

```
python3 scripts/json_formatter.py '{"b":1,"a":[1,2,3]}' --indent 2
-> {
     "a": [1, 2, 3],
     "b": 1
   }
```

`--indent` defaults to 2 and must be between 0 and 8. Exits non-zero with an
error message on invalid JSON.

This was previously a platform-executed handler_key skill (`json_formatter`
in `app/skills/catalog.py`). Nothing in this skill is executed
automatically — an agent runs `scripts/json_formatter.py` itself if and when
it decides to.
