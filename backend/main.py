"""CLI entry point for the influencer matching pipeline.

Usage:
    python main.py
    python main.py --goal "high-energy strength training for beginners" --platform TikTok \\
        --audience "millennials, home gym" --vibe "high energy, no-nonsense"
    python main.py --reindex   # clear and regenerate/re-embed the database
    python main.py --limit 5   # embedding smoke test, writes nothing
"""

import argparse
import sys
from pathlib import Path

from api.repositories.postgres_run_repository import PostgresRunRepository
from src import config, vector_store
from src.data_generator import generate_balanced_influencers, generate_influencers
from src.prospect_generator import generate_balanced_prospects, generate_prospects
from src.platforms import PLATFORMS
from src.embeddings import EmbeddingCache, index_records, text_key
from src.formatting import print_brief, print_results
from src.gemini_client import DailyQuotaExhausted, get_client
from src.match_service import rank_match, retrieve_for_run
from src.corpora import SYNTHETIC_KINDS, get_corpus
from src.models import Brief
from src.retrieval import rerank_candidates

CACHE_DIR = Path(__file__).resolve().parent / ".embed-cache"
_ORPHAN_WARN_MIN = 50
_MIN_CACHE_REUSE_RATIO = 0.05


def positive_int(max_value: int | None = None):
    """argparse type factory: rejects zero/negative values (and, if given,
    anything above max_value) instead of silently accepting them and
    failing later inside a SQL LIMIT or an oversized Gemini batch."""

    def _parse(value: str) -> int:
        n = int(value)
        if n <= 0:
            raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
        if max_value is not None and n > max_value:
            raise argparse.ArgumentTypeError(f"must be <= {max_value}, got {n}")
        return n

    return _parse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate, embed and index a corpus, then match a brand brief against it.")
    # A neutral example rather than the specific brand this file used to
    # advertise, so a bare `python main.py` demos the same goal-only query shape
    # the API and the evaluation use. Not empty: unlike the API path, nothing
    # calls _validate_brief here, so a blank --goal would embed an empty query
    # and fail deep inside the Gemini call instead of at the argument.
    parser.add_argument(
        "--goal",
        default="high-energy strength training for beginners",
        help="Free-text description of what the brand wants",
    )
    parser.add_argument("--platform", default="Instagram", choices=["Any", *PLATFORMS])
    # Optional, and empty by default for the same reason as the API's meta
    # defaults: Brief.query_text() folds a non-empty value into the embedded
    # query, so any default here silently becomes part of every run's ranking.
    parser.add_argument("--audience", default="")
    parser.add_argument("--vibe", default="")
    parser.add_argument(
        "--count", type=positive_int(config.MAX_INFLUENCER_COUNT),
        default=config.DEFAULT_INFLUENCER_COUNT, help="Size of the synthetic database",
    )
    parser.add_argument(
        "--balanced", action="store_true", 
        help="Generate balanced dataset with a minimum floor per (topic group, platform) cell"
    )
    parser.add_argument(
        "--balanced-floor", type=positive_int(),
        default=3,
        help="--balanced only: minimum profiles per (topic group, platform) cell; "
             "sets the dataset's minimum size (groups x platforms x floor)",
    )
    parser.add_argument(
        "--top-k", type=positive_int(config.MAX_TOP_K),
        default=config.DEFAULT_TOP_K_RETRIEVAL, help="Candidates to retrieve before ranking",
    )
    parser.add_argument(
        "--top-n", type=positive_int(config.MAX_TOP_K),
        default=config.DEFAULT_TOP_N_RANKED, help="Final shortlist size",
    )
    parser.add_argument("--reindex", action="store_true", help="Clear and regenerate/re-embed the database even if already populated")
    parser.add_argument("--index-only", action="store_true", help="Initialize or populate the creator index without running a sample match")
    parser.add_argument(
        "--limit", type=positive_int(),
        help="Embed only the first N profiles and write nothing. Use it to smoke "
             "test the embedding API before spending a full reindex's quota. Takes "
             "precedence over --index-only: combining them will not write either.",
    )
    parser.add_argument(
        "--embed-cache", type=Path,
        help="Vector cache to reuse and append to (default: backend/.embed-cache/).",
    )
    parser.add_argument(
        "--no-embed-cache", action="store_true",
        help="Ignore any cached vectors and re-embed every record.",
    )
    parser.add_argument(
        "--kind", choices=sorted(SYNTHETIC_KINDS), default="creator",
        help="Which corpus to generate and index. Prospects are indexing-only: "
             "ranking them arrives with their own rubric, and asking for a match "
             "here is refused rather than answered with creator rules.",
    )
    args = parser.parse_args()

    if args.top_n > args.top_k:
        parser.error(f"--top-n ({args.top_n}) can't be greater than --top-k ({args.top_k})")

    # Refused here, at parse time, rather than deep in the pipeline. A corpus
    # with no rubric of its own would otherwise reach another corpus's rules and
    # print confident nonsense about records it was never asked about.
    if args.kind != "creator" and not (args.index_only or args.limit):
        if get_corpus(args.kind, "synthetic").rubric is None:
            parser.error(
                f"--kind {args.kind} can generate and index only. Ranking a "
                f"{args.kind} needs its own rubric, which this corpus does not "
                f"define; pass --index-only to build the corpus."
            )

    return args


