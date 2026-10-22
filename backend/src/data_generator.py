"""Seeded Faker profiles for development, demos, and retrieval evaluation.

Creators are described by topic tags, not by a single taxonomy label. A real
creator rarely occupies one niche, and a free-text brief rarely names one
either, so a `niche TEXT NOT NULL` column was a lossy label over a vocabulary
that already existed in the tags. Tags are the whole topical signal now.

Determinism
-----------
Every creator is a pure function of a *slot key*:

    (seed, group, platform, slot)

where `group` is a TAG_GROUPS entry, `platform` a supported platform, and
`slot` the creator's index within that one cell. Each creator draws from its
own `random.Random` seeded with that key, and its own Faker instance seeded
from the same key, so nothing depends on how many creators were generated
before it.

This is not tidiness. With one shared random stream, a creator's values depended
on its position in the emit order, and the emit order depended on
`--balanced-floor`: raising the floor from 3 to 4 rewrote 98% of the corpus.
Since the profile text is the embedding cache key, that re-bills every vector,
and embedding is the expensive step (1,000 requests/day on the free tier). The
property tests in tests/test_data_generator.py pin the behaviour that makes
`--count` and `--balanced-floor` safe to change.

Ids are assigned from a stable sort of the slot key rather than from a
post-generation shuffle, so growing the corpus appends instead of renumbering.
"""

import hashlib
import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .corpora import CreatorSignals, CreatorSourceRecord, Influencer
from .platforms import PLATFORMS
from .slotting import ascii_fold, slot_faker, slot_rng, stable_seed

TOPIC_TAGS = [
    "AI", "C++", "DIY", "DJ", "EVs", "FIRE", "FPS", "HIIT", "JavaScript",
    "K-beauty", "Python", "RPG", "activities", "algorithms", "architecture",
    "authors", "backpacking", "baking", "beans", "biology", "breathwork",
    "brewing", "budget", "budgeting", "cafes", "calisthenics",
    "capsule wardrobe", "career", "cars", "cats", "cinematography",
    "clean beauty", "covers", "crypto", "curly hair", "design", "desserts",
    "diet", "digital art", "digital nomad", "discipline", "dogs", "drone",
    "eco", "editing", "education", "esports", "espresso", "family", "fashion",
    "fiction", "film", "fragrance", "gadgets", "gear", "guitar", "gym",
    "habits", "hair growth", "healthy recipes", "history", "hotels",
    "illustration", "indie games", "interiors", "investing", "landscape",
    "latte art", "leadership", "luxury", "luxury homes", "macros", "makeup",
    "marketing", "math", "meal prep", "memes", "mindfulness", "mindset",
    "minimalism", "minimalist", "mobility", "mods", "motorcycles", "newborn",
    "non-fiction", "nutrition", "outfits", "painting", "parody", "physics",
    "piano", "plants", "portraits", "production", "productivity", "products",
    "property", "protein", "quotes", "reading", "recipes", "renovation",
    "renting", "rescue", "research", "restaurants", "reviews", "running",
    "sales", "salon", "satire", "science", "secondhand", "sketches",
    "skincare", "slow fashion", "smart home", "solo travel", "space",
    "standup", "startups", "stocks", "storytelling", "streaming",
    "street food", "streetwear", "strength", "stretching", "study tips",
    "styling", "success", "supercars", "system design", "thrifted",
    "toddlers", "training", "travel", "vintage", "watches", "watercolor",
    "wellness",
]

