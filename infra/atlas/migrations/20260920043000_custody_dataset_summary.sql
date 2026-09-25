-- Custody's dataset summary: one row per body of data a run produced.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists because the one question this bounded context is for cannot be
-- answered by folding. "What did this run produce" names a run, not a
-- dataset, and a fold has to know which stream to fold.

-- ---------------------------------------------------------------------------
-- proj_custody_dataset_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- Every column of the aggregate is here, which is unusual for a summary and
-- is what a context holding only a join looks like from the read side. There
-- is nothing large to leave behind: two ids and two halves of a reference.
--
-- `created_at` is the DOMAIN time the caller reported, taken from the
-- envelope's `occurred_at`, not the moment the row was written. That is what
-- makes a backfill out of a store's own records say when the data actually
-- appeared rather than when somebody ran the import.
--
-- No `updated_at`, and the absence belongs to the aggregate rather than to
-- this table. Nothing changes a dataset yet, so a second timestamp would
-- always equal the first. It arrives in the migration that adds the first
-- event which moves one.

CREATE TABLE proj_custody_dataset_summary (
    dataset_id          uuid        PRIMARY KEY,
    run_id              uuid        NOT NULL,
    external_ref_scheme text        NOT NULL,
    external_ref_value  text        NOT NULL,
    created_at          timestamptz NOT NULL
);

-- The lookup this context exists for: given a run, what came out of it.
--
-- NOT unique, and deliberately so. How many datasets a run produces is the
-- reporting side's policy rather than a rule here, and the current policy of
-- one per run is kept out of the schema on purpose: the stream id is a fresh
-- id rather than one derived from the run, so many-to-one is already the
-- shape the write side allows.
CREATE INDEX proj_custody_dataset_summary_run_idx
    ON proj_custody_dataset_summary (run_id);

-- The keyset-pagination sort key. `dataset_id` is in it rather than only in
-- the output because two datasets written at the same instant have no defined
-- order between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one. A run producing several at once makes that tie
-- the ordinary case here rather than the backfill case.
CREATE INDEX proj_custody_dataset_summary_keyset_idx
    ON proj_custody_dataset_summary (created_at DESC, dataset_id DESC);

-- No index on the external reference, because nothing asks. A producer
-- wanting to know whether it already registered an address uses its
-- idempotency key, which answers without a query. An index maintained for
-- nobody is a write cost with no reader.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_custody_dataset_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_custody_dataset_summary')
ON CONFLICT DO NOTHING;
