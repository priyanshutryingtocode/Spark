from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from src import vector_store
from src.corpora import DEFAULT_KIND as DEFAULT_RUN_KIND


class InvalidCursor(ValueError):
    pass


class PostgresRunRepository:
    def __init__(self, connection_factory: Callable | None = None):
        self._connection_factory = connection_factory or vector_store.get_connection

    def ensure_schema(self) -> None:
        migration_dir = Path(__file__).resolve().parents[2] / "migrations"
        with self._connection_factory() as conn:
            # The creator account table is the referenced base for migrations
            # that add source, identity, and observation tables. Initialize it
            # before replaying migrations; company tables are created by their
            # own earlier migrations in that same sequence.
            vector_store.init_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            for migration in sorted(migration_dir.glob("*.sql")):
                already_applied = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE filename = %s",
                    (migration.name,),
                ).fetchone()
                if already_applied:
                    continue
                with conn.transaction():
                    conn.execute(migration.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s)",
                        (migration.name,),
                    )

    def create(self, record: dict, owner_id=None) -> dict:
        owner = _as_uuid(owner_id or record.get("owner_id"))
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO match_runs
                    (id, owner_id, kind, brief, params, result, warnings, summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, owner_id, kind, brief, params, result, warnings, summary,
                          created_at, updated_at
                """,
                (
                    record["id"],
                    owner,
                    # Defaulted rather than required: a record built before the
                    # two panels existed carries no kind, and the column default
                    # is the same 'creator' the summary would report.
                    record.get("kind", DEFAULT_RUN_KIND),
                    Jsonb(record["brief"]),
                    Jsonb(record["params"]),
                    Jsonb(record["result"]),
                    Jsonb(record["warnings"]),
                    Jsonb(record["summary"]),
                ),
            ).fetchone()
        return _record_from_row(row)

    def list(
        self,
        limit: int,
        cursor: str | None = None,
        owner_id=None,
        kind: str | None = None,
    ) -> tuple[list[dict], str | None]:
        conditions: list[str] = []
        params: list[Any] = []
        owner = _as_uuid(owner_id)
        if owner is not None:
            conditions.append("owner_id = %s")
            params.append(owner)
        # None means "every corpus", which is what an unfiltered caller wants.
        # The two panels always pass one, so neither ever sees the other's runs.
        if kind is not None:
            conditions.append("kind = %s")
            params.append(kind)
        if cursor:
            created_at, run_id = _decode_cursor(cursor)
            conditions.append("(created_at < %s OR (created_at = %s AND id < %s))")
            params.extend([created_at, created_at, run_id])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit + 1)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT id, created_at, kind, brief, warnings, summary
                FROM match_runs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                params,
            ).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_cursor = _encode_cursor(visible[-1][1], visible[-1][0]) if has_more and visible else None
        return [
            {
                "id": row[0],
                "created_at": row[1],
                # Defaults rather than indexing blindly: the SELECT order here
                # differs from `get`, so a shared positional reader would be a
                # silent mismatch waiting to happen.
                "kind": row[2],
                "brief": row[3],
                "warnings": row[4],
                "summary": row[5],
            }
            for row in visible
        ], next_cursor

    def get(self, run_id: UUID, owner_id=None) -> dict | None:
        owner = _as_uuid(owner_id)
        where = "id = %s"
        params: list[Any] = [run_id]
        if owner is not None:
            where += " AND owner_id = %s"
            params.append(owner)
        with self._connection_factory() as conn:
            row = conn.execute(
                f"""
                SELECT id, owner_id, kind, brief, params, result, warnings, summary,
                       created_at, updated_at
                FROM match_runs
                WHERE {where}
                """,
                params,
            ).fetchone()
        return _record_from_row(row) if row else None

    def delete(self, run_id: UUID, owner_id=None) -> bool:
        owner = _as_uuid(owner_id)
        where = "id = %s"
        params: list[Any] = [run_id]
        if owner is not None:
            where += " AND owner_id = %s"
            params.append(owner)
        with self._connection_factory() as conn:
            row = conn.execute(
                f"DELETE FROM match_runs WHERE {where} RETURNING id",
                params,
            ).fetchone()
        return row is not None

    def save_match(self, run_id: UUID, candidate_id: int, owner_id=None) -> dict | None:
        owner = _as_uuid(owner_id)
        run = self.get(run_id, owner_id=owner)
        if run is None:
            return None
        result = run.get("result") or {}
        candidate = next(
            (item for item in result.get("candidates", []) if item.get("id") == candidate_id),
            None,
        )
        ranked = next(
            (item for item in result.get("ranked", []) if item.get("id") == candidate_id),
            None,
        )
        if candidate is None or ranked is None:
            return None

        saved_id = uuid4()
        with self._connection_factory() as conn:
            conn.execute(
                """
                INSERT INTO saved_matches
                    (id, owner_id, run_id, candidate_id, kind, brief, candidate,
                     ranked, source_created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    saved_id,
                    owner,
                    run_id,
                    candidate_id,
                    run["kind"],
                    Jsonb(run["brief"]),
                    Jsonb(candidate),
                    Jsonb(ranked),
                    run["created_at"],
                ),
            )
            row = conn.execute(
                """
                SELECT id, run_id, kind, brief, candidate, ranked, status, note,
                       source_created_at, created_at, updated_at
                FROM saved_matches
                WHERE owner_id IS NOT DISTINCT FROM %s
                  AND run_id = %s AND candidate_id = %s
                """,
                (owner, run_id, candidate_id),
            ).fetchone()
        return _saved_match_from_row(row) if row else None

    def list_saved_matches(self, owner_id=None, kind: str | None = None) -> list[dict]:
        owner = _as_uuid(owner_id)
        where = ["owner_id IS NOT DISTINCT FROM %s"]
        params: list[Any] = [owner]
        if kind is not None:
            where.append("kind = %s")
            params.append(kind)
        with self._connection_factory() as conn:
            rows = conn.execute(
                f"""
                SELECT id, run_id, kind, brief, candidate, ranked, status, note,
                       source_created_at, created_at, updated_at
                FROM saved_matches
                WHERE {' AND '.join(where)}
                ORDER BY created_at DESC, id DESC
                """,
                params,
            ).fetchall()
        return [_saved_match_from_row(row) for row in rows]

    def update_saved_match(self, saved_id, owner_id=None, *, status=None, note=None) -> dict | None:
        owner = _as_uuid(owner_id)
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                UPDATE saved_matches
                SET status = COALESCE(%s, status),
                    note = COALESCE(%s, note),
                    updated_at = NOW()
                WHERE id = %s AND owner_id IS NOT DISTINCT FROM %s
                RETURNING id, run_id, kind, brief, candidate, ranked, status, note,
                          source_created_at, created_at, updated_at
                """,
                (status, note, _as_uuid(saved_id), owner),
            ).fetchone()
        return _saved_match_from_row(row) if row else None

    def save_match_feedback(
        self, run_id, candidate_id: int, kind: str, rating: str, reason: str = "", owner_id=None
    ) -> dict | None:
        owner = _as_uuid(owner_id)
        feedback_id = uuid4()
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                INSERT INTO match_feedback
                    (id, owner_id, run_id, candidate_id, kind, rating, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    (COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::UUID)),
                    run_id, candidate_id
                ) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    rating = EXCLUDED.rating,
                    reason = EXCLUDED.reason,
                    updated_at = NOW()
                RETURNING run_id, candidate_id, kind, rating, reason, updated_at
                """,
                (feedback_id, owner, _as_uuid(run_id), candidate_id, kind, rating, reason),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "candidate_id": row[1],
            "kind": row[2],
            "rating": row[3],
            "reason": row[4],
            "updated_at": row[5],
        }

    def delete_saved_match(self, saved_id: UUID, owner_id=None) -> bool:
        owner = _as_uuid(owner_id)
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                DELETE FROM saved_matches
                WHERE id = %s AND owner_id IS NOT DISTINCT FROM %s
                RETURNING id
                """,
                (saved_id, owner),
            ).fetchone()
        return row is not None


def _record_from_row(row) -> dict:
    return {
        "id": row[0],
        "owner_id": row[1],
        # The column is NOT NULL, so row[2] is always present once migration 010
        # has run. The fallback is for a row read before it, which is the same
        # reason the column defaults to 'creator'.
        "kind": row[2] or DEFAULT_RUN_KIND,
        "brief": row[3],
        "params": row[4],
        "result": row[5],
        "warnings": row[6],
        "summary": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def _saved_match_from_row(row) -> dict:
    return {
        "id": row[0],
        "run_id": row[1],
        "kind": row[2],
        "brief": row[3],
        "candidate": row[4],
        "ranked": row[5],
        "status": row[6],
        "note": row[7],
        "source_created_at": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


def _as_uuid(value):
    if value is None or value == "":
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _encode_cursor(created_at, run_id: UUID) -> str:
    value = f"{created_at.isoformat()}|{run_id}".encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[Any, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        created_at, run_id = value.split("|", 1)
        from datetime import datetime

        return datetime.fromisoformat(created_at), UUID(run_id)
    except (ValueError, UnicodeError) as exc:
        raise InvalidCursor("Invalid history cursor") from exc
