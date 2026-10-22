"""Seeded Faker company profiles for development, demos, and retrieval evaluation.

Mirrors `data_generator`'s contract, because a second corpus has to satisfy the
same one to be measurable:

  Every record is a pure function of its slot key `(seed, group, size_tier,
  slot)`. Each one draws from its own `random.Random` seeded with that key and
  its own Faker instance seeded from the same key, so nothing depends on how many
  records were generated before it.

This is not tidiness. With one shared random stream, a company's values depended on
its position in the emit order, and the emit order depended on the plan shape --
raising the coverage floor rewrote the corpus. Since `Prospect.corpus_text` is
the embedding cache key, that re-bills every vector, and embedding is the
expensive step. The determinism tests in tests/test_prospect_generator.py pin the
behaviour that makes --count and --min-per-cell safe to change.

THE BALANCE UNIT IS INDUSTRY x SIZE TIER, which is the prospect-side analogue of
balancing creators over tag-group x platform. Creators balance on `platform`
because it is a hard filter, so a filtered query can only return as many on-topic
rows as its cell holds. Prospects have no such filter -- industry is judged, not
constrained -- but "we sell to 50-200 employee companies" is just as real a
brief, and headcount is stated on the row, so a tier with too few companies
pool-limits that brief the same way. Balancing on the facet people actually
brief against is what stops the retrieval evaluation from measuring emptiness.

Calendar independence: `founded_year` is an absolute year, so the corpus is
anchored to NEWEST_FOUNDED_YEAR rather than to `date.today()`. A generator that
read the current date would produce a different corpus every January, which
silently invalidates every cached vector on the same schedule as a deploy.
"""

import random
from datetime import datetime, timedelta, timezone

from .corpora import (
    CompanyFundingRound, CompanySourceRecord, PROSPECT_VERTICALS, Prospect,
)
from .slotting import ascii_fold, slot_faker, slot_rng, stable_seed

#: The most recent founding year this corpus can produce. Fixed, not derived
#: from the clock -- see the module docstring.
NEWEST_FOUNDED_YEAR = 2023
OLDEST_FOUNDED_YEAR = 1996

#: Company size bands. The band is chosen first and headcount drawn inside it, so
#: headcount and every tier-derived signal agree by construction.
SIZE_TIERS: dict[str, tuple[int, int]] = {
    "micro": (2, 10),
    "small": (11, 50),
    "mid": (51, 200),
    "upper_mid": (201, 1_000),
    "mid_market": (1_001, 5_000),
    "enterprise": (5_001, 40_000),
}

#: Relative headcount growth per year, by tier. Bigger companies grow slower in
#: percentage terms, so the band narrows and drops as headcount rises. Without
#: this the corpus asserts things nobody believes -- a 30,000-person company
#: compounding at 40% a year.
GROWTH_BANDS: dict[str, tuple[float, float]] = {
    "micro": (0.20, 0.60),
    "small": (0.14, 0.42),
    "mid": (0.09, 0.30),
    "upper_mid": (0.05, 0.20),
    "mid_market": (0.02, 0.12),
    "enterprise": (0.005, 0.07),
}

#: Share of open roles that are growth or sales, by trend. A rising company is
#: hiring into its growth; a shrinking one is not hiring at all. This is the
#: prospect analogue of sponsored_ratio and must agree with growth_trend.
HIRING_BANDS: dict[str, tuple[float, float]] = {
    "rising": (0.34, 0.78),
    "steady": (0.10, 0.40),
    "declining": (0.0, 0.14),
}

#: How likely each trend is, by tier. Startups skew rising, large incumbents skew
#: steady, and the biggest skew declining -- otherwise "rising" stops being
#: informative in a ranking reason, which is the failure mode the creator corpus
#: documents for its own growth_trend thresholds.
TREND_WEIGHTS: dict[str, dict[str, float]] = {
    "micro": {"rising": 0.50, "steady": 0.32, "declining": 0.18},
    "small": {"rising": 0.44, "steady": 0.36, "declining": 0.20},
    "mid": {"rising": 0.36, "steady": 0.40, "declining": 0.24},
    "upper_mid": {"rising": 0.28, "steady": 0.46, "declining": 0.26},
    "mid_market": {"rising": 0.20, "steady": 0.50, "declining": 0.30},
    "enterprise": {"rising": 0.14, "steady": 0.52, "declining": 0.34},
}

