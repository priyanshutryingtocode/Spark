"""Paired evaluation for reviewed product context.

Run from backend with:
    python evaluate_context.py --kind creator
    python evaluate_context.py --kind prospect --use-extractor
    python evaluate_context.py --kind creator --no-ranking
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean
from time import perf_counter

from api.repositories.postgres_run_repository import PostgresRunRepository
from api.services.context_extractor import extract_product_context
from evaluate import DEFAULT_CASES, REPORTS_DIR, _run_case, _warmup, default_query_cache_path
from src import vector_store
from src.corpora import get_corpus
from src.embeddings import EmbeddingCache
from src.gemini_client import get_client

BACKEND_ROOT = Path(__file__).resolve().parent
CONTEXT_CASES = {
    "creator": BACKEND_ROOT / "data" / "creator_context_evaluation.json",
    "prospect": BACKEND_ROOT / "data" / "company_context_evaluation.json",
}
CONTEXT_GROUPS = {"underspecified", "specific_control", "irrelevant_control", "injection_control"}
METRICS = (
    "retrieval_tag_precision_at_k",
    "reranked_tag_precision_at_n",
    "ranked_tag_precision_at_n",
    "retrieval_campaign_precision_at_n",
    "reranked_campaign_precision_at_n",
    "strong_fit_count",
    "retrieval_latency_ms",
    "ranking_latency_ms",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare matching with and without reviewed product context.")
    parser.add_argument("--kind", choices=("creator", "prospect"), default="creator")
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--rate-limit-per-min", type=int, default=10)
    parser.add_argument("--no-ranking", action="store_true")
    parser.add_argument("--use-extractor", action="store_true",
                        help="Run fixture source text through Gemini extraction; otherwise use reviewed summaries.")
    parser.add_argument("--no-query-cache", action="store_true")
    args = parser.parse_args()
    args.cases = args.cases or CONTEXT_CASES[args.kind]
    if args.top_k <= 0 or args.top_n <= 0 or args.top_n > args.top_k:
        parser.error("top-k and top-n must be positive, and top-n cannot exceed top-k")
    if args.rate_limit_per_min <= 0:
        parser.error("--rate-limit-per-min must be positive")
    calls_per_pair = (0 if args.no_ranking else 3) + int(args.use_extractor)
    if calls_per_pair and args.rate_limit_per_min < calls_per_pair:
        parser.error(f"--rate-limit-per-min must be at least {calls_per_pair} for this mode")
    return args


def load_cases(path: Path, kind: str) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    reference = json.loads(DEFAULT_CASES[kind].read_text(encoding="utf-8"))
    refs = {case["id"]: case for case in reference}
    if len(cases) != 10 or len({case.get("id") for case in cases}) != 10:
        raise ValueError("Context evaluation requires exactly 10 unique cases per corpus.")
    if {case["id"] for case in cases} != set(refs):
        raise ValueError("Context cases must map one-to-one to the current golden relevance labels.")
    for case in cases:
        if case.get("group") not in CONTEXT_GROUPS:
            raise ValueError(f"{case['id']} has an unknown context group.")
        if not case.get("goal") or not case.get("source_text"):
            raise ValueError(f"{case['id']} needs a goal and fixture source_text.")
        if case.get("group") != "irrelevant_control":
            source = " ".join(case["source_text"].split())
            for quote in case.get("product_context", {}).get("source_quotes", []):
                if " ".join(quote.split()) not in source:
                    raise ValueError(f"{case['id']} has a source quote absent from its fixture text.")
        case["reference"] = refs[case["id"]]
    counts = {group: sum(case["group"] == group for case in cases) for group in CONTEXT_GROUPS}
    if counts != {"underspecified": 7, "specific_control": 1, "irrelevant_control": 1, "injection_control": 1}:
        raise ValueError(f"Expected 7 context cases and one of each control group; got {counts}.")
    return cases


def run_pair(client, case, top_k, top_n, query_cache, corpus, ranks, use_extractor):
    reference = case["reference"]
    baseline_case = {**reference, "goal": case["goal"], "product_context": None}
    context = case.get("product_context")
    extraction = None
    if use_extractor:
        extraction = extract_product_context(case["source_text"], corpus.kind, client)
        context = extraction.context.model_dump() if extraction.relevant else None
    assisted_case = {**reference, "goal": case["goal"], "product_context": context}
    baseline = _run_case(client, baseline_case, top_k, top_n, query_cache, corpus, ranks, query_mode="intent")
    combined = _run_case(client, assisted_case, top_k, top_n, query_cache, corpus, ranks, query_mode="combined")
    dual = _run_case(client, assisted_case, top_k, top_n, query_cache, corpus, ranks, query_mode="dual")

    def deltas(arm):
        return {
            key: round(arm[key] - baseline[key], 3 if "precision" in key else 1)
            for key in METRICS if key in baseline and key in arm
        }

    result = {
        "id": case["id"],
        "group": case["group"],
        "baseline": baseline,
        "legacy_combined_query": combined,
        "dual_channel": dual,
        "with_context": dual,
        "delta": deltas(dual),
        "legacy_combined_delta": deltas(combined),
        "filters_unchanged": (
            baseline["relaxed_filters"] == combined["relaxed_filters"]
            == dual["relaxed_filters"]
        ),
    }
    if extraction is not None:
        result["extraction"] = {
            "expected_relevant": case["group"] not in {"irrelevant_control", "injection_control"},
            "relevant": extraction.relevant,
            "message": extraction.message,
            "context": extraction.context.model_dump(mode="json"),
            "suggested_filters": extraction.suggested_filters,
            "verified_source_quote_count": len(extraction.context.source_quotes),
        }
    return result


def summarize(pairs: list[dict], metric: str, arm: str = "dual_channel") -> dict:
    delta_key = "delta" if arm == "dual_channel" else "legacy_combined_delta"
    chosen = [pair for pair in pairs if metric in pair[delta_key]]
    deltas = [pair[delta_key][metric] for pair in chosen]
    return {
        "cases": len(chosen),
        "baseline_mean": round(mean(pair["baseline"][metric] for pair in chosen), 3),
        "context_mean": round(mean(pair[arm][metric] for pair in chosen), 3),
        "mean_delta": round(mean(deltas), 3),
        "improved_cases": sum(delta > 0 for delta in deltas),
        "unchanged_cases": sum(delta == 0 for delta in deltas),
        "regressed_cases": sum(delta < 0 for delta in deltas),
    } if chosen else {"cases": 0, "not_measured": True}


def main() -> None:
    args = parse_args()
    cases = load_cases(args.cases, args.kind)
    corpus = get_corpus(args.kind, "synthetic")
    ranks = corpus.rubric is not None and not args.no_ranking
    query_cache = None if args.no_query_cache else EmbeddingCache(default_query_cache_path())
    client = get_client()

    PostgresRunRepository().ensure_schema()
    with vector_store.get_connection() as conn:
        if corpus.kind == "creator":
            vector_store.init_schema(conn)
        dataset_size = vector_store.count_records(conn, corpus.table)
        if not dataset_size:
            raise RuntimeError(f"No indexed synthetic {corpus.kind} records to evaluate.")
        _warmup(conn, corpus)

    calls_per_pair = (3 if ranks else 0) + int(args.use_extractor)
    batch_size = len(cases) if calls_per_pair == 0 else max(1, args.rate_limit_per_min // calls_per_pair)
    started = perf_counter()
    pairs = []
    for start in range(0, len(cases), batch_size):
        batch = cases[start:start + batch_size]
        batch_start = perf_counter()
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(
                run_pair, client, case, args.top_k, args.top_n,
                query_cache, corpus, ranks, args.use_extractor,
            ) for case in batch]
            pairs.extend(future.result() for future in futures)
        remaining = 60 - (perf_counter() - batch_start)
        if start + batch_size < len(cases) and calls_per_pair and remaining > 0:
            time.sleep(remaining)

    groups = {
        group: [pair for pair in pairs if pair["group"] == group]
        for group in sorted({pair["group"] for pair in pairs})
    }
    primary_metric = "ranked_tag_precision_at_n" if ranks else "reranked_tag_precision_at_n"
    group_summary = {
        group: {
            "primary_quality": summarize(rows, primary_metric),
            "campaign_quality": summarize(rows, "reranked_campaign_precision_at_n"),
            "strong_fits": summarize(rows, "strong_fit_count"),
            "filters_unchanged_count": sum(pair["filters_unchanged"] for pair in rows),
        }
        for group, rows in groups.items()
    }
    relevant = groups.get("underspecified", [])
    controls = [pair for group, rows in groups.items() if group != "underspecified" for pair in rows]
    quality = summarize(relevant, primary_metric)
    control_quality = summarize(controls, primary_metric)
    fallbacks = [pair for pair in pairs if pair["dual_channel"].get("ranking_fallback")]
    legacy_fallbacks = [pair for pair in pairs if pair["legacy_combined_query"].get("ranking_fallback")]
    intent_fallbacks = [pair for pair in pairs if pair["baseline"].get("ranking_fallback")]
    extraction_rows = [pair["extraction"] for pair in pairs if "extraction" in pair]
    extraction_accuracy = (
        mean(row["expected_relevant"] == row["relevant"] for row in extraction_rows)
        if extraction_rows else None
    )
    report = {
        "evaluation": "paired_product_context",
        "kind": corpus.kind,
        "dataset": "synthetic",
        "dataset_size": dataset_size,
        "case_count": len(pairs),
        "context_mode": "Gemini extraction" if args.use_extractor else "reviewed fixture summaries",
        "ranking_measured": (not fallbacks) if ranks else None,
        "primary_metric": primary_metric,
        "summary": {
            "underspecified": quality,
            "controls": control_quality,
            "groups": group_summary,
            "legacy_combined_query": {
                "underspecified": summarize(relevant, primary_metric, "legacy_combined_query"),
                "controls": summarize(controls, primary_metric, "legacy_combined_query"),
            },
            "ranking_fallback_cases": [pair["id"] for pair in fallbacks],
            "legacy_combined_ranking_fallback_cases": [pair["id"] for pair in legacy_fallbacks],
            "ranking_fallback_cases_by_arm": {
                "intent_only": [pair["id"] for pair in intent_fallbacks],
                "combined_query": [pair["id"] for pair in legacy_fallbacks],
                "dual_channel": [pair["id"] for pair in fallbacks],
            },
            "extractor_relevance_accuracy": round(extraction_accuracy, 3) if extraction_accuracy is not None else None,
            "extractor_cases": len(extraction_rows),
            "wall_clock_seconds": round(perf_counter() - started, 1),
            "pilot_gate": {
                "promising": (
                    quality.get("mean_delta", 0) >= 0.10
                    and quality.get("improved_cases", 0) >= 5
                    and control_quality.get("mean_delta", 0) >= -0.05
                    and (not ranks or not fallbacks)
                ),
                "rule": "At least +0.10 mean primary precision across underspecified cases, improvement in 5 or more, controls no worse than -0.05 mean, and no ranking fallbacks when ranking is enabled.",
                "warning": "This 10-case-per-corpus pilot is directional, not a statistically powered result.",
            },
        },
        "settings": {
            "top_k": args.top_k,
            "top_n": args.top_n,
            "ranking": ranks,
            "rate_limit_per_min": args.rate_limit_per_min,
            "query_cache_enabled": query_cache is not None,
            "query_cache_path": str(query_cache.path) if query_cache is not None else None,
            "query_cache_hits": query_cache.hits if query_cache is not None else 0,
            "query_cache_misses": query_cache.misses if query_cache is not None else 0,
        },
        "cases": pairs,
    }
    output = args.output or REPORTS_DIR / f"context-evaluation-{corpus.kind}-{dataset_size}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"\nPaired context evaluation written to {output}")


if __name__ == "__main__":
    main()
