"""The prospect golden suite: does it stay honest as the vocabulary changes?

Two failure modes this guards against, both invisible until they quietly
depress a score:

  1. A case names a tag the generator no longer emits, so its pool is empty and
     `recall_of_ceiling` returns 1.0 for having found nothing. The suite would
     report a *perfect* retrieval score for a case that could never match.
  2. A case leans on a tag that appears in two verticals' pools -- `accounting`
     and `compliance` do -- so its expected set does not identify one vertical and
     the "coherent pool" it was designed for is really the union of two.
"""

import json


from evaluate import DEFAULT_CASES
from src.prospect_generator import INDUSTRY_GROUPS

CASES = json.loads(DEFAULT_CASES["prospect"].read_text(encoding="utf-8"))

#: Tags deliberately shared between verticals' vocabularies. Usable, but only
#: alongside at least one tag unique to a single vertical.
AMBIGUOUS_TAGS = {"accounting", "compliance"}


def _tag_to_groups() -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for group, vocab in INDUSTRY_GROUPS.items():
        for tag in vocab["tags"]:
            owners.setdefault(tag, set()).add(group)
    return owners


TAG_OWNERS = _tag_to_groups()


def test_every_vertical_has_at_least_one_case():
    covered = set()
    for case in CASES:
        for tag in case["expected_tags"]:
            covered |= TAG_OWNERS.get(tag, set())
    missing = set(INDUSTRY_GROUPS) - covered
    assert not missing, f"no case exercises these verticals: {sorted(missing)}"


def test_every_expected_tag_still_exists_in_the_generated_vocabulary():
    """Otherwise the pool is empty and `recall_of_ceiling` scores 1.0 for
    retrieving nothing -- a perfect number for an impossible case."""
    unknown = {
        tag for case in CASES for tag in case["expected_tags"] if tag not in TAG_OWNERS
    }
    assert not unknown, f"cases name tags the generator no longer emits: {sorted(unknown)}"


def test_no_case_relies_on_a_single_ambiguous_tag():
    """`accounting` sits in fintech and professional services. A case whose whole
    expected set is ambiguous tags spans both, which is a legitimate brief but not
    what these cases were written to test."""
    for case in CASES:
        if len(case["expected_tags"]) == 1:
            only = case["expected_tags"][0]
            assert len(TAG_OWNERS[only]) == 1, (
                f"{case['id']}: '{only}' belongs to {sorted(TAG_OWNERS[only])}, so a "
                f"single-tag case cannot pick a vertical"
            )


def test_three_cases_are_flagged_hard():
    """Mirror of the creator suite's count. Flagged cases are reported per case
    rather than averaged, and too many of them make the flag meaningless."""
    hard = [c for c in CASES if c.get("hard")]
    assert len(hard) == 3, f"expected 3 hard cases, found {len(hard)}"


def test_a_hard_case_never_repeats_its_own_tags_in_the_brief():
    """Otherwise it is not hard. Checked literally, so the wording cannot quietly
    drift back into the vocabulary while still carrying the flag."""
    for case in CASES:
        if not case.get("hard"):
            continue
        words = set(case["goal"].lower().replace(",", " ").replace(".", " ").split())
        for tag in case["expected_tags"]:
            assert tag not in words, (
                f"{case['id']} is flagged hard but its brief contains '{tag}' verbatim"
            )


def test_every_case_has_the_fields_the_runner_reads():
    for case in CASES:
        assert case.get("id"), "case has no id"
        assert case.get("goal"), f"{case.get('id')}: no goal"
        assert case.get("expected_tags"), f"{case.get('id')}: no expected_tags"


def test_case_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(set(ids)) == len(ids)


def test_suite_covers_both_tiers_of_brief_voice():
    """At least one hard case and most of the rest plain, or the flag measures
    nothing because every case is hard.

    Relative to the suite size rather than a fixed count: the suite was cut from
    14 cases to 10 to fit the daily ranking quota, and an absolute threshold
    would have failed on the smaller suite without the mix changing at all.
    """
    assert any(c.get("hard") for c in CASES)
    plain = sum(1 for c in CASES if not c.get("hard"))
    assert plain * 2 >= len(CASES), f"only {plain} of {len(CASES)} cases are plain"


def test_the_suite_matches_the_creator_suite_shape():
    """Ten cases and three hard ones, like the creator suite.

    The two suites are read by the same evaluator and compared in the same
    reports, so a shape that differs between them makes their numbers mean
    different things. The creator suite is pinned at 10 and 3; this is the same
    pin for the company side.
    """
    assert len(CASES) == 10
    assert sum(1 for c in CASES if c.get("hard")) == 3


def test_the_two_suites_do_not_share_a_file():
    """A merged file would make `--kind` cosmetic and let a creator tag leak
    into a prospect case."""
    assert DEFAULT_CASES["creator"] != DEFAULT_CASES["prospect"]
    assert DEFAULT_CASES["prospect"].exists()