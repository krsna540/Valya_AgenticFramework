---
name: word-count
description: Counts words and characters in a block of text. Use when the user asks how long a piece of text is, or wants a word/character count.
license: MIT
metadata:
  category: text
  origin: built-in
---

# word-count

Counts words and characters in a block of text.

## When to use

- The user asks how many words or characters are in some text.
- The user pastes a block of text and asks "how long is this?"

## How to use

Run `scripts/word_count.py` with the text as an argument, or piped on
stdin. It prints a JSON object with `word_count` and `char_count`.

```
python3 scripts/word_count.py "The quick brown fox jumps over the lazy dog"
-> {"word_count": 9, "char_count": 43}
```

This was previously a platform-executed handler_key skill (`word_count` in
`app/skills/catalog.py`); it's kept here as a real, working example of the
folder format now that the handler_key catalog has been retired. Nothing in
this skill is executed automatically — an agent runs `scripts/word_count.py`
itself if and when it decides to.