#: Tier draw weights. Real company distributions are heavily bottom-heavy, so the
#: micro and small bands hold most of the corpus and the large bands are
#: deliberately thin -- but balanced generation guarantees each one exists.
TIER_WEIGHTS: dict[str, float] = {
    "micro": 0.30, "small": 0.28, "mid": 0.20,
    "upper_mid": 0.13, "mid_market": 0.06, "enterprise": 0.03,
}

SENIORITY_MIXES = [
    "junior-heavy", "early-career-weighted", "mid-weighted",
    "senior-weighted", "leadership-heavy",
]

DEPARTMENTS = [
    "engineering", "sales", "marketing", "customer success", "product",
    "operations", "finance", "people", "data", "support",
]

#: Department mixes that a real company of a given tier would plausibly have.
#: A two-person company does not have a finance department; an enterprise does
#: not have only engineering. Keyed by tier so the mix and the size agree.
DEPARTMENT_MIXES: dict[str, list[list[str]]] = {
    "micro": [["engineering", "operations"], ["engineering", "sales"],
              ["product", "engineering"], ["sales", "customer success"]],
    "small": [["engineering", "sales", "marketing"], ["product", "engineering", "support"],
              ["sales", "customer success", "operations"]],
    "mid": [["engineering", "sales", "marketing", "product"],
            ["engineering", "customer success", "data", "finance"],
            ["product", "marketing", "operations", "people"]],
    "upper_mid": [["engineering", "sales", "product", "customer success", "data"],
                  ["product", "engineering", "marketing", "finance", "support"],
                  ["sales", "marketing", "operations", "people", "customer success"]],
    "mid_market": [["engineering", "sales", "product", "marketing", "finance", "operations"],
                   ["sales", "customer success", "product", "data", "support", "people"]],
    "enterprise": [["engineering", "sales", "product", "marketing", "finance", "operations",
                    "customer success", "people"],
                   ["product", "engineering", "data", "support", "sales", "marketing",
                    "finance", "operations"]],
}

FUNDING_STAGES = ["bootstrapped", "seed", "Series A", "Series B", "Series C", "public"]

