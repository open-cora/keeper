-- Execution's run summary: the first projection table in this schema.
--
-- One row per run, maintained by a background worker tailing the event log.
-- Derived data in the strict sense: every column can be recomputed from the
-- `events` table, so dropping the table and resetting the bookmark below to
-- zero rebuilds it exactly. The log is the record; this is a convenience.
--
-- It exists because two questions cannot be answered by folding one stream.
-- Which run carries a given external reference, and what has run lately.
-- Folding needs to know which stream to fold, and both of those are asking.

-- ---------------------------------------------------------------------------
-- proj_execution_run_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- `parameters` is deliberately absent. It is the largest thing a run carries
-- and a page of fifty rows would be mostly parameters; a caller that wants
-- them reads the run by id.
--
-- Both timestamps are the DOMAIN time a caller reported, taken from the
-- envelope's `occurred_at`, not the moment a row was written. That is what
-- makes a backfilled run say when it actually ran. It also means `updated_at`
-- can sit earlier than `created_at` when two reporters disagree about an
-- engine's clock, which is visible rather than corrected: `events.recorded_at`
-- is database-set and says truthfully when each claim arrived.
--
-- No per-ending column. `status` already names which of the three endings
-- happened, and `completed_at` / `aborted_at` / `failed_at` would be the same
-- fact spelled three more times, two of them always NULL.

CREATE TABLE proj_execution_run_summary (
    run_id              uuid        PRIMARY KEY,
    plan_id             uuid        NOT NULL,
    external_ref_scheme text        NOT NULL,
    external_ref_value  text        NOT NULL,
    status              text        NOT NULL,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL
);

-- The lookup an adapter restarting after a crash makes: it holds the engine's
-- own id for a run and nothing else.
--
-- NOT unique, and that is a decision rather than an omission. A unique index
-- would enforce uniqueness by making the projection drop the second row, so a
-- run that exists in the log would be missing from every listing. A read model
-- that undercounts is worse than one that shows the caller both records and
-- lets them see the duplicate. Nothing on the write side refuses a duplicate
-- either; see the Run state module for that gap and what would close it.
CREATE INDEX proj_execution_run_summary_external_ref_idx
    ON proj_execution_run_summary (external_ref_scheme, external_ref_value);

-- The keyset-pagination sort key. `run_id` is in it rather than only in the
-- output because two runs reported at the same instant, which a backfill
-- produces routinely, would otherwise have no defined order between them, and
-- a page boundary landing inside such a tie repeats a row or skips one.
CREATE INDEX proj_execution_run_summary_keyset_idx
    ON proj_execution_run_summary (created_at DESC, run_id DESC);

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_run_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_run_summary')
ON CONFLICT DO NOTHING;
