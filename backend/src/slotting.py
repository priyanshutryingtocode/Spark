"""Reproducible per-slot primitives shared by every corpus generator.

These live outside the generators because the determinism contract is a property
of the *corpus*, not of one vocabulary: a record must depend on its own slot key
and nothing else, so regenerating one corpus, reordering it, or running it on a
different day cannot shift a single value. A second generator that re-implemented
any of this would produce a corpus that looked fine and quietly disagreed with
the evaluation report measured against the first one.

Nothing here may import faker at module scope: `src.platforms` sets the precedent
that the API server imports from `src` without pulling faker into the process,
and a second corpus needs these primitives to stay importable from the CLI's
seed planner, which runs before any Faker locale is chosen.
"""

import hashlib
import random
import unicodedata


def slot_rng(key: tuple) -> random.Random:
    """A generator whose stream depends only on the slot key, not on position."""
    return random.Random("|".join(str(part) for part in key))


def stable_seed(key: tuple, *parts: object) -> int:
    """A stable integer for a purpose, derived from the slot key.

    Python's `hash()` is not usable here: string hashing is salted per
    process, so the same corpus would produce different values on every run and
    silently break the determinism contract.
    """
    material = "|".join(str(part) for part in (*key, *parts))
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def slot_faker(key: tuple, locale: str):
    """Faker seeded from the slot key, so names do not depend on emit order.

    Faker's own `seed()` would work too, but hashing keeps the seed a plain
    string, so the value is reproducible across faker versions rather than
    depending on that version's internal seeding.

    Faker is imported inside the function on purpose: it is the one primitive
    that needs it, and keeping it off the module-scope import graph is what lets
    the rest of this module be imported by a server process.
    """
    from faker import Faker

    digest = hashlib.sha256("|".join(str(p) for p in key).encode("utf-8")).digest()
    fake = Faker(locale)
    fake.seed_instance(int.from_bytes(digest[:8], "big"))
    return fake


def ascii_fold(text: str) -> str:
    """Best-effort transliteration to ASCII.

    `faker.decode` is a private module, so it is imported defensively: a
    future Faker major could move it. The `unicodedata` fallback still handles
    accented Latin correctly, and only fails to romanize entirely non-Latin
    scripts, which is why callers treat an empty result as "no usable name"
    rather than producing an empty slug.
    """
    try:
        from faker.decode import unidecode
    except ImportError:  # pragma: no cover - only on a Faker major upgrade
        unidecode = None
    if unidecode is not None:
        return unidecode(text)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()