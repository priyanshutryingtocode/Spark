"""Tests for lexical term matching (src.text_match).

Term matching never influences retrieval order. It exists to explain a result
to a human: which of the brief's own words appear in the profile text the
creator's embedding was built from.
"""

from src.corpora import Influencer
from src.text_match import overlap_ratio, shared_terms, terms


def make(id_, tags=None, bio="", **overrides) -> Influencer:
    defaults = dict(
        handle=f"@c{id_}", platform="Instagram", city="Austin",
        followers=10_000, engagement=5.0,
        tags=tags or [], bio=bio,
    )
    defaults.update(overrides)
    return Influencer(id=id_, **defaults)


def test_tags_and_bio_are_searched():
    creator = make(1, tags=["sourdough", "baking"], bio="Slow food")
    assert shared_terms(terms("sourdough baking"), creator) == {"sourdough", "baking"}


def test_audience_and_brand_fields_are_searched():
    """corpus_text is the single source of truth, so a brief mentioning a
    brand the creator worked with must find them."""
    creator = make(1, tags=["fashion"], brand_collaborations=["Patagonia"])
    assert shared_terms(terms("patagonia partnership"), creator) == {"patagonia"}


def test_ratio_is_a_share_of_the_brief_not_the_profile():
    """Profile length must not inflate the score; only the brief is the denominator."""
    long_bio = " ".join(f"filler{i}" for i in range(60))
    creator = make(1, tags=["keto"], bio=long_bio)
    assert overlap_ratio(terms("keto"), creator) == 1.0
    assert overlap_ratio(terms("keto recipes"), creator) == 0.5


def test_unrelated_creator_scores_zero():
    assert overlap_ratio(terms("keto recipes"), make(1, tags=["fps"], bio="Shooter games.")) == 0.0


def test_empty_brief_terms_score_zero():
    assert overlap_ratio(set(), make(1, tags=["gym"])) == 0.0


def test_terms_drop_stopwords_and_short_tokens():
    assert terms("The best of a for AI") == {"best"}


def test_terms_are_case_insensitive():
    assert terms("Sourdough BAKING") == terms("sourdough baking")


def test_overlap_ratio_is_bounded():
    creator = make(1, tags=["keto", "recipes"], bio="Low carb")
    ratio = overlap_ratio(terms("keto recipes low carb"), creator)
    assert 0.0 <= ratio <= 1.0


def test_matching_reads_exactly_what_the_vector_saw():
    """The explanation must not quote a field corpus_text leaves out."""
    creator = make(1, tags=["gym"], bio="Lifting.")
    for field in ("platform", "city", "followers", "content_style"):
        assert str(creator.__getattribute__(field)) in creator.corpus_text() or field == "followers"
