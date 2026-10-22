"""Property tests for src.prospect_generator.

The contract is the same one data_generator documents: every record is a pure
function of its slot key. That is what makes --count and --min-per-cell safe to
change, because a record's corpus_text is the embedding cache key and re-billing
500 vectors is the expensive mistake this module exists to prevent.
"""

import pytest

from src.prospect_generator import (
    DEPARTMENTS,
    INDUSTRY_GROUPS,
    NEWEST_FOUNDED_YEAR,
    OLDEST_FOUNDED_YEAR,
    SIZE_TIERS,
    generate_balanced_prospects,
    generate_prospects,
)


def tier_of(headcount: int) -> str:
    for name, (low, high) in SIZE_TIERS.items():
        if low <= headcount <= high:
            return name
    raise AssertionError(f"headcount {headcount} is in no tier band")


# --- determinism -------------------------------------------------------------

def test_same_seed_reproduces_exactly():
    first = generate_balanced_prospects(count=216, min_per_cell=3, seed=42)
    second = generate_balanced_prospects(count=216, min_per_cell=3, seed=42)
    assert [p.corpus_text() for p in first] == [p.corpus_text() for p in second]


def test_a_different_seed_produces_a_different_corpus():
    first = generate_balanced_prospects(count=216, min_per_cell=3, seed=42)
    other = generate_balanced_prospects(count=216, min_per_cell=3, seed=7)
    assert [p.corpus_text() for p in first] != [p.corpus_text() for p in other]


def test_raising_the_floor_only_appends():
    """The one that matters most.

    The slot plan is ordered round-robin so the plan for floor N is a prefix of
    the plan for floor N+1. If it were ordered by cell instead, raising the floor
    would insert records into the middle and renumber everything after it -- which
    rewrites every corpus_text, invalidates every cached vector, and re-bills the
    whole corpus. Embedding is metered per record, so this is the difference
    between a free change and a 500-request one.
    """
    lower = generate_balanced_prospects(count=216, min_per_cell=3, seed=42)
    higher = generate_balanced_prospects(count=288, min_per_cell=4, seed=42)
    assert len(higher) > len(lower)
    assert [p.corpus_text() for p in higher[:len(lower)]] == [
        p.corpus_text() for p in lower
    ], "raising the floor rewrote existing records"


def test_unbalanced_generation_is_also_deterministic():
    assert [p.corpus_text() for p in generate_prospects(count=30, seed=42)] == [
        p.corpus_text() for p in generate_prospects(count=30, seed=42)
    ]


# --- coverage ----------------------------------------------------------------

def test_count_below_the_floor_is_rejected():
    with pytest.raises(ValueError, match="too small"):
        generate_balanced_prospects(count=10, min_per_cell=3)


def test_every_industry_and_size_cell_is_covered():
    prospects = generate_balanced_prospects(count=216, min_per_cell=3)
    seen = {(tier_of(p.headcount), p.industry) for p in prospects}
    expected = {
        (tier, industry)
        for tier in SIZE_TIERS
        for group in INDUSTRY_GROUPS.values()
        for industry in group["industries"]
    }
    missing = expected - seen
    assert not missing, f"{len(missing)} industry x size cells empty: {sorted(missing)[:6]}"


def test_the_floor_is_the_minimum_occupancy_not_the_only_occupancy():
    """A cell holding exactly the floor and nothing else would still pool-limit a
    brief; the remaining rows must spread rather than pile into one cell."""
    prospects = generate_balanced_prospects(count=216, min_per_cell=3)
    counts = {}
    for p in prospects:
        key = tier_of(p.headcount)
        counts[key] = counts.get(key, 0) + 1
    assert min(counts.values()) >= 3
    assert len(set(counts.values())) <= 2, "extra rows piled into too few tiers"


def test_below_the_floor_count_still_covers_every_tier():
    prospects = generate_balanced_prospects(count=216, min_per_cell=3)
    tiers = {tier_of(p.headcount) for p in prospects}
    assert tiers == set(SIZE_TIERS)


# --- identity ----------------------------------------------------------------

def test_names_are_unique():
    """Faker repeats company names inside a corpus of this size, and a duplicate
    would make two rows indistinguishable in results."""
    prospects = generate_balanced_prospects(count=500, min_per_cell=3)
    names = [p.name for p in prospects]
    assert len(set(names)) == len(names)


def test_ids_are_dense_and_ordered():
    prospects = generate_balanced_prospects(count=216, min_per_cell=3)
    assert [p.id for p in prospects] == list(range(len(prospects)))


# --- signal coherence --------------------------------------------------------
#
# A reason may quote growth, size and hiring at once, so drawing them
# independently would let the corpus assert a company that contradicts itself.

@pytest.fixture(scope="module")
def corpus():
    return generate_balanced_prospects(count=500, min_per_cell=3)


