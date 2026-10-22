"""Measure the structured rerank against the creator suite, retrieval only.

No ranking calls, so this is free to run as often as the change is made -- which
is the point. It reports the topical metric, the audience metric and the
combined one, before and after the rerank, because a rerank that raised the
audience number and quietly wrecked the topical one would be a trade dressed up
as a gain.

    ../venv/Scripts/python.exe scripts/measure_rerank.py [--kind creator]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.corpora import KINDS  # noqa: E402
from src.embeddings import get_cached_query_vector  # noqa: E402
from src.match_service import retrieve_candidates, retrieve_for_run  # noqa: E402
from src.models import Brief  # noqa: E402
from src.retrieval import rerank_candidates  # noqa: E402

from evaluate import (  # noqa: E402
    audience_precision, campaign_precision, icp_precision, tag_precision,
)

CASES = {
    "creator": pathlib.Path(__file__).resolve().parents[1] / "data" / "evaluation_cases.json",
    "prospect": pathlib.Path(__file__).resolve().parents[1] / "data" / "prospect_cases.json",
}


def build_brief(case: dict) -> Brief:
    """The brief a user of that corpus would fill in for the case."""
    audience = case.get("expected_audience") or {}
    icp = case.get("expected_icp") or {}
    return Brief(
        goal=case["goal"],
        platform=case.get("platform", "Any"),
        audience=case.get("audience", ""),
        vibe=case.get("vibe", ""),
        audience_age=list(audience.get("age", [])),
        audience_gender=audience.get("gender", ""),
        audience_countries=list(audience.get("countries", [])),
        target_industries=list(icp.get("industries", [])),
        target_size=tuple(icp["size"]) if icp.get("size") else None,
        target_countries=list(icp.get("countries", [])),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(KINDS), default="creator")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    corpus = KINDS[args.kind]

    raw = json.loads(CASES[args.kind].read_text(encoding="utf-8"))
    cases = raw["cases"] if isinstance(raw, dict) else raw
    if args.kind == "creator":
        cases = [c for c in cases if c.get("expected_audience")]
    else:
        cases = [c for c in cases if c.get("expected_icp") is not None]

    # Three points, not two. "Raw" ignores the structured fields entirely, so it
    # is what the app did before this work. "Filtered" applies the brief's
    # discrete requirements. "Reranked" adds the preferences on top. Only
    # showing the last two would hide which mechanism did the work.
    # Four points, because the two mechanisms answer different briefs.
    #   raw        neither
    #   filtered   the brief's discrete requirements
    #   reranked   the brief's preferences, over an unfiltered set
    #   both       preferences on top of the requirements
    # Showing only "raw" and "both" would hide that the rerank has nothing to add
    # once a filter has already excluded the off-audience candidates.
    variants = ("raw", "filtered", "reranked", "both")
    # A company campaign is measured against the ICP; a creator campaign against
    # the audience. Both are "the brief's own requirements", so the same three
    # numbers come out of each.
    fit = (lambda items, icp: icp_precision(items, icp, corpus)) if args.kind != "creator" else audience_precision
    totals = {f"{v}_{k}": 0.0 for v in variants for k in ("topic", "aud", "camp")}
    relaxed_cases = 0
    for case in cases:
        brief = build_brief(case)
        expected_tags = set(case["expected_tags"])
        audience = case.get("expected_audience") or case.get("expected_icp") or {}
        query_vec = get_cached_query_vector(brief.query_text())

        unfiltered = retrieve_candidates(
            brief, top_k=args.top_k, query_vec=query_vec, corpus=corpus, filters={}
        )
        # The same path the app takes, floor included: a filter that matches
        # nothing is relaxed rather than returning an empty page, and what the
        # user sees is the relaxed result, not the strict one.
        filtered, relaxed = retrieve_for_run(
            brief, top_k=args.top_k, query_vec=query_vec, corpus=corpus
        )
        if relaxed:
            relaxed_cases += 1
        for name, items in (
            ("raw", unfiltered),
            ("filtered", filtered),
            ("reranked", rerank_candidates(brief, unfiltered, corpus)),
            ("both", rerank_candidates(brief, filtered, corpus)),
        ):
            head = items[:args.top_n]
            totals[f"{name}_topic"] += tag_precision(head, expected_tags)
            totals[f"{name}_aud"] += fit(head, audience)
            totals[f"{name}_camp"] += campaign_precision(head, expected_tags, audience, corpus)

    n = len(cases) or 1
    print(f"  {args.kind}: {len(cases)} cases, top_n={args.top_n}, 0 ranking calls")
    print(f"    filters had to be relaxed in {relaxed_cases} of {len(cases)} cases")
    print(f"    {'':10} {'topical':>9} {'audience':>9} {'combined':>9}")
    for name in variants:
        print(f"    {name:10} {totals[f'{name}_topic']/n:9.3f} {totals[f'{name}_aud']/n:9.3f} {totals[f'{name}_camp']/n:9.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
