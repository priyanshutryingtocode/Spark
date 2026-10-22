"""Tests for the reindex CLI's quota ergonomics.

These cover the two failure modes that actually bite a bulk reindex on the
free tier: spending a whole day of quota on a corpus that does not match the
cache, and dying on a daily cap without explaining how to resume.
"""

from types import SimpleNamespace

import numpy as np
import pytest

import main
from src import config
from src.data_generator import generate_influencers
from src.embeddings import EmbeddingCache, text_key
from src.gemini_client import DailyQuotaExhausted


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    """Any attempt to reach PostgreSQL fails the test loudly.

    These tests exercise a CLI whose real job is to write the index, so
    without this a passing run could quietly truncate the live table.
    """

    def forbidden(*args, **kwargs):
        raise AssertionError("reindex CLI tests must not open a database connection")

    monkeypatch.setattr(main.vector_store, "get_connection", forbidden)


def make_args(tmp_path, **overrides):
    defaults = dict(
        platform="Instagram",
        audience="Gen Z",
        vibe="warm, friendly",
        count=3,
        balanced=False,
        balanced_floor=3,
        top_k=10,
        top_n=5,
        reindex=True,
        index_only=False,
        # limit keeps the run embed-only, which is the path that never writes.
        limit=3,
        embed_cache=tmp_path / "vectors.jsonl",
        no_embed_cache=False,
        kind="creator",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def bank(cache: EmbeddingCache, influencers, count: int) -> None:
    """Pretend the first `count` creators were already embedded."""
    cache.put_many([
        (text_key(influencer.corpus_text()),
         np.full(config.EMBED_DIMENSIONS, 0.3, dtype=np.float32))
        for influencer in influencers[:count]
    ])


def test_limit_with_index_only_never_writes(tmp_path, monkeypatch, capsys):
    """`--limit N --index-only` must not replace the live index.

    `--limit` is documented as writing nothing, but the guard used to read
    `bool(args.limit) and not args.index_only`, so passing `--index-only`
    alongside it flipped the guard to False and the run proceeded to
    replace_records() -- TRUNCATE plus insert N rows. On a shared database
    that is `--limit 5 --index-only` silently destroying an indexed corpus.

    The `no_database` fixture raises on any connection attempt, so reaching the
    write at all fails this test.
    """
    args = make_args(tmp_path, limit=3, index_only=True)
    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)

    main.ensure_indexed(args)
    captured = capsys.readouterr()

    assert "Ignoring --index-only" in captured.out
    assert "never writes" in captured.out


def test_limit_alone_still_reports_the_smoke_test(tmp_path, monkeypatch, capsys):
    args = make_args(tmp_path, limit=3, index_only=False)
    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)

    main.ensure_indexed(args)
    captured = capsys.readouterr()

    assert "Ignoring --index-only" not in captured.out
    assert "database was left untouched" in captured.out


def test_preflight_reports_reuse_and_remaining_requests(tmp_path, monkeypatch, capsys):
    args = make_args(tmp_path)
    influencers = generate_influencers(count=args.count)
    cache = EmbeddingCache(args.embed_cache)
    bank(cache, influencers, 2)

    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)
    main.ensure_indexed(args)
    captured = capsys.readouterr()

    assert "Reusing 2 of" in captured.out
    assert f"{len(influencers) - 2} requests still needed" in captured.out
    assert "WARNING" not in captured.err


def test_preflight_treats_a_multi_day_build_as_progress_not_mistake(tmp_path, monkeypatch, capsys):
    # A build in progress: most of the cache belongs to *this* dataset already
    # (banked by earlier days), with a few leftovers from the previous,
    # smaller index. Reuse is a large share of the cache, so nothing is wasted.
    args = make_args(tmp_path, count=300, limit=300)
    influencers = generate_influencers(count=300)
    cache = EmbeddingCache(args.embed_cache)
    cache.put_many([
        (f"older-dataset-{index}", np.full(config.EMBED_DIMENSIONS, 0.3, dtype=np.float32))
        for index in range(20)
    ])
    bank(cache, influencers, 100)

    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)
    main.ensure_indexed(args)
    captured = capsys.readouterr()

    assert "Reusing 100 of 300" in captured.out
    assert "200 requests still needed" in captured.out
    assert "WARNING" not in captured.err
    assert "resumes from this cache on the next run" in captured.out


