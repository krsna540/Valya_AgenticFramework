"""Playbook selection — the Planner's "which procedural memory applies here"
step (PLATFORM_ARCHITECTURE.md §11.5).

Scoring is lexical (token overlap between the objective and each playbook's
`when_to_use`/`name`/`description`), not embedding-based. That is a
deliberate choice, not a placeholder: this runs on every planning call, has
to finish in microseconds, and must not add a network round-trip or a new
model dependency to a step that is otherwise pure local computation. An
embedding-based ranker is a reasonable upgrade if the playbook catalogue
ever gets large enough for lexical overlap to stop discriminating, but this
codebase has never shown that catalogue size, and swapping it in later is a
one-function change: `select_relevant_playbooks` is the only entry point.

Selection happens once per planning attempt, not once per repair attempt —
see planner.py, which selects before entering `_plan_with_repair` and holds
the result for every retry within that pass.
"""
from __future__ import annotations

import re

from app.agents.tools import PlaybookSpec

#: Below this, a playbook is noise rather than signal and is left out of the
#: prompt entirely — an irrelevant playbook competing for the model's
#: attention is worse than none.
_MIN_SCORE = 0.08

_WORD_RE = re.compile(r"[a-z0-9]+")

#: `when_to_use` text is written in a narrow, formulaic style ("Use when...",
#: "Use for...") across almost every playbook, so these words appear in the
#: overlap between *every* objective and *every* playbook regardless of
#: actual relevance — left in, they alone can push an unrelated playbook
#: over `_MIN_SCORE`. Excluding them is what makes the score measure topical
#: overlap rather than "did both texts use English".
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "use", "used", "using", "uses", "when", "where", "for", "to", "of",
        "on", "in", "is", "are", "was", "were", "be", "being", "been", "and", "or", "with",
        "this", "that", "their", "it", "its", "as", "at", "by", "from", "you", "your",
    }
)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def _score(objective_tokens: set[str], playbook: PlaybookSpec) -> float:
    """Jaccard overlap between the objective and the playbook's selection
    text. `when_to_use` is what §11.5 defines as the selection signal; name
    and description are folded in at a lower weight so a well-named playbook
    with a thin `when_to_use` is still reachable."""
    if not objective_tokens:
        return 0.0
    selection_text = " ".join(
        [playbook.when_to_use, playbook.name, playbook.description or ""]
    )
    candidate_tokens = _tokens(selection_text)
    if not candidate_tokens:
        return 0.0
    overlap = objective_tokens & candidate_tokens
    union = objective_tokens | candidate_tokens
    return len(overlap) / len(union) if union else 0.0


def select_relevant_playbooks(
    objective: str,
    playbooks: list[PlaybookSpec],
    *,
    top_k: int = 2,
) -> list[PlaybookSpec]:
    """Return the `top_k` playbooks most relevant to `objective`, best first.

    Returns an empty list rather than an arbitrary top-k when nothing clears
    `_MIN_SCORE` — an agent with playbooks attached that don't apply to this
    turn should plan exactly as it would with none attached, not have a
    barely-related process forced into its prompt.
    """
    if not playbooks or not objective.strip():
        return []
    objective_tokens = _tokens(objective)
    scored = [(playbook, _score(objective_tokens, playbook)) for playbook in playbooks]
    scored = [(p, s) for p, s in scored if s >= _MIN_SCORE]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [p for p, _ in scored[:top_k]]


__all__ = ["select_relevant_playbooks"]
