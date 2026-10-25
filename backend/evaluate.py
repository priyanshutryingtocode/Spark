"""Evaluate retrieval and ranking against a versioned golden brief set.

Usage:
    python evaluate.py
    python evaluate.py --top-k 10 --top-n 5 --output reports/evaluation-report.json
    python evaluate.py --sequential   # old one-at-a-time pacing

A case is relevant when a retrieved creator carries at least one of the case's
`expected_tags`. Replace those tags with human-labelled outcomes when real
creator data is available.

Relevance is defined by intersection, not equality: creators now span several
topics, so a creator tagged across two areas counts for both. That inflates
precision relative to the older single-label definition and makes `pool_size`
larger, so reports written before this change are not comparable to these.

Cases run in batches sized to the rate limit (default 10/minute): each batch
fires concurrently, then the runner waits out the rest of that minute-window
before the next batch. Per-case latency timings are unaffected -- they only
cover that case's own retrieval/ranking work.
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean
from time import perf_counter

from api.repositories.postgres_run_repository import PostgresRunRepository
from src import config, vector_store
from src.corpora import CREATORS, KINDS, get_corpus
from src.embeddings import EmbeddingCache, embed_query, get_cached_query_vector
from src.text_match import overlap_ratio, terms
from src.gemini_client import get_client
from src.match_service import rank_match, retrieve_for_run
from src.retrieval import rerank_candidates
from src.models import Brief

BACKEND_ROOT = Path(__file__).resolve().parent
#: One golden dataset per corpus. They are separate files, not one file with a
#: kind field, because the two suites ask different questions: a creator brief
#: is about content and audience, a prospect brief about company fit.
DEFAULT_CASES = {
    "creator": BACKEND_ROOT / "data" / "evaluation_cases.json",
    "prospect": BACKEND_ROOT / "data" / "prospect_cases.json",
}
REPORTS_DIR = BACKEND_ROOT / "reports"
DEFAULT_QUERY_CACHE = BACKEND_ROOT / ".embed-cache"


def default_query_cache_path() -> Path:
    """A cache file dedicated to query vectors.

    Deliberately not the document cache that main.py writes: Gemini embeds
    under a different task type for queries than for documents, so one text
    has two legitimate vectors. Sharing a file would hand a document vector to
    retrieval and quietly skew every retrieval score.
    """
    safe_model = config.EMBED_MODEL.replace("/", "_")
    return DEFAULT_QUERY_CACHE / f"{safe_model}-{config.EMBED_DIMENSIONS}d-queries.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval (and ranking, where a rubric exists) quality.")
    parser.add_argument(
        "--kind", choices=sorted(KINDS), default="creator",
        help="Which corpus to evaluate against. Ranking is measured for any "
             "corpus that has a rubric of its own, and omitted entirely for one "
             "that has not, rather than scoring it with another corpus's rules.",
    )
    parser.add_argument("--cases", type=Path, default=None,
                        help="JSON golden-brief dataset (default: the --kind corpus's own)")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="JSON metrics output. Defaults to reports/evaluation-<kind>-<rows>.json, "
             "named for BOTH the corpus and its size, so runs cannot overwrite or be "
             "mistaken for each other. A creator run at 2000 and a prospect run at 500 "
             "are different measurements.",
    )
    parser.add_argument("--top-k", type=int, default=config.DEFAULT_TOP_K_RETRIEVAL)
    parser.add_argument("--top-n", type=int, default=config.DEFAULT_TOP_N_RANKED)
    parser.add_argument(
        "--no-ranking", action="store_true",
        help="Measure retrieval only, spending no ranking quota. The ranking "
             "metrics are omitted from the report rather than reported as zero, "
             "and the report says ranking was skipped and why.",
    )
    parser.add_argument(
        "--rate-limit-per-min", type=int, default=10,
        help="Max ranking requests per minute to throttle to (free tier = 10). "
             "Cases run in concurrent batches of this size.",
    )
    parser.add_argument(
        "--sequential", action="store_true",
        help="Run cases one at a time with even spacing (pre-parallel behavior).",
    )
    parser.add_argument(
        "--query-cache", type=Path, default=None,
        help="Reuse and append query vectors here so a repeat run costs no "
             "embedding quota (default: backend/.embed-cache/*-queries.jsonl).",
    )
    parser.add_argument(
        "--no-query-cache", action="store_true",
        help="Re-embed every case even if its vector was computed before.",
    )
    args = parser.parse_args()
    if args.cases is None:
        args.cases = DEFAULT_CASES[args.kind]
    if args.top_k <= 0 or args.top_n <= 0 or args.top_n > args.top_k:
        parser.error("top-k and top-n must be positive, and top-n cannot exceed top-k")
    if args.rate_limit_per_min <= 0:
        parser.error("--rate-limit-per-min must be positive")

    config.EMBED_REQUEST_INTERVAL_SECONDS = 0.0
    return args


def batch_windows(total: int, per_minute: int) -> list[list[int]]:
    """Split case indices into rate-limit windows: window w gets indices
    [w*per_minute, (w+1)*per_minute). Pure so the scheduling math is testable."""
    if per_minute <= 0 or total <= 0:
        return []
    return [
        list(range(start, min(start + per_minute, total)))
        for start in range(0, total, per_minute)
    ]


def icp_match(candidate, expected_icp: dict, corpus=None) -> bool:
    """Whether a company fits the ICP a brief stated.

    The company counterpart of `audience_match`: the industry has to be one of
    the wanted ones (when the brief named any -- a cross-vertical brief names
    none), the size has to be inside the band, and the country has to be one of
    the wanted ones. Every clause the brief stated is a requirement.

    The industries are expanded through the corpus's verticals, the same way the
    filter expands them. Without that the filter and the metric disagreed: a
    "supply chain" company passed a "logistics" filter and was then scored as
    wrong, so the report understated the corpus it was measuring.
    """
    if not expected_icp:
        return True
    industries = expected_icp.get("industries") or []
    if industries:
        if corpus is not None and getattr(corpus, "vertical_column", None):
            from src.scoring import expand_vertical

            industries = expand_vertical(list(industries), corpus.verticals)
        if str(candidate.industry) not in {str(i) for i in industries}:
            return False
    size = expected_icp.get("size")
    if size:
        low, high = size[0], size[1]
        if not low <= int(candidate.headcount) <= high:
            return False
    countries = expected_icp.get("countries") or []
    if countries and str(candidate.country) not in {str(c) for c in countries}:
        return False
    return True


def icp_precision(items, expected_icp: dict, corpus=None) -> float:
    if not items or not expected_icp:
        return 0.0
    return sum(1 for item in items if icp_match(item, expected_icp, corpus)) / len(items)


def audience_match(candidate, expected_audience: dict) -> bool:
    """Whether a candidate's audience fits the campaign's target audience.

    A conjunction: the age band has to be one of the wanted ones, the country
    has to be one of the wanted ones, and the gender split has to lean the way
    the brief asked. "Any" is satisfied by anything, so a brief that does not
    care about gender does not penalise a candidate for it.
    """
    if not expected_audience:
        return True
    age = expected_audience.get("age") or []
    if age and str(candidate.audience_age) not in {str(a) for a in age}:
        return False
    countries = expected_audience.get("countries") or []
    if countries and str(candidate.audience_country) not in {str(c) for c in countries}:
        return False
    return audience_gender_match(candidate, expected_audience.get("gender"))


def audience_gender_match(candidate, expected_gender) -> bool:
    gender = str(expected_gender or "any").strip().lower()
    if gender in {"", "any"}:
        return True
    split = str(getattr(candidate, "audience_gender", "") or "").lower()
    if gender.startswith("f"):
        return "female" in split and "male" not in split
    if gender.startswith("m"):
        return "male" in split and "female" not in split
    return True


def fit_dimension_scores(items, expected_fit: dict, corpus=None) -> tuple[dict, float | None]:
    """Score each stated audience/ICP requirement and required-field coverage.

    Overall fit is useful as a headline but hides which constraint is failing.
    A missing value fails its fit dimension; coverage separately identifies
    when the source record did not provide the fields needed to judge the fit.
    Dimensions not requested by a case are omitted.
    """
    if not expected_fit:
        return {}, None

    if corpus is not None and corpus.kind != "creator":
        industries = expected_fit.get("industries") or []
        if industries and getattr(corpus, "vertical_column", None):
            from src.scoring import expand_vertical

            industries = expand_vertical(list(industries), corpus.verticals)
        size = expected_fit.get("size")
        countries = expected_fit.get("countries") or []
        checks = {}
        if industries:
            wanted = {str(value) for value in industries}
            checks["industry"] = (
                lambda item: bool(str(getattr(item, "industry", "") or "").strip()),
                lambda item: str(getattr(item, "industry", "")) in wanted,
            )
        if size:
            low, high = size
            checks["size"] = (
                lambda item: getattr(item, "headcount", None) is not None,
                lambda item: getattr(item, "headcount", None) is not None
                and low <= int(item.headcount) <= high,
            )
        if countries:
            wanted = {str(value) for value in countries}
            checks["country"] = (
                lambda item: bool(str(getattr(item, "country", "") or "").strip()),
                lambda item: str(getattr(item, "country", "")) in wanted,
            )
    else:
        ages = {str(value) for value in expected_fit.get("age", [])}
        countries = {str(value) for value in expected_fit.get("countries", [])}
        gender = expected_fit.get("gender")
        checks = {}
        if ages:
            checks["audience_age"] = (
                lambda item: bool(str(getattr(item, "audience_age", "") or "").strip()),
                lambda item: str(getattr(item, "audience_age", "")) in ages,
            )
        if countries:
            checks["audience_country"] = (
                lambda item: bool(str(getattr(item, "audience_country", "") or "").strip()),
                lambda item: str(getattr(item, "audience_country", "")) in countries,
            )
        if gender and str(gender).strip().lower() not in {"", "any"}:
            checks["audience_gender"] = (
                lambda item: bool(str(getattr(item, "audience_gender", "") or "").strip()),
                lambda item: audience_gender_match(item, gender),
            )

    if not checks:
        return {}, None
    scores = {
        name: round(sum(1 for item in items if matches(item)) / len(items), 3)
        if items else 0.0
        for name, (_, matches) in checks.items()
    }
    coverage = round(
        sum(1 for item in items if all(has_value(item) for has_value, _ in checks.values()))
        / len(items),
        3,
    ) if items else 0.0
    return scores, coverage


def summarize_fit_metrics(case_results: list[dict], ranks: bool) -> tuple[dict, dict]:
    """Macro-average each requested fit dimension and coverage across cases.

    `cases` is included beside every mean because dimensions can be absent from
    some briefs. The average is case-weighted, so a case with many matching
    candidates cannot dominate the suite.
    """
    levels = ["retrieval", "reranked"] + (["ranked"] if ranks else [])
    dimensions_summary: dict[str, dict] = {}
    coverage_summary: dict[str, dict] = {}
    for level in levels:
        per_dimension: dict[str, list[float]] = {}
        coverage_values: list[float] = []
        for case in case_results:
            for name, value in case.get("fit_dimensions_at_n", {}).get(level, {}).items():
                if value is not None:
                    per_dimension.setdefault(name, []).append(value)
            coverage = case.get("fit_data_coverage_at_n", {}).get(level)
            if coverage is not None:
                coverage_values.append(coverage)
        dimensions_summary[level] = {
            name: {"mean_precision": round(mean(values), 3), "cases": len(values)}
            for name, values in sorted(per_dimension.items())
        }
        coverage_summary[level] = {
            "mean_coverage": round(mean(coverage_values), 3) if coverage_values else None,
            "cases": len(coverage_values),
        }
    return dimensions_summary, coverage_summary


def audience_precision(items, expected_audience: dict) -> float:
    """The share of `items` whose audience fits the campaign."""
    if not items or not expected_audience:
        return 0.0
    return sum(1 for item in items if audience_match(item, expected_audience)) / len(items)


def fit_precision(items, expected_fit: dict, corpus=None) -> float:
    """How well a shortlist fits what the brief asked for.

    The audience for a creator, the ICP for a company. Dispatched on the corpus
    rather than told which to use, so a call site cannot get it wrong by passing
    the wrong expectation.
    """
    if not items or not expected_fit:
        return 0.0
    if corpus is not None and corpus.kind != "creator":
        return icp_precision(items, expected_fit, corpus)
    return audience_precision(items, expected_fit)


def campaign_precision(items, expected_tags: set[str], expected_audience: dict,
                       corpus=None) -> float:
    """The share of `items` that are both on-topic and on-fit.

    This is the metric that says whether the shortlist is a campaign shortlist
    rather than two separate lists. The topical and fit halves are reported on
    their own as well, because a change in one that is hidden by the other is
    not a measurement.
    """
    if not items:
        return 0.0
    # A company fits an ICP; a creator fits an audience. The matcher follows the
    # corpus rather than being told which to use, so a call site cannot get it
    # wrong by passing the wrong one.
    is_company = corpus is not None and corpus.kind != "creator"
    def fits(item) -> bool:
        if is_company:
            return icp_match(item, expected_audience, corpus)
        return audience_match(item, expected_audience)
    hits = sum(1 for item in items if expected_tags & set(item.tags) and fits(item))
    return hits / len(items)


def tag_precision(items, expected_tags: set[str]) -> float:
    """Share of retrieved creators carrying at least one of the case's tags.

    Intersection-based by design, since creators now span several topics. The
    known cost is that a creator tagged across two topics counts as correct for
    both cases, which inflates precision relative to the old single-label
    definition; `tag_overlap` is reported alongside so the two can be read
    together.
    """
    if not items or not expected_tags:
        return 0.0
    return sum(bool(expected_tags & set(item.tags)) for item in items) / len(items)


def pool_for(
    conn,
    expected_tags: set[str],
    platform: str,
    table: str = vector_store.DEFAULT_TABLE,
) -> int:
    """Creators in the index that share at least one of the case's tags.

    This is the union, not a sum: a creator carrying two of the tags is one
    relevant creator, and `COUNT(DISTINCT id)` is what makes that correct.
    Summing per-tag counts would overstate the pool and make the ceiling
    unreachable in principle. It cannot come from `pool_sizes` because the
    relevant set is a union across tags rather than one grouped cell, so it
    costs one small indexed query per case.
    """
    if not expected_tags:
        return 0
    sql = (
        f"SELECT COUNT(DISTINCT {table}.id) FROM {table}, unnest(tags) AS tag "
        "WHERE tag = ANY(%s)"
    )
    params: list = [sorted(expected_tags)]
    if platform != "Any":
        sql += f" AND {table}.platform = %s"
        params.append(platform)
    return int(conn.execute(sql, params).fetchone()[0])


def ceiling_precision(pool: int, k: int) -> float:
    """Best precision@k this case could reach given what exists in the index."""
    return min(pool, k) / k if k > 0 else 0.0


def recall_of_ceiling(retrieved: int, pool: int, k: int) -> float:
    """Share of the relevant creators that could fit in the top k.

    1.0 means every achievable match was retrieved, which is the only reading
    of precision@k that stays comparable across corpus sizes. An empty pool
    counts as 1.0: there was nothing to find, so nothing was missed.
    """
    reachable = min(pool, k)
    return retrieved / reachable if reachable else 1.0


def _warmup(conn, corpus) -> None:
    """Absorb cold-start costs (first embedding API call + first HNSW query) so
    case #1 isn't timed against them. Without this, the very first retrieval
    pays the embedding round-trip plus a cold full-table scan over the Any
    platform, inflating one case's retrieval_latency."""
    query_vec = embed_query("warmup")
    vector_store.search(conn, query_embedding=query_vec, corpus=corpus, facet=None, top_k=1)


