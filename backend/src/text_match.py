"""Lexical matching between a free-text brief and one corpus record.

Retrieval is purely semantic, but a purely semantic result is hard to
defend to a user who asked for "sourdough baking" and cannot see why a
creator came back. This module answers that question: which of the brief's
own words appear in the text the record's embedding was built from.

Corpus-generic by construction and not by accident: the only thing it needs
from a record is `corpus_text()`, so the same code scores a company against a
sales brief. Nothing is reworded per corpus.

It is display-only. It scores and explains, and never reorders anything.
"""

import re
from typing import Any

STOP_WORDS = {
    "about", "and", "are", "for", "from", "into", "its", "not", "the",
    "this", "that", "their", "with", "your",
    "who", "want", "wants", "looking", "look", "like", "also", "just",
    "have", "has", "been", "they", "them", "will", "would", "make",
    "making", "need", "needs", "some", "any", "our", "out", "over",
    "than", "then", "there", "here", "what", "when", "which", "while",
}


def terms(text: str) -> set[str]:
    """Meaningful lowercase tokens, stop words and very short words removed."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) > 2 and word not in STOP_WORDS
    }


def shared_terms(brief_terms: set[str], record: Any) -> set[str]:
    """Brief terms that appear in the text this record was embedded as.

    Reads `corpus_text` directly rather than rebuilding a parallel string, so
    the explanation can never quote something the vector never saw.
    """
    return brief_terms & terms(record.corpus_text())


def overlap_ratio(brief_terms: set[str], record: Any) -> float:
    """Share of the brief's terms that appear anywhere in the record's text.

    The brief is the denominator, so a long profile cannot inflate the score.
    Returns 0.0 for a brief with no usable terms.
    """
    if not brief_terms:
        return 0.0
    return len(shared_terms(brief_terms, record)) / len(brief_terms)
