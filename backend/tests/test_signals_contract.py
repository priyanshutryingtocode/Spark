"""The embedding-cache contract for the creator_signals split.

Migration 007 moved five columns off `influencers` into `creator_signals`. That
is only safe if the text a creator is embedded as does not change, because the
text is the cache key: a one-character difference re-bills that creator's
vector, and at 1,000 requests/day on the free tier a full re-embed is a
multi-day cost.

These tests pin the contract mechanically rather than relying on the promise in
the migration comment. `_OLD_CORPUS_TEXT` is a literal copy of the string the
single-table version produced, so any drift in `corpus_text` -- a reordered
clause, a changed separator, a dropped field -- fails here.
"""

from dataclasses import replace

from src.data_generator import generate_balanced_influencers
from src.corpora import CreatorSignals, Influencer
from src.ranking import GROUNDABLE_FIELDS
from src.vector_store import _content_hash


def make_creator(**overrides) -> Influencer:
    base = dict(
        id=7,
        handle="@sample",
        platform="Instagram",
        city="Austin",
        country="USA",
        followers=12_000,
        engagement=5.0,
        tags=["gym", "running"],
        bio="Lifting daily.",
        name="Sam Example",
        content_style="Tutorials",
        audience_age="25-34",
        audience_gender="60% Female",
        audience_country="USA",
        brand_collaborations=["Nike", "Gymshark"],
    )
    base.update(overrides)
    return Influencer(**base)


# The exact string emitted when these fields lived on `influencers`, before the
# split. If this no longer matches, the cache is invalidated and every vector
# must be re-billed.
OLD_CORPUS_TEXT = (
    "Creator @sample on Instagram, based in Austin, USA. "
    "Topics: gym, running. "
    "Content style: Tutorials. "
    "Audience: 25-34, 60% Female, USA. "
    "Past brand partners: Nike, Gymshark. "
    "Lifting daily."
)


# Moved out of src/models.py: nothing in production called it, but the
# contract it checks -- that splitting signals into their own table did not
# change the text that was embedded -- is the reason this file exists.
def apply_signals(creator, signals):
    """Copy a signal row onto a creator, as read from the join."""
    creator.content_style = signals.content_style
    creator.audience_age = signals.audience_age
    creator.audience_gender = signals.audience_gender
    creator.audience_country = signals.audience_country
    creator.brand_collaborations = list(signals.brand_collaborations)
    creator.reach_ratio = signals.reach_ratio
    creator.sponsored_ratio = signals.sponsored_ratio
    creator.growth_trend = signals.growth_trend
    creator.audience_top_countries = list(signals.audience_top_countries)


def test_corpus_text_is_unchanged_by_the_signals_split():
    assert make_creator().corpus_text() == OLD_CORPUS_TEXT


def test_signals_reach_corpus_text_unchanged():
    """Reading the fields off a joined CreatorSignals produces the same text."""
    original = make_creator()
    via_signals = replace(original, **_signal_kwargs(original.signals()))
    assert via_signals.corpus_text() == OLD_CORPUS_TEXT
    assert _content_hash(via_signals.corpus_text()) == _content_hash(original.corpus_text())


def _signal_kwargs(signals: CreatorSignals) -> dict:
    return {
        "content_style": signals.content_style,
        "audience_age": signals.audience_age,
        "audience_gender": signals.audience_gender,
        "audience_country": signals.audience_country,
        "brand_collaborations": list(signals.brand_collaborations),
    }


def test_apply_signals_round_trips_corpus_text():
    original = make_creator()
    restored = Influencer(
        id=original.id, handle=original.handle, platform=original.platform,
        city=original.city, followers=original.followers, engagement=original.engagement,
        tags=list(original.tags), bio=original.bio, name=original.name, country=original.country,
    )
    assert restored.corpus_text() != OLD_CORPUS_TEXT
    apply_signals(restored, original.signals())
    assert restored.corpus_text() == OLD_CORPUS_TEXT


def test_every_groundable_field_is_still_in_the_embedded_text():
    """A reason may cite only what retrieval could have found.

    Five of the eight groundable fields now live in creator_signals, so this
    is the check that keeps the citation allowlist honest after the move.
    """
    for creator in generate_balanced_influencers(count=90, seed=3, min_per_group_platform=1):
        text = creator.corpus_text()
        for field, read in GROUNDABLE_FIELDS.items():
            for value in read(creator):
                assert str(value) in text, f"{field}={value!r} missing from corpus_text"


def test_new_signals_are_stored_but_not_citable():
    """reach_ratio, sponsored_ratio, growth_trend and the country list are
    displayable, not quotable.

    They are deliberately not in corpus_text, so a reason must not be able to
    claim them: retrieval never searched on them.
    """
    creator = make_creator()
    creator.reach_ratio = 1.5
    creator.sponsored_ratio = 0.4
    creator.growth_trend = "rising"
    creator.audience_top_countries = ["USA", "Canada"]
    text = creator.corpus_text()
    assert "1.5" not in text
    assert "rising" not in text
    assert "Canada" not in text
    for field in ("reach_ratio", "sponsored_ratio", "growth_trend",
                  "audience_top_countries"):
        assert field not in GROUNDABLE_FIELDS
