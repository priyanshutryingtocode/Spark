"""Clear birthplaces and citizenships that were stored as current locations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import vector_store


def main() -> None:
    with vector_store.get_connection() as conn, conn.transaction():
        result = conn.execute(
            """UPDATE real_creator_accounts AS account
               SET city = NULL, country = NULL
               WHERE (account.city IS NOT NULL OR account.country IS NOT NULL)
                 AND EXISTS (
                     SELECT 1 FROM real_creator_sources AS source
                     WHERE source.account_id = account.id
                       AND source.provider = 'wikidata'
                       AND (source.raw_payload ? 'birth_places'
                            OR source.raw_payload ? 'citizenships')
                 )"""
        )
        print(f"Cleared non-current location fields from {result.rowcount} creator accounts.")


if __name__ == "__main__":
    main()
