-- Add a second searchable corpus: prospects (companies a business could sell to).
--
-- The same split migration 007 made for creators. `prospects` holds what a
-- company states about itself; `prospect_signals` holds what a third party
-- infers about it. The two have different refresh cadences and different trust
-- levels, and keeping them apart is what lets a signal be corrected without
-- re-embedding the company.
--
-- Column-to-signal mapping is deliberately parallel to creator_signals, so the
-- two corpora read as siblings rather than as two unrelated schemas:
--
--   seniority_mix          <- audience_age        who the audience is
--   department_mix         <- audience_gender     which groups exist
--   tech_stack             <- brand_collaborations what it already buys
--   buying_signals         <- content_style       what it appears to need
--   growth_trend           <- growth_trend
--   growth_rate            <- reach_ratio         a derived ratio, never copied
--   hiring_intensity       <- sponsored_ratio
--   top_markets            <- audience_top_countries
--
-- ONE DELIBERATE DIVERGENCE: growth_trend is citable for prospects, and so will
-- appear in Prospect.corpus_text, where its creator counterpart is display-only.
-- Whether a company is growing is a primary ICP-fit signal -- a shrinking
-- company is a poor lead whatever its industry -- and leaving it uncitable would
-- mean the ranker cannot weigh the one thing it most decides on. growth_rate,
-- hiring_intensity and top_markets stay out, matching the creator split.
--
-- VECTOR(768) is a literal because a .sql migration cannot interpolate
-- config.EMBED_DIMENSIONS. That is not silently wrong if the env var changes:
-- vector_store.assert_index_matches_config compares the live column width
-- against config.EMBED_DIMENSIONS on every boot and raises IndexModelMismatch
-- naming the offending table. That assertion is table-parameterised precisely so
-- a second corpus inherits the check.
--
-- NO INDEXES beyond the primary keys and the HNSW vector index. There is no
-- industry index because industry is not a filter: it is text the ranking model
-- judges, not a WHERE clause, and an index on an unfiltered column is the same
-- dead weight migration 008 removed from creator_signals. There is no
-- growth_trend index either, for that same reason -- every insert of a prospect
-- would pay to maintain an index no query could use.
--
-- This migration, and not vector_store._schema_sql, is the sole source of truth
-- for these tables. `influencers` is created by runtime DDL instead, which is
-- why a migrations-only database never had it; `prospects` deliberately does not
-- repeat that split, so init_schema is not extended to create it.

-- No migration created the pgvector extension before this one; only runtime
-- vector_store._schema_sql did, which meant a migrations-only replay could not
-- have produced a searchable corpus at all. pgvector is a *trusted* extension,
-- so CREATE privilege is sufficient and this does not need superuser. If the
-- role cannot install it the migration fails loudly here, which is the right
-- outcome -- a silent skip would leave a table that looks searchable and cannot
-- be queried.
CREATE EXTENSION IF NOT EXISTS vector;

-- What the company states about itself.
CREATE TABLE IF NOT EXISTS public.prospects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    headcount INTEGER NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    description TEXT NOT NULL,
    tags TEXT[] NOT NULL,
    website TEXT,
    founded_year INTEGER,
    funding_stage TEXT,
    embedding VECTOR(768) NOT NULL,
    -- Same two columns influencers carries, for the same reasons: which embedder
    -- produced a vector, and the hash of the text it was produced from, so a
    -- reindex can skip rows whose corpus text has not changed.
    embed_model TEXT,
    content_hash TEXT
);

-- Inferred about the company by a third party. Server-side only, same posture as
-- creator_signals.
CREATE TABLE IF NOT EXISTS public.prospect_signals (
    prospect_id INTEGER PRIMARY KEY
        REFERENCES public.prospects(id) ON DELETE CASCADE,
    seniority_mix TEXT,
    department_mix TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    tech_stack TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    buying_signals TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    growth_trend TEXT,
    -- headcount growth per year, recomputed from the row rather than copied, so
    -- a reader dividing headcount by headcount cannot catch it out. Mirrors why
    -- reach_ratio is derived rather than stored as a source figure.
    growth_rate DOUBLE PRECISION,
    -- Share of open roles that are growth or sales. The prospect-side analogue of
    -- sponsored_ratio: a leading indicator of budget, not of the outcome.
    hiring_intensity DOUBLE PRECISION,
    top_markets TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
);

CREATE INDEX IF NOT EXISTS prospects_embedding_idx
    ON public.prospects USING hnsw (embedding vector_cosine_ops);

-- Signals are server-side only: RLS on, and no grants to the browser roles. The
-- API connects directly as the table owner, so this does not affect it.
DO $$
BEGIN
    IF to_regclass('public.prospect_signals') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.prospect_signals ENABLE ROW LEVEL SECURITY';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON TABLE public.prospect_signals FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL ON TABLE public.prospect_signals FROM authenticated';
    END IF;
END $$;