def test_preflight_warns_when_the_corpus_does_not_match_the_cache(tmp_path, monkeypatch, capsys):
    # A corpus switch: the cache belongs to another dataset, so almost none of
    # it is usable and every entry is about to be wasted.
    args = make_args(tmp_path)
    cache = EmbeddingCache(args.embed_cache)
    cache.put_many([
        (f"unrelated-{index}", np.full(config.EMBED_DIMENSIONS, 0.3, dtype=np.float32))
        for index in range(60)
    ])

    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)
    main.ensure_indexed(args)
    captured = capsys.readouterr()

    assert "WARNING" in captured.err
    assert "only 0 of the 60 cached vectors belong to this dataset" in captured.err
    assert "--balanced-floor" in captured.err


def test_preflight_warns_once_at_the_start_of_a_deliberate_corpus_switch(tmp_path, monkeypatch, capsys):
    # Day one of moving from a 1,000-row index to a 3,000-row one: the old cache
    # is entirely unusable, so this warns. Later days reuse a growing share of
    # the cache and stop warning, which is the whole point of the threshold.
    args = make_args(tmp_path, count=300, limit=300)
    influencers = generate_influencers(count=300)
    cache = EmbeddingCache(args.embed_cache)
    cache.put_many([
        (f"old-index-{index}", np.full(config.EMBED_DIMENSIONS, 0.3, dtype=np.float32))
        for index in range(100)
    ])

    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)
    main.ensure_indexed(args)
    assert "WARNING" in capsys.readouterr().err

    later = EmbeddingCache(args.embed_cache)
    bank(later, influencers, 100)
    main._report_remaining_work(influencers, later)
    assert "WARNING" not in capsys.readouterr().err


def test_no_cache_reports_the_full_spend(tmp_path, monkeypatch, capsys):
    args = make_args(tmp_path, no_embed_cache=True)
    monkeypatch.setattr(main, "index_records", lambda profiles, cache=None: None)

    main.ensure_indexed(args)
    out = capsys.readouterr().out

    assert "No vector cache in use: 3 requests will be spent." in out


def test_daily_cap_exits_cleanly_with_a_resume_report(tmp_path, monkeypatch, capsys):
    args = make_args(tmp_path)
    influencers = generate_influencers(count=args.count)
    cache = EmbeddingCache(args.embed_cache)
    bank(cache, influencers, 2)

    def explode(profiles, cache=None):
        raise DailyQuotaExhausted("embed_content(gemini-embedding-001)", "SomePerDayQuota", 1000)

    monkeypatch.setattr(main, "index_records", explode)

    with pytest.raises(SystemExit) as exit_info:
        main.ensure_indexed(args)

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    # No traceback, and the operator is told exactly what to do next.
    assert "exhausted its daily free-tier quota" in captured.err
    assert "midnight Pacific" in captured.err
    assert "re-run the same command" in captured.err
    assert "Traceback" not in captured.err
    # The banked work is still reported.
    assert "2 vectors banked" in captured.out


def test_contains_does_not_disturb_the_counters(tmp_path):
    cache = EmbeddingCache(tmp_path / "vectors.jsonl")
    cache.put_many([("key-a", np.full(config.EMBED_DIMENSIONS, 0.3, dtype=np.float32))])

    assert cache.contains("key-a") is True
    assert cache.contains("key-b") is False
    assert (cache.hits, cache.misses) == (0, 0)
