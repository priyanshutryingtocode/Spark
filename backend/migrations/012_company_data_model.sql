-- Canonical company identity, source aliases, operating observations, and
-- funding events. Prospects remain searchable companies; history is separate.
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS profile_url TEXT;

CREATE TABLE IF NOT EXISTS company_sources (
    id BIGSERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_company_id TEXT NOT NULL,
    profile_url TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (provider, external_company_id)
);
CREATE INDEX IF NOT EXISTS company_sources_company_idx
    ON company_sources (company_id, provider);

CREATE TABLE IF NOT EXISTS company_metric_snapshots (
    id BIGSERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    headcount INTEGER CHECK (headcount IS NULL OR headcount >= 0),
    headcount_low INTEGER CHECK (headcount_low IS NULL OR headcount_low >= 0),
    headcount_high INTEGER CHECK (headcount_high IS NULL OR headcount_high >= 0),
    headcount_growth_rate DOUBLE PRECISION,
    revenue_low NUMERIC(24, 2) CHECK (revenue_low IS NULL OR revenue_low >= 0),
    revenue_high NUMERIC(24, 2) CHECK (revenue_high IS NULL OR revenue_high >= 0),
    revenue_period TEXT,
    revenue_currency TEXT,
    monthly_web_visits BIGINT CHECK (monthly_web_visits IS NULL OR monthly_web_visits >= 0),
    open_roles INTEGER CHECK (open_roles IS NULL OR open_roles >= 0),
    sample_size INTEGER CHECK (sample_size IS NULL OR sample_size >= 0),
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    UNIQUE (company_id, provider, observed_at),
    CHECK (headcount_low IS NULL OR headcount_high IS NULL OR headcount_high >= headcount_low),
    CHECK (revenue_low IS NULL OR revenue_high IS NULL OR revenue_high >= revenue_low)
);
CREATE INDEX IF NOT EXISTS company_metric_snapshots_recent_idx
    ON company_metric_snapshots (company_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS company_funding_rounds (
    id BIGSERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_round_id TEXT NOT NULL,
    round_type TEXT NOT NULL,
    announced_at TIMESTAMPTZ,
    amount NUMERIC(24, 2) CHECK (amount IS NULL OR amount >= 0),
    currency TEXT,
    post_money_valuation NUMERIC(24, 2) CHECK (post_money_valuation IS NULL OR post_money_valuation >= 0),
    investors JSONB NOT NULL DEFAULT '[]'::JSONB,
    source_url TEXT,
    raw_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (provider, external_round_id)
);
CREATE INDEX IF NOT EXISTS company_funding_rounds_recent_idx
    ON company_funding_rounds (company_id, announced_at DESC);

ALTER TABLE prospect_signals
    ADD COLUMN IF NOT EXISTS source_provider TEXT NOT NULL DEFAULT 'synthetic',
    ADD COLUMN IF NOT EXISTS observed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION
        CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1);

DO $$
BEGIN
    ALTER TABLE company_sources ENABLE ROW LEVEL SECURITY;
    ALTER TABLE company_metric_snapshots ENABLE ROW LEVEL SECURITY;
    ALTER TABLE company_funding_rounds ENABLE ROW LEVEL SECURITY;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON company_sources, company_metric_snapshots,
            company_funding_rounds FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON company_sources, company_metric_snapshots,
            company_funding_rounds FROM authenticated;
    END IF;
END $$;