def test_headcount_always_lands_inside_its_tier_band(corpus):
    for p in corpus:
        low, high = SIZE_TIERS[tier_of(p.headcount)]
        assert low <= p.headcount <= high


def test_trend_and_growth_rate_never_disagree(corpus):
    for p in corpus:
        if p.growth_trend == "rising":
            assert p.growth_rate > 0, f"{p.name}: rising but {p.growth_rate:+.1%}"
        elif p.growth_trend == "declining":
            assert p.growth_rate < 0, f"{p.name}: declining but {p.growth_rate:+.1%}"
        else:
            assert abs(p.growth_rate) <= 0.05, (
                f"{p.name}: 'steady' at {p.growth_rate:+.1%} is a decline wearing "
                f"the wrong label"
            )


def test_growth_rate_magnitude_scales_down_with_size(corpus):
    """A 30,000-person company cannot compound at 40% a year, and a corpus that
    says so teaches the ranker nothing."""
    def mean_abs_rate(tier):
        rates = [abs(p.growth_rate) for p in corpus if tier_of(p.headcount) == tier]
        return sum(rates) / len(rates)

    assert mean_abs_rate("micro") > mean_abs_rate("upper_mid")
    assert mean_abs_rate("upper_mid") > mean_abs_rate("enterprise")


def test_hiring_intensity_agrees_with_trend(corpus):
    """A shrinking company is not hiring into growth."""
    by_trend = {}
    for p in corpus:
        by_trend.setdefault(p.growth_trend, []).append(p.hiring_intensity)
    assert sum(by_trend["rising"]) / len(by_trend["rising"]) > sum(
        by_trend["declining"]
    ) / len(by_trend["declining"])


def test_every_trend_label_is_represented(corpus):
    """A corpus that is 80% 'rising' makes the label useless in a reason."""
    trends = {p.growth_trend for p in corpus}
    assert trends == {"rising", "steady", "declining"}


def test_founding_year_is_inside_the_fixed_anchor(corpus):
    """Anchored to a constant, not to date.today().

    A generator reading the clock would emit a different corpus every January
    and silently invalidate every cached vector on the same schedule as a deploy.
    """
    for p in corpus:
        assert OLDEST_FOUNDED_YEAR <= p.founded_year <= NEWEST_FOUNDED_YEAR


def test_funding_stage_does_not_outlive_the_company(corpus):
    order = ["bootstrapped", "seed", "Series A", "Series B", "Series C", "public"]
    for p in corpus:
        age = NEWEST_FOUNDED_YEAR - p.founded_year
        if age < 5:
            assert order.index(p.funding_stage) <= order.index("Series A"), (
                f"{p.name}: {p.funding_stage} at age {age}"
            )
        if age < 10:
            assert order.index(p.funding_stage) <= order.index("Series B"), (
                f"{p.name}: {p.funding_stage} at age {age}"
            )


def test_headcount_matches_the_scale_of_its_funding_stage(corpus):
    """Nobody raises a Series B with three employees."""
    for p in corpus:
        if p.funding_stage in {"Series B", "Series C", "public"}:
            assert p.headcount >= 51, f"{p.name}: {p.funding_stage} at {p.headcount} staff"


def test_department_mix_is_credible_for_the_size(corpus):
    """A three-person company does not have a finance department."""
    for p in corpus:
        if p.headcount < 11:
            assert len(p.department_mix) <= 2, f"{p.name}: {p.department_mix}"
        if p.headcount >= 1_001:
            assert len(p.department_mix) >= 5, f"{p.name}: {p.department_mix}"


def test_departments_come_from_the_shared_vocabulary(corpus):
    for p in corpus:
        for department in p.department_mix:
            assert department in DEPARTMENTS


def test_top_markets_always_include_the_home_country(corpus):
    """A home market is a fact, not an insight -- the same reason
    audience_top_countries includes the creator's own country."""
    for p in corpus:
        assert p.top_markets[0] == p.country, f"{p.name}: {p.top_markets} vs {p.country}"


def test_tech_stack_and_buying_signals_match_the_industry(corpus):
    """The point of grouping the vocabulary by vertical: a fintech company must
    not come with a bakery's toolchain."""
    for p in corpus:
        group = next(
            g for g in INDUSTRY_GROUPS.values() if p.industry in g["industries"]
        )
        allowed_tools = {tool for stack in group["tech_stacks"] for tool in stack}
        allowed_signals = set(group["buying_signals"])
        assert set(p.tech_stack) <= allowed_tools, f"{p.name}: {p.tech_stack}"
        assert set(p.buying_signals) <= allowed_signals, f"{p.name}: {p.buying_signals}"


def test_corpus_text_is_never_empty_and_always_names_the_company(corpus):
    for p in corpus:
        text = p.corpus_text()
        assert text.strip(), f"{p.name} produced empty corpus_text"
        assert p.name in text
        assert str(p.headcount) in text