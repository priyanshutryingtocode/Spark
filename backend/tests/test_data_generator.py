"""Tests for src.data_generator: determinism, invariants, seed propagation.

The determinism tests are the important ones. The profile text is the
embedding cache key, so if a creator's values can shift when you change
`--count` or `--balanced-floor`, every vector is re-billed -- at 1,000 requests
a day on the free tier, a full day of quota for a change that should have been
free. These tests are the guard on that.
"""

import statistics

import pytest

from src.data_generator import (
    GROUP_TAGS,
    PLATFORMS,
    TAG_GROUPS,
    TOPIC_TAGS,
    generate_balanced_influencers,
    generate_influencers,
)

TAG_SET = set(TOPIC_TAGS)

SMALL = 270   # 10 groups x 9 platforms x floor 3
LARGE = 990   # floor 11


def handle_matches_name(name: str, handle: str) -> bool:
    """True when the handle is recognisably built from the name.

    Every generated pattern qualifies, including `f.last`, which carries the
    first *initial* and the full surname -- a real and common shape for a
    creator with a short first name.
    """
    from src.data_generator import _name_parts

    first, last = _name_parts(name)
    body = handle[1:].lower()
    if first and first in body:
        return True
    if last and last in body:
        return True
    return bool(last and first and body.startswith(f"{first[0]}."))


def fingerprint(c) -> tuple:
    """Every generated field, so any drift anywhere shows up."""
    return (
        c.id, c.name, c.handle, c.platform, c.city, c.country, c.language,
        c.followers, c.engagement, c.average_views, c.average_likes,
        c.average_comments, c.verified, c.posts_per_week, c.account_age_years,
        tuple(c.tags), c.bio, c.content_style, c.audience_age, c.audience_gender,
        c.audience_country, tuple(c.brand_collaborations), c.reach_ratio,
        c.sponsored_ratio, c.growth_trend, tuple(c.audience_top_countries),
    )


# ------------------------------------------------------------- determinism

def apply_signals(creator, signals) -> None:
    """Lives here, not in src/models.py: nothing in production called it."""
    creator.content_style = signals.content_style
    creator.audience_age = signals.audience_age
    creator.audience_gender = signals.audience_gender
    creator.audience_country = signals.audience_country
    creator.brand_collaborations = list(signals.brand_collaborations)
    creator.reach_ratio = signals.reach_ratio
    creator.sponsored_ratio = signals.sponsored_ratio
    creator.growth_trend = signals.growth_trend
    creator.audience_top_countries = list(signals.audience_top_countries)


def test_same_seed_reproduces_exactly():
    a = generate_balanced_influencers(count=SMALL, seed=5)
    b = generate_balanced_influencers(count=SMALL, seed=5)
    assert [fingerprint(c) for c in a] == [fingerprint(c) for c in b]


def test_a_different_seed_changes_the_corpus():
    a = generate_balanced_influencers(count=SMALL, seed=5)
    b = generate_balanced_influencers(count=SMALL, seed=6)
    assert [fingerprint(c) for c in a] != [fingerprint(c) for c in b]


def test_raising_the_balanced_floor_keeps_existing_creators():
    """The core property.

    A creator is a function of (seed, group, platform, slot), so a higher
    floor appends slots and must not rewrite anything already generated. Before
    this was fixed, a floor change rewrote 98% of the corpus and re-billed the
    entire embedding cache.
    """
    low = generate_balanced_influencers(count=SMALL, seed=5, min_per_group_platform=3)
    high = generate_balanced_influencers(count=SMALL + 90, seed=5, min_per_group_platform=4)
    assert [fingerprint(c) for c in low] == [fingerprint(c) for c in high[:SMALL]]


def test_a_large_floor_keeps_a_small_corpus_intact():
    small = generate_balanced_influencers(count=SMALL, seed=5, min_per_group_platform=3)
    large = generate_balanced_influencers(count=LARGE, seed=5, min_per_group_platform=11)
    assert [fingerprint(c) for c in small] == [fingerprint(c) for c in large[:SMALL]]


def test_growing_count_only_appends():
    small = generate_balanced_influencers(count=SMALL, seed=5)
    big = generate_balanced_influencers(count=SMALL * 2, seed=5)
    assert [fingerprint(c) for c in small] == [fingerprint(c) for c in big[:SMALL]]
    assert len(big) == SMALL * 2


def test_growing_count_appends_in_the_unbalanced_generator_too():
    small = generate_influencers(count=100, seed=9)
    big = generate_influencers(count=300, seed=9)
    assert [fingerprint(c) for c in small] == [fingerprint(c) for c in big[:100]]