# Tags that a brand is most likely to search for, grouped so the balanced
# generator can guarantee each group is represented on every platform. This is
# a generation-time concern only: nothing is stored, and retrieval never sees
# a group. Without it, a floor per tag (142 x 9 cells) would demand a corpus
# far larger than any free-tier index can hold.
TAG_GROUPS = {
    "apparel": ["fashion", "streetwear", "outfits", "minimalist", "capsule wardrobe",
                "slow fashion", "secondhand", "thrifted", "vintage", "styling", "luxury"],
    "fitness": ["gym", "strength", "running", "HIIT", "calisthenics", "mobility",
                "stretching", "breathwork", "mindfulness", "wellness"],
    "food": ["recipes", "baking", "desserts", "meal prep", "healthy recipes", "macros",
             "protein", "diet", "nutrition", "restaurants", "street food"],
    "beauty": ["makeup", "skincare", "clean beauty", "fragrance", "K-beauty", "curly hair",
               "hair growth", "salon", "products"],
    "tech": ["AI", "Python", "JavaScript", "C++", "algorithms", "system design",
             "gadgets", "smart home", "productivity", "editing", "design", "gear"],
    "travel": ["solo travel", "backpacking", "budget", "digital nomad", "travel",
               "hotels", "landscape", "architecture", "interiors", "cars"],
    "money": ["investing", "stocks", "budgeting", "crypto", "FIRE", "property",
              "renting", "luxury homes", "sales", "leadership", "startups", "marketing"],
    "culture": ["film", "digital art", "painting", "illustration", "watercolor",
                "sketches", "satire", "parody", "memes", "standup", "guitar",
                "piano", "DJ", "production", "covers", "storytelling"],
    "life": ["dogs", "cats", "training", "rescue", "toddlers", "family", "newborn",
             "career", "education", "study tips", "science", "space", "physics",
             "biology", "research", "math", "reading", "authors", "fiction",
             "non-fiction", "habits", "discipline", "mindset", "success", "quotes",
             "plants", "DIY", "renovation", "activities"],
    "mobility": ["EVs", "supercars", "motorcycles", "mods", "watches", "cafes",
                 "beans", "brewing", "espresso", "latte art", "reviews"],
}
# Asserted rather than filtered. The filter that used to be here silently
# dropped unknown entries at import, which is how "kinetic" sat in the mobility
# group for as long as it did. Every entry must now be a real tag, or the
# balanced floor for that cell is unsatisfiable.
_unknown = {t for tags in TAG_GROUPS.values() for t in tags} - set(TOPIC_TAGS)
if _unknown:
    raise ValueError(f"TAG_GROUPS contains tags that are not in TOPIC_TAGS: {sorted(_unknown)}")

GROUP_TAGS = {tag: group for group, tags in TAG_GROUPS.items() for tag in tags}

CITY_COUNTRY = {
    "New York": "USA", "Austin": "USA", "Toronto": "Canada", "London": "UK",
    "Paris": "France", "Berlin": "Germany", "Madrid": "Spain", "Rome": "Italy",
    "Tokyo": "Japan", "Seoul": "South Korea", "Singapore": "Singapore", "Bangkok": "Thailand",
    "Mumbai": "India", "Bangalore": "India", "Sydney": "Australia", "Cape Town": "South Africa",
    "Lagos": "Nigeria", "Dubai": "UAE", "Mexico City": "Mexico", "Sao Paulo": "Brazil",
}
LOCALE_BY_COUNTRY = {
    "USA": "en_US", "Canada": "en_CA", "UK": "en_GB", "France": "fr_FR", "Germany": "de_DE",
    "Spain": "es_ES", "Italy": "it_IT", "Japan": "ja_JP", "South Korea": "ko_KR",
    "India": "en_IN", "Brazil": "pt_BR", "Mexico": "es_MX", "Australia": "en_AU",
}
LANGUAGES_BY_COUNTRY = {
    "USA": ["English"], "Canada": ["English", "French"], "UK": ["English"],
    "France": ["French"], "Germany": ["German"], "Spain": ["Spanish"], "Italy": ["Italian"],
    "Japan": ["Japanese"], "South Korea": ["Korean"], "India": ["Hindi", "English"],
    "Brazil": ["Portuguese"], "Mexico": ["Spanish"], "Thailand": ["Thai", "English"],
    "Singapore": ["English"], "Australia": ["English"], "South Africa": ["English"],
    "Nigeria": ["English"], "UAE": ["Arabic", "English"],
}
BRAND_TAGS = {
    "tech": ["Apple", "Samsung", "Asus", "Lenovo", "NVIDIA", "GitHub", "JetBrains", "DigitalOcean",
             "Logitech", "Anker", "Notion", "Linear"],
    "travel": ["Airbnb", "Booking.com", "Expedia", "Marriott", "Marriott Bonvoy", "Rick Steves", "National Geographic"],
    "beauty": ["Sephora", "Nykaa", "Ulta", "Glossier", "Fenty Beauty", "The Ordinary"],
    "culture": ["Canon", "Sony", "DJI", "Adobe", "Fujifilm", "Sonos", "Bose", "Patagonia"],
    "money": ["Stripe", "Wise", "Revolut", "Vanguard", "Charles Schwab", "Coinbase", "Acorns"],
    "food": ["Blue Bottle", "Oatly", "Whole Foods", "Trader Joe's", "Sweetgreen", "HelloFresh"],
    "apparel": ["Uniqlo", "Everlane", "Zara", "Levi's", "ThredUp", "IKEA"],
    "fitness": ["Nike", "Adidas", "Gymshark", "Lululemon", "WHOOP", "ClassPass"],
    "life": ["Petco", "Chewy", "Target", "IKEA", "Whole Foods", "Staples", "Costco"],
    # mobility had no pool, so every EV/supercar/motorcycle creator fell through
    # to ALL_BRANDS and came out having worked with Coursera.
    "mobility": ["Dometic", "Garmin", "Michelin", "Shell", "Tire Rack", "Zipcar"],
}
ALL_BRANDS = sorted({brand for brands in BRAND_TAGS.values() for brand in brands})
BIOS = [
    "Helping people master {topics} through practical tips.",
    "Sharing daily inspiration about {topics}.",
    "Making {topics} simple and enjoyable.",
    "Reviews, tutorials, and honest experiences with {topics}.",
    "Weekly deep dives into {topics}, minus the filler.",
    "Answering the {topics} questions people actually ask.",
    "Documenting what {topics} looks like in practice, week by week.",
    "{topics} explained properly, with the numbers where they matter.",
]

