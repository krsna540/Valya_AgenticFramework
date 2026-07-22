#!/usr/bin/env python3
"""Converts text between common case conventions.

Usage:
    python3 text_case.py "some text here"
    echo "some text here" | python3 text_case.py

Prints a JSON object with the original text and every supported
conversion: upper, lower, title, snake_case, kebab-case, camelCase.

This is agent-invoked, not platform-executed: nothing in this skill folder
runs automatically when the skill is seeded, uploaded, or attached to an
agent (see ../SKILL.md).
"""
import json
import re
import sys


def _words(text: str) -> list[str]:
    """Splits text into words on whitespace and case/punctuation
    boundaries, so both "hello world" and "helloWorld" or "hello-world"
    split the same way."""
    # Insert a boundary before an uppercase letter that follows a lowercase
    # letter or digit (camelCase / PascalCase boundaries).
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    # Treat any run of non-alphanumeric characters as a separator.
    parts = re.split(r"[^A-Za-z0-9]+", spaced)
    return [p for p in parts if p]


def convert(text: str) -> dict:
    words = _words(text)
    lower_words = [w.lower() for w in words]
    return {
        "original": text,
        "upper": text.upper(),
        "lower": text.lower(),
        "title": " ".join(w.capitalize() for w in lower_words) if words else text.title(),
        "snake_case": "_".join(lower_words),
        "kebab-case": "-".join(lower_words),
        "camelCase": (lower_words[0] + "".join(w.capitalize() for w in lower_words[1:])) if lower_words else "",
    }


def main() -> None:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = sys.stdin.read().rstrip("\n")
    print(json.dumps(convert(text)))


if __name__ == "__main__":
    main()
