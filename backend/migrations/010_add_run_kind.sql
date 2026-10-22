-- Record which corpus a run searched, so one table can hold both.
--
-- `match_runs` predates the second corpus, and every row in it was a creator
-- run. `kind` defaults to 'creator', which backfills the existing rows from the
-- default rather than needing an UPDATE: adding a NOT NULL column with a DEFAULT
-- is a metadata-only operation on PostgreSQL 11+, so this does not rewrite the
-- table or lock it for the length of the data.
--
-- The column is deliberately NOT part of `brief`. `brief` is what the user
-- typed; `kind` is which body of records was searched. Keeping them apart means a
-- brief can be compared, listed and re-run without its corpus choice riding along
-- as editable text, and it means the filter is a plain indexed equality rather
-- than a JSONB extraction over the whole table.
--
-- The CHECK is the point of storing a TEXT column rather than a boolean. The
-- alternative encoding -- `is_prospect BOOLEAN` -- cannot be extended to a third
-- corpus without a second migration and a second nullable flag, and it makes a
-- typo'd literal silently mean "not a prospect". A CHECK turns that mistake into
-- an error at write time.
--
-- The index is separate from `match_runs_owner_created_idx` rather than a
-- replacement: that one still serves an unfiltered listing, and dropping it would
-- regress the only query the app made before panels existed.

ALTER TABLE match_runs
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'creator';

ALTER TABLE match_runs
    DROP CONSTRAINT IF EXISTS match_runs_kind_check;

ALTER TABLE match_runs
    ADD CONSTRAINT match_runs_kind_check CHECK (kind IN ('creator', 'prospect'));

-- The leading columns match how the list is filtered and paged: one owner, one
-- corpus, then newest first. `(owner_id, kind, created_at DESC, id DESC)` can
-- serve both `WHERE owner_id = ? AND kind = ?` and the same query without kind.
CREATE INDEX IF NOT EXISTS match_runs_owner_kind_created_idx
    ON match_runs (owner_id, kind, created_at DESC, id DESC);