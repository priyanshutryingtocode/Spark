"""Tests for src.vector_store SQL-safety helpers and the index/model guard
(offline, no database)."""

import re

import pytest

from src import config
from src.vector_store import (
    IndexModelMismatch,
    _embedding_dimension,
    _schema_sql,
    _validate_identifier,
    assert_index_matches_config,
)


class FakeConn:
    """Returns queued results in call order: one fetchone, one fetchall."""

    def __init__(self, dimension, models):
        self.results = [[dimension], [(model,) for model in models]]

    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return self.results.pop(0)

    def fetchall(self):
        return self.results.pop(0)


@pytest.mark.parametrize("name", ["influencers", "t", "a_1", "Table_2"])
def test_valid_identifiers_accepted(name):
    _validate_identifier(name)  # must not raise


@pytest.mark.parametrize("name", ["", "1abc", "_leading", "bad name", "drop-table", 'x"; --'])
def test_invalid_identifiers_rejected(name):
    with pytest.raises(ValueError, match="safe SQL identifier"):
        _validate_identifier(name)


def test_schema_sql_rejects_unsafe_table():
    with pytest.raises(ValueError):
        _schema_sql('influencers"; DROP TABLE users')


def test_content_hash_stable_and_sensitive():
    from src.vector_store import _content_hash
    assert _content_hash("abc") == _content_hash("abc")
    assert _content_hash("abc") != _content_hash("abd")


def test_signal_columns_are_not_on_the_influencers_table():
    """Inferred fields live in creator_signals, not on the searched row."""
    sql = _schema_sql("influencers")
    body = sql.split("CREATE TABLE")[1]
    for column in ("content_style", "audience_age", "audience_gender",
                   "audience_country", "brand_collaborations"):
        assert f"{column} TEXT" not in body
        assert f"DROP COLUMN IF EXISTS {column}" in sql


def test_signals_are_read_with_a_join_and_coalesced():
    """A missing signal row must not break retrieval.

    Every signal column is COALESCEd, so a record whose signals row is absent
    (or whose fields are NULL) still reads back as an empty string or zero
    rather than raising.

    The SQL moved into the corpus spec, so this now asserts that the join is
    *parametrised* -- the placeholders must still be there -- and separately that
    each corpus points them at the right real table and key. Checking the
    rendered text alone would pass even if a spec named the wrong table.
    """
    from src.corpora import CREATORS, PROSPECTS

    for corpus, signals_table, signals_key, columns in (
        (
            CREATORS, "creator_signals", "creator_id",
            ("content_style", "audience_age", "audience_gender", "audience_country",
             "brand_collaborations", "reach_ratio", "sponsored_ratio", "growth_trend",
             "audience_top_countries"),
        ),
        (
            PROSPECTS, "prospect_signals", "prospect_id",
            ("seniority_mix", "department_mix", "tech_stack", "buying_signals",
             "growth_trend", "growth_rate", "hiring_intensity", "top_markets"),
        ),
    ):
        sql = corpus.search_sql
        assert corpus.signals_table == signals_table
        assert corpus.signals_key == signals_key
        assert "LEFT JOIN {signals_table} AS s ON s.{signals_key} = i.id" in sql
        for column in columns:
            assert f"COALESCE(s.{column}" in sql, f"{corpus.kind}: {column} read without COALESCE"


def test_every_selected_expression_is_aliased():
    """dict_row keys on the column name, and an unaliased expression arrives as
    "coalesce" -- so sixteen COALESCEs would collide on one key and silently
    collapse every optional field onto the last one."""
    import re

    from src.corpora import CREATORS, PROSPECTS

    pattern = r"COALESCE\([^)]*\)(?:\s*\[[^\]]*\])?(?:\s*AS\s+\w+)?"
    for corpus in (CREATORS, PROSPECTS):
        select = corpus.search_sql.split("FROM", 1)[0]
        matches = list(re.finditer(pattern, select))
        assert matches, f"{corpus.kind}: no COALESCE expressions found to check"
        for match in matches:
            text = match.group(0)
            aliased = bool(re.search(r"\bAS\s+\w+$", text))
            assert aliased, f"{corpus.kind}: {text!r} has no alias"


def test_truncate_cascades_to_signals():
    """TRUNCATE without CASCADE would be blocked by the signals foreign key."""
    import inspect
    from src import vector_store

    source = inspect.getsource(vector_store.replace_records)
    assert re.search(r"TRUNCATE \{corpus\.table\} CASCADE", source), (
        "replace_records must truncate with CASCADE so signals rows go with "
        f"their records; got: {source!r}"
    )


def test_insert_sql_derives_every_fragment_from_one_column_tuple():
    """The column list, the placeholders and the DO UPDATE assignments are all
    generated from `columns`.

    They used to be written out three times by hand. When a column was dropped
    from one copy the statement still parsed and silently wrote every value into
    the wrong column -- the exact failure test_run_store.py exists for. This
    asserts the derivation holds: arity matches, and the key is the only column
    excluded from the update set.
    """
    from src.corpora import CREATORS, PROSPECTS
    from src.vector_store import _insert_sql

    for corpus, key, columns, table in (
        (CREATORS, "creator_id", CREATORS.signal_columns, CREATORS.signals_table),
        (PROSPECTS, "prospect_id", PROSPECTS.signal_columns, PROSPECTS.signals_table),
        (CREATORS, "id", CREATORS.write_columns, CREATORS.table),
        (PROSPECTS, "id", PROSPECTS.write_columns, PROSPECTS.table),
    ):
        sql = _insert_sql(table, columns, key)
        assert sql.count("%s") == len(columns), f"{table}: placeholder arity"
        for column in columns:
            assert column in sql.split("VALUES")[0], f"{table}: {column} not inserted"
        if len(columns) > 1:
            updated = sql.split("DO UPDATE SET")[1]
            assert f"{key} = EXCLUDED.{key}" not in updated, (
                f"{table}: conflict key {key} must not update itself"
            )
            assert updated.count("EXCLUDED.") == len(columns) - 1


def test_embedding_dimension_parses_pgvector_type():
    assert _embedding_dimension(FakeConn(f"vector({config.EMBED_DIMENSIONS})", [])) == config.EMBED_DIMENSIONS


def test_embedding_dimension_none_when_column_missing():
    assert _embedding_dimension(FakeConn(None, [])) is None


def test_matching_index_passes_the_guard():
    assert_index_matches_config(FakeConn(f"vector({config.EMBED_DIMENSIONS})", [config.EMBED_MODEL]))


def test_empty_index_passes_the_guard():
    # A freshly migrated table has no rows to mislabel, so there is nothing to
    # reindex yet; the readiness check reports the empty count instead.
    assert_index_matches_config(FakeConn(f"vector({config.EMBED_DIMENSIONS})", []))


def test_wrong_width_reports_a_reindex():
    with pytest.raises(IndexModelMismatch, match="reindex"):
        assert_index_matches_config(FakeConn("vector(384)", [config.EMBED_MODEL]))


def test_stale_embed_model_reports_a_reindex():
    with pytest.raises(IndexModelMismatch, match="reindex"):
        assert_index_matches_config(
            FakeConn(f"vector({config.EMBED_DIMENSIONS})", ["sentence-transformers/all-MiniLM-L6-v2"])
        )
