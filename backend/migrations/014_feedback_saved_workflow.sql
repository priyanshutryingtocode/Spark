ALTER TABLE saved_matches
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'to_review',
    ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE saved_matches
    DROP CONSTRAINT IF EXISTS saved_matches_status_check;
ALTER TABLE saved_matches
    ADD CONSTRAINT saved_matches_status_check
    CHECK (status IN ('to_review', 'contacted', 'in_conversation', 'partnered', 'passed'));

CREATE TABLE IF NOT EXISTS match_feedback (
    id UUID PRIMARY KEY,
    owner_id UUID,
    run_id UUID NOT NULL REFERENCES match_runs(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('creator', 'prospect')),
    rating TEXT NOT NULL CHECK (rating IN ('positive', 'negative')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS match_feedback_owner_run_candidate_idx
    ON match_feedback (
        COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::UUID),
        run_id,
        candidate_id
    );

CREATE INDEX IF NOT EXISTS match_feedback_owner_kind_created_idx
    ON match_feedback (owner_id, kind, created_at DESC);