#: The vertical each group belongs to, with the industries, topic tags, tools and
#: buying signals that belong to it. Keeping a group's four pools together is what
#: stops a company from being a fintech with a bakery's toolchain.
INDUSTRY_GROUPS: dict[str, dict[str, object]] = {
    "b2b_saas": {
        "industries": list(PROSPECT_VERTICALS["b2b_saas"]),
        "tags": ["saas", "workflow", "automation", "analytics", "integration",
                 "productivity", "api", "reporting"],
        "tech_stacks": [
            ["Salesforce", "HubSpot", "Slack", "Snowflake"],
            ["Jira", "GitHub", "Datadog", "Segment"],
            ["HubSpot", "Zendesk", "Stripe", "Looker"],
        ],
        "buying_signals": ["wants CRM migration", "hiring a sales team",
                          "scaling onboarding", "consolidating tools",
                          "needs analytics", "multi-region rollout"],
    },
    "fintech": {
        "industries": list(PROSPECT_VERTICALS["fintech"]),
        "tags": ["payments", "banking", "accounting", "compliance", "invoicing",
                 "treasury", "lending", "fraud"],
        "tech_stacks": [
            ["Stripe", "NetSuite", "Salesforce", "Snowflake"],
            ["Plaid", "Snowflake", "dbt", "Looker"],
            ["Chargebee", "NetSuite", "Segment", "Intercom"],
        ],
        "buying_signals": ["needs SOC 2", "expanding into new markets",
                          "wants real-time reconciliation", "hiring compliance",
                          "raising a Series B", "migrating ledgers"],
    },
    "healthtech": {
        "industries": list(PROSPECT_VERTICALS["healthtech"]),
        "tags": ["clinical", "health", "devices", "compliance", "telehealth",
                 "ehr", "diagnostics", "care"],
        "tech_stacks": [
            ["Epic", "Salesforce Health Cloud", "Snowflake", "Intercom"],
            ["Cerner", "Tableau", "Zendesk", "ServiceNow"],
            ["Epic", "Miro", "Looker", "Okta"],
        ],
        "buying_signals": ["needs HIPAA compliance", "expanding clinical trials",
                          "hiring regulatory staff", "wants patient analytics",
                          "integrating with an EHR", "hospital procurement cycle"],
    },
    "ecommerce": {
        "industries": list(PROSPECT_VERTICALS["ecommerce"]),
        "tags": ["ecommerce", "retail", "consumer", "dtc", "merchandising",
                 "fulfilment", "subscriptions", "marketplace"],
        "tech_stacks": [
            ["Shopify", "Klaviyo", "Stripe", "Gorgias"],
            ["Shopify Plus", "NetSuite", "Looker", "Attentive"],
            ["Amazon Seller Central", "ShipBob", "Stripe", "Segment"],
        ],
        "buying_signals": ["wants to cut CAC", "opening a new warehouse",
                          "launching subscriptions", "migrating platforms",
                          "international expansion", "seasonal peak headcount"],
    },
    "logistics": {
        "industries": list(PROSPECT_VERTICALS["logistics"]),
        "tags": ["logistics", "supply chain", "freight", "fleet", "warehouse",
                 "routing", "customs", "last mile"],
        "tech_stacks": [
            ["Oracle TMS", "SAP", "Snowflake", "Looker"],
            ["project44", "SAP", "Power BI", "ServiceNow"],
            ["Flexport", "NetSuite", "Tableau", "Slack"],
        ],
        "buying_signals": ["needs route optimisation", "consolidating carriers",
                          "cross-border customs", "expanding fleet",
                          "wants real-time tracking", "warehouse automation"],
    },
    "construction": {
        "industries": list(PROSPECT_VERTICALS["construction"]),
        "tags": ["construction", "real estate", "property", "contractors",
                 "building", "permits", "project management", "field"],
        "tech_stacks": [
            ["Procore", "Sage", "Power BI", "Microsoft 365"],
            ["Procore", "QuickBooks", "Tableau", "Okta"],
            ["Yardi", "Procore", "Salesforce", "ServiceNow"],
        ],
        "buying_signals": ["digitising field ops", "multi-project rollout",
                          "wants compliance reporting", "hiring project managers",
                          "consolidating subcontractors", "post-acquisition integration"],
    },
    "professional_services": {
        "industries": list(PROSPECT_VERTICALS["professional_services"]),
        "tags": ["consulting", "legal", "accounting", "advisory", "compliance",
                 "billing", "professional services", "audit"],
        "tech_stacks": [
            ["Microsoft 365", "Salesforce", "QuickBooks", "Tableau"],
            ["Clio", "Microsoft 365", "NetSuite", "Power BI"],
            ["Salesforce", "Vanta", "DocuSign", "Looker"],
        ],
        "buying_signals": ["wants document automation", "scaling advisory",
                          "needs audit trail", "hiring billers",
                          "moving to the cloud", "multi-practice rollup"],
    },
    "edtech": {
        "industries": list(PROSPECT_VERTICALS["edtech"]),
        "tags": ["education", "training", "learning", "courses", "assessment",
                 "lms", "cohorts", "certification"],
        "tech_stacks": [
            ["Canvas", "HubSpot", "Stripe", "Looker"],
            ["Docebo", "Salesforce", "Tableau", "Intercom"],
            ["Moodle", "Workday", "Snowflake", "Slack"],
        ],
        "buying_signals": ["selling to enterprise learners", "content localisation",
                          "wants completion analytics", "acquiring courses",
                          "adding certification tracks", "seasonal enrolment"],
    },
}

