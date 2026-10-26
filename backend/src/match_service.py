from __future__ import annotations

from . import vector_store
from .corpora import CREATORS, Corpus, Influencer
from .embeddings import get_cached_query_vector
from .gemini_client import get_client
from .models import Brief
from .ranking import rank_candidates
from .retrieval import dual_retrieve, hybrid_retrieve, retrieve_with_filters


def retrieve_candidates(
    brief: Brief,
    top_k: int,
    query_vec=None,
    context_vec=None,
    corpus: Corpus = CREATORS,
    filters: dict | None = None,
) -> list[Influencer]:
    """The corpus's nearest records to the brief.

    `filters` overrides the brief's own resolved filters when given, which is
    how the unfiltered baseline is measured.
    """
    if query_vec is None:
        query_vec = get_cached_query_vector(brief.intent_query_text())
        context_text = brief.context_query_text()
        if context_vec is None and context_text:
            context_vec = get_cached_query_vector(context_text)
    with vector_store.get_connection() as conn:
        if context_vec is not None:
            return dual_retrieve(
                conn, brief, top_k=top_k, corpus=corpus,
                intent_vec=query_vec, context_vec=context_vec,
                filters={} if filters is not None else None,
            )
        return hybrid_retrieve(conn, brief, top_k=top_k, corpus=corpus,
                               query_vec=query_vec,
                               filters={} if filters is not None else None)


def retrieve_for_run(
    brief: Brief,
    top_k: int,
    query_vec=None,
    context_vec=None,
    corpus: Corpus = CREATORS,
) -> tuple[list[Influencer], list[str]]:
    """The candidates for a run, and any filter that had to be relaxed.

    The floor matters because the corpora are small enough that a brief can ask
    for something they do not contain. Returning an empty list would read as
    "nothing matches" when the truth is "your filter excludes everything" --
    and the two call for different actions from the reader.
    """
    if query_vec is None:
        query_vec = get_cached_query_vector(brief.intent_query_text())
        context_text = brief.context_query_text()
        if context_vec is None and context_text:
            context_vec = get_cached_query_vector(context_text)
    with vector_store.get_connection() as conn:
        candidates, dropped = retrieve_with_filters(
            conn, brief, top_k=top_k, corpus=corpus, query_vec=query_vec,
            context_vec=context_vec,
        )
    labels = {spec.column: spec.label for spec in corpus.filters}
    return candidates, [labels.get(column, column) for column in dropped]


def rank_match(
    brief: Brief,
    candidates: list[Influencer],
    top_n: int,
    client=None,
    corpus: Corpus = CREATORS,
    relaxed_filters: list[str] | None = None,
) -> list[dict]:
    """Rank under `corpus`'s rubric.

    Defaults to CREATORS, which is what keeps the API path -- the only caller
    today -- unchanged until the mode switch lands and can pass its own corpus.
    """
    if client is None:
        client = get_client()
    if corpus.rubric is None:
        raise ValueError(
            f"corpus {corpus.kind!r} has no ranking rubric; rank under "
            f"retrieval order or use a corpus that defines one"
        )
    return rank_candidates(
        client, brief, candidates, top_n=top_n,
        corpus_kind=corpus.kind, rubric=corpus.rubric,
        relaxed_filters=relaxed_filters,
    )