def _run_case(client, case: dict, top_k: int, top_n: int, query_cache=None,
              corpus=CREATORS, ranks: bool = True) -> dict:
    # A creator case states its target audience; a company case states its ICP.
    # Both are the brief's requirements AND the definition of a correct
    # candidate, so one field drives the filters and the judgement.
    #
    # The ICP was being dropped here: the brief was built from
    # `expected_audience` alone, which a company case does not have, so the
    # company evaluation ran briefs with no industry, size or country filter at
    # all -- it measured unfiltered retrieval and called it the filtered path.
    expected_audience = case.get("expected_audience") or {}
    expected_icp = case.get("expected_icp") or {}
    expected_fit = expected_icp or expected_audience
    brief = Brief(
        goal=case["goal"], platform=case.get("platform", "Any"),
        audience=case.get("audience", ""), vibe=case.get("vibe", ""),
        audience_age=list(expected_audience.get("age", [])),
        audience_gender=expected_audience.get("gender", ""),
        audience_countries=list(expected_audience.get("countries", [])),
        target_industries=list(expected_icp.get("industries", [])),
        target_size=tuple(expected_icp["size"]) if expected_icp.get("size") else None,
        target_countries=list(expected_icp.get("countries", [])),
    )
    expected_tags = set(case["expected_tags"])
    brief_terms = terms(f"{brief.goal} {brief.audience} {brief.vibe}")

    embed_start = perf_counter()
    query_vec = get_cached_query_vector(brief.query_text(), query_cache)
    embed_ms = round((perf_counter() - embed_start) * 1000, 1)

    search_start = perf_counter()
    candidates, relaxed_filters = retrieve_for_run(
        brief, top_k=top_k, query_vec=query_vec, corpus=corpus
    )
    search_ms = round((perf_counter() - search_start) * 1000, 1)
    # The reranked shortlist, computed before any ranking call. Both orders are
    # kept so the report can show what the rerank changed and what it cost -- the
    # audience metric should rise and the topical one should not collapse, and
    # either half being invisible would make the trade unreadable.
    reranked = rerank_candidates(brief, candidates, corpus)

    retrieval_ms = round(embed_ms + search_ms, 1)

    ranking_start = perf_counter()
    # Ranking is optional per corpus. Having a rubric is the gate: a corpus
    # without a rubric of its own must not be scored with the creator one, which
    # would produce confident numbers about companies that mean nothing. The
    # ranking keys are OMITTED from the result rather than defaulted to 0.0 --
    # a missing key says "not measured", a 0.0 would say "measured, and it
    # scored nothing", and the summary averages cannot tell those apart.
    if ranks:
        ranked = rank_match(
            brief,
            reranked,
            top_n=top_n,
            client=client,
            corpus=corpus,
            relaxed_filters=relaxed_filters,
        )
        ranking_ms = round((perf_counter() - ranking_start) * 1000, 1)
        candidate_by_id = {candidate.id: candidate for candidate in candidates}
        ranked_candidates = [candidate_by_id[item["id"]] for item in ranked]
        ranked_correct = sum(1 for c in ranked_candidates if expected_tags & set(c.tags))
    else:
        ranked, ranked_candidates = [], []
        ranked_correct = 0

    retrieved_correct = sum(1 for c in candidates if expected_tags & set(c.tags))

    with vector_store.get_connection() as conn:
        pool = pool_for(conn, expected_tags, brief.platform, table=corpus.table)

    result = {
        "id": case["id"],
        "expected_tags": sorted(expected_tags),
        "corpus_kind": corpus.kind,
        "platform": brief.platform,
        # True when the brief is deliberately worded away from the case's own
        # tags, so literal word matching cannot pass it. Reported per case, not
        # averaged -- see the hard_cases block below.
        "hard": bool(case.get("hard")),
        "retrieved_count": len(candidates),
        "relaxed_filters": relaxed_filters,
        "retrieval_tag_precision_at_k": round(tag_precision(candidates, expected_tags), 3),
        "retrieval_tag_hit_at_k": retrieved_correct > 0,
        # Label-free relevance: how much of the brief's own wording appears in
        # the records that came back.
        "topic_overlap_at_k": round(
            mean(overlap_ratio(brief_terms, candidate) for candidate in candidates), 3
        ) if candidates else 0.0,
        # The retriever's own ordering, scored at the *same* cutoff the ranked
        # list is scored at. Present for every corpus, and the number a future
        # reranker has to beat.
        "retrieval_tag_precision_at_n": round(tag_precision(candidates[:top_n], expected_tags), 3),
        # The reranked shortlist at the same cutoff: the pair with the line above
        # is the only thing that isolates what the rerank did.
        "reranked_tag_precision_at_n": round(tag_precision(reranked[:top_n], expected_tags), 3),
        # How well the shortlist fits what the brief asked for -- the audience
        # for a creator, the ICP for a company.
        "retrieval_fit_precision_at_n": round(fit_precision(candidates[:top_n], expected_fit, corpus), 3),
        "reranked_fit_precision_at_n": round(fit_precision(reranked[:top_n], expected_fit, corpus), 3),
        # Both at once, which is what a campaign shortlist actually is: on-topic
        # AND the right audience. The topical number alone falls when a filter
        # is doing its job, and that fall is the point.
        "retrieval_campaign_precision_at_n": round(
            campaign_precision(candidates[:top_n], expected_tags, expected_fit, corpus), 3),
        "reranked_campaign_precision_at_n": round(
            campaign_precision(reranked[:top_n], expected_tags, expected_fit, corpus), 3),
        "pool_size": pool,
        "ceiling_precision_at_k": round(ceiling_precision(pool, top_k), 3),
        "recall_of_ceiling_at_k": round(recall_of_ceiling(retrieved_correct, pool, top_k), 3),
        "retrieval_latency_ms": retrieval_ms,
        "embed_latency_ms": embed_ms,
        "search_latency_ms": search_ms,
    }

    retrieval_dimensions, retrieval_coverage = fit_dimension_scores(
        candidates[:top_n], expected_fit, corpus
    )
    reranked_dimensions, reranked_coverage = fit_dimension_scores(
        reranked[:top_n], expected_fit, corpus
    )
    result["fit_dimensions_at_n"] = {
        "retrieval": retrieval_dimensions,
        "reranked": reranked_dimensions,
    }
    result["fit_data_coverage_at_n"] = {
        "retrieval": retrieval_coverage,
        "reranked": reranked_coverage,
    }

    if ranks:
        ranked_dimensions, ranked_coverage = fit_dimension_scores(
            ranked_candidates, expected_fit, corpus
        )
        result["fit_dimensions_at_n"]["ranked"] = ranked_dimensions
        result["fit_data_coverage_at_n"]["ranked"] = ranked_coverage
        result.update({
            "ranked_tag_precision_at_n": round(tag_precision(ranked_candidates, expected_tags), 3),
            "ranking_gain_at_n": round(
                tag_precision(ranked_candidates, expected_tags)
                - tag_precision(candidates[:top_n], expected_tags),
                3,
            ),
            "ceiling_precision_at_n": round(ceiling_precision(pool, top_n), 3),
            "recall_of_ceiling_at_n": round(recall_of_ceiling(ranked_correct, pool, top_n), 3),
            "ranking_fallback": any(item.get("source") == "fallback" for item in ranked),
            # The reason matters: "quota exhausted" and "model returned garbage"
            # look identical in a mean, and only the first is worth retrying. It
            # was previously dropped here and had to be recovered by hand.
            "fallback_reasons": sorted({
                str(item["fallback_reason"]) for item in ranked
                if item.get("fallback_reason")
            }),
            "fallback_count": sum(1 for item in ranked if item.get("source") == "fallback"),
            "filled_count": sum(1 for item in ranked if item.get("source") == "filled"),
            "strong_fit_count": sum(1 for item in ranked if item.get("fit") == "strong"),
            "ranking_latency_ms": ranking_ms,
        })
    return result


