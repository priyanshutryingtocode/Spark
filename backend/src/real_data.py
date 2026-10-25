"""Provider-neutral writes for normalized, source-backed profiles.

Adapters should normalize provider responses into these mappings before writing.
Unknown values stay null; this layer does not infer metrics from missing fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import numpy as np
from psycopg.types.json import Jsonb

from . import config, vector_store


CREATOR_PROFILE_COLUMNS = {
    "identity_id", "platform", "external_account_id", "handle", "name", "profile_url",
    "avatar_url", "bio", "platform_category", "city", "country", "language", "verified",
    "followers", "engagement", "average_views", "average_likes", "average_comments",
    "posts_per_week", "account_age_years", "tags", "search_document", "embedding",
    "embed_model", "content_hash", "is_active", "profile_observed_at",
}
COMPANY_PROFILE_COLUMNS = {
    "name", "canonical_domain", "legal_name", "registration_jurisdiction", "registration_id",
    "website", "description", "industry", "company_type", "city", "country", "founded_year",
    "headcount", "funding_stage", "tags", "search_document", "embedding", "embed_model",
    "content_hash", "is_active", "profile_observed_at",
}
CREATOR_SIGNAL_COLUMNS = {
    "content_style", "audience_age", "audience_gender", "audience_country", "brand_collaborations",
    "reach_ratio", "sponsored_ratio", "growth_trend", "audience_top_countries", "source_provider",
    "observed_at", "confidence",
}
COMPANY_SIGNAL_COLUMNS = {
    "seniority_mix", "department_mix", "tech_stack", "buying_signals", "growth_trend", "growth_rate",
    "hiring_intensity", "top_markets", "source_provider", "observed_at", "confidence",
}
CREATOR_METRIC_COLUMNS = {
    "observed_at", "period_start", "period_end", "followers", "following", "total_views", "total_likes",
    "post_count", "video_count", "average_views", "median_views", "average_likes", "average_comments",
    "engagement_rate", "posts_per_week", "sample_size", "metric_definitions",
}
COMPANY_METRIC_COLUMNS = {
    "observed_at", "headcount", "headcount_low", "headcount_high", "headcount_growth_rate",
    "revenue_low", "revenue_high", "revenue_currency", "revenue_period", "monthly_web_visits",
    "open_roles", "sample_size", "confidence",
}
CREATOR_CONTENT_COLUMNS = {
    "external_content_id", "content_type", "content_url", "title", "text", "language", "published_at",
}
CONTENT_METRIC_COLUMNS = {"observed_at", "views", "likes", "comments", "shares", "saves", "metric_definitions"}
TOPIC_COLUMNS = {"topic", "confidence", "method", "model_version", "evidence", "observed_at"}
FUNDING_COLUMNS = {
    "external_round_id", "round_type", "announced_at", "amount", "currency", "post_money_valuation",
    "investors", "source_url", "raw_payload",
}
JOB_COLUMNS = {
    "external_job_id", "title", "department", "location", "employment_type", "workplace_type",
    "posted_at", "valid_through", "source_url", "is_open", "last_seen_at", "raw_payload",
}
JSON_COLUMNS = {"profile", "raw_payload", "metric_definitions", "age_distribution", "gender_distribution",
                "country_distribution", "language_distribution", "investors", "evidence"}


def _validated(mapping: Mapping[str, Any], allowed: set[str], label: str) -> dict[str, Any]:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"Unknown {label} fields: {sorted(unknown)}")
    return dict(mapping)


def _vector(values: Any) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float32)
    if vector.shape != (config.EMBED_DIMENSIONS,):
        raise ValueError(f"Expected an embedding with {config.EMBED_DIMENSIONS} dimensions")
    if not np.isfinite(vector).all():
        raise ValueError("Embedding values must be finite")
    return vector


def _validate_embedding_fields(data: dict[str, Any]) -> None:
    for required in ("search_document", "embedding", "embed_model", "content_hash"):
        if data.get(required) is None:
            raise ValueError(f"Searchable profile requires {required}")
    if data["embed_model"] != config.EMBED_MODEL:
        raise ValueError(f"Expected embedding model {config.EMBED_MODEL!r}")
    if not str(data["search_document"]).strip() or not str(data["content_hash"]).strip():
        raise ValueError("search_document and content_hash cannot be empty")
    data["embedding"] = _vector(data["embedding"])


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _upsert(conn, table: str, values: Mapping[str, Any], conflict: tuple[str, ...], *, return_id=True):
    data = dict(values)
    for key in JSON_COLUMNS:
        if key in data and data[key] is not None and not isinstance(data[key], Jsonb):
            data[key] = Jsonb(_json_value(data[key]))
    columns = tuple(data)
    if not columns:
        raise ValueError(f"No values supplied for {table}")
    names = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    target = ", ".join(conflict)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in conflict)
    if table == "real_creator_accounts" and updates:
        updates += ", updated_at = NOW()"
    action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    returning = " RETURNING id" if return_id else ""
    cursor = conn.execute(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT ({target}) {action}{returning}",
        tuple(data[column] for column in columns),
    )
    return cursor.fetchone() if return_id else None


def _source(conn, table: str, entity_column: str, entity_id: int, source: Mapping[str, Any]) -> int:
    values = {
        entity_column: entity_id,
        "provider": source["provider"],
        "external_id": source["external_id"],
        "source_url": source.get("source_url"),
        "access_basis": source["access_basis"],
        "observed_at": source.get("observed_at"),
        "payload_hash": source.get("payload_hash"),
        "raw_payload": Jsonb(_json_value(source.get("raw_payload", {}))),
    }
    row = conn.execute(
        f"""INSERT INTO {table} ({', '.join(values)})
            VALUES ({', '.join(['%s'] * len(values))})
            ON CONFLICT (provider, external_id) DO UPDATE SET
                {entity_column} = EXCLUDED.{entity_column}, source_url = EXCLUDED.source_url,
                access_basis = EXCLUDED.access_basis, observed_at = EXCLUDED.observed_at,
                payload_hash = EXCLUDED.payload_hash, raw_payload = EXCLUDED.raw_payload,
                fetched_at = NOW()
            RETURNING id""",
        tuple(values.values()),
    ).fetchone()
    return row[0]


def _snapshot(conn, table: str, entity_column: str, entity_id: int, source_id: int, data: Mapping[str, Any]):
    values = {entity_column: entity_id, "source_id": source_id, **data}
    values = {k: (Jsonb(_json_value(v)) if k in JSON_COLUMNS and v is not None and not isinstance(v, Jsonb) else v)
              for k, v in values.items()}
    columns = tuple(values)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
        tuple(values[k] for k in columns),
    )


class RealDataRepository:
    """Store provider-normalized creator and company records without synthetic IDs."""

    def __init__(self, connection_factory=vector_store.get_connection):
        self._connection_factory = connection_factory

    def upsert_creator(self, profile: Mapping[str, Any], source: Mapping[str, Any], *,
                       signals: Mapping[str, Any] | None = None,
                       metrics: Mapping[str, Any] | None = None,
                       audience: Mapping[str, Any] | None = None,
                       content: list[Mapping[str, Any]] | None = None,
                       topics: list[Mapping[str, Any]] | None = None) -> int:
        profile_data = dict(profile)
        identity = profile_data.pop("identity", None)
        data = _validated(profile_data, CREATOR_PROFILE_COLUMNS, "creator profile")
        for required in ("platform", "external_account_id", "handle"):
            if data.get(required) is None:
                raise ValueError(f"Creator profile requires {required}")
        _validate_embedding_fields(data)
        source_data = dict(source)
        for required in ("provider", "external_id", "access_basis"):
            if not source_data.get(required):
                raise ValueError(f"Creator source requires {required}")
        with self._connection_factory() as conn, conn.transaction():
            identity_id = None
            if identity:
                if not identity.get("identity_key") or not identity.get("display_name"):
                    raise ValueError("Creator identity requires identity_key and display_name")
                row = conn.execute("""INSERT INTO real_creator_identities
                    (identity_key, display_name, identity_type) VALUES (%s, %s, %s)
                    ON CONFLICT (identity_key) DO UPDATE SET display_name = EXCLUDED.display_name,
                        identity_type = EXCLUDED.identity_type RETURNING id""",
                    (identity["identity_key"], identity["display_name"], identity.get("identity_type", "person")),
                ).fetchone()
                identity_id = row[0]
            if identity_id is not None:
                data["identity_id"] = identity_id
            row = _upsert(conn, "real_creator_accounts", data, ("platform", "external_account_id"))
            account_id = row[0] if row else conn.execute(
                "SELECT id FROM real_creator_accounts WHERE platform = %s AND external_account_id = %s",
                (data["platform"], data["external_account_id"]),
            ).fetchone()[0]
            source_id = _source(conn, "real_creator_sources", "account_id", account_id, source_data)
            profile_json = {k: v for k, v in data.items() if k != "embedding"}
            _snapshot(conn, "real_creator_profile_snapshots", "account_id", account_id, source_id, {
                "observed_at": source_data.get("observed_at"), "profile": profile_json,
            })
            if metrics is not None:
                metric_data = _validated(metrics, CREATOR_METRIC_COLUMNS, "creator metric snapshot")
                _snapshot(conn, "real_creator_metric_snapshots", "account_id", account_id, source_id, metric_data)
            if audience is not None:
                allowed = {"observed_at", "period_start", "period_end", "age_distribution", "gender_distribution",
                           "country_distribution", "language_distribution", "sample_size", "confidence"}
                _snapshot(conn, "real_creator_audience_snapshots", "account_id", account_id, source_id,
                          _validated(audience, allowed, "creator audience snapshot"))
            if signals is not None:
                signal_data = _validated(signals, CREATOR_SIGNAL_COLUMNS, "creator signals")
                _upsert(conn, "real_creator_signals", {"creator_id": account_id, **signal_data},
                        ("creator_id",), return_id=False)
            for topic in topics or []:
                topic_data = _validated(topic, TOPIC_COLUMNS, "creator topic signal")
                if not topic_data.get("topic") or not topic_data.get("method"):
                    raise ValueError("Each topic signal requires topic and method")
                topic_data.setdefault("observed_at", datetime.now(timezone.utc))
                _upsert(conn, "real_creator_topic_signals", {"account_id": account_id, **topic_data},
                        ("account_id", "topic", "method", "observed_at"))
            for item in content or []:
                item_data = _validated(item, CREATOR_CONTENT_COLUMNS | {"metrics"}, "creator content item")
                content_metrics = item_data.pop("metrics", None)
                if not item_data.get("external_content_id") or not item_data.get("content_type"):
                    raise ValueError("Each content item requires external_content_id and content_type")
                columns = tuple(item_data) + ("account_id", "source_id")
                values = {**item_data, "account_id": account_id, "source_id": source_id}
                row = conn.execute(
                    f"""INSERT INTO real_creator_content_items ({', '.join(columns)})
                        VALUES ({', '.join(['%s'] * len(columns))})
                        ON CONFLICT (source_id, external_content_id) DO UPDATE SET
                            content_type = EXCLUDED.content_type, content_url = EXCLUDED.content_url,
                            title = EXCLUDED.title, text = EXCLUDED.text, language = EXCLUDED.language,
                            published_at = EXCLUDED.published_at, updated_at = NOW()
                        RETURNING id""",
                    tuple(values[k] for k in columns),
                ).fetchone()
                if content_metrics is not None:
                    _snapshot(conn, "real_creator_content_metric_snapshots", "content_id", row[0], source_id,
                              _validated(content_metrics, CONTENT_METRIC_COLUMNS, "content metrics"))
        return account_id

    def upsert_company(self, profile: Mapping[str, Any], source: Mapping[str, Any], *,
                       signals: Mapping[str, Any] | None = None,
                       metrics: Mapping[str, Any] | None = None,
                       funding_rounds: list[Mapping[str, Any]] | None = None,
                       jobs: list[Mapping[str, Any]] | None = None) -> int:
        data = _validated(profile, COMPANY_PROFILE_COLUMNS, "company profile")
        for required in ("name",):
            if data.get(required) is None:
                raise ValueError(f"Company profile requires {required}")
        _validate_embedding_fields(data)
        source_data = dict(source)
        for required in ("provider", "external_id", "access_basis"):
            if not source_data.get(required):
                raise ValueError(f"Company source requires {required}")
        with self._connection_factory() as conn, conn.transaction():
            company_id = None
            row = conn.execute(
                """SELECT company_id FROM real_company_sources
                   WHERE provider = %s AND external_id = %s""",
                (source_data["provider"], source_data["external_id"]),
            ).fetchone()
            company_id = row[0] if row else None
            if data.get("canonical_domain"):
                row = conn.execute(
                    "SELECT id FROM real_companies WHERE lower(canonical_domain) = lower(%s)",
                    (data["canonical_domain"],),
                ).fetchone()
                company_id = company_id or (row[0] if row else None)
            if company_id is None and data.get("registration_id") and data.get("registration_jurisdiction"):
                row = conn.execute(
                    """SELECT id FROM real_companies
                       WHERE registration_id = %s AND registration_jurisdiction = %s""",
                    (data["registration_id"], data["registration_jurisdiction"]),
                ).fetchone()
                company_id = row[0] if row else None
            if company_id is None:
                columns = tuple(data)
                row = conn.execute(
                    f"INSERT INTO real_companies ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
                    tuple(data[k] for k in columns),
                ).fetchone()
                company_id = row[0]
            else:
                columns = tuple(data)
                assignments = ", ".join(f"{k} = %s" for k in columns)
                conn.execute(f"UPDATE real_companies SET {assignments}, updated_at = NOW() WHERE id = %s",
                             tuple(data[k] for k in columns) + (company_id,))
            source_id = _source(conn, "real_company_sources", "company_id", company_id, source_data)
            profile_json = {k: v for k, v in data.items() if k != "embedding"}
            _snapshot(conn, "real_company_profile_snapshots", "company_id", company_id, source_id, {
                "observed_at": source_data.get("observed_at"), "profile": profile_json,
            })
            if metrics is not None:
                _snapshot(conn, "real_company_metric_snapshots", "company_id", company_id, source_id,
                          _validated(metrics, COMPANY_METRIC_COLUMNS, "company metric snapshot"))
            if signals is not None:
                signal_data = _validated(signals, COMPANY_SIGNAL_COLUMNS, "company signals")
                _upsert(conn, "real_company_signals", {"company_id": company_id, **signal_data},
                        ("company_id",), return_id=False)
            for table, records, allowed, label in (
                ("real_company_funding_rounds", funding_rounds or [], FUNDING_COLUMNS, "funding round"),
                ("real_company_job_postings", jobs or [], JOB_COLUMNS, "job posting"),
            ):
                for record in records:
                    record_data = _validated(record, allowed, label)
                    fields = {"company_id": company_id, "source_id": source_id, **record_data}
                    columns = tuple(fields)
                    unique_key = "external_round_id" if table.endswith("funding_rounds") else "external_job_id"
                    mutable = [k for k in columns if k not in {"source_id", unique_key}]
                    assignments = ", ".join(f"{k} = EXCLUDED.{k}" for k in mutable)
                    conn.execute(
                        f"""INSERT INTO {table} ({', '.join(columns)})
                            VALUES ({', '.join(['%s'] * len(columns))})
                            ON CONFLICT (source_id, {unique_key}) DO UPDATE SET {assignments}""",
                        tuple(Jsonb(_json_value(v)) if k in JSON_COLUMNS and v is not None else v for k, v in fields.items()),
                    )
        return company_id
