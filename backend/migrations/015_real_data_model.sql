CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS real_creator_identities (
    id BIGSERIAL PRIMARY KEY,
    identity_key TEXT UNIQUE,
    display_name TEXT NOT NULL,
    identity_type TEXT NOT NULL DEFAULT 'person'
        CHECK (identity_type IN ('person', 'organization', 'unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS real_creator_accounts (
    id BIGSERIAL PRIMARY KEY,
    identity_id BIGINT REFERENCES real_creator_identities(id) ON DELETE SET NULL,
    platform TEXT NOT NULL,
    external_account_id TEXT NOT NULL,
    handle TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    profile_url TEXT,
    avatar_url TEXT,
    bio TEXT NOT NULL DEFAULT '',
    platform_category TEXT,
    city TEXT,
    country TEXT,
    language TEXT,
    verified BOOLEAN,
    followers BIGINT CHECK (followers IS NULL OR followers >= 0),
    engagement NUMERIC CHECK (engagement IS NULL OR engagement >= 0),
    average_views BIGINT CHECK (average_views IS NULL OR average_views >= 0),
    average_likes BIGINT CHECK (average_likes IS NULL OR average_likes >= 0),
    average_comments BIGINT CHECK (average_comments IS NULL OR average_comments >= 0),
    posts_per_week NUMERIC CHECK (posts_per_week IS NULL OR posts_per_week >= 0),
    account_age_years NUMERIC CHECK (account_age_years IS NULL OR account_age_years >= 0),
    tags TEXT[] NOT NULL DEFAULT '{}',
    search_document TEXT NOT NULL,
    embedding VECTOR(768) NOT NULL,
    embed_model TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    profile_observed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (platform, external_account_id)
);
CREATE INDEX IF NOT EXISTS real_creator_accounts_embedding_idx
    ON real_creator_accounts USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS real_creator_accounts_platform_idx
    ON real_creator_accounts (platform);
CREATE INDEX IF NOT EXISTS real_creator_accounts_identity_idx
    ON real_creator_accounts (identity_id) WHERE identity_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS real_creator_signals (
    creator_id BIGINT PRIMARY KEY REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    content_style TEXT,
    audience_age TEXT,
    audience_gender TEXT,
    audience_country TEXT,
    brand_collaborations TEXT[] NOT NULL DEFAULT '{}',
    reach_ratio NUMERIC CHECK (reach_ratio IS NULL OR reach_ratio >= 0),
    sponsored_ratio NUMERIC CHECK (sponsored_ratio IS NULL OR sponsored_ratio >= 0),
    growth_trend TEXT,
    audience_top_countries TEXT[] NOT NULL DEFAULT '{}',
    source_provider TEXT,
    observed_at TIMESTAMPTZ,
    confidence NUMERIC CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS real_creator_sources (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT,
    access_basis TEXT NOT NULL CHECK (access_basis IN (
        'public_api', 'creator_authorized', 'licensed_provider',
        'official_publication', 'manual_verified'
    )),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    observed_at TIMESTAMPTZ,
    payload_hash TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (provider, external_id)
);
CREATE INDEX IF NOT EXISTS real_creator_sources_account_idx
    ON real_creator_sources (account_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_creator_profile_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_creator_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    profile JSONB NOT NULL,
    UNIQUE (account_id, source_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS real_creator_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_creator_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start DATE,
    period_end DATE,
    followers BIGINT CHECK (followers IS NULL OR followers >= 0),
    following BIGINT CHECK (following IS NULL OR following >= 0),
    total_views BIGINT CHECK (total_views IS NULL OR total_views >= 0),
    total_likes BIGINT CHECK (total_likes IS NULL OR total_likes >= 0),
    post_count BIGINT CHECK (post_count IS NULL OR post_count >= 0),
    video_count BIGINT CHECK (video_count IS NULL OR video_count >= 0),
    average_views NUMERIC CHECK (average_views IS NULL OR average_views >= 0),
    median_views NUMERIC CHECK (median_views IS NULL OR median_views >= 0),
    average_likes NUMERIC CHECK (average_likes IS NULL OR average_likes >= 0),
    average_comments NUMERIC CHECK (average_comments IS NULL OR average_comments >= 0),
    engagement_rate NUMERIC CHECK (engagement_rate IS NULL OR engagement_rate >= 0),
    posts_per_week NUMERIC CHECK (posts_per_week IS NULL OR posts_per_week >= 0),
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    metric_definitions JSONB NOT NULL DEFAULT '{}'::JSONB,
    CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start)
);
CREATE INDEX IF NOT EXISTS real_creator_metrics_recent_idx
    ON real_creator_metric_snapshots (account_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_creator_audience_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_creator_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start DATE,
    period_end DATE,
    age_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    gender_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    country_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    language_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    confidence NUMERIC CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS real_creator_audience_recent_idx
    ON real_creator_audience_snapshots (account_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_creator_content_items (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_creator_sources(id) ON DELETE CASCADE,
    external_content_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_url TEXT,
    title TEXT,
    text TEXT,
    language TEXT,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, external_content_id)
);
CREATE INDEX IF NOT EXISTS real_creator_content_recent_idx
    ON real_creator_content_items (account_id, published_at DESC);

CREATE TABLE IF NOT EXISTS real_creator_content_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    content_id BIGINT NOT NULL REFERENCES real_creator_content_items(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_creator_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    views BIGINT CHECK (views IS NULL OR views >= 0),
    likes BIGINT CHECK (likes IS NULL OR likes >= 0),
    comments BIGINT CHECK (comments IS NULL OR comments >= 0),
    shares BIGINT CHECK (shares IS NULL OR shares >= 0),
    saves BIGINT CHECK (saves IS NULL OR saves >= 0),
    metric_definitions JSONB NOT NULL DEFAULT '{}'::JSONB
);
CREATE INDEX IF NOT EXISTS real_creator_content_metrics_recent_idx
    ON real_creator_content_metric_snapshots (content_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_creator_topic_signals (
    id BIGSERIAL PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES real_creator_accounts(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    confidence NUMERIC CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    method TEXT NOT NULL,
    model_version TEXT,
    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (account_id, topic, method, observed_at)
);

CREATE TABLE IF NOT EXISTS real_companies (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    canonical_domain TEXT,
    legal_name TEXT,
    registration_jurisdiction TEXT,
    registration_id TEXT,
    website TEXT,
    description TEXT NOT NULL DEFAULT '',
    industry TEXT,
    company_type TEXT,
    city TEXT,
    country TEXT,
    founded_year INTEGER CHECK (founded_year IS NULL OR founded_year BETWEEN 1600 AND 2200),
    headcount INTEGER CHECK (headcount IS NULL OR headcount >= 0),
    funding_stage TEXT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    search_document TEXT NOT NULL,
    embedding VECTOR(768) NOT NULL,
    embed_model TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    profile_observed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (registration_jurisdiction, registration_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS real_companies_domain_unique_idx
    ON real_companies (lower(canonical_domain)) WHERE canonical_domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS real_companies_embedding_idx
    ON real_companies USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS real_company_signals (
    company_id BIGINT PRIMARY KEY REFERENCES real_companies(id) ON DELETE CASCADE,
    seniority_mix TEXT,
    department_mix TEXT[] NOT NULL DEFAULT '{}',
    tech_stack TEXT[] NOT NULL DEFAULT '{}',
    buying_signals TEXT[] NOT NULL DEFAULT '{}',
    growth_trend TEXT,
    growth_rate NUMERIC,
    hiring_intensity NUMERIC CHECK (hiring_intensity IS NULL OR hiring_intensity >= 0),
    top_markets TEXT[] NOT NULL DEFAULT '{}',
    source_provider TEXT,
    observed_at TIMESTAMPTZ,
    confidence NUMERIC CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS real_company_sources (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES real_companies(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT,
    access_basis TEXT NOT NULL CHECK (access_basis IN (
        'public_api', 'company_published', 'registry', 'licensed_provider', 'manual_verified'
    )),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    observed_at TIMESTAMPTZ,
    payload_hash TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (provider, external_id)
);
CREATE INDEX IF NOT EXISTS real_company_sources_company_idx
    ON real_company_sources (company_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_company_profile_snapshots (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES real_companies(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_company_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    profile JSONB NOT NULL,
    UNIQUE (company_id, source_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS real_company_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES real_companies(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_company_sources(id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    headcount INTEGER CHECK (headcount IS NULL OR headcount >= 0),
    headcount_low INTEGER CHECK (headcount_low IS NULL OR headcount_low >= 0),
    headcount_high INTEGER CHECK (headcount_high IS NULL OR headcount_high >= 0),
    headcount_growth_rate NUMERIC,
    revenue_low NUMERIC(24, 2) CHECK (revenue_low IS NULL OR revenue_low >= 0),
    revenue_high NUMERIC(24, 2) CHECK (revenue_high IS NULL OR revenue_high >= 0),
    revenue_currency TEXT,
    revenue_period TEXT,
    monthly_web_visits BIGINT CHECK (monthly_web_visits IS NULL OR monthly_web_visits >= 0),
    open_roles INTEGER CHECK (open_roles IS NULL OR open_roles >= 0),
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    confidence NUMERIC CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CHECK (headcount_low IS NULL OR headcount_high IS NULL OR headcount_high >= headcount_low),
    CHECK (revenue_low IS NULL OR revenue_high IS NULL OR revenue_high >= revenue_low)
);
CREATE INDEX IF NOT EXISTS real_company_metrics_recent_idx
    ON real_company_metric_snapshots (company_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS real_company_funding_rounds (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES real_companies(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_company_sources(id) ON DELETE CASCADE,
    external_round_id TEXT NOT NULL,
    round_type TEXT NOT NULL,
    announced_at DATE,
    amount NUMERIC(24, 2) CHECK (amount IS NULL OR amount >= 0),
    currency TEXT,
    post_money_valuation NUMERIC(24, 2) CHECK (post_money_valuation IS NULL OR post_money_valuation >= 0),
    investors JSONB NOT NULL DEFAULT '[]'::JSONB,
    source_url TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (source_id, external_round_id)
);
CREATE INDEX IF NOT EXISTS real_company_funding_recent_idx
    ON real_company_funding_rounds (company_id, announced_at DESC);

CREATE TABLE IF NOT EXISTS real_company_job_postings (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT NOT NULL REFERENCES real_companies(id) ON DELETE CASCADE,
    source_id BIGINT NOT NULL REFERENCES real_company_sources(id) ON DELETE CASCADE,
    external_job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    location TEXT,
    employment_type TEXT,
    workplace_type TEXT,
    posted_at TIMESTAMPTZ,
    valid_through TIMESTAMPTZ,
    source_url TEXT NOT NULL,
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (source_id, external_job_id)
);
CREATE INDEX IF NOT EXISTS real_company_jobs_open_idx
    ON real_company_job_postings (company_id, posted_at DESC) WHERE is_open;

CREATE TABLE IF NOT EXISTS real_ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    corpus TEXT NOT NULL CHECK (corpus IN ('creator', 'company')),
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
    records_created INTEGER NOT NULL DEFAULT 0 CHECK (records_created >= 0),
    records_updated INTEGER NOT NULL DEFAULT 0 CHECK (records_updated >= 0),
    records_failed INTEGER NOT NULL DEFAULT 0 CHECK (records_failed >= 0),
    error_summary TEXT
);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'real_creator_identities', 'real_creator_accounts', 'real_creator_signals', 'real_creator_sources',
        'real_creator_profile_snapshots', 'real_creator_metric_snapshots',
        'real_creator_audience_snapshots', 'real_creator_content_items',
        'real_creator_content_metric_snapshots', 'real_creator_topic_signals',
        'real_companies', 'real_company_signals', 'real_company_sources', 'real_company_profile_snapshots',
        'real_company_metric_snapshots', 'real_company_funding_rounds',
        'real_company_job_postings', 'real_ingestion_runs'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON %I FROM anon', table_name);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON %I FROM authenticated', table_name);
        END IF;
    END LOOP;
END $$;