def test_ids_stay_contiguous_and_are_not_renumbered():
    creators = generate_balanced_influencers(count=LARGE, seed=5, min_per_group_platform=11)
    assert sorted(c.id for c in creators) == list(range(LARGE))
    grown = generate_balanced_influencers(count=LARGE + 90, seed=5, min_per_group_platform=11)
    assert [c.id for c in grown[:LARGE]] == list(range(LARGE))


def test_creator_depends_on_its_slot_not_on_its_id():
    """A slot's creator is fixed by the key; the id is just its position.

    Tag order is random per creator, so tags cannot identify a slot - the
    (seed, group, platform, slot) key can, and that is what the generator
    derives everything from.
    """
    from src.data_generator import TAG_GROUPS, _create_creator

    key = (5, "apparel", "Instagram", 0)
    first = _create_creator(0, key, "Instagram", TAG_GROUPS["apparel"], used_handles=set())
    elsewhere = _create_creator(999, key, "Instagram", TAG_GROUPS["apparel"], used_handles=set())
    assert (first.name, first.handle, tuple(first.tags), first.followers) == (
        elsewhere.name, elsewhere.handle, tuple(elsewhere.tags), elsewhere.followers
    )
    assert first.id != elsewhere.id


def test_handle_collision_bumps_only_the_colliding_creator():
    """A collision re-derives the handle with a sub-salt; nothing else moves.

    The old implementation retried by drawing from a shared random stream, so
    one collision anywhere in the corpus shifted every later creator. Here the
    retry depends only on the colliding creator's own slot key.
    """
    from src.data_generator import TAG_GROUPS, _create_creator

    key_a = (5, "apparel", "Instagram", 0)
    key_b = (5, "apparel", "Instagram", 1)
    group = TAG_GROUPS["apparel"]

    solo_a = _create_creator(0, key_a, "Instagram", group, used_handles=set())
    solo_b = _create_creator(1, key_b, "Instagram", group, used_handles=set())

    # b keeps its own handle whatever is reserved: the retry for a never looks
    # at another slot's key.
    after = _create_creator(1, key_b, "Instagram", group, used_handles={solo_a.handle})
    assert after.handle == solo_b.handle

    # Now make a collide for real: reserve every handle a would try in turn,
    # which is the same condition as a genuinely crowded pool.
    from src.data_generator import _derive_handle
    from src.slotting import stable_seed

    name = solo_a.name
    tags = list(solo_a.tags)
    taken = {
        _derive_handle(name, tags, stable_seed(key_a, "handle", attempt))
        for attempt in range(3)
    }
    crowded = _create_creator(0, key_a, "Instagram", group, used_handles=set(taken))
    assert crowded.handle not in taken
    assert crowded.name == solo_a.name, "only the handle may change"


def test_creator_is_reproducible_with_a_shared_handle_pool():
    """Two creators in one run must resolve the same handles every time.

    The pool is shared state, so this is the case where a bug in the retry
    order would show up: whatever the handles, the same pair must come out.
    """
    from src.data_generator import TAG_GROUPS, _create_creator

    group = TAG_GROUPS["apparel"]

    def run() -> list[str]:
        used: set[str] = set()
        return [
            _create_creator(i, (5, "apparel", "Instagram", i), "Instagram", group,
                            used_handles=used).handle
            for i in range(40)
        ]

    assert run() == run()
    assert len(set(run())) == 40


# ---------------------------------------------------------------- structure

def test_generate_influencers_count_and_ids():
    creators = generate_influencers(count=25, seed=7)
    assert len(creators) == 25
    assert sorted(c.id for c in creators) == list(range(25))


def test_handles_unique():
    for creators in (
        generate_influencers(count=200, seed=1),
        generate_balanced_influencers(count=SMALL, seed=1),
    ):
        handles = [c.handle for c in creators]
        assert len(handles) == len(set(handles))


def test_tags_come_from_the_vocabulary_and_span_topics():
    for c in generate_influencers(count=50):
        assert c.platform in PLATFORMS
        assert 4 <= len(c.tags) <= 8
        assert len(c.tags) == len(set(c.tags))
        assert all(tag in TAG_SET for tag in c.tags)


def test_creators_span_more_than_one_group():
    creators = generate_influencers(count=120, seed=3)
    multi = [c for c in creators
             if len({GROUP_TAGS[t] for t in c.tags if t in GROUP_TAGS}) > 1]
    assert len(multi) > len(creators) / 2


