from __future__ import annotations

from uuid import UUID

from src.formatting import match_evidence
from src.corpora import CREATORS, Corpus, Influencer, Prospect, dataset_for_record, get_corpus, kind_for_record
from src.models import Brief
from src.ranking import QUOTA_REASON_TAG
from src.summaries import CREATOR_SUMMARY, SummarySpec, summary_spec

from .schemas.models import (
    BriefPayload,
    CreatorSnapshot,
    ProspectSnapshot,
    SummaryCell,
    MatchParams,
    RankedEntry,
    RunDetail,
    RunListItem,
    RunSummary,
    SavedMatchResponse,
    Warning,
)


def brief_to_payload(brief: Brief) -> dict:
    return BriefPayload(
        goal=brief.goal,
        platform=brief.platform,
        audience=brief.audience,
        vibe=brief.vibe,
        audience_age=list(brief.audience_age),
        audience_gender=brief.audience_gender,
        audience_countries=list(brief.audience_countries),
        languages=list(brief.languages),
        min_reach_ratio=brief.min_reach_ratio,
        target_industries=list(brief.target_industries),
        target_size=brief.target_size,
        target_countries=list(brief.target_countries),
        budget_band=brief.budget_band,
        buyer_roles=list(brief.buyer_roles),
    ).model_dump(mode="json")


def creator_to_snapshot(influencer: Influencer) -> dict:
    return CreatorSnapshot(
        id=influencer.id,
        creator_key=creator_key(influencer),
        handle=influencer.handle,
        name=influencer.name,
        platform=influencer.platform,
        city=influencer.city,
        country=influencer.country,
        language=influencer.language,
        followers=influencer.followers,
        engagement_pct=influencer.engagement,
        average_views=influencer.average_views,
        average_likes=influencer.average_likes,
        average_comments=influencer.average_comments,
        verified=influencer.verified,
        posts_per_week=influencer.posts_per_week,
        account_age_years=influencer.account_age_years,
        match_reasons=list(getattr(influencer, "match_reasons", []) or []),
        content_style=influencer.content_style,
        audience_age=influencer.audience_age,
        audience_gender=influencer.audience_gender,
        audience_country=influencer.audience_country,
        brand_collaborations=influencer.brand_collaborations,
        tags=influencer.tags,
        bio=influencer.bio,
        similarity=influencer.similarity,
        reach_ratio=influencer.reach_ratio,
        sponsored_ratio=influencer.sponsored_ratio,
        growth_trend=influencer.growth_trend,
        audience_top_countries=influencer.audience_top_countries,
    ).model_dump(mode="json")


def prospect_to_snapshot(prospect) -> dict:
    """The stored shape of one company.

    `creator_key` is the field name for a corpus-agnostic row identity. It is
    wrong for a company and renaming it touches ~10 call sites including CSV,
    so the debt is recorded rather than paid here; Phase 6 owns the rename.
    """
    return ProspectSnapshot(
        id=prospect.id,
        creator_key=prospect_key(prospect),
        name=prospect.name,
        industry=prospect.industry,
        headcount=prospect.headcount,
        city=prospect.city,
        country=prospect.country,
        description=prospect.description,
        website=prospect.website,
        founded_year=prospect.founded_year,
        funding_stage=prospect.funding_stage,
        tags=prospect.tags,
        similarity=prospect.similarity,
        match_reasons=list(getattr(prospect, "match_reasons", []) or []),
        seniority_mix=prospect.seniority_mix,
        department_mix=prospect.department_mix,
        tech_stack=prospect.tech_stack,
        buying_signals=prospect.buying_signals,
        growth_trend=prospect.growth_trend,
        growth_rate=prospect.growth_rate,
        hiring_intensity=prospect.hiring_intensity,
        top_markets=prospect.top_markets,
    ).model_dump(mode="json")


def ranked_to_snapshot(
    entry: dict,
    influencer: Influencer,
    brief: Brief,
    rank: int,
) -> dict:
    return RankedEntry(
        id=influencer.id,
        creator_key=creator_key(influencer),
        rank=rank,
        fit=entry.get("fit", "unknown"),
        source=entry.get("source", "filled"),
        rationale=entry.get("rationale", ""),
        evidence=match_evidence(brief, influencer),
        grounding=entry.get("grounding", []),
        fallback_reason=entry.get("fallback_reason", ""),
    ).model_dump(mode="json", exclude_none=True)


def prospect_ranked_to_snapshot(
    entry: dict,
    prospect: Prospect,
    rank: int,
) -> dict:
    """A company's ranked row.

    No `match_evidence` equivalent: evidence is per-field verification against
    brief signals, and `MatchSignals` is the creator's signal set. A company is
    matched on text similarity, so there is no field-level evidence to cite and
    inventing one would claim a verification that never happened.
    """
    return RankedEntry(
        id=prospect.id,
        creator_key=prospect_key(prospect),
        rank=rank,
        fit=entry.get("fit", "unknown"),
        source=entry.get("source", "filled"),
        rationale=entry.get("rationale", ""),
        grounding=entry.get("grounding", []),
        fallback_reason=entry.get("fallback_reason", ""),
    ).model_dump(mode="json", exclude_none=True)


