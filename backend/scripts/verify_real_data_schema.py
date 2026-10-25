"""Confirm the real-data migration is installed without inspecting profile data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import vector_store


EXPECTED_TABLES = {
    "real_creator_identities", "real_creator_accounts", "real_creator_signals", "real_creator_sources",
    "real_creator_profile_snapshots", "real_creator_metric_snapshots", "real_creator_audience_snapshots",
    "real_creator_content_items", "real_creator_content_metric_snapshots", "real_creator_topic_signals",
    "real_companies", "real_company_signals", "real_company_sources", "real_company_profile_snapshots",
    "real_company_metric_snapshots", "real_company_funding_rounds", "real_company_job_postings",
    "real_ingestion_runs",
}


def main() -> None:
    with vector_store.get_connection() as conn:
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE filename = %s",
            ("015_real_data_model.sql",),
        ).fetchone()
        existing = {
            row[0] for row in conn.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name LIKE 'real_%'"""
            ).fetchall()
        }
        missing = EXPECTED_TABLES - existing
        if not applied or missing:
            raise SystemExit(f"Migration verification failed; missing tables: {sorted(missing)}")
        creators = conn.execute("SELECT count(*) FROM real_creator_accounts").fetchone()[0]
        companies = conn.execute("SELECT count(*) FROM real_companies").fetchone()[0]
        print(f"Migration 015 applied; {len(existing)} real-data tables present.")
        print(f"Real creator accounts: {creators}; real companies: {companies}.")


if __name__ == "__main__":
    main()
