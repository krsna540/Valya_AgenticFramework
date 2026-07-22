---
name: calculator
description: Evaluates a plain arithmetic expression (+, -, *, /, %, **, parentheses). Use for numeric questions.
license: MIT
metadata:
  category: math
  origin: built-in
---

# calculator

Evaluates a restricted arithmetic expression safely — numbers, `+ - * / % **`,
parentheses, unary +/-. Deliberately not a general `eval()`: no names, no
function calls, no attribute access, so there is no code-execution surface
even though the input may come straight from a chat message.

## When to use

- The user asks a numeric question, e.g. "what's 12 * (3 + 4) - 5?"

## How to use

```
python3 scripts/calculator.py "12 * (3 + 4) - 5"
-> 79
```

Exits non-zero with an error message on malformed input (e.g. division by
zero, or anything beyond arithmetic like `__import__(...)`).

This was previously a platform-executed handler_key skill (`calculator` in
`app/skills/catalog.py`); the safe-AST-walker approach is preserved as-is
here since it's the load-bearing security property. Nothing in this skill is
executed automatically — an agent runs `scripts/calculator.py` itself if and
when it decides to.