#: Countries and their largest adjacent export markets. `top_markets` always
#: contains the company's own country, the same way `audience_top_countries`
#: contains the creator's own -- a home market is a fact, not an insight.
MARKETS_BY_COUNTRY: dict[str, list[str]] = {
    "Germany": ["Germany", "Austria", "Switzerland", "Netherlands"],
    "France": ["France", "Belgium", "Senegal", "Canada"],
    "United Kingdom": ["United Kingdom", "Ireland", "Australia", "United States"],
    "United States": ["United States", "Canada", "United Kingdom", "Mexico"],
    "Canada": ["Canada", "United States", "United Kingdom"],
    "Netherlands": ["Netherlands", "Belgium", "Germany", "United Kingdom"],
    "Spain": ["Spain", "Portugal", "France", "Germany"],
    "Italy": ["Italy", "Spain", "France", "Germany"],
    "Sweden": ["Sweden", "Norway", "Denmark", "Finland"],
    "Poland": ["Poland", "Germany", "Czechia", "United Kingdom"],
    "Brazil": ["Brazil", "Portugal", "Argentina", "United States"],
    "India": ["India", "United Kingdom", "United Arab Emirates", "Singapore"],
    "Singapore": ["Singapore", "Malaysia", "Indonesia", "Australia"],
    "Australia": ["Australia", "New Zealand", "United Kingdom", "Singapore"],
    "Japan": ["Japan", "South Korea", "Taiwan", "Singapore"],
}

COUNTRIES = list(MARKETS_BY_COUNTRY)

CITIES_BY_COUNTRY: dict[str, list[str]] = {
    "Germany": ["Berlin", "Munich", "Hamburg", "Cologne", "Frankfurt"],
    "France": ["Paris", "Lyon", "Toulouse", "Nantes"],
    "United Kingdom": ["London", "Manchester", "Bristol", "Edinburgh"],
    "United States": ["New York", "Austin", "Chicago", "San Francisco", "Denver"],
    "Canada": ["Toronto", "Vancouver", "Montreal"],
    "Netherlands": ["Amsterdam", "Rotterdam", "Utrecht"],
    "Spain": ["Madrid", "Barcelona", "Valencia"],
    "Italy": ["Milan", "Rome", "Bologna"],
    "Sweden": ["Stockholm", "Gothenburg", "Malmo"],
    "Poland": ["Warsaw", "Krakow", "Wroclaw"],
    "Brazil": ["Sao Paulo", "Rio de Janeiro", "Florianopolis"],
    "India": ["Bangalore", "Mumbai", "Delhi", "Pune"],
    "Singapore": ["Singapore"],
    "Australia": ["Sydney", "Melbourne", "Brisbane"],
    "Japan": ["Tokyo", "Osaka", "Kyoto"],
}

DESCRIPTIONS = [
    "{name} builds {industry} tools for {who}.",
    "{name} is a {industry} company working with {who}.",
    "{name} helps {who} with {industry}, based in {city}.",
    "{name} provides {industry} software to {who} across {markets}.",
]


class _ProspectSignalPlan:
    """The signals that constrain each other, decided before the row exists.

    Headcount, growth trend, growth rate, hiring intensity and funding stage all
    have to agree with one another, so they are decided together and the row is
    built from the plan. Drawing them independently would let the corpus assert a
    company that is simultaneously shrinking and hiring, or a seed-stage company
    founded after its Series C.

    Growth rate is DERIVED from the tier band and the trend's sign rather than
    drawn free. That is the same reason migration 007 recomputes reach_ratio from
    average_views / followers instead of storing a source figure: a reader who
    divides the two numbers must not be able to catch the row contradicting
    itself.
    """

    __slots__ = ("tier", "headcount", "trend", "growth_rate", "hiring_intensity",
                 "founded_year", "funding_stage")

    def __init__(self, tier, headcount, trend, growth_rate, hiring_intensity,
                 founded_year, funding_stage):
        self.tier = tier
        self.headcount = headcount
        self.trend = trend
        self.growth_rate = growth_rate
        self.hiring_intensity = hiring_intensity
        self.founded_year = founded_year
        self.funding_stage = funding_stage


def _weighted_choice(rng: random.Random, weights: dict) -> object:
    """One key of `weights`, chosen with probability proportional to its value."""
    roll = rng.random() * sum(weights.values())
    cumulative = 0.0
    for key, weight in weights.items():
        cumulative += weight
        if roll < cumulative:
            return key
    return next(reversed(weights))


