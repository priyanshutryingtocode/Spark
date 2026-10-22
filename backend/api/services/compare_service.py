from __future__ import annotations

from api.serialization import candidate_key, summarize_record
from src.corpora import CREATORS, Corpus


def summarize_run(run: dict, corpus: Corpus = CREATORS) -> dict:
    return summarize_record(run, corpus)


def compare_runs(run_a: dict, run_b: dict, corpus: Corpus = CREATORS) -> dict:
    """Compare two runs of the same corpus. The caller owns the cross-corpus
    refusal; this only compares.
    """
    candidates_a = {candidate_key(i): i for i in run_a["result"]["candidates"]}
    candidates_b = {candidate_key(i): i for i in run_b["result"]["candidates"]}
    ranked_a = {e["id"] for e in run_a["result"]["ranked"]}
    ranked_b = {e["id"] for e in run_b["result"]["ranked"]}

    shared = [
        {
            "id": candidate["id"],
            "creator_key": key,
            # `label`, not `handle`: a company has none, and reading
            # candidate["handle"] off one is what this field exists to avoid.
            "label": _label(candidate, corpus),
        }
        for key, candidate in sorted(candidates_a.items())
        if key in candidates_b
        and candidate["id"] in ranked_a
        and candidate["id"] in ranked_b
    ]

    return {
        "run_ids": [run_a["id"], run_b["id"]],
        "summary_a": summarize_run(run_a, corpus),
        "summary_b": summarize_run(run_b, corpus),
        "shared": shared,
    }


def _label(candidate: dict, corpus: Corpus) -> str:
    if corpus.kind == "prospect":
        return str(candidate.get("name") or candidate.get("creator_key") or "")
    return str(candidate.get("handle") or candidate.get("name") or candidate.get("creator_key") or "")