# Format-level content styles. Kept separate from topical tags on purpose: a
# creator's *subject* and their *format* are independent decisions, and a brief
# asking for "long-form explainers" should be matchable on format.
CONTENT_STYLES = [
    # (style, weight) - weights skew to the formats that actually dominate.
    ("Educational", 11), ("Tutorials", 10), ("Reviews", 9), ("Lifestyle", 8),
    ("Storytelling", 7), ("Vlogs", 6), ("Entertainment", 6),
    ("Long-form review", 5), ("Short-form tutorial", 5), ("Livestream", 4),
    ("Podcast clips", 4), ("Photo essay", 3), ("Duet / stitch", 3),
    ("Behind the scenes", 3), ("Comparison", 3), ("How-to walkthrough", 4),
    ("Unboxing", 3), ("Q&A", 2), ("Reaction", 2), ("Documentary", 2),
    ("Interview", 2), ("Weekly roundup", 3), ("Voiceover explainer", 2),
    ("Talking head", 3),
]

# (band, weight). Weighted rather than uniform: 25-34 and 18-24 carry most
# social audiences, and a flat distribution would make every age reason
# implausible.
AUDIENCE_AGES = [
    ("13-17", 4), ("18-24", 22), ("25-34", 26), ("35-44", 19),
    ("45-54", 12), ("55-64", 8), ("65+", 5),
    ("18-24 (skew)", 1), ("25-34 (skew)", 1), ("35-44 (skew)", 1),
    ("Mixed 18-44", 1), ("Mostly 45+", 1),
]

# (split, weight). Real audiences are not all near 50/50; the 45-55 band is the
# single most common, with a long tail either side.
AUDIENCE_GENDERS = [
    ("50% Female / 50% Male", 18), ("55% Female", 11), ("55% Male", 10),
    ("60% Female", 10), ("60% Male", 9), ("45% Female", 7), ("45% Male", 7),
    ("62% Female", 5), ("62% Male", 5), ("70% Female", 4), ("70% Male", 4),
    ("70% Female (skew)", 3), ("70% Male (skew)", 3), ("40% Female", 2),
    ("40% Male", 2), ("78% Female", 2), ("78% Male", 2),
]

# Growth is derived from reach and comment share rather than drawn
# independently, so a "declining" creator cannot also have great reach. See
# _plan_signals.
GROWTH_TRENDS = ["rising", "steady", "declining"]

# Above this reach ratio, organic reach stops being believable for a
# sponsored-heavy account.
_SPONSORED_REACH_CEILING = 0.5

# Countries whose audiences a creator might mostly be in, drawn to match the
# creator's own base country most of the time.
AUDIENCE_COUNTRIES = [
    "USA", "USA", "USA", "India", "UK", "Brazil", "Canada", "Australia",
    "Germany", "France", "Japan", "Mexico", "South Korea", "Spain",
    "Netherlands", "Sweden", "Indonesia", "Philippines", "Nigeria", "UAE",
    "South Africa", "Singapore", "Ireland", "New Zealand", "Poland",
    "Italy", "Turkey", "Thailand", "Vietnam", "Saudi Arabia",
]