def _plan_signals(rng: random.Random, tier: str) -> _ProspectSignalPlan:
    """Decide size, trend, growth, hiring and vintage together.

    Age is derived from the tier and the trend rather than drawn, so the funding
    stage it implies cannot contradict the founding year. A company founded last
    year is a pre-seed or bootstrapped shop; one founded in the 1990s may have
    raised all the way up or never raised at all.
    """
    low, high = SIZE_TIERS[tier]
    headcount = rng.randint(low, high)

    trend = _weighted_choice(rng, TREND_WEIGHTS[tier])

    # Sign from the trend, magnitude from the tier. This is the coherence that
    # makes a 30,000-person company never claim 40% growth.
    low_growth, high_growth = GROWTH_BANDS[tier]
    magnitude = rng.uniform(low_growth, high_growth)
    if trend == "rising":
        growth_rate = magnitude
    elif trend == "declining":
        growth_rate = -magnitude
    else:
        # Steady is near-flat BY CONSTRUCTION, not a slice of the tier's band.
        # Scaling the band by a small factor looked reasonable and was not: a
        # micro company's band is up to 60%, so a quarter of it put "steady" at
        # -15%, which is a decline wearing the wrong label. Capped at 5% so the
        # three labels stay distinguishable.
        flat_band = min(0.05, high_growth)
        growth_rate = rng.uniform(-flat_band, flat_band)

    hiring_low, hiring_high = HIRING_BANDS[trend]
    hiring_intensity = round(rng.uniform(hiring_low, hiring_high), 3)

    if trend == "declining":
        age = rng.randint(6, 27)
    elif tier in {"micro", "small"}:
        age = rng.randint(1, 9)
    elif tier == "mid":
        age = rng.randint(2, 16)
    else:
        age = rng.randint(4, 27)
    founded_year = max(OLDEST_FOUNDED_YEAR, NEWEST_FOUNDED_YEAR - age)

    stage = _funding_stage(age, headcount, trend, rng)
    return _ProspectSignalPlan(
        tier=tier, headcount=headcount, trend=trend,
        growth_rate=round(growth_rate, 3), hiring_intensity=hiring_intensity,
        founded_year=founded_year, funding_stage=stage,
    )


def _funding_stage(age: int, headcount: int, trend: str, rng: random.Random) -> str:
    """A funding stage the age and headcount can support.

    A declining company is rarely well-capitalised and a two-person one has not
    raised a Series B, so both ends are clamped before the draw.
    """
    if trend == "declining":
        options = ["bootstrapped", "bootstrapped", "seed", "Series A"]
    elif headcount < 11:
        options = ["bootstrapped", "seed", "seed"]
    elif headcount < 51:
        options = ["seed", "Series A", "Series A"]
    elif headcount < 201:
        options = ["Series A", "Series A", "Series B"]
    elif headcount < 1_001:
        options = ["Series B", "Series B", "Series C"]
    else:
        options = ["Series B", "Series C", "Series C", "public"]

    # Age caps how far a company can have got: nothing founded last year is
    # public. Truncate rather than re-draw so the cap cannot be silently ignored.
    if age < 5:
        options = [s for s in options if FUNDING_STAGES.index(s) <= FUNDING_STAGES.index("Series A")]
    if age < 10:
        options = [s for s in options if FUNDING_STAGES.index(s) <= FUNDING_STAGES.index("Series B")]
    return rng.choice(options or ["bootstrapped"])


def _seniority_mix(rng: random.Random, headcount: int) -> str:
    """Seniority skew by size. Big companies are not junior-heavy however the
    dice fall, and a ten-person shop is usually the opposite."""
    if headcount < 51:
        return rng.choice(["junior-heavy", "junior-heavy", "early-career-weighted", "mid-weighted"])
    if headcount < 1_001:
        return rng.choice(["early-career-weighted", "mid-weighted", "mid-weighted", "senior-weighted"])
    return rng.choice(["mid-weighted", "mid-weighted", "senior-weighted", "leadership-heavy"])


def _stable_suffix(key: tuple) -> str:
    """A short stable disambiguator, for names Faker repeats."""
    import hashlib

    return hashlib.sha256("|".join(str(p) for p in key).encode("utf-8")).hexdigest()[:3].upper()


def _derive_name(fake, key: tuple, group: str, used: set[str]) -> str:
    """A company name, with a stable suffix only when the plain one is taken.

    Appending unconditionally would make every name carry noise; appending
    never would let a collision silently drop a company.
    """
    base = ascii_fold(fake.company())
    if base not in used:
        used.add(base)
        return base
    candidate = f"{base} {stable_seed(key, group, 'name') % 90 + 10}"
    while candidate in used:
        candidate = f"{base} {_stable_suffix(key + (len(used),))}"
    used.add(candidate)
    return candidate


