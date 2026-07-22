#!/usr/bin/env python3
"""Parses a raw JSON string and returns it pretty-printed, keys sorted.

Usage:
    python3 json_formatter.py '{"b":1,"a":[1,2,3]}' --indent 2

Prints the formatted JSON. Exits non-zero with an error message on invalid
JSON or an out-of-range --indent.

This is agent-invoked, not platform-executed: nothing in this skill folder
runs automatically when the skill is uploaded or attached to an agent (see
../SKILL.md).
"""
import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_json")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    if not (0 <= args.indent <= 8):
        print("--indent must be between 0 and 8", file=sys.stderr)
        sys.exit(1)

    try:
        parsed = json.loads(args.raw_json)
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(parsed, indent=args.indent, sort_keys=True))


if __name__ == "__main__":
    main()
