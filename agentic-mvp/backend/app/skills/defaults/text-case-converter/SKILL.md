---
name: text-case-converter
description: Converts text between common cases (UPPER, lower, Title Case, snake_case, kebab-case, camelCase). Use when the user wants text reformatted into a specific case convention.
license: MIT
metadata:
  category: text
  origin: built-in
  seeded: default
---

# text-case-converter

Converts a block of text between common case conventions.

## When to use

- The user asks to convert text to uppercase, lowercase, or Title Case.
- The user wants a variable/identifier name reformatted, e.g. into
  `snake_case`, `kebab-case`, or `camelCase`.

## How to use

Run `scripts/text_case.py` with the target case and the text as arguments,
or pipe the text on stdin. It prints a JSON object with the original text
and every supported conversion.

```
python3 scripts/text_case.py "Hello World Example"
-> {
     "original": "Hello World Example",
     "upper": "HELLO WORLD EXAMPLE",
     "lower": "hello world example",
     "title": "Hello World Example",
     "snake_case": "hello_world_example",
     "kebab-case": "hello-world-example",
     "camelCase": "helloWorldExample"
   }
```

This is the one skill this app seeds automatically for every new tenant on
signup, so a fresh workspace's Skills page isn't empty on day one. Like
every other skill here, nothing in this folder is executed automatically —
an agent runs `scripts/text_case.py` itself if and when it decides to.
