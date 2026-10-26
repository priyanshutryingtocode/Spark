"""Display helpers, kept separate from pipeline logic so they're easy to
swap out (e.g. if you later render results in a web UI instead of stdout)."""

from typing import Any

from .corpora import CREATORS, Corpus, Influencer
from .models import Brief
from .text_match import shared_terms, terms


def format_followers(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def match_evidence(brief: Brief, influencer: Influencer) -> list[str]:
    """Deterministic profile evidence for a retrieved result.

    The LLM's reason is checked against the profile in `src/ranking`; this is
    the independent backstop shown alongside it, built only from the text the
    creator was embedded as.
    """
    evidence: list[str] = []
    brief_terms = terms(f"{brief.goal} {brief.audience} {brief.vibe}")
    shared = sorted(shared_terms(brief_terms, influencer))
    if shared:
        evidence.append(f"Brief terms found in profile: {', '.join(shared[:5])}")

    matching_tags = [tag for tag in influencer.tags if terms(tag) & brief_terms]
    if matching_tags:
        evidence.append(f"Relevant profile tags: {', '.join(matching_tags[:3])}")

    if not evidence:
        evidence.append("Retrieved by semantic similarity across the creator profile")
    return evidence


def print_brief(brief: Brief) -> None:
    print("\nBrief:")
    print(f"  Goal: {brief.goal}")
    print(f"  Platform: {brief.platform}")
    print(f"  Audience: {brief.audience}")
    print(f"  Vibe: {brief.vibe}")


def print_results(
    ranked: list[dict],
    candidates_by_id: dict[int, Any],
    brief: Brief,
    corpus: Corpus = CREATORS,
) -> None:
    fallback_entries = [e for e in ranked if e.get("source") == "fallback"]
    filled_entries = [e for e in ranked if e.get("source") == "filled"]
    if fallback_entries:
        print("\nWARNING: Gemini ranking is temporarily unavailable; showing retrieval-order results instead.")
    elif filled_entries:
        print(
            f"\nNote: the model only ranked {len(ranked) - len(filled_entries)} of {len(ranked)} requested "
            f"slots; the rest were filled from retrieval order (marked [filled] below)."
        )

    print(f"\nTop {len(ranked)} matches (fit is AI-assessed against the brief):\n")
    for i, entry in enumerate(ranked, start=1):
        cand = candidates_by_id[entry["id"]]
        fit_tag = f"[{entry.get('fit', 'unknown')} fit] " if entry.get("fit") else ""
        # A company is not a creator: it has no handle, no platform and no
        # follower count, so the creator line would either crash or print
        # fields it does not have.
        if corpus.kind == "prospect":
            place = ", ".join(part for part in (cand.city, cand.country) if part)
            print(f"{i}. {fit_tag}{cand.name}  ({cand.industry}, {place})")
            print(f"   {format_followers(cand.headcount)} employees")
        else:
            engagement = f"{cand.engagement:.1f}%" if cand.engagement is not None else "—"
            print(f"{i}. {fit_tag}{cand.handle}  ({cand.platform}, {cand.city})")
            print(f"   {format_followers(cand.followers)} followers · {engagement} engagement")
        if cand.similarity is not None:
            print(f"   Semantic relevance: {cand.similarity:.1%}")
        print(f"   Evidence: {'; '.join(match_evidence(brief, cand))}")
        for claim in entry.get("grounding", []):
            print(f"   Grounded in {claim['field']}: \"{claim['quote']}\"")
        print(f"   {entry['rationale']}\n")