def _tier_metrics(rng: random.Random) -> tuple[int, float]:
    tier = rng.choices(["nano", "micro", "macro", "mega"], weights=[45, 35, 15, 5])[0]
    ranges = {
        "nano": ((1_000, 10_000), (7.0, 12.0)), "micro": ((10_001, 100_000), (4.0, 8.0)),
        "macro": ((100_001, 1_000_000), (2.5, 5.0)), "mega": ((1_000_001, 5_000_000), (1.2, 3.0)),
    }
    follower_range, engagement_range = ranges[tier]
    return rng.randint(*follower_range), round(rng.uniform(*engagement_range), 1)


def _profile_metrics(rng: random.Random, followers: int, engagement: float) -> tuple[int, int, int]:
    """Average views, likes and comments, consistent with each other.

    Views are drawn log-uniformly rather than uniformly: most posts reach a
    small fraction of followers and a few go viral, so a flat distribution
    would make the median creator implausible. The multiplier is clamped to
    [views, 12 * views] so average_views can never be below average_likes,
    which would contradict the engagement rate computed from them.
    """
    likes = max(1, round(followers * engagement / 100))
    # exp(uniform(ln 0.03, ln 1.6)) - a right-skewed view count per follower.
    views = max(likes, round(followers * math.exp(rng.uniform(math.log(0.03), math.log(1.6)))))
    comments = min(likes, max(1, round(likes * rng.uniform(0.01, 0.12))))
    return views, likes, comments


def _draw_tags(rng: random.Random, focus: list[str] | None = None) -> list[str]:
    """Pick 4-8 distinct topic tags, optionally biased toward a focus group.

    A creator covering several topics is realistic and is what lets one
    creator satisfy briefs written in different vocabularies. `focus` seeds the
    draw from one TAG_GROUPS entry so the balanced generator can guarantee
    per-group coverage; the rest of the tags come from anywhere, which is where
    the cross-topic overlap comes from.
    """
    focus = focus or []
    tags: list[str] = []
    if focus:
        take = min(len(focus), rng.randint(2, 3))
        tags.extend(rng.sample(focus, k=take))
    remaining = [tag for tag in TOPIC_TAGS if tag not in tags]
    rng.shuffle(remaining)
    target = rng.randint(4, 8)
    tags.extend(remaining[: max(0, target - len(tags))])
    rng.shuffle(tags)
    return tags


def _draw_brand_pool(tags: list[str]) -> list[str]:
    """Brands a creator with these tags plausibly worked with.

    The pool is built from every topic group the creator's tags fall in, so a
    creator spanning fitness and travel can have worked with a sports brand
    and a travel one. `sorted` keeps the draw order independent of set
    iteration, which is what stops the pool (and therefore the collaboration
    list) from shifting between runs.
    """
    groups = sorted({GROUP_TAGS[tag] for tag in tags if tag in GROUP_TAGS})
    pool: list[str] = []
    for group in groups:
        pool.extend(BRAND_TAGS.get(group, []))
    if not pool:
        pool = list(ALL_BRANDS)
    # A creator can only have worked with one brand twice; duplicates would
    # make `brand_collaborations` read as filler.
    return sorted(set(pool))


@dataclass(frozen=True)
class _SignalPlan:
    """The signals that constrain other fields, decided before the row exists.

    Reach, growth and sponsorship all have to agree with each other, so they
    are decided together and the view count is then made to match. Deciding
    them after the fact and scaling the ratio would leave a row whose
    `reach_ratio` contradicts its own `average_views`.
    """

    growth_trend: str
    sponsored_ratio: float
    view_multiplier: float