def main() -> None:
    args = parse_args()
    corpus = get_corpus(args.kind)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not cases:
        raise RuntimeError(f"Evaluation dataset {args.cases.name} is empty")

    client = get_client()
    case_results: list[dict | None] = [None] * len(cases)

    query_cache = None
    if not args.no_query_cache:
        query_cache = EmbeddingCache(args.query_cache or default_query_cache_path())

    PostgresRunRepository().ensure_schema()
    with vector_store.get_connection() as conn:
        # init_schema is the CREATORS' runtime DDL. Migration 009 is the sole
        # source of truth for prospects, so calling it here would build the wrong
        # table and leave the one under evaluation missing.
        if corpus.kind == "creator":
            vector_store.init_schema(conn)
        dataset_size = vector_store.count_records(conn, corpus.table)
        if not dataset_size:
            raise RuntimeError(
                f"No indexed {corpus.kind} records. Run "
                f"`python main.py --kind {corpus.kind} --reindex --index-only` first."
            )
        _warmup(conn, corpus)

    started = perf_counter()

    # The one decision about ranking, made before any case runs, so the
    # per-case gate and the report gates cannot disagree. A corpus without a
    # rubric of its own must not be scored with another corpus's rules, and
    # --no-ranking measures the retrieval for free. It has to sit above the
    # sequential branch too: both branches run cases, and only the concurrent
    # one had it.
    ranks = corpus.rubric is not None and not args.no_ranking

    if args.sequential:
        spacing = 60.0 / args.rate_limit_per_min
        for idx, case in enumerate(cases):
            if idx > 0:
                time.sleep(spacing)
            case_results[idx] = _run_case(
                    client, case, args.top_k, args.top_n, query_cache, corpus, ranks
                )
    else:
        windows = batch_windows(len(cases), args.rate_limit_per_min)
        for w, window in enumerate(windows):
            window_start = perf_counter()
            if len(windows) > 1:
                print(f"Window {w + 1}/{len(windows)}: cases "
                      f"{window[0] + 1}-{window[-1] + 1} firing concurrently...")
            with ThreadPoolExecutor(max_workers=len(window)) as pool:
  
                futures = {}
                for idx in window:
                    futures[idx] = pool.submit(
                        _run_case, client, cases[idx], args.top_k, args.top_n,
                        query_cache, corpus, ranks,
                    )
                for idx, future in futures.items():
                    case_results[idx] = future.result()

            if len(windows) > 1:
                elapsed = perf_counter() - window_start
                remaining = 60.0 - elapsed
                if remaining > 0 and w < len(windows) - 1:
                    print(f"  window done in {elapsed:.1f}s; waiting {remaining:.1f}s "
                          f"to respect the per-minute quota")
                    time.sleep(remaining)

    report_results = [r for r in case_results if r is not None]
    total_wall = perf_counter() - started

    # Split so a corpus with no rubric produces a report that omits the ranking
    # metrics rather than one that KeyErrors on them or, worse, reports zeros
    # that read as "scored, and scored nothing".
    summary = {
        "ranking_skipped": None if ranks else (
            "--no-ranking" if args.no_ranking else "the corpus has no rubric"
        ),
        "case_count": len(report_results),
        "mean_retrieval_tag_precision_at_k": round(mean(item["retrieval_tag_precision_at_k"] for item in report_results), 3),
        "retrieval_tag_hit_rate_at_k": round(mean(item["retrieval_tag_hit_at_k"] for item in report_results), 3),
        "mean_retrieval_tag_precision_at_n": round(mean(item["retrieval_tag_precision_at_n"] for item in report_results), 3),
        # The pair that isolates the rerank, and the pair that says whether the
        # shortlist is a campaign shortlist rather than two separate lists.
        "mean_reranked_tag_precision_at_n": round(mean(item["reranked_tag_precision_at_n"] for item in report_results), 3),
        "mean_retrieval_fit_precision_at_n": round(mean(item["retrieval_fit_precision_at_n"] for item in report_results), 3),
        "mean_reranked_fit_precision_at_n": round(mean(item["reranked_fit_precision_at_n"] for item in report_results), 3),
        "mean_retrieval_campaign_precision_at_n": round(mean(item["retrieval_campaign_precision_at_n"] for item in report_results), 3),
        "mean_reranked_campaign_precision_at_n": round(mean(item["reranked_campaign_precision_at_n"] for item in report_results), 3),
        "mean_retrieval_latency_ms": round(mean(item["retrieval_latency_ms"] for item in report_results), 1),
        "mean_embed_latency_ms": round(mean(item["embed_latency_ms"] for item in report_results), 1),
        "mean_search_latency_ms": round(mean(item["search_latency_ms"] for item in report_results), 1),
        "mean_topic_overlap_at_k": round(mean(item["topic_overlap_at_k"] for item in report_results), 3),
        "mean_recall_of_ceiling_at_k": round(mean(item["recall_of_ceiling_at_k"] for item in report_results), 3),
        "mean_ceiling_precision_at_k": round(mean(item["ceiling_precision_at_k"] for item in report_results), 3),
        "wall_clock_seconds": round(total_wall, 1),
    }
    fit_dimensions, fit_coverage = summarize_fit_metrics(report_results, ranks)
    summary["fit_dimension_precision_at_n"] = fit_dimensions
    summary["fit_data_coverage_at_n"] = fit_coverage

    if ranks:
        summary.update({
            "mean_ranked_tag_precision_at_n": round(mean(item["ranked_tag_precision_at_n"] for item in report_results), 3),
            # The reranker's contribution, and the only pair here that isolates it:
            # identical candidates, identical cutoff, different order.
            "mean_ranking_gain_at_n": round(mean(item["ranking_gain_at_n"] for item in report_results), 3),
            "ranking_fallback_rate": round(mean(item["ranking_fallback"] for item in report_results), 3),
            # A ranked precision computed mostly from retrieval order still looks
            # like a result. Measured the first time on prospects: 0.886 against
            # a 0.857 baseline looked like a reranker gain until the fallback rate
            # beside it turned out to be 0.929 -- one case had actually run.
            "ranking_measured": mean(item["ranking_fallback"] for item in report_results) == 0,
            "total_fallback_slots": sum(item["fallback_count"] for item in report_results),
            "total_filled_slots": sum(item["filled_count"] for item in report_results),
            "mean_strong_fits_per_case": round(mean(item["strong_fit_count"] for item in report_results), 2),
            "mean_ranking_latency_ms": round(mean(item["ranking_latency_ms"] for item in report_results), 1),
            "mean_recall_of_ceiling_at_n": round(mean(item["recall_of_ceiling_at_n"] for item in report_results), 3),
            "mean_ceiling_precision_at_n": round(mean(item["ceiling_precision_at_n"] for item in report_results), 3),
            "cases_at_ceiling_at_n": sum(1 for item in report_results if item["recall_of_ceiling_at_n"] >= 1.0),
        })
    else:
        # Say plainly what this suite did not measure. The corpus is balanced on
        # industry x size tier, and relevance here is tag overlap alone -- so a
        # reader must not mistake this report for validation of the tier balance.
        summary["relevance_is"] = (
            "tag overlap only. The prospects corpus is balanced on industry x size "
            "tier, but this suite cannot see the size dimension: a case whose brief "
            "names a headcount band would be scored on its industry tags alone."
        )
    hard = [item for item in report_results if item["hard"]]
    if hard:
        # Reported per case, not as a mean. 
        summary["hard_cases"] = {
            "case_count": len(hard),
            "note": (
                f"{len(hard)} briefs, too few for a mean; read the individual "
                "cases rather than averaging them"
            ),
            "cases": [
                {
                    "id": item["id"],
                    "retrieval_tag_precision_at_k": item["retrieval_tag_precision_at_k"],
                    "topic_overlap_at_k": item["topic_overlap_at_k"],
                }
                for item in hard
            ],
        }

    headline = {
        "corpus_kind": corpus.kind,
        "dataset_size": dataset_size,
        "case_count": len(report_results),
        "mean_retrieval_tag_precision_at_k": summary["mean_retrieval_tag_precision_at_k"],
        "mean_retrieval_tag_precision_at_n": summary["mean_retrieval_tag_precision_at_n"],
        "mean_reranked_tag_precision_at_n": summary["mean_reranked_tag_precision_at_n"],
        "mean_retrieval_fit_precision_at_n": summary["mean_retrieval_fit_precision_at_n"],
        "mean_reranked_fit_precision_at_n": summary["mean_reranked_fit_precision_at_n"],
        "mean_retrieval_campaign_precision_at_n": summary["mean_retrieval_campaign_precision_at_n"],
        "mean_reranked_campaign_precision_at_n": summary["mean_reranked_campaign_precision_at_n"],
        "mean_recall_of_ceiling_at_k": summary["mean_recall_of_ceiling_at_k"],
        "mean_topic_overlap_at_k": summary["mean_topic_overlap_at_k"],
    }
    if ranks:
        headline.update({
            "mean_ranked_tag_precision_at_n": summary["mean_ranked_tag_precision_at_n"],
            # Repeated in the headline on purpose: headline is the trimmed view
            # people quote, and a ranked number with a fallback beside it is easy
            # to read as a gain and impossible to unsee later.
            "ranking_measured": summary["ranking_measured"],
            "mean_ranking_gain_at_n": summary["mean_ranking_gain_at_n"],
            "mean_recall_of_ceiling_at_n": summary["mean_recall_of_ceiling_at_n"],
            "mean_strong_fits_per_case": summary["mean_strong_fits_per_case"],
            "ranking_fallback_rate": summary["ranking_fallback_rate"],
        })
    # Why the ranking metrics are absent, when they are. The headline is the
    # trimmed view people quote, and a headline with no ranking numbers should
    # say they were not measured rather than leave it implied.
    headline["ranking_skipped"] = None if ranks else (
        "--no-ranking" if args.no_ranking else "the corpus has no rubric"
    )

    report = {
        "corpus_kind": corpus.kind,
        # Why there are no ranking metrics, when there are none. Without this a
        # skipped run is indistinguishable from a corpus that has no rubric.
        "ranking_skipped": None if ranks else (
            "--no-ranking" if args.no_ranking else "the corpus has no rubric"
        ),
        "embedding_model": config.EMBED_MODEL,
        "embed_dimensions": config.EMBED_DIMENSIONS,
        "dataset_size": dataset_size,
        "top_k": args.top_k,
        "top_n": args.top_n,
        "query_cache": {
            "enabled": query_cache is not None,
            "path": str(query_cache.path) if query_cache is not None else None,
            "hits": query_cache.hits if query_cache is not None else 0,
            "misses": query_cache.misses if query_cache is not None else 0,
        },
        "headline": headline,
        "cases": report_results,
        "summary": summary,
    }

    # Named for BOTH corpus and size. A creator run at 2000 and a prospect run at
    # 500 are different measurements, and a filename carrying only the row count
    # makes them collide the day both are 2000.
    output = args.output or REPORTS_DIR / f"evaluation-{corpus.kind}-{dataset_size}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["headline"], indent=2))
    print(f"\nFull per-case report written to {output}")


if __name__ == "__main__":
    main()
