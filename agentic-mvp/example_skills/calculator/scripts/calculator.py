#!/usr/bin/env python3
"""Evaluates a plain arithmetic expression (+, -, *, /, %, **, parentheses).

Usage:
    python3 calculator.py "12 * (3 + 4) - 5"

Prints the numeric result. Exits non-zero with an error message on
malformed input.

Deliberately not a general `eval()`: a restricted AST walker accepts only
numbers, +-*/%**, parens, and unary +/- — no names, no calls, no attribute
access, so there is no code-execution surface even though the expression
may come straight from a chat message.

This is agent-invoked, not platform-executed: nothing in this skill folder
runs automatically when the skill is uploaded or attached to an agent (see
../SKILL.md).
"""
import ast
import operator
import sys

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: calculator.py '<expression>'", file=sys.stderr)
        sys.exit(2)
    expression = " ".join(sys.argv[1:])
    try:
        tree = ast.parse(expression, mode="eval")
        value = _safe_eval(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError) as e:
        print(f"could not evaluate {expression!r}: {e}", file=sys.stderr)
        sys.exit(1)
    print(value)


if __name__ == "__main__":
    main()