def test_niche_is_gone_from_the_model():
    for c in generate_influencers(count=10):
        assert not hasattr(c, "niche")
        assert not hasattr(c, "secondary_niches")


# ------------------------------------------------------------------ handles

def test_every_handle_reflects_the_creator_name():
    """The regression this guards.

    The handle used to come from an independent `fake.user_name()` draw, so
    "Jody Burns" got "@huangdaniel4379" -- measured at 1% name-related across
    the 500-creator corpus, and those were coincidences. A reviewer scanning
    synthetic data checks the handle against the name first.
    """
    creators = generate_balanced_influencers(count=500, min_per_group_platform=5, seed=42)
    mismatched = [f"{c.name!r} -> {c.handle!r}" for c in creators
                  if not handle_matches_name(c.name, c.handle)]
    assert not mismatched, f"{len(mismatched)} handles unrelated to their name: {mismatched[:3]}"


def test_non_ascii_names_still_get_a_related_handle():
    """A naive slug yields an empty handle for Hangul or Devanagari names.

    46 of the 500 creators have no ASCII characters at all, so this is not an
    edge case.
    """
    from src.data_generator import _name_parts
    from src.slotting import ascii_fold

    creators = generate_balanced_influencers(count=500, min_per_group_platform=5, seed=42)
    non_ascii = [c for c in creators if not c.name.isascii()]
    assert non_ascii, "corpus should contain non-Latin names for this to mean anything"
    for c in non_ascii:
        first, _ = _name_parts(c.name)
        assert first, f"{c.name!r} produced no romanized name"
        assert ascii_fold(c.name).isascii()
        assert handle_matches_name(c.name, c.handle), f"{c.name!r} -> {c.handle!r}"


def test_accented_names_fold_to_ascii():
    from src.data_generator import _name_parts

    assert _name_parts("Giosuè Curatoli") == ("giosue", "curatoli")
    assert _name_parts("Thora Sigurdardottir")[0] == "thora"


def test_handles_stay_within_a_realistic_length():
    creators = generate_balanced_influencers(count=500, min_per_group_platform=5, seed=42)
    assert max(len(c.handle) for c in creators) <= 30
    assert all(len(c.handle) >= 3 for c in creators)


def test_topic_suffix_comes_from_the_creators_own_tags():
    """`@jodyburns.science` should mean the creator covers science."""
    import re

    from src.data_generator import _tag_slug

    creators = generate_balanced_influencers(count=500, min_per_group_platform=5, seed=42)
    for i, c in enumerate(creators):
        slugs = {re.sub(r"[^a-z0-9]+", "", t.lower())[:12] for t in c.tags}
        assert _tag_slug(c.tags, i * 7) in slugs


def test_handles_are_unique_at_scale():
    creators = generate_balanced_influencers(count=LARGE, seed=42, min_per_group_platform=11)
    assert len({c.handle for c in creators}) == len(creators)


def test_balanced_covers_every_group_platform_floor():
    floor = 2
    creators = generate_balanced_influencers(count=180, seed=42, min_per_group_platform=floor)
    counts: dict[tuple[str, str], int] = {}
    for c in creators:
        for group in {GROUP_TAGS[t] for t in c.tags if t in GROUP_TAGS}:
            counts[(group, c.platform)] = counts.get((group, c.platform), 0) + 1
    combos = {(g, p) for g in TAG_GROUPS for p in PLATFORMS}
    assert set(counts) >= combos
    assert min(counts[combo] for combo in combos) >= floor


def test_balanced_too_small_raises():
    with pytest.raises(ValueError, match="too small"):
        generate_balanced_influencers(count=10)


def test_balanced_respects_requested_fields():
    creators = generate_balanced_influencers(count=SMALL, seed=42)
    assert len(creators) == SMALL
    assert sorted(c.id for c in creators) == list(range(SMALL))


# ------------------------------------------------------------------ signals

def test_signals_have_real_variety():
    """Thin signal values make every ranking reason read the same."""
    creators = generate_balanced_influencers(count=LARGE, seed=42, min_per_group_platform=11)
    assert len({c.content_style for c in creators}) >= 20
    assert len({c.audience_age for c in creators}) >= 10
    assert len({c.audience_gender for c in creators}) >= 12
    assert len({c.growth_trend for c in creators}) == 3
    assert max(len(c.audience_top_countries) for c in creators) >= 3


