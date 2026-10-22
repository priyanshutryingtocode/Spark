"""Embedding and indexing: turns influencer profiles and brand briefs into
vectors, so retrieval.py can do semantic search over them.

Embeddings come from the Gemini embedding API rather than a local model. That
is what keeps the API service inside a 512 MB free-tier budget: a local
SentenceTransformer pulls in torch, which alone exceeds the whole allowance.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from . import config
from .corpora import Influencer
from .gemini_client import embed_content_throttled, get_client

BATCH_SIZE = 50

_client = None
_client_lock = threading.Lock()

_last_request_at = 0.0
_request_lock = threading.Lock()


def get_embedding_client():
    """Cached Gemini client. The SDK client is safe to share across threads."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = get_client()
    return _client


def _throttle() -> None:
    """Space out API calls to stay under the free tier's per-minute cap.

    The lock is held across the sleep on purpose: it makes the interval a
    process-wide floor rather than a per-thread one, so concurrent callers
    queue instead of bursting past the quota.
    """
    global _last_request_at
    interval = config.EMBED_REQUEST_INTERVAL_SECONDS
    if interval <= 0:
        return
    with _request_lock:
        wait = interval - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _normalize(vector) -> np.ndarray:
    """L2-normalize so pgvector's cosine distance is exact.

    The API's Matryoshka-truncated vectors are not unit-norm, and the search
    compares them with `embedding <=> query`.
    """
    array = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        raise RuntimeError(f"{config.EMBED_MODEL} returned a zero-magnitude vector")
    return array / norm


def _embed(text: str, task_type: str) -> np.ndarray:
    """Embed one text. The API accepts a single content per request."""
    _throttle()
    response = embed_content_throttled(
        get_embedding_client(),
        config.EMBED_MODEL,
        text,
        task_type=task_type,
        output_dimensionality=config.EMBED_DIMENSIONS,
    )
    values = response.embeddings[0].values
    vector = _normalize(values)
    if vector.shape[-1] != config.EMBED_DIMENSIONS:
        raise RuntimeError(
            f"{config.EMBED_MODEL} returned {vector.shape[-1]}-dim vectors but "
            f"EMBED_DIMENSIONS={config.EMBED_DIMENSIONS}. Change both together "
            f"and reindex."
        )
    return vector


def embed_documents(texts: list[str]) -> list[np.ndarray]:
    """Embed creator profiles for indexing (RETRIEVAL_DOCUMENT)."""
    return [_embed(text, config.EMBED_TASK_DOCUMENT) for text in texts]


def embed_query(text: str) -> np.ndarray:
    """Embed a brand brief for retrieval (RETRIEVAL_QUERY)."""
    return _embed(text, config.EMBED_TASK_QUERY)


_QUERY_CACHE_SIZE = 128
_query_cache: OrderedDict[str, np.ndarray] = OrderedDict()
_query_cache_lock = threading.Lock()


def _remember_query(key: str, vector: np.ndarray) -> None:
    with _query_cache_lock:
        _query_cache[key] = vector
        _query_cache.move_to_end(key)
        while len(_query_cache) > _QUERY_CACHE_SIZE:
            _query_cache.popitem(last=False)


def get_cached_query_vector(text: str, cache: EmbeddingCache | None = None) -> np.ndarray:
    """Embed a brief, reusing whatever has already been computed for it.

    `cache` is opt-in and defaults to None. The service leaves it None on
    purpose: a live request must not touch the disk, and EmbeddingCache holds
    every vector it has seen in memory, so wiring it into the request path
    would trade a bounded 128-entry LRU for unbounded growth on a 512 MB box.

    Offline tools pass a cache so a run can be repeated without re-billing the
    daily embedding quota. It must be a *query* cache: Gemini embeds documents
    and queries under different task types, so the same text yields two
    different vectors and the two must never share a file.
    """
    key = text_key(text)

    with _query_cache_lock:
        cached = _query_cache.get(key)
        if cached is not None:
            _query_cache.move_to_end(key)
            return cached

    if cache is not None:
        vector = cache.get(key)
        if vector is not None:
            _remember_query(key, vector)
            return vector

    vector = embed_query(text)
    with _query_cache_lock:
        # Another thread may have embedded the same brief while we waited on
        # the API; prefer whichever landed first so we only ever cache one.
        settled = _query_cache.get(key)
        if settled is not None:
            return settled
    _remember_query(key, vector)
    if cache is not None:
        cache.put_many([(key, vector)])
    return vector


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

class EmbeddingCache:
    """Append-only content-hash -> vector store on disk.

    Reindexing spends a large slice of the daily embedding quota, and a plain
    network hiccup halfway through would otherwise throw that spend away. The
    synthetic corpus is seeded, so re-running a reindex produces the same texts
    and every hit here is a request we do not have to make again. Entries
    recorded with a different model or width are ignored, so a cache from an
    earlier embedder can never poison a new index.
    """

    def __init__(self, path: Path, model: str | None = None, dimensions: int | None = None):
        self.path = Path(path)
        self.model = model or config.EMBED_MODEL
        self.dimensions = dimensions or config.EMBED_DIMENSIONS
        self.hits = 0
        self.misses = 0
        self._vectors: dict[str, list[float]] = {}
        self._write_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # truncated final line from an interrupted run
                if record.get("model") != self.model or record.get("dimensions") != self.dimensions:
                    continue
                key = record.get("key")
                values = record.get("values")
                if isinstance(key, str) and isinstance(values, list):
                    self._vectors[key] = values

    def contains(self, key: str) -> bool:
        """Membership test that leaves the hit/miss counters untouched.

        The CLI uses this to size the remaining work before spending anything,
        so the report it prints describes the run that is about to happen
        rather than the one that already finished.
        """
        return key in self._vectors

    def get(self, key: str) -> np.ndarray | None:
        values = self._vectors.get(key)
        if values is None:
            self.misses += 1
            return None
        self.hits += 1
        return _normalize(values)

    def put_many(self, entries: list[tuple[str, np.ndarray]]) -> None:
        if not entries:
            return
        with self._write_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for key, vector in entries:
                    self._vectors[key] = [float(value) for value in vector]
                    handle.write(json.dumps({
                        "key": key,
                        "model": self.model,
                        "dimensions": self.dimensions,
                        "values": self._vectors[key],
                    }) + "\n")
                handle.flush()

    def __len__(self) -> int:
        return len(self._vectors)


def index_records(
    records: list[Influencer],
    cache: EmbeddingCache | None = None,
) -> None:
    """Populate the .embedding field on every record, in this process.

    Corpus-generic already: the only thing it needs from a record is
    `corpus_text()`, so a second corpus works without a branch here.

    Vectors are persisted to Postgres/pgvector by vector_store.replace_records,
    so this only runs on generation/reindex, not on every query. When a cache is
    supplied, already-embedded texts are reused and only the misses are billed.
    """
    done = 0
    pending: list[tuple[Influencer, str]] = []
    for record in records:
        text = record.corpus_text()
        key = text_key(text)
        vector = cache.get(key) if cache is not None else None
        if vector is None:
            pending.append((record, text))
        else:
            record.embedding = vector
            done += 1

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        vectors = embed_documents([text for _, text in batch])
        for (record, _), vec in zip(batch, vectors):
            record.embedding = vec
        if cache is not None:
            cache.put_many([(text_key(text), vec) for (_, text), vec in zip(batch, vectors)])
        done += len(batch)
        print(f"  embedded {done}/{len(records)}", flush=True)