def _create_prospect(
    prospect_id: int,
    key: tuple,
    tier: str,
    group: str,
    slot: int,
    used_names: set[str],
) -> Prospect:
    rng = slot_rng(key)
    vocab: dict = INDUSTRY_GROUPS[group]
    fake = slot_faker(key, "en_US")

    plan = _plan_signals(rng, tier)
    country = rng.choice(COUNTRIES)
    city = rng.choice(CITIES_BY_COUNTRY[country])
    # Rotated by slot, NOT drawn. A cell holds `floor` records and a group has
    # three industries, so a random draw leaves most (industry, tier) pairs
    # unpopulated -- 25 of 144 at floor 3 -- and a brief naming one of them
    # retrieves nothing. Rotating makes every industry present in every tier
    # whenever the floor is at least the number of industries in a group, and it
    # is still a pure function of the slot key.
    industries = vocab["industries"]
    industry = industries[slot % len(industries)]
    tags = rng.sample(vocab["tags"], 3)
    tech_stack = list(rng.choice(vocab["tech_stacks"]))
    buying_signals = rng.sample(vocab["buying_signals"], 2)
    seniority_mix = _seniority_mix(rng, plan.headcount)
    department_mix = list(rng.choice(DEPARTMENT_MIXES[plan.tier]))
    # Always sell where you are; then add adjacent markets.
    others = [m for m in MARKETS_BY_COUNTRY[country] if m != country]
    rng.shuffle(others)
    top_markets = [country, *others[: rng.randint(1, 2)]]

    name = _derive_name(fake, key, group, used_names)
    description = rng.choice(DESCRIPTIONS).format(
        name=name, industry=industry.lower(), city=city,
        who=", ".join(tags[:2]),
        markets=", ".join(top_markets[1:]) or top_markets[0],
    )
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=stable_seed(key, "observed-at") % 270
    )
    source_record = CompanySourceRecord(
        provider="synthetic",
        external_company_id=f"synthetic-{prospect_id}",
        profile_url=f"https://companies.example/{ascii_fold(name).lower().replace(' ', '-')}",
        observed_at=observed_at,
        raw_payload={"generator": "seeded", "slot": str(slot)},
    )
    funding_rounds = []
    funded_stages = ["seed", "Series A", "Series B", "Series C", "public"]
    stage_ranges = {
        "seed": (500_000, 4_000_000), "series-a": (5_000_000, 25_000_000),
        "series-b": (20_000_000, 80_000_000), "series-c": (50_000_000, 200_000_000),
        "public": (100_000_000, 500_000_000),
    }
    if plan.funding_stage != "bootstrapped":
        last_stage = funded_stages.index(plan.funding_stage)
        for stage_index, stage in enumerate(funded_stages[:last_stage + 1]):
            stage_slug = ascii_fold(stage).lower().replace(' ', '-')
            low, high = stage_ranges[stage_slug]
            year_span = 2025 - plan.founded_year
            round_year = min(2025, plan.founded_year + max(1, round(year_span * (stage_index + 1) / (last_stage + 2))))
            month = min(12, 2 + stage_index * 3)
            funding_rounds.append(CompanyFundingRound(
                company_id=prospect_id, provider="synthetic",
                external_round_id=f"synthetic-{prospect_id}-{stage_slug}",
                round_type=stage,
                announced_at=datetime(round_year, month, 1, tzinfo=timezone.utc),
                amount=round(rng.uniform(low, high), 2), currency="USD",
                investors=["Synthetic Capital"],
                source_url=f"https://companies.example/{ascii_fold(name).lower().replace(' ', '-')}/funding",
                raw_payload={"generator": "seeded"},
            ))

    return Prospect(
        id=prospect_id,
        name=name,
        industry=industry,
        headcount=plan.headcount,
        city=city,
        country=country,
        description=description,
        tags=tags,
        website=f"https://www.{ascii_fold(name).lower().replace(' ', '')}.example",
        profile_url=source_record.profile_url,
        founded_year=plan.founded_year,
        funding_stage=plan.funding_stage,
        seniority_mix=seniority_mix,
        department_mix=department_mix,
        tech_stack=tech_stack,
        buying_signals=buying_signals,
        growth_trend=plan.trend,
        growth_rate=plan.growth_rate,
        hiring_intensity=plan.hiring_intensity,
        top_markets=top_markets,
        source_records=[source_record], funding_rounds=funding_rounds,
        observed_at=observed_at,
    )