def _plan_signals(
    rng: random.Random,
    followers: int,
    average_views: int,
    average_likes: int,
    average_comments: int,
) -> _SignalPlan:
    """Decide trend and sponsorship, then say how far views must move to agree.

    A reason may quote growth, reach and sponsorship at once, so drawing them
    independently would let the corpus assert a profile that contradicts
    itself. A rising creator has real reach, a declining one does not, and
    heavy sponsored work never comes with strong organic reach.
    """
    raw_reach = average_views / max(followers, 1)
    comment_share = average_comments / max(average_likes, 1)
    score = raw_reach + comment_share * 4

    # Thresholds are set so the corpus is mostly steady with real minorities
    # either side; a corpus where half the creators are "rising" would make
    # the label useless in a ranking reason.
    if score >= 0.85:
        trend = "rising"
    elif score < 0.3:
        trend = "declining"
    else:
        trend = "steady"

    # Most creator accounts are not primarily sponsored.
    sponsored = round(rng.uniform(0.3, 0.75) if rng.random() < 0.10 else rng.uniform(0.0, 0.3), 3)

    multiplier = 1.0
    if trend == "rising":
        multiplier = 1.25
    elif trend == "declining":
        multiplier = 0.5

    # Sponsored-heavy reach is bought, so organic reach is lower even when the
    # raw draw was strong. The ceiling is enforced here rather than by capping
    # the ratio later, so reach_ratio stays exactly views / followers.
    if sponsored > 0.3:
        # Aimed a little under the ceiling: integer views are rounded after the
        # multiplier, so landing exactly on it overshoots by a fraction.
        if raw_reach * multiplier > _SPONSORED_REACH_CEILING * 0.95:
            multiplier = (_SPONSORED_REACH_CEILING * 0.95) / raw_reach
        if trend == "rising":
            trend = "steady"
    return _SignalPlan(growth_trend=trend, sponsored_ratio=sponsored, view_multiplier=multiplier)


def _draw_signals(
    rng: random.Random,
    creator_id: int,
    country: str,
    tags: list[str],
    followers: int,
    reach_ratio: float,
    sponsored_ratio: float,
    growth_trend: str,
) -> CreatorSignals:
    """The inferred half of a profile. `reach_ratio` is passed in already
    consistent with the row's average_views."""
    audience_age = rng.choices(
        [band for band, _ in AUDIENCE_AGES],
        weights=[w for _, w in AUDIENCE_AGES],
    )[0]
    audience_gender = rng.choices(
        [split for split, _ in AUDIENCE_GENDERS],
        weights=[w for _, w in AUDIENCE_GENDERS],
    )[0]

    audience_country = country if rng.random() < 0.65 else rng.choice(AUDIENCE_COUNTRIES)
    # A short, ordered list rather than one country: brands targeting a region
    # need more than the headline number.
    top_countries = [audience_country]
    others = [c for c in AUDIENCE_COUNTRIES if c != audience_country]
    rng.shuffle(others)
    top_countries.extend(others[: rng.randint(1, 3)])

    brand_pool = _draw_brand_pool(tags)
    collaborations = rng.sample(brand_pool, k=min(len(brand_pool), rng.randint(0, 5)))
    collaborations.sort()

    # Synthetic distributions use the same account-level estimates as the
    # display fields. Keep them as shares so provider imports can replace these
    # maps without changing the canonical model.
    age_bands = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    dominant_age = next((band for band in age_bands if band in audience_age), "25-34")
    distribution_rng = random.Random(stable_seed((creator_id,), "audience-distributions"))
    age_weights = {band: distribution_rng.gammavariate(1.5, 1) for band in age_bands}
    age_weights[dominant_age] *= 4
    age_total = sum(age_weights.values())
    age_distribution = {band: round(value / age_total, 4) for band, value in age_weights.items()}

    female_pct = 50
    match = re.search(r"(\d+)%\s*Female", audience_gender, re.IGNORECASE)
    if match:
        female_pct = int(match.group(1))
    else:
        match = re.search(r"(\d+)%\s*Male", audience_gender, re.IGNORECASE)
        if match:
            female_pct = 100 - int(match.group(1))
    gender_distribution = {"female": female_pct / 100, "male": 1 - female_pct / 100}

    country_weights = [0.60] + [0.40 / max(len(top_countries) - 1, 1)] * (len(top_countries) - 1)
    country_distribution = dict(zip(top_countries, country_weights))
    primary_languages = LANGUAGES_BY_COUNTRY.get(audience_country, ["English"])
    language_distribution = {language: round(0.7 / len(primary_languages), 4) for language in primary_languages}
    language_distribution["Other"] = round(0.3, 4)

    return CreatorSignals(
        creator_id=creator_id,
        content_style=rng.choices(
            [style for style, _ in CONTENT_STYLES],
            weights=[w for _, w in CONTENT_STYLES],
        )[0],
        audience_age=audience_age,
        audience_gender=audience_gender,
        audience_country=audience_country,
        brand_collaborations=collaborations,
        reach_ratio=reach_ratio,
        sponsored_ratio=sponsored_ratio,
        growth_trend=growth_trend,
        audience_top_countries=top_countries,
        age_distribution=age_distribution,
        gender_distribution=gender_distribution,
        country_distribution=country_distribution,
        language_distribution=language_distribution,
    )


