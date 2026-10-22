"""The stated/inferred contract for the prospect corpus.

Mirrors test_signals_contract.py, which pins the same split for creators: the
searchable row holds what a company says, `prospect_signals` holds what a third
party infers, and the two have to keep that boundary or a reason ends up citing
an inferred figure as though the company declared it.

One thing is deliberately NOT a mirror. For creators, growth_trend is stored and
displayed but never embedded, because a creator's growth is not evidence a brand
matched on. For prospects it *is* citable and *is* embedded, because whether a
company is growing is a primary ICP-fit signal. The first test below pins that
divergence so it stays a decision rather than drifting into an accident.
"""

from src.corpora import Prospect


def make_prospect(**overrides) -> Prospect:
    base = dict(
        id=1, name="Acme", industry="B2B SaaS", headcount=240,
        city="Berlin", country="Germany", description="Workflow tooling for teams.",
        tags=["saas", "workflow"],
    )
    base.update(overrides)
    return Prospect(**base)


#: Citable: present in the embedded text a grounded reason may quote.
CITABLE = ("seniority_mix", "department_mix", "growth_trend", "tech_stack", "buying_signals")

#: Display-only: stored and returned, but deliberately not embedded. Each is
#: derivable from something already in corpus_text, so embedding it would only
#: dilute the vector -- the same argument that keeps them out of the creator text.
DISPLAY_ONLY = ("growth_rate", "hiring_intensity", "top_markets")


def values_of(record, field: str) -> list:
    """A field's value(s) as a list, whether it is a string, a number or a list."""
    value = getattr(record, field)
    return list(value) if isinstance(value, (list, tuple)) else [value]


def test_growth_trend_is_citable_for_prospects_but_not_for_creators():
    """The one deliberate divergence from the creator split.

    If this ever flips, a shrinking company would look identical to a growing one
    to the ranker, which is the single most ICP-relevant fact about it.
    """
    from src.corpora import Influencer

    prospect = make_prospect(growth_trend="rising")
    assert "rising" in prospect.corpus_text()

    creator = Influencer(
        id=1, handle="@a", platform="TikTok", city="Austin", followers=10,
        engagement=1.0, tags=["gym"], bio="Tips.", growth_trend="rising",
    )
    assert creator.growth_trend not in creator.corpus_text()


def test_every_citable_signal_reaches_corpus_text():
    """A grounded reason quotes a stored field, so the field has to be in the
    text retrieval actually searched. Anything citable that corpus_text omits is
    a claim the model cannot check honestly."""
    prospect = make_prospect(
        seniority_mix="mid-weighted",
        department_mix=["engineering", "sales"],
        growth_trend="rising",
        tech_stack=["Salesforce", "HubSpot"],
        buying_signals=["wants CRM migration"],
    )
    text = prospect.corpus_text()
    for field in CITABLE:
        for item in values_of(prospect, field):
            assert str(item) in text, f"{field}={item!r} is citable but missing from corpus_text"


def test_display_only_signals_are_kept_out_of_the_embedded_text():
    """Stored and returned, but not embedded: they are ratios and lists derivable
    from fields already in the text, and adding them only dilutes the vector."""
    prospect = make_prospect(
        growth_rate=0.31, hiring_intensity=0.22, top_markets=["DACH", "BENELUX"],
    )
    text = prospect.corpus_text()
    # Present on the record, retrievable, just not embedded.
    assert prospect.growth_rate == 0.31
    assert prospect.top_markets == ["DACH", "BENELUX"]
    for field in DISPLAY_ONLY:
        for item in values_of(prospect, field):
            assert str(item) not in text, f"{field}={item!r} leaked into corpus_text"


def test_growth_rate_is_derivable_from_what_is_already_embedded():
    """Why growth_rate is display-only rather than redundant noise: headcount is
    stated on the row, so the ratio is recoverable by any reader that needs it,
    and the corpus text already says how big the company is."""
    prospect = make_prospect(headcount=240, growth_rate=0.31)
    text = prospect.corpus_text()
    assert "240 employees" in text
    assert "0.31" not in text


def test_signals_split_does_not_change_the_stated_row():
    """What a company states and what is inferred about it must stay separable:
    a reason should be able to say "inferred seniority mix" rather than implying
    the company published it."""
    prospect = make_prospect(
        seniority_mix="mid-weighted",
        tech_stack=["Salesforce"],
        website="https://acme.test",
        funding_stage="Series A",
    )
    signals = prospect.signals()
    stated = {f for f in ("name", "industry", "headcount", "city", "country",
                          "description", "tags", "website", "founded_year",
                          "funding_stage")}
    inferred = {f.name for f in signals.__dataclass_fields__.values()} - {"prospect_id"}
    assert stated & inferred == set(), "a field appears as both stated and inferred"
