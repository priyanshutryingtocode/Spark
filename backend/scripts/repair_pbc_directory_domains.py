"""Split PBC Index companies previously merged on a shared directory domain."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.embeddings import embed_documents
from src.real_data import COMPANY_PROFILE_COLUMNS
from src.vector_store import get_connection
from scripts.import_open_real_data import company_document, to_company_profile


SOURCE_TABLES = (
    "real_company_profile_snapshots",
    "real_company_metric_snapshots",
    "real_company_funding_rounds",
    "real_company_job_postings",
)


def main() -> None:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT source.id, source.external_id, source.company_id, company.name,
                      source.raw_payload->'entry' AS entry
               FROM real_company_sources AS source
               JOIN real_companies AS company ON company.id = source.company_id
               WHERE source.provider = 'pbc_index'
                 AND lower(company.canonical_domain) IN ('bcorporation.net', 'pbcindex.com')"""
        ).fetchall()

    repairs = []
    for source_id, external_id, old_company_id, current_name, entry in rows:
        if not entry or entry.get("name", "").casefold() == current_name.casefold():
            continue
        embedding = embed_documents([company_document(entry)])[0]
        profile, _ = to_company_profile(entry, embedding)
        if profile["canonical_domain"] is not None:
            raise RuntimeError(f"Expected a directory URL for PBC record {external_id}")
        repairs.append((source_id, old_company_id, profile))

    for source_id, old_company_id, profile in repairs:
        with get_connection() as conn, conn.transaction():
            columns = tuple(key for key in profile if key in COMPANY_PROFILE_COLUMNS)
            placeholders = ", ".join(["%s"] * len(columns))
            new_company_id = conn.execute(
                f"INSERT INTO real_companies ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id",
                tuple(profile[column] for column in columns),
            ).fetchone()[0]
            for table in SOURCE_TABLES:
                conn.execute(
                    f"UPDATE {table} SET company_id = %s WHERE source_id = %s AND company_id = %s",
                    (new_company_id, source_id, old_company_id),
                )
            conn.execute(
                "UPDATE real_company_sources SET company_id = %s, fetched_at = NOW() WHERE id = %s",
                (new_company_id, source_id),
            )
            print(f"Split {profile['name']} ({external_id}) from shared directory domain.")

    print(f"Repaired {len(repairs)} company source records.")


if __name__ == "__main__":
    main()
