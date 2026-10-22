-- Account-level creator model. A person may own several independent accounts;
-- matching remains account-level so each account keeps its own audience and stats.
CREATE TABLE IF NOT EXISTS creator_identities (
    id BIGINT PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL
);

ALTER TABLE influencers
    ADD COLUMN IF NOT EXISTS identity_id BIGINT
        REFERENCES creator_identities(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS profile_url TEXT;

CREATE INDEX IF NOT EXISTS influencers_identity_id_idx
    ON influencers (identity_id) WHERE identity_id IS NOT NULL;

-- Provider identifiers are aliases for one canonical account. Keeping the raw
-- response here makes provider remapping possible without exposing it to search.
CREATE TABLE IF NOT EXISTS creator_account_sources (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_account_id TEXT NOT NULL,
    profile_url TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (provider, external_account_id)
);

CREATE INDEX IF NOT EXISTS creator_account_sources_account_idx
    ON creator_account_sources (account_id, provider);

CREATE TABLE IF NOT EXISTS creator_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    period_days INTEGER NOT NULL CHECK (period_days > 0),
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    followers BIGINT CHECK (followers IS NULL OR followers >= 0),
    average_views DOUBLE PRECISION CHECK (average_views IS NULL OR average_views >= 0),
    average_likes DOUBLE PRECISION CHECK (average_likes IS NULL OR average_likes >= 0),
    average_comments DOUBLE PRECISION CHECK (average_comments IS NULL OR average_comments >= 0),
    engagement_rate DOUBLE PRECISION CHECK (engagement_rate IS NULL OR engagement_rate >= 0),
    posts_per_week DOUBLE PRECISION CHECK (posts_per_week IS NULL OR posts_per_week >= 0),
    UNIQUE (account_id, provider, observed_at, period_days)
);

CREATE INDEX IF NOT EXISTS creator_metric_snapshots_recent_idx
    ON creator_metric_snapshots (account_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS creator_audience_snapshots (
    id BIGSERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    age_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    gender_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    country_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    language_distribution JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (account_id, provider, observed_at)
);

CREATE INDEX IF NOT EXISTS creator_audience_snapshots_recent_idx
    ON creator_audience_snapshots (account_id, observed_at DESC);

-- Fast current view used by search; the dated observation tables above retain
-- history and provenance. These values are nullable because providers differ.
ALTER TABLE creator_signals
    ADD COLUMN IF NOT EXISTS source_provider TEXT NOT NULL DEFAULT 'synthetic',
    ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION
        CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1);

DO $$
BEGIN
    ALTER TABLE creator_account_sources ENABLE ROW LEVEL SECURITY;
    ALTER TABLE creator_metric_snapshots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE creator_audience_snapshots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE creator_identities ENABLE ROW LEVEL SECURITY;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON creator_account_sources, creator_metric_snapshots,
            creator_audience_snapshots, creator_identities FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON creator_account_sources, creator_metric_snapshots,
            creator_audience_snapshots, creator_identities FROM authenticated;
    END IF;
END $$;