def _slot_plan(count: int, floor: int) -> list[tuple[str, str, int]]:
    """The (group, size_tier, slot) cells to fill, in a stable order.

    Round-robin -- one record per cell at a time, round by round -- and that
    ordering is what makes ids stable. Sorting by cell instead would group a
    cell's records together, so raising the floor would renumber everything after
    it and invalidate every cached vector.
    """
    groups = list(INDUSTRY_GROUPS)
    tiers = list(SIZE_TIERS)
    return [
        (group, tier, slot)
        for slot in range(floor)
        for group in groups
        for tier in tiers
    ]


def _cell_rank() -> dict[tuple[str, str], int]:
    """Cells in the same order _slot_plan emits them.

    _extend_plan must break ties on occupancy using THIS order, not alphabetical.
    Sorting by name looks equivalent and is not: the tier names sort as
    enterprise, micro, mid, mid_market, small, upper_mid -- so an alphabetically
    ordered round starts at enterprise while a planned round starts at micro, and
    the two plans stop sharing a prefix. That is exactly the property the
    round-robin plan exists to provide.
    """
    return {
        (group, tier): index
        for index, (group, tier) in enumerate(
            (g, t) for g in INDUSTRY_GROUPS for t in SIZE_TIERS
        )
    }


def _extend_plan(plan: list[tuple[str, str, int]], count: int) -> list[tuple[str, str, int]]:
    """Grow the plan to `count`, filling the emptiest cells in turn.

    Occupancy is read from the plan itself, so adding a record never changes an
    earlier cell's slot numbering.
    """
    occupancy: dict[tuple[str, str], int] = {}
    next_slot: dict[tuple[str, str], int] = {}
    for group, tier, slot in plan:
        cell = (group, tier)
        occupancy[cell] = occupancy.get(cell, 0) + 1
        next_slot[cell] = max(next_slot.get(cell, -1), slot) + 1

    rank = _cell_rank()
    while len(plan) < count:
        cell = min(occupancy, key=lambda c: (occupancy[c], rank[c]))
        plan.append((cell[0], cell[1], next_slot[cell]))
        occupancy[cell] += 1
        next_slot[cell] += 1
    return plan[:count]


def generate_prospects(count: int = 60, seed: int = 42) -> list[Prospect]:
    """Generate `count` companies with no coverage guarantee."""
    rng = slot_rng((seed, "prospect", "unbalanced", count))
    tiers = list(SIZE_TIERS)
    groups = list(INDUSTRY_GROUPS)
    used: set[str] = set()
    prospects = []
    for index in range(count):
        key = (seed, "prospect", index)
        prospects.append(
            _create_prospect(
                index,
                key,
                rng.choice(tiers),
                rng.choice(groups),
                slot=index,
                used_names=used,
            )
        )
    return prospects


def generate_balanced_prospects(
    count: int = 216,
    min_per_cell: int = 3,
    seed: int = 42,
) -> list[Prospect]:
    """Generate companies with guaranteed coverage of industry x size tier.

    The floor matters for the same reason it does for creators: a brief that
    names a size band can only retrieve as many on-topic companies as that cell
    holds, which caps recall@k. A cell with two companies cannot return five.

    Every record is a pure function of its slot key, so raising the floor adds
    records without rewriting the existing ones -- which is what keeps the
    embedding cache usable across reindex runs.
    """
    groups = list(INDUSTRY_GROUPS)
    tiers = list(SIZE_TIERS)
    cells = len(groups) * len(tiers)
    min_total = min_per_cell * cells

    if count < min_total:
        raise ValueError(
            f"count={count} too small for balanced generation. Minimum required: "
            f"{min_total} ({min_per_cell} per {cells} industry x size cells)"
        )

    plan = _extend_plan(_slot_plan(count, min_per_cell), count)
    used: set[str] = set()
    return [
        _create_prospect(index, (seed, group, tier, slot), tier, group, slot, used_names=used)
        for index, (group, tier, slot) in enumerate(plan)
    ]