def _apply_reach(views: int, likes: int, multiplier: float) -> int:
    """Scale views toward the plan, never below what the like count implies.

    The floor matters: rounding can push a heavily scaled view count below the
    likes, and `average_views < average_likes` would contradict the engagement
    rate computed from those two numbers.
    """
    return max(round(views * multiplier), likes, 1)


def _create_creator(
    creator_id: int,
    key: tuple,
    platform: str,
    focus: list[str] | None = None,
    used_handles: set[str] | None = None,
) -> Influencer:
    """One creator, a pure function of (creator_id, key, platform, focus).

    `key` must be the slot key -- (seed, group, platform, slot). Everything
    drawn here comes from `key`, never from a shared stream, so this creator
    is byte-identical no matter how many creators are generated before it or
    what floor the balanced generator used.
    """
    rng = slot_rng(key)
    used_handles = used_handles if used_handles is not None else set()

    tags = _draw_tags(rng, focus)
    followers, engagement = _tier_metrics(rng)
    views, likes, comments = _profile_metrics(rng, followers, engagement)
    # Trend and sponsorship constrain each other, so they are decided before
    # the view count is fixed and views are then made to match them. Scaling
    # the ratio afterwards would leave a row whose reach_ratio contradicted
    # its own average_views.
    plan = _plan_signals(rng, followers, views, likes, comments)
    views = _apply_reach(views, likes, plan.view_multiplier)
    reach_ratio = views / max(followers, 1)
    city = rng.choice(list(CITY_COUNTRY))
    country = CITY_COUNTRY[city]

    # The name is drawn first because the handle is derived from it. Handles
    # are unique per platform+handle, matching creator_key; a collision bumps
    # a sub-salt derived from the slot key, so it never touches another
    # creator's stream.
    locale = LOCALE_BY_COUNTRY.get(country, "en_US")
    name = slot_faker(key + ("name",), locale).name()

    handle = ""
    for attempt in range(_MAX_HANDLE_ATTEMPTS):
        handle = _derive_handle(name, tags, stable_seed(key, "handle", attempt))
        if handle and handle not in used_handles:
            break
    else:
        # Extremely unlikely at corpus sizes the free tier supports; a salted
        # fallback keeps the function total rather than raising mid-index.
        handle = f"@creator{creator_id}_{_stable_suffix(key)}"
    used_handles.add(handle)
    signals = _draw_signals(
        rng, creator_id, country, tags, followers,
        reach_ratio, plan.sponsored_ratio, plan.growth_trend,
    )
    identity_key = f"synthetic:{key[0]}:{key[1]}:{key[3]}"
    identity_id = stable_seed(identity_key) & ((1 << 63) - 1) or 1
    identity_name = slot_faker((key[0], key[1], key[3], "identity"), "en_US").name()
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=stable_seed(key, "observed-at") % 270
    )
    source_record = CreatorSourceRecord(
        provider="synthetic",
        external_account_id=f"synthetic-{creator_id}",
        profile_url=f"https://social.example/{platform.lower()}/{handle.lstrip('@')}",
        observed_at=observed_at,
        raw_payload={"generator": "seeded", "slot": str(key[3])},
    )
    # The lead tags give the bio a readable subject without reintroducing a
    # taxonomy label.
    lead = ", ".join(tags[:3])

    return Influencer(
        id=creator_id, name=name, handle=handle,
        platform=platform, city=city, country=country,
        language=rng.choice(LANGUAGES_BY_COUNTRY.get(country, ["English"])),
        followers=followers, engagement=engagement, average_views=views, average_likes=likes,
        average_comments=comments, verified=followers >= 500_000 and rng.random() < 0.4,
        posts_per_week=rng.randint(1, 21), account_age_years=rng.randint(1, 14),
        tags=tags,
        bio=f"{name}. {rng.choice(BIOS).format(topics=lead)} Based in {city}, {country}.",
        content_style=signals.content_style,
        audience_age=signals.audience_age,
        audience_gender=signals.audience_gender,
        audience_country=signals.audience_country,
        brand_collaborations=list(signals.brand_collaborations),
        reach_ratio=signals.reach_ratio,
        sponsored_ratio=signals.sponsored_ratio,
        growth_trend=signals.growth_trend,
        audience_top_countries=list(signals.audience_top_countries),
        audience_age_distribution=dict(signals.age_distribution),
        audience_gender_distribution=dict(signals.gender_distribution),
        audience_country_distribution=dict(signals.country_distribution),
        audience_language_distribution=dict(signals.language_distribution),
        identity_id=identity_id, identity_key=identity_key,
        identity_name=identity_name, profile_url=source_record.profile_url,
        source_records=[source_record],
    )