def default_cache_path() -> Path:
    safe_model = config.EMBED_MODEL.replace("/", "_")
    return CACHE_DIR / f"{safe_model}-{config.EMBED_DIMENSIONS}d.jsonl"


def _generate(args, corpus) -> list:
    """Build the corpus named by --kind.

    Balanced generation means something slightly different per corpus, and the
    difference is deliberate rather than an oversight: creators balance over
    tag-group x platform because platform is a hard filter, prospects over
    industry x size tier because that is the pair a brief actually names.
    """
    if args.balanced:
        if corpus.kind == "creator":
            return generate_balanced_influencers(
                count=args.count, min_per_group_platform=args.balanced_floor
            )
        return generate_balanced_prospects(
            count=args.count, min_per_cell=args.balanced_floor
        )
    if corpus.kind == "creator":
        return generate_influencers(count=args.count)
    return generate_prospects(count=args.count)


def ensure_indexed(args) -> None:
    """Only regenerate + re-embed if the corpus is empty or --reindex was
    passed. Generation and embedding happen entirely before any database
    write -- if anything fails partway (bad key, network, quota), nothing
    here has touched the database yet, so existing indexed data survives.
    """
    corpus = get_corpus(args.kind, "synthetic")

    # `--limit` is the only flag that can suppress a write, so it is checked on
    # its own.
    embed_only = bool(args.limit)
    if args.limit and args.index_only:
        print(
            "Ignoring --index-only: --limit never writes, and combining the two "
            "would otherwise have replaced the live index with the first "
            f"{args.limit} records.",
        )

    if not embed_only:
        with vector_store.get_connection() as conn:
            existing = vector_store.count_records(conn, corpus.table)
        if existing and not args.reindex:
            print(f"Found {existing} indexed {corpus.kind} records, "
                  f"skipping re-embedding. Pass --reindex to rebuild.")
            return

    print(f"Generating synthetic {corpus.kind} database...")
    records = _generate(args, corpus)
    if args.limit:
        records = records[:args.limit]

    cache = None
    if not args.no_embed_cache:
        cache = EmbeddingCache(args.embed_cache or default_cache_path())

    _report_remaining_work(records, cache)

    print(f"Embedding {len(records)} {corpus.kind} records with "
          f"{config.EMBED_MODEL} ({config.EMBED_DIMENSIONS}d)...")
    try:
        index_records(records, cache=cache)
    except DailyQuotaExhausted as exc:
        _report_cache(cache)
        print(str(exc), file=sys.stderr)
        print(
            "Nothing was lost: re-run the same command after the reset and the "
            f"cached vectors are reused, so only the remaining {corpus.kind} "
            "records are billed.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    _report_cache(cache)

    if embed_only:
        print("--limit was used, so the database was left untouched. "
              "Re-run without --limit to write the index.")
        return

    print(f"Writing {corpus.kind} records to {corpus.table} (atomic replace)...")
    with vector_store.get_connection() as conn:
        vector_store.replace_records(conn, records, corpus)
    return True


def _report_remaining_work(records, cache: EmbeddingCache | None) -> None:
    """Say what a reindex is about to cost before it costs anything.

    Embeddings are billed per record and the free tier caps them per day, so a
    large build is expected to stop at the cap and resume. That must not be
    reported the same way as a run that is about to waste an already-paid-for
    cache because the flags changed, so the two cases are told apart by whether
    the cache holds vectors this dataset cannot use.
    """
    if cache is None:
        print(f"No vector cache in use: {len(records)} requests will be spent.")
        return

    keys = [text_key(record.corpus_text()) for record in records]
    reusable = sum(1 for key in keys if cache.contains(key))
    remaining = len(keys) - reusable
    interval = config.EMBED_REQUEST_INTERVAL_SECONDS
    estimate = f"~{int(remaining * interval)}s" if interval > 0 else "no throttle"
    print(f"Vector cache: {len(cache)} vectors in {cache.path}")
    print(f"Reusing {reusable} of {len(keys)} records; "
          f"{remaining} requests still needed ({estimate}).")

    if len(cache) >= _ORPHAN_WARN_MIN and reusable < len(cache) * _MIN_CACHE_REUSE_RATIO:
        print(
            f"WARNING: only {reusable} of the {len(cache)} cached vectors belong to this "
            f"dataset. The generator is seeded, so a reindex only reuses cached vectors "
            f"when --count and --balanced-floor match the previous run. Continuing spends "
            f"{remaining} fresh requests, and the rest of the cache goes unused.",
            file=sys.stderr,
        )
    elif remaining:
        print(
            "The free tier caps embedding at 1,000 requests/day, so a build this size "
            "stops at the cap and resumes from this cache on the next run. The database "
            "is only written once every creator is embedded."
        )


def _report_cache(cache: EmbeddingCache | None) -> None:
    if cache is None:
        return
    print(f"Embedding API calls this run: {cache.misses} "
          f"({cache.hits} reused, {len(cache)} vectors banked in {cache.path}).")


def main() -> None:
    args = parse_args()

    PostgresRunRepository().ensure_schema()
    with vector_store.get_connection() as conn:
        vector_store.init_schema(conn)

    ensure_indexed(args)
    if args.index_only or args.limit:
        return

    # The corpus the brief is answered against. `--kind` has always named the
    # corpus to build; it now also names the corpus to search, so a company
    # match from the command line searches companies.
    corpus = get_corpus(args.kind, "synthetic")
    brief = Brief(
        goal=args.goal,
        # A corpus with no platform facet ignores the platform entirely, so
        # carrying one in the brief would put a fact that is not true of the
        # search into the run's record.
        platform=args.platform if corpus.facet_is_hard_filter else "Any",
        audience=args.audience,
        vibe=args.vibe,
    )
    print_brief(brief)

    print("\nRetrieving candidates (metadata filter + pgvector search)...")
    # The relaxing retriever, the same one the API uses: it drops the filters
    # one at a time until the corpus has something to say, and says which it
    # dropped. A CLI that returned nothing where the app returns an explained
    # result would not be reproducing what the app does.
    candidates, relaxed = retrieve_for_run(brief, top_k=args.top_k, corpus=corpus)
    if relaxed:
        print(f"  WARNING: no {corpus.kind} matched every filter; dropped: {', '.join(relaxed)}")
    if not candidates:
        print(f"No {corpus.kind} records found for that brief.")
        return
    print(f"  {len(candidates)} candidates returned")

    candidates = rerank_candidates(brief, candidates, corpus=corpus)
    print("\nRanking with Gemini...")
    ranked = rank_match(
        brief,
        candidates,
        top_n=args.top_n,
        client=get_client(),
        corpus=corpus,
        relaxed_filters=relaxed,
    )

    candidates_by_id = {c.id: c for c in candidates}
    print_results(ranked, candidates_by_id, brief=brief, corpus=corpus)


if __name__ == "__main__":
    main()
