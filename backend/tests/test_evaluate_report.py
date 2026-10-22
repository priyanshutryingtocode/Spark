"""Tests for the evaluation report's ceiling-aware metrics.

Precision@k is bounded by how many relevant creators exist in the filtered
cell, so these helpers are what make a score comparable across corpus sizes.
Pure functions only: no database, no API.
"""

import pytest

from evaluate import ceiling_precision, pool_for, recall_of_ceiling, tag_precision


class FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def execute(self, sql, params=None):
        self.query = sql
        self.params = params
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (self.rows[0][2] if len(self.rows[0]) > 2 else self.rows[0][1],)


def test_pool_for_counts_the_union_of_matching_tags():
    """Relevance is an intersection, so the reachable pool is the union; a
    creator carrying two of the tags is one relevant creator, not two."""
    conn = FakeConn([("any", "any", 9)])

    assert pool_for(conn, {"gym", "running"}, "TikTok") == 9
    assert conn.params[0] == ["gym", "running"]


def test_pool_for_applies_the_platform_filter_and_ignores_any():
    filtered = FakeConn([("any", "any", 4)])
    pool_for(filtered, {"gym"}, "TikTok")
    assert "platform = %s" in filtered.query
    assert filtered.params[1] == "TikTok"

    unfiltered = FakeConn([("any", "any", 12)])
    pool_for(unfiltered, {"gym"}, "Any")
    assert "platform = %s" not in unfiltered.query


def test_pool_for_without_tags_is_zero():
    assert pool_for(FakeConn([("any", "any", 5)]), set(), "Any") == 0


class _Creator:
    def __init__(self, tags):
        self.tags = tags


def test_tag_precision_counts_any_shared_tag():
    creators = [_Creator(["gym"]), _Creator(["skincare"]), _Creator(["gym", "fps"])]
    assert tag_precision(creators, {"gym"}) == pytest.approx(2 / 3)


def test_tag_precision_edge_cases():
    assert tag_precision([], {"gym"}) == 0.0
    assert tag_precision([_Creator(["gym"])], set()) == 0.0


@pytest.mark.parametrize("pool,k,expected", [
    (3, 10, 0.3),    # the floor of a small balanced corpus caps the score
    (11, 10, 1.0),   # a deeper cell lifts the cap entirely
    (18, 10, 1.0),   # never above 1.0
    (0, 10, 0.0),
    (3, 5, 0.6),     # the same pool measured at top_n
    (5, 5, 1.0),
])
def test_ceiling_precision(pool, k, expected):
    assert ceiling_precision(pool, k) == pytest.approx(expected)


def test_ceiling_precision_handles_zero_k():
    assert ceiling_precision(3, 0) == 0.0


@pytest.mark.parametrize("retrieved,pool,k,expected", [
    (3, 3, 10, 1.0),   # every creator that could fit was retrieved
    (2, 3, 10, 0.667), # a real miss
    (10, 11, 10, 1.0), # pool deeper than k: k retrieved is a full score
    (5, 5, 5, 1.0),
    (4, 5, 5, 0.8),
    (0, 0, 10, 1.0),   # nothing to find is nothing missed
    (0, 3, 10, 0.0),
])
def test_recall_of_ceiling(retrieved, pool, k, expected):
    assert recall_of_ceiling(retrieved, pool, k) == pytest.approx(expected, abs=0.001)


def test_capped_case_still_scores_full_marks():
    """The point of the metric: a saturated cell must not look like a miss."""
    pool = 3
    k = 10
    retrieved = 3

    assert ceiling_precision(pool, k) == 0.3
    assert recall_of_ceiling(retrieved, pool, k) == 1.0


# ------------------------------------------------------- connection lifetime
class _TrackingVectorStore:
    """Appends acquire/release to the shared event log as the pool is used."""

    DEFAULT_TABLE = "influencers"
    events: list = []

    class _Conn:
        def __enter__(self):
            _TrackingVectorStore.events.append("acquire")
            return self

        def __exit__(self, *exc):
            _TrackingVectorStore.events.append("release")
            return False

    @staticmethod
    def get_connection():
        return _TrackingVectorStore._Conn()


