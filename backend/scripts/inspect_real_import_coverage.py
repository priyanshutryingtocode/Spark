"""Report field coverage and duplicate keys for the isolated real-data corpus."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import vector_store


def main() -> None:
    with vector_store.get_connection() as conn:
        creators = conn.execute(
            """SELECT count(*), count(DISTINCT identity_id), count(bio), count(platform_category),
                      count(city), count(country), count(language), count(followers),
                      count(*) FILTER (WHERE verified)
               FROM real_creator_accounts"""
        ).fetchone()
        companies = conn.execute(
            """SELECT count(*), count(website), count(description), count(industry), count(city),
                      count(country), count(founded_year), count(headcount), count(funding_stage)
               FROM real_companies"""
        ).fetchone()
        metrics = conn.execute("SELECT count(*) FROM real_creator_metric_snapshots").fetchone()[0]
        topics = conn.execute("SELECT count(*) FROM real_creator_topic_signals").fetchone()[0]
        creator_sources = conn.execute("SELECT count(*) FROM real_creator_sources").fetchone()[0]
        company_sources = conn.execute("SELECT count(*) FROM real_company_sources").fetchone()[0]
        duplicates = conn.execute(
            """SELECT count(*) FROM (
                   SELECT platform, external_account_id FROM real_creator_accounts
                   GROUP BY platform, external_account_id HAVING count(*) > 1
               ) duplicate_keys"""
        ).fetchone()[0]

    print("Creator rows, identities, bio, category, city, country, language, followers, verified:", creators)
    print("Company rows, website, description, industry, city, country, founded, headcount, funding:", companies)
    print("Follower snapshots, occupation topics, creator sources, company sources, duplicate account keys:",
          metrics, topics, creator_sources, company_sources, duplicates)


if __name__ == "__main__":
    main()
