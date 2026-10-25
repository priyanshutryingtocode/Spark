"""Hybrid retrieval: metadata filters plus semantic search.

The filters and the pgvector search run as a single Postgres query (see
vector_store.search). This module embeds the brief's own words (cached) and
searches.

An earlier version added a lexical term-overlap prior on top of the vector
score. Measured against the free-text golden cases it was net-neutral (mean
p@10 0.393 pure similarity vs 0.387 with the prior), because the bonus was
capped far below the similarity gaps between neighbouring candidates and so
could only reorder near-ties. It was removed rather than kept as a knob.
Literal term matching still earns its place as human-readable evidence on
each result (see src.text_match and src.formatting).
"""

from __future__ import annotations

from typing import Any

import psycopg

from . import config, vector_store
from .corpora import CREATORS, Corpus
from .embeddings import get_cached_query_vector
from .models import Brief
from .scoring import expand_vertical, filter_hit

#: How many candidates a filtered search must return before the filters are
#: relaxed.
#:
#: One, not a comfortable shortlist size. A brief that names an ICP and matches
#: two accounts has been answered precisely, and widening the filters to
#: manufacture a full page of results would trade two real leads for eight
#: records that do not fit. The relaxation exists for the brief that matches
#: nothing at all, and it reports itself when it happens.
MIN_FILTERED_RESULTS = 1


def similarity_sort(candidates: list[Any]) -> list[Any]:
    """Return a new list ordered by vector similarity, descending.

    A missing similarity counts as 0 so records that fall outside the
    embedding path still sort last instead of raising.
    """
    return sorted(candidates, key=lambda inf: -(inf.similarity or 0.0))


def resolve_facet(brief: Brief, corpus: Corpus) -> str | None:
    """The brief's facet value as a WHERE-clause value, or None for unfiltered.

    Two ways to end up unfiltered: a corpus that does not filter at all
    (prospects -- industry is something the ranker judges, not a constraint), or
    a brief whose facet is the corpus's "anything" value ("Any" for platform).
    Both mean the same thing to the query, so both collapse to None.
    """
    if not corpus.facet_is_hard_filter or corpus.facet_column is None:
        return None
    return None if brief.platform == "Any" else brief.platform


def resolve_filters(brief: Brief, corpus: Corpus) -> dict[str, Any]:
    """The corpus's structured filters, as {column: value}.

    A filter is only included when the brief actually asked for it. Values that
    mean "anything" -- an empty list, a blank string -- are excluded, because a
    WHERE clause on an empty set matches nothing and that is a different thing
    from not filtering.
    """
    resolved: dict[str, Any] = {}
    for spec in corpus.filters:
        value = getattr(brief, spec.brief_field, None)
        if not _is_requested(value):
            continue
        if spec.mode == "in" and isinstance(value, str):
            value = [value]
        if spec.column == corpus.vertical_column and isinstance(value, list):
            # The brief names a vertical; the column holds the industries inside
            # it. Without this, "logistics" matches one of three logistics
            # industries and the brief looks like it found nothing.
            value = expand_vertical(value, corpus.verticals)
        resolved[spec.column] = value
    return resolved


def filter_order(filters: dict[str, Any], corpus: Corpus) -> list[str]:
    """Filter columns in the order they are relaxed when a search comes back empty.

    Most selective first, so the filter that was doing the most work is the one
    dropped, and a brief that asks for too much still gets a result instead of
    an empty list.
    """
    order = {spec.column: spec.drop_order for spec in corpus.filters}
    return sorted(filters, key=lambda column: (order.get(column, 99), column))


def hybrid_retrieve(
    conn: psycopg.Connection,
    brief: Brief,
    top_k: int = 10,
    corpus: Corpus = CREATORS,
    query_vec=None,
    filters: dict[str, Any] | None = None,
) -> list[Any]:
    """Retrieve the corpus's nearest rows, filtered.

    `filters` overrides the brief's own resolved filters when given, which is how
    the relaxation path retries with fewer.
    """
    if query_vec is None:
        query_vec = get_cached_query_vector(brief.query_text())
    candidates = vector_store.search(
        conn,
        query_embedding=query_vec,
        corpus=corpus,
        facet=resolve_facet(brief, corpus),
        top_k=top_k,
        filters=resolve_filters(brief, corpus) if filters is None else filters,
    )
    return similarity_sort(candidates)[:top_k]


