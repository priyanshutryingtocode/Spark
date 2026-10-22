"""Postgres + pgvector: the persistent home for influencer embeddings."""

import hashlib
import logging
import threading
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg.types.json import Jsonb

from . import config
from .corpora import Corpus

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "influencers"

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()

_schema_ready_tables: set[str] = set()


def _configure_connection(conn: psycopg.Connection) -> None:
    """Runs once per new pooled connection: register pgvector adapters and
    pin the HNSW scan mode. Doing these here (instead of in search()) means
    each query saves two extra roundtrips."""
    register_vector(conn)
    try:
        conn.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', false)")
    except psycopg.Error:
        logger.debug("hnsw.iterative_scan unavailable", exc_info=True)


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not config.DATABASE_URL:
                    raise RuntimeError(
                        "DATABASE_URL is not set. Copy to .env and paste in "
                        "your Supabase connection string (click Connect on your "
                        "project's dashboard, then the Session pooler tab)."
                    )
                _pool = ConnectionPool(
                    conninfo=config.DATABASE_URL,
                    min_size=1,
                    max_size=4,
                    kwargs={"autocommit": True, "prepare_threshold": None},
                    configure=_configure_connection,
                    open=True,
                )
    return _pool


def _schema_sql(table: str) -> str:
    _validate_identifier(table)
    return f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS {table} (
    id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL,
    platform TEXT NOT NULL,
    city TEXT NOT NULL,
    followers INTEGER NOT NULL,
    engagement NUMERIC NOT NULL,
    tags TEXT[] NOT NULL,
    bio TEXT NOT NULL,
    embedding VECTOR({config.EMBED_DIMENSIONS}) NOT NULL,
    name TEXT,
    country TEXT,
    language TEXT,
    average_views INTEGER,
    average_likes INTEGER,
    average_comments INTEGER,
    verified BOOLEAN,
    posts_per_week INTEGER,
    account_age_years INTEGER
);

ALTER TABLE {table} ADD COLUMN IF NOT EXISTS embed_model TEXT;
ALTER TABLE {table} ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE {table} DROP COLUMN IF EXISTS rate;
-- The single-label taxonomy is gone; topic tags are the only topical signal.
-- DROP (not SET NULL) because nothing reads these columns any more.
ALTER TABLE {table} DROP COLUMN IF EXISTS niche;
ALTER TABLE {table} DROP COLUMN IF EXISTS secondary_niches;
-- Inferred characteristics live in creator_signals (migration 007), not here.
ALTER TABLE {table} DROP COLUMN IF EXISTS content_style;
ALTER TABLE {table} DROP COLUMN IF EXISTS audience_age;
ALTER TABLE {table} DROP COLUMN IF EXISTS audience_gender;
ALTER TABLE {table} DROP COLUMN IF EXISTS audience_country;
ALTER TABLE {table} DROP COLUMN IF EXISTS brand_collaborations;

CREATE INDEX IF NOT EXISTS {table}_embedding_idx
    ON {table} USING hnsw (embedding vector_cosine_ops);
-- Measured on the live 2,000-row index (2026-10-02), which is what the earlier TODO
-- asked for. Keeping it.
--
--   recall@10  1.000   recall@50  1.000   (20 sampled queries vs exact search)
--   planner    chooses this index; a real top-10 query runs 1.05ms
--   cost       index 16MB against a 936kB table -- 17x, which is the price
--
-- The ef_search tuning further down is what makes the recall numbers hold:
-- at the pgvector default of 40, recall@50 falls to 0.800. At top_k=50 the
-- unfiltered path raises it to 400 and recall returns to 1.000. Dropping the
-- index would mean a seq-scan over 2000 x 768 floats per query and would
-- re-introduce the crowding problem as the corpus grows.

