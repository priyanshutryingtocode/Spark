"""Tests for the hosted embedder, the query-vector LRU cache, and the
on-disk vector cache used to make reindexing resumable.

No network: the Gemini client is replaced with a fake, and the per-request
floor is turned off so the tests do not sleep.
"""

import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from src import config, embeddings


class FakeEmbedResponse:
    def __init__(self, values):
        self.embeddings = [type("Embedding", (), {"values": values})()]


class FakeModels:
    def __init__(self, recorder, dimensions=None, fail_times=0):
        self.recorder = recorder
        self.dimensions = dimensions or config.EMBED_DIMENSIONS
        self.fail_times = fail_times
        self.counter = 0

    def embed_content(self, model, contents, config=None):
        self.recorder.append({
            "model": model,
            "text": contents,
            "task_type": config.task_type,
            "output_dimensionality": config.output_dimensionality,
        })
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("transient")
        self.counter += 1
        return FakeEmbedResponse([float(self.counter)] * self.dimensions)


class FakeClient:
    def __init__(self, models):
        self.models = models


@pytest.fixture(autouse=True)
def fast_and_clean(monkeypatch):
    monkeypatch.setattr(config, "EMBED_REQUEST_INTERVAL_SECONDS", 0.0)
    embeddings._query_cache.clear()
    embeddings._client = None
    yield
    embeddings._query_cache.clear()
    embeddings._client = None


@pytest.fixture
def recorder():
    return []


@pytest.fixture
def fake_api(monkeypatch, recorder):
    def install(dimensions=None, fail_times=0):
        models = FakeModels(recorder, dimensions=dimensions, fail_times=fail_times)
        monkeypatch.setattr(embeddings, "get_embedding_client", lambda: FakeClient(models))
        return models

    return install


def test_query_uses_retrieval_query_task_and_requested_width(fake_api, recorder):
    fake_api()
    vector = embeddings.embed_query("find me a fitness creator")

    assert vector.shape == (config.EMBED_DIMENSIONS,)
    assert recorder[0]["model"] == config.EMBED_MODEL
    assert recorder[0]["task_type"] == "RETRIEVAL_QUERY"
    assert recorder[0]["output_dimensionality"] == config.EMBED_DIMENSIONS


def test_documents_use_retrieval_document_task(fake_api, recorder):
    fake_api()
    embeddings.embed_documents(["doc one", "doc two"])

    assert [call["task_type"] for call in recorder] == ["RETRIEVAL_DOCUMENT"] * 2
    assert len(recorder) == 2  # one request per text


def test_vectors_are_l2_normalized(fake_api):
    fake_api()
    vector = embeddings.embed_query("anything")

    assert pytest.approx(1.0, abs=1e-5) == float(np.linalg.norm(vector))


def test_wrong_width_raises_actionable_error(fake_api):
    fake_api(dimensions=config.EMBED_DIMENSIONS + 8)

    with pytest.raises(RuntimeError, match="reindex"):
        embeddings.embed_query("anything")


def test_cache_hit_skips_api_call(fake_api, recorder):
    fake_api()
    first = embeddings.get_cached_query_vector("same brief")
    second = embeddings.get_cached_query_vector("same brief")

    assert len(recorder) == 1
    assert (first == second).all()


def test_different_briefs_embed_separately(fake_api, recorder):
    fake_api()
    embeddings.get_cached_query_vector("brief A")
    embeddings.get_cached_query_vector("brief B")

    assert len(recorder) == 2


def test_lru_eviction(monkeypatch, fake_api, recorder):
    fake_api()
    monkeypatch.setattr(embeddings, "_QUERY_CACHE_SIZE", 2)
    for text in ("one", "two", "three"):
        embeddings.get_cached_query_vector(text)
    assert len(embeddings._query_cache) == 2

    before = len(recorder)
    embeddings.get_cached_query_vector("three")
    assert len(recorder) == before  # still cached

    embeddings.get_cached_query_vector("one")
    assert len(recorder) == before + 1

    embeddings.get_cached_query_vector("three")
    assert len(recorder) == before + 1

    embeddings.get_cached_query_vector("two")
    assert len(recorder) == before + 2


