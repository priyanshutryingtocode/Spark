"""Import source-attributed creator and company data into isolated real_* tables.

Sources: Verified Handles (CC0), Wikidata structured data (CC0), and PBC Index
(CC BY 4.0). Wikipedia-derived creator descriptions and profile images are not
copied. Platform metrics stay null unless a licensed source provides them.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config
from src.corpora import content_hash
from src.embeddings import embed_documents
from src.real_data import RealDataRepository


VH_BULK_URL = "https://verifiedhandles.org/data/verified-handles-latest.jsonl.gz"
PBC_API = "https://pbcindex.com/api/companies"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "SparkRealData/0.1 (provider-neutral data import; contact via project repository)"
CREATOR_TERMS = (
    "youtuber", "tiktoker", "content creator", "social media personality", "internet personality",
    "influencer", "streamer", "vlogger", "video blogger", "podcaster", "digital creator",
    "twitch personality", "gaming personality", "online personality", "actor", "actress",
    "musician", "singer", "rapper", "comedian", "model", "athlete", "chef", "cook",
    "journalist", "author", "writer", "artist", "television personality", "radio personality",
    "fashion designer", "beauty pageant", "professional wrestler", "esports player",
)
PLATFORM_NAMES = {
    "youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok",
    "threads": "Threads", "twitter": "X", "bluesky": "Bluesky",
    "twitch": "Twitch", "facebook": "Facebook", "snapchat": "Snapchat",
}
PLATFORM_ORDER = ("youtube", "tiktok", "instagram", "twitch", "threads", "twitter", "bluesky", "facebook", "snapchat")
FOLLOWER_QUALIFIERS = {
    "youtube": ("P2397", "P11245"), "tiktok": ("P7085",), "instagram": ("P2003",),
    "twitch": ("P5797",), "threads": ("P11892",), "twitter": ("P2002", "P6552"),
    "facebook": ("P2013", "P4003"), "snapchat": ("P2984",),
}


def get_json(url: str, *, user_agent: str = USER_AGENT, attempts: int = 3) -> dict:
    for attempt in range(attempts):
        request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
            api_error = payload.get("error") if isinstance(payload, dict) else None
            if api_error:
                if api_error.get("code") == "maxlag" and attempt + 1 < attempts:
                    time.sleep(max(2, int(float(api_error.get("lag", 3))) + 1))
                    continue
                raise RuntimeError(f"Public API error from {url}: {api_error.get('code', 'unknown')}")
            return payload
        except HTTPError as error:
            if error.code == 429 and attempt + 1 < attempts:
                delay = int(error.headers.get("Retry-After", "3"))
                time.sleep(max(1, delay))
                continue
            raise
        except (TimeoutError, URLError):
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not fetch {url}")


def get_directory_creators(identity_limit: int) -> list[dict]:
    preferred: list[tuple[int, dict]] = []
    other_video_creators: list[tuple[int, dict]] = []
    chunk_size = 3_000_000
    with tempfile.TemporaryFile() as archive:
        start = 0
        total = None
        while total is None or start < total:
            end = start + chunk_size - 1
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "application/gzip",
                "Range": f"bytes={start}-{end}",
            }
            request = Request(VH_BULK_URL, headers=headers)
            with urlopen(request, timeout=60) as response:
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if response.status != 206 or not match or int(match.group(1)) != start:
                    raise RuntimeError("Verified Handles bulk snapshot did not honor the requested byte range")
                actual_end, response_total = int(match.group(2)), int(match.group(3))
                if total is not None and total != response_total:
                    raise RuntimeError("Verified Handles bulk snapshot changed during download")
                total = response_total
                payload = response.read()
                if len(payload) != actual_end - start + 1:
                    raise RuntimeError(f"Incomplete Verified Handles range starting at byte {start}")
                archive.write(payload)
            start = actual_end + 1

        archive.seek(0)
        with gzip.GzipFile(fileobj=archive) as snapshot:
            for line in snapshot:
                item = json.loads(line)
                if item.get("type") != "person":
                    continue
                qid = item.get("qid")
                if not re.fullmatch(r"Q\d+", qid or ""):
                    continue
                entity = {
                    "vhid": item["vhid"], "short": item.get("short"), "title": item.get("title", ""),
                    "subtitle": item.get("subtitle"), "entity_type": item.get("type"),
                    "entity_kind": item.get("kind"), "verified": item.get("verified"),
                    "claimed": item.get("claimed"), "qid": qid, "url": item.get("url"),
                    "updated_at": item.get("updated_at"), "handles": item.get("handles", []),
                }
                accounts = creator_accounts(entity)
                if not accounts:
                    continue
                source_text = " ".join((entity.get("subtitle") or "", entity.get("entity_kind") or "")).lower()
                matches_creator_term = any(term in source_text for term in CREATOR_TERMS)
                has_video_platform = any(account["platform"] in {"YouTube", "TikTok", "Twitch"} for account in accounts)
                if not matches_creator_term and not has_video_platform:
                    continue
                score = (
                    100 * matches_creator_term
                    + 12 * len(accounts)
                    + 8 * sum(account["platform"] in {"YouTube", "TikTok", "Twitch"} for account in accounts)
                    + 4 * bool(entity.get("claimed"))
                )
                row = (score, entity)
                (preferred if matches_creator_term else other_video_creators).append(row)

    preferred.sort(key=lambda row: (-row[0], row[1]["title"].casefold(), row[1]["vhid"]))
    other_video_creators.sort(key=lambda row: (-row[0], row[1]["title"].casefold(), row[1]["vhid"]))
    selected = (preferred + other_video_creators)[:identity_limit]
    return [entity for _, entity in selected]


def _wikidata_claim_ids(entity: dict, property_id: str) -> list[str]:
    values = []
    for claim in entity.get("claims", {}).get(property_id, []):
        value = (claim.get("mainsnak", {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and re.fullmatch(r"Q\d+", value.get("id", "")):
            values.append(value["id"])
    return values


def get_wikidata_facts(entities: list[dict]) -> dict[str, dict]:
    qids: dict[str, str] = {}
    for entity in entities:
        qid = entity.get("qid") or next((h.get("value") for h in entity.get("handles", [])
                   if h.get("platform") == "wikidata" and re.fullmatch(r"Q\d+", h.get("value", ""))), None)
        if qid:
            qids[entity["vhid"]] = qid
    if not qids:
        return {}

    entities_by_qid: dict[str, dict] = {}
    for start in range(0, len(qids), 40):
        batch = list(qids.values())[start:start + 40]
        query = urlencode({
            "action": "wbgetentities", "ids": "|".join(batch), "props": "labels|descriptions|claims",
            "languages": "en", "format": "json", "maxlag": 10,
        })
        response = get_json(f"{WIKIDATA_API}?{query}")
        entities_by_qid.update(response.get("entities", {}))

    occupation_ids = sorted({
        qid for wd_entity in entities_by_qid.values()
        for qid in _wikidata_claim_ids(wd_entity, "P106")
    })
    place_ids = sorted({
        qid for wd_entity in entities_by_qid.values()
        for prop in ("P19", "P27", "P1412")
        for qid in _wikidata_claim_ids(wd_entity, prop)
    })
    labels: dict[str, str] = {}
    for start in range(0, len(set(occupation_ids + place_ids)), 40):
        batch = sorted(set(occupation_ids + place_ids))[start:start + 40]
        if not batch:
            continue
        query = urlencode({"action": "wbgetentities", "ids": "|".join(batch), "props": "labels",
                           "languages": "en", "format": "json", "maxlag": 10})
        response = get_json(f"{WIKIDATA_API}?{query}")
        labels.update({
            qid: data.get("labels", {}).get("en", {}).get("value", qid)
            for qid, data in response.get("entities", {}).items()
        })

    facts = {}
    for vhid, qid in qids.items():
        wd_entity = entities_by_qid.get(qid, {})
        description = wd_entity.get("descriptions", {}).get("en", {}).get("value", "")
        occupations = list(dict.fromkeys(
            labels.get(occupation, occupation) for occupation in _wikidata_claim_ids(wd_entity, "P106")
        ))
        facts[vhid] = {
            "qid": qid,
            "description": description,
            "occupations": occupations,
            "birth_places": list(dict.fromkeys(labels.get(item, item) for item in _wikidata_claim_ids(wd_entity, "P19"))),
            "citizenships": list(dict.fromkeys(labels.get(item, item) for item in _wikidata_claim_ids(wd_entity, "P27"))),
            "languages": list(dict.fromkeys(labels.get(item, item) for item in _wikidata_claim_ids(wd_entity, "P1412"))),
            "follower_claims": wd_entity.get("claims", {}).get("P8687", []),
        }
    return facts


def creator_accounts(entity: dict) -> list[dict]:
    handles = [h for h in entity.get("handles", []) if h.get("category") == "social" and h.get("value")]
    by_platform: dict[str, dict] = {}
    for handle in handles:
        platform = handle.get("platform")
        if platform in {"youtube_channel", "youtube_handle"}:
            by_platform.setdefault("youtube", {})[platform] = handle
        elif platform in PLATFORM_NAMES:
            by_platform.setdefault(platform, handle)

    result = []
    for platform in PLATFORM_ORDER:
        handle_data = by_platform.get(platform)
        if not handle_data:
            continue
        if platform == "youtube":
            channel = handle_data.get("youtube_channel")
            username = handle_data.get("youtube_handle")
            selected = channel or username
            external_id = channel.get("value") if channel else username.get("value")
            handle_value = username.get("value") if username else (entity.get("short") or external_id)
            profile_url = selected.get("url") or (username or {}).get("url")
            source_handles = [item for item in (channel, username) if item]
            verified = any(item.get("verified", False) for item in source_handles)
        else:
            selected = handle_data
            external_id = selected["value"]
            handle_value = selected.get("display") or selected["value"]
            profile_url = selected.get("url")
            source_handles = [selected]
            verified = selected.get("verified", False)
        if not external_id or not profile_url:
            continue
        result.append({
            "platform": PLATFORM_NAMES[platform], "external_account_id": str(external_id),
            "handle": str(handle_value).lstrip("@"), "profile_url": profile_url,
            "verified": bool(verified), "source_handles": source_handles,
        })
        if len(result) == 2:
            break
    return result


def latest_platform_followers(account: dict, facts: dict) -> dict | None:
    platform = next((key for key, label in PLATFORM_NAMES.items() if label == account["platform"]), None)
    qualifier_ids = FOLLOWER_QUALIFIERS.get(platform, ())
    if not qualifier_ids:
        return None
    expected_ids = {
        str(value).lstrip("@")
        for item in account.get("source_handles", [])
        for value in (item.get("value"), item.get("display"))
        if value
    } | {account["external_account_id"], account["handle"]}
    observations = []
    for claim in facts.get("follower_claims", []):
        main_value = (claim.get("mainsnak", {}).get("datavalue") or {}).get("value")
        try:
            count = int(float(str(main_value.get("amount", "")).lstrip("+")))
        except (AttributeError, TypeError, ValueError):
            continue
        if count < 0:
            continue
        qualifiers = claim.get("qualifiers", {})
        account_values = {
            str((item.get("datavalue") or {}).get("value", "")).lstrip("@")
            for qualifier in qualifier_ids for item in qualifiers.get(qualifier, [])
        }
        if not expected_ids.intersection(account_values):
            continue
        time_claims = qualifiers.get("P585", [])
        time_value = (time_claims[0].get("datavalue") or {}).get("value", {}) if time_claims else {}
        raw_time = time_value.get("time", "")
        try:
            observed_at = datetime.fromisoformat(raw_time.lstrip("+").replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            observed_at = observed_at.astimezone(timezone.utc)
        except ValueError:
            continue
        if (datetime.now(timezone.utc) - observed_at).days > 730:
            continue
        observations.append({"followers": count, "observed_at": observed_at, "claim": claim})
    return max(observations, key=lambda item: item["observed_at"]) if observations else None


def company_candidates(limit: int, existing_slugs: set[str] | None = None) -> list[dict]:
    data = get_json(f"{PBC_API}?{urlencode({'status': 'private'})}")
    candidates = [company for company in data.get("companies", [])
                  if company.get("verification_status") == "verified"
                  and 2018 <= (company.get("founded_year") or 0) <= date.today().year
                  and company.get("website") and company.get("offerings") and company.get("categories")]
    candidates.sort(key=lambda c: (c.get("founded_year", 0), c.get("name", "")), reverse=True)

    existing_slugs = existing_slugs or set()
    existing = [company for company in candidates if company.get("slug") in existing_slugs]
    selected = existing[:limit]
    remaining = max(0, limit - len(selected))
    by_industry: Counter[str] = Counter()
    fresh_candidates = [company for company in candidates if company.get("slug") not in existing_slugs]
    categories = {company["categories"][0] for company in fresh_candidates}
    max_per_category = max(2, (remaining + len(categories) - 1) // max(1, len(categories)))
    for company in fresh_candidates:
        industry = company["categories"][0]
        if by_industry[industry] >= max_per_category:
            continue
        selected.append(company)
        by_industry[industry] += 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_slugs = {company["slug"] for company in selected}
        selected.extend(company for company in fresh_candidates if company["slug"] not in selected_slugs
                        and len(selected) < limit)
    return selected


def company_document(company: dict) -> str:
    headquarters = company.get("headquarters") or {}
    location = ", ".join(value for value in (
        headquarters.get("city"), headquarters.get("state"), headquarters.get("country")
    ) if value)
    purpose = company.get("public_benefit_purpose") or ""
    categories = ", ".join(company.get("categories", []))
    return " ".join(part for part in (
        f"{company['name']} is an early-stage private public-benefit company.",
        f"Industry: {categories}.", f"Location: {location}." if location else "",
        company.get("offerings", ""), f"Stated public benefit: {purpose}." if purpose else "",
    ) if part).strip()


def canonical_company_domain(website: str) -> str | None:
    parsed = urlparse(website)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host in {"bcorporation.net", "pbcindex.com"}:
        return None
    return host or None


def to_company_profile(company: dict, embedding) -> tuple[dict, dict]:
    website = company["website"]
    domain = canonical_company_domain(website)
    headquarters = company.get("headquarters") or {}
    categories = list(dict.fromkeys(company.get("categories", [])))
    purpose = company.get("public_benefit_purpose") or ""
    offering = company.get("offerings", "").strip()
    description_parts = [offering]
    if purpose:
        description_parts.append(f"Stated public benefit: {purpose}")
    description_parts.append("Source attribution: PBC Index (CC BY 4.0), https://pbcindex.com.")
    description = " ".join(part for part in description_parts if part)
    document = company_document(company)
    company_profile = {
        "name": company["name"], "canonical_domain": domain, "legal_name": company.get("legal_name"),
        "registration_jurisdiction": company.get("statutory_jurisdiction"),
        "website": website, "description": description, "industry": categories[0] if categories else "",
        "company_type": company.get("statutory_form") or ", ".join(company.get("governance_types", [])),
        "city": headquarters.get("city"), "country": headquarters.get("country"),
        "founded_year": company.get("founded_year"), "headcount": None, "funding_stage": None,
        "tags": categories + list(company.get("governance_types", [])),
        "search_document": document, "embedding": embedding, "embed_model": config.EMBED_MODEL,
        "content_hash": content_hash(document), "is_active": True,
    }
    source = {
        "provider": "pbc_index", "external_id": company["slug"],
        "source_url": f"https://pbcindex.com/api/companies/{company['slug']}",
        "access_basis": "licensed_provider", "observed_at": None,
        "payload_hash": content_hash(json.dumps(company, sort_keys=True, ensure_ascii=False)),
        "raw_payload": {
            "license": "CC BY 4.0", "attribution": "PBC Index, https://pbcindex.com",
            "retrieved_at": date.today().isoformat(), "source_records": company.get("sources", []),
            "verification_status": company.get("verification_status"),
            "governance_types": company.get("governance_types", []),
            "entry": company,
        },
    }
    if company.get("last_updated"):
        try:
            observed = datetime.fromisoformat(company["last_updated"])
            company_profile["profile_observed_at"] = (
                observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
            )
        except ValueError:
            pass
    return company_profile, source


def existing_real_profile_keys() -> tuple[set[tuple[str, str]], int, set[str], int]:
    from src.vector_store import get_connection

    with get_connection() as conn:
        creator_keys = {
            (row[0], row[1]) for row in conn.execute(
                "SELECT platform, external_account_id FROM real_creator_accounts"
            ).fetchall()
        }
        creator_count = conn.execute("SELECT count(*) FROM real_creator_accounts").fetchone()[0]
        company_slugs = {
            row[0] for row in conn.execute(
                "SELECT external_id FROM real_company_sources WHERE provider = 'pbc_index'"
            ).fetchall()
        }
        company_count = conn.execute("SELECT count(*) FROM real_companies").fetchone()[0]
    return creator_keys, creator_count, company_slugs, company_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creators", type=int, default=250, help="target searchable creator accounts in the real corpus")
    parser.add_argument("--companies", type=int, default=250, help="target unique verified private PBCs in the real corpus")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report selection without embedding or writing")
    args = parser.parse_args()
    if args.creators < 0 or args.companies < 0:
        parser.error("limits must be non-negative")
    if not args.dry_run and (args.creators or args.companies) and not config.GEMINI_API_KEY:
        parser.error("GEMINI_API_KEY is required to embed searchable profiles")

    existing_creator_keys, existing_creator_count, existing_company_slugs, existing_company_count = (
        existing_real_profile_keys() if not args.dry_run else (set(), 0, set(), 0)
    )
    creators = get_directory_creators(args.creators) if args.creators else []
    facts = get_wikidata_facts(creators)
    existing_creator_rows = []
    new_creator_rows = []
    for entity in creators:
        wikidata = facts.get(entity["vhid"], {})
        accounts = creator_accounts(entity)
        for account in accounts:
            account_key = (account["platform"], account["external_account_id"])
            if account_key not in existing_creator_keys and len(new_creator_rows) >= max(0, args.creators - existing_creator_count):
                continue
            name = entity.get("title", "").strip()
            occupations = wikidata.get("occupations", [])
            description = wikidata.get("description", "").strip()
            follower_observation = latest_platform_followers(account, wikidata)
            place = (wikidata.get("birth_places") or [None])[0]
            country = (wikidata.get("citizenships") or [None])[0]
            language = (wikidata.get("languages") or [None])[0]
            document = " ".join(part for part in (
                f"Creator {name} on {account['platform']}.",
                f"Public profile description: {description}." if description else "",
                f"Occupations: {', '.join(occupations)}." if occupations else "",
                f"Birthplace: {place}." if place else "",
                f"Citizenship: {country}." if country else "",
                f"Languages: {language}." if language else "",
                f"Account handle: @{account['handle']}.",
            ) if part)
            row = {"entity": entity, "facts": wikidata, "account": account,
                   "name": name, "description": description, "occupations": occupations,
                   "place": place, "country": country, "language": language,
                   "follower_observation": follower_observation, "document": document}
            (existing_creator_rows if account_key in existing_creator_keys else new_creator_rows).append(row)
    creator_rows = existing_creator_rows + new_creator_rows[:max(0, args.creators - existing_creator_count)]

    candidates = company_candidates(args.companies, existing_company_slugs) if args.companies else []
    existing_companies = [company for company in candidates if company.get("slug") in existing_company_slugs]
    new_company_capacity = max(0, args.companies - existing_company_count)
    companies = existing_companies + [company for company in candidates
                                      if company.get("slug") not in existing_company_slugs][:new_company_capacity]
    selected_creator_identities = {row["entity"]["vhid"] for row in creator_rows}
    print(f"Selected {len(selected_creator_identities)} creator identities / {len(creator_rows)} platform accounts.")
    print(f"Selected {len(companies)} verified private public-benefit companies founded since 2018.")
    if creator_rows:
        print("Creator field coverage: " + ", ".join((
            f"verified account {sum(row['account']['verified'] for row in creator_rows)}/{len(creator_rows)}",
            f"bio {sum(bool(row['description']) for row in creator_rows)}/{len(creator_rows)}",
            f"occupation {sum(bool(row['occupations']) for row in creator_rows)}/{len(creator_rows)}",
            f"location {sum(bool(row['place'] or row['country']) for row in creator_rows)}/{len(creator_rows)}",
            f"language {sum(bool(row['language']) for row in creator_rows)}/{len(creator_rows)}",
            f"dated followers {sum(bool(row['follower_observation']) for row in creator_rows)}/{len(creator_rows)}",
        )))
    if companies:
        print("Company field coverage: " + ", ".join((
            f"website {sum(bool(c.get('website')) for c in companies)}/{len(companies)}",
            f"offering {sum(bool(c.get('offerings')) for c in companies)}/{len(companies)}",
            f"benefit purpose {sum(bool(c.get('public_benefit_purpose')) for c in companies)}/{len(companies)}",
            f"headquarters {sum(bool(c.get('headquarters')) for c in companies)}/{len(companies)}",
            f"legal form {sum(bool(c.get('statutory_form') or c.get('governance_types')) for c in companies)}/{len(companies)}",
            "headcount/funding stage are not reported by this source",
        )))
    if args.dry_run:
        for row in creator_rows[:8]:
            print(f"  Creator: {row['name']} — {row['account']['platform']} @{row['account']['handle']}")
        for company in companies[:8]:
            industry = ", ".join(company.get("categories", [])[:2])
            print(f"  Company: {company['name']} ({company.get('founded_year')}, {industry})")
        print("Dry run: nothing embedded or written.")
        return

    documents = [row["document"] for row in creator_rows] + [company_document(company) for company in companies]
    embeddings = embed_documents(documents)
    creator_embeddings = embeddings[:len(creator_rows)]
    company_embeddings = embeddings[len(creator_rows):]
    repository = RealDataRepository()
    imported_creators = 0
    follower_snapshots = 0
    creator_topics = 0
    for row, embedding in zip(creator_rows, creator_embeddings):
        entity, account, facts = row["entity"], row["account"], row["facts"]
        vhid = entity["vhid"]
        observed_at = datetime.now(timezone.utc)
        handle_ids = [f"{item['platform']}:{item['value']}" for item in account["source_handles"]]
        provider_id = f"{vhid}:{account['platform'].lower()}:{account['external_account_id']}"
        safe_entry = {
            "vhid": vhid, "title": entity.get("title"), "short": entity.get("short"),
            "url": entity.get("url"), "entity_type": entity.get("entity_type"),
            "verified": entity.get("verified"), "claimed": entity.get("claimed"),
            "qid": facts.get("qid"), "handles": account["source_handles"],
        }
        follower = row["follower_observation"]
        payload = {
            "identity": {"identity_key": vhid, "display_name": entity.get("title", ""), "identity_type": "person"},
            "platform": account["platform"], "external_account_id": account["external_account_id"],
            "handle": account["handle"], "name": row["name"], "profile_url": account["profile_url"],
            "bio": row["description"], "platform_category": ", ".join(row["occupations"][:4]),
            "city": None, "country": None, "language": row["language"],
            "verified": account["verified"], "followers": follower["followers"] if follower else None,
            "tags": row["occupations"],
            "search_document": row["document"], "embedding": embedding,
            "embed_model": config.EMBED_MODEL, "content_hash": content_hash(row["document"]),
            "profile_observed_at": observed_at,
        }
        directory_source = {
            "provider": "verified_handles", "external_id": provider_id,
            "source_url": entity.get("url"), "access_basis": "public_api", "observed_at": observed_at,
            "raw_payload": {
                "license": "CC0 1.0", "directory_entry": safe_entry, "directory_handle_ids": handle_ids,
                "note": "Verified Handles descriptions, snippets, and images intentionally excluded.",
            },
        }
        repository.upsert_creator(payload, directory_source)

        wikidata_source = {
            "provider": "wikidata", "external_id": f"{facts['qid']}:{account['platform']}:{account['external_account_id']}",
            "source_url": f"https://www.wikidata.org/entity/{facts['qid']}",
            "access_basis": "public_api", "observed_at": follower["observed_at"] if follower else observed_at,
            "raw_payload": {
                "license": "CC0 1.0", "qid": facts["qid"], "description": row["description"],
                "occupation_labels": row["occupations"], "birth_places": facts.get("birth_places", []),
                "citizenships": facts.get("citizenships", []), "languages": facts.get("languages", []),
                "social_media_follower_claim": follower["claim"] if follower else None,
            },
        }
        metrics = ({
            "observed_at": follower["observed_at"], "followers": follower["followers"],
            "metric_definitions": {
                "followers": f"Wikidata P8687, matched to account qualifier; reported {follower['observed_at'].date().isoformat()}."
            },
        } if follower else None)
        topics = [{
            "topic": occupation, "confidence": 0.95, "method": "wikidata_occupation",
            "model_version": "Wikidata P106", "evidence": {"qid": facts["qid"], "property": "P106"},
            "observed_at": observed_at,
        } for occupation in row["occupations"]]
        repository.upsert_creator(payload, wikidata_source, metrics=metrics, topics=topics)
        imported_creators += 1
        follower_snapshots += int(follower is not None)
        creator_topics += len(topics)

    imported_companies = 0
    for company, embedding in zip(companies, company_embeddings):
        profile, source = to_company_profile(company, embedding)
        repository.upsert_company(profile, source)
        imported_companies += 1

    imported_identity_count = len({row["entity"]["vhid"] for row in creator_rows})
    print(f"Imported {imported_creators} creator platform accounts across {imported_identity_count} identities.")
    print(f"Imported {imported_companies} companies.")
    print(f"Creator enrichment: {creator_topics} occupation topic signals; {follower_snapshots} dated platform-matched follower snapshots.")
    print("Unreported audience, engagement, reach and view metrics remain null.")
    print("Company facts: PBC Index CC BY 4.0; attribution is included in each profile and source record.")


if __name__ == "__main__":
    main()