CREATE INDEX IF NOT EXISTS {table}_platform_idx ON {table} (platform);

ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
"""


def _validate_identifier(name: str) -> None:
    if not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise ValueError(f"Not a safe SQL identifier: {name!r}")


def get_connection(timeout: float = 10):
    """Check a connection out of the pool as a context manager:

        with vector_store.get_connection() as conn:
            ...

    On exit the connection returns to the pool instead of being torn down,
    so repeat queries skip connection setup entirely. `timeout` bounds how
    long a caller waits for a healthy connection before PoolTimeout -- short
    enough that an unreachable database surfaces an error banner quickly,
    long enough to absorb transient Supabase pooler handoffs."""
    return _get_pool().connection(timeout=timeout)


def init_schema(conn: psycopg.Connection, table: str = DEFAULT_TABLE) -> None:
    """Create tables/indexes if missing. Idempotent DDL; skipped after the
    first successful run per table per process (cheap, but why pay it)."""
    if table in _schema_ready_tables:
        return
    conn.execute(_schema_sql(table))
    _schema_ready_tables.add(table)


def count_records(conn: psycopg.Connection, table: str = DEFAULT_TABLE) -> int:
    _validate_identifier(table)
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class IndexModelMismatch(RuntimeError):
    """The stored creator index was built by a different embedding model.

    Raised instead of letting a search fail deep inside pgvector with an opaque
    "expected N dimensions, not M" error, so the API can report the actionable
    cause: the index needs a reindex.
    """


def _embedding_dimension(conn: psycopg.Connection, table: str = DEFAULT_TABLE) -> int | None:
    row = conn.execute(
        """
        SELECT format_type(att.atttypid, att.atttypmod)
        FROM pg_attribute AS att
        WHERE att.attrelid = to_regclass(%s)
          AND att.attname = 'embedding'
          AND NOT att.attisdropped
        """,
        (table,),
    ).fetchone()
    if not row or not row[0]:
        return None
    digits = "".join(char for char in str(row[0]) if char.isdigit())
    return int(digits) if digits else None


def assert_index_matches_config(conn: psycopg.Connection, table: str = DEFAULT_TABLE) -> None:
    """Fail fast when the index cannot answer queries for the configured model.

    A vector column of the wrong width, or rows labelled with another embedder,
    means every search would either error or silently compare incompatible
    vector spaces.
    """
    width = _embedding_dimension(conn, table)
    if width is not None and width != config.EMBED_DIMENSIONS:
        raise IndexModelMismatch(
            f"creator index is vector({width}) but EMBED_DIMENSIONS="
            f"{config.EMBED_DIMENSIONS}; reindex with `python main.py --reindex` "
            f"after changing the embedding model."
        )
    _validate_identifier(table)
    rows = conn.execute(
        f"SELECT DISTINCT embed_model FROM {table} WHERE embed_model IS NOT NULL LIMIT 5"
    ).fetchall()
    stale = {row[0] for row in rows} - {config.EMBED_MODEL}
    if stale:
        raise IndexModelMismatch(
            f"creator index was built with {sorted(stale)} but the service is "
            f"configured for {config.EMBED_MODEL!r}; reindex with "
            f"`python main.py --reindex`."
        )


def _refresh_stats(conn: psycopg.Connection, table: str = DEFAULT_TABLE) -> None:
    """Refresh planner statistics after a bulk replace. Without this the
    optimizer keeps stale estimates (often from an empty table) and falls
    back to seq-scans / cold HNSW walks, which shows up as multi-second
    latency on the first unfiltered (platform=Any) query."""
    try:
        conn.execute(f"ANALYZE {table}")
    except psycopg.Error:
        # Its absence only costs latency on the first unfiltered query.
        logger.debug("ANALYZE %s failed", table, exc_info=True)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _insert_sql(table: str, columns: tuple[str, ...], key: str | tuple[str, ...]) -> str:
    """INSERT ... ON CONFLICT DO UPDATE, derived entirely from `columns`.

    Every fragment comes from the one tuple: the column list, the VALUES
    placeholders, and the DO UPDATE assignments (all columns except the conflict
    key). They used to be written out by hand, three times, and when a column was
    dropped from one copy the statement still parsed -- it just wrote every value
    into the wrong column. That is the bug `test_run_store.py` was written for.
    """
    _validate_identifier(table)
    placeholders = ", ".join(["%s"] * len(columns))
    keys = (key,) if isinstance(key, str) else key
    assignments = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in keys)
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {assignments}"
    )


def upsert_records(conn: psycopg.Connection, records: list, corpus: Corpus) -> None:
    _validate_identifier(corpus.table)
    _validate_identifier(corpus.signals_table)

    rows = []
    for record in records:
        row = corpus.row_from_record(record)
        missing = set(corpus.write_columns) - set(row)
        if missing:
            raise ValueError(f"{corpus.kind} row is missing columns: {sorted(missing)}")
        rows.append(tuple(row[c] for c in corpus.write_columns))

    signal_rows = []
    for signals in (record.signals() for record in records):
        row = _signal_row(signals, corpus.signals_key)
        missing = set(corpus.signal_columns) - set(row)
        if missing:
            raise ValueError(f"{corpus.kind} signal row is missing columns: {sorted(missing)}")
        signal_rows.append(tuple(row[c] for c in corpus.signal_columns))

    if corpus.kind == "creator":
        identities = {
            identity.id: identity
            for record in records
            if (identity := record.identity()) is not None
        }
        if identities:
            identity_columns = ("id", "identity_key", "display_name")
            identity_rows = [
                (identity.id, identity.identity_key, identity.display_name)
                for identity in identities.values()
            ]
            with conn.cursor() as identity_cursor:
                identity_cursor.executemany(
                    _insert_sql("creator_identities", identity_columns, "id"), identity_rows
                )

    with conn.cursor() as cur:
        cur.executemany(_insert_sql(corpus.table, corpus.write_columns, "id"), rows)
        cur.executemany(
            _insert_sql(corpus.signals_table, corpus.signal_columns, corpus.signals_key),
            signal_rows,
        )
        if corpus.kind == "creator":
            source_columns = (
                "account_id", "provider", "external_account_id", "profile_url",
                "observed_at", "raw_payload",
            )
            sources = [
                (
                    record.id, source.provider, source.external_account_id,
                    source.profile_url or None, source.observed_at, Jsonb(source.raw_payload),
                )
                for record in records for source in record.source_records
            ]
            if sources:
                cur.executemany(
                    _insert_sql(
                        "creator_account_sources", source_columns,
                        ("provider", "external_account_id"),
                    ),
                    sources,
                )

            metric_columns = (
                "account_id", "provider", "observed_at", "period_days", "sample_size",
                "followers", "average_views", "average_likes", "average_comments",
                "engagement_rate", "posts_per_week",
            )
            metric_snapshots = [
                snapshot
                for record in records
                for snapshot in (record.metric_snapshots or [record.metrics_snapshot()])
            ]
            if metric_snapshots:
                metric_rows = [
                    tuple(getattr(snapshot, column) for column in metric_columns)
                    for snapshot in metric_snapshots
                ]
                cur.executemany(
                    _insert_sql(
                        "creator_metric_snapshots", metric_columns,
                        ("account_id", "provider", "observed_at", "period_days"),
                    ),
                    metric_rows,
                )

            audience_columns = (
                "account_id", "provider", "observed_at", "sample_size", "confidence",
                "age_distribution", "gender_distribution", "country_distribution",
                "language_distribution",
            )
            audience_snapshots = [
                snapshot
                for record in records
                for snapshot in (record.audience_snapshots or [record.audience_snapshot()])
            ]
            if audience_snapshots:
                audience_rows = [
                    (
                        snapshot.account_id, snapshot.provider, snapshot.observed_at,
                        snapshot.sample_size, snapshot.confidence,
                        Jsonb(snapshot.age_distribution), Jsonb(snapshot.gender_distribution),
                        Jsonb(snapshot.country_distribution), Jsonb(snapshot.language_distribution),
                    )
                    for snapshot in audience_snapshots
                ]
                cur.executemany(
                    _insert_sql(
                        "creator_audience_snapshots", audience_columns,
                        ("account_id", "provider", "observed_at"),
                    ),
                    audience_rows,
                )
        elif corpus.kind == "prospect":
            sources = [
                (
                    record.id, source.provider, source.external_company_id,
                    source.profile_url or None, source.observed_at, Jsonb(source.raw_payload),
                )
                for record in records for source in record.source_records
            ]
            if sources:
                cur.executemany(
                    _insert_sql(
                        "company_sources",
                        ("company_id", "provider", "external_company_id", "profile_url", "observed_at", "raw_payload"),
                        ("provider", "external_company_id"),
                    ),
                    sources,
                )

            metric_columns = (
                "company_id", "provider", "observed_at", "headcount",
                "headcount_low", "headcount_high", "headcount_growth_rate",
                "revenue_low", "revenue_high", "revenue_period", "revenue_currency",
                "monthly_web_visits", "open_roles",
                "sample_size", "confidence",
            )
            metric_snapshots = [
                snapshot
                for record in records
                for snapshot in (record.metric_snapshots or [record.metrics_snapshot()])
            ]
            if metric_snapshots:
                cur.executemany(
                    _insert_sql(
                        "company_metric_snapshots", metric_columns,
                        ("company_id", "provider", "observed_at"),
                    ),
                    [tuple(getattr(snapshot, column) for column in metric_columns) for snapshot in metric_snapshots],
                )

            round_columns = (
                "company_id", "provider", "external_round_id", "round_type",
                "announced_at", "amount", "currency", "post_money_valuation",
                "investors", "source_url", "raw_payload",
            )
            funding_rounds = [round_ for record in records for round_ in record.funding_rounds]
            if funding_rounds:
                cur.executemany(
                    _insert_sql(
                        "company_funding_rounds", round_columns,
                        ("provider", "external_round_id"),
                    ),
                    [
                        (
                            round_.company_id, round_.provider, round_.external_round_id,
                            round_.round_type, round_.announced_at, round_.amount,
                            round_.currency, round_.post_money_valuation,
                            Jsonb(round_.investors), round_.source_url or None,
                            Jsonb(round_.raw_payload),
                        )
                        for round_ in funding_rounds
                    ],
                )


def _signal_row(signals, key: str) -> dict:
    """The signals dataclass as a {column: value} dict, keyed however this
    corpus names its primary key (creator_id / prospect_id)."""
    row = {f: getattr(signals, f) for f in signals.__dataclass_fields__}
    row.pop(key, None)
    row[key] = getattr(signals, key)
    return row


def replace_records(conn: psycopg.Connection, records: list, corpus: Corpus) -> None:
    """Atomically swap the corpus's contents for a fresh set.

    Callers must fully generate + embed the records *before* calling this
    -- nothing in here should ever run a Gemini call. The clear and the
    write both happen inside one transaction (conn.transaction(), which
    works even though get_connection() sets autocommit=True), so if the
    write fails partway through, the clear is rolled back too and the
    table is left exactly as it was, not empty.

    TRUNCATE CASCADE removes each corpus's signals and source history through
    foreign keys (migrations 007, 009, 011, 012).
    """
    _validate_identifier(corpus.table)
    with conn.transaction():
        # CASCADE so the signals rows go with their records; without it the
        # foreign key would block the truncate.
        conn.execute(f"TRUNCATE {corpus.table} CASCADE")
        if corpus.kind == "creator":
            conn.execute("TRUNCATE creator_identities CASCADE")
        upsert_records(conn, records, corpus)
    _refresh_stats(conn, corpus.table)


def search(
    conn: psycopg.Connection,
    query_embedding: np.ndarray,
    corpus: Corpus,
    facet: str | None,
    top_k: int,
    filters: dict[str, Any] | None = None,
) -> list:
    """Retrieve the `top_k` rows of `corpus` nearest `query_embedding`.

    `facet` is the already-resolved filter value, or None for unfiltered. The
    caller decides that, because whether a facet is a filter at all is a property
    of the corpus (`Corpus.facet_is_hard_filter`), not of this function.

    `filters` adds the corpus's structured filters, as {column: value}. A list
    value is matched with `= ANY(...)` so "these industries" is one clause
    rather than one per value.

    Returns whatever `corpus.row_builder` produces, which is why the annotation
    is not list[Influencer]: a second corpus returns prospects.
    """
    _validate_identifier(corpus.table)
    _validate_identifier(corpus.signals_table)

    try:
        # An unfiltered search walks the whole HNSW graph, so it needs a larger
        # ef_search to avoid under-fetching neighbours; a filtered one matches a
        # smaller subset and needs far fewer hops. Keyed on whether a WHERE
        # clause exists rather than on any one corpus's facet name, so a corpus
        # with no facet at all takes the unfiltered branch correctly.
        has_where = facet is not None or bool(filters)
        ef_search = max(80, top_k * 8) if not has_where else max(40, top_k * 4)
        conn.execute(
            "SELECT set_config('hnsw.ef_search', %s, false)", (str(ef_search),)
        )
    except psycopg.Error:
        logger.debug("hnsw.ef_search tuning failed", exc_info=True)

    # One LEFT JOIN, not a second query: retrieval returns top_k rows and a
    # per-row signal fetch would be top_k round trips. The join is on the primary
    # key, so it does not change the row set, and every signal is COALESCEd so a
    # record with no signal row still reads back cleanly rather than raising on a
    # NULL.
    #
    # dict_row, not positional: the column list moved into the corpus spec, and
    # two row shapes mapped by index is exactly how the removed `pipeline` column
    # turned into a silent column shift. This is also why every expression in
    # corpus.search_sql carries an explicit alias -- an unaliased COALESCE(...)
    # arrives as "coalesce", and sixteen of them would collide on one key.
    sql = corpus.search_sql.format(
        table=corpus.table,
        signals_table=corpus.signals_table,
        signals_key=corpus.signals_key,
    )
    params: list = [query_embedding]
    clauses: list[str] = []
    if facet is not None:
        clauses.append(f"i.{corpus.facet_column} = %s")
        params.append(facet)
    for column, value in (filters or {}).items():
        # The column is validated as an identifier because it is interpolated
        # into the statement. It comes from a Corpus declaration rather than user
        # input, but a declared column is still a string in a query. A qualified
        # name ("s.audience_age") is allowed because some filters read the
        # signals table, which is where the inferred fields live.
        qualifier, _, bare = column.rpartition(".")
        if qualifier:
            _validate_identifier(qualifier)
            column_ref = f"{qualifier}.{bare}"
        else:
            column_ref = column
        _validate_identifier(bare)
        # The band check comes first: a (min, max) tuple is also a list, and
        # taking the list branch turned "between 200 and 2000 staff" into
        # "headcount is one of 200 or 2000", which matches almost nothing.
        is_band = (
            isinstance(value, (tuple, list))
            and len(value) == 2
            and all(isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in value)
        )
        if is_band:
            clauses.append(f"{column_ref} BETWEEN %s AND %s")
            params.append(value[0])
            params.append(value[1])
        elif isinstance(value, (list, tuple, set)):
            clauses.append(f"{column_ref} = ANY(%s)")
            params.append(list(value))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            clauses.append(f"{column_ref} = %s")
            params.append(value)
        else:
            clauses.append(f"{column_ref} = %s")
            params.append(value)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY (i.embedding <=> %s) LIMIT %s"
    params.append(query_embedding)
    params.append(top_k)

    # dict_row is set on a cursor, not on execute(): Connection.execute() has no
    # row_factory parameter, and setting it on the pooled connection instead would
    # leak into every other caller that shares the pool.
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    return [corpus.row_builder(row) for row in rows]