def test_query_cache_survives_a_failing_api_call(fake_api):
    fake_api(fail_times=1)
    with pytest.raises(RuntimeError):
        embeddings.get_cached_query_vector("brief")
    assert len(embeddings._query_cache) == 0


def test_embedding_cache_round_trips_and_resumes(tmp_path, fake_api):
    path = tmp_path / "vectors.jsonl"
    fake_api()

    first = embeddings.EmbeddingCache(path)
    first.put_many([("key-a", np.full(config.EMBED_DIMENSIONS, 0.5, dtype=np.float32))])
    assert len(first) == 1

    reopened = embeddings.EmbeddingCache(path)
    assert reopened.hits == 0
    assert reopened.get("key-a") is not None
    assert reopened.misses == 0
    assert pytest.approx(1.0, abs=1e-5) == float(np.linalg.norm(reopened.get("key-a")))


def test_embedding_cache_ignores_other_models_and_widths(tmp_path, fake_api):
    path = tmp_path / "vectors.jsonl"
    records = [
        {"key": "key-a", "model": "some-other-model",
         "dimensions": config.EMBED_DIMENSIONS, "values": [0.1] * config.EMBED_DIMENSIONS},
        {"key": "key-b", "model": config.EMBED_MODEL,
         "dimensions": config.EMBED_DIMENSIONS - 8, "values": [0.1] * (config.EMBED_DIMENSIONS - 8)},
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    fake_api()

    cache = embeddings.EmbeddingCache(path)
    assert len(cache) == 0
    assert cache.get("key-a") is None
    assert cache.get("key-b") is None


def test_embedding_cache_skips_a_truncated_final_line(tmp_path, fake_api):
    path = tmp_path / "vectors.jsonl"
    path.write_text(
        json.dumps({
            "key": "key-a",
            "model": config.EMBED_MODEL,
            "dimensions": config.EMBED_DIMENSIONS,
            "values": [0.1] * config.EMBED_DIMENSIONS,
        }) + "\n" + '{"key": "key-b", "val',
        encoding="utf-8",
    )
    fake_api()

    cache = embeddings.EmbeddingCache(path)
    assert len(cache) == 1
    assert cache.get("key-b") is None


def test_index_records_reuses_cached_vectors(tmp_path, fake_api, recorder):
    from src.data_generator import generate_influencers

    fake_api()
    influencers = generate_influencers(count=3)
    keys = [embeddings.text_key(influencer.corpus_text()) for influencer in influencers]

    cache = embeddings.EmbeddingCache(tmp_path / "vectors.jsonl")
    cache.put_many([(key, np.full(config.EMBED_DIMENSIONS, 0.25, dtype=np.float32)) for key in keys])
    requests_before = len(recorder)

    embeddings.index_records(influencers, cache=cache)

    assert len(recorder) == requests_before  # nothing re-billed
    assert all(influencer.embedding is not None for influencer in influencers)
    assert pytest.approx(1.0, abs=1e-5) == float(np.linalg.norm(influencers[0].embedding))


def test_index_records_embeds_only_cache_misses(tmp_path, fake_api, recorder):
    from src.data_generator import generate_influencers

    fake_api()
    influencers = generate_influencers(count=4)
    cache = embeddings.EmbeddingCache(tmp_path / "vectors.jsonl")
    cache.put_many([(
        embeddings.text_key(influencers[0].corpus_text()),
        np.full(config.EMBED_DIMENSIONS, 0.25, dtype=np.float32),
    )])
    requests_before = len(recorder)

    embeddings.index_records(influencers, cache=cache)

    assert len(recorder) == requests_before + 3
    assert cache.hits == 1
    assert cache.misses == 3


def test_request_floor_spaces_calls(monkeypatch):
    class FakeTime:
        def __init__(self):
            self.now = 100.0
            self.slept: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            self.now += seconds

    fake = FakeTime()
    monkeypatch.setattr(embeddings, "time", fake)
    monkeypatch.setattr(config, "EMBED_REQUEST_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(embeddings, "_last_request_at", 100.0)

    embeddings._throttle()
    embeddings._throttle()

    assert fake.slept == [1.0, 1.0]


def test_query_cache_path_is_separate_from_the_document_cache():
    """One text has two legitimate vectors -- Gemini embeds it under
    RETRIEVAL_DOCUMENT and RETRIEVAL_QUERY -- so the two caches must not
    share a file or retrieval gets handed a document vector."""
    from evaluate import default_query_cache_path

    assert default_query_cache_path().name.endswith("-queries.jsonl")
    assert default_query_cache_path() != default_query_cache_path().with_name(
        default_query_cache_path().name.replace("-queries", "")
    )


def test_a_document_vector_is_never_served_to_a_query(tmp_path, fake_api, recorder):
    fake_api()
    shared = "sustainable fashion thrift creator"
    doc_cache = embeddings.EmbeddingCache(tmp_path / "docs.jsonl")
    doc_vector = embeddings.embed_documents([shared])[0]
    doc_cache.put_many([(embeddings.text_key(shared), doc_vector)])

    before = len(recorder)
    query_cache = embeddings.EmbeddingCache(tmp_path / "queries.jsonl")
    embeddings.get_cached_query_vector(shared, query_cache)

    assert len(recorder) == before + 1, "query was answered without an embedding request"
    assert recorder[-1]["task_type"] == "RETRIEVAL_QUERY"
    assert query_cache.misses == 1
    assert len(query_cache) == 1


def test_repeat_run_spends_no_embedding_quota(tmp_path, fake_api, recorder):
    fake_api()
    path = tmp_path / "queries.jsonl"
    first = embeddings.EmbeddingCache(path)
    original = embeddings.get_cached_query_vector("a fashion brief", first)
    assert len(recorder) == 1

    embeddings._query_cache.clear()  # a fresh process starts with an empty LRU
    second = embeddings.EmbeddingCache(path)
    resumed = embeddings.get_cached_query_vector("a fashion brief", second)

    assert len(recorder) == 1, "the repeat run re-billed the embedding quota"
    assert second.hits == 1
    assert np.allclose(original, resumed)


def test_query_cache_ignores_records_from_another_model(tmp_path):
    path = tmp_path / "queries.jsonl"
    embeddings.EmbeddingCache(path, model="gemini-embedding-001").put_many(
        [("k", np.ones(config.EMBED_DIMENSIONS, dtype=np.float32))]
    )

    assert embeddings.EmbeddingCache(path, model="text-embedding-004").get("k") is None


def test_the_service_path_never_touches_disk(fake_api, recorder, monkeypatch):
    """A live request must not read or write the cache: Render's filesystem is
    ephemeral and the cache holds every vector it has seen in memory."""
    # This test shipped without calling fake_api(). The fixture only *returns* the
    # installer, so it ran against the real Gemini endpoint and spent a day of the
    # embedding quota on every full-suite run. It surfaced as a
    # DailyQuotaExhausted failure, which is how it was found.
    fake_api()

    def boom(*args, **kwargs):
        raise AssertionError("the default query path persisted to disk")

    monkeypatch.setattr(embeddings.EmbeddingCache, "put_many", boom)
    assert embeddings.get_cached_query_vector("a brief") is not None
    # Asserted so a future refactor that skips the stub cannot leave this quietly
    # reaching the network again: an empty recorder means nothing was embedded.
    assert len(recorder) == 1


def test_concurrent_writers_do_not_interleave_records(tmp_path):
    """One record is ~15 KB of JSON, far past the size at which an append is
    atomic, so the evaluator's concurrent cases would corrupt the file without
    the write lock."""
    cache = embeddings.EmbeddingCache(tmp_path / "queries.jsonl")
    dim = config.EMBED_DIMENSIONS

    def write(i):
        vector = np.random.default_rng(i).normal(size=dim).astype(np.float32)
        cache.put_many([(f"key-{i}", vector)])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))

    lines = [ln for ln in (tmp_path / "queries.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == 24
    assert len({json.loads(ln)["key"] for ln in lines}) == 24