def test_connection_is_not_held_across_the_ranking_call(monkeypatch):
    """The pool slot must not be held while the ranking call is in flight.

    A window fires len(window) cases at once -- 10 by default -- while the pool
    has max_size=4. The case used to check a connection out at the top and hold
    it through the embedding call, the vector search and the ranking call, even
    though the only query it runs is pool_for() at the very end. So most of a
    window was threads blocked on a pool they were not using.

    The ordering is the whole point: with the connection taken up front the log
    starts "acquire, retrieve, rank"; it must start "retrieve, rank, acquire".
    """
    import evaluate as ev

    events: list[str] = []
    _TrackingVectorStore.events = events

    monkeypatch.setattr(ev, "vector_store", _TrackingVectorStore)
    monkeypatch.setattr(ev, "Brief", lambda **kw: type("B", (), {"query_text": lambda self: "q", **kw})())

    class _Candidate:
        def __init__(self, cid, tags):
            self.id, self.tags = cid, tags

    def fake_retrieve(brief, top_k, query_vec, corpus=None):
        events.append("retrieve")
        return [_Candidate(0, ["gym"]), _Candidate(1, ["food"])]

    def fake_rank(brief, candidates, top_n, client, corpus=None):
        events.append("rank")
        return [{"id": candidates[0].id}]

    monkeypatch.setattr(ev, "retrieve_candidates", fake_retrieve)
    monkeypatch.setattr(ev, "rank_match", fake_rank)
    monkeypatch.setattr(ev, "get_cached_query_vector", lambda text, cache=None: [0.0] * 768)
    monkeypatch.setattr(ev, "terms", lambda text: {"gym"})
    monkeypatch.setattr(ev, "overlap_ratio", lambda terms, c: 0.0)
    monkeypatch.setattr(ev, "pool_for", lambda conn, tags, platform, table=None: 12)

    ev._run_case(
        object(),
        {"id": "c1", "goal": "strength", "expected_tags": ["gym"]},
        top_k=10,
        top_n=5,
    )

    assert events == ["retrieve", "rank", "acquire", "release"], (
        f"connection ordering changed: {events}"
    )


# ------------------------------------------------- comparable reranking pair
class _Cand:
    def __init__(self, cid, tags):
        self.id, self.tags = cid, tags


@pytest.mark.parametrize("candidates,ranked_ids,expected_retrieval,expected_rank", [
    # The retriever's top 2 are already the relevant ones; reranking cannot help.
    ([_Cand(0, ["gym"]), _Cand(1, ["gym"])], [0, 1], 1.0, 1.0),
    # Relevant creator is retrieved but sits 4th; the ranker promotes it.
    ([_Cand(0, ["food"]), _Cand(1, ["food"]), _Cand(2, ["food"]), _Cand(3, ["gym"])], [3, 0], 0.0, 0.5),
    # Nothing relevant anywhere in the top n.
    ([_Cand(0, ["food"]), _Cand(1, ["food"])], [0, 1], 0.0, 0.0),
])
def test_ranking_gain_is_rank_minus_retrieval_at_the_same_cutoff(
    candidates, ranked_ids, expected_retrieval, expected_rank
):
    """The two scores must describe the same rows.

    `ranked_tag_precision_at_n` alone cannot be read as a retrieval result: it
    is precision after the reranker has reordered the list, at a different
    cutoff from the retrieval score. Scoring the retriever's own top n gives two
    numbers over identical rows, so their difference is the reranker's doing and
    nothing else's.
    """
    import evaluate as ev

    ranked_candidates = [candidates[i] for i in ranked_ids]
    expected = {"gym"}

    retrieval = ev.tag_precision(candidates[:2], expected)
    ranked = ev.tag_precision(ranked_candidates, expected)

    assert retrieval == pytest.approx(expected_retrieval)
    assert ranked == pytest.approx(expected_rank)
    assert round(ranked - retrieval, 3) == round(expected_rank - expected_retrieval, 3)
