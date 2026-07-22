#!/usr/bin/env python3
"""Counts words and characters in a block of text.

Usage:
    python3 word_count.py "some text"
    echo "some text" | python3 word_count.py

Prints a JSON object: {"word_count": N, "char_count": N}

This is agent-invoked, not platform-executed: nothing in this skill folder
runs automatically when the skill is uploaded or attached to an agent (see
../SKILL.md).
"""
import json
import sys


def main() -> None:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read()
    result = {"word_count": len(text.split()), "char_count": len(text)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
