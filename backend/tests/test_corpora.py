"""Tests for src.corpora: the creator corpus declaration.

`corpus_text` is the single source of truth for what a profile "says", and
changing it invalidates every cached vector, so its contract is pinned here
rather than alongside the query-side model in test_models.py.
"""

import pytest

from src.corpora import (
    CREATORS,
    KINDS,
    PROSPECTS,
    CreatorSignals,
    Influencer,
    Prospect,
    ProspectSignals,
    get_corpus,
)


def test_corpus_text_contains_profile_facts():
    inf = Influencer(
        id=1, handle="@fitpro", platform="TikTok",
        city="Austin", followers=1000, engagement=5.0,
        tags=["gym", "HIIT"], bio="Lifting daily.",
    )
    text = inf.corpus_text()
    for fragment in ("@fitpro", "TikTok", "Austin", "gym", "HIIT", "Lifting daily."):
        assert fragment in text


def test_corpus_text_carries_every_field_a_reason_may_cite():
    """A grounded reason quotes a stored field, so the field has to be in the
    text retrieval actually searched. Anything a reason could cite but
    corpus_text omits is a claim the model cannot check honestly."""
    from src.ranking import GROUNDABLE_FIELDS

    inf = Influencer(
        id=1, handle="@fitpro", platform="TikTok", city="Austin",
        country="USA", followers=1000, engagement=5.0,
        tags=["gym", "HIIT"], bio="Lifting daily.",
        content_style="Tutorials", audience_age="25-34",
        audience_gender="60% Female", audience_country="USA",
        brand_collaborations=["Nike", "Gymshark"],
    )
    text = inf.corpus_text()
    for field in GROUNDABLE_FIELDS:
        for value in GROUNDABLE_FIELDS[field](inf):
            assert str(value) in text, f"{field}={value!r} missing from corpus_text"


def test_corpus_text_omits_empty_optional_fields():
    """No 'Audience: ,' placeholders, which would only dilute the vector."""
    inf = Influencer(
        id=1, handle="@a", platform="TikTok", city="Austin",
        followers=1000, engagement=5.0, tags=["gym"], bio="Tips.",
    )
    text = inf.corpus_text()
    assert "Content style" not in text
    assert "Audience" not in text
    assert "Past brand partners" not in text


def test_signals_round_trip_off_the_searchable_row():
    """The signal row is a projection, not a second copy of the truth.

    `influencers` keeps only what a profile states; `CreatorSignals` is what a
    third party inferred about it. If signals() ever drifted from the row it
    would let a reason cite an inferred figure the corpus text never embedded.
    """
    inf = Influencer(
        id=7, handle="@a", platform="TikTok", city="Austin",
        followers=1000, engagement=5.0,
        content_style="Tutorials", audience_age="25-34",
        brand_collaborations=["Nike"], reach_ratio=0.42,
        sponsored_ratio=0.1, growth_trend="rising",
        audience_top_countries=["USA", "CAN"],
    )
    signals = inf.signals()
    assert isinstance(signals, CreatorSignals)
    assert signals.creator_id == inf.id
    assert signals.content_style == inf.content_style
    assert signals.brand_collaborations == ["Nike"]
    assert signals.reach_ratio == inf.reach_ratio
    assert signals.growth_trend == inf.growth_trend
    assert signals.audience_top_countries == ["USA", "CAN"]


def test_signals_copies_mutable_lists_rather_than_aliasing_them():
    """A signals row is handed to the DB writer, which may keep it. Aliasing the
    lists would let a later mutation of the record rewrite a stored row."""
    inf = Influencer(
        id=7, handle="@a", platform="TikTok", city="Austin",
        followers=1000, engagement=5.0, brand_collaborations=["Nike"],
    )
    signals = inf.signals()
    signals.brand_collaborations.append("Adidas")
    assert inf.brand_collaborations == ["Nike"]