def test_every_creator_has_a_signal_row():
    for c in generate_influencers(count=40, seed=2):
        signals = c.signals()
        assert signals.creator_id == c.id
        assert signals.content_style
        assert signals.audience_age
        assert signals.audience_gender
        assert signals.growth_trend in {"rising", "steady", "declining"}
        assert 0.0 < signals.reach_ratio
        assert 0.0 <= signals.sponsored_ratio <= 0.75
        assert signals.audience_top_countries[0] == signals.audience_country


def test_signals_round_trip_through_apply():
    original = generate_influencers(count=1, seed=8)[0]
    copy = generate_influencers(count=1, seed=8)[0]
    apply_signals(copy, original.signals())
    assert copy.content_style == original.content_style
    assert copy.brand_collaborations == original.brand_collaborations
    assert copy.reach_ratio == original.reach_ratio
    assert copy.growth_trend == original.growth_trend


def test_reach_ratio_is_exactly_views_over_followers():
    """The signal must be the row's own arithmetic, not a separate estimate.

    A reason may quote reach_ratio and average_views together; if the two
    disagreed, the corpus would be asserting something a reader could disprove
    by dividing.
    """
    for c in generate_balanced_influencers(count=300, seed=4, min_per_group_platform=3):
        assert c.reach_ratio == c.average_views / max(c.followers, 1)


def test_growth_trend_agrees_with_reach():
    creators = generate_balanced_influencers(count=LARGE, seed=42, min_per_group_platform=11)
    rising = [c.reach_ratio for c in creators if c.growth_trend == "rising"]
    declining = [c.reach_ratio for c in creators if c.growth_trend == "declining"]
    assert statistics.median(rising) > statistics.median(declining)
    assert not [c for c in creators if c.growth_trend == "rising" and c.reach_ratio < 0.3]
    assert not [c for c in creators if c.growth_trend == "declining" and c.reach_ratio > 0.5]


def test_heavy_sponsorship_never_pairs_with_excellent_organic_reach():
    creators = generate_balanced_influencers(count=LARGE, seed=42, min_per_group_platform=11)
    assert not [c for c in creators if c.sponsored_ratio > 0.3 and c.reach_ratio > 0.5]


def test_metric_facts_are_internally_consistent():
    for c in generate_balanced_influencers(count=300, seed=6, min_per_group_platform=3):
        assert c.average_views >= c.average_likes, "views below likes contradicts engagement"
        assert c.average_likes >= c.average_comments
        assert 0 < c.engagement <= 100


def test_collaborations_are_unique_real_brands():
    from src.data_generator import ALL_BRANDS

    for c in generate_influencers(count=200, seed=9):
        assert len(set(c.brand_collaborations)) == len(c.brand_collaborations)
        assert all(brand in ALL_BRANDS for brand in c.brand_collaborations)
        assert len(c.brand_collaborations) <= 5


def test_corpus_text_includes_the_signals_a_reason_may_cite():
    """corpus_text must not change when the signal columns move tables."""
    from src.ranking import GROUNDABLE_FIELDS

    for c in generate_influencers(count=20, seed=12):
        text = c.corpus_text()
        for field in GROUNDABLE_FIELDS:
            for value in GROUNDABLE_FIELDS[field](c):
                assert str(value) in text, f"{field}={value!r} missing from corpus_text"


def test_generated_corpus_text_is_pinned():
    """A golden fingerprint over a real slice of the corpus.

    `test_same_seed_reproduces_exactly` proves the generator is deterministic.
    This proves the *format* has not moved, which is a different guarantee and
    the one with teeth: corpus_text is the text every vector is built from, and
    `Influencer.corpus_text` says outright that changing it invalidates every
    cached vector. A reworded fact -- "Topics:" becoming "Focuses on:" -- would
    change nothing else in the suite and would quietly degrade retrieval quality
    for every indexed creator until a full re-embed nobody had noticed was
    needed. A hash pins the exact bytes.

    200 records rather than the full corpus: enough to cover every draw path the
    generator takes, fast enough to run on every change.
    """
    import hashlib

    from src.data_generator import generate_influencers

    fingerprint = hashlib.sha256(
        "|".join(c.corpus_text() for c in generate_influencers(count=200)).encode("utf-8")
    ).hexdigest()
    assert fingerprint == "a093b6c0f91a17ca50834ebfb04271a6a7540cd995406ad27ca8e8f1f38cd195", (
        "generated corpus_text changed: every cached vector is now stale and the "
        "corpus must be re-embedded. If this is intentional, update the value here "
        "AND reindex."
    )