_MAX_HANDLE_ATTEMPTS = 24

# Real handles are short. Longest platform limit in common use is 30.
_HANDLE_MAX_LEN = 30
# A topic suffix longer than this reads as a sentence, not a handle.
_TAG_SUFFIX_MAX_LEN = 12


def _name_parts(name: str) -> tuple[str, str | None]:
    """(first, last) of an ASCII-folded display name, lowercased.

    Single-word names get a `None` surname, which the pattern list handles
    separately rather than inventing one.
    """
    bits = [bit for bit in re.split(r"[^A-Za-z]+", ascii_fold(name)) if bit]
    if not bits:
        return "", None
    first = bits[0].lower()
    last = bits[-1].lower() if len(bits) > 1 else None
    return first, last


def _tag_slug(tags: list[str], seed: int) -> str:
    """One of the creator's own tags, slugified for use as a handle suffix.

    Drawing from the creator's tags rather than a fixed vocabulary is what
    makes `@jodyburns.science` mean something: the suffix is a topic this
    creator actually covers. Long tags are truncated so the handle stays
    within `_HANDLE_MAX_LEN`.
    """
    candidates = []
    for tag in tags:
        slug = re.sub(r"[^a-z0-9]+", "", ascii_fold(tag).lower())
        if slug:
            candidates.append(slug[:_TAG_SUFFIX_MAX_LEN])
    if not candidates:
        return ""
    return candidates[seed % len(candidates)]


def _handle_patterns(first: str, last: str | None, topic: str, seed: int) -> list[str]:
    """Handle shapes in the order real creators tend to use them.

    Every pattern contains the first or last name. A name-based handle is what
    a person whose brand *is* them would pick, and it is the thing a reviewer
    checks first when scrolling synthetic data.
    """
    number = seed % 97 + 3
    if not last:
        # Mononyms (Kim Min-jun, as generated for ko_KR) have no surname to
        # work with, so the patterns degrade rather than duplicating a name.
        options = [first, f"{first}{number}"]
        if topic:
            options += [f"{first}.{topic}", f"{topic}{first}", f"{first}_{topic}"]
        return options
    options = [
        f"{first}{last}",
        f"{first}.{last}",
        f"{first}_{last}",
        f"{first[0]}.{last}",
        f"{first}{last}{number}",
    ]
    if topic:
        options += [f"{first}{last}.{topic}", f"{topic}{first}", f"{first}.{last}{number}"]
    else:
        options += [f"{first}.{last}{number}", f"{first[0]}{last}{number}"]
    return options


def _derive_handle(name: str, tags: list[str], seed: int) -> str:
    """A handle derived from the creator's own name and topics.

    Deterministic in `seed` (a stable hash of the slot key), so it survives a
    cache miss, a reindex, and a different corpus size.
    """
    first, last = _name_parts(name)
    if not first:
        return ""
    topic = _tag_slug(tags, seed >> 8)
    options = _handle_patterns(first, last, topic, seed)
    handle = options[seed % len(options)]
    if len(handle) > _HANDLE_MAX_LEN - 1:
        # The budget is for the whole handle, and every handle carries an "@".
        handle = handle[:_HANDLE_MAX_LEN - 1].rstrip("._")
    return f"@{handle}"


def _stable_suffix(key: tuple) -> str:
    return hashlib.sha256("|".join(str(p) for p in key).encode("utf-8")).hexdigest()[:6]