def test_server_side_modules_do_not_import_faker():
    """`platforms` established that the API server imports from src without
    pulling faker into the process. corpora and slotting sit on the same path, so
    a module-scope faker import in either would drag it back in -- which is why
    slot_faker imports Faker inside the function."""
    import subprocess
    import sys

    probe = (
        "import sys; import src.corpora, src.slotting, src.models, "
        "src.retrieval, src.ranking, src.vector_store; "
        "print('faker' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False", "a server-side module imported faker"


# --- the corpus registry -----------------------------------------------------

def test_registry_exposes_both_kinds():
    assert sorted(KINDS) == ["creator", "prospect"]
    assert get_corpus("creator") is CREATORS
    assert get_corpus("prospect") is PROSPECTS


def test_unknown_kind_raises_rather_than_defaulting():
    """Defaulting to creators would be the worse failure: a typo in a stored
    brief would silently answer a prospect request with creators."""
    with pytest.raises(KeyError):
        get_corpus("leads")


def test_prospects_declare_no_facet():
    """Industry is text the ranker judges, not a WHERE clause. A hard filter
    would hide the cross-industry leads that are often the answer, and would
    also inherit a facet heuristic written for platform."""
    assert CREATORS.facet_is_hard_filter is True
    assert CREATORS.facet_column == "platform"
    assert PROSPECTS.facet_is_hard_filter is False
    assert PROSPECTS.facet_column is None


def test_creator_row_builder_reconstructs_an_influencer():
    """search() used to do this positionally inside the function. It moved into
    the spec, and this is the guard that the move did not shift a column."""
    row = {
        "id": 7, "handle": "@a", "platform": "TikTok", "city": "Austin",
        "followers": 1000, "engagement": 5.0, "tags": ["gym"], "bio": "Tips.",
        "similarity": 0.87, "name": "A", "country": "USA", "language": "en",
        "average_views": 900, "average_likes": 40, "average_comments": 5,
        "verified": True, "posts_per_week": 3, "account_age_years": 4,
        "content_style": "Tutorials", "audience_age": "25-34",
        "audience_gender": "60% Female", "audience_country": "USA",
        "brand_collaborations": ["Nike"], "reach_ratio": 0.4,
        "sponsored_ratio": 0.1, "growth_trend": "rising",
        "audience_top_countries": ["USA"],
    }
    inf = CREATORS.row_builder(row)
    assert isinstance(inf, Influencer)
    assert inf.id == 7 and inf.handle == "@a" and inf.similarity == 0.87
    assert inf.reach_ratio == 0.4 and inf.engagement == 5.0
    assert inf.brand_collaborations == ["Nike"]


def test_prospect_row_builder_reconstructs_a_prospect():
    row = {
        "id": 3, "name": "Acme", "industry": "B2B SaaS", "headcount": 240,
        "city": "Berlin", "country": "Germany", "description": "Workflow tooling.",
        "tags": ["saas", "workflow"], "website": "https://acme.test",
        "founded_year": 2019, "funding_stage": "Series A", "similarity": 0.81,
        "seniority_mix": "mid-weighted", "department_mix": ["engineering", "sales"],
        "tech_stack": ["Salesforce"], "buying_signals": ["wants CRM"],
        "growth_trend": "rising", "growth_rate": 0.31, "hiring_intensity": 0.22,
        "top_markets": ["DACH"],
    }
    pr = PROSPECTS.row_builder(row)
    assert isinstance(pr, Prospect)
    assert pr.id == 3 and pr.name == "Acme" and pr.headcount == 240
    assert pr.tech_stack == ["Salesforce"] and pr.growth_rate == 0.31


# --- the prospect corpus -----------------------------------------------------

def test_prospect_corpus_text_contains_stated_facts():
    pr = Prospect(
        id=1, name="Acme", industry="B2B SaaS", headcount=240,
        city="Berlin", country="Germany", description="Workflow tooling for teams.",
        tags=["saas", "workflow"], website="https://acme.test",
        founded_year=2019, funding_stage="Series A",
    )
    text = pr.corpus_text()
    for fragment in ("Acme", "B2B SaaS", "240 employees", "Berlin", "Germany",
                     "saas", "workflow", "Workflow tooling for teams."):
        assert fragment in text


def test_prospect_corpus_text_omits_empty_optional_fields():
    pr = Prospect(id=1, name="Acme", industry="SaaS", headcount=10,
                  city="Berlin", country="DE", description="Tools.",
                  tags=["saas"])
    text = pr.corpus_text()
    assert "Seniority mix" not in text
    assert "Departments" not in text
    assert "Growth" not in text
    assert "Tools in use" not in text
    assert "Signals it needs" not in text


def test_prospect_signals_round_trip_off_the_searchable_row():
    pr = Prospect(
        id=5, name="Acme", industry="SaaS", headcount=240,
        city="Berlin", country="DE", description="Tools.", tags=["saas"],
        seniority_mix="mid-weighted", department_mix=["engineering"],
        tech_stack=["Salesforce"], buying_signals=["wants CRM"],
        growth_trend="rising", growth_rate=0.31, hiring_intensity=0.22,
        top_markets=["DACH"],
    )
    signals = pr.signals()
    assert isinstance(signals, ProspectSignals)
    assert signals.prospect_id == pr.id
    assert signals.tech_stack == ["Salesforce"]
    assert signals.growth_trend == "rising"
    assert signals.growth_rate == 0.31


def test_prospect_signals_copies_mutable_lists_rather_than_aliasing_them():
    pr = Prospect(id=5, name="Acme", industry="SaaS", headcount=10,
                  city="Berlin", country="DE", description="T.", tags=[],
                  tech_stack=["Salesforce"])
    signals = pr.signals()
    signals.tech_stack.append("HubSpot")
    assert pr.tech_stack == ["Salesforce"]


def test_prospect_corpus_text_is_pinned():
    """The prospect-side golden string, for the same reason as the creator
    fingerprint in test_data_generator: the format is frozen by migration 009's
    header comment, so it needs bytes pinned against quiet reformatting.

    Full record, every optional populated -- this pins the ordering and the
    punctuation of all seven fact sentences at once.
    """
    prospect = Prospect(
        id=1, name="Acme", industry="B2B SaaS", headcount=240,
        city="Berlin", country="Germany", description="Workflow tooling for teams.",
        tags=["saas", "workflow"], website="https://acme.test",
        founded_year=2019, funding_stage="Series A",
        seniority_mix="mid-weighted", department_mix=["engineering", "sales"],
        tech_stack=["Salesforce"], buying_signals=["wants CRM"],
        growth_trend="rising",
    )
    assert prospect.corpus_text() == (
        "Company Acme, a B2B SaaS company of 240 employees, based in Berlin, Germany. "
        "Topics: saas, workflow. "
        "Seniority mix: mid-weighted. "
        "Departments: engineering, sales. "
        "Growth: rising. "
        "Tools in use: Salesforce. "
        "Signals it needs: wants CRM. "
        "Workflow tooling for teams."
    ), "Prospect.corpus_text changed: every cached vector is now stale"