def build_warnings(
    ranked: list[dict],
    relaxed: list[str] | None = None,
    retrieved: int = 0,
) -> list[Warning]:
    warnings: list[Warning] = []
    if retrieved and not ranked:
        # The run found records and then produced no shortlist from them. Every
        # other path out of the ranking is a *fallback* and says so; this one is
        # silent, and a silent empty shortlist reads as "nothing matched" -- a
        # claim about the data when the truth is about the run.
        warnings.append(
            Warning(
                code="NO_RANKED_RESULTS",
                severity="error",
                message=(
                    f"{retrieved} records were retrieved but none could be "
                    "ranked, so there is no shortlist to show."
                ),
                details={"retrieved": retrieved},
            )
        )
    if relaxed:
        # The shortlist is not the one that was asked for, and the reader has to
        # be told: "no companies match" and "we dropped your filter" call for
        # different actions, and only one of them is about the data.
        warnings.append(
            Warning(
                code="FILTER_RELAXED",
                severity="warning",
                message=(
                    "The filters were relaxed because nothing matched all of them "
                    f"({', '.join(relaxed)}). The results are wider than the brief asked for."
                ),
                details={"relaxed": list(relaxed)},
            )
        )
    fallback = [item for item in ranked if item.get("source") == "fallback"]
    if fallback:
        reason = next((item.get("fallback_reason", "") for item in fallback if item.get("fallback_reason")), "")
        is_quota = reason.startswith(QUOTA_REASON_TAG)
        if is_quota:
            # "Unavailable" would read as an outage, and the sensible response
            # to an outage is to retry immediately -- which cannot help here.
            # Say what actually happened and when it changes.
            message = (
                "Today's free ranking quota is spent, so these are in retrieval order "
                "rather than ranked. It resets at midnight Pacific."
            )
        else:
            message = "Gemini ranking was unavailable; showing retrieval order."
        warnings.append(
            Warning(
                code="RANKING_FALLBACK",
                severity="error",
                message=message,
                details={"reason": reason} if reason else {},
            )
        )
    elif any(item.get("source") == "filled" for item in ranked):
        filled = sum(item.get("source") == "filled" for item in ranked)
        warnings.append(
            Warning(
                code="RANKING_PARTIALLY_FILLED",
                severity="info",
                message=f"The model ranked {len(ranked) - filled} of {len(ranked)} requested slots.",
                details={"filled": filled, "requested": len(ranked)},
            )
        )
    return [warning.model_dump(mode="json") for warning in warnings]


def build_summary(
    candidates: list[dict],
    ranked: list[dict],
    spec: SummarySpec = CREATOR_SUMMARY,
) -> dict:
    """The one place run statistics are computed.

    Takes the persisted snapshot shape rather than record objects, because that is
    what a stored run actually holds -- `compare_service` has to recompute from a
    DB record and was reimplementing this against dicts.

    Every count is taken over the joined set. The previous version counted
    `n_strong`/`n_weak` over the whole ranked list while `n_results` counted
    only joined candidates, so a run with a dangling ranked entry could report
    "4/5 strong fits".
    """
    values = spec.compute(candidates, ranked)
    cells = spec.render_cells(values)
    # exclude_none on the OUTER dump, not per cell: RunSummary holds
    # list[SummaryCell], so the outer serialisation re-renders each nested cell
    # with its own defaults and the inner exclude_none would be undone. The
    # effect wanted is that an unset optional is absent -- every cell would
    # otherwise carry "primary": null and "explanation": null in the run's
    # summary JSONB, forever.
    return RunSummary(
        kind=spec.kind,
        cells=[SummaryCell(**cell) for cell in cells],
        **{key: values.get(key) for key in spec.keys},
    ).model_dump(mode="json", exclude_none=True)


def build_run_record(result: dict, run_id: UUID, corpus: Corpus = CREATORS) -> dict:
    """Serialise a run for storage.

    Stamps `kind` itself. It was left to the caller, so any caller that passed a
    corpus but forgot the extra assignment persisted a companies run labelled
    `creator` -- invisible to the Companies panel and unserialisable on read.
    """
    brief: Brief = result["brief"]
    params: dict[str, int] = result["params"]
    candidates: list = result["candidates"]
    ranked: list[dict] = result["ranked"]
    by_id = {candidate.id: candidate for candidate in candidates}

    if corpus.kind == "prospect":
        ranked_snapshots = [
            prospect_ranked_to_snapshot(entry, by_id[entry["id"]], rank)
            for rank, entry in enumerate(ranked, start=1)
            if entry.get("id") in by_id
        ]
        candidate_snapshots = [prospect_to_snapshot(item) for item in candidates]
    else:
        ranked_snapshots = [
            ranked_to_snapshot(entry, by_id[entry["id"]], brief, rank)
            for rank, entry in enumerate(ranked, start=1)
            if entry.get("id") in by_id
        ]
        candidate_snapshots = [creator_to_snapshot(item) for item in candidates]

    dataset = "real" if corpus.real_data else "synthetic"
    summary = build_summary(candidate_snapshots, ranked, summary_spec(corpus.kind))
    summary["dataset"] = dataset
    return {
        "id": run_id,
        "kind": corpus.kind,
        "dataset": dataset,
        "brief": brief_to_payload(brief),
        "params": MatchParams(**params).model_dump(mode="json"),
        "result": {
            "candidates": candidate_snapshots,
            "ranked": ranked_snapshots,
        },
        "warnings": build_warnings(
            ranked,
            result.get("relaxed_filters"),
            retrieved=len(candidate_snapshots),
        ),
        "summary": summary,
    }