def _slot_plan(count: int, floor: int) -> list[tuple[str, str, int]]:
    """The (group, platform, slot) cells to fill, in a stable order.

    Ordered by (slot, group, platform) -- one creator per cell at a time,
    round by round -- and *that* ordering is what makes ids stable. Sorting by
    (group, platform, slot) instead would group all of a cell's creators
    together, so raising the floor would insert new creators into the middle of
    the list and renumber everything after it. Round-robin keeps the plan for
    any floor a prefix of the plan for a higher one, so raising the floor only
    appends.
    """
    groups = list(TAG_GROUPS)
    platforms = list(PLATFORMS)
    plan = [
        (group, platform, slot)
        for slot in range(floor)
        for group in groups
        for platform in platforms
    ]
    return plan


def generate_influencers(count: int = 60, seed: int = 42) -> list[Influencer]:
    """Generate reproducible, internally consistent fake creator profiles.

    No balance guarantee: cells are filled round-robin across groups and
    platforms so the corpus still covers the vocabulary, but a platform can end
    up thin. Use `generate_balanced_influencers` when a floor matters.
    """
    groups = list(TAG_GROUPS)
    platforms = list(PLATFORMS)
    used: set[str] = set()
    creators: list[Influencer] = []
    for creator_id in range(count):
        group = groups[creator_id % len(groups)]
        platform = platforms[(creator_id // len(groups)) % len(platforms)]
        key = (seed, group, platform, creator_id)
        creators.append(_create_creator(
            creator_id, key, platform, TAG_GROUPS[group], used_handles=used
        ))
    return creators


def generate_balanced_influencers(
    count: int = 60,
    seed: int = 42,
    min_per_group_platform: int = 3,
) -> list[Influencer]:
    """Generate influencers with balanced topic-group x platform coverage.

    With no niche label, the coverage unit is a TAG_GROUPS entry: 10 groups
    x 9 platforms = 90 cells, so the minimum viable count is
    len(TAG_GROUPS) * len(PLATFORMS) * min_per_group_platform. The floor
    matters because a platform-filtered query can only return as many on-topic
    creators as its cell holds, which caps precision@k.

    A creator is never limited to its group: `_draw_tags` takes 2-3 tags from
    the focus group and fills the rest from the whole vocabulary, so pools
    overlap and cross-topic briefs can still find someone.

    Every creator is a pure function of its slot key, so raising the floor
    adds creators without rewriting the existing ones -- which is what keeps
    the embedding cache usable across reindex runs.
    """
    groups = list(TAG_GROUPS)
    platforms = list(PLATFORMS)
    total_combos = len(groups) * len(platforms)
    min_total = min_per_group_platform * total_combos

    if count < min_total:
        raise ValueError(
            f"count={count} too small for balanced generation. "
            f"Minimum required: {min_total} ({min_per_group_platform} per {total_combos} combos)"
        )

    plan = _extend_plan(
        _slot_plan(count, min_per_group_platform),
        count, groups, platforms,
    )

    used: set[str] = set()
    return [
        _create_creator(
            creator_id,
            (seed, group, platform, slot),
            platform,
            TAG_GROUPS[group],
            used_handles=used,
        )
        for creator_id, (group, platform, slot) in enumerate(plan)
    ]


def _extend_plan(
    plan: list[tuple[str, str, int]],
    count: int,
    groups: list[str],
    platforms: list[str],
) -> list[tuple[str, str, int]]:
    """Grow the slot plan to `count` by filling the emptiest cells in turn.

    Cell occupancy is computed from the plan itself, so adding a creator never
    changes an earlier cell's slot numbering.
    """
    counts: dict[tuple[str, str], int] = {}
    next_slot: dict[tuple[str, str], int] = {}
    for group, platform, slot in plan:
        cell = (group, platform)
        counts[cell] = counts.get(cell, 0) + 1
        next_slot[cell] = max(next_slot.get(cell, -1), slot) + 1
    cells = [(g, p) for g in groups for p in platforms]
    while len(plan) < count:
        # Deterministic tie-break on the cell name: no rng, so which cell gets
        # the next slot depends only on occupancy, never on call order.
        cell = min(cells, key=lambda c: (counts.get(c, 0), c))
        counts[cell] = counts.get(cell, 0) + 1
        plan.append((cell[0], cell[1], next_slot.get(cell, 0)))
        next_slot[cell] = next_slot.get(cell, 0) + 1
    return plan