def retrieve_with_filters(
    conn: psycopg.Connection,
    brief: Brief,
    top_k: int = 10,
    corpus: Corpus = CREATORS,
    query_vec=None,
) -> tuple[list[Any], list[str]]:
    """Retrieve, relaxing filters until the result is not empty.

    Returns the candidates and the list of filter columns that were dropped. The
    corpus is small enough that a strict filter can match nothing -- "fintech
    between 51 and 200 staff" is four companies -- and a brief that asks for
    something the corpus does not contain should come back with results and an
    explanation, not an empty page that looks like a broken search.
    """
    filters = resolve_filters(brief, corpus)
    if not filters:
        return hybrid_retrieve(conn, brief, top_k, corpus, query_vec, {}), []

    order = filter_order(filters, corpus)
    # The filters are relaxed only until the search returns something, and
    # every filter dropped is reported. Relaxing further than that would widen
    # the answer away from the brief for the sake of a longer list.
    floor = min(top_k, MIN_FILTERED_RESULTS)
    for attempt in range(len(order) + 1):
        remaining = {k: v for k, v in filters.items() if k not in order[:attempt]}
        candidates = hybrid_retrieve(conn, brief, top_k, corpus, query_vec, remaining)
        if len(candidates) >= floor or attempt == len(order):
            return attach_filter_reasons(brief, candidates, corpus), order[:attempt]
    return [], order


def attach_filter_reasons(brief: Brief, candidates: list[Any], corpus: Corpus) -> list[Any]:
    """Record which of the brief's filters each record satisfied.

    A filter that is applied but not shown reads as a filter the user did not
    ask for, which is worse than not filtering at all: they cannot tell whether
    a result is a good match or a survivor.
    """
    for candidate in candidates:
        hits = []
        for spec in corpus.filters:
            wanted = getattr(brief, spec.brief_field, None)
            if not _is_requested(wanted):
                continue
            value = getattr(candidate, spec.column, None)
            if spec.column.startswith("s."):
                value = getattr(candidate, spec.column.split(".", 1)[1], None)
            hit = filter_hit(value, wanted, spec.mode)
            if hit is not None:
                hits.append(f"{spec.label} {hit}")
        existing = list(getattr(candidate, "match_reasons", []) or [])
        try:
            candidate.match_reasons = hits + existing
        except AttributeError:
            pass
    return candidates


def rerank_candidates(
    brief: Brief,
    candidates: list[Any],
    corpus: Corpus = CREATORS,
    weight: float = config.RERANK_WEIGHT,
) -> list[Any]:
    """Reorder retrieved candidates by how well they match the brief's structured fields.

    The embedding answers "is this about the right thing". The rerank answers "is
    this about the right thing, for the right people" -- and it is deliberately a
    reorder, never an exclusion, because the fields it reads are estimates.
    A creator whose audience is "25-34" when the brief asked for "18-24" is a
    worse match, not a non-match.

    `weight` blends the match score into the similarity. It is a single constant
    because the similarity scale is narrow -- the corpus sits in a 0.78-0.88 band
    -- so a small number is a large number.
    """
    if not candidates or not corpus.rerank:
        return candidates

    scored = []
    for candidate in candidates:
        match, reasons = _match_score(brief, candidate, corpus)
        # getattr, not attribute access: a record that never went through the
        # embedding path has no similarity, and a missing value is a zero rather
        # than a crash in the middle of a run.
        similarity = getattr(candidate, "similarity", 0.0) or 0.0
        final = similarity + weight * match
        scored.append((final, candidate, reasons))
    scored.sort(key=lambda item: -item[0])
    return [_attach(item[1], item[2]) for item in scored]


def _is_requested(value: Any) -> bool:
    """Whether a brief value asks for anything.

    A zero floor and an "any" preference both look like values but ask for
    nothing, and counting them would put weight in the denominator that no
    candidate can ever satisfy -- so every candidate would score lower and the
    comparison between them would shift for no reason.
    """
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip() != "" and value.strip().lower() != "any"
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def _match_score(brief: Brief, candidate: Any, corpus: Corpus) -> tuple[float, list[str]]:
    """The weighted match score and the human-readable reasons behind it.

    The denominator is the weight of every field the brief *asked for*, not of
    the ones that matched. Dividing by the matched weight instead would score a
    candidate that satisfied one field perfectly at 1.0 -- the same as one that
    satisfied everything -- and a candidate matching nothing would be excluded
    from the average rather than counted as a failure. The score is "how much of
    what was asked for did this get".
    """
    total = 0.0
    requested = 0.0
    reasons: list[str] = []
    for spec in corpus.rerank:
        wanted = getattr(brief, spec.brief_field, None)
        if not _is_requested(wanted):
            continue
        value = getattr(candidate, spec.column, None)
        if corpus.real_data and value is None:
            continue
        requested += spec.weight
        score = spec.scorer(value, wanted)
        if score <= 0:
            continue
        total += score * spec.weight
        reasons.append(f"{spec.label} {round(score * 100)}%")
    if not requested:
        return 0.0, []
    return total / requested, reasons


def _attach(candidate: Any, reasons: list[str]) -> Any:
    """Record why a candidate matched, for the UI to show.

    Merged rather than replaced: the filter hits are attached first, and
    overwriting them with the rerank's reasons would silently drop the
    explanation of the filter that actually selected the record.
    """
    try:
        existing = list(getattr(candidate, "match_reasons", []) or [])
        candidate.match_reasons = existing + [r for r in reasons if r not in existing]
    except AttributeError:
        pass
    return candidate
