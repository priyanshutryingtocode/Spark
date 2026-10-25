CREATE TABLE IF NOT EXISTS saved_matches (
    id UUID PRIMARY KEY,
    owner_id UUID,
    run_id UUID NOT NULL,
    candidate_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('creator', 'prospect')),
    brief JSONB NOT NULL,
    candidate JSONB NOT NULL,
    ranked JSONB NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS saved_matches_owner_run_candidate_idx
    ON saved_matches (
        COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::UUID),
        run_id,
        candidate_id
    );

CREATE INDEX IF NOT EXISTS saved_matches_owner_kind_created_idx
    ON saved_matches (owner_id, kind, created_at DESC, id DESC);
