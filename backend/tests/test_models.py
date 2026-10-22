"""Tests for src.models: the query shared by every corpus."""

from api.schemas.models import BriefPayload
from src.models import Brief


def test_query_text_uses_free_text_goal_verbatim():
    """Free text is the query: nothing is rewritten or appended from a list."""
    brief = Brief(
        goal="a thrifted-vintage label for slow fashion", platform="TikTok",
        audience="millennials", vibe="high energy",
    )
    text = brief.query_text()
    assert text.startswith("a thrifted-vintage label for slow fashion")
    assert "millennials" in text
    assert "high energy" in text
    assert "Topics include:" not in text


def test_query_text_uses_goal_alone_when_refinements_empty():
    brief = Brief(goal="deep-dive coding tutorials", platform="Any")
    assert brief.query_text() == "deep-dive coding tutorials"


def test_legacy_niche_payload_is_accepted_as_goal():
    """Old clients still posting 'niche' keep working; it becomes the goal."""
    payload = BriefPayload.model_validate({"niche": "sourdough baking for beginners", "platform": "Any"})
    assert payload.goal == "sourdough baking for beginners"
    assert Brief(goal=payload.goal, platform=payload.platform).query_text() == "sourdough baking for beginners"