def run_detail(record: dict) -> RunDetail:
    result = _normalize_result(record["result"])
    kind = kind_for_record(record)
    dataset = dataset_for_record(record)
    corpus = get_corpus(kind, dataset)
    return RunDetail.model_validate(
        {
            "run_id": record["id"],
            "created_at": record["created_at"],
            "brief": record["brief"],
            "params": record["params"],
            "warnings": record["warnings"],
            "summary": summarize_record(record, corpus),
            # The `candidates` annotation is a union, so Pydantic picks the arm by
            # trying each. Left to itself it would match a company against
            # CreatorSnapshot wherever the required fields happened to overlap --
            # `id`, `creator_key` and `tags` all exist on both -- and silently
            # emit a company as a creator with most fields defaulted away. Naming
            # the kind here is what makes the union unambiguous.
            "kind": kind,
            "dataset": dataset,
            "candidates": [_candidate_arm(candidate, kind) for candidate in result["candidates"]],
            "ranked": result["ranked"],
        }
    )


def saved_match_response(record: dict) -> dict:
    return SavedMatchResponse(
        saved_id=record["id"],
        run_id=record["run_id"],
        kind=record["kind"],
        brief=record["brief"],
        candidate=record["candidate"],
        ranked=record["ranked"],
        status=record["status"],
        note=record["note"],
        source_created_at=record["source_created_at"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    ).model_dump(mode="json")


def summarize_record(record: dict, corpus: Corpus = CREATORS) -> dict:
    """The summary, with cells present even for runs stored before cells existed.
    Regenerated on read rather than rewritten: cells are pure formatting over
    values already stored, so they cannot disagree with the stored numbers.
    """
    spec = summary_spec(corpus.kind)
    stored = record.get("summary") or {}
    if stored.get("cells") and stored.get("kind") == corpus.kind:
        return stored
    if all(key in stored for key in spec.keys):
        hydrated = dict(stored)
        hydrated["kind"] = corpus.kind
        hydrated["cells"] = spec.render_cells(stored)
        return hydrated
    result = _normalize_result(record["result"])
    return build_summary(result["candidates"], result["ranked"], spec)


def _candidate_arm(candidate: dict, kind: str) -> dict:
    """Coerce one stored candidate into the arm `kind` names."""
    model = ProspectSnapshot if kind == "prospect" else CreatorSnapshot
    # No exclude_none: a stored creator candidate can carry an explicit null for a
    # field that did not exist when it was written, and dropping it would change
    # the payload for stored runs. `evidence` lives on the ranked row instead.
    return model.model_validate(candidate).model_dump(mode="json")


def _normalize_result(result: dict) -> dict:
    candidates = []
    by_id = {}
    for raw in result.get("candidates", []):
        candidate = dict(raw)
        candidate["creator_key"] = candidate_key(candidate)
        candidates.append(candidate)
        by_id[candidate["id"]] = candidate
    ranked = []
    for raw in result.get("ranked", []):
        entry = dict(raw)
        candidate = by_id.get(entry.get("id"))
        if candidate is not None:
            entry["creator_key"] = candidate["creator_key"]
        ranked.append(entry)
    return {"candidates": candidates, "ranked": ranked}


def candidate_key(candidate: dict) -> str:
    """A stored row's identity, back-filled when the column predates it.

    Reads whichever corpus's fields are present. This back-fill runs on every run
    the app displays, including the five stored before any prospect existed, so
    it must not assume a creator shape: a row carrying `headcount` is a company
    and keying it by an absent platform/handle would produce "::" for every one.
    """
    key = candidate.get("creator_key")
    if key and ":" in key:
        return key
    if "headcount" in candidate:
        return f"{candidate.get('industry', '')}:{candidate.get('name', '')}"
    return f"{candidate.get('platform', '')}:{candidate.get('handle', '')}"


def run_list_item(record: dict) -> RunListItem:
    summary = record.get("summary") or {}
    return RunListItem(
        run_id=record["id"],
        created_at=record["created_at"],
        brief=record["brief"],
        kind=kind_for_record(record),
        dataset=dataset_for_record(record),
        n_results=int(summary.get("n_results", 0)),
        n_strong=int(summary.get("n_strong", 0)),
        has_warnings=bool(record.get("warnings")),
    )


def creator_key(influencer: Influencer) -> str:
    return f"{influencer.platform}:{influencer.handle}"


def prospect_key(prospect) -> str:
    """The same idea as creator_key: industry plus name, both of which are stated
    on the record, so two companies in the same sector stay distinct.
    """
    return f"{prospect.industry}:{prospect.name}"
