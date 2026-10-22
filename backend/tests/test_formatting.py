"""Tests for src.formatting display helpers."""

from src.formatting import format_followers, match_evidence
from src.corpora import Influencer
from src.models import Brief


def make_influencer(id_=1, tags=None, bio=""):
    return Influencer(
        id=id_, handle=f"@c{id_}", platform="Instagram",
        city="Austin", followers=1000, engagement=5.0,
        tags=tags or [], bio=bio,
    )


def test_format_followers_boundaries():
    assert format_followers(999) == "999"
    assert format_followers(1_000) == "1K"
    assert format_followers(48_000) == "48K"
    assert format_followers(1_000_000) == "1.0M"
    assert format_followers(5_400_000) == "5.4M"


def test_match_evidence_reports_brief_terms_found_in_the_profile():
    brief = Brief(goal="calm yoga stretching for beginners", platform="Any")
    inf = make_influencer(1, tags=["stretching"], bio="Gentle flows")
    evidence = " | ".join(match_evidence(brief, inf))
    assert "Brief terms found in profile" in evidence


def test_match_evidence_shared_terms_from_tags_and_bio():
    brief = Brief(goal="", platform="Any", audience="", vibe="calm yoga stretching")
    inf = make_influencer(1, tags=["stretching"], bio="")
    evidence = " | ".join(match_evidence(brief, inf))
    assert "Relevant profile tags" in evidence


def test_match_evidence_fallback_message():
    brief = Brief(goal="zzz qqq", platform="Any", audience="", vibe="xxx yyy")
    inf = make_influencer(1, tags=["fps"], bio="Shooter games.")
    evidence = " | ".join(match_evidence(brief, inf))
    assert "semantic similarity" in evidence
